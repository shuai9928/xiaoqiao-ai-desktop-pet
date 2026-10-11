"""Finite CrossPet work signals from already sanitised session snapshots.

No files, clocks, transcript readers or foreground selection live here. Counts
refer to observed action rows, not actual tool calls (writers may de-duplicate).
Mac snapshots affect their character's work, never recent_turn(). Between two
updates the tracker holds the caller's latest rows (references, no copies) only
to recognise unchanged ones; it never reads text out of them later.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import hashlib
import math
import operator

CHARACTERS = frozenset(('claude', 'codex', 'glm', 'gemini', 'deepseek'))
STATUS = frozenset(('收到新任务', '本轮已结束', '本轮已中断', '等待新任务',
                    '正在处理任务', '工具调用'))
LOCAL_WINDOW, MAC_WINDOW = 20.0, 180.0
DWELL, ACTION_STUCK = 2.5, 90.0
MAX_SESSIONS, MAX_ACTIONS, MAX_EVENTS = 256, 48, 64
_STALE_AFTER = {'running': 2400.0, 'waiting': 7200.0, 'error': 3600.0}


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _character(agent):
    if not isinstance(agent, str) or len(agent) > 128:
        return None
    name = agent.lower()
    if 'claude' in name:
        return 'claude'
    if 'codex' in name:
        return 'codex'
    if 'zcode' in name:
        return 'glm'
    return None


def pose_for_tool(name):
    """Upstream's ordered name mapping, applied only to public tool labels."""
    name = name.lower() if isinstance(name, str) else ''
    if name in ('askuserquestion', 'request_user_input', 'ask_user_question', 'ask_user', 'ask_question'):
        return 'asking'
    if any(word in name for word in ('image_gen', 'imagegen', 'generate_image', 'draw', 'paint')):
        return 'drawing'
    if 'view_image' in name or name == 'find_by_name':
        return 'reading'
    if name in ('write_stdin', 'exec_command', 'shell', 'local_shell'):
        return 'running'     # Codex polling/feeding a running command, not editing a file
    if name == 'read_url_content' or name.startswith('browser'):
        return 'searching'
    for words, pose in ((('read', 'grep', 'glob', 'list', 'view', 'cat'), 'reading'),
                        (('write', 'edit', 'patch', 'replace', 'create'), 'writing'),
                        (('web', 'fetch', 'browse', 'search', 'http'), 'searching'),
                        (('agent', 'task', 'subagent', 'delegate'), 'delegating')):
        if any(word in name for word in words):
            return pose
    return 'running'


def _label_pose(label, delegated):
    if label == '问你问题':
        return 'asking'
    if label.startswith(('委派子智能体', '跟进子智能体')):
        return 'delegating'
    if label.startswith(('读网页', '搜网页')):
        return 'searching'
    for starts, pose in ((('读', '搜索'), 'reading'), (('改', '写'), 'writing'),
                         (('跑测试', '构建', '远程', '命令'), 'running')):
        if any(label == prefix or label.startswith(prefix + ' ') for prefix in starts):
            return pose
    if label == '执行工具':
        return 'running'
    if label == '等结果':
        return 'delegating' if delegated else 'running'
    if label.startswith('调用工具'):
        return pose_for_tool(label[4:].strip())
    return pose_for_tool(label)


@dataclass(frozen=True)
class _Action:
    key: tuple
    at: float | None
    pose: str
    status: str | None
    result: bool
    error: bool


@dataclass
class _Session:
    character: str
    mac: bool
    state: str
    updated: float | None
    since: float | None
    turn: float | None
    actions: tuple
    stale: bool
    observed: dict = field(default_factory=dict)
    first_seen: float | None = None
    seen_at: float | None = None
    ended: tuple | None = None       # turn signature of the last done/interrupt edge

    @property
    def turn_signature(self):
        """Which turn this snapshot shows: marker, Mac round start, and its tool rows.

        A re-stamped closing row (same turn, same rows) keeps the signature, so a
        turn is celebrated once; a new marker, a newer Mac since or new rows change it.
        """
        return (self.turn, self.since if self.mac else None,
                tuple(a.key for a in self.actions if a.status is None))

    @property
    def signature(self):
        return (self.state, self.since, self.turn,
                tuple((a.key, a.result, a.error) for a in self.actions))

    @property
    def terminal(self):
        return self.actions[0].status if self.actions and self.actions[0].status in (
            '本轮已结束', '本轮已中断') else None

    def fresh(self, now):
        if self.stale or self.updated is None or self.updated > now:
            return False
        limit = _STALE_AFTER.get(self.state)
        return limit is None or now - self.updated <= limit


