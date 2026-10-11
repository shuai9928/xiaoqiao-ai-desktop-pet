"""Blink clips through the production face/art caches, using checked-in art only.

No Pet.__init__, Tk window, model, runtime configuration or session is used.
The only mocked output is the native layered-window endpoint; the face renderer
and flat workspace's keystone/cache path remain the production implementations.
"""
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageChops

import flat_workspace
import pet
import sprite_animation
from test_scene_art import _shell


ROOT = Path(__file__).resolve().parents[1]
NOW = 10_000.0
SAMPLE_TIMES = (.02, .08, .16)


def runtime_shell(*, scale=1.0, native=False):
    """Public portrait/scene plus synthetic timing and side-effect endpoints."""
    p = _shell()
    p.scale = scale
    if native:
        p.spr2 = p.main_src.copy()
    else:
        height = int(p._sprite_h * scale * pet.SS)
        p.spr2 = p.main_src.resize(
            (int(p.main_src.width * height / p.main_src.height), height),
            Image.Resampling.LANCZOS)
    p._sprite_bank = sprite_animation.SpriteBank.load(
        ROOT / 'assets', p.main_src, p.cfg['eyes'])
    p._art_face_cache = OrderedDict()
    p._blink_patches = None
    p._blink_started_at = None
    p.blink_until = 0.0
    p.state = 'swing'
    p._swing = {'art': True}
    p._nap_on_swing = False
    p.drag = None
    p.singing = False
    p.parts = []
    p._lid_until = 0.0
    p._lid_disp = 0.0
    p._lid_prev_t = NOW
    p._lid_pending = p._mouth = None
    return p


def rgb_diff(before, after):
    return ImageChops.difference(before.convert('RGB'), after.convert('RGB'))


class BlinkSpriteRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.p = runtime_shell()
        self.assertIsNone(self.p._sprite_bank.fallback_reason)

    def keys(self, p=None):
        p = self.p if p is None else p
        self.assertTrue(p._begin_blink(NOW))
        return [p._face_texture_key(NOW + elapsed, .123, False)
                for elapsed in SAMPLE_TIMES]

    def draw(self, key, p=None):
        p = self.p if p is None else p
        return p._face_texture(None, key, base=p.spr2)

    def test_three_timed_frames_reach_the_full_face_key(self):
        keys = self.keys()
        self.assertAlmostEqual(self.p.blink_until - NOW, .18)
        self.assertEqual([key[5] for key in keys],
                         [(1, 'blink', 0), (1, 'blink', 1), (1, 'blink', 2)])
        self.assertEqual(len(set(keys)), 3)
        self.assertTrue(all(key[:5] == ('', 0, True, 1.0, '') for key in keys))
        frames = [self.draw(key) for key in keys]
        self.assertEqual(frames[0].tobytes(), frames[2].tobytes())
        self.assertIsNotNone(rgb_diff(frames[0], frames[1]).getbbox())

    def test_repeated_sampling_and_rendering_do_not_advance_the_clip(self):
        self.p._begin_blink(NOW)
        at = NOW + .08
        first = self.p._face_texture_key(at, .123, False)
        image = self.draw(first)
        for _ in range(3):
            repeated = self.p._face_texture_key(at, .123, False)
            self.assertEqual(repeated, first)
            self.assertEqual(self.draw(repeated).tobytes(), image.tobytes())
        self.assertEqual(self.p._blink_started_at, NOW)

    def test_expired_clip_returns_original_pixels_instead_of_holding_last_frame(self):
        self.keys()
        for at in (self.p.blink_until, NOW + 10):
            key = self.p._face_texture_key(at, .123, False)
            self.assertEqual(key, ('', 0, False, 0.0, ''))
            self.assertEqual(self.draw(key).tobytes(), self.p.spr2.tobytes())

    def test_future_start_does_not_show_a_procedural_closed_fallback(self):
        self.p._begin_blink(NOW + .001)
        key = self.p._face_texture_key(NOW, .123, False)
        self.assertEqual(key, ('', 0, False, 0.0, ''))
        self.assertEqual(self.draw(key).tobytes(), self.p.spr2.tobytes())
        started = self.p._face_texture_key(NOW + .001, .123, False)
        self.assertEqual(started[5], (1, 'blink', 0))

    def test_sleep_overrides_running_clip_and_never_uses_an_animation_frame(self):
        self.keys()
        with patch.object(self.p._sprite_bank, 'overlay',
                          side_effect=AssertionError('sleep must use the held closed renderer')):
            sleeping = self.p._face_texture_key(NOW + .02, 0, True)
            self.assertEqual(sleeping, ('sleep', 0, False, 1.0, ''))
            first = self.draw(sleeping)
            self.assertEqual(self.draw(self.p._face_texture_key(NOW + 5, 0, True)).tobytes(),
                             first.tobytes())
            # Even a stale six-field cache key cannot animate a sleeping face.
            stale = sleeping + ((1, 'blink', 0),)
            self.assertEqual(self.draw(stale).tobytes(), first.tobytes())

    def test_blink_to_nap_to_wake_clears_playback_without_residual_eyes(self):
        p = self.p
        self.keys()
        p._swing['pend'] = SimpleNamespace(idle_amp=.085, damping=.30)
        self.assertTrue(p._set_swing_nap(True, NOW + .02))
        self.assertEqual(p.blink_until, 0)
        self.assertIsNone(p._blink_started_at)
        asleep = p._face_texture_key(NOW + .03, 0, True)
        self.assertEqual(asleep, ('sleep', 0, False, 1.0, ''))
        sleeping = self.draw(asleep)
        self.assertIsNotNone(rgb_diff(sleeping, p.spr2).getbbox())
        self.assertTrue(p._set_swing_nap(False, NOW + .04))
        awake = p._face_texture_key(NOW + .04, 0, False)
        self.assertEqual(awake, ('', 0, False, 0.0, ''))
        self.assertEqual(self.draw(awake).tobytes(), p.spr2.tobytes())

    def test_sleep_yawn_and_nap_cannot_start_a_clip(self):
        for state, napping in (('sleep', False), ('yawn', False), ('swing', True)):
            with self.subTest(state=state, napping=napping):
                p = runtime_shell()
                p.state, p._nap_on_swing = state, napping
                self.assertFalse(p._begin_blink(NOW))
                self.assertIsNone(p._blink_started_at)
                self.assertEqual(p.blink_until, 0)

    def test_native_closed_png_matches_the_existing_closed_eye_renderer(self):
        p = runtime_shell(native=True)
        closed = self.keys(p)[1]
        self.assertEqual(self.draw(closed, p).tobytes(),
                         self.draw(('', 0, True, 1.0, ''), p).tobytes())

    def test_blink_frames_preserve_alpha_and_pixels_outside_the_eye_rect_at_both_scales(self):
        for scale in (.76, 1.0):
            p = runtime_shell(scale=scale)
            for key in self.keys(p):
                with self.subTest(scale=scale, frame=key[5]):
                    before, after = p.spr2, self.draw(key, p)
                    self.assertEqual(before.getchannel('A').tobytes(),
                                     after.getchannel('A').tobytes())
                    overlay, (x, y) = p._sprite_bank.overlay(
                        sprite_animation.FrameRef(*key[5]), before.size)
                    diff = rgb_diff(before, after)
                    self.assertIsNotNone(diff.getbbox())
                    diff.paste((0, 0, 0), (x, y, x + overlay.width, y + overlay.height))
                    self.assertIsNone(diff.getbbox())
                    # The entire mouth, seated body and contact area are untouched.
                    body = (0, round(before.height * .455), before.width, before.height)
                    self.assertEqual(before.crop(body).tobytes(), after.crop(body).tobytes())

    def test_mouth_emotion_and_laugh_are_independent_of_blink_frame(self):
        frames = self.keys()
        mouth_band = (0, round(self.p.spr2.height * .455),
                      self.p.spr2.width, self.p.spr2.height)
        base_mouth = self.p.spr2.crop(mouth_band)
        for style, phase, emotion in (('', 0, 'angry'), ('laugh', 7, ''), ('sing', 5, '')):
            with self.subTest(style=style, emotion=emotion):
                keys = [(style, phase, True, 1.0, emotion, key[5]) for key in frames]
                mouths = [self.draw(key).crop(mouth_band) for key in keys]
                self.assertIsNotNone(rgb_diff(base_mouth, mouths[0]).getbbox())
                self.assertTrue(all(mouth.tobytes() == mouths[0].tobytes() for mouth in mouths))

    def test_missing_bank_keeps_the_old_five_field_key_duration_and_closed_fallback(self):
        p = self.p
        p._sprite_bank = sprite_animation.SpriteBank(fallback_reason='manifest_missing')
        self.assertTrue(p._begin_blink(NOW))
        self.assertAlmostEqual(p.blink_until - NOW, .12)
        key = p._face_texture_key(NOW + .04, .123, False)
        self.assertEqual(key, ('', 0, True, 1.0, ''))
        legacy = self.draw(key)
        # A previously cached frame reference also falls back without stale pixels.
        self.assertEqual(self.draw(key + ((1, 'blink', 0),)).tobytes(), legacy.tobytes())
        p._sprite_bank = None
        self.assertEqual(self.draw(key).tobytes(), legacy.tobytes())

    def test_non_art_and_lit_source_paths_remain_procedural(self):
        p = self.p
        frame_key = self.keys()[0]
        p._swing = {'art': False}
        self.assertAlmostEqual(p._blink_duration(), .12)
        p._begin_blink(NOW)
        key = p._face_texture_key(NOW + .04, .123, False)
        self.assertEqual(len(key), 5)
        p.warper = SimpleNamespace(lit_source=Mock(return_value=p.spr2))
        with patch.object(p._sprite_bank, 'overlay',
                          side_effect=AssertionError('lit source cannot use unlit PNGs')):
            lit = p._face_texture(None, frame_key)
            self.assertEqual(lit.tobytes(), self.draw(key).tobytes())

    def test_real_art_overlay_cache_separates_frames_and_reuses_same_key(self):
        keys = self.keys()
        with patch.object(self.p, '_face_texture', wraps=self.p._face_texture) as draw:
            overlays = [self.p._art_face_overlay(key, .3) for key in keys]
            self.assertEqual(draw.call_count, 3)
            self.assertTrue(all(overlay is not None for overlay in overlays))
            for key, overlay in zip(keys, overlays):
                self.assertIs(self.p._art_face_overlay(key, .3), overlay)
            self.assertEqual(draw.call_count, 3)
        self.assertEqual({key[0][5] for key in self.p._art_face_cache},
                         {(1, 'blink', 0), (1, 'blink', 1), (1, 'blink', 2)})

    def test_flat_workspace_keystone_cache_receives_each_frame_and_reuses_repeated_time(self):
        p = self.p
        keys = self.keys()
        p._swing.update(geo={'u': 1.0, 'k': .3, 'O': (0, 0),
                             'size': (600, 600), 'flat': True},
                        scene_l=0, scene_t=0, theta=0.0)
        p._art_pose = Mock(return_value=None)
        p.hwnd = 0  # native output is mocked; no real window is accessed
        ui = {'now': NOW, 'mock': True, 'sessions': []}
        with patch.object(flat_workspace, 'live_ui', return_value=ui), \
             patch.object(flat_workspace, 'render', return_value=(Image.new('RGBA', (600, 600)), [], 0)), \
             patch.object(pet, 'push_layered'), \
             patch('agent_companion.paint_effect'), \
             patch.object(p._scene_art, 'keystone', wraps=p._scene_art.keystone) as warp, \
             patch.object(p, '_art_face_overlay', wraps=p._art_face_overlay) as overlay:
            for key in keys:
                p._last_face_key = key
                flat_workspace.push(p, None)
            self.assertEqual((warp.call_count, overlay.call_count), (3, 3))
            for key in keys:
                p._last_face_key = key
                flat_workspace.push(p, None)
            self.assertEqual((warp.call_count, overlay.call_count), (3, 3))
        self.assertEqual({cache_key[3][5] for cache_key in p._ks_cache._d},
                         {(1, 'blink', 0), (1, 'blink', 1), (1, 'blink', 2)})

    def test_art_face_cache_has_lru_eviction_instead_of_retaining_all_scaled_frames(self):
        key = self.keys()[0]
        first = self.p._art_face_overlay(key, .3)
        second = self.p._art_face_overlay(key, .301)
        for i in range(2, 24):
            self.p._art_face_overlay(key, .3 + i * .001)
        self.assertEqual(len(self.p._art_face_cache), 24)
        self.assertIs(self.p._art_face_overlay(key, .3), first)
        self.p._art_face_overlay(key, .4)
        self.assertEqual(len(self.p._art_face_cache), 24)
        self.assertIs(self.p._art_face_overlay(key, .3), first)
        self.assertIsNot(self.p._art_face_overlay(key, .301), second)

    def test_production_scale_rebuild_clears_frame_related_caches_and_keeps_loaded_clip(self):
        p = self.p
        key = self.keys()[0]
        p._art_face_overlay(key, .3)
        self.assertTrue(p._sprite_bank._scaled)
        p._ks_cache.put(('old-frame', key), object())
        p._last_face_key = key
        p._warp_cache = {'old-scale': object()}
        p._expr_rs = {'old-scale': object()}
        p._castfx_lock = Lock()
        p.root = Mock()  # never executes the scheduled Tk callbacks
        p.decors_meta = []
        p._text_warm_scheduled = True
        p.scale = .76
        p._art_regeo = Mock()
        with patch.object(pet, 'DepthWarp', return_value=object()), \
             patch.object(pet.fx, 'FX', return_value=object()), \
             patch.object(pet, 'load_font', return_value=None):
            p.rebuild_scale_cache()
        self.assertFalse(p._sprite_bank._scaled)
        self.assertFalse(p._art_face_cache)
        self.assertFalse(p._ks_cache._d)
        self.assertFalse(p._warp_cache)
        self.assertFalse(p._expr_rs)
        self.assertIsNone(p._last_face_key)
        self.assertIsNone(p._blink_patches)
        self.assertEqual(p.spr2.height, int(p._sprite_h * .76 * pet.SS))
        p._art_regeo.assert_called_once_with(p._swing, 1.0)
        self.assertEqual(p._sprite_bank.sample('blink', .08).cache_key, (1, 'blink', 1))
        self.assertAlmostEqual(p._sprite_bank.duration('blink'), .18)

    def test_sampling_and_face_render_do_not_reopen_assets_at_runtime(self):
        with patch.object(Image, 'open', side_effect=AssertionError('runtime image read')), \
             patch.object(Path, 'open', side_effect=AssertionError('runtime file read')):
            for key in self.keys():
                self.draw(key)
                self.p._art_face_overlay(key, .3)


if __name__ == '__main__':
    unittest.main()
