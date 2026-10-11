"""CrossPet's visual director, with injected resources, randomness and time.

No windows, images, user data, model calls or movement/physics live here. The
host consumes View.say once and persists the supplied small memory dictionary.
All times are seconds; greeting dates use the user's China Standard Time.
"""
from dataclasses import dataclass
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import math
import re

DWELL = 2.5
SLEEP_AFTER = 600.0
WORK_LINE_GAP = 8.0
GREET_COOLDOWN = 1800.0
FADE_SECONDS = .35
TRANSIENT = {'happy': 5.0, 'proud': 6.0, 'oops': 4.0, 'surprised': 3.0,
             'pat': 4.0, 'hum': 4.0, 'stretch': 3.2, 'yawn': 3.0}
MOTION = dict(idle='bob', listening='hop', thinking='rock', reading='rock', writing='bob',
              running='quick', searching='sway', delegating='sway', happy='jump', proud='hop',
              oops='shake', surprised='jolt', pat='sway', sleeping='slow', tired='slow',
              hum='sway', stretch='squish', yawn='squish', drawing='rock', pop='hop',
              pretend='bob', caught='shake', bye='dash', deepthink='slow', swim='sway',
              eat='bob', slack='slow', pout='jolt', reset='jump', feast='bob', compact='squish',
              sorry='slow', clawd='sway', float='float', asking='hop', update='gift',
              greet_morning='hop', greet_noon='bob', greet_afternoon='sway', greet_evening='sway',
              greet_night='slow', greet_dawn='slow', fest_halloween='gift', fest_christmas='gift',
              fest_newyear='jump', fest_spring='gift', fest_lantern='gift', fest_dragonboat='gift',
              fest_midautumn='gift', fest_national='hop')
LOCAL_LINES = {'idle': ('……', '在呢'), 'pat': ('嘿嘿', '（蹭蹭）'), 'surprised': ('诶？！',),
               'hum': ('♪～',), 'stretch': ('伸个懒腰～',), 'yawn': ('哈啊……',),
               'sleeping': ('zZz',), 'tired': ('有点累了…',)}
LUNAR = {
    2026: ('02-17', '03-03', '06-19', '09-25'), 2027: ('02-06', '02-20', '06-09', '09-15'),
    2028: ('01-26', '02-09', '05-28', '10-03'), 2029: ('02-13', '02-27', '06-16', '09-22'),
    2030: ('02-03', '02-17', '06-05', '09-12'), 2031: ('01-23', '02-06', '06-24', '10-01'),
    2032: ('02-11', '02-25', '06-12', '09-19'), 2033: ('01-31', '02-14', '06-01', '09-08'),
    2034: ('02-19', '03-05', '06-20', '09-27'), 2035: ('02-08', '02-22', '06-10', '09-16'),
    2036: ('01-28', '02-11', '05-30', '10-04'),
}
_POSE = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
_CST = timezone(timedelta(hours=8))
WORK_POSES = frozenset(('listening', 'thinking', 'reading', 'writing', 'running',
                        'searching', 'delegating', 'drawing', 'asking'))


def time_slot(date):
    h = date.hour
    return ('night' if h >= 23 or h < 2 else 'dawn' if h < 5 else 'morning' if h < 11
            else 'noon' if h < 14 else 'afternoon' if h < 18 else 'evening')


def festival(date):
    md = date.strftime('%m-%d')
    lunar = LUNAR.get(date.year)
    if lunar:
        for index, name in ((1, 'lantern'), (2, 'dragonboat'), (3, 'midautumn')):
            if md == lunar[index]:
                return name
    if md == '10-31':
        return 'halloween'
    if md in ('12-24', '12-25'):
        return 'christmas'
    if md == '01-01':
        return 'newyear'
    if lunar:
        spring = datetime.strptime(f'{date.year}-{lunar[0]}', '%Y-%m-%d').date()
        if 0 <= (date.date() - spring).days < 7:
            return 'spring'
    return 'national' if '10-01' <= md <= '10-07' else None


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class View:
    character: str | None
    pose: str
    art_pose: str
    frame_index: int
    blink: bool
    motion: str | None
    motion_t: float
    fade_from: tuple | None
    fade_alpha: float
    fx: str | None
    fx_age: float
    say: str
    egg: dict | None


