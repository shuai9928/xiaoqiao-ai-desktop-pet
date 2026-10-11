"""AI-mode frame pacing (I-50 workstream 3).

AI mode has two tiers: awake/drag 16 ms (33 ms when the AI-only frame budget
says this machine cannot keep up) and sleeping 33 ms. The schedule itself is a
VsyncPacer: absolute deadlines on a monotonic clock, phase-locked half way
between two DWM vblanks, resynchronised (never caught up) after a stall.
timeBeginPeriod(1) is held only while the AI pet is visible. Xiaoqiao keeps
_frame_delay/_paced_delay exactly (pinned in test_pet / test_nap_frame_tier).

Fake clock, fake DWM timing and fake winmm only; never creates Tk windows.
"""
import inspect
import json
import math
import random
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pet
from test_swing_lifecycle import NOW, core_shell

P60 = 1000.0 / 60


def view(pose='idle', blink=False, fade_alpha=1.0):
    return SimpleNamespace(pose=pose, blink=blink, fade_alpha=fade_alpha, motion=None, fx=None)


def ai_shell(fast=True):
    p = core_shell()
    p._static_active = lambda: True
    p._ai_fast_ok = fast
    p._ai_pet_view = view()
    return p


class FakeClock:
    def __init__(self, ms=5000.0):
        self.ms = ms

    def __call__(self):
        return self.ms / 1000.0


class FakeDwm:
    """DWM grid: period plus one vblank somewhere on it (past or future, as the real one).

    `reported` optionally replaces the reported period per call (DWM's own smoothed
    estimate, which spikes after a panel self-refresh / phase jump) while the vblanks
    stay on the true grid.
    """
    def __init__(self, period=16.6656, vblank=3.21, reported=None):
        self.period, self.vblank, self.calls = period, vblank, 0
        self.reported = list(reported or ())

    def __call__(self, now_ms):
        self.calls += 1
        k = math.floor((now_ms - self.vblank) / self.period) + 2      # a "future" vblank
        shown = self.reported.pop(0) if self.reported else self.period
        return shown, self.vblank + k * self.period


def drive(pacer, clock, spents, target=P60, latency=None):
    """Emulate the Tk loop: tick starts, works `spent`, schedules after(delay), wakes late by latency."""
    starts, delays, dues = [], [], []
    for s in spents:
        starts.append(clock.ms)
        clock.ms += s
        d = pacer.delay(target)
        delays.append(d)
        dues.append(pacer.due)
        clock.ms += d + (latency() if latency else 0.0)
    return starts, delays, dues


def intervals(starts):
    return [b - a for a, b in zip(starts, starts[1:])]


