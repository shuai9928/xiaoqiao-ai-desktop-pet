"""Pure director contracts: fake clock/RNG and public resources, no host or AI."""
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
import json
import unittest

from ai_pet import AiPetDirector, LUNAR, TRANSIENT, festival, time_slot


class Rng:
    def __init__(self, chance=.99, last=False):
        self.chance, self.last = chance, last
    def choice(self, values):
        return values[-1] if self.last else values[0]
    def random(self):
        return self.chance
    def uniform(self, low, high):
        return low


class Catalog:
    def __init__(self, greetings=False):
        self.greetings = greetings
        self.count = 2
        self.base = 0
        self.poses = set(('idle', 'listening', 'thinking', 'reading', 'writing',
                          'running', 'searching', 'delegating', 'drawing', 'asking',
                          'happy', 'proud', 'oops', 'surprised', 'pat', 'hum', 'stretch',
                          'yawn', 'sleeping', 'tired', 'sorry', 'deepthink', 'slack',
                          'pout', 'reset', 'eat', 'pop', 'pretend', 'caught', 'bye'))
    def get(self, character):
        return SimpleNamespace(available=True, is_egg=character.endswith('_egg')) if character in (
            'claude', 'codex', 'deepseek', 'gemini', 'glm', 'claude_egg', 'codex_egg') else None
    def has_pose(self, character, pose):
        return pose in self.poses or (self.greetings and isinstance(pose, str) and pose.startswith(('greet_', 'fest_')))
    def resolve(self, character, pose):
        return pose if self.has_pose(character, pose) else 'idle'
    def frame_count(self, character, pose):
        return self.count
    def blink_index(self, character):
        return None if character == 'gemini' else self.base
    def lines(self, character, pose):
        if pose.startswith(('greet_', 'fest_')) and not self.greetings:
            return ()
        return (pose + '台词',) if self.has_pose(character, pose) or pose == 'escape' else ()
    def behavior(self, character):
        data = {'greeting': '你好呀', 'idle_actions': ('slack',), 'poke_pose': 'pout',
                'corrected_pose': 'sorry', 'fx': MappingProxyType({'deepthink': 'bubbles'}),
                'glyph': '·'}
        if character == 'deepseek':
            data['long_think'] = MappingProxyType({'after': 15, 'pose': 'deepthink'})
        if character and character.endswith('_egg'):
            data['egg'] = MappingProxyType({'host': character[:-4], 'caption': '客串', 'aura': 'stars'})
        return MappingProxyType(data)
    def eggs_for(self, character):
        return (character + '_egg',) if character in ('claude', 'codex') else ()


