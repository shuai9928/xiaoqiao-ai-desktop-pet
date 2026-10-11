"""Pure Action API contracts; no Pet, Tk, configuration or real session data.

These tests exercise requests and interruptions over the existing SeatMotion
timeline. Visual feedback, rewards and dialogue remain the caller's concern.
"""
import json
import math
import unittest

from character_actions import ActionContext, ActionSystem
from seat_motion import ACTIONS, SeatMotion


NOW = 10_000.0
AGENT_ACTIONS = ('glance', 'nudge', 'startle', 'relief')
TOUCH_ACTIONS = ('pat', 'flick', 'push', 'shy')
ALL_ACTIONS = AGENT_ACTIONS + TOUCH_ACTIONS
SOURCES = ('user', 'agent', 'demo')


def context(**changes):
    values = dict(movement='swing', on_swing=True, sleeping=False,
                  reduced_motion=False, dragging=False, singing=False)
    values.update(changes)
    return ActionContext(**values)


def system():
    motion = SeatMotion()
    return ActionSystem(motion=motion), motion


class RequestContractTests(unittest.TestCase):
    def test_success_is_frozen_truthy_public_result(self):
        actions, _ = system()
        result = actions.request('pat', context(), NOW)
        self.assertTrue(result)
        self.assertIs(result.accepted, True)
        self.assertEqual((result.action, result.source, result.reason),
                         ('pat', 'user', 'started'))
        for field, replacement in (('action', 'push'), ('source', 'agent'),
                                   ('accepted', False), ('reason', 'other')):
            with self.subTest(field=field), self.assertRaises(AttributeError):
                setattr(result, field, replacement)

    def test_user_and_demo_can_request_all_eight_actions(self):
        for source in ('user', 'demo'):
            for name in ALL_ACTIONS:
                with self.subTest(source=source, action=name):
                    actions, _ = system()
                    result = actions.request(name, context(), NOW, source=source)
                    self.assertTrue(result)
                    self.assertEqual(result.reason, 'started')
                    self.assertEqual(actions.active(context(), NOW + .05), name)

    def test_agent_can_request_only_companion_actions(self):
        for name in AGENT_ACTIONS:
            with self.subTest(action=name):
                actions, _ = system()
                self.assertTrue(actions.request(name, context(), NOW, source='agent'))
        for name in TOUCH_ACTIONS:
            with self.subTest(action=name):
                actions, _ = system()
                result = actions.request(name, context(), NOW, source='agent')
                self.assertFalse(result)
                self.assertIs(result.accepted, False)
                self.assertEqual(result.reason, 'source_not_allowed')
                self.assertEqual((result.action, result.source), (name, 'agent'))
                self.assertIsNone(actions.active(context(), NOW))

    def test_unknown_and_malformed_names_are_sanitized(self):
        for name in ('', 'dance', 'pat\nsecret-marker', None, 123, True,
                     [], {'name': 'pat'}, object()):
            with self.subTest(value_type=type(name).__name__):
                actions, _ = system()
                result = actions.request(name, context(), NOW)
                self.assertFalse(result)
                self.assertEqual(result.reason, 'unknown_action')
                self.assertIsNone(result.action)
                self.assertEqual(result.source, 'user')

    def test_unknown_and_malformed_sources_are_sanitized(self):
        for source in ('', 'model', 'user\nsecret-marker', None, 123, True,
                       [], {'source': 'user'}, object()):
            with self.subTest(value_type=type(source).__name__):
                actions, _ = system()
                result = actions.request('pat', context(), NOW, source=source)
                self.assertFalse(result)
                self.assertEqual(result.reason, 'unknown_source')
                self.assertEqual(result.action, 'pat')
                self.assertIsNone(result.source)

    def test_nonfinite_boolean_and_non_numeric_times_are_rejected(self):
        for now in (math.nan, math.inf, -math.inf, True, False,
                    None, '10000', [], object(), 10 ** 400):
            with self.subTest(value_type=type(now).__name__):
                actions, _ = system()
                result = actions.request('pat', context(), now)
                self.assertFalse(result)
                self.assertEqual(result.reason, 'invalid_time')
                self.assertIsNone(actions.active(context(), NOW))

    def test_finite_int_and_float_times_are_accepted(self):
        for now in (10_000, NOW):
            with self.subTest(now=now):
                actions, _ = system()
                self.assertTrue(actions.request('glance', context(), now))

    def test_only_integer_unit_sides_are_accepted(self):
        for side in (0, 2, -2, True, False, 1.0, -1.0, None, '1', []):
            with self.subTest(value_type=type(side).__name__, side=side):
                actions, _ = system()
                result = actions.request('pat', context(), NOW, side=side)
                self.assertFalse(result)
                self.assertEqual(result.reason, 'invalid_side')
                self.assertIsNone(actions.active(context(), NOW))

    def test_valid_side_is_forwarded_to_the_existing_timeline(self):
        right, right_motion = system()
        left, left_motion = system()
        self.assertTrue(right.request('glance', context(), NOW, side=1))
        self.assertTrue(left.request('glance', context(), NOW, side=-1))
        rx, ry = right_motion.gaze(NOW + .5, (0.0, 0.0))
        lx, ly = left_motion.gaze(NOW + .5, (0.0, 0.0))
        self.assertGreater(rx, 0)
        self.assertAlmostEqual(lx, -rx)
        self.assertAlmostEqual(ly, ry)

    def test_invalid_requests_do_not_interrupt_a_playing_action(self):
        invalid_requests = (
            dict(name='unknown'), dict(source='unknown'), dict(now=math.nan),
            dict(side=True), dict(name='push', source='agent'),
        )
        for overrides in invalid_requests:
            with self.subTest(overrides=overrides):
                actions, _ = system()
                self.assertTrue(actions.request('pat', context(), NOW))
                values = dict(name='glance', now=NOW + .2, source='agent', side=1)
                values.update(overrides)
                result = actions.request(context=context(), **values)
                self.assertFalse(result)
                self.assertEqual(actions.active(context(), NOW + .25), 'pat')