class AiTierTests(unittest.TestCase):
    def test_awake_poses_are_60fps_and_fall_back_to_30_when_over_budget(self):
        for pose in ('idle', 'thinking', 'reading', 'writing', 'running', 'pat',
                     'surprised', 'bye', 'happy', 'oops'):
            for fast in (True, False):
                with self.subTest(pose=pose, fast=fast):
                    p = ai_shell(fast)
                    p._ai_pet_view = view(pose)
                    self.assertEqual(p._frame_delay(), 16 if fast else 33)
                    p._ai_pet_view = view(pose, blink=True)
                    self.assertEqual(p._frame_delay(), 16 if fast else 33)
                    p._ai_pet_view = view(pose, fade_alpha=0.4)
                    self.assertEqual(p._frame_delay(), 16 if fast else 33)

    def test_quiet_sleep_is_30fps_and_any_signal_returns_the_awake_tier(self):
        for fast in (True, False):
            p = ai_shell(fast)
            p._ai_pet_view = view('sleeping')
            self.assertEqual(p._frame_delay(), 33)          # was 100
            for signal in (dict(blink=True), dict(fade_alpha=0.5)):
                p._ai_pet_view = view('sleeping', **signal)
                self.assertEqual(p._frame_delay(), 16 if fast else 33, signal)
            p._ai_pet_view = view('sleeping')
            p.bubble = ('呼…', NOW + 3)
            self.assertEqual(p._frame_delay(), 16 if fast else 33)

    def test_drag_and_scene_drag_follow_the_hand_at_60fps(self):
        for fast in (True, False):
            for name in ('drag', '_scene_drag'):
                with self.subTest(fast=fast, name=name):
                    p = ai_shell(fast)
                    p._ai_pet_view = view('sleeping')
                    setattr(p, name, {'dx': 0})
                    self.assertEqual(p._frame_delay(), 16 if fast else 33)   # was 33

    def test_no_view_yet_and_missing_budget_flag_default_to_60fps(self):
        p = ai_shell()
        p._ai_pet_view = None
        del p._ai_fast_ok
        self.assertEqual(p._frame_delay(), 16)

    def test_ai_mode_never_uses_the_old_20_or_10_fps_tiers(self):
        p = ai_shell()
        for pose in ('idle', 'sleeping', 'pat', 'bye'):
            for fast in (True, False):
                p._ai_pet_view, p._ai_fast_ok = view(pose), fast
                self.assertIn(p._frame_delay(), (16, 33))

    def test_xiaoqiao_tiers_unchanged_and_ignore_the_ai_budget(self):
        p = core_shell()
        self.assertFalse(p._static_active())
        for ai_ok in (True, False):
            p._ai_fast_ok = ai_ok
            p.state, p._fast_ok, p.drag = 'swing', False, None
            self.assertEqual(p._frame_delay(), 50)          # resident swing
            p.state = 'sleep'
            self.assertEqual(p._frame_delay(), 100)         # still sleeper
            p.state, p.drag = 'idle', {'x': 1}
            self.assertEqual(p._frame_delay(), 33)          # drag, machine too slow
            p._fast_ok = True
            self.assertEqual(p._frame_delay(), 16)          # drag, fast machine
            p.drag = None
        for ai_ok in (True, False):
            p = core_shell()
            with patch.object(pet.time, 'time', return_value=NOW):
                p.go_sleep()
            self.assertTrue(p._nap_on_swing)
            p.parts, p._fast_ok, p._ai_fast_ok = [], True, ai_ok
            self.assertEqual(p._frame_delay(), 100)         # swing nap


class AiBudgetTests(unittest.TestCase):
    def test_ema_alpha_and_hysteresis(self):
        p = pet.Pet.__new__(pet.Pet)
        p._note_ai_spent(10.0)
        self.assertAlmostEqual(p._ai_frame_ms, 1.0)
        self.assertTrue(p._ai_fast_ok)
        for _ in range(200):
            p._note_ai_spent(5.0)
        self.assertTrue(p._ai_fast_ok)
        n = 0
        while p._ai_fast_ok:
            p._note_ai_spent(12.0)
            n += 1
        self.assertGreater(p._ai_frame_ms, pet.AI_FAST_BUDGET_MS)
        self.assertLess(p._ai_frame_ms, pet.AI_FAST_BUDGET_MS + 1.0)
        self.assertGreater(n, 3)                            # one spike does not drop the tier
        for _ in range(200):                                # 6 ms: inside the 5.6..8 band
            p._note_ai_spent(6.0)
            self.assertFalse(p._ai_fast_ok)
        while not p._ai_fast_ok:
            p._note_ai_spent(4.0)
        self.assertLess(p._ai_frame_ms, pet.AI_FAST_BUDGET_MS * 0.7)
        self.assertEqual(pet.AI_FAST_BUDGET_MS, 8.0)
        self.assertEqual(pet.FAST_BUDGET_MS, 13.0)

    def test_a_single_spike_does_not_drop_to_30fps(self):
        p = pet.Pet.__new__(pet.Pet)
        for _ in range(100):
            p._note_ai_spent(3.0)
        p._note_ai_spent(40.0)                               # e.g. a panel rebuild landing in one tick
        self.assertTrue(p._ai_fast_ok)

    def test_ai_budget_does_not_touch_the_xiaoqiao_budget(self):
        p = pet.Pet.__new__(pet.Pet)
        p._frame_ms, p._fast_ok = 2.0, True
        for _ in range(50):
            p._note_ai_spent(30.0)
        self.assertFalse(p._ai_fast_ok)
        self.assertEqual((p._frame_ms, p._fast_ok), (2.0, True))


