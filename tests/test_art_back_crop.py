"""Back-layer crop of the swing pet (Fix B).

render() used to convert("RGBa").reduce(SS) the whole supersampled hat-fx back layer
and flat_workspace.push then cropped _hat_fx_back_box out of the result. Now
Pet._reduce_art_back crops the box (times SS) out of the supersampled layer FIRST and
hands push the small image together with its offset (_art_small_back_at). The result
must be byte-identical to the old order of operations in every case, and anything the
fast path cannot prove identical keeps the old whole-layer path.

Never creates Pet/Tk windows; the pushing owner is the synthetic one of
test_flat_workspace (real scene art, no GUI).
"""
import random
import unittest
from unittest.mock import patch

from PIL import Image

import flat_workspace as flat
import pet
from tools.assets.export_house_stage import owner
from test_moon_house import snapshot

SS = pet.SS


def noisy_layer(size, seed):
    """Random RGBA: mostly transparent, some opaque patches, nonzero RGB under alpha 0."""
    rng = random.Random(seed)
    w, h = size
    img = Image.frombytes('RGBA', size, rng.randbytes(w * h * 4))
    img.putalpha(img.getchannel('A').point(lambda v: v if v < 40 else 0))
    for _ in range(12):
        x, y = rng.randrange(w), rng.randrange(h)
        img.paste((rng.randrange(256), rng.randrange(256), rng.randrange(256),
                   rng.randrange(1, 256)),
                  (x, y, min(w, x + rng.randrange(1, 40)), min(h, y + rng.randrange(1, 40))))
    return img


def old_small(back, W, H):
    """What render() computed before Fix B."""
    return (back.convert('RGBa').reduce(SS) if back.size == (W * SS, H * SS)
            else back.resize((W, H), Image.BILINEAR))


def same_pixels(a, b):
    return a.mode == b.mode and a.size == b.size and a.tobytes() == b.tobytes()


def shell(flat_geo=True, enabled=True, box=None):
    """Just enough of a Pet for _reduce_art_back."""
    p = pet.Pet.__new__(pet.Pet)
    p._swing = {'art': True, 'geo': {'flat': flat_geo}}
    p._hat_fx_enabled_now = lambda: enabled
    p._hat_fx_back_box = box
    return p