class ContextAndCancellationTests(unittest.TestCase):
    def test_blocked_conditions_have_stable_precedence(self):
        cases = (
            (dict(sleeping=True, dragging=True, reduced_motion=True, singing=True,
                  movement='idle', on_swing=False), 'sleeping'),
            (dict(dragging=True, reduced_motion=True, singing=True,
                  movement='idle', on_swing=False), 'dragging'),
            (dict(reduced_motion=True, singing=True,
                  movement='idle', on_swing=False), 'reduced_motion'),
            (dict(singing=True, movement='idle', on_swing=False), 'singing'),
            (dict(movement='idle', on_swing=False), 'not_seated'),
            (dict(on_swing=False), 'missing_scene'),
        )
        for changes, reason in cases:
            with self.subTest(reason=reason):
                actions, _ = system()
                blocked = context(**changes)
                result = actions.request('pat', blocked, NOW)
                self.assertFalse(result)
                self.assertEqual(result.reason, reason)
                view = actions.snapshot(blocked, NOW)
                self.assertEqual(view['state'], 'blocked')
                self.assertIsNone(view['active'])

    def test_every_block_cancels_without_replaying_after_recovery(self):
        conditions = (
            (dict(sleeping=True), 'sleeping'),
            (dict(dragging=True), 'dragging'),
            (dict(reduced_motion=True), 'reduced_motion'),
            (dict(singing=True), 'singing'),
            (dict(movement='idle'), 'not_seated'),
            (dict(on_swing=False), 'missing_scene'),
        )
        for name in ('nudge', 'pat', 'relief'):
            for changes, reason in conditions:
                with self.subTest(action=name, reason=reason):
                    actions, motion = system()
                    self.assertTrue(actions.request(name, context(), NOW))
                    blocked = context(**changes)
                    self.assertIsNone(actions.active(blocked, NOW + .4))
                    view = actions.snapshot(blocked, NOW + .4)
                    self.assertEqual(view['state'], 'blocked')
                    self.assertIsNone(view['active'])
                    self.assertEqual(view['last_cancel_reason'], reason)
                    # Recovery happens well before the old timeline would expire.
                    self.assertIsNone(actions.active(context(), NOW + .5))
                    self.assertEqual(actions.snapshot(context(), NOW + .5)['state'], 'idle')
                    base = (.13, -.19)
                    self.assertEqual(motion.gaze(NOW + .5, base), base)
                    self.assertEqual(motion.breath(NOW + .5, .42), .42)
                    self.assertFalse(motion.holding(NOW + .5))
                    self.assertEqual(motion.due(NOW + .5), [])

    def test_snapshot_is_read_only_and_explicit_active_applies_guard(self):
        actions, _ = system()
        self.assertTrue(actions.request('pat', context(), NOW))
        blocked = context(dragging=True)
        view = actions.snapshot(blocked, NOW + .1)
        self.assertEqual(view['state'], 'blocked')
        self.assertIsNone(view['active'])
        self.assertIsNone(view['last_cancel_reason'])
        # Diagnostics do not mutate the live timeline or its host overlays.
        self.assertEqual(actions.active(context(), NOW + .2), 'pat')
        self.assertIsNone(actions.snapshot(context(), NOW + .2)['last_cancel_reason'])
        self.assertIsNone(actions.active(blocked, NOW + .3))
        self.assertEqual(actions.snapshot(blocked, NOW + .3)['last_cancel_reason'], 'dragging')
        self.assertIsNone(actions.active(context(), NOW + .4))

    def test_expiration_restores_base_channels_and_idle_snapshot(self):
        for name in ALL_ACTIONS:
            with self.subTest(action=name):
                actions, motion = system()
                self.assertTrue(actions.request(name, context(), NOW))
                end = NOW + ACTIONS[name]['dur'] + .01
                self.assertIsNone(actions.active(context(), end))
                self.assertEqual(actions.snapshot(context(), end)['state'], 'idle')
                self.assertEqual(motion.gaze(end, (.12, .23)), (.12, .23))
                self.assertEqual(motion.breath(end, .42), .42)
                self.assertFalse(motion.holding(end))
                self.assertEqual(motion.due(end), [])

    def test_a_new_request_after_cancellation_starts_without_old_impulses(self):
        actions, motion = system()
        self.assertTrue(actions.request('pat', context(), NOW))
        actions.active(context(sleeping=True), NOW + .1)
        self.assertTrue(actions.request('glance', context(), NOW + .2))
        self.assertEqual(actions.active(context(), NOW + .45), 'glance')
        self.assertEqual(motion.due(NOW + .45), [('hat', .3)])
        self.assertIsNone(actions.snapshot(context(), NOW + .45)['last_cancel_reason'])

    def test_earlier_frame_clock_keeps_new_action_without_early_effects(self):
        for name in ALL_ACTIONS:
            with self.subTest(action=name):
                actions, motion = system()
                born = NOW + .003
                self.assertTrue(actions.request(name, context(), born))
                self.assertEqual(actions.active(context(), NOW), name)
                self.assertEqual(actions.snapshot(context(), NOW)['state'], 'playing')
                base = (.13, -.19)
                self.assertEqual(motion.gaze(NOW, base), base)
                self.assertEqual(motion.breath(NOW, .42), .42)
                self.assertFalse(motion.holding(NOW))
                self.assertEqual(motion.due(NOW), [])
                self.assertEqual(actions.active(context(), born + .05), name)
                self.assertIsNone(actions.active(context(), born + ACTIONS[name]['dur'] + .01))