class PacerTests(unittest.TestCase):
    def test_dwm_struct_is_the_packed_292_byte_layout(self):
        import ctypes
        self.assertEqual(ctypes.sizeof(pet._DwmTiming), 292)
        self.assertEqual(pet._DwmTiming.qpc_vblank.offset, 28)
        self.assertEqual(pet._DwmTiming.qpc_period.offset, 12)

    def test_real_dwm_query_is_sane_or_none(self):
        got = pet.dwm_timing(1000.0)
        if got is not None:
            period, vblank = got
            self.assertTrue(4.0 <= period <= 50.0)
            self.assertTrue(math.isfinite(vblank))

    def test_600_frames_average_the_refresh_period_and_never_schedule_negative(self):
        rng = random.Random(7)
        clock = FakeClock()
        pacer = pet.VsyncPacer(clock=clock, timing=lambda now: None)     # DWM down: 60 Hz fallback
        starts, delays, _ = drive(pacer, clock, [rng.uniform(2, 12) for _ in range(601)],
                                  latency=lambda: rng.uniform(0, 0.9))
        iv = intervals(starts)
        self.assertEqual(len(iv), 600)
        self.assertAlmostEqual(sum(iv) / len(iv), P60, delta=0.1)
        self.assertGreaterEqual(min(delays), 1)
        self.assertTrue(all(isinstance(d, int) for d in delays))
        self.assertLess(max(iv), P60 + 2.0)
        self.assertGreater(min(iv), P60 - 2.0)
        self.assertFalse(pacer.dwm_ok)
        self.assertAlmostEqual(pacer.period, P60)

    def test_the_old_int_truncation_path_beats_against_the_refresh(self):
        # Documents why: max(4, int(16 - spent)) averages ~16 ms here, not 16.67.
        rng = random.Random(7)
        t, starts = 0.0, []
        for _ in range(601):
            starts.append(t)
            spent = rng.uniform(2, 12)
            t += spent + max(4, int(16 - spent)) + rng.uniform(0, 0.9)
        self.assertLess(sum(intervals(starts)) / 600, P60 - 0.1)

    def test_stall_resyncs_to_the_next_slot_without_catch_up_burst(self):
        clock = FakeClock()
        pacer = pet.VsyncPacer(clock=clock, timing=FakeDwm())
        spents = [4.0] * 300 + [100.0] + [4.0] * 100
        starts, delays, dues = drive(pacer, clock, spents)
        iv = intervals(starts)
        self.assertGreater(iv[300], 100.0)                  # the stalled frame itself
        self.assertLessEqual(iv[300], 100.0 + pacer.period + 1)
        after = iv[301:]
        self.assertTrue(all(abs(x - pacer.period) < 1.0 for x in after), min(after))
        self.assertEqual(sum(x < pacer.period / 2 for x in after), 0)

    def test_late_by_less_than_a_period_fires_once_then_returns_to_the_grid(self):
        clock = FakeClock()
        pacer = pet.VsyncPacer(clock=clock, timing=FakeDwm())
        starts, delays, dues = drive(pacer, clock, [4.0] * 200 + [25.0] + [4.0] * 50)
        iv = intervals(starts)
        self.assertEqual(delays[200], 1)                     # one immediate frame, no queue
        self.assertEqual(sum(x < pacer.period / 2 for x in iv[200:]), 1)
        self.assertTrue(all(abs(b - a - pacer.period) < 1e-6 for a, b in zip(dues[200:], dues[201:])))

    def test_deadlines_sit_half_way_between_vblanks(self):
        dwm = FakeDwm(period=16.6656, vblank=3.21)
        clock = FakeClock(12345.678)
        rng = random.Random(3)
        pacer = pet.VsyncPacer(clock=clock, timing=dwm)
        starts, delays, dues = drive(pacer, clock, [rng.uniform(2, 12) for _ in range(300)],
                                     latency=lambda: rng.uniform(0, 0.9))
        anchor = dwm.vblank + dwm.period / 2
        for due in dues:
            ph = (due - anchor) % dwm.period
            self.assertLess(min(ph, dwm.period - ph), 1e-6)
        for s in starts[1:]:
            ph = (s - anchor) % dwm.period
            self.assertLess(min(ph, dwm.period - ph), 0.5 + 0.9 + 1e-9)
        self.assertTrue(pacer.dwm_ok)
        self.assertAlmostEqual(pacer.period, 16.6656)
        self.assertTrue(3 <= dwm.calls <= 7, dwm.calls)      # probed about once a second

    def test_first_deadline_is_the_next_slot_and_reset_resyncs(self):
        dwm = FakeDwm()
        clock = FakeClock(777.0)
        pacer = pet.VsyncPacer(clock=clock, timing=dwm)
        d = pacer.delay(P60)
        self.assertTrue(0 < pacer.due - clock.ms <= dwm.period)
        self.assertTrue(1 <= d <= 17)
        clock.ms += 5000.0                                   # e.g. a Xiaoqiao stretch
        pacer.reset()
        d = pacer.delay(P60)
        self.assertTrue(0 < pacer.due - clock.ms <= dwm.period)

    def test_grid_shift_is_absorbed_one_millisecond_per_probe(self):
        dwm = FakeDwm()
        clock = FakeClock()
        pacer = pet.VsyncPacer(clock=clock, timing=dwm)
        drive(pacer, clock, [3.0] * 120)
        dwm.vblank += 3.0                                    # grid moved under us
        _, _, dues = drive(pacer, clock, [3.0] * 400)
        steps = [b - a for a, b in zip(dues, dues[1:])]
        self.assertTrue(all(abs(s - dwm.period) <= pacer.NUDGE_MS + 1e-9 for s in steps))
        anchor = dwm.vblank + dwm.period / 2
        ph = (dues[-1] - anchor) % dwm.period
        self.assertLess(min(ph, dwm.period - ph), 1e-6)

    def test_30fps_tier_is_two_periods_and_switching_tiers_does_not_burst(self):
        dwm = FakeDwm()
        clock = FakeClock()
        pacer = pet.VsyncPacer(clock=clock, timing=dwm)
        starts, _, _ = drive(pacer, clock, [3.0] * 60, target=1000.0 / 30)
        self.assertAlmostEqual(pacer.step, 2 * dwm.period)
        iv = intervals(starts)
        self.assertTrue(all(abs(x - 2 * dwm.period) < 1.0 for x in iv[1:]))
        more, _, _ = drive(pacer, clock, [3.0] * 60, target=P60)
        iv = intervals(starts[-1:] + more)
        self.assertTrue(all(abs(x - dwm.period) < 1.0 or abs(x - 2 * dwm.period) < 1.0 for x in iv))
        self.assertTrue(all(abs(x - dwm.period) < 1.0 for x in iv[2:]))

    def test_120hz_panel_keeps_60fps_as_two_refreshes(self):
        clock = FakeClock()
        pacer = pet.VsyncPacer(clock=clock, timing=FakeDwm(period=1000.0 / 120))
        drive(pacer, clock, [3.0] * 240)                     # 3 consistent reads to accept 8.33 ms
        self.assertAlmostEqual(pacer.period, 1000.0 / 120)
        starts, _, _ = drive(pacer, clock, [3.0] * 301)
        self.assertAlmostEqual(pacer.step, 1000.0 / 60)
        self.assertAlmostEqual(sum(intervals(starts)) / 300, 1000.0 / 60, delta=0.1)

    def test_a_spiking_dwm_period_estimate_is_ignored(self):
        # Measured on the target laptop: 17.85 -> 17.6 -> ... -> 16.70 over ~2.5 s, often.
        spike = [16.6656, 16.6656, 17.851, 17.381, 17.043, 16.881, 16.785, 16.729, 16.70,
                 16.6656, 20.948, 18.789, 17.876, 17.204, 16.952, 16.80, 16.72, 16.6656]
        clock = FakeClock()
        pacer = pet.VsyncPacer(clock=clock, timing=FakeDwm(reported=spike))
        seen = []
        for _ in range(len(spike) + 2):
            starts, _, _ = drive(pacer, clock, [4.0] * 60)
            seen.append(pacer.period)
        self.assertTrue(all(abs(p - 16.6656) < 0.03 for p in seen), seen)
        self.assertEqual(pacer.step, pacer.period)

    def test_a_real_refresh_change_is_accepted_after_three_consistent_reads(self):
        clock = FakeClock()
        dwm = FakeDwm(reported=[16.6656] * 3 + [8.3328] * 20)
        pacer = pet.VsyncPacer(clock=clock, timing=dwm)
        periods = []
        for _ in range(8):
            drive(pacer, clock, [4.0] * 60)
            periods.append(round(pacer.period, 4))
        self.assertEqual(periods[:5].count(8.3328), 0)
        self.assertEqual(periods[-1], 8.3328)
        self.assertAlmostEqual(pacer.step, 16.6656, places=3)        # 60 fps = 2 refreshes at 120 Hz

    def test_failing_or_raising_dwm_falls_back_to_60hz(self):
        for timing in (lambda now: None, Mock(side_effect=OSError)):
            clock = FakeClock()
            pacer = pet.VsyncPacer(clock=clock, timing=timing)
            starts, delays, _ = drive(pacer, clock, [5.0] * 200)
            self.assertFalse(pacer.dwm_ok)
            self.assertAlmostEqual(sum(intervals(starts)) / 199, P60, delta=0.1)


