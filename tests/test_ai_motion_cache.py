"""AI motion: sub-pixel cache, constant fit, eased crossfade, smooth effects.

Synthetic sprites and the public character packs only; no Tk window, model or
personal data. The host test uses the isolated checks runner like I47's.
"""
import os
import random
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import ai_fx as fx
import appearance
import flat_workspace as f
from ai_pet import View

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def blob(w=40, h=80, fill=(200, 120, 60, 255)):
    image = Image.new('RGBA', (w, h))
    ImageDraw.Draw(image).ellipse((3, 3, w - 4, h - 1), fill=fill)
    return image


def slab(w=96, h=100):
    return Image.new('RGBA', (w, h), (200, 120, 60, 255))


def centroid(image, at):
    alpha = image.getchannel('A')
    w, h = alpha.size
    data, total, sx, sy = alpha.tobytes(), 0, 0, 0
    for y in range(h):
        for x, v in enumerate(data[y*w:(y+1)*w]):
            if v:
                total, sx, sy = total + v, sx + v*x, sy + v*y
    return at[0] + sx / total, at[1] + sy / total


def area(image):
    return sum(image.getchannel('A').tobytes()) / 255


class SubPixelTests(unittest.TestCase):
    def test_eighth_pixel_steps_move_the_alpha_centroid_monotonically(self):
        cache, image = fx.MotionCache(), blob()
        ys = [centroid(*cache.render('blob', image, (0, k / (8 * 80), 0, 1, 1))[:2])[1] for k in range(17)]
        steps = [b - a for a, b in zip(ys, ys[1:])]
        self.assertTrue(all(.115 < s < .135 for s in steps), steps)    # even, not 1/9 + a double step
        self.assertAlmostEqual(ys[-1] - ys[0], 2, delta=.02)
        xs = [centroid(*cache.render('blob', image, (-k / (8 * 80), 0, 0, 1, 1))[:2])[0] for k in range(9)]
        self.assertTrue(all(-.135 < b - a < -.115 for a, b in zip(xs, xs[1:])), xs)

    def test_integer_phase_translation_returns_the_source_object(self):
        cache, image = fx.MotionCache(), blob()
        with patch.object(Image.Image, 'transform', side_effect=AssertionError('resampled')):
            out, at, box = cache.render('blob', image, (-5 / 80, 3 / 80, 0, 1, 1))
        self.assertIs(out, image)
        self.assertEqual(at, (-5, 3))
        self.assertEqual(box, image.getchannel('A').getbbox())
        self.assertEqual(len(cache), 0)

    def test_transforms_quantise_and_steady_cycle_is_all_hits(self):
        cache, image = fx.MotionCache(), blob()
        a = cache.render('blob', image, (0, 0, 1.001, 1, 1))
        b = cache.render('blob', image, (0, 0, 1.019, 1, 1))     # same .05 deg cell
        self.assertIs(a[0], b[0])
        for t in range(181):
            cache.render('blob', image, fx.motion('rock', t / 60))
        misses = cache.misses
        for t in range(181, 361):
            cache.render('blob', image, fx.motion('rock', t / 60))
        self.assertEqual(cache.misses, misses)
        self.assertLessEqual(len(cache), 101)

    def test_lru_is_bounded_by_pixels_and_count(self):
        image = blob()
        one = len(fx.MotionCache().render('blob', image, (0, 0, 1, 1, 1))[0].tobytes()) // 4
        cache = fx.MotionCache(max_pixels=one * 5, max_items=4)
        for k in range(30):
            cache.render('blob', image, (0, 0, -3 + k * .2, 1, 1))
            self.assertLessEqual(cache.pixels, one * 5 + one // 2)
            self.assertLessEqual(len(cache), 4)
        misses = cache.misses
        cache.render('blob', image, (0, 0, -3 + 29 * .2, 1, 1))
        self.assertEqual(cache.misses, misses)                # newest kept
        cache.render('blob', image, (0, 0, -3, 1, 1))
        self.assertEqual(cache.misses, misses + 1)            # oldest evicted

    def test_key_separates_sources(self):
        cache = fx.MotionCache()
        red, blue = blob(fill=(255, 0, 0, 255)), blob(fill=(0, 0, 255, 255))
        a = cache.render(('claude', 1, 'fp', 'idle', 0, False, 10, 10), red, (0, 0, 2, 1, 1))[0]
        b = cache.render(('claude', 2, 'fp', 'idle', 0, False, 10, 10), blue, (0, 0, 2, 1, 1))[0]
        self.assertNotEqual(a.tobytes(), b.tobytes())


class FitTests(unittest.TestCase):
    def test_rock_fit_is_constant_without_size_pulsing(self):
        cache, image = fx.MotionCache(), slab(96, 100)
        areas, fits = [], set()
        for t in range(181):
            fits.add(cache.fit('wide', image, 'rock', 100, 2))
            out, at, box = cache.place('wide', image, (2, 0), 'rock', fx.motion('rock', t / 60), 100)
            self.assertTrue(0 <= at[0] and at[0] + out.width <= 100, (t, at, out.size))
            areas.append(area(out))
        self.assertEqual(len(fits), 1)
        factor = fits.pop()[0]
        self.assertTrue(.9 < factor < 1, factor)
        self.assertLess(max(areas) / min(areas), 1.01)       # per-frame LANCZOS shrink varied ~4%

    def test_families_that_fit_keep_factor_one_and_identity(self):
        cache, image = fx.MotionCache(), blob(60, 100)
        for family in ('bob', 'rock', 'sway', 'slow', 'shake', 'float', 'jump', 'squish', None):
            self.assertEqual(cache.fit('narrow', image, family, 120, 30), (1.0, 0), family)
        out, at, box = cache.place('narrow', image, (30, 5), None, fx.motion(None, 1), 120)
        self.assertIs(out, image)
        self.assertEqual(at, (30, 5))

    def test_rotation_pivots_on_the_feet(self):
        image = Image.new('RGBA', (60, 100))
        pen = ImageDraw.Draw(image)
        pen.rectangle((10, 0, 49, 93), fill=(40, 200, 40, 255))
        pen.rectangle((27, 94, 32, 99), fill=(255, 0, 0, 255))
        cache = fx.MotionCache()
        for angle in (-2.5, 2.5, 4):
            out, at, _ = cache.place('feet', image, (40, 10), 'rock', (0, 0, angle, 1, 1), 160)
            red = [(x, y) for y in range(out.height) for x in range(out.width)
                   if out.getpixel((x, y))[0] > 200 and out.getpixel((x, y))[1] < 90 and out.getpixel((x, y))[3] > 200]
            cx = at[0] + sum(x for x, _ in red) / len(red) + .5
            cy = at[1] + sum(y for _, y in red) / len(red) + .5
            self.assertLess(abs(cx - 70), 1, angle)
            self.assertLess(abs(cy - 107), 1, angle)

    def test_real_shake_keeps_its_full_travel(self):
        cat = appearance.CharacterCatalog.load(ASSETS)
        size = f.static_layout(1.5, 30)[2]
        cache = fx.MotionCache()
        for character in ('claude', 'codex'):
            frame = cat.frame(character, 'oops', size)
            lefts = []
            for t in range(85):
                out, at, box = cache.place(frame.ref, frame.image, frame.offset, 'shake',
                                           fx.motion('shake', t / 60), size[0])
                lefts.append(at[0] + box[0])
            self.assertGreaterEqual(max(lefts) - min(lefts), 6, character)

    def test_shake_at_the_column_edge_shifts_the_base_not_the_motion(self):
        cache, image = fx.MotionCache(), slab(96, 100)
        xs = []
        for t in range(85):
            out, at, box = cache.place('edge', image, (4, 0), 'shake', fx.motion('shake', t / 60), 100)
            self.assertTrue(0 <= at[0] and at[0] + out.width <= 100)
            xs.append(centroid(out, at)[0])
        factor = cache.fit('edge', image, 'shake', 100, 4)[0]
        self.assertLess(factor, 1)
        self.assertGreater(max(xs) - min(xs), 2 * .03 * 100 * factor - 1)

    def test_exits_slide_out_and_are_clipped_not_shrunk(self):
        cache, image = fx.MotionCache(), blob(60, 100)
        self.assertEqual(cache.fit('exit', image, 'dash', 100, 35)[0], 1.0)
        rights, widths = [], []
        for t in range(0, 133, 4):
            out, at, box = cache.place('exit', image, (35, 0), 'dash', fx.motion('dash', t / 60), 100)
            self.assertTrue(0 <= at[0] and at[0] + out.width <= 100)
            self.assertEqual(box, out.getchannel('A').getbbox())
            rights.append(at[0] + out.width)
            widths.append(out.width)
        self.assertEqual(rights[-1], 100)
        self.assertLess(widths[-1], widths[0] - 10)


class AlphaBoxTests(unittest.TestCase):
    def test_alpha_box_matches_every_returned_image(self):
        cache, image = fx.MotionCache(), blob()
        cases = [(0, 0, 0, 1, 1), (0, .013, 0, 1, 1), (.02, -.01, 2.5, 1, 1), (0, -.02, 0, 1.01, 1.015),
                 (0, -.05, 0, .96, 1.04)]
        for transform in cases:
            out, at, box = cache.place('box', image, (20, 10), 'bob', transform, 120)
            self.assertEqual(box, out.getchannel('A').getbbox(), transform)
        old = cache.place('box', image, (20, 10), 'rock', (0, 0, -2, 1, 1), 120)
        new = cache.place('other', blob(50, 70), (25, 20), 'rock', (0, 0, -2, 1, 1), 120)
        for alpha in (0, .3, 1):
            out, at, box = fx.crossfade_sprites(old, new, alpha)
            self.assertEqual(box, out.getchannel('A').getbbox(), alpha)

    def test_catalog_frames_carry_their_alpha_box(self):
        cat = appearance.CharacterCatalog.load(ASSETS)
        frame = cat.frame('claude', 'idle', (172, 194))
        self.assertEqual(frame.alpha_box, frame.image.getchannel('A').getbbox())


class CrossfadeTests(unittest.TestCase):
    def test_ease_is_css_ease(self):
        def css(x):
            lo, hi = 0.0, 1.0
            for _ in range(60):
                mid = (lo + hi) / 2
                bx = 3*(1-mid)**2*mid*.25 + 3*(1-mid)*mid**2*.25 + mid**3
                lo, hi = (mid, hi) if bx < x else (lo, mid)
            s = (lo + hi) / 2
            return 3*(1-s)**2*s*.1 + 3*(1-s)*s**2 + s**3
        values = [fx.ease(i / 100) for i in range(101)]
        self.assertEqual((values[0], values[-1]), (0, 1))
        self.assertTrue(all(b >= a for a, b in zip(values, values[1:])))
        for i in range(101):
            self.assertAlmostEqual(values[i], css(i / 100), delta=1e-3)
        self.assertAlmostEqual(fx.ease(.5), .8024, delta=.002)

    def test_crossfade_blends_both_sprites_in_their_union(self):
        old = (Image.new('RGBA', (10, 10), (255, 0, 0, 255)), (0, 0))
        new = (Image.new('RGBA', (10, 10), (0, 0, 255, 255)), (5, 0))
        out, at, box = fx.crossfade_sprites(old, new, .5)
        self.assertEqual((out.size, at, box), ((15, 10), (0, 0), (0, 0, 15, 10)))
        k = fx.ease(.5)
        r, g, b, a = out.getpixel((7, 5))
        self.assertAlmostEqual(r, 255 * (1 - k), delta=1.5)
        self.assertAlmostEqual(b, 255 * k, delta=1.5)
        self.assertEqual(out.getpixel((2, 5))[:3], (255, 0, 0))   # premultiplied: no dark fringe


class HostLookTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('XIAOQIAO_CHECKS_ISOLATED') != '1':
            raise RuntimeError('Use tools/run_checks.py with synthetic user data')
        from test_appearance import shell
        self.clock = 1700000000.0
        self.p = shell(ai_announce=False, bubble=None, ui_reduced_anim=False, root=Mock())
        for target in (patch('pet.time.time', side_effect=lambda: self.clock),
                       patch('pet.threading.Thread.start'),
                       patch('foreground_ai.ForegroundProcess.current', return_value=None)):
            target.start()
            self.addCleanup(target.stop)
        self.p.set_appearance_mode('ai', pin='claude')
        self.p._ai_pet.rng = random.Random(123)
        self.size = f.static_layout(1.5, 30)[2]
        self.cat = self.p._appearance.catalog

    def look(self, **kw):
        values = dict(character='claude', pose='thinking', art_pose='thinking', frame_index=0, blink=False,
                      motion='rock', motion_t=0.0, fade_from=None, fade_alpha=1.0, fx=None, fx_age=0.0,
                      say='', egg=None)
        values.update(kw)
        view = View(**values)
        self.p._ai_view = lambda now: view
        return self.p._static_look(self.size)

    def test_outgoing_frame_takes_the_running_transform_and_eases(self):
        frame, dy = self.look(fade_from=('claude', 'idle', 0, False), fade_alpha=.5)
        cache = self.p._ai_motion
        new_f, old_f = self.cat.frame('claude', 'thinking', self.size), self.cat.frame('claude', 'idle', self.size)
        motion = fx.motion('rock', 0)
        new = cache.place(new_f.ref, new_f.image, new_f.offset, 'rock', motion, self.size[0], fast=True)
        old = cache.place(old_f.ref, old_f.image, old_f.offset, 'rock', motion, self.size[0], fast=True)
        expected, at, box = fx.crossfade_sprites(old, new, .5)
        self.assertEqual(dy, 0)
        self.assertEqual((frame.offset, frame.alpha_box), (at, box))
        self.assertEqual(frame.image.tobytes(), expected.tobytes())
        flat = (old_f.image, old_f.offset)
        untilted = fx.crossfade_sprites(flat, new, .5)[0]
        self.assertNotEqual(frame.image.tobytes(), untilted.tobytes())

    def test_reduced_motion_is_the_untouched_catalog_sprite(self):
        frame, _ = self.look(motion=None)
        source = self.cat.frame('claude', 'thinking', self.size)
        self.assertIs(frame.image, source.image)
        self.assertEqual((frame.offset, frame.alpha_box), (source.offset, source.alpha_box))

    def test_bob_moves_in_eighth_pixels_and_box_lies_in_the_column(self):
        ys = []
        for i in range(97):
            frame, _ = self.look(pose='idle', art_pose='idle', motion='bob', motion_t=i / 60)
            self.assertTrue(0 <= frame.offset[0] and frame.offset[0] + frame.image.width <= self.size[0])
            self.assertEqual(frame.alpha_box, frame.image.getchannel('A').getbbox())
            ys.append(frame.offset[1])
        self.assertEqual(min(ys), -7)            # 0.025 x 249 px: integer part of the lift
        self.assertGreater(len(self.p._ai_motion), 4)    # fractional phases are resampled
        self.assertLessEqual(len(self.p._ai_motion), 8)

    def test_leaving_ai_mode_releases_the_motion_cache(self):
        self.look()
        cache = self.p._ai_motion
        generation = cache._generation
        self.p.set_appearance_mode('xiaoqiao')
        self.assertIsNone(self.p._static_look(self.size))
        self.assertNotIn('_ai_motion', self.p.__dict__)
        self.assertGreater(cache._generation, generation)    # any warm thread stops


class WarmTests(unittest.TestCase):
    def test_warm_thread_renders_a_cycle_and_cancels(self):
        cache, image = fx.MotionCache(), blob()
        worker = cache.warm([('blob', image, (10, 0), 120, None)], 'rock', 0.0)
        worker.join(20)
        self.assertFalse(worker.is_alive())
        warmed = len(cache)
        self.assertGreater(warmed, 90)
        for t in range(181):
            cache.place('blob', image, (10, 0), 'rock', fx.motion('rock', t / 60), 120)
        self.assertEqual(cache.misses, 0)
        gate = threading.Event()
        real = fx.MotionCache._render

        def slow(*args, **kw):
            gate.wait(5)
            return real(*args, **kw)
        with patch.object(fx.MotionCache, '_render', side_effect=slow):
            worker = cache.warm([('other', blob(30, 60), (0, 0), 120, None)], 'sway', 0.0)
            cache.cancel()
            gate.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertLessEqual(len(cache), warmed + 1)

    def test_unknown_family_or_empty_jobs_start_nothing(self):
        cache = fx.MotionCache()
        self.assertIsNone(cache.warm([], 'rock', 0))
        self.assertIsNone(cache.warm([('k', blob(), (0, 0), 50, None)], None, 0))


class EffectContinuityTests(unittest.TestCase):
    def test_thinking_dots_fade_smoothly_with_staggered_phases(self):
        u, color = 2, (100, 60, 160)
        width = round(174 * u)
        left, right, top = 20, 330, 120
        unit = min(u, (top - u - 1) / 32, (width - 2*u) / 54)
        x0 = max(9*unit, min(width - 45*unit, (left + right) / 2 + 16*unit))
        darkness = [[], [], []]
        for step in range(73):
            image = Image.new('RGBA', (width, 300))
            fx.draw(image, 'thinking', 1.2 + step / 60, (left, top, right, 290), u, color)
            for i in range(3):
                cx = round(x0 + (15 + 7*i) * unit)
                best = min(sum(image.getpixel((x, y))[:3]) for x in range(cx - 1, cx + 2)
                           for y in range(74, 84) if image.getpixel((x, y))[3] == 255
                           and image.getpixel((x, y))[2] - image.getpixel((x, y))[1] > 4)
                darkness[i].append(765 - best)
        for i, series in enumerate(darkness):
            jumps = [abs(b - a) for a, b in zip(series, series[1:])]
            self.assertLessEqual(max(jumps), 25, (i, jumps))
            self.assertGreater(max(series) - min(series), 250, i)
            peak = series.index(max(series)) / 60
            self.assertLess(abs((peak - .6 - .3 * i + .6) % 1.2 - .6), .05, i)


class CatalogLockTests(unittest.TestCase):
    def test_cached_frame_never_waits_behind_a_decode_and_disable_stays_atomic(self):
        cat = appearance.CharacterCatalog.load(ASSETS)
        cached = cat.frame('claude', 'idle', (172, 194))
        inside, release = threading.Event(), threading.Event()
        real = appearance.CharacterCatalog._decode

        def slow(spec):
            inside.set()
            release.wait(5)
            return real(spec)
        with patch.object(appearance.CharacterCatalog, '_decode', side_effect=slow):
            worker = threading.Thread(target=cat.prewarm, args=('codex', ['idle']), daemon=True)
            worker.start()
            try:
                self.assertTrue(inside.wait(5))
                began = time.perf_counter()
                self.assertIs(cat.frame('claude', 'idle', (172, 194)), cached)
                cat.disable('codex', 'image_missing')
                self.assertLess(time.perf_counter() - began, .5)
            finally:
                release.set()
                worker.join(10)
        self.assertFalse(any(key[0] == 'codex' for key in cat._natives))
        self.assertIsNone(cat.frame('codex', 'idle', (172, 194)))


if __name__ == '__main__':
    unittest.main()
