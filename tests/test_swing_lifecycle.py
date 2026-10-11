"""Current-core swing lifecycle using synthetic scenes and real input callbacks.

Never creates Pet/Tk windows, loads saved configuration, or accesses sessions.
Geometry and user feedback are synthetic; lifecycle, Action API, mouse routing,
scheduled callbacks, and Pendulum are the production implementations.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import life
import pet
import seat_motion


NOW = 10_000.0
LAYOUTS = ((True, True), (True, False), (False, False))


class CallbackQueue:
    """Keep the actual Tk after callback for a later synthetic event."""

    def __init__(self):
        self.pending = []
        self.configure = Mock()

    def after(self, milliseconds, callback):
        self.pending.append((milliseconds, callback))
        return f'synthetic-after-{len(self.pending)}'

    def take(self, milliseconds):
        for index, (delay, callback) in enumerate(self.pending):
            if delay == milliseconds:
                del self.pending[index]
                return callback
        raise AssertionError(f'No callback scheduled for {milliseconds}ms')


def event(x=10, y=10, x_root=100, y_root=200):
    return SimpleNamespace(x=x, y=y, x_root=x_root, y_root=y_root)


def core_shell(*, art=True, flat=True, seated=True, home=False):
    """Fake only assets/geometry and side-effect endpoints, never the lifecycle."""
    p = pet.Pet.__new__(pet.Pet)
    p._core_edition = True
    p._flat_panel_style = flat
    p._flat_mode = 'live'
    p._flat_bar_drag = None
    p.state = 'idle'
    p.state_until = 0.0
    p.drag = None
    p.x, p.fy = 1400.0, 1529.0
    p.W, p.H, p.FOOT_Y, p.scale = 537, 650, 600, 1.25
    p.settings = {}
    p._swing = p._swing_pull = p._scene_drag = None
    p.swing_home = home
    p._swing_remount = 0.0
    p._land_then = None
    p._nap_on_swing = False
    p.singing = p.ui_reduced_anim = p.thinking_now = False
    p._fast_ok = False
    p.last_interact = NOW - 120.0
    p.click_token = 0
    p._chain_rect = None
    p._book_open = p._crystal_open = False
    p._house_hover = None
    p.root = CallbackQueue()
    p.swing_layer = Mock()
    p.life = life.LifeMotion()
    p.cfg = {}
    p.blink_until = p._lid_until = 0.0
    p._lid_pending = p._mouth = p._micro_motion = None
    p.bubble = p.sticker = None
    p.parts, p.circles = [], []
    p._ks_cache = {}
    p._scene_art = (SimpleNamespace(meta={'face': {'eye_l': (60, 40),
                                                'eye_r': (74, 44)}}) if art else None)
    geometry = {'size': (440, 500), 'sl': (0, 0), 'gtl': (60, 40),
                'O': (0, 0), 'k': 1.0, 'flat': flat, 'u': 1.0,
                'hat_fx_pad': 0}
    p._art_geo = Mock(return_value=geometry)
    p._limit_house_scale = Mock(side_effect=lambda value: value)
    p._swing_fit_scene = Mock(return_value=False)
    p.say, p.sfx, p.save_settings = Mock(), Mock(), Mock()
    p._cancel_ball = Mock()
    p._start_micro_motion = Mock()
    p._art_hat_hit = Mock(return_value=False)
    p._art_seat_hit = Mock(return_value=False)
    p.wobble_hat = Mock()
    # A delayed real _seat_head_click would wake a nap, so the regression
    # catches invocation of the old callback, rather than just a token value.
    p.pet_head = Mock(side_effect=lambda: p.wake_if_sleep())
    p._swing_impulse = Mock()
    for name in ('_catch_collect', '_pop_bubble', '_catch_ball',
                 '_catch_leaf', '_catch_flower', '_catch_snow'):
        setattr(p, name, Mock(return_value=False))

    def add_part(kind, *args, **properties):
        p.parts.append(dict(kind=kind, **properties))

    p.add_part = Mock(side_effect=add_part)
    if seated:
        with patch.object(pet.time, 'time', return_value=NOW):
            p.start_swing(quiet=True)
        p._swing['ui_hits'] = []
    return p


def pose_markers(p):
    """Position/velocity are deliberately nonzero before a lifecycle event."""
    sw = p._swing
    sw['theta'], sw['omega'] = .17, -.23
    sw['pend'].theta, sw['pend'].omega = .17, -.23
    return sw, sw['pend'], (p.x, p.fy), sw['rect']


class SwingEntryTests(unittest.TestCase):
    def test_real_builders_enter_core_art_flat_and_procedural_scenes(self):
        for art, flat in LAYOUTS:
            with self.subTest(art=art, flat=flat):
                p = core_shell(art=art, flat=flat)
                self.assertTrue(p.core_profile())
                self.assertEqual(p.state, 'swing')
                self.assertEqual(bool(p._swing.get('art')), art)
                if art:
                    self.assertEqual(p._swing['geo']['flat'], flat)
                    p._art_geo.assert_called_once()
                self.assertFalse(p._nap_on_swing)
                self.assertEqual((p._swing['pend'].idle_amp, p._swing['pend'].damping),
                                 (.085, .30))

    def test_start_is_idempotent_without_resetting_position_or_velocity(self):
        for art, flat in LAYOUTS:
            with self.subTest(art=art, flat=flat):
                p = core_shell(art=art, flat=flat)
                sw, pend, location, rect = pose_markers(p)
                with patch.object(pet.time, 'time', return_value=NOW + 1):
                    p.start_swing(quiet=True)
                self.assertIs(p._swing, sw)
                self.assertIs(sw['pend'], pend)
                self.assertEqual((sw['theta'], sw['omega'], pend.theta, pend.omega),
                                 (.17, -.23, .17, -.23))
                self.assertEqual((p.x, p.fy, sw['rect']), (*location, rect))

    def test_sleep_yawn_and_body_drag_refuse_entry(self):
        for blocked in ('sleep', 'yawn', 'drag'):
            with self.subTest(blocked=blocked):
                p = core_shell(seated=False)
                if blocked == 'drag':
                    p.drag = (100, 200, p.x, p.fy, True, NOW)
                else:
                    p.state = blocked
                state = p.state
                with patch.object(pet.time, 'time', return_value=NOW):
                    p.start_swing(quiet=True)
                self.assertIsNone(p._swing)
                self.assertEqual(p.state, state)
                p._art_geo.assert_not_called()

    def test_entering_a_new_scene_clears_an_orphan_nap_marker(self):
        p = core_shell(seated=False)
        p._nap_on_swing = True
        p.parts = [{'kind': 'zzz'}, {'kind': 'synthetic-dust'}]
        before = p.last_interact
        with patch.object(pet.time, 'time', return_value=NOW):
            p.start_swing(quiet=True)
        self.assertEqual(p.state, 'swing')
        self.assertFalse(p._nap_on_swing)
        self.assertEqual(p.parts, [{'kind': 'synthetic-dust'}])
        self.assertEqual(p.last_interact, before)


class SwingNapTests(unittest.TestCase):
    def test_sleep_and_wake_preserve_the_scene_pendulum_and_arc(self):
        for art, flat in LAYOUTS:
            with self.subTest(art=art, flat=flat):
                p = core_shell(art=art, flat=flat)
                sw, pend, location, rect = pose_markers(p)
                with patch.object(pet.time, 'time', return_value=NOW + 1):
                    p._exec_cmd({'op': 'sleep'})
                self.assertTrue(p._nap_on_swing)
                self.assertEqual(p.state, 'swing')
                self.assertIs(p._swing, sw)
                self.assertIs(sw['pend'], pend)
                self.assertEqual((pend.idle_amp, pend.damping), (.012, .85))
                self.assertEqual((sw['theta'], sw['omega'], pend.theta, pend.omega),
                                 (.17, -.23, .17, -.23))
                with patch.object(pet.time, 'time', return_value=NOW + 2):
                    p._exec_cmd({'op': 'wake'})
                self.assertFalse(p._nap_on_swing)
                self.assertEqual(p.state, 'swing')
                self.assertIs(p._swing, sw)
                self.assertIs(sw['pend'], pend)
                self.assertEqual((pend.idle_amp, pend.damping), (.085, .30))
                self.assertEqual((sw['theta'], sw['omega'], pend.theta, pend.omega),
                                 (.17, -.23, .17, -.23))
                self.assertEqual((p.x, p.fy, sw['rect']), (*location, rect))
                self.assertFalse(any(q['kind'] == 'zzz' for q in p.parts))
                self.assertEqual(p.last_interact, NOW + 2)

    def test_repeated_sleep_does_not_add_feedback_or_particles(self):
        p = core_shell()
        with patch.object(pet.time, 'time', return_value=NOW):
            p.go_sleep()
        parts = list(p.parts)
        calls = (p.say.call_count, p.add_part.call_count, p._cancel_ball.call_count)
        with patch.object(pet.time, 'time', return_value=NOW + 1):
            p.go_sleep()
        self.assertEqual(p.parts, parts)
        self.assertEqual((p.say.call_count, p.add_part.call_count,
                          p._cancel_ball.call_count), calls)

    def test_awake_wake_is_idempotent_and_keeps_a_playing_action(self):
        p = core_shell()
        sw, pend, _, _ = pose_markers(p)
        before = p.last_interact
        with patch.object(pet.time, 'time', return_value=NOW):
            self.assertTrue(p.perform_action('pat'))
        token = p._action_expression_token
        with patch.object(pet.time, 'time', return_value=NOW + .1):
            p._exec_cmd({'op': 'wake'})
            p.wake_up()
        self.assertEqual(p.state, 'swing')
        self.assertIs(p._swing, sw)
        self.assertIs(sw['pend'], pend)
        self.assertEqual((sw['theta'], sw['omega'], pend.theta, pend.omega),
                         (.17, -.23, .17, -.23))
        self.assertEqual(p.last_interact, before)
        self.assertIs(p._action_expression_token, token)
        self.assertEqual(p._active_seat(NOW + .2).name, 'pat')
        p.say.assert_not_called()
        p.sfx.play.assert_not_called()
        self.assertEqual(p.root.pending, [])

    def test_sleep_then_wake_in_one_frame_cancels_without_replaying(self):
        for name in ('pat', 'push'):
            with self.subTest(action=name):
                p = core_shell()
                p._offer_lid(.34, 'sad', NOW, hold=10)
                with patch.object(pet.time, 'time', return_value=NOW):
                    self.assertTrue(p.perform_action(name))
                self.assertIsNotNone(p._lid_pending)
                if name == 'push':
                    self.assertEqual(p._mouth[0], 'laugh')
                # No render, update or _active_seat call between these events.
                with patch.object(pet.time, 'time', return_value=NOW + .1):
                    p.go_sleep()
                    p.wake_up()
                self.assertFalse(p._nap_on_swing)
                self.assertIsNone(p._seat_motion.name)
                self.assertIsNone(p._lid_pending)
                self.assertIsNone(p._mouth)
                self.assertIsNone(p._action_expression_token)
                self.assertEqual((p._lid, p._lid_mode, p._lid_until),
                                 (.34, 'sad', NOW + 10))
                self.assertIsNone(p._active_seat(NOW + .2))
                self.assertEqual(p._actions().last_cancel_reason, 'sleeping')
                self.assertEqual(p._seat_motion.due(NOW + 1.6), [])

    def test_nap_uses_the_quiet_tier_and_activity_can_raise_it(self):
        p = core_shell()
        with patch.object(pet.time, 'time', return_value=NOW):
            p.go_sleep()
        self.assertEqual(p._frame_delay(), 100)
        p.thinking_now = True
        self.assertEqual(p._frame_delay(), 33)
        p.thinking_now = False
        p.bubble = ('synthetic activity', NOW + 1)
        self.assertEqual(p._frame_delay(), 33)

    def test_moving_scene_drag_has_priority_over_an_external_sleep_request(self):
        p = core_shell()
        sw = p._swing
        with patch.object(pet.time, 'time', return_value=NOW):
            p.on_press(event())
            p.on_drag(event(x_root=112))
            p._exec_cmd({'op': 'sleep'})
        self.assertTrue(p._scene_drag['moved'])
        self.assertFalse(p._nap_on_swing)
        self.assertIs(p._swing, sw)
        p.add_part.assert_not_called()
        self.assertEqual((sw['pend'].idle_amp, sw['pend'].damping), (.085, .30))

    def test_singing_does_not_enter_nap(self):
        p = core_shell()
        p.singing = True
        sw = p._swing
        with patch.object(pet.time, 'time', return_value=NOW):
            p.go_sleep()
        self.assertFalse(p._nap_on_swing)
        self.assertIs(p._swing, sw)
        self.assertEqual((sw['pend'].idle_amp, sw['pend'].damping), (.085, .30))
        p.add_part.assert_not_called()


class SwingExitTests(unittest.TestCase):
    def test_exit_restores_old_pendulum_without_faking_a_wake_interaction(self):
        p = core_shell(home=True)
        sw, pend, location, _ = pose_markers(p)
        before = p.last_interact
        with patch.object(pet.time, 'time', return_value=NOW):
            p.go_sleep()
        p.parts.extend([{'kind': 'ball'}, {'kind': 'ball_ring'},
                        {'kind': 'synthetic-dust'}])
        with patch.object(pet.time, 'time', return_value=NOW + 1):
            p._swing_stop(restore=False)
        self.assertIsNone(p._swing)
        self.assertFalse(p._nap_on_swing)
        self.assertEqual((pend.idle_amp, pend.damping), (.085, .30))
        self.assertEqual((sw['theta'], sw['omega'], pend.theta, pend.omega),
                         (.17, -.23, .17, -.23))
        self.assertEqual((p.x, p.fy), location)
        self.assertEqual(p.last_interact, before)
        self.assertEqual(p.parts, [{'kind': 'synthetic-dust'}])
        self.assertTrue(40 <= p._swing_remount - (NOW + 1) <= 70)
        p.swing_layer.close.assert_called()

    def test_update_reconciles_external_state_or_body_drag_without_advancing(self):
        for blocked in ('fall', 'body_drag'):
            with self.subTest(blocked=blocked):
                p = core_shell()
                sw, pend, location, _ = pose_markers(p)
                with patch.object(pet.time, 'time', return_value=NOW):
                    self.assertTrue(p.perform_action('push'))
                if blocked == 'body_drag':
                    p.drag = (100, 200, p.x, p.fy, True, NOW)
                else:
                    p.state = 'fall'
                state = p.state
                with patch.object(pet.time, 'time', return_value=NOW + .1), \
                     patch.object(pend, 'step', wraps=pend.step) as step:
                    p._update_swing_state(NOW + .1)
                step.assert_not_called()
                self.assertEqual(p.state, state)
                self.assertIsNone(p._swing)
                self.assertIsNone(p._seat_motion.name)
                self.assertIsNone(p._mouth)
                self.assertIsNone(p._action_expression_token)
                self.assertEqual((p.x, p.fy), location)
                self.assertEqual((sw['theta'], sw['omega'], pend.theta, pend.omega),
                                 (.17, -.23, .17, -.23))

    def test_update_discards_orphan_nap_without_modifying_movement_or_interaction(self):
        p = core_shell(seated=False)
        p._nap_on_swing = True
        p.parts = [{'kind': 'zzz'}, {'kind': 'synthetic-dust'}]
        before = p.last_interact
        p._update_swing_state(NOW)
        self.assertEqual(p.state, 'idle')
        self.assertFalse(p._nap_on_swing)
        self.assertEqual(p.last_interact, before)
        self.assertEqual(p.parts, [{'kind': 'synthetic-dust'}])


class SwingInputLifecycleTests(unittest.TestCase):
    def press(self, p, at=NOW):
        with patch.object(pet.time, 'time', return_value=at):
            p.on_press(event())
        return p.root.take(seat_motion.LONG_PRESS_MS)

    def release(self, p, at=NOW + .01):
        with patch.object(pet.time, 'time', return_value=at):
            p.on_release(event())
        return p.root.take(60)

    def test_old_release_callback_cannot_wake_a_new_nap(self):
        for target in ('head', 'hat', 'seat'):
            with self.subTest(target=target):
                p = core_shell()
                p._art_hat_hit.return_value = target == 'hat'
                p._art_seat_hit.return_value = target == 'seat'
                self.press(p)
                callback = self.release(p)
                with patch.object(pet.time, 'time', return_value=NOW + .02):
                    p.go_sleep()
                with patch.object(pet.time, 'time', return_value=NOW + .06):
                    callback()
                self.assertTrue(p._nap_on_swing)
                self.assertEqual(p.state, 'swing')
                p.pet_head.assert_not_called()
                p.wobble_hat.assert_not_called()
                p._swing_impulse.assert_not_called()
                self.assertIsNone(p.__dict__.get('_seat_motion'))

    def test_old_release_callback_cannot_act_in_a_replacement_scene(self):
        p = core_shell()
        old = p._swing
        self.press(p)
        callback = self.release(p)
        with patch.object(pet.time, 'time', return_value=NOW + .02):
            p._swing_stop()
            p.state = 'idle'
            p.start_swing(quiet=True)
        self.assertIsNot(p._swing, old)
        with patch.object(pet.time, 'time', return_value=NOW + .06):
            callback()
        p.pet_head.assert_not_called()
        p.wobble_hat.assert_not_called()
        self.assertIsNone(p.__dict__.get('_seat_motion'))

    def test_old_long_press_callback_is_invalid_after_sleep_and_wake(self):
        p = core_shell()
        callback = self.press(p)
        with patch.object(pet.time, 'time', return_value=NOW + .1):
            p.go_sleep()
            p.wake_up()
        with patch.object(pet.time, 'time', return_value=NOW + .9):
            callback()
        self.assertIsNone(p._scene_drag)
        self.assertIsNone(p.__dict__.get('_seat_motion'))
        self.assertFalse(p._nap_on_swing)

    def test_old_long_press_callback_is_invalid_after_scene_replacement(self):
        p = core_shell()
        callback = self.press(p)
        old = p._swing
        with patch.object(pet.time, 'time', return_value=NOW + .1):
            p._swing_stop()
            p.state = 'idle'
            p.start_swing(quiet=True)
        self.assertIsNot(p._swing, old)
        with patch.object(pet.time, 'time', return_value=NOW + .9):
            callback()
        self.assertIsNone(p._scene_drag)
        self.assertIsNone(p.__dict__.get('_seat_motion'))

    def test_current_long_press_plays_shy_and_release_does_not_double_count(self):
        p = core_shell()
        callback = self.press(p)
        sw = p._swing
        with patch.object(pet.time, 'time', return_value=NOW + .9):
            callback()
        self.assertEqual(p._seat_motion.name, 'shy')
        self.assertIs(p._swing, sw)
        with patch.object(pet.time, 'time', return_value=NOW + .95):
            p.on_release(event())
        self.assertEqual(p.root.pending, [])
        p.pet_head.assert_not_called()
        p.wobble_hat.assert_not_called()

    def test_click_that_wakes_nap_does_not_arm_long_press(self):
        p = core_shell()
        with patch.object(pet.time, 'time', return_value=NOW):
            p.go_sleep()
        sw = p._swing
        with patch.object(pet.time, 'time', return_value=NOW + .1):
            p.on_press(event())
        self.assertFalse(p._nap_on_swing)
        self.assertIs(p._swing, sw)
        self.assertEqual(p.root.pending, [])
        self.assertFalse(p._scene_drag['moved'])

    def test_slow_scene_drag_keeps_the_scene_cancels_shy_and_saves_once(self):
        for art, flat in LAYOUTS:
            with self.subTest(art=art, flat=flat):
                p = core_shell(art=art, flat=flat)
                sw, pend, _, _ = pose_markers(p)
                callback = self.press(p)
                left, top = sw['scene_l'], sw['scene_t']
                with patch.object(pet.time, 'time', return_value=NOW + .2):
                    for distance in range(1, 13):
                        p.on_drag(event(x_root=100 + distance))
                    p._update_swing_state(NOW + .2)
                self.assertIs(p._swing, sw)
                self.assertEqual(p.state, 'swing')
                self.assertEqual((sw['scene_l'], sw['scene_t']), (left + 12, top))
                self.assertTrue(p._scene_drag['moved'])
                self.assertEqual(p._frame_delay(), 33)
                with patch.object(pet.time, 'time', return_value=NOW + .9):
                    callback()
                self.assertIsNone(p.__dict__.get('_seat_motion'))
                with patch.object(pet.time, 'time', return_value=NOW + 1):
                    p.on_release(event(x_root=112))
                self.assertIsNone(p._scene_drag)
                p.save_settings.assert_called_once()
                self.assertEqual(p.settings['swing_scene']['l'], left + 12)
                self.assertEqual(p.settings['swing_scene']['t'], top)
                self.assertEqual((sw['theta'], sw['omega'], pend.theta, pend.omega),
                                 (.17, -.23, .17, -.23))
                p.pet_head.assert_not_called()
                p.wobble_hat.assert_not_called()


if __name__ == '__main__':
    unittest.main()
