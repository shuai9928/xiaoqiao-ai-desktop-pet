"""Relief body bank contracts; temporary synthetic images/configuration only."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import sprite_animation as sprites


class BodySpriteBankTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='xiaoqiao_body_sprite_')
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.assets = self.folder / 'assets'
        self.animations = self.assets / 'animations'
        self.body = self.animations / 'relief-body'
        self.body.mkdir(parents=True)
        self.source = Image.new('RGBA', (80, 120), (145, 133, 180, 255))
        self.geometry = {
            'meta': {'girl_bbox': [12, 0, 92, 120], 'label': '合成'},
            'rig': {'body': [[.2, .4], [.7, .5], [.6, .8]]},
            'contact_gate_version': 1,
        }
        self.base = self.source.crop((20, 55, 44, 70))
        self.inhale = self.base.copy()
        self.inhale.putpixel((12, 7), (55, 34, 89, 255))
        self.exhale = self.base.copy()
        self.exhale.paste((17, 28, 39, 0), (8, 4, 16, 11))
        for name, image in (('base', self.base), ('inhale', self.inhale), ('exhale', self.exhale)):
            image.save(self.body / (name + '.png'))
        self.manifest = {
            'version': 1,
            'source': {
                'size': list(self.source.size),
                'rgba_sha256': hashlib.sha256(self.source.tobytes()).hexdigest(),
                'geometry_sha256': self.geometry_hash(self.geometry),
            },
            'clip': {
                'action': 'relief', 'channel': 'breath', 'loop': False,
                'return_to': 'base', 'canvas': list(self.source.size),
                'rect': [20, 55, 24, 15], 'anchor': [20, 55],
                'frames': [
                    {'file': 'base.png', 'duration_ms': 700, 'baked_breath': 0},
                    {'file': 'inhale.png', 'duration_ms': 700, 'baked_breath': 1.25},
                    {'file': 'exhale.png', 'duration_ms': 700, 'baked_breath': -.75},
                    {'file': 'base.png', 'duration_ms': 700, 'baked_breath': 0},
                ],
            },
        }
        self.write()

    @staticmethod
    def geometry_hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                         allow_nan=False).encode('utf-8')).hexdigest()

    def write(self, manifest=None):
        (self.body / 'manifest.json').write_text(
            json.dumps(self.manifest if manifest is None else manifest), encoding='utf-8')

    def load(self, **kwargs):
        return sprites.BodySpriteBank.load(
            kwargs.get('assets', self.assets), kwargs.get('source', self.source),
            kwargs.get('geometry', self.geometry), kwargs.get('expected_duration', 2.8))

    def assert_empty(self, bank, reason=None):
        self.assertIn(bank.fallback_reason, sprites.BODY_FALLBACK_REASONS)
        if reason is not None:
            self.assertEqual(bank.fallback_reason, reason)
        self.assertIsNone(bank.duration())
        self.assertIsNone(bank.sample(0))
        self.assertIsNone(bank.replacement(sprites.FrameRef(1, 'relief_body', 0), self.source.size))
        self.assertFalse(bank._scaled)

    def test_valid_duration_frame_identity_and_exact_boundaries(self):
        bank = self.load()
        self.assertIsNone(bank.fallback_reason)
        self.assertAlmostEqual(bank.duration(), 2.8)
        for elapsed, index in ((0, 0), (.699999, 0), (.7, 1),
                               (1.399999, 1), (1.4, 2), (2.1, 3), (2.799999, 3)):
            with self.subTest(elapsed=elapsed):
                ref = bank.sample(elapsed)
                self.assertEqual(ref.cache_key, (1, 'relief_body', index))
                self.assertIs(type(ref.index), int)
        self.assertIsNone(bank.sample(2.8))
        self.assertIsNone(bank.sample(100))

    def test_frame_ref_stays_frozen_and_cannot_be_confused_with_blink(self):
        bank = self.load()
        ref = bank.sample(.8)
        with self.assertRaises(FrozenInstanceError):
            ref.index = 2
        self.assertIsNone(bank.replacement(sprites.FrameRef(1, 'blink', 1), self.source.size))

    def test_sampling_is_stateless_and_negative_age_never_plays(self):
        bank = self.load()
        first = bank.sample(.9)
        for elapsed in (2.7, 2.8, 100, 0, -.001, .9, .9):
            bank.sample(elapsed)
        self.assertEqual(bank.sample(.9), first)
        self.assertIsNone(bank.sample(-.001))
        self.assertFalse(bank._scaled)

    def test_invalid_times_fail_without_advancing_or_mutating_the_bank(self):
        bank = self.load()
        for elapsed in (True, False, math.nan, math.inf, -math.inf,
                        -1, '1', None, [], {}, 10 ** 500):
            with self.subTest(kind=type(elapsed).__name__):
                self.assertIsNone(bank.sample(elapsed))
        self.assertEqual(bank.sample(.8).index, 1)
        self.assertIsNone(bank.fallback_reason)

    def test_replacement_has_fixed_anchor_breath_and_uniform_native_or_double_scale(self):
        bank = self.load()
        ref = bank.sample(.8)
        image, at, breath = bank.replacement(ref, self.source.size)
        self.assertEqual((image.mode, image.size, at, breath), ('RGBA', (30, 21), (17, 52), 1.25))
        self.assertEqual(image.crop((3, 3, 27, 18)).tobytes(), self.inhale.tobytes())
        image, at, breath = bank.replacement(ref, (160, 240))
        self.assertEqual((image.size, at, breath), ((54, 36), (37, 107), 1.25))
        for size in ((101, 153), (102, 153)):
            self.assertIsNotNone(bank.replacement(ref, size))
        self.assertIsNone(bank.replacement(ref, (110, 153)))

    def test_rgba_paste_replaces_transparent_holes_and_does_not_touch_outside_the_crop(self):
        bank = self.load()
        image, (x, y), breath = bank.replacement(bank.sample(1.6), self.source.size)
        self.assertEqual(breath, -.75)
        target = self.source.copy()
        target.paste(image, (x, y))  # deliberately no mask: erase old silhouette
        self.assertEqual(target.getpixel((20 + 12, 55 + 7)), (17, 28, 39, 0))
        self.assertEqual(target.crop((20, 55, 44, 70)).tobytes(), self.exhale.tobytes())
        target.paste(self.source.crop((20, 55, 44, 70)), (20, 55))
        self.assertEqual(target.tobytes(), self.source.tobytes())

    def test_neutral_replacement_matches_whole_source_scaling_byteexact_at_fractional_sizes(self):
        # A textured translucent canvas catches resize-phase drift that a flat
        # fill hides. The asset remains neutral, including its invisible RGB.
        self.source.putdata([((x * 17 + y * 3) % 256, (x * 7 + y * 19) % 256,
                              (x * 23 + y * 13) % 256, 1 + (x * 29 + y * 31) % 255)
                             for y in range(120) for x in range(80)])
        self.source.crop((20, 55, 44, 70)).save(self.body / 'base.png')
        self.manifest['source']['rgba_sha256'] = hashlib.sha256(self.source.tobytes()).hexdigest()
        self.write()
        bank = self.load()
        self.assertIsNone(bank.fallback_reason)
        for size in ((80, 120), (31, 47), (101, 153), (102, 153), (160, 240), (1, 1)):
            with self.subTest(size=size):
                expected = self.source.resize(size, Image.Resampling.LANCZOS)
                actual = expected.copy()
                image, at, breath = bank.replacement(bank.sample(0), size)
                actual.paste(image, at)
                self.assertEqual(breath, 0)
                self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_nonzero_downscaled_replacement_matches_whole_canvas_sampling_including_alpha(self):
        bank = self.load()
        for elapsed, frame in ((.8, self.inhale), (1.6, self.exhale)):
            native = self.source.copy()
            native.paste(frame, (20, 55))
            for size in ((31, 47), (40, 60), (79, 119), (80, 120)):
                with self.subTest(size=size, elapsed=elapsed):
                    expected = native.resize(size, Image.Resampling.LANCZOS)
                    actual = self.source.resize(size, Image.Resampling.LANCZOS)
                    image, at, _ = bank.replacement(bank.sample(elapsed), size)
                    actual.paste(image, at)
                    self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_loaded_source_is_independent_of_later_caller_mutation_and_close(self):
        original = self.source.copy()
        bank = self.load()
        self.source.paste((2, 3, 4, 0), (0, 0, 80, 120))
        self.source.close()
        size = (31, 47)
        expected = original.resize(size, Image.Resampling.LANCZOS)
        actual = expected.copy()
        image, at, _ = bank.replacement(bank.sample(0), size)
        actual.paste(image, at)
        self.assertEqual(actual.tobytes(), expected.tobytes())
        bank.clear_scaled_cache()
        self.assertIsNotNone(bank.replacement(bank.sample(.8), (80, 120)))

    def test_scaled_filter_halo_is_clipped_to_canvas_at_the_origin_and_small_targets(self):
        self.manifest['clip']['rect'] = [0, 0, 24, 15]
        self.manifest['clip']['anchor'] = [0, 0]
        self.write()
        bank = self.load()
        for size in ((80, 120), (31, 47), (1, 1)):
            with self.subTest(size=size):
                image, at, _ = bank.replacement(bank.sample(.8), size)
                self.assertEqual(at, (0, 0))
                self.assertLessEqual(image.width, size[0])
                self.assertLessEqual(image.height, size[1])

    def test_refs_and_invalid_or_oversized_targets_fail_before_allocating_cache_entries(self):
        bank = self.load()
        bad_refs = (None, (1, 'relief_body', 0), sprites.FrameRef(True, 'relief_body', 0),
                    sprites.FrameRef(2, 'relief_body', 0), sprites.FrameRef(1, [], 0),
                    sprites.FrameRef(1, 'relief', 0), sprites.FrameRef(1, 'relief_body', True),
                    sprites.FrameRef(1, 'relief_body', -1), sprites.FrameRef(1, 'relief_body', 4),
                    sprites.FrameRef(1, 'relief_body', 1.0))
        for ref in bad_refs:
            self.assertIsNone(bank.replacement(ref, self.source.size))
        for size in (None, [], (80,), (0, 120), (True, 120), (80.0, 120),
                     (4097, 120), (2001, 2000), (800, 120), (-80, 120)):
            self.assertIsNone(bank.replacement(bank.sample(0), size))
        self.assertFalse(bank._scaled)
        self.assertIsNone(bank.fallback_reason)

    def test_scaled_cache_is_lru_bounded_and_clear_preserves_loaded_clip(self):
        bank = self.load()
        ref = bank.sample(.8)
        sizes = [(80 * scale, 120 * scale) for scale in range(1, 10)]
        first = bank.replacement(ref, sizes[0])
        second = bank.replacement(ref, sizes[1])
        for size in sizes[2:8]:
            bank.replacement(ref, size)
        self.assertEqual(len(bank._scaled), 8)
        self.assertIs(bank.replacement(ref, sizes[0]), first)
        bank.replacement(ref, sizes[8])
        self.assertEqual(len(bank._scaled), 8)
        self.assertIs(bank.replacement(ref, sizes[0]), first)
        self.assertIsNot(bank.replacement(ref, sizes[1]), second)
        bank.clear_scaled_cache()
        self.assertFalse(bank._scaled)
        self.assertEqual(bank.sample(.8), ref)
        self.assertAlmostEqual(bank.duration(), 2.8)

    def test_all_unique_images_are_decoded_once_and_runtime_never_reopens_any_asset(self):
        with patch.object(Image, 'open', wraps=Image.open) as opened:
            bank = self.load()
            self.assertEqual(opened.call_count, 3)
        for file in self.body.iterdir():
            file.unlink()
        with patch.object(Path, 'open', side_effect=AssertionError('runtime file read')), \
             patch.object(Image, 'open', side_effect=AssertionError('runtime image read')):
            for elapsed in (0, .8, 1.6, 2.2, .8):
                ref = bank.sample(elapsed)
                self.assertIsNotNone(bank.replacement(ref, (160, 240)))
            self.assertIsNone(bank.sample(2.8))
            bank.clear_scaled_cache()
            self.assertIsNotNone(bank.replacement(bank.sample(.8), self.source.size))
            self.assertAlmostEqual(bank.duration(), 2.8)

    def test_missing_manifest_is_an_empty_finite_fallback(self):
        (self.body / 'manifest.json').unlink()
        self.assert_empty(self.load(), 'manifest_missing')

    def test_invalid_json_duplicate_keys_and_nan_constants_are_rejected(self):
        for raw in ('not-json', '{"version":1,"version":1}', '{"secret":"FAKE_PRIVATE","bad":NaN}'):
            (self.body / 'manifest.json').write_text(raw, encoding='utf-8')
            self.assert_empty(self.load(), 'invalid_manifest')

    def test_manifest_byte_limit_includes_its_exact_boundary(self):
        raw = json.dumps(self.manifest).encode('utf-8')
        padded = raw + b' ' * (sprites.MAX_MANIFEST_BYTES - len(raw))
        (self.body / 'manifest.json').write_bytes(padded)
        self.assertIsNone(self.load().fallback_reason)
        (self.body / 'manifest.json').write_bytes(padded + b' ')
        self.assert_empty(self.load(), 'invalid_manifest')

    def test_source_binding_requires_the_exact_decoded_rgba_canvas(self):
        altered = self.source.copy()
        altered.putpixel((0, 0), (1, 2, 3, 255))
        for source in (altered, self.source.convert('RGB'), Image.new('RGBA', (81, 120)), None):
            self.assert_empty(self.load(source=source), 'source_mismatch')

    def test_geometry_hash_uses_default_sorted_ascii_json_and_rejects_any_binding_change(self):
        reordered = dict(reversed(list(self.geometry.items())))
        self.assertIsNone(self.load(geometry=reordered).fallback_reason)
        changed = copy.deepcopy(self.geometry)
        changed['contact_gate_version'] = 2
        for value in (changed, None, {'nan': math.nan}, {'unsupported': object()}):
            self.assert_empty(self.load(geometry=value), 'geometry_mismatch')
        compact = copy.deepcopy(self.manifest)
        compact['source']['geometry_sha256'] = hashlib.sha256(json.dumps(
            self.geometry, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        self.write(compact)
        self.assert_empty(self.load(), 'geometry_mismatch')

    def test_geometry_schema_rejects_bad_version_bindings_dimensions_rect_or_anchor(self):
        cases = []
        for key, value in (('version', True), ('version', 2), ('source', [])):
            data = copy.deepcopy(self.manifest)
            data[key] = value
            cases.append(data)
        for key, value in (('size', [2001, 2000]), ('size', [True, 120]),
                           ('rgba_sha256', 'x' * 64), ('geometry_sha256', 'missing')):
            data = copy.deepcopy(self.manifest)
            data['source'][key] = value
            cases.append(data)
        for key, value in (('canvas', [81, 120]), ('canvas', [80, False]),
                           ('rect', [-1, 55, 24, 15]), ('rect', [70, 55, 24, 15]),
                           ('rect', [20, 55, True, 15]), ('rect', [20, 55, 24, 0]),
                           ('rect', [20, 55, 24]), ('anchor', [21, 55]),
                           ('anchor', [20, True]), ('anchor', None)):
            data = copy.deepcopy(self.manifest)
            data['clip'][key] = value
            cases.append(data)
        for number, data in enumerate(cases):
            with self.subTest(case=number):
                self.write(data)
                self.assert_empty(self.load(), 'invalid_manifest')

    def test_patch_pixel_budget_is_enforced_before_decoding(self):
        with patch.object(sprites, 'MAX_FRAME_PIXELS', 300), \
             patch.object(Image, 'open', side_effect=AssertionError('over-budget frame must not decode')):
            self.assert_empty(self.load(), 'invalid_manifest')

    def test_only_relief_breath_nonlooping_base_return_protocol_is_allowed(self):
        for key, value in (('action', 'glance'), ('action', None), ('channel', 'look'),
                           ('loop', True), ('loop', 0), ('return_to', 'idle'),
                           ('frames', []), ('frames', {}), ('frames', [None]),
                           ('frames', [self.manifest['clip']['frames'][0]] * 17)):
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.manifest)
                data['clip'][key] = value
                self.write(data)
                self.assert_empty(self.load(), 'invalid_manifest')
        data = copy.deepcopy(self.manifest)
        data['clips'] = {'relief': data.pop('clip')}
        self.write(data)
        self.assert_empty(self.load(), 'invalid_manifest')

    def test_durations_reject_nonfinite_bool_nonpositive_and_overlong_entries(self):
        for duration in (True, False, math.nan, math.inf, -math.inf, 0, -1, 1000.1, '700', None, 10 ** 500):
            with self.subTest(kind=type(duration).__name__):
                data = copy.deepcopy(self.manifest)
                data['clip']['frames'][0]['duration_ms'] = duration
                self.write(data)
                self.assert_empty(self.load(), 'invalid_manifest')

    def test_expected_duration_is_finite_positive_bounded_and_matches_the_whole_clip(self):
        for expected in (True, False, None, math.nan, math.inf, -1, 0, 4.001, '2.8', 10 ** 500, 2.7, 2.800002):
            self.assert_empty(self.load(expected_duration=expected), 'invalid_manifest')
        self.assertIsNone(self.load(expected_duration=2.8000005).fallback_reason)
        data = copy.deepcopy(self.manifest)
        data['clip']['frames'][0]['duration_ms'] += .01
        self.write(data)
        self.assert_empty(self.load(), 'invalid_manifest')

    def test_four_second_limit_and_fractional_duration_values(self):
        data = copy.deepcopy(self.manifest)
        for entry in data['clip']['frames']:
            entry['duration_ms'] = 1000
        self.write(data)
        self.assertIsNone(self.load(expected_duration=4).fallback_reason)
        data['clip']['frames'].append(copy.deepcopy(data['clip']['frames'][0]))
        data['clip']['frames'][-1]['duration_ms'] = .5
        self.write(data)
        self.assert_empty(self.load(expected_duration=4), 'invalid_manifest')
        data = copy.deepcopy(self.manifest)
        data['clip']['frames'][0]['duration_ms'] = 699.5
        data['clip']['frames'][1]['duration_ms'] = 700.5
        self.write(data)
        self.assertIsNone(self.load().fallback_reason)

    def test_breath_values_are_finite_nonbool_in_range_and_exactly_quarter_quantized(self):
        for breath in (True, False, math.nan, math.inf, -math.inf, -1.5001, 1.5001,
                       .1, .250000000001, '1.25', None, 10 ** 500):
            with self.subTest(kind=type(breath).__name__):
                data = copy.deepcopy(self.manifest)
                data['clip']['frames'][1]['baked_breath'] = breath
                self.write(data)
                self.assert_empty(self.load(), 'invalid_manifest')
        for breath in (-1.5, 1.5, -.25, .25, 0):
            data = copy.deepcopy(self.manifest)
            data['clip']['frames'][1]['baked_breath'] = breath
            self.write(data)
            self.assertIsNone(self.load().fallback_reason)

    def test_reused_png_or_normalized_alias_must_have_the_same_baked_breath(self):
        for filename in ('base.png', './base.png'):
            data = copy.deepcopy(self.manifest)
            data['clip']['frames'][-1].update(file=filename, baked_breath=.25)
            self.write(data)
            with patch.object(Image, 'open', side_effect=AssertionError('inconsistent metadata must not decode')):
                self.assert_empty(self.load(), 'invalid_manifest')

    def test_frame_path_rejects_absolute_drive_unc_parent_uri_and_stream_paths(self):
        for filename in ('/outside.png', 'C:/outside.png', 'C:outside.png',
                         '//server/share/frame.png', '\\outside.png', '..\\outside.png',
                         '../outside.png', 'sub/../../outside.png', 'base.png:stream',
                         'https://example.test/frame.png', None, '', 'x' * 513):
            with self.subTest(filename=filename):
                data = copy.deepcopy(self.manifest)
                data['clip']['frames'][0]['file'] = filename
                self.write(data)
                self.assert_empty(self.load(), 'unsafe_path')

    def test_resolved_animation_folder_body_folder_manifest_and_frame_escapes_are_rejected(self):
        original = Path.resolve
        targets = (self.animations, self.body, self.body / 'manifest.json', self.body / 'base.png')
        for target in targets:
            def resolve(path, *args, **kwargs):
                if path == target:
                    return self.folder / 'escaped' / target.name
                return original(path, *args, **kwargs)
            with self.subTest(target=target.name), \
                 patch.object(Path, 'resolve', resolve), \
                 patch.object(Image, 'open', side_effect=AssertionError('path escape must not decode')):
                self.assert_empty(self.load(), 'unsafe_path')

    def test_unique_decode_budget_is_enforced_before_opening_an_extra_image(self):
        with patch.object(sprites, 'MAX_DECODED_PIXELS', 2 * 24 * 15), \
             patch.object(Image, 'open', wraps=Image.open) as opened:
            self.assert_empty(self.load(), 'invalid_frame')
            self.assertEqual(opened.call_count, 2)

    def test_png_file_byte_limit_uses_stat_before_decode_and_accepts_exact_boundary(self):
        largest = max((self.body / name).stat().st_size
                      for name in ('base.png', 'inhale.png', 'exhale.png'))
        with patch.object(sprites, 'BODY_MAX_FILE_BYTES', largest - 1), \
             patch.object(Image, 'open', side_effect=AssertionError('oversized PNG must not decode')):
            self.assert_empty(self.load(), 'invalid_frame')
        with patch.object(sprites, 'BODY_MAX_FILE_BYTES', largest):
            self.assertIsNone(self.load().fallback_reason)

    def test_total_png_byte_budget_counts_unique_files_once_and_rejects_before_decoding(self):
        total = sum((self.body / name).stat().st_size
                    for name in ('base.png', 'inhale.png', 'exhale.png'))
        with patch.object(sprites, 'BODY_MAX_TOTAL_FILE_BYTES', total - 1), \
             patch.object(Image, 'open', side_effect=AssertionError('aggregate PNG bytes must not decode')):
            self.assert_empty(self.load(), 'invalid_frame')
        with patch.object(sprites, 'BODY_MAX_TOTAL_FILE_BYTES', total):
            self.assertIsNone(self.load().fallback_reason)

    def test_large_png_trailing_data_is_rejected_even_with_a_small_decoded_image(self):
        path = self.body / 'inhale.png'
        with path.open('ab') as stream:
            stream.write(b'\0' * (sprites.BODY_MAX_FILE_BYTES + 1 - path.stat().st_size))
        with patch.object(Image, 'open', side_effect=AssertionError('padded image must not decode')):
            self.assert_empty(self.load(), 'invalid_frame')

    def test_missing_corrupt_wrong_sized_or_non_rgba_frame_invalidates_the_whole_bank(self):
        path = self.body / 'inhale.png'
        path.unlink()
        self.assert_empty(self.load(), 'invalid_frame')
        path.write_bytes(b'broken PNG')
        self.assert_empty(self.load(), 'invalid_frame')
        Image.new('RGBA', (25, 15)).save(path)
        self.assert_empty(self.load(), 'invalid_frame')
        Image.new('RGB', (24, 15)).save(path)
        self.assert_empty(self.load(), 'invalid_frame')

    def test_apng_is_rejected_even_if_its_first_frame_matches_rgba_dimensions(self):
        self.base.save(self.body / 'inhale.png', save_all=True,
                       append_images=[self.inhale], duration=[100, 100], loop=0)
        self.assert_empty(self.load(), 'invalid_frame')

    def test_a_fourteen_step_production_style_timeline_reuses_decoded_images(self):
        data = copy.deepcopy(self.manifest)
        data['clip']['frames'] = [dict(file='base.png', duration_ms=200, baked_breath=0)
                                 for _ in range(14)]
        self.write(data)
        with patch.object(Image, 'open', wraps=Image.open) as opened:
            bank = self.load()
            self.assertEqual(opened.call_count, 1)
        self.assertIsNone(bank.fallback_reason)
        self.assertEqual(bank.sample(2.7).cache_key, (1, 'relief_body', 13))
        self.assertAlmostEqual(bank.duration(), 2.8)

    def test_failure_reason_does_not_echo_manifest_text_geometry_or_paths(self):
        data = copy.deepcopy(self.manifest)
        data['clip']['frames'][0]['file'] = '../SYNTHETIC_PRIVATE_NOTE.png'
        self.write(data)
        reason = self.load().fallback_reason
        self.assertIn(reason, sprites.BODY_FALLBACK_REASONS)
        self.assertNotIn('SYNTHETIC_PRIVATE', reason)
        self.assertNotIn(str(self.folder), reason)
        cyclic = {}
        cyclic['cycle'] = cyclic
        self.write()
        self.assert_empty(self.load(geometry=cyclic), 'geometry_mismatch')


if __name__ == '__main__':
    unittest.main()
