"""I-52: WorkTracker reuses the parse of a row object it saw on the last update.

The scan now hands out the very same dict for an unchanged session file. The memo
must be invisible: every event, level and stored session equals a tracker that
parses every row afresh. Synthetic rows only, no session files or Pet.
"""
import copy
import random
import unittest
from unittest.mock import patch

import ai_work
from ai_work import CHARACTERS, MAX_SESSIONS, WorkTracker


class Fresh(WorkTracker):
    """The tracker as it was: every row parsed afresh (and fed deep copies, so no
    identity is ever shared even if this override stopped being called)."""

    def _parse(self, row, now, memo):
        return ai_work._snapshot(row, now)

    def update(self, sessions, now):
        super().update(copy.deepcopy(sessions), now)


def session(state='running', *, sid='s', agent='native-claude', updated=100, actions=(), since=100, **extra):
    return dict(id=sid, agent=agent, state=state, updated=updated, since=since, actions=list(actions), **extra)


def act(label, t=100, r='', err=0):
    return dict(a=label, t=t, r=r, err=err)


def state(t):
    """Everything the tracker keeps that a later update or query can read."""
    rec = lambda s: (s.character, s.mac, s.state, s.updated, s.since, s.turn, s.actions, s.stale,
                     s.observed, s.first_seen, s.seen_at, s.ended)
    return repr(([(k, rec(s)) for k, s in t._sessions.items()], [(k, rec(s)) for k, s in t._current.items()],
                 t._activity, sorted((c, list(q)) for c, q in t._events.items()), list(t._turns), t._now, t._ready))


def answers(t, now):
    """Every public query, then the drained events (drain empties the queues)."""
    out = []
    for when in (now, now + 1, now + 3, now + 100):
        out.append([t.level(c, when) for c in sorted(CHARACTERS)])
        out.append([t.recent_turn(when), t.recent_turn(when, 5)])
    out.append([t.last_activity(c) for c in sorted(CHARACTERS)])
    out.append([t.drain(c) for c in sorted(CHARACTERS)])
    return repr(out)


def counted(t, rows, now):
    """t.update(rows, now), returning how many rows it really parsed."""
    calls, real = [], ai_work._snapshot
    with patch.object(ai_work, '_snapshot', side_effect=lambda row, at: calls.append(1) or real(row, at)):
        t.update(rows, now)
    return len(calls)


LABELS = ('读 a.py', '改 b', '写 c', '跑测试 unit', '构建 x', '问你问题', '委派子智能体 · y', '跟进子智能体',
          '等结果', '调用工具 image_gen', '执行工具', '读网页', '搜索 z', 'web_search', 'apply_patch', 'exec_command',
          '收到新任务', '本轮已结束', '本轮已中断', '等待新任务', '工具调用', '', 'x' * 600)
AGENTS = ('native-claude', 'native-codex', 'zcode', 'mac-claude', 'mac-codex', 'Mac-Claude-w')


