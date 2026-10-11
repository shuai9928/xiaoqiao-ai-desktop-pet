"""I-46: one "pat her head" intent, one entry (chat keyword, core menu, pet_cmd, head click).

Synthetic seated shell from test_swing; never Pet.__init__, no Tk window, no model.
"""
import unittest
from unittest.mock import Mock, patch

import life
import pet
from test_swing import seated_pet

NOW = 10_000.0


class FakeMenu:
    """Records add_command; every other Tk menu call is a no-op."""

    def __init__(self, log):
        self.log = log

    def add_command(self, **kw):
        self.log.append(kw)

    def __getattr__(self, name):
        return lambda *a, **k: None


class PatEntryTests(unittest.TestCase):
    def setUp(self):
        self.p = p = seated_pet()
        p._core_edition = True
        p.life = life.LifeMotion()
        p.ui_reduced_anim = p._nap_on_swing = False
        p._scene_drag = None
        p.cfg = {}
        p.blink_until = 0.0
        p._lid_until = 0.0
        p._lid_pending = p._mouth = None
        p.last_interact = NOW
        p.pet_head = Mock()            # its own feedback is covered by test_pet / test_seat_motion
        p._swing_impulse = Mock()

    def call(self, fn, *args):
        with patch.object(pet.time, 'time', return_value=NOW):
            return fn(*args)

    def assert_seated_pat(self):
        p = self.p
        p.pet_head.assert_called_once()
        p._swing_impulse.assert_not_called()
        self.assertEqual(p._seat_motion.name, 'pat')
        request = p._actions().last_request
        self.assertEqual((request.action, request.source, request.accepted), ('pat', 'user', True))

    def assert_no_seated_action(self):
        motion = self.p.__dict__.get('_seat_motion')
        self.assertTrue(motion is None or motion.name is None)

    def test_chat_keywords_map_to_the_unified_entry_and_legacy_table_is_untouched(self):
        for text in ('摸摸', '摸头', '摸摸头', '小乔摸摸头~'):
            with self.subTest(text=text):
                self.assertEqual(self.p._match_pet_action(text), 'request_pat')
        self.assertEqual(pet.Pet._match_pet_action('摸摸头', legacy=True), 'pet_head')

    def test_chat_message_plays_the_same_seated_pat_as_a_head_click(self):
        self.p._log_chat = Mock()
        self.call(self.p.ask_ai, '摸摸头')
        self.assert_seated_pat()

    def test_core_menu_item_uses_the_unified_entry(self):
        p, items = self.p, []
        p._menu = lambda parent=None: FakeMenu(items)
        p.sound_on = p.tts_on = p.ai_lights = p.ai_announce = False
        p.topmost = p.click_through = False
        with patch.object(pet, 'autostart_enabled', return_value=False):
            p._build_menu()
        item = next(kw for kw in items if kw.get('label') == '摸摸头')
        self.call(item['command'])
        self.assert_seated_pat()

    def test_pet_command_uses_the_unified_entry(self):
        self.call(self.p._exec_cmd, {'op': 'pet'})
        self.assert_seated_pat()

    def test_head_click_route_is_unchanged(self):
        self.call(self.p._seat_head_click)
        self.assert_seated_pat()

    def test_nap_wakes_first_like_the_mouse_and_candy_then_pats(self):
        p = self.p
        self.assertTrue(self.call(p._set_swing_nap, True, NOW))
        p.parts = [{'kind': 'zzz'}, {'kind': 'sparkle'}]
        self.call(p.request_pat)
        self.assertFalse(p._nap_on_swing)
        self.assertEqual([q['kind'] for q in p.parts], ['sparkle'])
        pend = p._swing.get('pend')
        if pend is not None:
            self.assertEqual((pend.idle_amp, pend.damping),
                             (pet.SWING_IDLE_AMP, pet.SWING_IDLE_DAMPING))
        self.assertEqual(p.state, 'swing')
        self.assert_seated_pat()

    def test_off_the_swing_it_is_the_plain_pet_head(self):
        p = self.p
        p.state, p._swing = 'idle', None
        self.call(p.request_pat)
        p.pet_head.assert_called_once()
        p._swing_impulse.assert_not_called()
        self.assert_no_seated_action()

    def test_blocked_on_the_swing_falls_back_exactly_like_the_mouse(self):
        p = self.p
        p.ui_reduced_anim = True
        self.call(p.request_pat)
        p.pet_head.assert_called_once()
        p._swing_impulse.assert_called_once_with(0.10)
        self.assert_no_seated_action()
        self.assertEqual(p._actions().last_request.reason, 'reduced_motion')


if __name__ == '__main__':
    unittest.main()