class FakeWinmm:
    def __init__(self, begin_result=0, events=None):
        self.begin_result, self.events = begin_result, [] if events is None else events

    def timeBeginPeriod(self, n):
        self.events.append(('begin', n))
        return self.begin_result

    def timeEndPeriod(self, n):
        self.events.append(('end', n))
        return 0

    def count(self, kind):
        return sum(1 for e in self.events if e[0] == kind)


def tick_shell():
    p = pet.Pet.__new__(pet.Pet)
    p.root = Mock()
    p.root.state.return_value = 'normal'
    p._tick_body, p._pump, p._log_exc = Mock(), Mock(), Mock()
    p._frame_ms, p._fast_ok = 0.0, True
    p.drag = p._scene_drag = p.bubble = None
    p._ai_pet_view = view()
    p._ai_static = True
    p._static_active = lambda: p._ai_static
    p._paced_delay = Mock(return_value=33)
    p.clock = FakeClock()
    p._vsync = pet.VsyncPacer(clock=p.clock, timing=FakeDwm())
    return p


def tick(p, n=1, advance=16.6656):
    for _ in range(n):
        p.tick()
        p.clock.ms += advance
    p._log_exc.assert_not_called()
    return p.root.after.call_args[0][0]


class HiresAndTickTests(unittest.TestCase):
    def test_a_failing_frame_still_releases_the_timer_outside_ai_mode(self):
        fake = FakeWinmm()
        p = tick_shell()
        with patch.object(pet, 'winmm', fake):
            tick(p, 3)                                  # AI visible: 1 ms timer held
            self.assertEqual((fake.count('begin'), fake.count('end')), (1, 0))
            p._ai_static = False                        # switched to Xiaoqiao...
            p._tick_body.side_effect = RuntimeError('frame failed')
            p.tick()                                    # ...and that frame throws
        self.assertEqual(fake.count('end'), 1)
        self.assertFalse(p._hires)

    def test_hires_is_held_only_while_the_ai_pet_is_visible(self):
        fake = FakeWinmm()
        p = tick_shell()
        with patch.object(pet, 'winmm', fake):
            d = tick(p, 5)
            self.assertTrue(1 <= d <= 17)
            p._paced_delay.assert_not_called()
            self.assertEqual((fake.count('begin'), fake.count('end')), (1, 0))
            self.assertTrue(p._hires)
            p._ai_pet_view = view('sleeping')               # 30 fps tier still needs 1 ms timers
            tick(p, 3)
            self.assertEqual(fake.count('begin'), 1)
            p.root.state.return_value = 'withdrawn'
            self.assertEqual(tick(p, 3), 100)
            self.assertEqual((fake.count('begin'), fake.count('end')), (1, 1))
            self.assertIsNone(p._vsync.due)                  # resync when shown again
            p.root.state.return_value = 'normal'
            tick(p, 2)
            self.assertEqual((fake.count('begin'), fake.count('end')), (2, 1))
            p._ai_static = False                             # Xiaoqiao: old pacing, default timers
            self.assertEqual(tick(p, 3), 33)
            self.assertEqual(p._paced_delay.call_count, 3)
            self.assertEqual((fake.count('begin'), fake.count('end')), (2, 2))
            self.assertFalse(p._hires)
            self.assertIsNone(p._vsync.due)
        self.assertTrue(all(n == 1 for _, n in fake.events))

    def test_quit_releases_the_timer_before_destroying_the_root(self):
        events = []
        fake = FakeWinmm(events=events)
        p = tick_shell()
        with patch.object(pet, 'winmm', fake):
            tick(p, 2)
            p._ai_work_panel = p._room_preview = p._tray = None
            p.close_action_card = p.save_settings = p.stop_sing = Mock()
            p.fsmagic, p.swing_layer, p.sfx = Mock(), Mock(), Mock()
            p.root.tk.call.return_value = ('after#1',)
            p.root.destroy.side_effect = lambda: events.append(('destroy', 0))
            p._finish_quit()
            p._finish_quit()                                 # idempotent: no second release
        self.assertEqual([e[0] for e in events], ['begin', 'end', 'destroy', 'destroy'])
        self.assertFalse(p._hires)

    def test_a_refused_timer_request_is_not_released_later(self):
        fake = FakeWinmm(begin_result=97)                   # TIMERR_NOCANDO
        p = tick_shell()
        with patch.object(pet, 'winmm', fake):
            tick(p, 3)
            self.assertFalse(getattr(p, '_hires', False))
            p._ai_static = False
            tick(p, 1)
        self.assertEqual(fake.count('end'), 0)

    def test_set_hires_is_a_guarded_toggle_and_init_never_calls_it(self):
        fake = FakeWinmm()
        p = pet.Pet.__new__(pet.Pet)
        with patch.object(pet, 'winmm', fake):
            for on in (True, True, False, False, True, False):
                p._set_hires(on)
        self.assertEqual([e[0] for e in fake.events], ['begin', 'end', 'begin', 'end'])
        self.assertNotIn('_set_hires', inspect.getsource(pet.Pet.__init__))
        self.assertNotIn('timeBeginPeriod', inspect.getsource(pet.Pet.__init__))

    def test_tick_feeds_the_ai_budget_only_in_ai_mode(self):
        p = tick_shell()
        with patch.object(pet, 'winmm', FakeWinmm()):
            p._ai_static = False
            tick(p, 5)
            self.assertFalse(hasattr(p, '_ai_frame_ms'))
            p._ai_static = True
            tick(p, 5)
            self.assertTrue(hasattr(p, '_ai_frame_ms'))
            p._set_hires(False)

    def test_tick_records_one_frame_entry_per_tick(self):
        p = tick_shell()
        with patch.object(pet, 'winmm', FakeWinmm()):
            tick(p, 4)
            p._ai_static = False
            tick(p, 2)
            p.root.state.return_value = 'withdrawn'
            tick(p, 1)
        flags = [row[2] for row in p._frame_log]
        self.assertEqual(flags, [True] * 4 + [False] * 2 + [None])
        self.assertTrue(all(abs(row[3] - 16.6656) < 1e-9 for row in list(p._frame_log)[:4]))
        self.assertEqual(p._frame_log[-1][3], 100)