class DirectorTests(unittest.TestCase):
    def make(self, character='claude', *, memory=None, chance=.99, last=False, greetings=False, now=1000):
        catalog = Catalog(greetings)
        d = AiPetDirector(catalog, rng=Rng(chance, last), memory={} if memory is None else memory)
        self.assertTrue(d.set_character(character, now, 'entered'))
        d.tick(now)
        return d

    def test_work_dwell_keeps_only_latest_request(self):
        d = self.make()
        d.on_work('reading', (), 1001)
        self.assertEqual(d.tick(1001).pose, 'idle')
        d.on_work('writing', (), 1002)
        self.assertEqual(d.tick(1002.5).pose, 'writing')
        self.assertEqual(d.tick(1003).pose, 'writing')

    def test_urgent_edges_bypass_dwell_and_done_tool_threshold(self):
        d = self.make()
        for at, event, pose in ((1001, {'kind': 'turn'}, 'listening'),
                                (1001.1, {'kind': 'oops'}, 'oops'),
                                (1001.2, {'kind': 'interrupt'}, 'surprised'),
                                (1001.3, {'kind': 'done', 'n_tools': 7}, 'happy'),
                                (1001.4, {'kind': 'done', 'n_tools': 8}, 'proud')):
            d.on_work(None, (event,), at)
            self.assertEqual(d.tick(at).pose, pose)

    def test_turn_returns_to_thinking_even_without_context_flags(self):
        d = self.make()
        d.on_work(None, ({'kind': 'turn'},), 1001)
        self.assertEqual(d.tick(1003.49).pose, 'listening')
        self.assertEqual(d.tick(1003.5).pose, 'thinking')

    def test_work_lines_throttled_and_emitted_once(self):
        d = self.make()
        d.on_work('reading', (), 1003)
        self.assertEqual(d.tick(1003).say, 'reading台词')
        self.assertEqual(d.tick(1003.1).say, '')
        d.on_work('writing', (), 1006)
        self.assertEqual(d.tick(1006).say, '')
        d.on_work('running', (), 1024)
        self.assertEqual(d.tick(1024).say, 'running台词')
        d.on_work(None, ({'kind': 'done'},), 1025)
        self.assertEqual(d.tick(1025).say, 'happy台词')

    def test_persistent_work_resumes_after_click_and_manual_wake(self):
        d = self.make()
        d.on_work('writing', (), 1003)
        d.tick(1003)
        d.on_click(1004)
        self.assertEqual(d.tick(1004).pose, 'pat')
        d.on_work('writing', (), 1006)
        self.assertEqual(d.tick(1008).pose, 'writing')
        d.set_resting(True, 1009)
        d.on_work('writing', (), 1010)
        d.on_click(1011)
        self.assertEqual(d.tick(1011).pose, 'yawn')
        self.assertEqual(d.tick(1014.1).pose, 'writing')

    def test_turn_listens_then_shows_the_already_observed_work(self):
        # A 2 s snapshot can carry the new turn and its first tool together:
        # after listening, go straight to that tool instead of a filler think.
        d = self.make()
        d.on_work('writing', ({'kind': 'turn'},), 1001)
        self.assertEqual(d.tick(1003.49).pose, 'listening')
        self.assertEqual(d.tick(1003.5).pose, 'writing')

    def test_turn_without_known_work_thinks_after_listening(self):
        d = self.make()
        d.on_work('thinking', ({'kind': 'turn'},), 1001)
        self.assertEqual(d.tick(1003.5).pose, 'thinking')

    def test_transients_have_named_durations(self):
        for pose, duration in TRANSIENT.items():
            with self.subTest(pose=pose):
                d = self.make()
                d._show(pose, 1001, urgent=True)
                self.assertEqual(d.tick(1001 + duration - .01).pose, pose)
                self.assertEqual(d.tick(1001 + duration).pose, 'idle')

    def test_corrected_pose_only_after_recent_error(self):
        d = self.make()
        d.on_work(None, ({'kind': 'oops'},), 1001)
        d.on_work('thinking', ({'kind': 'turn'},), 1100)
        self.assertEqual(d.tick(1100).pose, 'sorry')
        self.assertEqual(d.tick(1103).pose, 'thinking')
        d.on_work(None, ({'kind': 'oops'},), 1104)
        d.on_work('thinking', ({'kind': 'turn'},), 1300)
        self.assertEqual(d.tick(1300).pose, 'listening')

    def test_readonly_nested_long_think_configuration(self):
        d = self.make('deepseek')
        d.on_work('thinking', (), 1003)
        self.assertIsInstance(d.catalog.behavior('deepseek')['long_think'], Mapping)
        self.assertEqual(d.tick(1017.99).pose, 'thinking')
        view = d.tick(1018)
        self.assertEqual((view.pose, view.fx), ('deepthink', 'bubbles'))

    def test_model_context_retains_long_think_until_context_finishes(self):
        d = self.make('deepseek')
        self.assertEqual(d.tick(1003, model_thinking=True).pose, 'thinking')
        for at in (1018, 1018.1, 1021, 1030):
            self.assertEqual(d.tick(at, model_thinking=True).pose, 'deepthink')
        self.assertEqual(d.tick(1033).pose, 'idle')

    def test_real_public_catalog_long_think_is_not_skipped(self):
        from appearance import CharacterCatalog
        cat = CharacterCatalog.load(Path(__file__).resolve().parents[1] / 'assets')
        self.assertTrue(cat.get('deepseek').available, cat.get('deepseek'))
        lt = cat.behavior('deepseek')['long_think']
        self.assertIsInstance(lt, Mapping)
        self.assertNotIsInstance(lt, dict)
        d = AiPetDirector(cat, rng=Rng(), memory={})
        d.set_character('deepseek', 1000, 'entered')
        d.on_work('thinking', (), 1000)
        self.assertEqual(d.tick(1000 + lt['after']).pose, lt['pose'])

    def test_polling_does_not_refresh_quiet_timer(self):
        d = self.make()
        for at in (1100, 1200, 1500):
            d.on_work(None, (), at)
            d.tick(at)
        self.assertEqual(d.tick(1600).pose, 'sleeping')
        self.assertEqual(d.tick(1601).say, '')

    def test_real_activity_wakes_automatic_sleep(self):
        d = self.make()
        self.assertEqual(d.tick(1600).pose, 'sleeping')
        d.on_work('reading', ({'kind': 'activity'},), 1600.1)
        self.assertEqual(d.tick(1600.1).pose, 'reading')

    def test_manual_rest_wins_over_work_context_and_quota(self):
        d = self.make()
        self.assertTrue(d.set_resting(True, 1001))
        d.on_work('reading', ({'kind': 'turn'},), 1002)
        d.set_quota(True, (), 1003)
        self.assertEqual(d.tick(1020, chat_open=True, model_thinking=True).pose, 'sleeping')
        d.on_click(1021)
        view = d.tick(1021)
        self.assertEqual((view.pose, view.say), ('yawn', '唔…你回来啦'))
        self.assertEqual(d.tick(1024).pose, 'reading')
        d.on_work(None, (), 1025)
        self.assertEqual(d.tick(1027).pose, 'tired')

    def test_switch_cancels_timers_work_manual_hold_and_old_lines(self):
        d = self.make()
        d.set_resting(True, 1001)
        d.on_work('thinking', ({'kind': 'turn'},), 1002)
        self.assertTrue(d.set_character('codex', 1003, 'restore'))
        self.assertEqual(d.tick(1003).pose, 'idle')
        self.assertEqual(d.tick(1004).say, '')
        d.on_click(1005)
        d.set_character('claude', 1005.1, 'pinned')
        self.assertEqual(d.tick(1010).pose, 'idle')

    def test_click_and_poke_use_character_lines_and_return(self):
        d = self.make()
        d.on_click(1001)
        self.assertEqual((d.tick(1001).pose, d.tick(1001).say), ('pat', ''))
        d.on_poke(1002)
        self.assertEqual(d.tick(1002).say, 'pout台词')
        self.assertEqual(d.tick(1005.5).pose, 'idle')

    def test_each_explicit_pat_speaks_even_if_pose_stays_pat(self):
        d = self.make()
        d.on_click(1001)
        self.assertEqual(d.tick(1001).say, 'pat台词')
        d.on_click(1001.5)
        self.assertEqual(d.tick(1001.5).say, 'pat台词')
        self.assertEqual(d.tick(1001.6).say, '')

    def test_feed_is_visual_eat_and_wakes_manual_rest(self):
        d = self.make()
        d.set_resting(True, 1001)
        d.on_feed(1002)
        view = d.tick(1002)
        self.assertEqual((view.pose, view.say), ('eat', 'eat台词'))
        self.assertEqual(d.tick(1006).pose, 'idle')

    def test_feed_falls_back_to_character_happy(self):
        d = self.make()
        d.catalog.poses.remove('eat')
        d.on_feed(1001)
        self.assertEqual(d.tick(1001).pose, 'happy')

    def test_variant_rotates_to_different_frame_after_eight_seconds(self):
        d = self.make()
        before = d.tick(1007.99)
        after = d.tick(1008)
        self.assertEqual((before.frame_index, after.frame_index), (0, 1))
        self.assertEqual(after.fade_from, ('claude', 'idle', 0, before.blink))
        self.assertEqual(after.fade_alpha, 0)
        self.assertIsNone(d.tick(1008.36).fade_from)

    def test_blink_only_idle_base_and_exact_140ms(self):
        d = self.make()
        self.assertTrue(d.tick(1003).blink)
        self.assertTrue(d.tick(1003.139).blink)
        self.assertFalse(d.tick(1003.14).blink)
        d.catalog.base = 1
        self.assertFalse(d.tick(1006).blink)
        d.on_work('reading', (), 1007)
        self.assertFalse(d.tick(1010).blink)

    def test_character_without_blink_never_receives_overlay(self):
        d = self.make('gemini')
        self.assertFalse(d.tick(1003).blink)

    def test_reduced_motion_suppresses_blink_fade_motion_fx_and_eggs(self):
        d = self.make(chance=0)
        d.on_work('reading', (), 1003)
        view = d.tick(1003, reduced_motion=True)
        self.assertEqual((view.motion, view.fx, view.blink, view.fade_alpha, view.fade_from),
                         (None, None, False, 1, None))
        d.on_click(1004)
        self.assertIsNone(d.tick(1004, reduced_motion=True).egg)
        self.assertFalse(d.play_egg(1005, force=True))

    def test_chat_listening_bobs_and_context_closing_returns_to_idle(self):
        d = self.make()
        view = d.tick(1003, chat_open=True)
        self.assertEqual((view.pose, view.motion), ('listening', 'bob'))
        self.assertEqual(d.tick(1006).pose, 'idle')

    def test_egg_host_identity_phase_and_catch_timing(self):
        d = self.make()
        self.assertTrue(d.play_egg(1001))
        view = d.tick(1001)
        self.assertEqual((d.character, view.character, view.pose, view.egg['host']),
                         ('claude', 'claude_egg', 'pop', 'claude'))
        self.assertEqual(d.tick(1003.2).pose, 'pretend')
        self.assertEqual(d.tick(1012.2).say, 'pretend台词')
        d.on_click(1013)
        self.assertEqual(d.tick(1013).pose, 'caught')
        self.assertEqual(d.tick(1015).pose, 'bye')
        view = d.tick(1017.2)
        self.assertEqual((view.character, view.pose, view.egg), ('claude', 'idle', None))

    def test_uncaught_egg_escapes_after_forty_seconds(self):
        d = self.make()
        d.play_egg(1001)
        d.tick(1003.2)
        view = d.tick(1043.2)
        self.assertEqual((view.pose, view.say), ('bye', 'escape台词'))
        self.assertIsNone(d.tick(1045.4).egg)

    def test_work_and_character_switch_cancel_egg_without_stale_lines(self):
        d = self.make()
        d.play_egg(1001)
        d.on_work('reading', ({'kind': 'activity'},), 1002)
        self.assertIsNone(d.tick(1002).egg)
        d.on_work(None, (), 1005)
        d.tick(1005)
        self.assertTrue(d.play_egg(1008))
        d.set_character('codex', 1009, 'entered')
        view = d.tick(1050)
        self.assertEqual((view.character, view.pose, view.egg, view.say), ('codex', 'idle', None, ''))

    def test_disabled_eggs_blocks_random_pat_and_explicit_play(self):
        d = self.make(chance=0)
        d.set_eggs_enabled(False)
        self.assertFalse(d.play_egg(1001, force=True))
        d.on_click(1002)
        self.assertEqual(d.tick(1002).pose, 'pat')
        self.assertEqual(d.memory['eggs_enabled'], False)

    def test_random_pat_can_start_only_matching_host_egg(self):
        d = self.make('codex', chance=0)
        d.on_click(1001)
        view = d.tick(1001)
        self.assertEqual((view.character, view.egg['host']), ('codex_egg', 'codex'))
        d.set_character('gemini', 1002, 'entered')
        d.on_click(1003)
        self.assertEqual(d.tick(1003).pose, 'pat')

    def test_broken_egg_can_be_publicly_cancelled_to_host(self):
        d = self.make()
        d.play_egg(1001)
        self.assertTrue(d.cancel_egg(1002))
        self.assertFalse(d.cancel_egg(1002))
        view = d.tick(1002)
        self.assertEqual((view.character, d.character, view.egg), ('claude', 'claude', None))

    def test_quota_tired_and_recovery_survive_memory_reconstruction(self):
        memory = {}
        d = self.make(memory=memory)
        d.set_quota(False, [{'label': '5h', 'used': 90, 'reset': 5000}], 1001)
        self.assertEqual(d.tick(1001).pose, 'tired')
        restored = self.make(memory=json.loads(json.dumps(memory)), now=1002)
        self.assertEqual(restored.tick(1002).pose, 'tired')
        restored.set_quota(False, [{'label': '5h', 'used': 10, 'reset': 5000}], 1003)
        self.assertEqual(restored.tick(1003).pose, 'idle')

    def test_quota_stale_expired_and_other_character_do_not_force_tired(self):
        d = self.make()
        d.set_quota(False, [{'label': '5h', 'used': 100, 'stale': True},
                            {'label': 'week', 'used': 100, 'expired': True}], 1001)
        self.assertEqual(d.tick(1001).pose, 'idle')
        other = self.make('gemini')
        other.set_quota(True, [{'label': '5h', 'used': 100}], 1001)
        self.assertEqual(other.tick(1001).pose, 'idle')

    def test_codex_early_reset_exact_threshold_and_duration(self):
        d = self.make('codex')
        d.set_quota(False, [{'label': '5h', 'used': 80, 'reset': 5000}], 1001)
        d.set_quota(False, [{'label': '5h', 'used': 65, 'reset': 5000}], 1002)
        self.assertEqual(d.tick(1002).pose, 'reset')
        self.assertEqual(d.tick(1008.49).pose, 'reset')
        self.assertEqual(d.tick(1008.5).pose, 'idle')

    def test_codex_reset_requires_same_label_and_original_future_window(self):
        for label, reset, used in (('week', 5000, 60), ('5h', 1602, 60), ('5h', 5000, 66)):
            with self.subTest(label=label, reset=reset, used=used):
                d = self.make('codex')
                d.set_quota(False, [{'label': '5h', 'used': 80, 'reset': reset}], 1001)
                d.set_quota(False, [{'label': label, 'used': used, 'reset': 6000}], 1002)
                self.assertEqual(d.tick(1002).pose, 'idle')

    def test_dev_hold_ignores_work_and_expires_then_can_be_cancelled_by_click(self):
        d = self.make()
        self.assertTrue(d.dev_show('proud', 8, 1001))
        d.on_work('reading', ({'kind': 'oops'},), 1002)
        self.assertEqual(d.tick(1008).pose, 'proud')
        self.assertEqual(d.tick(1009).pose, 'reading')
        self.assertTrue(d.dev_show('thinking', 8, 1010))
        d.on_click(1011)
        self.assertEqual(d.tick(1011).pose, 'pat')

    def test_farewell_blocks_interactions_for_host_exit_delay(self):
        d = self.make()
        self.assertEqual(d.farewell(1001), 2)
        d.on_click(1002)
        d.on_feed(1002)
        d.on_work('reading', ({'kind': 'turn'},), 1002)
        self.assertFalse(d.dev_show('happy', 1, 1002))
        self.assertEqual(d.tick(1004).pose, 'bye')

    def test_farewell_waves_before_last_second_leave_motion(self):
        d = self.make()
        d.farewell(1001)
        view = d.tick(1001)
        self.assertEqual((view.pose, view.motion, view.say), ('bye', 'bob', 'bye台词'))
        self.assertEqual(d.tick(1001.89).motion, 'bob')
        view = d.tick(1001.9)
        self.assertEqual(view.motion, 'leave')
        self.assertAlmostEqual(view.motion_t, 0)

    def test_motion_phase_runs_on_while_the_family_is_unchanged(self):
        # CrossPet keeps the CSS animation when the class stays the same: a
        # rock pose following a rock pose, or a new variant, must not snap back.
        d = self.make()
        d.on_work('thinking', (), 1003)
        self.assertAlmostEqual(d.tick(1003.5).motion_t, .5)
        d.on_work('reading', (), 1006)
        view = d.tick(1006.5)
        self.assertEqual((view.pose, view.motion), ('reading', 'rock'))
        self.assertAlmostEqual(view.motion_t, 3.5)
        view = d.tick(1014)                        # variant rotation keeps the phase too
        self.assertEqual((view.frame_index, view.motion_t), (1, 11))
        d.on_work('writing', (), 1015)
        view = d.tick(1015.25)
        self.assertEqual(view.motion, 'bob')
        self.assertAlmostEqual(view.motion_t, .25)   # a new family starts at its pose change
        d.on_click(1016)
        self.assertEqual(d.tick(1016).motion_t, 0)   # pat sways: new family again

    def test_corrupt_memory_and_unknown_events_are_safe_and_private(self):
        for memory in ({'quota': []}, {'quota': {'claude': []}}, {'greeting_at': []},
                       {'quota': {'claude': {'windows': 42}}, 'greeted': 4}):
            with self.subTest(memory=memory):
                d = self.make(memory=memory)
                d.set_character('codex', 1001, 'foreground')
                d.tick(1001)
                d.set_quota(False, [{'label': '5h', 'used': 10}], 1002)
        d = self.make()
        raw = '秘密聊天全文/private/file'
        d.on_work(raw, [{'kind': 'unknown', 'text': raw}, {'kind': 'done', 'n_tools': True, 'text': raw}], float('nan'))
        self.assertEqual(d.tick(1000).pose, 'happy')
        self.assertNotIn(raw, repr(d.__dict__))
        self.assertFalse(d.dev_show(raw, 2, 1001))
        self.assertFalse(d.set_character('claude_egg', 1002))