def _snapshot(row, now):
    if not isinstance(row, dict):
        return None
    sid, agent = row.get('id'), row.get('agent')
    c = _character(agent)
    if c is None or not isinstance(sid, str) or not 0 < len(sid) <= 256:
        return None
    raw = row.get('actions')
    raw = raw[:MAX_ACTIONS] if isinstance(raw, (tuple, list)) else ()
    turn, rows, delegated = None, [], False
    for value in raw:
        if isinstance(value, dict) and value.get('turn'):
            turn = _number(value.get('t'))
            if turn is None or turn > now:
                return None  # corrupt/future round must not rank or borrow old history
            break
        label = value if isinstance(value, str) else value.get('a') if isinstance(value, dict) else None
        if not isinstance(label, str) or not label or len(label) > 512:
            continue
        at = _number(value.get('t')) if isinstance(value, dict) else None
        if isinstance(value, dict) and 't' in value and (at is None or at > now):
            continue                 # corrupt/future action evidence is not an AI event
        result = bool(value.get('r')) if isinstance(value, dict) else False
        error = (type(value.get('err')) in (int, bool) and value.get('err') == 1) if isinstance(value, dict) else False
        status = label if label in STATUS else None
        delegated |= label.startswith(('委派子智能体', '跟进子智能体'))
        # Retain only a bounded digest and finite classification, no label/result text.
        identity = (at, hashlib.sha256(label.encode('utf-8', errors='replace')).digest()[:16])
        rows.append((identity, at, label, status, result, error))
    acts = tuple(_Action(key, at, _label_pose(label, delegated), status, result, err)
                 for key, at, label, status, result, err in rows)
    state = row.get('state')
    if not isinstance(state, str) or state not in ('running', 'waiting', 'error', 'done', 'idle'):
        return None  # unknown state is not evidence for an idle/interruption edge
    since = _number(row.get('since'))
    if row.get('since') is not None and (since is None or since > now):
        return None  # a malformed start clock is not real work evidence either
    sid = hashlib.sha256(sid.encode('utf-8', errors='replace')).digest()[:16]
    return sid, _Session(c, agent.lower().startswith('mac-'), state,
                         _number(row.get('updated')), since,
                         turn, acts, bool(row.get('stale')))


_ROW_FIELDS = ('id', 'agent', 'actions', 'state', 'since', 'updated', 'stale')   # all _snapshot reads


def _horizon(row):
    """The latest clock _snapshot may compare with now: since and every row stamp."""
    raw = row.get('actions')
    raw = raw[:MAX_ACTIONS] if isinstance(raw, (tuple, list)) else ()
    stamps = [_number(v.get('t')) for v in raw if isinstance(v, dict)] + [_number(row.get('since'))]
    return max((s for s in stamps if s is not None), default=-math.inf)


class _ParseMemo(dict):
    """id(row) -> (row, its _ROW_FIELDS values, _snapshot parts or None).

    The row is the caller's own object, kept only until the next update so its id
    cannot be reused meanwhile; the repr stays as opaque as the rest of the state.
    """
    __slots__ = ()

    def __repr__(self):
        return f'<{len(self)} parsed rows>'