class FrameStatsTests(unittest.TestCase):
    def test_empty_or_missing_log_still_serialises(self):
        p = pet.Pet.__new__(pet.Pet)
        for log in (None, deque(maxlen=pet.FRAME_STATS_N)):
            if log is not None:
                p._frame_log = log
            s = p._frame_stats_summary()
            json.dumps(s)
            self.assertEqual(s['n'], 0)
            self.assertIsNone(s['mode'])
            for key in ('interval_p50', 'interval_p95', 'interval_p99', 'interval_max',
                        'spent_p50', 'spent_p95', 'spent_max', 'late_share', 'target_ms',
                        'dwm_period_ms'):
                self.assertIsNone(s[key], key)
            self.assertTrue(s['ai_fast_ok'])
            self.assertFalse(s['hires'])

    def test_percentiles_and_late_share(self):
        p = pet.Pet.__new__(pet.Pet)
        t, rows = 10.0, []
        gaps = [10.0] * 90 + [30.0] * 10
        for i in range(101):
            rows.append((t, float(i + 1), True, P60))
            if i < 100:
                t += gaps[i] / 1000.0
        p._frame_log = deque(rows, maxlen=pet.FRAME_STATS_N)
        p._vsync = pet.VsyncPacer(clock=FakeClock(), timing=FakeDwm())
        p._vsync.delay(P60)
        p._hires, p._ai_fast_ok = True, False
        s = p._frame_stats_summary()
        self.assertEqual(s['n'], 101)
        self.assertEqual(s['mode'], 'ai')
        self.assertEqual((s['interval_p50'], s['interval_p95'], s['interval_p99'], s['interval_max']),
                         (10.0, 30.0, 30.0, 30.0))
        self.assertEqual((s['spent_p50'], s['spent_p95'], s['spent_max']), (51.0, 96.0, 101.0))
        self.assertEqual(s['late_share'], 0.1)
        self.assertEqual(s['target_ms'], round(P60, 3))
        self.assertEqual(s['dwm_period_ms'], 16.6656)
        self.assertEqual((s['ai_fast_ok'], s['hires']), (False, True))

    def test_only_the_latest_mode_is_measured(self):
        p = pet.Pet.__new__(pet.Pet)
        rows = [(i * 0.033, 9.0, False, None) for i in range(20)]       # Xiaoqiao stretch
        rows.append((5.0, 0.1, None, 100))                              # hidden
        rows += [(60.0 + i * P60 / 1000.0, 3.0, True, P60) for i in range(30)]
        p._frame_log = deque(rows, maxlen=pet.FRAME_STATS_N)
        s = p._frame_stats_summary()
        self.assertEqual(s['mode'], 'ai')
        self.assertAlmostEqual(s['interval_max'], P60, places=1)       # no 55 s gap pair
        self.assertEqual(s['spent_max'], 3.0)
        self.assertEqual(s['late_share'], 0.0)

    def test_log_is_bounded(self):
        p = pet.Pet.__new__(pet.Pet)
        for i in range(pet.FRAME_STATS_N + 100):
            p._note_frame(i * 0.016, 1.0, True, P60)
        self.assertEqual(len(p._frame_log), pet.FRAME_STATS_N)
        self.assertEqual(p._frame_log[0][0], 100 * 0.016)

    def test_state_export_carries_frame_stats(self):
        self.assertIn('"frame_stats": self._frame_stats_summary()',
                      inspect.getsource(pet.Pet._write_state))


if __name__ == '__main__':
    unittest.main()