class AiPetDirector:
    """One bounded visual timeline; methods never invoke host behaviour.

    on_work events use kind (also accepts type) in turn/oops/done/interrupt/
    activity. Only done uses n_tools. Unknown fields are neither copied nor
    stored. A repeated level without events is polling, not new activity.
    """
    def __init__(self, catalog, *, rng, memory):
        self.catalog, self.rng = catalog, rng
        self.memory = memory if isinstance(memory, dict) else {}
        self.character = None
        self._clock = 0.0
        self._render_id, self._pose, self._index = None, 'idle', 0
        self._pose_since = self._shown_at = self._last_active = 0.0
        self._level = self._pending = self._return = None
        self._until = self._dev_until = self._farewell_until = None
        self._manual_rest = self._reduced = self._emitted = False
        self._say = ''
        self._last_work_line = -math.inf
        self._trouble = None
        self._low = False
        self._egg = None
        self._next_idle = self._next_greet = self._next_egg = self._next_variant = math.inf
        self._next_blink, self._blink_until = math.inf, 0.0
        self._fade_from, self._fade_started = None, 0.0
        self._motion, self._motion_since, self._motion_tick = None, 0.0, -math.inf
        self._greet_requested = False
        self._context = (False, False)
        self._context_owned = False

    def _now(self, now):
        if not _finite(now):
            return self._clock
        self._clock = max(self._clock, float(now))
        return self._clock

    def _pick(self, values):
        return self.rng.choice(tuple(values)) if values else None

    def _behavior(self, character=None):
        return self.catalog.behavior(character or self._render_id or self.character) or {}

    def _line(self, key, character=None):
        lines = self.catalog.lines(character or self._render_id or self.character, key)
        value = self._pick(lines or LOCAL_LINES.get(key, ()))
        return value if isinstance(value, str) and len(value) <= 40 and '\n' not in value else ''

    def _rest(self):
        return 'tired' if self._low else 'idle'

    def _duration(self, pose):
        if pose.startswith('greet_'):
            return 5.5
        if pose.startswith('fest_'):
            return 6.5
        if pose in (self._behavior().get('idle_actions') or ()):
            return 4.0
        return TRANSIENT.get(pose)

    def _ref(self, now):
        if self._render_id is None:
            return None
        return (self._render_id, self.catalog.resolve(self._render_id, self._pose),
                self._index, now < self._blink_until)

    def _show(self, pose, now, *, urgent=False, duration=None, return_to=None,
              work=False, speak=True, character=None):
        if not isinstance(pose, str) or not _POSE.fullmatch(pose):
            return False
        if not urgent and self._emitted and now < self._shown_at + DWELL:
            self._pending = (pose, self._shown_at + DWELL, duration, return_to, work, speak)
            return False
        character = character or (self._egg['id'] if self._egg else self.character)
        changed = (character, pose) != (self._render_id, self._pose)
        self._pending = None
        self._shown_at = now
        if changed:
            self._fade_from, self._fade_started = self._ref(now), now
            self._render_id, self._pose, self._pose_since = character, pose, now
            count = self.catalog.frame_count(character, pose)
            self._index = self._pick(range(max(1, count))) or 0
            self._next_variant = now + self.rng.uniform(8.0, 10.0)
            self._next_blink, self._blink_until = now + self.rng.uniform(3.0, 6.5), 0.0
        if speak and (changed or (urgent and not work)) and (not work or now - self._last_work_line >= WORK_LINE_GAP):
            self._say = self._line(pose, character)
            if work and self._say:
                self._last_work_line = now
        duration = self._duration(pose) if duration is None else duration
        self._until = now + duration if duration is not None else None
        self._return = return_to
        return changed

    def set_character(self, character, now, reason='entered'):
        now = self._now(now)
        pack = self.catalog.get(character)
        if pack is None or not pack.available or getattr(pack, 'is_egg', False):
            return False
        if character == self.character:
            return False
        old = self._ref(now)
        self.character = character
        self._level = self._pending = self._return = self._until = None
        self._dev_until = self._farewell_until = self._egg = self._trouble = None
        self._manual_rest = False
        self._say = ''
        self._last_work_line = -math.inf
        self._last_active = now
        self._next_idle, self._next_greet, self._next_egg = now + 20, now + 60, now + 60
        quota = self.memory.get('quota')
        saved = quota.get(character) if isinstance(quota, Mapping) else None
        self._low = character in ('claude', 'codex') and isinstance(saved, Mapping) and saved.get('low') is True
        self._emitted = False
        self._show(self._rest(), now, urgent=True, speak=False)
        self._fade_from = old
        self._greet_requested = reason in ('foreground', 'follow')
        self._context = (False, False)
        self._context_owned = False
        return True

    def entry_poses(self, character, now, level=None, *, chat_open=False, model_thinking=False):
        """Poses a foreground switch to character shows first, likeliest first; read-only.

        set_character's rest (tired from the saved quota; Claude/Codex get both,
        as the host's quota sync right after may flip it), on_work(level)'s work
        pose, else the first tick's chat pose, and its greeting (festival or
        time slot). Never asleep, an idle action or an egg: the switch marks her
        active and defers those. The host scales these off the frame loop while
        the switch is still pending.
        """
        pack = self.catalog.get(character)
        if pack is None or not pack.available or getattr(pack, 'is_egg', False):
            return ()
        quota = self.memory.get('quota')
        saved = quota.get(character) if isinstance(quota, Mapping) else None
        low = isinstance(saved, Mapping) and saved.get('low') is True
        poses = (['tired', 'idle'] if low else ['idle', 'tired']) if character in ('claude', 'codex') else ['idle']
        if isinstance(level, str) and level in WORK_POSES:
            poses.append(level)
        elif model_thinking or chat_open:
            poses.append('thinking' if model_thinking else 'listening')
        try:
            date = datetime.fromtimestamp(now, _CST)
        except (ValueError, OverflowError, OSError, TypeError):
            return tuple(poses)
        fest = festival(date)
        poses += [p for p in ('fest_' + fest if fest else None, 'greet_' + time_slot(date))
                  if p and self.catalog.has_pose(character, p)]
        return tuple(poses)

    def on_work(self, level, events, now):
        now = self._now(now)
        if self.character is None:
            return
        level = level if isinstance(level, str) and level in WORK_POSES else None
        changed = level != self._level
        self._level = level
        edges = [event for event in (events if isinstance(events, (tuple, list)) else ())
                 if isinstance(event, dict) and event.get('kind', event.get('type'))
                 in ('turn', 'oops', 'done', 'interrupt', 'activity')][:64]
        active = bool(edges) or (changed and level is not None)
        if active:
            self._last_active = now
        if self._farewell_until is not None or self._manual_rest or self._dev_until is not None:
            return
        if changed or edges:
            self._context_owned = False
        if self._egg and (level is not None or any(e.get('kind', e.get('type')) != 'activity' for e in edges)):
            self._end_egg(now)
        if changed or (active and self._pose == 'sleeping'):
            if self._until is None or level is not None:
                self._show(level or self._rest(), now, work=True, urgent=self._pose == 'sleeping')
        for event in edges:
            kind = event.get('kind', event.get('type'))
            if kind == 'turn':
                corrected = self._behavior().get('corrected_pose')
                if (self._trouble is not None and now - self._trouble <= 180
                        and isinstance(corrected, str) and self.catalog.has_pose(self.character, corrected)):
                    self._trouble = None
                    self._show(corrected, now, urgent=True, duration=3.0, return_to='thinking')
                else:
                    self._show('listening', now, urgent=True, duration=DWELL, return_to='thinking', work=True)
            elif kind == 'oops':
                self._trouble = now
                self._show('oops', now, urgent=True)
            elif kind == 'interrupt':
                self._trouble = now
                self._show('surprised', now, urgent=True)
            elif kind == 'done':
                self._trouble = None
                count = event.get('n_tools', 0)
                self._show('proud' if type(count) is int and count >= 8 else 'happy', now, urgent=True)

    def set_resting(self, resting, now):
        now = self._now(now)
        if type(resting) is not bool or self.character is None or self._farewell_until is not None:
            return False
        was_sleeping = self._manual_rest or self._pose == 'sleeping'
        self._manual_rest = resting
        self._dev_until = self._pending = None
        self._last_active = now
        if self._egg:
            self._end_egg(now)
        if resting:
            self._show('sleeping', now, urgent=True)
        elif was_sleeping:
            self._show('yawn', now, urgent=True)
            self._say = '唔…你回来啦'
        return True

    def on_click(self, now):
        now = self._now(now)
        if self.character is None or self._farewell_until is not None:
            return
        self._last_active = now
        if self._egg:
            self._tick_egg(now)
            if self._egg and self._egg['phase'] == 'pretend':
                self._egg['phase'], self._egg['until'] = 'caught', now + 2.0
                self._show('caught', now, urgent=True)
            return
        self._dev_until = None
        if self._manual_rest or self._pose == 'sleeping':
            self.set_resting(False, now)
            return
        if self.eggs_enabled and not self._reduced and self.rng.random() < .03 and self.play_egg(now, force=True):
            return
        self._show('pat', now, urgent=True)

    def on_poke(self, now):
        now = self._now(now)
        if self._egg or self._manual_rest or self._pose == 'sleeping':
            self.on_click(now)
            return
        if self.character is None or self._farewell_until is not None:
            return
        self._last_active, self._dev_until = now, None
        pose = self._behavior().get('poke_pose')
        pose = pose if isinstance(pose, str) and self.catalog.has_pose(self.character, pose) else 'surprised'
        self._show(pose, now, urgent=True, duration=3.5)

    def on_feed(self, now):
        """A visual menu interaction, without rewards, audio or host physics."""
        now = self._now(now)
        if self.character is None or self._farewell_until is not None:
            return
        if self._egg:
            self._end_egg(now)
        self._manual_rest = False
        self._dev_until = self._pending = None
        self._last_active = now
        pose = next((p for p in ('eat', 'feast') if self.catalog.has_pose(self.character, p)), 'happy')
        self._show(pose, now, urgent=True, duration=4.0)

    def farewell(self, now):
        now = self._now(now)
        if self._egg:
            self._end_egg(now)
        self._dev_until = self._pending = None
        self._farewell_until = now + 2.0
        self._show('bye', now, urgent=True, duration=2.0)
        return 2.0

    def dev_show(self, pose, secs, now):
        now = self._now(now)
        if (self.character is None or self._farewell_until is not None or self._manual_rest
                or not isinstance(pose, str) or not _POSE.fullmatch(pose)
                or not _finite(secs) or not 0 < secs <= 600):
            return False
        if self._egg:
            self._end_egg(now)
        self._show(pose, now, urgent=True, duration=float(secs), speak=False)
        self._dev_until = now + float(secs)
        return True

    def set_quota(self, low, windows, now):
        now = self._now(now)
        if self.character is None:
            return
        rows = []
        for row in windows if isinstance(windows, (tuple, list)) else ():
            if (not isinstance(row, dict) or row.get('stale') or row.get('expired')
                    or not isinstance(row.get('label'), str) or not 0 < len(row['label']) <= 32
                    or not _finite(row.get('used')) or not 0 <= row['used'] <= 100):
                continue
            reset = row.get('reset')
            rows.append(dict(label=row['label'], used=float(row['used']),
                             reset=float(reset) if _finite(reset) else None))
            if len(rows) >= 16:
                break
        store = self.memory.setdefault('quota', {})
        if not isinstance(store, dict):
            store = self.memory['quota'] = {}
        prev = store.get(self.character, {})
        old_rows = prev.get('windows', ()) if isinstance(prev, dict) else ()
        old_rows = old_rows if isinstance(old_rows, (list, tuple)) else ()
        reset_event = self.character == 'codex' and any(
            old.get('label') == row['label'] and _finite(old.get('reset'))
            and now < old['reset'] - 600 and _finite(old.get('used')) and old['used'] - row['used'] >= 15
            for row in rows for old in old_rows if isinstance(old, dict))
        was_low = self._low
        self._low = self.character in ('claude', 'codex') and (low is True or any(r['used'] >= 90 for r in rows))
        store[self.character] = dict(low=self._low, windows=rows)
        if self._manual_rest or self._farewell_until is not None or self._dev_until is not None or self._egg:
            return
        if reset_event:
            self._show('reset', now, urgent=True, duration=6.5)
        elif self._pose in ('idle', 'tired') and was_low != self._low:
            self._show(self._rest(), now, urgent=True, speak=self._low)

    @property
    def eggs_enabled(self):
        return self.memory.get('eggs_enabled', True) is not False

    def set_eggs_enabled(self, enabled):
        if type(enabled) is bool:
            self.memory['eggs_enabled'] = enabled

    def play_egg(self, now, force=False):
        now = self._now(now)
        choices = self.catalog.eggs_for(self.character) if self.character else ()
        if (not self.eggs_enabled or not choices or self._egg or self._manual_rest
                or self._dev_until is not None or self._farewell_until is not None or self._reduced
                or (not force and self._pose != 'idle')):
            return False
        ident = self._pick(choices)
        self._egg = dict(id=ident, host=self.character, phase='pop', until=now + 2.2, next_line=math.inf)
        self._show('pop', now, urgent=True)
        return True

    def _end_egg(self, now):
        self._egg = None
        self._say = ''
        self._show(self._rest(), now, urgent=True, speak=False)

    def cancel_egg(self, now):
        """Discard a missing/broken cameo while keeping its selected host."""
        now = self._now(now)
        if self._egg is None:
            return False
        self._end_egg(now)
        return True

    def _tick_egg(self, now):
        for _ in range(4):
            egg = self._egg
            if not egg or now < egg['until']:
                break
            at, phase = egg['until'], egg['phase']
            if phase == 'pop':
                egg.update(phase='pretend', until=at + 40, next_line=at + 9)
                self._show('pretend', at, urgent=True)
            elif phase in ('pretend', 'caught'):
                egg.update(phase='bye', until=at + 2.2)
                self._show('bye', at, urgent=True)
                if phase == 'pretend':
                    self._say = self._line('escape') or '没人发现～下次见！'
            else:
                self._end_egg(at)
        if self._egg and self._egg['phase'] == 'pretend' and now >= self._egg['next_line']:
            self._say = self._line('pretend')
            self._egg['next_line'] = now + 9

    def _greet(self, now, busy):
        try:
            date = datetime.fromtimestamp(now, _CST)
        except (ValueError, OverflowError, OSError):
            return False
        store = self.memory.setdefault('greeted', {})
        if not isinstance(store, dict):
            store = self.memory['greeted'] = {}
        done = store.get(self.character, ())
        done = [k for k in done if isinstance(k, str) and len(k) <= 80] if isinstance(done, (list, tuple)) else []
        day, today, slot, fest = (date - timedelta(hours=5)).strftime('%Y-%m-%d'), date.strftime('%Y-%m-%d'), time_slot(date), festival(date)
        slot_key, fest_key = f'slot:{day}:{slot}', f'fest:{today}:{fest}'
        available = lambda p: self.catalog.has_pose(self.character, p) or self.catalog.lines(self.character, p)
        pose = 'fest_' + fest if fest and fest_key not in done and available('fest_' + fest) else None
        cooldowns = self.memory.setdefault('greeting_at', {})
        if not isinstance(cooldowns, dict):
            cooldowns = self.memory['greeting_at'] = {}
        last = cooldowns.get(self.character)
        if pose is None and slot_key not in done and available('greet_' + slot) and (not _finite(last) or now - last >= GREET_COOLDOWN):
            pose = 'greet_' + slot
        if pose is None:
            return False
        store[self.character] = [k for k in done if day in k or today in k][-32:] + [slot_key] + ([fest_key] if fest else [])
        cooldowns[self.character] = now
        if not busy and self.catalog.has_pose(self.character, pose):
            self._show(pose, now, urgent=True)
        self._say = self._line(pose, self.character) or self._behavior(self.character).get('greeting', '')
        return True

    def tick(self, now, *, chat_open=False, model_thinking=False, reduced_motion=False):
        now = self._now(now)
        self._reduced = bool(reduced_motion)
        if self.character is None:
            return View(None, 'idle', 'idle', 0, False, None, 0, None, 1, None, 0, '', None)
        held = self._farewell_until is not None or self._manual_rest
        if not held:
            if self._egg:
                self._tick_egg(now)
            elif self._until is not None and now >= self._until:
                at, target = self._until, self._return or self._level or self._rest()
                if target == 'thinking' and self._level not in (None, 'thinking'):
                    # Our 2 s snapshots can deliver the new turn and its first
                    # tool together; show that tool rather than a filler think.
                    target = self._level
                self._dev_until = None
                self._show(target, at, urgent=True, work=target == 'thinking', speak=target == 'thinking')
            if self._pending and now >= self._pending[1] and not self._egg:
                pose, at, duration, target, work, speak = self._pending
                self._show(pose, at, urgent=True, duration=duration, return_to=target, work=work, speak=speak)
            if not self._egg and self._dev_until is None:
                context = (bool(chat_open), bool(model_thinking))
                if context != self._context and any(context):
                    self._last_active = now
                self._context = context
                lt = self._behavior().get('long_think')
                is_long_think = (self._level == 'thinking' and isinstance(lt, Mapping)
                                 and self._pose == lt.get('pose'))
                if (self._until is None and self._level is not None and self._pose != self._level
                        and not is_long_think):
                    self._show(self._level, now, work=True)
                if self._until is None and self._level is None:
                    desired = 'thinking' if model_thinking else 'listening' if chat_open else None
                    context_long_think = (desired == 'thinking' and isinstance(lt, Mapping)
                                          and self._pose == lt.get('pose'))
                    if desired and self._pose != desired and not context_long_think:
                        self._show(desired, now, work=True)
                        self._context_owned = True
                    elif not desired and self._context_owned:
                        self._show(self._rest(), now, work=True)
                        self._context_owned = False
                if (self._pose == 'thinking' and isinstance(lt, Mapping) and _finite(lt.get('after'))
                        and now - self._pose_since >= lt['after'] and self.catalog.has_pose(self.character, lt.get('pose'))):
                    self._show(lt['pose'], now, urgent=True, work=True)
                if self._greet_requested:
                    self._greet_requested = False
                    busy = self._level is not None or self._pose not in ('idle', 'tired')
                    if not self._greet(now, busy):
                        cooldowns = self.memory.get('greeting_at')
                        if not isinstance(cooldowns, dict):
                            cooldowns = self.memory['greeting_at'] = {}
                        last = cooldowns.get(self.character)
                        if not _finite(last) or now - last >= GREET_COOLDOWN:
                            self._say = self._behavior(self.character).get('greeting', '')
                            cooldowns[self.character] = now
                if now >= self._next_greet:
                    self._next_greet = now + 60
                    if self._pose in ('idle', 'tired') and now - self._last_active < SLEEP_AFTER:
                        self._greet(now, False)
                if self._pose in ('idle', 'tired') and not any(context) and now - self._last_active >= SLEEP_AFTER:
                    self._show('sleeping', now, urgent=True)
                if now >= self._next_idle:
                    self._next_idle = now + 20
                    if self._pose in ('idle', 'tired') and not self._reduced and self.rng.random() < .42:
                        own = [p for p in self._behavior().get('idle_actions', ()) if self.catalog.has_pose(self.character, p)]
                        pool = own * 2 + ['hum', 'stretch'] + (['yawn'] if now - self._last_active > 180 else [])
                        pose = self._pick(pool)
                        self._show(pose, now, urgent=True, duration=4.0 if pose in own else None)
                if now >= self._next_egg:
                    self._next_egg = now + 60
                    if not self._reduced and self._pose == 'idle' and self.rng.random() < 1 / 40:
                        self.play_egg(now)
        if not self._egg and self._dev_until is None and not held:
            if now >= self._next_variant and not self._reduced:
                count = self.catalog.frame_count(self._render_id, self._pose)
                if count > 1:
                    old = self._ref(now)
                    self._index = self._pick([i for i in range(count) if i != self._index])
                    self._fade_from, self._fade_started, self._blink_until = old, now, 0.0
                self._next_variant = now + self.rng.uniform(8, 10)
            if now >= self._next_blink:
                self._next_blink = now + self.rng.uniform(3, 6.5)
                base = getattr(self.catalog, 'blink_index', lambda c: None)(self._render_id)
                if not self._reduced and self._pose == 'idle' and base == self._index and now - self._fade_started >= .6:
                    self._blink_until = now + .14
        alpha = 1.0 if self._reduced else min(1.0, max(0.0, (now - self._fade_started) / FADE_SECONDS))
        behavior = self._behavior()
        fx = (behavior.get('fx') or {}).get(self._pose, self._pose)
        motion = 'bob' if chat_open and self._pose == 'listening' and self._until is None else MOTION.get(self._pose, 'bob')
        if self._farewell_until is not None:
            leave_at = self._farewell_until - 1.1
            motion = 'leave' if now >= leave_at else 'bob'
        if motion != self._motion:
            # CrossPet keeps a CSS animation running while its class is
            # unchanged: only a new family restarts, from its pose change.
            self._motion = motion
            self._motion_since = self._pose_since if self._pose_since >= self._motion_tick else now
        self._motion_tick = now
        motion_t = max(0.0, now - self._motion_since)
        if motion == 'leave':
            motion_t = now - leave_at
        say, self._say = self._say, ''
        self._emitted = True
        egg = None
        if self._egg:
            info = behavior.get('egg') or {}
            egg = dict(host=self._egg['host'], phase=self._egg['phase'], caption=info.get('caption', ''), aura=info.get('aura'))
        return View(self._render_id, self._pose, self.catalog.resolve(self._render_id, self._pose),
                    self._index, not self._reduced and now < self._blink_until,
                    None if self._reduced else motion, motion_t,
                    self._fade_from if alpha < 1 else None, alpha,
                    None if self._reduced else fx, max(0.0, now - self._pose_since), say, egg)
