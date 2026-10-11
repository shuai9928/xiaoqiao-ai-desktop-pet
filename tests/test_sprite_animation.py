"""Sprite bank contracts using temporary synthetic public-style assets only."""
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import sprite_animation as sprites


class SpriteBankTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='xiaoqiao_sprite_')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.assets = self.folder / 'assets'
        self.animations = self.assets / 'animations'
        self.animations.mkdir(parents=True)
        self.source = Image.new('RGBA', (80, 120), (240, 226, 215, 255))
        self.eyes = {'right': [.5, .4], 'left': [.35, .38], 'label': '合成'}
        self.half = Image.new('RGBA', (24, 15), (200, 170, 160, 0))
        self.half.putpixel((12, 7), (50, 40, 65, 255))
        self.closed = self.half.copy()
        self.closed.putpixel((13, 7), (50, 40, 65, 255))
        self.half.save(self.animations / 'blink-half.png')
        self.closed.save(self.animations / 'blink-closed.png')
        self.manifest = {
            'version': 1,
            'source': {
                'size': list(self.source.size),
                'rgba_sha256': hashlib.sha256(self.source.tobytes()).hexdigest(),
                'eyes_sha256': hashlib.sha256(json.dumps(
                    self.eyes, sort_keys=True, ensure_ascii=True).encode('utf-8')).hexdigest(),
            },
            'clips': {'blink': {
                'layer': 'expression', 'canvas': list(self.source.size),
                'rect': [6, 10, 24, 15], 'anchor': [6, 10],
                'loop': False, 'return_to': 'base',
                'frames': [
                    {'file': 'blink-half.png', 'duration_ms': 40},
                    {'file': 'blink-closed.png', 'duration_ms': 100},
                    {'file': 'blink-half.png', 'duration_ms': 40},
                ],
            }},
        }
        self.write()

    def write(self, manifest=None):
        data = self.manifest if manifest is None else manifest
        (self.animations / 'manifest.json').write_text(
            json.dumps(data, ensure_ascii=True), encoding='utf-8')

    def load(self, **kwargs):
        return sprites.SpriteBank.load(kwargs.get('assets', self.assets),
                                       kwargs.get('source', self.source),
                                       kwargs.get('eyes', self.eyes))

    def assert_empty(self, bank, reason=None):
        self.assertIn(bank.fallback_reason, sprites.FALLBACK_REASONS)
        if reason is not None:
            self.assertEqual(bank.fallback_reason, reason)
        self.assertIsNone(bank.duration('blink'))
        self.assertIsNone(bank.sample('blink', 0))
        self.assertIsNone(bank.overlay(sprites.FrameRef(1, 'blink', 0), (80, 120)))

    def test_valid_bank_duration_and_exact_frame_boundaries(self):
        bank = self.load()
        self.assertIsNone(bank.fallback_reason)
        self.assertAlmostEqual(bank.duration('blink'), .180)
        for elapsed, index in ((0, 0), (.039999, 0), (.04, 1),
                               (.139999, 1), (.14, 2), (.179999, 2)):
            with self.subTest(elapsed=elapsed):
                ref = bank.sample('blink', elapsed)
                self.assertIsInstance(ref.index, int)
                self.assertEqual(ref.index, index)
                self.assertEqual(ref.cache_key, (1, 'blink', index))
        self.assertIsNone(bank.sample('blink', .18))
        self.assertIsNone(bank.sample('blink', 10))

    def test_sampling_is_stateless_and_never_loops(self):
        bank = self.load()
        sequence = [.14, .18, .04, 10, 0, .179999, .04]
        first = [bank.sample('blink', t) for t in sequence]
        self.assertEqual([bank.sample('blink', t) for t in reversed(sequence)],
                         list(reversed(first)))
        self.assertEqual(bank.sample('blink', 0).index, 0)

    def test_invalid_sample_times_return_none(self):
        bank = self.load()
        for elapsed in (-1, -.001, math.nan, math.inf, -math.inf,
                        True, False, None, '0.04', [], {}, 10 ** 400):
            with self.subTest(value_type=type(elapsed).__name__):
                self.assertIsNone(bank.sample('blink', elapsed))
        self.assertEqual(bank.sample('blink', 0).index, 0)

    def test_only_blink_name_can_be_sampled(self):
        bank = self.load()
        for name in ('sleep', 'walk', '', None, 3, True, [], {}):
            with self.subTest(name=name):
                self.assertIsNone(bank.duration(name))
                self.assertIsNone(bank.sample(name, 0))

    def test_frame_reference_is_frozen(self):
        ref = self.load().sample('blink', .04)
        with self.assertRaises(AttributeError):
            ref.index = 2

    def test_overlay_uses_fixed_rect_anchor_and_uniform_scale(self):
        bank = self.load()
        half = bank.sample('blink', 0)
        closed = bank.sample('blink', .04)
        image, offset = bank.overlay(half, (80, 120))
        self.assertEqual((image.size, image.mode, offset), ((24, 15), 'RGBA', (6, 10)))
        self.assertEqual(image.tobytes(), self.half.tobytes())
        self.assertEqual(bank.overlay(closed, (80, 120))[0].tobytes(), self.closed.tobytes())
        image2, offset2 = bank.overlay(half, (160, 240))
        self.assertEqual((image2.size, offset2), ((48, 30), (12, 20)))
        # The host floors the target canvas width; this one-pixel difference
        # does not stretch either the frame or its anchor on a separate axis.
        small, small_at = bank.overlay(half, (60, 91))
        self.assertEqual(small.size, (round(24 * 91 / 120), round(15 * 91 / 120)))
        self.assertEqual(small_at, (round(6 * 91 / 120), round(10 * 91 / 120)))

    def test_invalid_refs_and_target_sizes_fail_safely(self):
        bank = self.load()
        ref = bank.sample('blink', 0)
        for invalid in (None, ref.cache_key, sprites.FrameRef(2, 'blink', 0),
                        sprites.FrameRef(True, 'blink', 0), sprites.FrameRef(1, 'walk', 0),
                        sprites.FrameRef(1, 'blink', -1), sprites.FrameRef(1, 'blink', 3),
                        sprites.FrameRef(1, 'blink', True)):
            with self.subTest(ref=invalid):
                self.assertIsNone(bank.overlay(invalid, (80, 120)))
        for size in (None, [], (80,), (80, 120, 1), (True, 120), (80.0, 120),
                     (0, 120), (-80, 120), (10, 120), (4097, 4097),
                     (4096, 4096), (math.inf, 120)):
            with self.subTest(size=size):
                self.assertIsNone(bank.overlay(ref, size))

    def test_overlay_cache_is_bounded_lru_and_clear_preserves_loaded_frames(self):
        bank = self.load()
        ref = bank.sample('blink', 0)
        sizes = [(80 + 2 * i, 120 + 3 * i) for i in range(9)]
        images = [bank.overlay(ref, size)[0] for size in sizes[:8]]
        self.assertIs(bank.overlay(ref, sizes[0])[0], images[0])  # make first newest
        bank.overlay(ref, sizes[8])
        self.assertIs(bank.overlay(ref, sizes[0])[0], images[0])
        self.assertIs(bank.overlay(ref, sizes[2])[0], images[2])
        self.assertIsNot(bank.overlay(ref, sizes[1])[0], images[1])  # second was oldest
        bank.clear_scaled_cache()
        self.assertIsNot(bank.overlay(ref, sizes[0])[0], images[0])
        self.assertEqual(bank.sample('blink', .04).index, 1)
        self.assertAlmostEqual(bank.duration('blink'), .18)

    def test_unique_pngs_are_decoded_once_and_runtime_never_reads_disk(self):
        with patch.object(Image, 'open', wraps=Image.open) as opened:
            bank = self.load()
        self.assertEqual(opened.call_count, 2)  # half is reused by frame zero and two
        for file in self.animations.iterdir():
            file.unlink()
        with patch.object(Image, 'open', side_effect=AssertionError('runtime disk read')), \
             patch.object(Path, 'open', side_effect=AssertionError('runtime disk read')):
            for elapsed in (0, .04, .14, .18):
                ref = bank.sample('blink', elapsed)
                if ref:
                    self.assertIsNotNone(bank.overlay(ref, (80, 120)))
            bank.clear_scaled_cache()
            self.assertIsNotNone(bank.overlay(bank.sample('blink', 0), (160, 240)))

    def test_missing_manifest_is_a_finite_empty_fallback(self):
        (self.animations / 'manifest.json').unlink()
        self.assert_empty(self.load(), 'manifest_missing')

    def test_malformed_json_and_duplicate_keys_are_rejected(self):
        for content in ('{', 'null', '[]', '{"version":1,"version":1}'):
            with self.subTest(content=content):
                (self.animations / 'manifest.json').write_text(content, encoding='utf-8')
                self.assert_empty(self.load(), 'invalid_manifest')

    def test_manifest_byte_limit_includes_exact_boundary(self):
        path = self.animations / 'manifest.json'
        raw = path.read_bytes()
        padded = raw + b' ' * (sprites.MAX_MANIFEST_BYTES - len(raw))
        path.write_bytes(padded)
        self.assertIsNone(self.load().fallback_reason)
        path.write_bytes(padded + b' ')
        self.assert_empty(self.load(), 'invalid_manifest')

    def test_source_rgba_bytes_size_and_mode_are_bound(self):
        changed = self.source.copy()
        changed.putpixel((0, 0), (239, 226, 215, 255))
        for source in (changed, self.source.convert('RGB'),
                       Image.new('RGBA', (81, 120)), None):
            with self.subTest(source_type=type(source).__name__):
                self.assert_empty(self.load(source=source), 'source_mismatch')

    def test_eyes_fingerprint_uses_sorted_ascii_json_and_rejects_changes(self):
        reordered = dict(reversed(list(self.eyes.items())))
        self.assertIsNone(self.load(eyes=reordered).fallback_reason)
        for eyes in ({**self.eyes, 'left': [.36, .38]}, [], None,
                     {**self.eyes, 'size': math.nan}):
            with self.subTest(eyes=eyes):
                self.assert_empty(self.load(eyes=eyes), 'eyes_mismatch')

    def test_clip_schema_and_geometry_fail_closed(self):
        mutations = (
            lambda m: m.update(version=True),
            lambda m: m['source'].update(size=[4096, 4096]),
            lambda m: m['source'].update(size=[True, 120]),
            lambda m: m['clips'].update(walk=copy.deepcopy(m['clips']['blink'])),
            lambda m: m['clips']['blink'].update(loop=True),
            lambda m: m['clips']['blink'].update(loop=0),
            lambda m: m['clips']['blink'].update(return_to='idle'),
            lambda m: m['clips']['blink'].update(layer='movement'),
            lambda m: m['clips']['blink'].update(canvas=[81, 120]),
            lambda m: m['clips']['blink'].update(rect=[-1, 10, 24, 15]),
            lambda m: m['clips']['blink'].update(rect=[6, 110, 24, 15]),
            lambda m: m['clips']['blink'].update(rect=[6, 10, 0, 15]),
            lambda m: m['clips']['blink'].update(rect=[6, 10, True, 15]),
            lambda m: m['clips']['blink'].update(rect=[0, 0, 2000, 2000]),
            lambda m: m['clips']['blink'].update(anchor=[7, 10]),
            lambda m: m['clips']['blink'].update(anchor=[6.0, 10]),
            lambda m: m['clips']['blink'].update(frames=[]),
            lambda m: m['clips']['blink'].update(frames=m['clips']['blink']['frames'] * 6),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                self.write(manifest)
                self.assert_empty(self.load(), 'invalid_manifest')

    def test_durations_reject_bool_nonfinite_nonpositive_and_over_budget(self):
        for duration in (True, False, 0, -1, math.nan, math.inf, -math.inf,
                         1001, None, '40', [], 10 ** 400):
            with self.subTest(duration=duration):
                manifest = copy.deepcopy(self.manifest)
                manifest['clips']['blink']['frames'][0]['duration_ms'] = duration
                self.write(manifest)
                self.assert_empty(self.load(), 'invalid_manifest')
        manifest = copy.deepcopy(self.manifest)
        for entry in manifest['clips']['blink']['frames']:
            entry['duration_ms'] = 700
        self.write(manifest)
        self.assert_empty(self.load(), 'invalid_manifest')

    def test_finite_fractional_durations_and_exact_total_limit_are_valid(self):
        manifest = copy.deepcopy(self.manifest)
        for entry, duration in zip(manifest['clips']['blink']['frames'], (500.5, 999.5, 500)):
            entry['duration_ms'] = duration
        self.write(manifest)
        bank = self.load()
        self.assertIsNone(bank.fallback_reason)
        self.assertEqual(bank.duration('blink'), 2.0)
        self.assertIsNone(bank.sample('blink', 2.0))

    def test_absolute_drive_unc_parent_and_stream_paths_are_rejected(self):
        paths = ('../outside.png', '..\\outside.png', '/outside.png',
                 'C:/outside.png', 'C:outside.png', '\\\\server\\share\\outside.png',
                 '\\outside.png', 'blink-half.png:stream', 'https://host/frame.png')
        for filename in paths:
            with self.subTest(filename=filename):
                manifest = copy.deepcopy(self.manifest)
                manifest['clips']['blink']['frames'][0]['file'] = filename
                self.write(manifest)
                self.assert_empty(self.load(), 'unsafe_path')

    def test_resolved_frame_escape_is_rejected_before_any_image_is_opened(self):
        # Simulate a resolved symlink target without requiring Windows symlink
        # privileges; real Path.resolve remains in use for all other paths.
        target = self.folder / 'outside.png'
        original_resolve = Path.resolve
        escaped = self.animations / 'blink-half.png'

        def resolve(path, *args, **kwargs):
            return target if path == escaped else original_resolve(path, *args, **kwargs)

        with patch.object(Path, 'resolve', new=resolve), \
             patch.object(Image, 'open', side_effect=AssertionError('escaped decode')):
            self.assert_empty(self.load(), 'unsafe_path')

    def test_manifest_itself_cannot_resolve_outside_animation_directory(self):
        target = self.folder / 'outside-manifest.json'
        original_resolve = Path.resolve
        escaped = self.animations / 'manifest.json'

        def resolve(path, *args, **kwargs):
            return target if path == escaped else original_resolve(path, *args, **kwargs)

        with patch.object(Path, 'resolve', new=resolve):
            self.assert_empty(self.load(), 'unsafe_path')

    def test_animation_directory_cannot_resolve_outside_asset_root(self):
        target = self.folder / 'outside-animations'
        original_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            return target if path == self.animations else original_resolve(path, *args, **kwargs)

        with patch.object(Path, 'resolve', new=resolve):
            self.assert_empty(self.load(), 'unsafe_path')

    def test_unique_decode_budget_is_enforced_before_opening_an_extra_image(self):
        third = self.animations / 'blink-third.png'
        self.closed.save(third)
        manifest = copy.deepcopy(self.manifest)
        manifest['clips']['blink']['frames'][2]['file'] = third.name
        self.write(manifest)
        with patch.object(sprites, 'MAX_DECODED_PIXELS', 2 * 24 * 15), \
             patch.object(Image, 'open', wraps=Image.open) as opened:
            self.assert_empty(self.load(), 'invalid_frame')
        self.assertEqual(opened.call_count, 2)

    def test_apng_is_rejected_even_when_its_png_mode_and_dimensions_match(self):
        self.half.save(self.animations / 'blink-half.png', save_all=True,
                       append_images=[self.closed], duration=[40, 100], loop=0)
        with Image.open(self.animations / 'blink-half.png') as animated:
            self.assertEqual((animated.format, animated.mode, animated.size),
                             ('PNG', 'RGBA', (24, 15)))
            self.assertGreater(animated.n_frames, 1)
        self.assert_empty(self.load(), 'invalid_frame')

    def test_missing_corrupt_wrong_size_and_non_rgba_frames_are_rejected(self):
        half = self.animations / 'blink-half.png'
        variants = (
            lambda: half.unlink(),
            lambda: half.write_bytes(b'not a png'),
            lambda: Image.new('RGBA', (25, 15)).save(half),
            lambda: Image.new('RGB', (24, 15)).save(half),
        )
        for index, invalidate in enumerate(variants):
            with self.subTest(variant=index):
                self.half.save(half)
                invalidate()
                self.assert_empty(self.load(), 'invalid_frame')

    def test_failure_reason_never_contains_manifest_text_or_path(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['clips']['blink']['frames'][0]['file'] = '../SYNTHETIC_PRIVATE_TEXT.png'
        self.write(manifest)
        bank = self.load()
        self.assertIn(bank.fallback_reason, sprites.FALLBACK_REASONS)
        self.assertNotIn('SYNTHETIC_PRIVATE_TEXT', bank.fallback_reason)
        self.assertNotIn(str(self.folder), bank.fallback_reason)


if __name__ == '__main__':
    unittest.main()
