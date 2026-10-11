"""Current-core Action API integration, using a synthetic shell, never Pet.__init__."""
import unittest
from unittest.mock import Mock, patch

import agent_companion
from agent_reactions import Reaction
import life
import pet
from test_swing import seated_pet

NOW = 10_000.0


class ActionAPIRuntimeTests(unittest.TestCase):
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

    def request(self, name, at=NOW, **kwargs):
        with patch.object(pet.time, 'time', return_value=at):
            return self.p.perform_action(name, **kwargs)

    def test_compatibility_entry_uses_the_same_request_guard(self):
        with patch.object(pet.time, 'time', return_value=NOW):
            self.assertFalse(self.p.start_seat_action({'rotation': 1000}))
            self.assertTrue(self.p.start_seat_action('shy', -1))
        self.assertEqual(self.p._seat_motion.side, -1)
        self.assertEqual(self.p._actions().last_request.source, 'user')

    def test_sleep_cancels_body_and_its_queued_expression_without_replay(self):
        p = self.p
        p._offer_lid(.34, 'sad', NOW, hold=.5)  # unrelated existing expression
        self.assertTrue(self.request('pat'))
        self.assertEqual(p._lid_pending[1], 'shy')
        p._nap_on_swing = True
        self.assertIsNone(p._active_seat(NOW + .1))
        self.assertIsNone(p._lid_pending)
        self.assertEqual((p._lid, p._lid_mode, p._lid_until), (.34, 'sad', NOW + .5))
        p._nap_on_swing = False
        self.assertIsNone(p._active_seat(NOW + 1))
        self.assertEqual(p._face_texture_key(NOW + 1, 0, False)[3:], (0.0, ''))
        self.assertEqual(p._actions().last_cancel_reason, 'sleeping')

    def test_promoted_action_lid_retains_ownership_when_drag_interrupts(self):
        p = self.p
        p._offer_lid(.34, 'sad', NOW, hold=.2)
        self.assertTrue(self.request('nudge', source='agent'))
        token = p._action_expression_token
        p._face_texture_key(NOW + .3, 0, False)
        self.assertIs(p._lid_owner, token)
        self.assertEqual(p._lid_mode, 'curious')
        p._scene_drag = {'moved': True}
        self.assertIsNone(p._active_seat(NOW + .4))
        self.assertEqual(p._lid_until, NOW + .4)
        p._scene_drag = None
        self.assertIsNone(p._active_seat(NOW + .5))

    def test_cancel_never_clears_a_new_unrelated_chat_emotion(self):
        p = self.p
        self.assertTrue(self.request('push'))
        with patch.object(pet.time, 'time', return_value=NOW + .1):
            p.play_emotion('angry')
        until = p._lid_until
        p.ui_reduced_anim = True
        self.assertIsNone(p._active_seat(NOW + .2))
        self.assertEqual((p._lid, p._lid_mode, p._lid_until), (.42, 'angry', until))
        self.assertIsNone(p._mouth)  # push's owned laugh is released

    def test_action_end_discards_an_expression_that_never_got_its_turn(self):
        p = self.p
        p._offer_lid(.34, 'sad', NOW, hold=10)
        self.assertTrue(self.request('pat'))
        self.assertIsNone(p._active_seat(NOW + 3))
        self.assertIsNone(p._lid_pending)
        self.assertEqual(p._lid_until, NOW + 10)

    def test_newer_user_action_releases_only_the_previous_action_overlays(self):
        p = self.p
        self.assertTrue(self.request('push'))
        self.assertEqual(p._mouth[0], 'laugh')
        self.assertTrue(self.request('flick', at=NOW + .2))
        self.assertIsNone(p._mouth)
        self.assertEqual(p._lid_mode, 'amazed')
        self.assertIsNone(p._lid_pending)

    def test_dismount_immediately_discards_body_and_owned_laugh(self):
        p = self.p
        self.assertTrue(self.request('push'))
        with patch.object(pet.time, 'time', return_value=NOW + .2):
            p._swing_stop()
        self.assertIsNone(p._seat_motion.name)
        self.assertIsNone(p._action_expression_token)
        self.assertIsNone(p._mouth)
        p.state = 'fall'
        self.assertEqual(p._face_texture_key(NOW + .3, 0, False)[0], '')
        with patch.object(pet.time, 'time', return_value=NOW + .4):
            p.start_swing(quiet=True)
        self.assertIsNone(p._active_seat(NOW + .5))

    def test_non_swing_facial_sampling_never_promotes_a_stale_action_lid(self):
        p = self.p
        p._offer_lid(.34, 'sad', NOW, hold=.2)
        self.assertTrue(self.request('pat'))
        p.state = 'fall'  # a legacy transition may bypass the scene helper
        key = p._face_texture_key(NOW + .3, 0, False)
        self.assertIsNone(p._seat_motion.name)
        self.assertIsNone(p._lid_pending)
        self.assertEqual(key[3:], (0.0, ''))

    def test_agent_request_respects_priority_and_has_no_user_feedback(self):
        p = self.p
        self.assertTrue(self.request('pat'))
        before = (p._lid, p._lid_mode, p._lid_until, p._lid_pending)
        p.play_emotion = Mock()
        with patch.object(pet.time, 'time', return_value=NOW + .1):
            agent_companion.execute(p, Reaction('waiting', 'Claude', emotion='curious'), NOW + .1)
        self.assertEqual(p._seat_motion.name, 'pat')
        self.assertEqual((p._lid, p._lid_mode, p._lid_until, p._lid_pending), before)
        self.assertEqual(p._actions().last_request.reason, 'priority')
        p.play_emotion.assert_not_called()
        p.sfx.play.assert_not_called()

    def test_named_demo_uses_the_api_without_rewards_or_persisted_changes(self):
        p = self.p
        p.gain_star = Mock()
        p.save_settings = Mock()
        with patch.object(pet.time, 'time', return_value=NOW):
            p._exec_cmd({'op': 'demo', 'secs': 1, 'seat_action': 'shy'})
        self.assertEqual(p._actions().last_request.source, 'demo')
        self.assertEqual(p._seat_motion.name, 'shy')
        p.gain_star.assert_not_called()
        p.save_settings.assert_not_called()
        p.sfx.play.assert_not_called()


if __name__ == '__main__':
    unittest.main()