class GreetingTests(unittest.TestCase):
    def stamp(self, date):
        return datetime.fromisoformat(date).replace(tzinfo=timezone(timedelta(hours=8))).timestamp()
    def director(self, memory=None):
        return AiPetDirector(Catalog(greetings=True), rng=Rng(), memory={} if memory is None else memory)

    def test_all_slot_boundaries(self):
        for hour, expected in ((0, 'night'), (2, 'dawn'), (5, 'morning'), (11, 'noon'),
                               (14, 'afternoon'), (18, 'evening'), (23, 'night')):
            self.assertEqual(time_slot(datetime(2026, 10, 9, hour)), expected)

    def test_lunar_table_and_festival_precedence(self):
        for year, dates in LUNAR.items():
            for md, name in zip(dates, ('spring', 'lantern', 'dragonboat', 'midautumn')):
                self.assertEqual(festival(datetime.fromisoformat(f'{year}-{md}')), name)
        self.assertEqual(festival(datetime(2031, 10, 1)), 'midautumn')
        for md, name in (('10-31', 'halloween'), ('12-24', 'christmas'), ('12-25', 'christmas'),
                         ('01-01', 'newyear'), ('10-07', 'national')):
            self.assertEqual(festival(datetime.fromisoformat('2026-' + md)), name)
        self.assertIsNone(festival(datetime(2026, 10, 9)))

    def test_five_am_greeting_day_and_persisted_duplicate_suppression(self):
        d = self.director()
        at = self.stamp('2026-10-09T04:50:00')
        d.set_character('claude', at, 'foreground')
        self.assertEqual(d.tick(at).pose, 'greet_dawn')
        self.assertIn('slot:2026-10-08:dawn', d.memory['greeted']['claude'])
        restored = self.director(json.loads(json.dumps(d.memory)))
        restored.set_character('claude', at + 60, 'foreground')
        self.assertEqual(restored.tick(at + 60).say, '')
        next_day = self.stamp('2026-10-09T05:21:00')
        restored.on_work(None, ({'kind': 'activity'},), next_day)
        self.assertEqual(restored.tick(next_day).pose, 'greet_morning')
        self.assertIn('slot:2026-10-09:morning', restored.memory['greeted']['claude'])

    def test_pinned_entered_restore_do_not_emit_entry_greeting(self):
        at = self.stamp('2026-10-09T08:00:00')
        for reason in ('entered', 'pinned', 'restore'):
            d = self.director()
            d.set_character('claude', at, reason)
            view = d.tick(at)
            self.assertEqual((view.pose, view.say), ('idle', ''))

    def test_busy_foreground_greeting_only_speaks_preserving_pose(self):
        d = self.director()
        at = self.stamp('2026-10-09T08:00:00')
        d.set_character('claude', at, 'foreground')
        d.on_work('reading', (), at)
        view = d.tick(at)
        self.assertEqual((view.pose, view.say), ('reading', 'greet_morning台词'))

    def test_festival_precedes_regular_slot_and_uses_six_and_half_seconds(self):
        d = self.director()
        at = self.stamp('2026-10-31T08:00:00')
        d.set_character('claude', at, 'follow')
        self.assertEqual(d.tick(at).pose, 'fest_halloween')
        self.assertEqual(d.tick(at + 6.49).pose, 'fest_halloween')
        self.assertEqual(d.tick(at + 6.5).pose, 'idle')
        self.assertIn('fest:2026-10-31:halloween', d.memory['greeted']['claude'])


if __name__ == '__main__':
    unittest.main()