class ReduceArtBackTests(unittest.TestCase):
    W, H = 70, 53    # odd sizes on purpose

    def layer(self, seed=1):
        return noisy_layer((self.W * SS, self.H * SS), seed)

    def in_range_boxes(self, rng, n):
        W, H = self.W, self.H
        boxes = [(0, 0, 1, 1), (W - 1, H - 1, W, H), (0, 0, W, 1),
                 (0, 0, 1, H), (3, 3, 4, 4), (33, 17, 34, 52), (0, 0, W // 2, H // 2)]
        for _ in range(n):
            x0, y0 = rng.randrange(0, W), rng.randrange(0, H)
            box = (x0, y0, rng.randrange(x0 + 1, W + 1), rng.randrange(y0 + 1, H + 1))
            if (box[2] - box[0]) * (box[3] - box[1]) * 5 <= W * H * 4:
                boxes.append(box)
        return boxes

    def test_cropped_reduce_is_byte_identical_to_cropping_the_reduced_layer(self):
        back = self.layer()
        full = old_small(back, self.W, self.H)
        boxes = self.in_range_boxes(random.Random(7), 400)
        self.assertGreater(len(boxes), 100)
        for box in boxes:
            with self.subTest(box=box):
                small, at = shell(box=box)._reduce_art_back(back, self.W, self.H)
                self.assertEqual(at, (box[0], box[1]))
                self.assertEqual(small.size, (box[2] - box[0], box[3] - box[1]))
                self.assertTrue(same_pixels(small, full.crop(box)))

    def test_a_box_covering_most_of_the_frame_keeps_the_whole_layer(self):
        # the extra crop copy would cost more than the reduce it saves
        W, H = self.W, self.H
        back = self.layer(9)
        want = old_small(back, W, H)
        for box in ((0, 0, W, H), (0, 0, W, H - 3), (2, 2, W - 2, H - 2), (0, 0, W - 1, H)):
            with self.subTest(box=box):
                small, at = shell(box=box)._reduce_art_back(back, W, H)
                self.assertIsNone(at)
                self.assertTrue(same_pixels(small, want))
        small, at = shell(box=(0, 0, W, H * 4 // 5))._reduce_art_back(back, W, H)
        self.assertEqual(at, (0, 0))                 # exactly 4/5: still cropped

    def test_box_in_the_real_range_of_pet_py_is_what_gain_star_produces(self):
        # gain_star clamps with max(0, floor(..)) / min(W, ceil(..)): always in range
        back = self.layer(8)
        full = old_small(back, self.W, self.H)
        for box in ((0, 0, 9, 7), (60, 40, 70, 53), (0, 20, 70, 21)):
            small, at = shell(box=box)._reduce_art_back(back, self.W, self.H)
            self.assertEqual(at, box[:2])
            self.assertTrue(same_pixels(small, full.crop(box)))

    def test_everything_else_keeps_the_whole_layer(self):
        W, H = self.W, self.H
        back = self.layer(3)
        want = old_small(back, W, H)
        cases = [('no box', shell(box=None)),
                 ('not flat', shell(flat_geo=False, box=(2, 2, 9, 9))),
                 ('not flat, hat fx off', shell(flat_geo=False, enabled=False, box=(2, 2, 9, 9))),
                 ('zero width', shell(box=(5, 5, 5, 9))),
                 ('zero height', shell(box=(5, 5, 9, 5))),
                 ('inverted x', shell(box=(9, 5, 5, 9))),
                 ('inverted y', shell(box=(5, 9, 9, 5))),
                 ('left of frame', shell(box=(-5, 3, 10, 10))),
                 ('above frame', shell(box=(3, -3, 10, 10))),
                 ('right of frame', shell(box=(W - 4, 0, W + 9, 9))),
                 ('below frame', shell(box=(0, H - 4, 9, H + 9))),
                 ('fully outside', shell(box=(W + 2, 0, W + 8, 5))),
                 ('float box', shell(box=(4.0, 5.0, 20.0, 30.0))),
                 ('list box', shell(box=[4, 5, 20, 30])),
                 ('bool in box', shell(box=(True, 5, 20, 30))),
                 ('short box', shell(box=(4, 5, 20)))]
        for label, p in cases:
            with self.subTest(label):
                small, at = p._reduce_art_back(back, W, H)
                self.assertIsNone(at)
                self.assertTrue(same_pixels(small, want))

    def test_flat_scene_without_hat_fx_never_reduces_the_layer(self):
        # flat_workspace.push composites the back layer only while hat fx is on.
        for box in ((1, 1, 9, 9), None):
            self.assertEqual(shell(enabled=False, box=box)._reduce_art_back(
                self.layer(4), self.W, self.H), (None, None))

    def test_hat_fx_switches_of_the_real_predicate_are_honoured(self):
        p = pet.Pet.__new__(pet.Pet)
        p._swing = {'art': True, 'geo': {'flat': True}}
        p._hat_fx_back_box = (1, 1, 9, 9)
        p._hat_fx_enabled, p.ui_reduced_anim = True, False
        p.fx = type('Fx', (), {'hat': object()})()
        back = self.layer(4)
        small, at = p._reduce_art_back(back, self.W, self.H)
        self.assertEqual(at, (1, 1))
        self.assertEqual(small.size, (8, 8))
        for attr, value in (('_hat_fx_enabled', False), ('ui_reduced_anim', True)):
            q = pet.Pet.__new__(pet.Pet)
            q.__dict__.update(p.__dict__)
            setattr(q, attr, value)
            self.assertEqual(q._reduce_art_back(back, self.W, self.H), (None, None))
        q = pet.Pet.__new__(pet.Pet)
        q.__dict__.update(p.__dict__)
        q.fx = type('Fx', (), {'hat': None})()
        self.assertEqual(q._reduce_art_back(back, self.W, self.H), (None, None))

    def test_size_mismatch_falls_back_to_the_old_bilinear_path(self):
        back = noisy_layer((self.W * SS + 2, self.H * SS), 6)
        small, at = shell(box=(1, 1, 9, 9))._reduce_art_back(back, self.W, self.H)
        self.assertIsNone(at)
        self.assertTrue(same_pixels(small, old_small(back, self.W, self.H)))


def flat_pet(theta=0.0):
    """Real Pet shell + real scene art with the flat workspace (see test_native_composition)."""
    p = owner(1.25)
    p.sw, p.sh = 2880, 1800
    p._flat_panel_style = p._studio_style = True
    p._house_on = False
    p.settings = {}
    p._flat_mode = 'tasks'
    g = p._art_geo(1)
    p._swing = {'geo': g, 'theta': theta, 'scene_l': 0, 'scene_t': 0, 'ui': snapshot(),
                'art': True}
    return p


def pushed(p, small_back, at, box, enabled=True):
    p._art_small_back, p._hat_fx_back_box = small_back, box
    if at is None:
        p.__dict__.pop('_art_small_back_at', None)     # a caller that never heard of it
    else:
        p._art_small_back_at = at
    p._hat_fx_enabled_now = lambda: enabled
    with patch('pet.push_layered'):
        p._push_swing_art(Image.new('RGBA', (p.W, p.H)))
    return p._swing['scene_canvas'].copy()


def reduced_now(p, back, box, enabled=True):
    """What render() hands to push after Fix B (the box was set by gain_star)."""
    p._hat_fx_back_box = box
    p._hat_fx_enabled_now = lambda: enabled
    return p._reduce_art_back(back, p.W, p.H)


class FlatPushBackLayerTests(unittest.TestCase):
    BOXES = ((0, 0, 537, 650), (10, 8, 40, 30), (0, 0, 1, 1), (200, 100, 330, 220),
             (533, 646, 537, 650), (333, 17, 334, 52), (150, 120, 420, 400),
             (66, 40, 472, 390))

    def test_composited_canvas_is_identical_for_every_scale_and_box(self):
        scales, visible = set(), 0
        for theta in (0.0, .1, -.12, .2):
            p = flat_pet(theta)
            W, H = p.W, p.H
            back = noisy_layer((W * SS, H * SS), 11)
            full = old_small(back, W, H)
            blank = pushed(p, None, None, None)
            _, _, bs = p._art_small_map(p._swing)
            scales.add(round(bs, 3))
            for box in self.BOXES:
                with self.subTest(theta=theta, box=box):
                    before = pushed(p, full, None, box)           # old: whole layer, push crops
                    small, at = reduced_now(p, back, box)         # new: render hands the crop
                    self.assertEqual(at, None if box == (0, 0, 537, 650) else box[:2])
                    after = pushed(p, small, at, box)
                    self.assertTrue(same_pixels(before, after))
                    visible += not same_pixels(before, blank)
        self.assertGreater(len(scales), 2)          # the BILINEAR resize path is exercised
        self.assertTrue(any(abs(s - 1) > 1e-3 for s in scales))
        self.assertGreater(visible, 15)             # and the comparison is not vacuous

    def test_zero_size_and_fallback_boxes_push_the_same_canvas_as_before(self):
        # Boxes the fast path will not touch keep the whole-layer path, hence the very
        # same outcome as before -- including the ValueError push already raised for a
        # zero-sized box once the layer is rescaled (a latent bug, deliberately kept).
        def outcome(small, at, box):
            try:
                return 'canvas', pushed(p, small, at, box)
            except ValueError as e:
                return 'ValueError', str(e)

        for theta in (0.0, .1):
            p = flat_pet(theta)
            W, H = p.W, p.H
            back = noisy_layer((W * SS, H * SS), 13)
            full = old_small(back, W, H)
            for box in ((5, 5, 5, 9), (5, 5, 9, 5), (-5, -3, 10, 10),
                        (W - 4, H - 4, W + 9, H + 9), (W + 2, 0, W + 8, 5), None):
                with self.subTest(theta=theta, box=box):
                    before = outcome(full, None, box)
                    small, at = reduced_now(p, back, box)
                    self.assertIsNone(at)                      # whole-layer path
                    after = outcome(small, at, box)
                    self.assertEqual(before[0], after[0])
                    if before[0] == 'canvas':
                        self.assertTrue(same_pixels(before[1], after[1]))
                    else:
                        self.assertEqual(before[1], after[1])

    def test_hat_fx_off_composites_nothing_and_render_skips_the_layer(self):
        p = flat_pet(.1)
        W, H = p.W, p.H
        back = noisy_layer((W * SS, H * SS), 12)
        box = (100, 80, 300, 260)
        none = pushed(p, None, None, box)
        # old: the full layer was reduced and handed over, push ignored it (hat fx off)
        off = pushed(p, old_small(back, W, H), None, box, enabled=False)
        self.assertTrue(same_pixels(none, off))
        self.assertEqual(reduced_now(p, back, box, enabled=False), (None, None))
        small, at = reduced_now(p, back, box)
        on = pushed(p, small, at, box)
        self.assertFalse(same_pixels(none, on))       # with hat fx on the dust is painted

    def test_owner_without_the_offset_attribute_still_crops_by_box(self):
        # an owner/test double that never heard of _art_small_back_at keeps the old behaviour
        p = flat_pet(.1)
        W, H = p.W, p.H
        back = noisy_layer((W * SS, H * SS), 11)
        box = (150, 120, 420, 400)
        legacy = pushed(p, old_small(back, W, H), None, box)
        self.assertNotIn('_art_small_back_at', p.__dict__)
        small, at = reduced_now(p, back, box)
        self.assertTrue(same_pixels(legacy, pushed(p, small, at, box)))
        self.assertFalse(same_pixels(legacy, pushed(p, None, None, box)))


class RealSizeTests(unittest.TestCase):
    def test_live_window_size_byte_identical(self):
        # BASE 430x520 at scale 1.25 -> 537x650, supersampled 1074x1300
        W, H = int(pet.BASE_W * 1.25), int(pet.BASE_H * 1.25)
        back = noisy_layer((W * SS, H * SS), 21)
        full = old_small(back, W, H)
        rng = random.Random(3)
        for _ in range(20):
            x0, y0 = rng.randrange(0, W - 1), rng.randrange(0, H - 1)
            box = (x0, y0, rng.randrange(x0 + 1, W + 1), rng.randrange(y0 + 1, H + 1))
            small, at = shell(box=box)._reduce_art_back(back, W, H)
            self.assertEqual(at, box[:2])
            self.assertTrue(same_pixels(small, full.crop(box)), box)


if __name__ == '__main__':
    unittest.main()
