"""Independent I-45 Tk wiring checks with synthetic state and public assets.

Run through tools/run_checks.py: no normal Pet instance, files, AI or foreground
probe are started. Real ChatBox/Card widgets exercise the production callbacks.
"""
import gc
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import pet
import agent_companion
import appearance
import flat_workspace
import life
import ui_themes
from agent_reactions import Reaction
from PIL import Image, ImageDraw


def make_host(root):
    p = pet.Pet.__new__(pet.Pet)
    p.root = root
    p.settings = {}
    p._flat_panel_style = True
    p._appearance = None
    p._ui_theme = ui_themes.XIAOQIAO
    p.state = 'swing'
    p._nap_on_swing = True
    p._swing = {'geo': {'flat': True}, 'synthetic_identity': object()}
    p.drag = p._scene_drag = None
    p.click_token = 0
    p.chatbox = p.action_card = None
    p.sw, p.sh = 1366, 768
    p.x, p.fy, p.W, p.H = 600, 620, 400, 400
    p.star = 76
    p.brain = None
    p.chat_log = []
    p.thinking_now = p.ai_thinking = False
    p._ai_work_sessions = []
    p.ui_reduced_anim = True
    p.t0 = time.time()
    p.last_interact = 0.0
    p.companion_days = lambda: 12
    p.affection_level = lambda: '亲密伙伴'
    p._today_summary = lambda limit=None: '合成陪伴记录'
    for name in ('save_settings', 'say', '_log_exc', 'ask_ai', 'open_chat',
                 'open_ai_panel', 'open_room_preview', 'eat_candy', 'pet_head',
                 'wake_up', 'go_sleep', '_show_full_menu'):
        setattr(p, name, Mock())
    return p


class AppearanceRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('XIAOQIAO_CHECKS_ISOLATED') != '1':
            raise RuntimeError('Run Tk appearance checks through the isolated runner')

    def setUp(self):
        # A Tk failure is a real test error, never an unreported skipped check.
        self.clock = patch('pet.time.time', return_value=10000.0)
        self.clock.start();self.addCleanup(self.clock.stop)
        probe = patch('foreground_ai.ForegroundProcess.current', return_value=None)
        warmup = patch('pet.threading.Thread.start')
        probe.start();warmup.start()
        self.addCleanup(probe.stop);self.addCleanup(warmup.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.callbacks = []
        self.root.report_callback_exception = lambda *args: self.callbacks.append(str(args[1]))
        self.p = make_host(self.root)
        self.area = patch.object(pet, 'work_area_at', return_value=(0, 0, 1366, 728))
        self.area.start()
        self.addCleanup(self.area.stop)

    def tearDown(self):
        try:
            self.p.close_action_card()
            if self.p.chatbox is not None:
                self.p.chatbox.close()
            self.root.update_idletasks()
            self.assertEqual(self.callbacks, [])
        finally:
            self.root.destroy()

    def chat(self):
        self.p.chatbox = chat = pet.ChatBox(self.p)
        self.root.update()
        return chat

    def assert_switch(self, mode, pin=None):
        self.assertTrue(self.p.set_appearance_mode(mode, pin=pin))
        self.root.update()
        self.p._log_exc.assert_not_called()
        self.assertEqual(self.p.appearance_mode(), mode)
        self.assertTrue(self.p._nap_on_swing)
        self.p.ask_ai.assert_not_called()
        self.p.wake_up.assert_not_called()

    def assert_images_alive(self, chat):
        gc.collect()
        live = set(chat.win.tk.call('image', 'names'))
        for name in chat.log.image_names():
            image = str(chat.log.image_cget(name, 'image'))
            self.assertIn(image, live, (name, image))
        for button, _, _, _ in chat._control_specs:
            for image in button._imgs.values():
                self.assertIn(str(image), live)
        self.assertIn(str(chat._bg_photo), live)
        self.assertIn(str(chat._field_img), live)

    def prepare_seated_action_host(self):
        p = self.p
        p.ui_reduced_anim = p._nap_on_swing = False
        p.life = life.LifeMotion()
        p.cfg = {}
        p.blink_until = p._lid_until = 0.0
        p._lid_pending = p._mouth = None
        p._swing['pend'] = life.Pendulum(period=3.4, idle_amp=.075)
        p.last_interact = 9900.0
        return p

    def test_normal_card_mode_buttons_reopen_atomically_and_keep_nap_and_position(self):
        scene = self.p._swing
        self.p.open_action_card(260, 180)
        self.root.update()
        first = self.p.action_card
        self.assertIsNotNone(first)
        self.assertEqual(self.p.appearance_mode(), 'xiaoqiao')
        self.assertIsNone(self.p._appearance)  # Opening the card does not load AI packs.
        xy = first.win.winfo_x(), first.win.winfo_y()
        first.mode_buttons['ai'].invoke()
        self.root.update()
        second = self.p.action_card
        self.assertTrue(first.closed)
        self.assertIsNot(first, second)
        self.assertEqual(self.p.appearance_mode(), 'ai')
        self.assertTrue(self.p._static_active())
        self.assertEqual(second.T, self.p._ui_theme.card)
        self.assertEqual((second.win.winfo_x(), second.win.winfo_y()), xy)
        self.assertEqual(str(second.mode_buttons['ai'].cget('background')), second.T['accent'])
        self.assertEqual(second.buttons['睡觉'].cget('text'), '睡觉')
        # The hidden Xiaoqiao nap does not put a newly selected AI to sleep.
        second.mode_buttons['xiaoqiao'].invoke()
        self.root.update()
        third = self.p.action_card
        self.assertTrue(second.closed)
        self.assertEqual(self.p.appearance_mode(), 'xiaoqiao')
        self.assertEqual(third.T, ui_themes.XIAOQIAO.card)
        self.assertIs(self.p._swing, scene)
        self.assertTrue(self.p._nap_on_swing)
        self.assertIsNone(self.p.chatbox)
        self.p.wake_up.assert_not_called()
        self.p._log_exc.assert_not_called()

    def test_open_chat_switches_all_themes_in_place_without_losing_draft_or_history(self):
        self.p.chat_log = [
            {'role': 'user', 'text': '合成历史问题', 't': 1700000000},
            {'role': 'qiao', 'text': '合成历史回答', 't': 1700000020},
        ]
        chat = self.chat()
        chat.draft.set('尚未发送的合成草稿')
        chat.hist = ['发送过的合成文本']
        chat.hist_i, chat.hist_draft = 1, '历史导航草稿'
        chat.entry.icursor(4)
        chat.entry.selection_range(1, 3)
        text = chat.log.get('1.0', 'end')
        metadata = dict(chat._message_images)
        window, entry, log = chat.win, chat.entry, chat.log
        for theme_key in ('claude', 'codex', 'gemini', 'deepseek', 'xiaoqiao'):
            if theme_key == 'xiaoqiao':
                self.assert_switch('xiaoqiao')
            else:
                self.assert_switch('ai', theme_key)
            self.assertIs(chat.win, window)
            self.assertIs(chat.entry, entry)
            self.assertIs(chat.log, log)
            self.assertEqual(chat._theme_key, theme_key)
            self.assertIs(chat.A, ui_themes.theme(theme_key).apple)
            self.assertEqual(chat.draft.get(), '尚未发送的合成草稿')
            self.assertEqual(chat.hist, ['发送过的合成文本'])
            self.assertEqual((chat.hist_i, chat.hist_draft), (1, '历史导航草稿'))
            self.assertEqual(chat.entry.index('insert'), 4)
            self.assertEqual((chat.entry.index('sel.first'), chat.entry.index('sel.last')), (1, 3))
            self.assertEqual(chat.log.get('1.0', 'end'), text)
            self.assertEqual(chat._message_images, metadata)
            self.assertEqual(str(chat.log.cget('background')), chat.A.hexc(chat.A.BG))
            self.assertEqual(str(chat.entry.cget('background')), chat.A.hexc(chat.A.ELEV))
            self.assertEqual(str(chat.send_btn.cget('state')), 'normal')
            self.assert_images_alive(chat)

    def test_retheme_preserves_reading_scroll_selection_and_focused_entry(self):
        chat = self.chat()
        for i in range(24):
            chat.log_reply(f'第 {i} 条合成记录，供滚动与换色回归检查。')
        self.root.update()
        chat.log.yview_moveto(.3)
        chat.log.tag_add('sel', '2.0', '2.1')
        chat.win.focus_force()
        chat.entry.focus_set()
        self.root.update()
        view = chat.log.yview()
        top_index = chat.log.index('@0,0')
        selection = tuple(chat.log.tag_ranges('sel'))
        self.assertLess(view[1], .99)  # This actually tests reading older messages.
        self.assertIs(chat.win.focus_get(), chat.entry)
        self.assert_switch('ai', 'claude')
        self.assertEqual(chat.log.index('@0,0'), top_index)
        self.assertAlmostEqual(chat.log.yview()[0], view[0], places=6)
        self.assertEqual(tuple(chat.log.tag_ranges('sel')), selection)
        self.assertIs(chat.win.focus_get(), chat.entry)

    def test_pending_typing_timer_survives_switch_and_is_removed_without_history_pollution(self):
        chat = self.chat()
        chat.log_reply('合成上一条回答')
        text = chat._text_without_typing()
        metadata = dict(chat._message_images)
        self.p.ai_thinking = True
        chat.show_typing(True)
        chat.win.after_cancel(chat._typing)
        chat._typing = chat.win.after(60000, lambda: chat._typing_tick(0))
        timer, name = chat._typing, chat._typing_name
        self.assertIsNotNone(timer)
        self.assert_switch('ai', 'deepseek')
        self.assertEqual(chat._typing, timer)
        self.assertEqual(chat._typing_name, name)
        self.assertEqual(chat._message_images, metadata)
        self.assertEqual(chat._text_without_typing(), text)
        self.assert_images_alive(chat)
        # Run the same production callback directly; no timing sleep or model.
        chat.win.after_cancel(chat._typing)
        chat._typing_tick(2)
        self.assertIsNotNone(chat._typing)
        self.assertNotEqual(chat._typing, timer)
        self.assert_switch('ai', 'gemini')
        self.assert_images_alive(chat)
        self.p.ai_thinking = False
        chat.show_typing(False)
        self.assertIsNone(chat._typing)
        self.assertNotIn(name, chat.log.image_names())
        self.assertEqual(chat._message_images, metadata)
        self.assertEqual(chat._text_without_typing(), text)
        self.assertEqual(self.p.chat_log, [])

    def test_repeated_reply_metadata_and_count_remain_usable_after_switch(self):
        chat = self.chat()
        chat.log_reply('合成重复回答', 1700000000)
        chat.log_reply('合成重复回答', 1700000010)
        message_name = chat._last_msg[4]
        self.assertEqual(chat._message_images[message_name], ('qiao', '合成重复回答', 2))
        self.assert_switch('ai', 'codex')
        self.assertEqual(chat._last_msg[4], message_name)
        self.assertEqual(str(chat._last_msg[5]), str(chat.log.image_cget(message_name, 'image')))
        chat.log_reply('合成重复回答', 1700000020)
        self.assertEqual(chat._message_images[message_name], ('qiao', '合成重复回答', 3))
        self.assertEqual(chat.log.get('1.0', 'end').count('合成重复回答'), 1)
        self.assertIn('×3', chat.log.get('1.0', 'end'))
        self.assert_images_alive(chat)

    def test_button_callbacks_hold_the_new_images_and_disabled_send_stays_disabled(self):
        chat = self.chat()
        old_dict = chat.send_btn._imgs
        old_normal = str(old_dict['normal'])
        self.assert_switch('ai', 'gemini')
        self.assertIs(chat.send_btn._imgs, old_dict)
        self.assertNotEqual(str(old_dict['normal']), old_normal)
        chat.send_btn.event_generate('<Enter>')
        self.root.update()
        self.assertEqual(str(chat.send_btn.cget('image')), str(old_dict['disabled']))
        chat.draft.set('准备发送的合成草稿')
        chat.send_btn.event_generate('<Enter>')
        self.root.update()
        self.assertEqual(str(chat.send_btn.cget('image')), str(old_dict['hover']))
        chat.send_btn.event_generate('<Leave>')
        self.root.update()
        self.assertEqual(str(chat.send_btn.cget('image')), str(old_dict['normal']))
        chat.send_btn.invoke()
        self.p.ask_ai.assert_called_once_with('准备发送的合成草稿')
        self.assertEqual(chat.hist, ['准备发送的合成草稿'])
        self.assertEqual(chat.draft.get(), '')
        self.assertEqual(str(chat.send_btn.cget('state')), 'disabled')

    def test_resource_fallback_rethemes_an_open_chat_without_losing_its_content(self):
        chat = self.chat()
        chat.draft.set('素材损坏也应保留的合成草稿')
        chat.log_reply('素材损坏也应保留的合成记录')
        text = chat.log.get('1.0', 'end')
        self.assert_switch('ai', 'gemini')
        with patch.object(self.p._appearance.catalog, '_native', return_value=None):
            self.assertIsNone(self.p._static_look((164, 194)))
        self.root.update()
        self.assertEqual(self.p._appearance.selection.character, 'xiaoqiao')
        self.assertEqual(self.p._ui_theme.key, 'xiaoqiao')
        self.assertEqual(chat._theme_key, 'xiaoqiao')
        self.assertEqual(chat.draft.get(), '素材损坏也应保留的合成草稿')
        self.assertEqual(chat.log.get('1.0', 'end'), text)
        self.assertTrue(self.p._nap_on_swing)
        self.assert_images_alive(chat)
        self.p._log_exc.assert_not_called()

    def test_closed_chat_and_invalid_mode_are_safe_without_reopening_or_model_calls(self):
        chat = self.chat()
        chat.close()
        self.assert_switch('ai', 'claude')
        before = self.p._appearance_state()
        saves = self.p.save_settings.call_count
        self.assertFalse(self.p.set_appearance_mode('unknown'))
        self.assertEqual(self.p._appearance_state(), before)
        self.assertEqual(self.p.save_settings.call_count, saves)
        self.assertFalse(chat.win.winfo_exists())
        self.assertIs(self.p.chatbox, chat)
        self.p._log_exc.assert_not_called()

    def test_automatic_follow_saves_last_for_reconstruction_only_when_it_changes(self):
        self.assert_switch('ai', 'auto')
        self.assertEqual(self.p._appearance.selection.character, 'claude')
        self.p.save_settings.reset_mock()
        self.p._fg_probe = Mock()
        self.p._fg_probe.current.return_value = 'ChatGPT.exe'
        with patch('pet.time.monotonic', return_value=100.0):
            self.p._poll_foreground(1000.0)
        self.p.save_settings.assert_not_called()  # Not stable for half a second yet.
        with patch('pet.time.monotonic', return_value=100.6):
            self.p._poll_foreground(1000.6)
        self.assertEqual(self.p._appearance.selection.character, 'codex')
        self.assertEqual(self.p._ui_theme.key, 'codex')
        self.assertEqual(self.p.settings['appearance_last'], 'codex')
        self.p.save_settings.assert_called_once()
        restored = appearance.AppearanceSelector(self.p._appearance.catalog, dict(self.p.settings))
        self.assertEqual((restored.mode, restored.pin, restored.selection.character,
                          restored.selection.theme), ('ai', 'auto', 'codex', 'codex'))
        self.p._fg_probe.current.return_value = 'explorer.exe'
        with patch('pet.time.monotonic', return_value=101.0):
            self.p._poll_foreground(1001.0)
        self.p.save_settings.assert_called_once()  # Unknown apps do not rewrite settings.
        self.assertEqual(self.p._appearance.selection.character, 'codex')
        self.assertTrue(self.p._nap_on_swing)
        self.p.wake_up.assert_not_called()

    def test_unconfigured_pose_uses_same_pack_idle_but_lost_configured_pose_drops_the_pack(self):
        # Mutate only a private temporary copy of the public character files.
        with tempfile.TemporaryDirectory(prefix='appearance-pose-boundary-') as folder:
            root = Path(folder)
            shutil.copytree(Path(pet.ASSETS) / 'characters', root / 'characters')
            manifest_path = root / 'characters' / 'gemini' / 'manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            waiting_file = manifest['poses']['asking'][0]['file']
            without_waiting = dict(manifest, poses=dict(manifest['poses']))
            del without_waiting['poses']['asking']
            del without_waiting['poses']['listening']
            manifest_path.write_text(json.dumps(without_waiting), encoding='utf-8')
            catalog = appearance.CharacterCatalog.load(root)
            self.assertTrue(catalog.get('gemini').available)
            self.p._ai_pet = None
            self.p._applied_look = None
            self.p._appearance = appearance.AppearanceSelector(catalog, {})
            self.assert_switch('ai', 'gemini')
            self.p._ai_pet_ready().dev_show('asking', 15, time.time())
            frame, _ = self.p._static_look((164, 194))
            self.assertEqual(frame.pose, 'idle')
            self.assertEqual(self.p._appearance.selection.character, 'gemini')
            self.assertEqual(self.p._ui_theme.key, 'gemini')
            # The exact same request with an explicitly declared file that
            # disappears after validation must NOT borrow a healthy idle image.
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            catalog = appearance.CharacterCatalog.load(root)
            self.assertTrue(catalog.get('gemini').available)
            self.p._ai_pet = None
            self.p._applied_look = None
            self.p._appearance = appearance.AppearanceSelector(catalog, {})
            self.assert_switch('ai', 'gemini')
            self.p._ai_pet_ready().dev_show('asking', 15, time.time())
            (manifest_path.parent / waiting_file).unlink()
            self.assertIsNone(self.p._static_look((164, 194)))
            self.assertFalse(catalog.get('gemini').available)
            selection = self.p._appearance.selection
            self.assertEqual((selection.character, selection.theme, selection.renderer),
                             ('xiaoqiao', 'xiaoqiao', 'legacy'))
            self.assertEqual(self.p._ui_theme.key, 'xiaoqiao')
            self.assertEqual(self.p.settings['appearance_pin'], 'auto')
            self.assertTrue(self.p._nap_on_swing)

    def test_flat_first_fallback_frame_draws_xiaoqiao_with_its_theme_and_caches_that_theme(self):
        self.assert_switch('ai', 'gemini')
        self.p._swing.update({
            'geo': {'u': 1.0, 'k': .2, 'O': (0, 0), 'flat': True},
            'ui': {'now': 1700000000.0, 'sessions': [], 'sources': [],
                   'sel_session': None, 'quota': None, 'codex_quota': None, 'mock': True},
            'scene_l': 0, 'scene_t': 0, 'theta': 0,
        })
        self.p.hwnd = 1  # push_layered below is mocked: never touches a real window.
        self.p._flat_mode = 'live'
        self.p._ac = lambda canvas, image, x, y: canvas.alpha_composite(image, (round(x), round(y)))
        marker = (210, 55, 120, 255)

        def paint_builtin(owner, canvas, swing, geo):
            # Isolate theme/role ordering from the already-tested contact mesh.
            ImageDraw.Draw(canvas).rectangle((80, flat_workspace.PY + 50,
                                              82, flat_workspace.PY + 52), fill=marker)

        with patch.object(self.p._appearance.catalog, '_native', return_value=None), \
             patch.object(flat_workspace, 'paint_xiaoqiao', side_effect=paint_builtin) as painter, \
             patch('agent_companion.paint_effect'), patch('pet.push_layered') as push:
            flat_workspace.push(self.p, None)
            first = push.call_args.args[1]
            self.assertEqual(self.p._appearance.selection.character, 'xiaoqiao')
            self.assertEqual(self.p._ui_theme.key, 'xiaoqiao')
            self.assertEqual(first.getpixel((81, flat_workspace.PY + 51)), marker)
            expected = Image.new('RGB', (1, 1), ui_themes.XIAOQIAO.panel['BG']).getpixel((0, 0))
            self.assertEqual(first.getpixel((300, flat_workspace.PY + 100))[:3], expected)
            self.assertEqual(self.p._flat_cache[0][-1], 'xiaoqiao')
            flat_workspace.push(self.p, None)
            second = push.call_args.args[1]
            self.assertEqual(second.tobytes(), first.tobytes())
            self.assertEqual(painter.call_count, 2)
        self.p._log_exc.assert_not_called()

    def test_switch_to_ai_immediately_cancels_real_action_expressions_and_later_impulses(self):
        p = self.prepare_seated_action_host()
        # glance has a future hat impulse; push owns a short laughing mouth.
        # Each must be cancelled synchronously, before a later animation tick.
        for action, born in (('glance', 10000.0), ('push', 10010.0)):
            with self.subTest(action=action):
                with patch('pet.time.time', return_value=born):
                    self.assertTrue(p.perform_action(action))
                motion = p._seat_motion
                self.assertEqual(motion.name, action)
                token = p._action_expression_token
                self.assertIs(p._lid_owner, token)
                if action == 'push':
                    self.assertEqual(p._mouth[0], 'laugh')
                    self.assertIs(p._mouth_owner, token)
                with patch('pet.time.time', return_value=born + .05):
                    self.assertTrue(p.set_appearance_mode('ai', pin='claude'))
                self.assertIsNone(motion.name)
                self.assertIsNone(p._action_expression_token)
                self.assertIsNone(p._lid_owner)
                self.assertLessEqual(p._lid_until, born + .05)
                self.assertIsNone(p._lid_pending)
                self.assertIsNone(p._mouth)
                self.assertEqual(motion.due(born + 1), [])
                # A fast return to the still-visible swing cannot resume it.
                with patch('pet.time.time', return_value=born + .1):
                    self.assertTrue(p.set_appearance_mode('xiaoqiao'))
                self.assertIsNone(p._active_seat(born + .2))
                pend = p._swing['pend']
                with patch.object(p.life.hat_rot, 'impulse', wraps=p.life.hat_rot.impulse) as hat, \
                     patch.object(pend, 'impulse', wraps=pend.impulse) as swing:
                    p._seat_swing_step(p._swing, .02, born + 1)
                hat.assert_not_called()
                swing.assert_not_called()
                self.assertIsNone(motion.name)
        p._log_exc.assert_not_called()

    def test_switch_discards_the_actions_queued_lid_but_keeps_an_unrelated_expression(self):
        p = self.prepare_seated_action_host()
        p._offer_lid(.34, 'sad', 10000.0, hold=5.0)
        with patch('pet.time.time', return_value=10000.0):
            self.assertTrue(p.perform_action('pat'))
        self.assertIs(p._lid_pending_owner, p._action_expression_token)
        self.assertEqual(p._lid_pending[1], 'shy')
        original = (p._lid, p._lid_mode, p._lid_until)
        with patch('pet.time.time', return_value=10000.05):
            self.assertTrue(p.set_appearance_mode('ai', pin='codex'))
        self.assertIsNone(p._seat_motion.name)
        self.assertIsNone(p._lid_pending)
        self.assertIsNone(p._lid_pending_owner)
        self.assertIsNone(p._action_expression_token)
        self.assertEqual((p._lid, p._lid_mode, p._lid_until), original)
        with patch('pet.time.time', return_value=10000.1):
            self.assertTrue(p.set_appearance_mode('xiaoqiao'))
        self.assertIsNone(p._active_seat(10000.3))
        self.assertIsNone(p._lid_pending)
        self.assertEqual((p._lid, p._lid_mode, p._lid_until), original)

    def test_static_character_rejects_user_and_agent_seated_actions_without_hidden_timeline(self):
        p = self.prepare_seated_action_host()
        self.assertTrue(p.set_appearance_mode('ai', pin='gemini'))
        self.assertTrue(p._static_active())
        self.assertFalse(p._action_context().on_swing)
        saves = p.save_settings.call_count
        for action, source in (('pat', 'user'), ('nudge', 'agent')):
            with self.subTest(action=action, source=source), \
                 patch('pet.time.time', return_value=10000.0):
                self.assertFalse(p.perform_action(action, source=source))
                self.assertFalse(p._actions().last_request.accepted)
                self.assertEqual(p._actions().last_request.reason, 'missing_scene')
                self.assertIsNone(p._actions().motion.name)
                self.assertIsNone(p.__dict__.get('_seat_motion'))
                self.assertIsNone(p.__dict__.get('_action_expression_token'))
                self.assertIsNone(p._mouth)
        self.assertEqual(p.save_settings.call_count, saves)
        p.pet_head.assert_not_called()
        p.ask_ai.assert_not_called()

    def test_ai_pat_uses_static_happy_hop_and_keeps_nap_without_xiaoqiao_feedback(self):
        p = self.p
        scene = p._swing
        p._wake_from_nap = Mock()
        p._swing_impulse = Mock()
        p.gain_star = Mock()
        p.sfx = Mock()
        self.assert_switch('ai', 'deepseek')
        saves = p.save_settings.call_count
        with patch('pet.time.time', return_value=10000.0):
            p.request_pat()
        self.assertTrue(p._nap_on_swing)
        self.assertIs(p._swing, scene)
        self.assertIsNone(p._static_hold)
        self.assertEqual(p._ai_pet.character, 'deepseek')
        self.assertEqual(p.last_interact, 10000.0)
        self.assertEqual(p._static_pose(10000.1), 'pat')
        self.assertIsNone(p.__dict__.get('_seat_motion'))
        self.assertIsNone(p.__dict__.get('_action_system'))
        self.assertEqual(p.save_settings.call_count, saves)
        p.pet_head.assert_not_called()
        p._wake_from_nap.assert_not_called()
        p.wake_up.assert_not_called()
        p._swing_impulse.assert_not_called()
        p.gain_star.assert_not_called()
        p.sfx.play.assert_not_called()
        p.ask_ai.assert_not_called()

    def test_static_agent_reaction_keeps_notifications_but_never_runs_xiaoqiao_fallbacks(self):
        p = self.prepare_seated_action_host()
        self.assertTrue(p.set_appearance_mode('ai', pin='claude'))
        p.ai_announce = False
        p._ai_work_sessions = [dict(id='simulated-claude', agent='native-claude', state='waiting', updated=10000.0)]
        p._ai_sessions_scanned = True          # as after a real _scan_ai_sessions
        p._ai_sync_work(10000.0, p._ai_work_sessions)
        old_effect = p._companion_effect = (9000.0, ('star_burst',))
        p._moon_look_until = 9001.0
        p.sfx = Mock()
        p.play_emotion = Mock()
        p._start_micro_motion = Mock()
        p._swing_impulse = Mock()
        p.hop = Mock()
        p.start_stretch = Mock(return_value=False)
        saves = p.save_settings.call_count
        reaction = Reaction('waiting', 'Claude', say='合成确认通知',
                            emotion='curious', fallback='mild', motion='notice',
                            effects=('hop', 'stretch', 'sweat'), sfx='notify')
        with patch.object(p, 'perform_action', wraps=p.perform_action) as action:
            self.assertTrue(agent_companion.execute(p, reaction, 10000.0))
        action.assert_not_called()
        p.play_emotion.assert_not_called()
        p._start_micro_motion.assert_not_called()
        p._swing_impulse.assert_not_called()
        p.hop.assert_not_called()
        p.start_stretch.assert_not_called()
        self.assertIs(p._companion_effect, old_effect)
        self.assertEqual(p._moon_look_until, 9001.0)
        self.assertIsNone(p.__dict__.get('_seat_motion'))
        self.assertIsNone(p.__dict__.get('_static_hold'))
        self.assertEqual(p._static_pose(10003.0), 'asking')
        p.say.assert_not_called()
        p.sfx.play.assert_not_called()
        self.assertEqual(p._last_companion_reaction,
                         dict(kind='waiting', agent='Claude', at=10000.0))
        # The director may persist its own bounded quota/greeting memory.
        self.assertLessEqual(p.save_settings.call_count, saves + 1)
        p.ask_ai.assert_not_called()


if __name__ == '__main__':
    unittest.main()
