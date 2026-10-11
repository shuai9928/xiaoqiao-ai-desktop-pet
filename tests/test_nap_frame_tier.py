"""Frame tier of a napping swing pet and of a ground sleeper (Fix A).

Ambient particles (zzz, sparkle, snow, petal, leaf, firefly, note) no longer pull a
nap or a ground sleep out of the 10 fps tier: they drift slowly and the idle path
(_quiet_idle_ok) already tolerates them. Every real interaction signal still does:
bubble, sticker, circles, thinking, any NON-ambient particle, a recent interaction
(press, hover, wheel and menu all refresh last_interact), drag and scene drag.

Never creates Pet/Tk windows; fixtures are the synthetic shells of
test_swing_lifecycle (their last_interact is two minutes before NOW, i.e. "long
ago"; recency is tested by patching pet.time.time).
"""
import unittest
from unittest.mock import Mock, patch

import pet
from test_swing_lifecycle import NOW, core_shell, event


def napping(fast=False):
    p = core_shell()
    with patch.object(pet.time, 'time', return_value=NOW):
        p.go_sleep()
    assert p._nap_on_swing and p.state == 'swing'
    p.parts = []
    p._fast_ok = fast
    return p


class NapFrameTierTests(unittest.TestCase):
    def test_quiet_nap_and_ambient_only_nap_are_10fps(self):
        for fast in (False, True):
            p = napping(fast)
            self.assertEqual(p._frame_delay(), 100)
            for kind in sorted(pet.AMBIENT_PARTS):
                with self.subTest(kind=kind, fast=fast):
                    p.parts = [{'kind': kind}]
                    self.assertEqual(p._frame_delay(), 100)
            p.parts = [{'kind': kind} for kind in sorted(pet.AMBIENT_PARTS)] * 3
            self.assertEqual(p._frame_delay(), 100)

    def test_a_non_ambient_part_returns_the_interactive_tier(self):
        for kind in ('star', 'heart', 'confetti', 'gear', 'hit_ring', 'meteor'):
            for fast in (False, True):
                with self.subTest(kind=kind, fast=fast):
                    p = napping(fast)
                    p.parts = [{'kind': 'sparkle'}, {'kind': kind}, {'kind': 'zzz'}]
                    # meteor is calm background: never the 60 fps tier, still not 10 fps
                    want = 33 if (not fast or kind in pet.CALM_PARTS) else 16
                    self.assertEqual(p._frame_delay(), want)

    def test_bubble_sticker_circles_and_thinking_return_the_interactive_tier(self):
        signals = (('bubble', ('hi', NOW + 5)), ('sticker', object()),
                   ('circles', [object()]), ('thinking_now', True))
        for name, value in signals:
            for fast in (False, True):
                with self.subTest(signal=name, fast=fast):
                    p = napping(fast)
                    p.parts = [{'kind': 'zzz'}, {'kind': 'sparkle'}]
                    setattr(p, name, value)
                    self.assertEqual(p._frame_delay(), 33)

    def test_recent_interaction_returns_the_interactive_tier(self):
        p = napping()
        p.parts = [{'kind': 'sparkle'}]
        p.last_interact = NOW
        for dt, want in ((0.0, 33), (3.99, 33), (4.0, 33), (4.01, 100), (75.0, 100)):
            with self.subTest(seconds_since_interaction=dt):
                with patch.object(pet.time, 'time', return_value=NOW + dt):
                    self.assertEqual(p._frame_delay(), want)

    def test_hover_with_a_sparkle_trail_stays_interactive_then_settles(self):
        # on_hover refreshes last_interact and sprinkles sparkles (ambient kind)
        p = napping()
        p.last_interact = NOW + 10
        p.parts = [{'kind': 'sparkle'}]
        with patch.object(pet.time, 'time', return_value=NOW + 11):
            self.assertEqual(p._frame_delay(), 33)
        with patch.object(pet.time, 'time', return_value=NOW + 15):
            self.assertEqual(p._frame_delay(), 100)

    def test_the_real_hover_handler_refreshes_the_recency_clock(self):
        p = napping()
        p._hover_last, p._spark_cd, p.stroke_acc, p.stroke_cd = None, 0.0, 0.0, 0.0
        p._crystal_hover_since = 0.0
        p._set_house_hover = Mock()
        p.house_enabled = p.studio_enabled = lambda: False
        self.assertEqual(p._frame_delay(), 100)
        with patch.object(pet.time, 'time', return_value=NOW + 30):
            p.on_hover(event())
            self.assertEqual(p.last_interact, NOW + 30)
            self.assertTrue(p._nap_on_swing)          # hover does not wake her
            # the hover sprinkled a sparkle: ambient, so only the recency keeps 33 ms
            self.assertEqual([q['kind'] for q in p.parts], ['sparkle'])
            self.assertEqual(p._frame_delay(), 33)
        with patch.object(pet.time, 'time', return_value=NOW + 35):
            self.assertEqual(p._frame_delay(), 100)

    def test_drag_and_scene_drag_keep_priority(self):
        p = napping(True)
        p.drag = (0, 0, 0, 0, False, 0.0)
        self.assertEqual(p._frame_delay(), 16)
        p.drag = None
        p._scene_drag = {'mx': 0, 'my': 0, 'moved': False}
        self.assertEqual(p._frame_delay(), 16)
        p._fast_ok = False
        self.assertEqual(p._frame_delay(), 33)

    def test_a_click_on_the_nap_leaves_the_quiet_tier_on_the_next_frame(self):
        # The press handler runs between frames: it clears the nap marker and arms
        # the scene grab, so the very next _frame_delay() (computed at the end of the
        # next tick) is already the interactive tier, never 10 fps.
        for fast, want in ((False, 33), (True, 16)):
            with self.subTest(fast=fast):
                p = napping(fast)
                self.assertEqual(p._frame_delay(), 100)
                with patch.object(pet.time, 'time', return_value=NOW + .1):
                    p.on_press(event())
                self.assertFalse(p._nap_on_swing)
                self.assertEqual(p.last_interact, NOW + .1)
                self.assertEqual(p._frame_delay(), want)
                p._scene_drag = None                  # released: awake resting swing
                self.assertEqual(p._frame_delay(), 50)

    def test_ground_sleep_follows_the_same_rules(self):
        for fast in (False, True):
            with self.subTest(fast=fast):
                p = core_shell(seated=False)
                p.state, p._fast_ok = 'sleep', fast
                self.assertEqual(p._frame_delay(), 100)
                p.parts = [{'kind': 'zzz'}, {'kind': 'sparkle'}, {'kind': 'snow'}]
                self.assertEqual(p._frame_delay(), 100)
                p.parts = [{'kind': 'sparkle'}, {'kind': 'star'}]
                self.assertEqual(p._frame_delay(), 33)
                p.parts, p.bubble = [], ('hi', NOW + 5)
                self.assertEqual(p._frame_delay(), 33)
                p.bubble, p.last_interact = None, NOW
                with patch.object(pet.time, 'time', return_value=NOW + 2):
                    self.assertEqual(p._frame_delay(), 33)
                with patch.object(pet.time, 'time', return_value=NOW + 9):
                    self.assertEqual(p._frame_delay(), 100)
                p.drag = (0, 0, 0, 0, False, 0.0)     # a dragged sleeper is not asleep
                self.assertEqual(p._frame_delay(), 16 if fast else 33)

    def test_awake_resting_swing_is_not_affected(self):
        p = core_shell()
        p._fast_ok = False
        p.parts = [{'kind': 'sparkle'}]
        self.assertFalse(p._nap_on_swing)
        self.assertEqual(p._frame_delay(), 50)

    def test_stub_without_last_interact_attribute_still_works(self):
        # test_swing.shell_pet() style shells never set last_interact
        p = napping()
        del p.last_interact
        self.assertEqual(p._frame_delay(), 100)


if __name__ == '__main__':
    unittest.main()
