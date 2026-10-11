"""Alpha-bbox trimmed reduce of the main supersampled frame (optional Fix C).

Pet._reduce_frame must return exactly what render() always computed,
frame.convert("RGBa").reduce(SS): same mode, size and bytes, for any content --
alpha 0 pixels with garbage RGB, alpha 1, 254, 255, sprites touching every edge,
bounding boxes that are not multiples of SS, empty frames, big frames.

No Pet instance, no Tk window.
"""
import random
import unittest

from PIL import Image

import pet

SS = pet.SS


def old(frame):
    return frame.convert('RGBa').reduce(SS)


def same(a, b):
    return a.mode == b.mode and a.size == b.size and a.tobytes() == b.tobytes()


def garbage_under_transparency(size, rng):
    """RGB noise everywhere, alpha 0 everywhere: premultiplication must erase all of it."""
    w, h = size
    img = Image.frombytes('RGBA', size, rng.randbytes(w * h * 4))
    img.putalpha(0)
    return img


def sprite(rng, w, h):
    s = Image.frombytes('RGBA', (w, h), rng.randbytes(w * h * 4))
    # faint, half and full alpha mixed with fully transparent holes
    s.putalpha(s.getchannel('A').point(lambda v: (0, 1, 254, 255, v)[v % 5]))
    return s


def scattered(W, H, rng, region, count):
    """Garbage-padded frame with `count` sprites placed inside region (1x coords)."""
    frame = garbage_under_transparency((W * SS, H * SS), rng)
    x0, y0, x1, y1 = region
    for i in range(count):
        w, h = rng.randrange(1, 40), rng.randrange(1, 40)
        w, h = min(w, (x1 - x0) * SS), min(h, (y1 - y0) * SS)
        x = rng.randrange(x0 * SS, max(x0 * SS + 1, x1 * SS - w))
        y = rng.randrange(y0 * SS, max(y0 * SS + 1, y1 * SS - h))
        if i == 0:                    # pin the bounding box to the region's corners
            x, y = x0 * SS, y0 * SS
        elif i == 1:
            x, y = x1 * SS - w, y1 * SS - h
        frame.alpha_composite(sprite(rng, w, h), (x, y))
    return frame


class ReduceFrameTests(unittest.TestCase):
    W, H = 70, 53    # odd sizes on purpose

    def check(self, frame, W=None, H=None):
        W, H = W or self.W, H or self.H
        got = pet.Pet._reduce_frame(frame, W, H)
        self.assertTrue(same(got, old(frame)))
        return got

    def test_empty_frame(self):
        frame = Image.new('RGBA', (self.W * SS, self.H * SS), (0, 0, 0, 0))
        self.check(frame)
        self.check(garbage_under_transparency(frame.size, random.Random(1)))

    def test_a_single_pixel_anywhere_including_every_corner_and_odd_offsets(self):
        W, H = self.W, self.H
        rng = random.Random(2)
        spots = [(0, 0), (W * SS - 1, 0), (0, H * SS - 1), (W * SS - 1, H * SS - 1),
                 (1, 1), (W * SS // 2, H * SS // 2), (W * SS // 2 + 1, H * SS // 2 + 1)]
        spots += [(rng.randrange(W * SS), rng.randrange(H * SS)) for _ in range(60)]
        for x, y in spots:
            for alpha in (1, 128, 255):
                with self.subTest(x=x, y=y, alpha=alpha):
                    frame = garbage_under_transparency((W * SS, H * SS), rng)
                    frame.putpixel((x, y), (200, 100, 50, alpha))
                    self.check(frame)

    def test_random_sprites_in_regions_of_every_size(self):
        W, H = self.W, self.H
        rng = random.Random(3)
        cropped = fallback = 0
        for i in range(300):
            rw, rh = rng.randrange(2, W + 1), rng.randrange(2, H + 1)
            rx, ry = rng.randrange(0, W - rw + 1), rng.randrange(0, H - rh + 1)
            frame = scattered(W, H, rng, (rx, ry, rx + rw, ry + rh), rng.randrange(2, 7))
            bb = frame.getbbox(alpha_only=True)
            x0, y0, x1, y1 = bb[0] // SS, bb[1] // SS, -(-bb[2] // SS), -(-bb[3] // SS)
            if (x1 - x0) * (y1 - y0) * 2 > W * H:
                fallback += 1
            else:
                cropped += 1
            with self.subTest(i=i, bbox=bb):
                self.check(frame)
        self.assertGreater(cropped, 20)       # both branches are really exercised
        self.assertGreater(fallback, 20)

    def test_content_on_every_edge_and_full_frame(self):
        W, H = self.W, self.H
        rng = random.Random(4)
        for region in ((0, 0, W, 3), (0, H - 3, W, H), (0, 0, 3, H), (W - 3, 0, W, H),
                       (0, 0, W, H)):
            with self.subTest(region=region):
                self.check(scattered(W, H, rng, region, 8))
        full = sprite(rng, W * SS, H * SS)
        self.check(full)

    def test_bbox_that_is_not_a_multiple_of_ss(self):
        W, H = self.W, self.H
        rng = random.Random(5)
        for x, y, w, h in ((3, 3, 1, 1), (3, 3, 2, 2), (4, 4, 3, 3), (5, 7, 11, 13), (9, 9, 5, 1)):
            with self.subTest(box=(x, y, w, h)):
                frame = garbage_under_transparency((W * SS, H * SS), rng)
                frame.paste(sprite(rng, w, h), (x, y))
                self.check(frame)

    def test_live_window_size(self):
        # BASE 430x520 at scale 1.25 -> 537x650, supersampled 1074x1300
        W, H = int(pet.BASE_W * 1.25), int(pet.BASE_H * 1.25)
        rng = random.Random(6)
        for region in ((100, 40, 440, 300), (0, 0, W, H), (250, 300, 300, 330)):
            with self.subTest(region=region):
                self.check(scattered(W, H, rng, region, 36), W, H)


if __name__ == '__main__':
    unittest.main()
