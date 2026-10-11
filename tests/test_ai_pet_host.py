"""Actual I47 host glue with public assets and synthetic events only."""
import os
import random
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import appearance
import pet
import ui_themes
from test_appearance import shell


class AiPetHostTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('XIAOQIAO_CHECKS_ISOLATED') != '1':
            raise RuntimeError('Use tools/run_checks.py with synthetic user data')
        self.clock = 1700000000.0
        self.p = shell(ai_announce=False, bubble=None, root=Mock())
        self.p._fg_probe = Mock()
        self.p._fg_probe.current.return_value = None
        self.time_patch = patch('pet.time.time', side_effect=lambda: self.clock)
        self.thread_patch = patch('pet.threading.Thread.start')
        self.time_patch.start()
        self.thread_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.addCleanup(self.thread_patch.stop)
        self.p.set_appearance_mode('ai', pin='claude')
        self.p._ai_pet.rng = random.Random(123)
        self.p._ai_pet.set_eggs_enabled(False)

    def pose(self, advance=0):
        self.clock += advance
        return self.p._static_pose(self.clock)

    def row(self, state, label='读 合成资料', agent='native-claude', **kwargs):
        row = dict(id='simulated-'+agent, agent=agent, state=state,
                   updated=self.clock, since=self.clock, stale=False,
                   actions=[dict(a=label, r='', t=self.clock)])
        row.update(kwargs)
        return row

    def scan(self, rows):
        self.p._ai_work_sessions = rows
        self.p._ai_sessions_scanned = True     # what _scan_ai_sessions marks
        self.p._ai_sync_work(self.clock, rows)

    def test_old_mac_work_is_not_replayed_by_the_first_real_scan(self):
        # Restored in AI mode before any scan: the tracker must take its baseline
        # from the first real scan, not from the empty startup list.
        self.assertFalse(getattr(self.p, '_ai_sessions_scanned', False))
        old = dict(id='mac-claude-old', agent='mac-claude', state='done', updated=self.clock - 3 * 3600,
                   since=self.clock - 3 * 3600 - 60, stale=False, actions=['跑测试 合成'])
        self.scan([old])
        self.assertEqual(self.pose(), 'idle')
        self.scan([dict(old, since=self.clock - 10, updated=self.clock)])   # a genuinely new round
        self.assertIn(self.pose(), ('happy', 'proud'))

    def test_a_failed_look_change_can_be_retried(self):
        selection = self.p._appearance.set_pin('codex')
        with patch.object(pet.Pet, '_apply_look', side_effect=RuntimeError('mid-apply')):
            with self.assertRaises(RuntimeError):
                self.p._apply_selection(selection)
        self.assertIsNone(self.p._applied_look)
        self.p._apply_selection(selection)                 # retried, not skipped as applied
        self.assertEqual(self.p._ui_theme.key, 'codex')

    def test_visual_sleep_does_not_mutate_xiaoqiao_nap_or_physics(self):
        scene = self.p._swing = {'sentinel': object()}
        self.p._nap_on_swing = False
        self.p.sfx = Mock()
        self.p.go_sleep()
        self.assertEqual(self.pose(), 'sleeping')
        self.assertTrue(self.p._is_resting())
        self.assertFalse(self.p._nap_on_swing)
        self.assertIs(self.p._swing, scene)
        self.p.wake_up()
        self.assertEqual(self.pose(), 'yawn')
        self.assertFalse(self.p._is_resting())
        self.p.sfx.play.assert_not_called()

    def test_automatic_xiaoqiao_timer_does_not_sleep_ai_at_75_seconds(self):
        self.p._nap_on_swing = True
        self.assertNotEqual(self.pose(76), 'sleeping')
        self.assertEqual(self.pose(525), 'sleeping')
        self.p._static_click()
        self.assertEqual(self.pose(), 'yawn')

    def test_explicit_rest_resists_work_until_user_wakes(self):
        self.p.go_sleep()
        self.scan([self.row('running', '改 合成模块')])
        self.assertEqual(self.pose(3), 'sleeping')
        self.p._static_click()
        self.assertEqual(self.pose(), 'yawn')
        self.assertEqual(self.pose(3.1), 'writing')

    def test_ai_interactions_never_give_xiaoqiao_rewards_voice_or_impulses(self):
        self.p._nap_on_swing = True
        for name in ('gain_star', '_count_today', '_wake_from_nap', 'pet_head', '_swing_impulse'):
            setattr(self.p, name, Mock())
        self.p.sfx = Mock()
        self.p.request_pat()
        self.assertEqual(self.pose(), 'pat')
        self.p._static_poke()
        self.assertEqual(self.pose(), 'surprised')
        self.p.eat_candy()
        self.assertEqual(self.pose(), next((pose for pose in ('eat','feast') if self.p._appearance.catalog.has_pose('claude',pose)), 'happy'))
        self.assertTrue(self.p._nap_on_swing)
        for name in ('gain_star', '_count_today', '_wake_from_nap', 'pet_head', '_swing_impulse'):
            getattr(self.p, name).assert_not_called()
        self.p.sfx.play.assert_not_called()

    def test_back_to_xiaoqiao_cancels_ai_timer_and_preserves_old_nap(self):
        self.p._nap_on_swing = True
        self.p.request_pat()
        self.assertEqual(self.pose(), 'pat')
        self.p.set_appearance_mode('xiaoqiao')
        self.assertIsNone(self.p._ai_pet)
        self.assertIsNone(self.p._static_look((172,194)))
        self.assertTrue(self.p._nap_on_swing)
        self.p.set_appearance_mode('ai', pin='claude')
        self.assertEqual(self.pose(), 'idle')

    def test_background_turn_never_changes_selection_or_theme(self):
        self.p.set_appearance_pin('auto')
        self.scan([self.row('running', '收到新任务', agent='native-codex')])
        self.assertEqual(self.p._appearance.selection.character, 'claude')
        self.assertEqual(self.p._ui_theme.key, 'claude')
        self.assertEqual(self.pose(), 'idle')

    def test_entering_ai_mode_uses_foreground_not_background_activity(self):
        self.p.set_appearance_mode('xiaoqiao')
        self.p._ai_work_sessions = [self.row('running', agent='native-codex')]
        self.p._fg_probe.current.return_value = 'ZCode.exe'
        self.p.set_appearance_mode('ai', pin='auto')
        self.assertEqual(self.p._appearance.selection.character, 'glm')
        self.assertEqual(self.p._ui_theme.label, '墨夜狐影')

    def test_selected_work_drives_read_write_ask_and_completion_only(self):
        self.scan([self.row('running', '读 合成资料')])
        self.assertEqual(self.pose(3), 'reading')
        self.scan([self.row('running', '改 合成模块')])
        self.assertEqual(self.pose(3), 'writing')
        self.scan([self.row('waiting', '问你问题')])
        self.assertEqual(self.pose(3), 'asking')
        self.scan([self.row('done', '本轮已结束')])
        self.assertEqual(self.pose(), 'happy')
        self.assertEqual(self.pose(5.1), 'idle')

    def test_expired_quota_is_not_current_low_energy(self):
        self.p._quota = {'t':(self.clock-4000)*1000, 'fh':99, 'sd':99}
        self.scan([])
        self.assertEqual(self.pose(), 'idle')
        self.p._quota = {'t':self.clock*1000, 'fh':99, 'sd':60}
        self.scan([])
        self.assertEqual(self.pose(), 'tired')
        self.assertEqual(self.p._ui_theme.key, 'claude')

    def test_reduced_motion_removes_transform_fx_blink_and_fades(self):
        self.p._static_click()
        view = self.p._ai_view(self.clock)
        self.assertEqual(view.pose, 'pat')
        self.assertIsNone(view.motion)
        self.assertIsNone(view.fx)
        self.assertFalse(view.blink)
        self.assertEqual(view.fade_alpha, 1)
        frame, dy = self.p._static_look((172,194))
        self.assertEqual(dy, 0)
        self.assertGreater(frame.image.getbbox()[2], 0)

    def test_broken_main_pack_falls_back_with_theme_same_frame(self):
        with patch.object(self.p._appearance.catalog, '_native', return_value=None):
            self.assertIsNone(self.p._static_look((172,194)))
        self.assertEqual(self.p._appearance.selection.character, 'xiaoqiao')
        self.assertIs(self.p._ui_theme, ui_themes.XIAOQIAO)
        self.assertIsNone(self.p._ai_pet)

    def test_pose_demo_is_bounded_and_does_not_change_mode_or_selection(self):
        before = self.p._appearance.selection.cache_key
        self.p._exec_cmd({'op':'ai_pose','pose':'running','secs':999999})
        self.assertEqual(self.pose(), 'running')
        self.assertEqual(self.pose(15.1), 'idle')
        self.assertEqual(self.p._appearance.selection.cache_key, before)
        self.p._exec_cmd({'op':'ai_pose','pose':'../escape','secs':5})
        self.assertEqual(self.pose(), 'idle')

    def test_quit_schedules_real_farewell_and_is_idempotent(self):
        self.p._finish_quit = Mock()
        self.p.quit()
        self.assertEqual(self.pose(), 'bye')
        self.p.root.after.assert_called_once()
        delay, callback = self.p.root.after.call_args.args
        self.assertEqual(delay, 2000)
        self.p.quit()
        self.p.root.after.assert_called_once()
        self.p._finish_quit.assert_not_called()
        callback()
        self.p._finish_quit.assert_called_once()

    def test_mode_switch_discards_only_old_visual_bubble(self):
        self.p.set_appearance_mode('xiaoqiao')
        history = self.p.chat_log = [{'who':'you', 'text':'synthetic saved message'}]
        self.p.bubble = ('old Xiaoqiao feedback', self.clock)
        self.p.set_appearance_mode('ai', pin='claude')
        self.assertIsNone(self.p.bubble)
        self.assertIs(self.p.chat_log, history)

    def test_old_notification_does_not_reply_or_speak_in_ai_mode(self):
        self.p._reply = Mock()
        self.p._speak = Mock()
        with patch('agent_companion.acknowledge_hook') as ack:
            self.p._exec_cmd({'op':'announce', 'text':'synthetic notification'})
        ack.assert_called_once_with(self.p, self.clock)
        self.p._reply.assert_not_called()
        self.p._speak.assert_not_called()

    def test_hidden_particles_do_not_swallow_ai_press(self):
        self.p._swing = {'ui_hits':[]}
        self.p._book_open = self.p._crystal_open = False
        catches = ('_catch_collect','_pop_bubble','_catch_ball','_catch_leaf',
                   '_catch_flower','_catch_snow','_wake_from_nap')
        for name in catches:
            setattr(self.p, name, Mock(return_value=True))
        e = SimpleNamespace(x=30, y=100, x_root=500, y_root=600)
        with patch('flat_workspace.bar_input', return_value=False):
            self.p.on_press(e)
        self.assertEqual(self.p._scene_drag['mx'], 500)
        for name in catches:
            getattr(self.p, name).assert_not_called()

    def test_farewell_cannot_be_interrupted_by_foreground_or_mode_switch(self):
        self.p.set_appearance_pin('auto')
        self.p._finish_quit = Mock()
        self.p.quit()
        self.p._fg_probe.current.return_value = 'ChatGPT.exe'
        self.p._poll_foreground(self.clock)
        self.p.set_appearance_mode('xiaoqiao')
        self.p.set_appearance_pin('codex')
        self.assertEqual(self.p._appearance.selection.character, 'claude')
        self.assertEqual(self.pose(1), 'bye')
        self.assertEqual(self.p.root.after.call_args.args[0], 2000)

    def test_ai_chat_cannot_use_xiaoqiao_voice(self):
        self.p.tts_on = self.p.sound_on = True
        self.p._tts_render = Mock()
        self.p._tts_play = Mock()
        self.p._speak_sapi = Mock()
        self.p._speak_lock = threading.Lock()
        with patch('pet.threading.Thread') as worker:
            self.p._speak('synthetic reply')
            worker.assert_not_called()
        self.p._tts_render.assert_not_called()
        self.p._tts_play.assert_not_called()
        self.p._speak_sapi.assert_not_called()

    def test_playing_speech_is_closed_on_mode_switch_without_fallback(self):
        self.p.set_appearance_mode('xiaoqiao')
        self.p._tts_n, self.p.tts_volume = 0, 50
        commands = []
        def mci(command):
            commands.append(command)
            if command.startswith('play '):
                self.p.set_appearance_mode('ai', pin='claude')
            return 0, ''
        with patch('pet.mci', side_effect=mci):
            self.assertFalse(self.p._tts_play('synthetic.mp3'))
        self.assertGreaterEqual(commands.count('close pettts0'), 3)
        self.assertIsNone(self.p._tts_alias)

    def test_switching_mode_terminates_only_owned_sapi_child(self):
        self.p.set_appearance_mode('xiaoqiao')
        proc = Mock()
        proc.poll.return_value = None
        proc.communicate.side_effect = lambda **kw: self.p.set_appearance_mode('ai', pin='claude')
        with patch('pet.subprocess.Popen', return_value=proc) as start:
            self.p._speak_sapi('synthetic reply')
        self.assertEqual(start.call_count, 1)
        proc.terminate.assert_called()
        self.assertIsNone(self.p._sapi_process)

    def test_inflight_synthesis_cannot_play_after_entering_ai_mode(self):
        self.p.set_appearance_mode('xiaoqiao')
        self.p.tts_on = self.p.sound_on = True
        self.p._speak_lock = threading.Lock()
        def render(text):
            self.p.set_appearance_mode('ai', pin='claude')
            return 'synthetic.mp3'
        self.p._tts_render = Mock(side_effect=render)
        self.p._tts_play = Mock()
        self.p._speak_sapi = Mock()
        with patch('pet.threading.Thread') as worker:
            self.p._speak('synthetic reply')
            callback = worker.call_args.kwargs['target']
        callback()
        self.p._tts_render.assert_called_once()
        self.p._tts_play.assert_not_called()
        self.p._speak_sapi.assert_not_called()


if __name__ == '__main__':
    unittest.main()