class WorkTracker:
    def __init__(self):
        self._ready = False
        self._sessions = OrderedDict()
        self._current = {}
        self._events = {c: deque(maxlen=MAX_EVENTS) for c in CHARACTERS}
        self._activity = {}
        self._turns = deque(maxlen=MAX_EVENTS)
        self._now = None
        self._parsed = _ParseMemo()

    def _emit(self, rec, kind, now, *, n_tools=None):
        event = dict(kind=kind, at=now, source='mac' if rec.mac else 'local')
        if kind == 'done':
            event['n_tools'] = n_tools
        self._events[rec.character].append(event)
        if kind == 'turn' and not rec.mac:
            self._turns.append((now, rec.character))

    @staticmethod
    def _evidence(rec, stamp, now):
        # Mac observations arrive in coarse polling batches; no local follow hint.
        return rec.mac or (stamp is not None and 0 <= now - stamp <= LOCAL_WINDOW)

    @staticmethod
    def _observed_results(rec, old, now):
        """Bounded evidence for writers that attach a result without a new stamp.

        Only a previously observed action changing result/error flags qualifies;
        discovering an old row or returning after a long gap is not a new error.
        """
        if (old is None or not old.fresh(now) or old.turn != rec.turn
                or old.seen_at is None or not 0 <= now - old.seen_at <= (
                    MAC_WINDOW if rec.mac else LOCAL_WINDOW)):
            return set()
        previous = {a.key: a for a in old.actions}
        return {a.key for a in rec.actions if a.key in previous and (
            (a.result and not previous[a.key].result)
            or (a.error and not previous[a.key].error))}

    @staticmethod
    def _action_stamp(rec, action):
        return action.at if action.at is not None else rec.observed[action.key]

    @classmethod
    def _latest_action(cls, rec):
        actions = [a for a in rec.actions if a.status is None]
        return max(actions, key=lambda a: cls._action_stamp(rec, a)) if actions else None

    @classmethod
    def _work_stamp(cls, rec):
        # Updated may be a synchronisation heartbeat. It can keep a session
        # fresh, but must not let an older remote action steal the active pose.
        action = cls._latest_action(rec)
        if action is not None:
            stamp = cls._action_stamp(rec, action)
            return max(stamp, rec.turn) if rec.turn is not None else stamp
        return (rec.turn if rec.turn is not None else
                rec.since if rec.since is not None else rec.first_seen)

    def _parse(self, row, now, memo):
        """_snapshot(row, now), reusing the last update's parse of this very row object.

        The scan hands out the same dict for an unchanged session file and never
        edits it; its top-level values are rechecked by identity anyway (the action
        list itself must not be edited in place). A parse is kept only when no clock
        in the row is ahead of now: every '> now' check then answers the same for
        any later now, and a backwards clock resets the tracker, memo included.
        The _Session is always new, since update() writes to it.
        """
        if not isinstance(row, dict):
            return _snapshot(row, now)
        values = tuple(map(row.get, _ROW_FIELDS))
        hit = memo.get(id(row))
        if hit is not None and hit[0] is row and all(map(operator.is_, values, hit[1])):
            self._parsed[id(row)] = hit
            return None if hit[2] is None else (hit[2][0], _Session(*hit[2][1]))
        parsed = _snapshot(row, now)
        if _horizon(row) <= now:
            s = parsed and parsed[1]
            self._parsed[id(row)] = (row, values, parsed and (parsed[0], (
                s.character, s.mac, s.state, s.updated, s.since, s.turn, s.actions, s.stale)))
        return parsed

    def update(self, sessions, now):
        if _number(now) is None:
            return
        if self._now is not None and now < self._now:
            # A wall-clock correction establishes a new baseline, never replays edges.
            self.__init__()
        self._now = now
        baseline, self._ready = not self._ready, True
        rows = sessions[:MAX_SESSIONS] if isinstance(sessions, (list, tuple)) else ()
        current, memo, self._parsed = {}, self._parsed, _ParseMemo()   # only this input's rows stay
        for row in rows:
            parsed = self._parse(row, now, memo)
            if parsed is None:
                continue
            sid, rec = parsed
            if sid in current:
                continue
            old = self._sessions.get(sid)
            if old is not None and (old.character != rec.character or old.mac != rec.mac):
                old = None
            rec.observed = {a.key: old.observed.get(a.key, now) if old else now for a in rec.actions}
            rec.first_seen = old.first_seen if old else now
            rec.seen_at = now
            rec.ended = old.ended if old else None
            result_changes = self._observed_results(rec, old, now)
            current[sid] = rec
            changed = old is None or old.signature != rec.signature
            if rec.fresh(now) and changed:
                if baseline:
                    stamp = max((a.at for a in rec.actions if a.at is not None and a.at <= now), default=rec.updated)
                    if stamp is not None:
                        self._activity[rec.character] = max(self._activity.get(rec.character, 0), stamp)
                else:
                    latest = rec.updated
                    if self._evidence(rec, latest, now) or result_changes:
                        self._activity[rec.character] = now
                        self._emit(rec, 'activity', now)
            if not baseline and rec.fresh(now):
                marker_changed = rec.turn is not None and (old is None or old.turn is None or rec.turn > old.turn)
                # A whole turn can start and finish between two scans: a ZCode
                # marker or a Mac round (since) newer than the last one counts.
                newer_round = rec.mac and rec.since is not None and old is not None and (
                    old.since is None or rec.since > old.since)
                legacy_turn = rec.turn is None and rec.state == 'running' and (
                    old is None or old.state in ('idle', 'done') or newer_round)
                if (marker_changed or legacy_turn) and self._evidence(rec, rec.turn if marker_changed else rec.updated, now):
                    self._emit(rec, 'turn', now)
                previous = {a.key: a for a in old.actions} if old else {}
                for action in reversed(rec.actions):
                    before = previous.get(action.key)
                    # A fresh writer stamp can identify a delayed result on an
                    # already known action. An unseen historical row needs its
                    # own action stamp; a heartbeat alone is not error evidence.
                    stamp = rec.updated if before else action.at
                    if (action.error and not (before and before.error)
                            and (self._evidence(rec, stamp, now) or action.key in result_changes)):
                        self._emit(rec, 'oops', now)
                if rec.mac and rec.state == 'error' and (old is None or old.state != 'error'):
                    self._emit(rec, 'oops', now)
                done = rec.state == 'done' and (old is None or old.state != 'done'
                                                or marker_changed or newer_round)
                terminal_new = bool(rec.terminal and (old is None or rec.terminal != old.terminal or
                    rec.actions[0].key != old.actions[0].key))
                done |= terminal_new and rec.terminal == '本轮已结束'
                interrupted = (terminal_new and rec.terminal == '本轮已中断') or (
                    old is not None and old.fresh(now) and old.state in ('running', 'waiting')
                    and rec.state == 'idle' and rec.terminal != '本轮已结束') or (
                    marker_changed and rec.state == 'idle' and rec.terminal != '本轮已结束')
                stamp = rec.actions[0].at if terminal_new and rec.actions[0].at is not None else rec.updated
                ended = rec.turn_signature
                if (done or interrupted) and ended == rec.ended:
                    pass        # the same turn re-stamped its closing row: already shown
                elif done and self._evidence(rec, stamp, now):
                    rec.ended = ended
                    self._emit(rec, 'done', now, n_tools=sum(a.status is None for a in rec.actions))
                elif interrupted and self._evidence(rec, stamp, now):
                    rec.ended = ended
                    self._emit(rec, 'interrupt', now)
            # An offline (stale) snapshot must not become the comparison baseline:
            # when sync returns, the same round would replay its turn and error.
            self._sessions[sid] = rec if rec.fresh(now) or old is None else old
            self._sessions.move_to_end(sid)
        self._current = current
        while len(self._sessions) > MAX_SESSIONS:
            self._sessions.popitem(last=False)
        for c, events in self._events.items():
            self._events[c] = deque((e for e in events if now - e['at'] <= (
                MAC_WINDOW if e['source'] == 'mac' else LOCAL_WINDOW)), maxlen=MAX_EVENTS)
        while self._turns and now - self._turns[0][0] > MAC_WINDOW:
            self._turns.popleft()

    def level(self, character, now):
        if not isinstance(character, str) or character not in CHARACTERS or _number(now) is None:
            return None
        rows = [r for r in self._current.values() if r.character == character and r.fresh(now)]
        if any(r.state == 'waiting' for r in rows):
            return 'asking'
        running = [r for r in rows if r.state == 'running' and r.terminal is None]
        if not running:
            return None
        rec = max(running, key=self._work_stamp)
        action = self._latest_action(rec)
        if action is None:
            return 'thinking'
        first = rec.observed[action.key]
        stamp = action.at if action.at is not None else first
        if stamp > now or now - stamp > ACTION_STUCK:
            return 'thinking'
        if action.result and now - first >= DWELL:
            return 'thinking'
        return action.pose

    def drain(self, character):
        events = self._events.get(character) if isinstance(character, str) else None
        if events is None:
            return ()
        result = tuple(dict(e) for e in events)
        events.clear()
        return result

    def last_activity(self, character):
        return self._activity.get(character) if isinstance(character, str) else None

    def recent_turn(self, now, window=30):
        """Local evidence query only. The host must not use it to follow background AI."""
        if _number(now) is None or _number(window) is None:
            return None
        return next((c for stamp, c in reversed(self._turns) if 0 <= now - stamp <= window), None)
