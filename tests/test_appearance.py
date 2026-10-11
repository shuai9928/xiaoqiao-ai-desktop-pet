"""I-45: Xiaoqiao / AI pet modes, character packs, themes and the host wiring.

Synthetic shells only: no Tk window, no model, no real sessions or quota.
"""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

import appearance as ap
import apple_ui
import flat_workspace as flat
import pet
import ui_themes
import ui3d

ASSETS = Path(pet.ASSETS)


def catalog():
    return ap.CharacterCatalog.load(ASSETS)


class CatalogTests(unittest.TestCase):
    def test_public_packs_load_without_decoding_pixels(self):
        c = catalog()
        self.assertIsNone(c.fallback_reason)
        self.assertEqual(c.ids(), ('xiaoqiao', 'claude', 'codex', 'gemini', 'deepseek', 'glm'))
        self.assertEqual(c._natives, {})            # Xiaoqiao mode never pays for AI pictures
        for key in ('claude', 'codex', 'gemini', 'deepseek', 'glm'):
            pack = c.get(key)
            self.assertEqual((pack.renderer, pack.theme), ('static', key))
            self.assertTrue({'idle', 'thinking', 'asking', 'happy', 'sleeping', 'listening'} <= set(pack.poses))
            self.assertEqual(pack.schema_version, 2)

    def test_windows_apps_map_to_providers_case_insensitively(self):
        c = catalog()
        self.assertEqual(c.provider_for_process('ChatGPT.exe'), 'codex')    # the Codex desktop app
        self.assertEqual(c.provider_for_process('CLAUDE.EXE'), 'claude')
        for other in ('explorer.exe', 'WindowsTerminal.exe', 'chrome.exe', 'pythonw.exe', None, 'C:\\x\\claude.exe'):
            self.assertIsNone(c.provider_for_process(other), other)

    def test_frame_sits_in_the_box_feet_down_and_is_cached(self):
        c = catalog()
        for key in ('claude', 'codex', 'gemini', 'deepseek', 'glm'):
            for size in ((164, 194), (246, 291)):
                f = c.frame(key, 'idle', size)
                x, y = f.offset
                self.assertTrue(0 <= x and x + f.image.width <= size[0], (key, size))
                self.assertEqual(y + f.image.height, size[1], (key, size))   # feet on the box bottom
                self.assertIs(c.frame(key, 'idle', size), f)
        # Decoded pictures are reduced once; the native cache stays small.
        self.assertTrue(all(n.image.height <= ap.NATIVE_MAX_H for n in c._natives.values()))

    def test_missing_pose_and_aliases_fall_back_within_the_same_pack(self):
        c = catalog()
        self.assertEqual(c.frame('codex', 'sleep', (164, 194)).pose, 'sleeping')
        self.assertEqual(c.frame('codex', 'no-such-pose', (164, 194)).pose, 'idle')
        self.assertIsNone(c.frame('xiaoqiao', 'idle', (164, 194)))      # legacy renderer, not a picture
        self.assertIsNone(c.frame('nobody', 'idle', (164, 194)))

    def test_scaled_cache_is_bounded(self):
        c = catalog()
        for h in range(100, 100 + ap.MAX_SCALED_CACHE + 6):
            c.frame('gemini', 'idle', (140, h))
        self.assertLessEqual(len(c._scaled), ap.MAX_SCALED_CACHE)

    def test_broken_resources_degrade_the_whole_pack_or_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ASSETS / 'characters', root / 'characters')
            self.assertEqual(ap.CharacterCatalog.load(root).ids()[-1], 'glm')
            # A replaced picture no longer matches its SHA256: only that pack drops out.
            Image.new('RGBA', (570, 640), (255, 0, 0, 128)).save(root / 'characters' / 'claude' / 'idle.webp')
            c = ap.CharacterCatalog.load(root)
            self.assertFalse(c.get('claude').available)
            self.assertEqual(c.get('claude').fallback_reason, 'image_mismatch')
            self.assertTrue(c.get('codex').available)
            # A manifest escaping its folder is refused.
            m = root / 'characters' / 'codex' / 'manifest.json'
            data = json.loads(m.read_text(encoding='utf-8'))
            data['poses']['idle'][0]['file'] = '../claude/idle.webp'
            m.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(ap.CharacterCatalog.load(root).get('codex').fallback_reason, 'unsafe_path')
            # No registry at all: Xiaoqiao only, with a reason.
            (root / 'characters' / 'registry.json').unlink()
            c = ap.CharacterCatalog.load(root)
            self.assertEqual((c.ids(), c.fallback_reason), (('xiaoqiao',), 'config_missing'))

    def test_manifests_match_the_pictures(self):
        import subprocess, sys
        tool = Path(pet.HERE) / 'tools' / 'build_character_manifests.py'
        r = subprocess.run([sys.executable, '-I', str(tool), '--check'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.c = catalog()

    def test_default_and_unknown_settings_keep_xiaoqiao(self):
        for settings in (None, {}, {'appearance_mode': 'bogus'}, {'appearance_mode': 3}):
            s = ap.AppearanceSelector(self.c, settings)
            self.assertEqual((s.mode, s.selection.character, s.selection.renderer),
                             ('xiaoqiao', 'xiaoqiao', 'legacy'))
            self.assertIs(s.observe('claude', 10.0), s.selection)          # Xiaoqiao mode ignores the foreground

    def test_entering_ai_mode_shows_a_character_at_once(self):
        s = ap.AppearanceSelector(self.c, {})
        self.assertEqual(s.set_mode('ai', initial='codex').character, 'codex')
        s = ap.AppearanceSelector(self.c, {'appearance_mode': 'ai', 'appearance_last': 'gemini'})
        self.assertEqual(s.selection.character, 'gemini')                 # restored after a restart
        self.assertEqual(ap.AppearanceSelector(self.c, {}).set_mode('ai').character, 'claude')

    def test_follow_needs_half_a_second_and_ignores_unknown_apps(self):
        s = ap.AppearanceSelector(self.c, {})
        s.set_mode('ai', initial='claude')
        self.assertEqual(s.observe('codex', 1.0).character, 'claude')
        self.assertEqual(s.observe('codex', 1.4).character, 'claude')
        self.assertEqual(s.observe('codex', 1.5).character, 'codex')
        self.assertEqual(s.selection.theme, 'codex')
        # Explorer, a browser or the pet itself: keep the current look, restart the timer.
        self.assertEqual(s.observe(None, 2.0).character, 'codex')
        s.observe('claude', 2.1)
        s.observe(None, 2.4)
        self.assertEqual(s.observe('claude', 2.7).character, 'codex')
        self.assertEqual(s.observe('claude', 3.2).character, 'claude')

    def test_drag_defers_and_the_latest_request_wins_on_release(self):
        s = ap.AppearanceSelector(self.c, {})
        s.set_mode('ai', initial='claude')
        s.observe('gemini', 1.0, dragging=True)
        self.assertEqual(s.observe('gemini', 2.0, dragging=True).character, 'claude')
        self.assertEqual(s.observe('gemini', 2.1).character, 'gemini')

    def test_pin_overrides_following_and_survives_export(self):
        s = ap.AppearanceSelector(self.c, {})
        s.set_mode('ai')
        self.assertEqual(s.set_pin('deepseek').character, 'deepseek')
        self.assertEqual(s.observe('codex', 5.0).character, 'deepseek')
        self.assertEqual(s.observe('codex', 9.0).character, 'deepseek')
        exported = s.settings_export()
        self.assertEqual(exported['appearance_pin'], 'deepseek')
        again = ap.AppearanceSelector(self.c, exported)
        self.assertEqual((again.mode, again.selection.character), ('ai', 'deepseek'))
        self.assertEqual(s.set_mode('xiaoqiao').character, 'xiaoqiao')

    def test_unavailable_pack_falls_back_to_xiaoqiao_as_a_whole(self):
        c = self.c
        c._packs['claude'] = ap.CharacterPack('claude', 'claude', 'static', 'xiaoqiao',
                                              available=False, fallback_reason='image_missing')
        s = ap.AppearanceSelector(c, {})
        s.set_mode('ai', initial='codex')
        sel = s.observe('claude', 1.0)
        sel = s.observe('claude', 2.0)
        self.assertEqual((sel.character, sel.theme, sel.reason), ('xiaoqiao', 'xiaoqiao', 'resource_fallback'))


class ThemeTests(unittest.TestCase):
    def test_xiaoqiao_theme_is_todays_colours(self):
        t = ui_themes.theme('xiaoqiao')
        self.assertEqual(dict(t.panel), flat.PALETTE)
        self.assertIs(t.apple, apple_ui)
        self.assertEqual(dict(t.menu), dict(bg=pet.UI_PANEL, fg=pet.UI_TEXT, activebackground=pet.UI_BTN,
                                            activeforeground=pet.UI_TITLE, disabledforeground=pet.UI_TEXT_DIM,
                                            selectcolor=pet.UI_FIELD))
        self.assertEqual(t.card['calm'], (ui3d.CALM_TOP, ui3d.CALM_BOTTOM))
        self.assertEqual(t.card['edge'], ui3d.CALM_GOLD)
        self.assertIs(ui_themes.theme('no-such-theme'), t)

    def test_every_theme_is_complete_and_state_colours_never_change(self):
        states = dict(flat.COLORS)
        for key, t in ui_themes.THEMES.items():
            self.assertEqual(set(t.panel), set(flat.PALETTE), key)
            for name in ('BG', 'ELEV', 'TEXT', 'TEXT2', 'BLUE', 'HAIR'):
                self.assertTrue(hasattr(t.apple, name), (key, name))
            ui = dict(flat_snapshot(), palette=t.panel)
            im, hits, _ = flat.render_live(ui, 1)
            # Panel fill carries the theme background; the rim stays opaque.
            self.assertEqual(im.getpixel((60, flat.PY + 100))[:3], Image.new('RGB', (1, 1), t.panel['BG']).getpixel((0, 0)))
        self.assertEqual(flat.COLORS, states)

    def test_palettes_draw_the_same_api(self):
        f = apple_ui.font(14, 420)
        for t in ui_themes.THEMES.values():
            A = t.apple
            self.assertEqual(A.bubble('你好', 200, f, True).getpixel((10, 10))[:3], A.BLUE)
            self.assertEqual(A.pill(80, 30).size, (80, 30))
            self.assertEqual(A.circle_button(26, '×').size, (26, 26))
            self.assertEqual(A.window(40, 40, 8, '#010203').size, (40, 40))


def flat_snapshot():
    from test_moon_house import snapshot
    return snapshot()


def shell(**kw):
    """Just enough of a Pet for the appearance methods."""
    p = pet.Pet.__new__(pet.Pet)
    p.settings = {}
    p._flat_panel_style = True
    p.state = 'swing'
    p._nap_on_swing = False
    p.thinking_now = False
    p.chatbox = None
    p.drag = p._scene_drag = None
    p.ui_reduced_anim = True
    p.t0 = time.time()
    p.last_interact = 0.0
    p._ai_work_sessions = []
    p._appearance = None
    p._ui_theme = ui_themes.XIAOQIAO
    p.save_settings = Mock()
    p.say = Mock()
    p.__dict__.update(kw)
    return p


class HostTests(unittest.TestCase):
    def setUp(self):
        probe = patch('foreground_ai.ForegroundProcess.current', return_value=None)
        warmup = patch('pet.threading.Thread.start')
        probe.start();warmup.start()
        self.addCleanup(probe.stop);self.addCleanup(warmup.stop)

    def test_xiaoqiao_mode_draws_her_and_keeps_the_hat(self):
        p = shell(_hat_fx_enabled=True, fx=SimpleNamespace(hat=object()), ui_reduced_anim=False)
        self.assertIsNone(p._static_look((164, 194)))
        self.assertTrue(p._hat_fx_enabled_now())
        self.assertIsNone(p._appearance)                 # no catalog loaded in Xiaoqiao mode

    def test_switching_modes_swaps_character_and_theme_together(self):
        p = shell(_hat_fx_enabled=True, fx=SimpleNamespace(hat=object()), ui_reduced_anim=False)
        p._ai_work_sessions = [dict(id='simulated-codex', agent='native-codex', state='running', updated=time.time())]
        p._ai_sessions_scanned = True          # as after a real _scan_ai_sessions
        p._fg_probe = Mock()
        p._fg_probe.current.return_value = 'ChatGPT.exe'
        self.assertTrue(p.set_appearance_mode('ai'))
        self.assertEqual(p._appearance.selection.character, 'codex')      # explicit entry uses reliable foreground identity
        self.assertEqual(p._ui_theme.key, 'codex')
        frame, dy = p._static_look((164, 194))
        self.assertEqual(frame.pose, 'thinking')                          # Codex is running
        self.assertFalse(p._hat_fx_enabled_now())                         # her hat dust is hidden...
        self.assertTrue(p._hat_fx_layout_on())                            # ...but the window keeps its headroom
        self.assertEqual(p.settings['appearance_mode'], 'ai')
        p.save_settings.assert_called()
        self.assertTrue(p.set_appearance_mode('xiaoqiao'))
        self.assertIsNone(p._static_look((164, 194)))
        self.assertEqual(p._ui_theme.key, 'xiaoqiao')

    def test_ai_mode_needs_the_workspace_layout(self):
        p = shell(_flat_panel_style=False)
        self.assertFalse(p.set_appearance_mode('ai'))
        p.say.assert_called()
        self.assertEqual(p.appearance_mode(), 'xiaoqiao')

    def test_hidden_xiaoqiao_nap_does_not_override_ai_visual_rest_or_interaction(self):
        p = shell()
        p.set_appearance_mode('ai', pin='claude')
        p._nap_on_swing = True
        self.assertEqual(p._static_pose(time.time()), 'idle')
        p.go_sleep()
        self.assertEqual(p._static_pose(time.time()), 'sleeping')
        p._static_click()
        self.assertEqual(p._static_pose(time.time()), 'yawn')
        self.assertTrue(p._nap_on_swing)

    def test_gemini_and_deepseek_have_no_invented_work_state(self):
        p = shell()
        p.set_appearance_mode('ai', pin='gemini')
        p._ai_work_sessions = [dict(agent='native-claude', state='running', updated=time.time())]
        p._ai_sessions_scanned = True          # as after a real _scan_ai_sessions
        self.assertIsNone(p._agent_state_for('gemini', time.time()))
        self.assertEqual(p._static_pose(time.time()), 'idle')

    def test_foreground_follow_is_rate_limited_and_honours_drag(self):
        p = shell()
        p.set_appearance_mode('ai', pin='auto')
        p._fg_probe = Mock()
        p._fg_probe.current.return_value = 'chatgpt.exe'
        clock = [100.0]
        with patch('time.monotonic', lambda: clock[0]):
            p._poll_foreground(1000.0)
            clock[0] = 100.3
            p._poll_foreground(1000.1)                 # inside FG_POLL_S: not even asked
            self.assertEqual(p._fg_probe.current.call_count, 1)
            p._scene_drag = {'moved': True}
            p._poll_foreground(1000.3)
            clock[0] = 100.8
            p._poll_foreground(1000.6)
            self.assertNotEqual(p._appearance.selection.character, 'codex')
            p._scene_drag = None
            clock[0] = 101.0
            p._poll_foreground(1000.9)
        self.assertEqual(p._appearance.selection.character, 'codex')
        self.assertEqual(p._ui_theme.key, 'codex')

    def test_click_on_a_static_character_is_a_hop_not_her_seat_actions(self):
        p = shell()
        p.set_appearance_mode('ai', pin='claude')
        d = {'moved': False}
        p._scene_drag = d
        self.assertFalse(p._seat_long_press(d, 10))     # shy is Xiaoqiao's seated action
        p._static_click()
        p._ai_pet.set_eggs_enabled(False)
        p._static_click()
        self.assertEqual(p._static_pose(time.time()), 'pat')

    def test_a_picture_lost_after_loading_drops_the_whole_look(self):
        p = shell()
        p.set_appearance_mode('ai', pin='gemini')
        catalog = p._appearance.catalog
        with patch.object(catalog, '_native', return_value=None):
            self.assertIsNone(p._static_look((164, 194)))
        sel = p._appearance.selection
        self.assertEqual((sel.character, sel.theme, sel.renderer), ('xiaoqiao', 'xiaoqiao', 'legacy'))
        self.assertEqual(p._ui_theme.key, 'xiaoqiao')                     # no Xiaoqiao on a Gemini panel
        self.assertEqual(catalog.get('gemini').fallback_reason, 'image_missing')
        self.assertEqual(p.settings['appearance_pin'], 'auto')            # a dead pin is not restored
        self.assertIsNone(p._static_look((164, 194)))

    def test_a_look_change_cancels_queued_clicks(self):
        p = shell(click_token=7)
        p.set_appearance_mode('ai', pin='codex')
        self.assertGreater(p.click_token, 7)          # a 60 ms seat click queued before cannot fire

    def test_pet_cmd_selects_modes(self):
        p = shell(_core_edition=True)
        with patch.object(pet.Pet, 'core_profile', return_value=True):
            p._exec_cmd({'op': 'appearance', 'mode': 'ai', 'pin': 'deepseek'})
            self.assertEqual((p.appearance_mode(), p._appearance.selection.character), ('ai', 'deepseek'))
            p._exec_cmd({'op': 'appearance', 'pin': 'auto'})
            self.assertEqual(p._appearance.pin, 'auto')
            p._exec_cmd({'op': 'appearance', 'mode': 'xiaoqiao'})
            self.assertEqual(p.appearance_mode(), 'xiaoqiao')
        state = p._appearance_state()
        self.assertEqual((state['mode'], state['character'], state['theme']), ('xiaoqiao', 'xiaoqiao', 'xiaoqiao'))

    def test_workspace_push_draws_the_character_instead_of_her_art(self):
        frame = SimpleNamespace(image=Image.new('RGBA', (30, 50), (255, 0, 0, 255)), offset=(4, 6))
        o = SimpleNamespace(_swing={'geo': {'u': 1.0, 'k': .2, 'O': (0, 0), 'flat': True}, 'ui': flat_snapshot(),
                                    'scene_l': 0, 'scene_t': 0, 'theta': 0},
                            _scene_art=Mock(), _ac=Mock(), hwnd=1,
                            _static_look=lambda size: (frame, 0), _ui_theme=ui_themes.theme('claude'))
        with patch('pet.push_layered') as pushed:
            flat.push(o, None)
        o._scene_art.scaled.assert_not_called()                  # her swing layers are not touched
        self.assertEqual(o._ac.call_count, 1)
        _, img, x, y = o._ac.call_args[0]
        self.assertIs(img, frame.image)
        self.assertEqual((x, y), (flat.static_layout(1)[0] + 4, flat.static_layout(1)[1] + 6))
        canvas = pushed.call_args[0][1]
        self.assertEqual(canvas.getpixel((300, flat.PY + 100))[:3], (40, 31, 27))   # Claude's panel colour


class ChatRethemeTests(unittest.TestCase):
    """Real Tk widgets in a withdrawn root: retheme keeps the draft and history."""

    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f'no Tk: {e}')
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_open_chat_takes_the_new_theme_in_place(self):
        from appearance_ui import retheme_chat
        p = shell(root=self.root, sw=1920, sh=1080, x=600, fy=900, W=400, H=500, brain=None,
                  chat_log=[{'role': 'user', 'text': '早', 't': time.time() - 60},
                            {'role': 'qiao', 'text': '早呀', 't': time.time() - 50}],
                  ai_thinking=False)
        p._swing = None
        with patch.object(pet, 'work_area_at', return_value=(0, 0, 1920, 1080)), \
             patch('popup_material.apply_surface'):
            cb = pet.ChatBox(p)
        try:
            cb.draft.set('还没发的话')
            images = dict(cb._message_images)
            self.assertEqual(len(images), 2)
            claude = ui_themes.theme('claude')
            retheme_chat(cb, claude.apple, 'claude')
            self.assertIs(cb.A, claude.apple)
            self.assertEqual(cb.draft.get(), '还没发的话')
            self.assertEqual(set(cb._message_images), set(images))
            self.assertEqual(str(cb.log.cget('background')), claude.apple.hexc(claude.apple.BG))
            self.assertEqual(str(cb.entry.cget('background')), claude.apple.hexc(claude.apple.ELEV))
            retheme_chat(cb, claude.apple, 'claude')                 # same theme twice: nothing to do
        finally:
            cb.win.destroy()


if __name__ == '__main__':
    unittest.main()
