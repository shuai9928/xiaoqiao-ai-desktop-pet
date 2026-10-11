"""Relief body sprites through production Action, pose and flat-grid paths.

Uses checked-in artwork and synthetic state only. Never creates Pet/Tk, reads
personal data, invokes a model, writes settings or sends a native window frame.
Run through the isolated checks worker, alongside the public asset bank tests.
"""
from pathlib import Path
from threading import Lock
from unittest.mock import Mock, patch
import json
import unittest

from PIL import Image, ImageChops

import flat_workspace
import pet
import seat_motion
import sprite_animation
from tools.preview_seated_actions import synthetic_owner


ROOT = Path(__file__).resolve().parents[1]
NOW = 10_000.0
PROTECTED_POINTS = ((610, 520), (737, 554), (658, 582), (380, 630),
                    (330, 152), (1020, 188), (705, 905), (810, 1140))


def declared_frame(age):
    """Expected interval from the public pack, independent of runtime state."""
    entries = json.loads((ROOT / 'assets/animations/relief-body/manifest.json').read_text(
        encoding='utf-8'))['clip']['frames']
    end = 0.0
    for index, entry in enumerate(entries):
        end += entry['duration_ms'] / 1000.0
        if age < end:
            return index
    return None


def body_shell(scene_scale=1.0):
    p = synthetic_owner(scene_scale, (1920, 1080), 1.0)
    sa = p._scene_art
    p._body_sprite_bank = sprite_animation.BodySpriteBank.load(
        ROOT / 'assets', sa.src['swing_studio'],
        {'meta': sa.meta, 'rig': p.cfg['rig']['regions'], 'contact_gate_version': 1},
        seat_motion.ACTIONS['relief']['dur'])
    p._sprite_bank = sprite_animation.SpriteBank.load(
        ROOT / 'assets', p.main_src, p.cfg['eyes'])
    p._last_body_frame = None
    p._lid_until = p._lid_disp = 0.0
    p._lid_prev_t = NOW
    p._lid_pending = p._mouth = None
    p._blink_started_at = None
    p.parts = []
    p.last_interact = NOW
    p.gain_star, p.save_settings, p.say = Mock(), Mock(), Mock()
    return p


def all_channel_diff(a, b):
    bands = ImageChops.difference(a, b).split()
    result = bands[0]
    for band in bands[1:]:
        result = ImageChops.lighter(result, band)
    return result


class BodySpriteRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.p = body_shell()
        self.assertIsNone(self.p._body_sprite_bank.fallback_reason)

    def request(self, p=None, name='relief', at=NOW, source='user'):
        p = self.p if p is None else p
        with patch.object(pet.time, 'time', return_value=at):
            return p.perform_action(name, source=source)

    def pose(self, age, p=None):
        p = self.p if p is None else p
        phase = round(p._swing['theta'] / .008) * .008
        with patch.object(pet.time, 'time', return_value=NOW + age):
            return p._art_pose(phase)

    def source(self, p=None):
        p = self.p if p is None else p
        return p._scene_art.scaled(p._swing['geo']['k'])['swing_studio'][0]

    def apply(self, age, p=None):
        p = self.p if p is None else p
        pose = self.pose(age, p)
        original = self.source(p)
        replaced, residual = p._art_body_sprite_source(original, pose)
        return original, replaced, pose, residual

    def push(self, age, p=None):
        p = self.p if p is None else p
        with patch.object(pet.time, 'time', return_value=NOW + age), \
             patch.object(flat_workspace, 'live_ui', return_value={'now': NOW, 'mock': True, 'sessions': []}), \
             patch.object(flat_workspace, 'render', return_value=(Image.new('RGBA', p._swing['geo']['size']), [], 0)), \
             patch.object(pet, 'push_layered'), patch('agent_companion.paint_effect'):
            p._push_swing_art(None)
        return p._swing['scene_canvas']

    def test_body_sampling_uses_the_existing_action_birth_and_time_only(self):
        self.assertTrue(self.request())
        seat = self.p._seat_motion
        self.assertEqual(seat.born, NOW)
        for age in (.01, .21, .91, 1.11, 1.31, 2.71):
            with self.subTest(age=age):
                pose = self.pose(age)
                self.assertEqual(pose['body_sprite']['ref'], (1, 'relief_body', declared_frame(age)))
                self.assertEqual(pose['q'][6], pose['body_sprite']['ref'])
        self.assertEqual(seat.born, NOW)
        self.assertFalse(any(name.startswith('_body') and name.endswith('_started_at')
                             for name in self.p.__dict__))

    def test_future_action_birth_does_not_preplay_a_body_frame(self):
        self.assertTrue(self.request(at=NOW + .01))
        before = self.pose(0)
        self.assertNotIn('body_sprite', before)
        self.assertEqual(len(before['q']), 6)
        self.assertEqual(self.p._seat_motion.name, 'relief')
        self.assertEqual(self.pose(.02)['body_sprite']['ref'], (1, 'relief_body', 0))

    def test_success_subtracts_baked_breath_once_and_keeps_effective_pose(self):
        self.request()
        original, replaced, pose, residual = self.apply(.91)
        body = pose['body_sprite']
        self.assertIsNot(original, replaced)
        self.assertAlmostEqual(residual['breath'], pose['breath'] - body['breath'])
        self.assertAlmostEqual(residual['breath'] + body['breath'], pose['breath'])
        self.assertEqual(pose['breath'], pose['q'][5])
        for channel in ('look', 'hat', 'hair', 'theta', 'q'):
            self.assertEqual(residual[channel], pose[channel])
        self.assertEqual(self.p._last_body_frame, body['ref'])

    def test_dimension_mismatch_does_not_replace_pixels_or_subtract_breath(self):
        self.request()
        pose = self.pose(.91)
        original = self.source()
        mismatch = original.crop((0, 0, original.width - 1, original.height))
        self.p._last_body_frame = ('stale',)
        result, residual = self.p._art_body_sprite_source(mismatch, pose)
        self.assertIs(result, mismatch)
        self.assertIs(residual, pose)
        self.assertEqual(residual['breath'], pose['breath'])
        self.assertIsNone(self.p._last_body_frame)

    def test_flat_fallback_and_its_cache_hit_do_not_report_an_unapplied_body_frame(self):
        p = self.p
        self.request()
        pose = self.pose(.91)
        body = pose['body_sprite']
        invalid = dict(body, size=(body['size'][0] - 1, body['size'][1]))
        with patch.object(p, '_art_body_sprite_frame', return_value=invalid), \
             patch.object(p._scene_art, 'pose_keystone', wraps=p._scene_art.pose_keystone) as warp:
            self.push(.91)
            self.assertEqual(warp.call_args.args[-1]['breath'], pose['breath'])
            self.assertIsNone(p._last_body_frame)
            p._last_body_frame = ('stale',)
            self.push(.91)
            self.assertEqual(warp.call_count, 1)
            self.assertIsNone(p._last_body_frame)

    def test_empty_bank_and_replacement_failure_keep_the_complete_old_pose(self):
        self.request()
        full = self.pose(.91)
        for bank in (None, sprite_animation.BodySpriteBank(fallback_reason='manifest_missing')):
            with self.subTest(bank=type(bank).__name__):
                self.p._body_sprite_bank = bank
                fallback = self.pose(.91)
                self.assertNotIn('body_sprite', fallback)
                self.assertEqual(fallback['q'], full['q'][:6])
                self.assertEqual(fallback['breath'], full['breath'])
                original = self.source()
                self.assertEqual(self.p._art_body_sprite_source(original, fallback), (original, fallback))
        p = body_shell()
        self.request(p)
        with patch.object(p._body_sprite_bank, 'replacement', return_value=None):
            fallback = self.pose(.91, p)
        self.assertNotIn('body_sprite', fallback)
        self.assertEqual(fallback['q'], full['q'][:6])

    def test_other_actions_and_non_flat_layouts_do_not_use_the_body_bank(self):
        p = self.p
        with patch.object(p._body_sprite_bank, 'sample', side_effect=AssertionError('unexpected sprite sample')):
            for name in seat_motion.ACTIONS:
                if name == 'relief':
                    continue
                with self.subTest(action=name):
                    p._seat_motion = seat_motion.SeatMotion()
                    self.assertTrue(self.request(name=name))
                    self.assertNotIn('body_sprite', self.pose(.5))
            p._seat_motion = seat_motion.SeatMotion()
            self.assertTrue(self.request())
            p._swing['geo']['flat'] = False
            self.assertNotIn('body_sprite', self.pose(.5))
            p._swing['geo']['flat'], p._swing['art'] = True, False
            self.assertNotIn('body_sprite', self.pose(.5))

    def test_nap_drag_reduced_motion_and_dismount_cancel_without_replaying_body_frames(self):
        for reason in ('nap', 'drag', 'reduced_motion', 'dismount'):
            with self.subTest(reason=reason):
                p = body_shell()
                self.request(p)
                self.assertIn('body_sprite', self.pose(.51, p))
                if reason == 'nap':
                    p._set_swing_nap(True, NOW + .52)
                elif reason == 'drag':
                    p._scene_drag = {'moved': True}
                elif reason == 'reduced_motion':
                    p.ui_reduced_anim = True
                else:
                    p.state = 'fall'
                self.assertNotIn('body_sprite', self.pose(.53, p))
                self.assertIsNone(p._seat_motion.name)
                p._nap_on_swing = p.ui_reduced_anim = False
                p._scene_drag = None
                p.state = 'swing'
                self.assertNotIn('body_sprite', self.pose(.54, p))

    def test_higher_priority_touch_replaces_relief_and_rejected_relief_does_not_change_it(self):
        p = self.p
        self.request()
        self.assertIn('body_sprite', self.pose(.51))
        self.assertTrue(self.request(name='pat', at=NOW + .52))
        self.assertNotIn('body_sprite', self.pose(.53))
        previous = (p._seat_motion.born, p._seat_motion.name, p._lid_until,
                    p._lid_mode, p._lid_pending)
        self.assertFalse(self.request(at=NOW + .54, source='agent'))
        self.assertEqual(p._actions().last_request.reason, 'priority')
        self.assertEqual((p._seat_motion.born, p._seat_motion.name, p._lid_until,
                          p._lid_mode, p._lid_pending), previous)
        self.assertNotIn('body_sprite', self.pose(.55))

    def test_expiry_restores_the_base_source_and_clears_last_rendered_frame(self):
        self.request()
        self.apply(.91)
        # Addition/subtraction of an absolute wall clock can round 2.8 slightly
        # below the duration; cross that existing timeline boundary explicitly.
        at_end = self.pose(seat_motion.ACTIONS['relief']['dur'] + 1e-8)
        self.assertNotIn('body_sprite', at_end)
        self.assertIsNone(self.p._seat_motion.name)
        original = self.source()
        restored, residual = self.p._art_body_sprite_source(original, at_end)
        self.assertIs(restored, original)
        self.assertIs(residual, at_end)
        self.assertIsNone(self.p._last_body_frame)

    def test_zero_baked_frame_is_exactly_the_original_scaled_source(self):
        for scale in (.76, 1.0):
            with self.subTest(scale=scale):
                p = body_shell(scale)
                self.request(p)
                original, replaced, pose, _ = self.apply(.01, p)
                self.assertEqual(pose['body_sprite']['breath'], 0)
                self.assertEqual(replaced.tobytes(), original.tobytes())

    def test_native_replacements_preserve_face_grip_rope_seat_and_pixels_outside_rect(self):
        p = self.p
        p._swing['geo']['k'] = 1.0
        self.request()
        off_x, off_y = p._scene_art.bbox['swing_studio'][:2]
        for age in (.21, .91, 1.11, 1.91, 2.31):
            original, replaced, pose, _ = self.apply(age)
            body = pose['body_sprite']
            x, y = body['offset']
            diff = all_channel_diff(original, replaced)
            diff.paste(0, (x, y, x + body['image'].width, y + body['image'].height))
            self.assertIsNone(diff.getbbox())
            for ax, ay in PROTECTED_POINTS:
                with self.subTest(age=age, point=(ax, ay)):
                    box = (ax - off_x - 4, ay - off_y - 4, ax - off_x + 5, ay - off_y + 5)
                    self.assertEqual(original.crop(box).tobytes(), replaced.crop(box).tobytes())
            seat = (0, 830 - off_y, original.width, original.height)
            self.assertEqual(original.crop(seat).tobytes(), replaced.crop(seat).tobytes())

    def test_scaled_replacements_preserve_eye_mouth_grip_and_seat_centres(self):
        for scale in (.76, 1.0):
            p = body_shell(scale)
            self.request(p)
            original, replaced, _, _ = self.apply(.91, p)
            sa = p._scene_art
            source_width, source_height = sa.src['swing_studio'].size
            off_x, off_y = sa.bbox['swing_studio'][:2]
            for ax, ay in PROTECTED_POINTS:
                px = round((ax - off_x) * original.width / source_width)
                py = round((ay - off_y) * original.height / source_height)
                with self.subTest(scale=scale, point=(ax, ay)):
                    self.assertEqual(original.getpixel((px, py)), replaced.getpixel((px, py)))

    def test_replacement_uses_rgba_paste_and_does_not_mutate_shared_sources_or_cached_png(self):
        self.request()
        pose = self.pose(.91)
        source = self.source()
        before = source.tobytes()
        body = pose['body_sprite']
        png_before = body['image'].tobytes()
        replaced, _ = self.p._art_body_sprite_source(source, pose)
        x, y = body['offset']
        self.assertEqual(replaced.crop((x, y, x + body['image'].width,
                                       y + body['image'].height)).tobytes(), png_before)
        self.assertEqual(source.tobytes(), before)
        self.assertEqual(body['image'].tobytes(), png_before)
        self.assertIs(self.source(), source)
        # A synthetic transparent hole demonstrates why alpha-composite is wrong.
        hole = Image.new('RGBA', (1, 1), (31, 17, 47, 0))
        candidate = dict(body, image=hole, offset=(0, 0))
        erased, _ = self.p._art_body_sprite_source(source, dict(pose, body_sprite=candidate))
        self.assertEqual(erased.getpixel((0, 0)), (31, 17, 47, 0))
        self.assertEqual(source.tobytes(), before)

    def test_blink_and_emotion_mouth_overlay_are_applied_after_body_replacement(self):
        p = self.p
        self.request()
        p._begin_blink(NOW + .9)
        p._mouth = ('laugh', NOW + 2)
        key = p._face_texture_key(NOW + .91, .123, False)
        self.assertTrue(key[2])
        self.assertEqual(key[0], 'laugh')
        p._last_face_key = key
        with patch.object(p, '_art_body_sprite_source', wraps=p._art_body_sprite_source) as body, \
             patch.object(p, '_art_face_overlay', wraps=p._art_face_overlay) as face:
            self.push(.91)
            self.assertEqual(body.call_count, 1)
            self.assertEqual(face.call_count, 1)
            self.assertEqual(face.call_args.args[0], key)
        self.assertIsNotNone(p._last_body_frame)
        self.assertEqual(p._mouth[0], 'laugh')
        painted = p._face_texture(None, key, base=p.spr2)
        self.assertIsNotNone(all_channel_diff(p.spr2, painted).getbbox())

    def test_flat_keystone_cache_identity_includes_body_frame_and_reports_cache_hits(self):
        p = self.p
        self.request()
        first, second = self.pose(.91), self.pose(1.01)
        self.assertEqual(first['q'][:6], second['q'][:6])
        self.assertNotEqual(first['q'][6], second['q'][6])
        with patch.object(p._scene_art, 'pose_keystone', wraps=p._scene_art.pose_keystone) as warp:
            self.push(.91)
            self.push(1.01)
            self.assertEqual(warp.call_count, 2)
            p._last_body_frame = None
            self.push(.91)
            self.assertEqual(warp.call_count, 2)
            self.assertEqual(p._last_body_frame, first['body_sprite']['ref'])
        self.assertTrue(all(len(key[4]) == 7 for key in p._ks_cache._d))

    def test_actual_scene_scale_dimensions_are_used_and_oversized_target_falls_back(self):
        for scale in (.76, 1.0):
            p = body_shell(scale)
            self.request(p)
            pose = self.pose(.91, p)
            source = self.source(p)
            self.assertEqual(pose['body_sprite']['size'], source.size)
            replacement = p._body_sprite_bank.replacement(
                sprite_animation.FrameRef(*pose['body_sprite']['ref']), source.size)
            self.assertEqual(pose['body_sprite']['offset'], replacement[1])
        self.request()
        with patch.object(self.p._scene_art, 'scaled',
                          return_value={'swing_studio': (Mock(size=(5000, 5000)), (0, 0))}):
            pose = self.pose(.91)
        self.assertNotIn('body_sprite', pose)
        self.assertEqual(len(pose['q']), 6)

    def test_repeated_draw_is_pure_and_never_refires_hat_or_pendulum_impulses(self):
        p = self.p
        self.request()
        with patch.object(p.life.hat_rot, 'impulse', wraps=p.life.hat_rot.impulse) as hat, \
             patch.object(p._swing['pend'], 'impulse', wraps=p._swing['pend'].impulse) as pend:
            p._seat_swing_step(p._swing, .05, NOW + 1.35)
            self.assertEqual((hat.call_count, pend.call_count), (1, 1))
            previous = (p.life.hat_rot.x, p.life.hat_rot.v,
                        p._swing['pend'].theta, p._swing['pend'].omega,
                        set(p._seat_motion.fired))
            for _ in range(3):
                self.push(1.35)
            self.assertEqual((hat.call_count, pend.call_count), (1, 1))
            self.assertEqual((p.life.hat_rot.x, p.life.hat_rot.v,
                              p._swing['pend'].theta, p._swing['pend'].omega,
                              set(p._seat_motion.fired)), previous)
        p.save_settings.assert_not_called()
        p.gain_star.assert_not_called()

    def test_scale_rebuild_clears_body_and_upstream_caches_without_unloading_clip(self):
        p = self.p
        self.request()
        self.apply(.91)
        p._ks_cache.put(('old',), object())
        p._warp_cache = p._expr_rs = {}
        p._castfx_lock = Lock()
        p.root = Mock()
        p.decors_meta = []
        p._text_warm_scheduled = True
        p._art_regeo = Mock()
        self.assertTrue(p._body_sprite_bank._scaled)
        with patch.object(pet, 'DepthWarp', return_value=object()), \
             patch.object(pet.fx, 'FX', return_value=object()), \
             patch.object(pet, 'load_font', return_value=None):
            p.rebuild_scale_cache()
        self.assertFalse(p._body_sprite_bank._scaled)
        self.assertFalse(p._ks_cache._d)
        self.assertIsNone(p._last_body_frame)
        self.assertAlmostEqual(p._body_sprite_bank.duration(), 2.8)
        self.assertEqual(p._body_sprite_bank.sample(.91).cache_key,
                         (1, 'relief_body', declared_frame(.91)))


if __name__ == '__main__':
    unittest.main()