class PriorityTests(unittest.TestCase):
    def test_agent_reactions_cannot_interrupt_user_touch(self):
        for name in AGENT_ACTIONS:
            with self.subTest(action=name):
                actions, _ = system()
                self.assertTrue(actions.request('pat', context(), NOW))
                result = actions.request(name, context(), NOW + .2, source='agent')
                self.assertFalse(result)
                self.assertEqual(result.reason, 'priority')
                self.assertEqual(actions.active(context(), NOW + .25), 'pat')
                # The rejected request did not restart or extend the original.
                self.assertIsNone(actions.active(context(), NOW + ACTIONS['pat']['dur'] + .01))

    def test_priority_depends_on_action_not_source(self):
        actions, _ = system()
        self.assertTrue(actions.request('pat', context(), NOW, source='demo'))
        result = actions.request('glance', context(), NOW + .1, source='user')
        self.assertFalse(result)
        self.assertEqual(result.reason, 'priority')
        self.assertEqual(actions.active(context(), NOW + .2), 'pat')

    def test_higher_priority_replaces_lower_priority(self):
        actions, _ = system()
        self.assertTrue(actions.request('glance', context(), NOW, source='agent'))
        self.assertTrue(actions.request('nudge', context(), NOW + .1, source='agent'))
        self.assertEqual(actions.active(context(), NOW + .15), 'nudge')
        self.assertTrue(actions.request('pat', context(), NOW + .2))
        self.assertEqual(actions.active(context(), NOW + .25), 'pat')

    def test_equal_priority_replaces_existing_action(self):
        for before, after, source in (('startle', 'nudge', 'agent'),
                                      ('pat', 'flick', 'user')):
            with self.subTest(before=before, after=after):
                actions, _ = system()
                self.assertTrue(actions.request(before, context(), NOW, source=source))
                result = actions.request(after, context(), NOW + .3, source=source)
                self.assertTrue(result)
                self.assertEqual(result.reason, 'started')
                self.assertEqual(actions.active(context(), NOW + .35), after)
                # Expiration belongs to the replacement's start time.
                self.assertEqual(actions.active(context(), NOW + ACTIONS[after]['dur'] + .1), after)
                self.assertIsNone(actions.active(context(), NOW + .3 + ACTIONS[after]['dur'] + .01))

    def test_expired_high_priority_action_does_not_block_new_reaction(self):
        actions, _ = system()
        self.assertTrue(actions.request('pat', context(), NOW))
        later = NOW + ACTIONS['pat']['dur'] + .01
        self.assertTrue(actions.request('glance', context(), later, source='agent'))
        self.assertEqual(actions.active(context(), later + .1), 'glance')