class Fuzz:
    """Scan-like session lists: unchanged files keep their dict, changed ones get a new dict."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.now = 1000.0
        self.rows = {}
        self.sids = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', '', 'x' * 300, 5]

    def stamp(self):
        rng, now = self.rng, self.now
        r = rng.random()
        if r < .6:
            return now - rng.choice((0, 0, .5, 1, 2, 3, 15, 19.9, 20, 21, 89, 100, 3000, 9000))
        if r < .8:
            return now + rng.choice((.5, 1, 2, 4, 30))            # ahead of the clock
        return rng.choice(('x', None, float('nan'), float('inf'), -1, True, 5, int(now) - 1))

    def action(self):
        rng = self.rng
        r = rng.random()
        if r < .08:
            return rng.choice(LABELS + (42, None))                 # legacy string row or junk
        if r < .16:
            marker = {'turn': rng.choice((1, True, 0, 'yes')), 't': self.stamp()}
            if rng.random() < .1:
                del marker['t']
            return marker
        a = {'a': rng.choice(LABELS + (None, 3))}
        if rng.random() < .85:
            a['t'] = self.stamp()
        if rng.random() < .5:
            a['r'] = rng.choice(('', 'ok', None, 0, 1, '返回'))
        if rng.random() < .3:
            a['err'] = rng.choice((0, 1, True, False, 1.0, '1'))
        return a

    def make(self, sid, prev=None):
        rng = self.rng
        acts = [self.action() for _ in range(rng.randrange(0, 5))]
        if prev is not None and isinstance(prev.get('actions'), list) and rng.random() < .75:
            acts += prev['actions']          # writers prepend; older item dicts are shared
        agent = prev['agent'] if prev is not None and rng.random() < .9 else rng.choice(AGENTS + ('random', 7))
        row = dict(id=sid, agent=agent, updated=self.stamp(), actions=acts[:60],
                   state=rng.choice(('running', 'running', 'waiting', 'done', 'done', 'idle', 'error', 'bogus', None)))
        if rng.random() < .8:
            row['since'] = self.stamp()
        if rng.random() < .25:
            row['stale'] = rng.choice((True, False, 1, 0))
        if rng.random() < .04:
            row['actions'] = rng.choice((None, 'x', tuple(acts)))
        return row

    def replace_field(self, row):
        rng = self.rng
        key = rng.choice(('updated', 'stale', 'state', 'since', 'agent', 'actions'))
        if key in ('updated', 'since'):
            row[key] = self.stamp()
        elif key == 'stale':
            row[key] = not row.get('stale')
        elif key == 'state':
            row[key] = rng.choice(('running', 'done', 'idle'))
        elif key == 'agent':
            row[key] = rng.choice(AGENTS)
        else:
            row[key] = [self.action()] + list(row.get('actions') or ())

    def step(self):
        """Advance the clock and the files; returns (sessions, now)."""
        rng = self.rng
        r = rng.random()
        if r < .04:
            self.now -= rng.choice((.5, 30, 500))                  # wall-clock correction
        elif r < .07:
            return self.batch(), rng.choice((float('nan'), True, None, -1, float('inf')))
        else:
            self.now += rng.choice((0, .5, 1, 2, 2, 2, 2, 5, 19, 21, 90, 200))
        for sid in self.sids:
            x = rng.random()
            if sid not in self.rows:
                if x < .4:
                    self.rows[sid] = self.make(sid)
            elif x < .04:
                del self.rows[sid]
            elif x < .3:
                self.rows[sid] = self.make(sid, self.rows[sid])
            elif x < .34:
                self.replace_field(self.rows[sid])                 # a field replaced on the same dict
        return self.batch(), self.now

    def batch(self):
        rng = self.rng
        rows = list(self.rows.values())
        if rng.random() < .3:
            rng.shuffle(rows)
        if rows and rng.random() < .1:
            rows.insert(rng.randrange(len(rows) + 1), rng.choice(rows))   # the same object twice
        if rng.random() < .08:
            rows.insert(rng.randrange(len(rows) + 1), rng.choice((None, 'row', 3, [], {})))
        r = rng.random()
        return tuple(rows) if r < .05 else rng.choice((None, 'x', {})) if r < .07 else rows


class MemoEquivalenceTests(unittest.TestCase):
    def test_randomised_scans_match_a_tracker_that_parses_everything(self):
        dict_rows = parsed = 0
        for seed in range(4):
            fuzz, memo, fresh = Fuzz(seed), WorkTracker(), Fresh()
            for step in range(500):
                rows, now = fuzz.step()
                calls = counted(memo, rows, now)
                fresh.update(rows, now)
                if isinstance(rows, (list, tuple)) and ai_work._number(now) is not None:
                    dict_rows += sum(type(r) is dict for r in rows[:MAX_SESSIONS])
                    parsed += calls
                with self.subTest(seed=seed, step=step):
                    self.assertEqual(state(memo), state(fresh))
                    self.assertEqual(answers(memo, fuzz.now), answers(fresh, fuzz.now))
        self.assertLess(parsed, .6 * dict_rows)                    # the memo really was exercised

    def test_unchanged_row_objects_are_not_parsed_again(self):
        rows = [session(sid='a', actions=[act('读 x', 99)]), session('done', sid='b', agent='mac-codex', since=90),
                session(sid='c', agent='nobody')]
        memo, fresh = WorkTracker(), Fresh()
        self.assertEqual(counted(memo, rows, 100), 3)
        fresh.update(rows, 100)
        self.assertEqual(counted(memo, list(rows), 102), 0)
        fresh.update(list(rows), 102)
        self.assertEqual(state(memo), state(fresh))
        changed = [rows[0], dict(rows[1], state='running', updated=103), rows[2]]
        self.assertEqual(counted(memo, changed, 104), 1)
        fresh.update(changed, 104)
        self.assertEqual(state(memo), state(fresh))
        self.assertEqual(answers(memo, 104), answers(fresh, 104))

    def test_a_parse_is_reused_only_once_the_clock_passed_every_stamp(self):
        rows = [session(sid='a', updated=100, actions=[act('写 later', 105), act('读 now', 100)])]
        memo, fresh = WorkTracker(), Fresh()
        for now, parses in ((100, 1), (103, 1), (105, 1), (106, 0), (130, 0)):
            with self.subTest(now=now):
                self.assertEqual(counted(memo, rows, now), parses)
                fresh.update(rows, now)
                self.assertEqual(state(memo), state(fresh))
                self.assertEqual(answers(memo, now), answers(fresh, now))

    def test_a_future_turn_or_start_is_not_remembered_as_a_rejection(self):
        for row in (session(sid='a', actions=[act('写 x', 100), {'turn': 1, 't': 104}]),
                    session(sid='a', since=104, actions=[act('写 x', 100)])):
            with self.subTest(row=row):
                memo, fresh = WorkTracker(), Fresh()
                for now in (101, 103, 104, 105):
                    memo.update([row], now)
                    fresh.update([row], now)
                    self.assertEqual(answers(memo, now), answers(fresh, now))
                    self.assertEqual(state(memo), state(fresh))
                self.assertEqual(memo.level('claude', 105), 'writing')

    def test_a_backwards_clock_forgets_every_parse(self):
        rows = [session(sid='a', actions=[act('读 x', 40)], updated=40, since=40)]
        memo, fresh = WorkTracker(), Fresh()
        for now, parses in ((100, 1), (101, 0), (50, 1), (51, 0), (45, 1)):
            with self.subTest(now=now):
                self.assertEqual(counted(memo, rows, now), parses)
                fresh.update(rows, now)
                self.assertEqual(state(memo), state(fresh))
                self.assertEqual(answers(memo, now), answers(fresh, now))

    def test_a_field_replaced_on_the_same_dict_is_parsed_again(self):
        row = session('waiting', sid='m', agent='mac-claude', updated=103)
        local = session(sid='l', updated=102, actions=[act('写 local', 102)])
        memo, fresh = WorkTracker(), Fresh()
        memo.update([local, row], 103)
        fresh.update([local, row], 103)
        self.assertEqual(memo.level('claude', 103), 'asking')
        for key, value in (('updated', 103.0), ('stale', True), ('stale', 1), ('updated', 104.0), ('state', 'done'),
                           ('agent', 'mac-codex'), ('actions', [act('读 again', 104)]), ('since', 104), ('id', 'n')):
            with self.subTest(key=key):
                row[key] = value
                self.assertEqual(counted(memo, [local, row], 104), 1)
                fresh.update([local, row], 104)
                self.assertEqual(state(memo), state(fresh))
                self.assertEqual(answers(memo, 104), answers(fresh, 104))

    def test_dict_subclass_rows_are_remembered_too(self):
        class Row(dict):
            pass
        rows = [Row(session(sid='a', actions=[act('读 x', 99)])), Row(session('done', sid='b', since=None))]
        memo, fresh = WorkTracker(), Fresh()
        for now, parses in ((100, 2), (102, 0)):
            with self.subTest(now=now):
                self.assertEqual(counted(memo, rows, now), parses)
                fresh.update(rows, now)
                self.assertEqual(state(memo), state(fresh))
                self.assertEqual(answers(memo, now), answers(fresh, now))

    def test_sessions_are_rebuilt_so_earlier_records_never_change(self):
        row = session(sid='a', actions=[act('读 x', 99)])
        t = WorkTracker()
        t.update([row], 100)
        first = next(iter(t._current.values()))
        before = (dict(first.observed), first.first_seen, first.seen_at, first.ended)
        t.update([row], 102)
        second = next(iter(t._current.values()))
        self.assertIsNot(second, first)
        self.assertIs(second.actions, first.actions)               # immutable parts may be shared
        self.assertEqual((first.observed, first.first_seen, first.seen_at, first.ended), before)
        self.assertEqual(second.seen_at, 102)

    def test_only_the_latest_rows_are_held_and_never_shown(self):
        secret = 'not-to-be-kept'
        a = session(sid=secret, actions=[act('写 ' + secret, 99, secret)])
        b = session(sid='b')
        t = WorkTracker()
        t.update([a, b, None, 'x'], 100)
        self.assertEqual({id(entry[0]) for entry in t._parsed.values()}, {id(a), id(b)})
        t.update([b], 101)
        self.assertEqual([entry[0] for entry in t._parsed.values()], [b])
        self.assertNotIn(secret, repr(t.__dict__))
        t.update([], 102)
        self.assertEqual(len(t._parsed), 0)
        t.update([session('done', sid=str(n), updated=101) for n in range(MAX_SESSIONS + 20)], 103)
        self.assertEqual(len(t._parsed), MAX_SESSIONS)

    def test_rows_with_unusable_clocks_or_types_still_match(self):
        rows = [session(sid='a', actions=[act('读 x', float('nan')), act('写 y', 'soon'), act('改 z', 100)]),
                session(sid='b', since=float('inf')), session(sid='c', updated=True, actions=['读 legacy']),
                dict(session(sid='d'), actions=None), dict(session(sid='e'), stale=[]), None, 4, ['a']]
        memo, fresh = WorkTracker(), Fresh()
        for now in (100, 101, 160):
            memo.update(rows, now)
            fresh.update(rows, now)
            self.assertEqual(state(memo), state(fresh))
            self.assertEqual(answers(memo, now), answers(fresh, now))


if __name__ == '__main__':
    unittest.main()