class SnapshotTests(unittest.TestCase):
    def test_snapshot_exposes_only_compact_public_protocol(self):
        actions, _ = system()
        result = actions.request('pat', context(), NOW)
        view = actions.snapshot(context(), NOW + .1)
        self.assertEqual(set(view), {'state', 'active', 'last_request', 'last_cancel_reason'})
        self.assertEqual(view['state'], 'playing')
        self.assertEqual(view['active'], 'pat')
        self.assertEqual(view['last_request'], dict(action=result.action, source=result.source,
                                                   accepted=True, reason='started'))
        self.assertIsNone(view['last_cancel_reason'])
        self.assertIsInstance(json.dumps(view), str)

    def test_rejected_request_is_preserved_for_diagnostics(self):
        actions, _ = system()
        self.assertTrue(actions.request('pat', context(), NOW))
        result = actions.request('glance', context(), NOW + .1, source='agent')
        self.assertFalse(result)
        view = actions.snapshot(context(), NOW + .2)
        self.assertEqual(view['state'], 'playing')
        self.assertEqual(view['active'], 'pat')
        self.assertEqual(view['last_request'], dict(action='glance', source='agent',
                                                   accepted=False, reason='priority'))

    def test_arbitrary_input_is_never_saved_in_snapshot(self):
        marker = 'SYNTHETIC_PRIVATE_TEXT_NOT_FOR_EXPORT'
        requests = (
            dict(name=marker), dict(source=marker),
            dict(name={'prompt': marker}), dict(source={'prompt': marker}),
            dict(now=marker), dict(side=marker),
        )
        for overrides in requests:
            with self.subTest(overrides=overrides):
                actions, _ = system()
                values = dict(name='pat', now=NOW, source='user', side=1)
                values.update(overrides)
                result = actions.request(context=context(), **values)
                self.assertFalse(result)
                view = actions.snapshot(context(), NOW)
                self.assertNotIn(marker, json.dumps(view))
                self.assertIsInstance(view['last_request'], dict)
                saved = view['last_request']
                self.assertIn(saved['action'], ALL_ACTIONS + (None,))
                self.assertIn(saved['source'], SOURCES + (None,))
                self.assertIs(saved['accepted'], False)
                self.assertEqual(saved['reason'], result.reason)

    def test_snapshot_is_a_copy_and_cannot_change_subsequent_result(self):
        actions, _ = system()
        actions.request('pat', context(), NOW)
        view = actions.snapshot(context(), NOW + .1)
        view['active'] = 'unknown'
        view['last_request']['action'] = 'unknown'
        again = actions.snapshot(context(), NOW + .2)
        self.assertEqual(again['active'], 'pat')
        self.assertEqual(again['last_request']['action'], 'pat')


if __name__ == '__main__':
    unittest.main()
