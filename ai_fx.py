"""Small deterministic PIL motions and effects for the AI character column.

Translations are fractions of sprite height; angle is clockwise degrees.
Transforms pivot at bottom centre. Effects never allocate a full workspace
layer, blur, read files, or paint to the right of 174 logical pixels.
MotionCache renders the per-frame transforms at sub-pixel precision into a
bounded LRU, so a steady motion cycle resamples nothing.
"""
from collections import OrderedDict
import math
import threading
import time
from PIL import Image, ImageColor, ImageDraw, ImageFont

IDENTITY = (0.0, 0.0, 0.0, 1.0, 1.0)
MAX_PIXELS = 4_000_000
LEFT_WIDTH = 174
SUBPIXEL = 8              # translation steps per pixel
ANGLE_STEP = .05          # degrees
SCALE_STEP = .001
CACHE_PIXELS = 16_000_000
CACHE_ITEMS = 1024
# Seconds sampled to find a family's worst-case envelope and to pre-render one
# cycle: a full period, or a one-shot entry plus the period it settles into.
SPANS = dict(bob=3.2, hop=.8, quick=.45, slow=4.5, jump=.7, rock=3.0, sway=1.8,
             float=4.2, shake=1.4, squish=1.6, gift=1.75, jolt=3.75, dash=2.2, leave=1.0)
SLIDES = frozenset(('dash', 'leave'))   # exits slide out and are clipped, not shrunk
PAD = 2      # PIL's BICUBIC drops output pixels mapped outside the source: pad edges
_FONT = ImageFont.load_default()
_EFFECTS = frozenset(('pat', 'sleeping', 'sleep', 'idle', 'victory', 'proud', 'happy',
    'celebrate', 'hum', 'thinking', 'surprised', 'oops', 'tired', 'stretch', 'yawn',
    'bubbles', 'steam', 'priceDown', 'priceUp', 'greet_morning', 'greet_noon',
    'greet_afternoon', 'greet_evening', 'greet_night', 'greet_dawn',
    'fest_halloween', 'fest_christmas', 'fest_newyear', 'fest_spring',
    'fest_lantern', 'fest_dragonboat', 'fest_midautumn', 'fest_national'))


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _wave(t, period):
    return (1 - math.cos(2 * math.pi * (t % period) / period)) / 2


def _keys(t, keys):
    for (a, v), (b, w) in zip(keys, keys[1:]):
        if t <= b:
            p = max(0, min(1, (t - a) / (b - a)))
            p = p * p * (3 - 2 * p)
            return tuple(x + (y - x) * p for x, y in zip(v, w))
    return keys[-1][1]


def motion(name, t):
    """The upstream motion families, sampled without mutable timers or RNG."""
    if not isinstance(name, str) or not _finite(t) or t < 0:
        return IDENTITY
    if name in ('bob', 'hop', 'quick', 'slow'):
        period, amount = {'bob': (3.2, .025), 'hop': (.8, .05),
                          'quick': (.45, .018), 'slow': (4.5, .008)}[name]
        p = _wave(t, period)
        return (0.0, -amount * p, 0.0, 1 + .01 * p if name == 'slow' else 1.0,
                1 + .015 * p if name == 'slow' else 1.0)
    if name == 'jump':
        p = _wave(t, .7)
        return (0.0, -.09 * p, 0.0, 1.02 - .04 * p, .98 + .04 * p)
    if name in ('rock', 'sway'):
        return (0.0, 0.0, -2.5 + 5 * _wave(t, 3 if name == 'rock' else 1.8), 1.0, 1.0)
    if name == 'float':
        p = _wave(t, 4.2)
        return (0.0, -.04 - .06 * p, -1.5 + 3 * p, 1.0, 1.0)
    if name == 'shake':
        p = (t % 1.4) / 1.4
        dx = _keys(p, ((0, (0,)), (.1, (-.03,)), (.2, (.03,)),
                       (.3, (-.02,)), (.4, (.02,)), (.5, (0,)), (1, (0,))))[0]
        return (dx, 0.0, 0.0, 1.0, 1.0)
    if name == 'squish':
        p = _wave(t, 1.6)
        return (0.0, 0.0, 0.0, 1 - .04 * p, 1 + .05 * p)
    if name == 'gift':
        if t >= .65:
            return (0.0, -.05 * _wave(t - .65, 1.1), 0.0, 1.0, 1.0)
        return _keys(t / .65, ((0, (0, .03, 0, 1.05, .93)),
                              (.45, (0, -.09, 0, .97, 1.04)), (1, IDENTITY)))
    if name == 'jolt':
        if t >= .55:
            return motion('bob', t - .55)
        return _keys(t / .55, ((0, IDENTITY), (.25, (-.03, -.04, -4, .97, 1.04)),
                              (.6, (.01, 0, 1.5, 1, 1)), (1, IDENTITY)))
    if name in ('dash', 'leave'):
        p = min(1, t / (2.2 if name == 'dash' else 1.0))
        p = max(0, (p - .55) / .45) if name == 'dash' else p
        p = p * p
        return (.28 * p, 0.0, 4 * p, 1.0, 1.0)
    return IDENTITY


def _transform(value):
    if not isinstance(value, (tuple, list)) or len(value) != 5 or not all(_finite(x) for x in value):
        return IDENTITY
    dx, dy, angle, sx, sy = value
    return (max(-.3, min(.3, dx)), max(-.15, min(.15, dy)), max(-8, min(8, angle)),
            max(.9, min(1.1, sx)), max(.9, min(1.1, sy)))


def apply(img, transform):
    """Return a transformed image and placement offset; never modify img.

    A pure translation returns the same image, so its pixels are not resampled.
    Invalid transform values mean identity. Oversized input fails explicitly.
    """
    if not isinstance(img, Image.Image) or img.width * img.height > MAX_PIXELS:
        raise ValueError('sprite exceeds pixel budget')
    dx, dy, angle, sx, sy = _transform(transform)
    w, h = img.size
    shift = (round(dx * h), round(dy * h))
    if angle == 0 and sx == sy == 1:
        return img, shift
    rad = math.radians(angle)
    a, b, c, d = sx * math.cos(rad), -sy * math.sin(rad), sx * math.sin(rad), sy * math.cos(rad)
    ox, oy = w / 2, h
    points = [(a * (x - ox) + b * (y - oy) + ox + shift[0],
               c * (x - ox) + d * (y - oy) + oy + shift[1])
              for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
    left = math.floor(min(x for x, _ in points)) - 1
    top = math.floor(min(y for _, y in points)) - 1
    right = math.ceil(max(x for x, _ in points)) + 1
    bottom = math.ceil(max(y for _, y in points)) + 1
    size = (right - left, bottom - top)
    if size[0] * size[1] > MAX_PIXELS:
        return img, shift
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    tx, ty = left - ox - shift[0], top - oy - shift[1]
    matrix = (ia, ib, ia * tx + ib * ty + ox, ic, id_, ic * tx + id_ * ty + oy)
    image = img.convert('RGBa').transform(size, Image.Transform.AFFINE, matrix,
                                         Image.Resampling.BICUBIC).convert('RGBA')
    return image, (left, top)


def crossfade(old, new, alpha):
    """Premultiplied blend for equal-size RGBA canvases; alpha is 0..1.

    The caller supplies the 350 ms elapsed fraction and canvas placement. This
    pure helper does not run a clock or fade unrelated workspace pixels.
    """
    if (not isinstance(old, Image.Image) or not isinstance(new, Image.Image)
            or old.size != new.size or old.width * old.height > MAX_PIXELS):
        raise ValueError('crossfade needs equal bounded canvases')
    alpha = max(0, min(1, alpha)) if _finite(alpha) else 1
    if alpha == 0:
        return old
    if alpha == 1:
        return new
    return Image.blend(old.convert('RGBa'), new.convert('RGBa'), alpha).convert('RGBA')


def _bezier(p1, p2, s):
    return 3*(1-s)*(1-s)*s*p1 + 3*(1-s)*s*s*p2 + s*s*s


def _ease_table(x1, y1, x2, y2, steps=256):
    table = []
    for i in range(steps + 1):
        x, lo, hi = i / steps, 0.0, 1.0
        for _ in range(40):          # x(s) is monotone for CSS timing curves
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if _bezier(x1, x2, mid) < x else (lo, mid)
        table.append(_bezier(y1, y2, (lo + hi) / 2))
    table[0], table[-1] = 0.0, 1.0
    return tuple(table)


EASE = _ease_table(.25, .1, .25, 1)      # CSS 'ease', CrossPet's opacity transition


def ease(t):
    """CSS ease cubic-bezier(.25,.1,.25,1) through a 257-entry table."""
    if not _finite(t) or t >= 1:
        return 1.0
    if t <= 0:
        return 0.0
    i, f = divmod(t * (len(EASE) - 1), 1)
    i = int(i)
    return EASE[i] + (EASE[i + 1] - EASE[i]) * f


def crossfade_sprites(old, new, alpha):
    """Fade two placed sprites, (image, (x, y)), inside their union only.

    alpha is the linear 0..1 fade; it is eased like CrossPet. Returns
    (image, (x, y), alpha_box). The blend itself is crossfade() (premultiplied).
    """
    (oi, (ox, oy)), (ni, (nx, ny)) = old[:2], new[:2]
    alpha = ease(alpha)
    left, top = min(ox, nx), min(oy, ny)
    size = (max(ox + oi.width, nx + ni.width) - left, max(oy + oi.height, ny + ni.height) - top)

    def layer(img, x, y):
        if (x, y) == (left, top) and img.size == size:
            return img
        out = Image.new('RGBA', size)
        out.paste(img, (x - left, y - top))
        return out
    image = crossfade(layer(oi, ox, oy), layer(ni, nx, ny), alpha)
    return image, (left, top), image.getchannel('A').getbbox()


def _quantise(transform, height, fit):
    dx, dy, angle, sx, sy = _transform(transform)
    return (round(dx * height * fit * SUBPIXEL), round(dy * height * fit * SUBPIXEL),
            round(angle / ANGLE_STEP), round(sx / SCALE_STEP), round(sy / SCALE_STEP))


def _linear(fit, ai, si, ti):
    rad = math.radians(ai * ANGLE_STEP)
    sx, sy = si * SCALE_STEP * fit, ti * SCALE_STEP * fit
    return sx * math.cos(rad), -sy * math.sin(rad), sx * math.sin(rad), sy * math.cos(rad)


def _hull(alpha):
    """Convex hull of an L mask's nonzero pixel squares, as edge coordinates."""
    w, h = alpha.size
    data, points = alpha.tobytes(), []
    for y in range(h):
        row = data[y*w:(y+1)*w]
        right = len(row.rstrip(b'\0'))
        if right:
            left = w - len(row.lstrip(b'\0'))
            points += ((left, y), (left, y+1), (right, y), (right, y+1))
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def side(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and side(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and side(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class _Source:
    """Per-sprite facts, computed once: alpha box, hull, premultiplied pixels."""
    __slots__ = ('image', 'box', '_hull', '_premul')

    def __init__(self, image):
        self.image, self.box = image, image.getchannel('A').getbbox()
        self._hull = self._premul = None

    @property
    def hull(self):
        if self._hull is None:
            w, h = self.image.size
            self._hull = tuple((x - w/2, y - h) for x, y in _hull(self.image.getchannel('A')))
        return self._hull

    @property
    def premul(self):
        if self._premul is None:
            w, h = self.image.size
            padded = Image.new('RGBa', (w + 2*PAD, h + 2*PAD))
            padded.paste(self.image.convert('RGBa'), (PAD, PAD))
            self._premul = padded
        return self._premul


class MotionCache:
    """Sub-pixel transformed sprites in a bounded LRU; safe for one warm thread.

    Keys must identify the source pixels (CharacterFrame.ref does: character,
    pack version and fingerprint, pose, variant, blink and box size). Placement
    is an integer floor position; the 1/8 px remainder of the translation, the
    angle (0.05 deg) and the scale (0.001) are folded into one BICUBIC affine on
    premultiplied pixels. An integer translation alone returns the source image.
    """
    def __init__(self, max_pixels=CACHE_PIXELS, max_items=CACHE_ITEMS, max_sources=24):
        self.max_pixels, self.max_items, self.max_sources = max_pixels, max_items, max_sources
        self._items, self._sources, self._fits = OrderedDict(), OrderedDict(), OrderedDict()
        self._pixels = 0
        self._lock = threading.Lock()
        self._generation = 0
        self._worker = None
        self.hits = self.misses = 0

    @property
    def pixels(self):
        return self._pixels

    def __len__(self):
        return len(self._items)

    def _source(self, key, img):
        with self._lock:
            src = self._sources.get(key)
            if src is not None:
                self._sources.move_to_end(key)
                return src
        src = _Source(img)
        with self._lock:
            src = self._sources.setdefault(key, src)
            while len(self._sources) > self.max_sources:
                self._sources.popitem(last=False)
        return src

    def _get(self, ck):
        with self._lock:
            hit = self._items.get(ck)
            if hit is not None:
                self._items.move_to_end(ck)
            return hit

    def _store(self, ck, value):
        pixels = value[0].width * value[0].height
        if pixels > self.max_pixels:
            return value
        with self._lock:
            held = self._items.get(ck)
            if held is not None:
                return held
            self._items[ck] = value
            self._pixels += pixels
            while len(self._items) > self.max_items or self._pixels > self.max_pixels:
                _, old = self._items.popitem(last=False)
                self._pixels -= old[0].width * old[0].height
        return value

    @staticmethod
    def _render(src, fit, ai, si, ti, fx, fy, resample=Image.Resampling.BICUBIC):
        w, h = src.image.size
        a, b, c, d = _linear(fit, ai, si, ti)
        ox, oy = w / 2, h
        tx, ty = fx / SUBPIXEL, fy / SUBPIXEL
        points = [(a*(x-ox) + b*(y-oy) + ox + tx, c*(x-ox) + d*(y-oy) + oy + ty)
                  for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
        left = math.floor(min(x for x, _ in points)) - 2
        top = math.floor(min(y for _, y in points)) - 2
        size = (math.ceil(max(x for x, _ in points)) + 2 - left,
                math.ceil(max(y for _, y in points)) + 2 - top)
        det = a * d - b * c
        ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
        sx0, sy0 = left - ox - tx, top - oy - ty
        matrix = (ia, ib, ia*sx0 + ib*sy0 + ox + PAD, ic, id_, ic*sx0 + id_*sy0 + oy + PAD)
        image = src.premul.transform(size, Image.Transform.AFFINE, matrix, resample).convert('RGBA')
        box = image.getchannel('A').getbbox()
        if box is None:
            return Image.new('RGBA', (1, 1)), (0, 0), None
        if box != (0, 0) + size:
            image = image.crop(box)
        return image, (left + box[0], top + box[1]), (0, 0, image.width, image.height)

    def render(self, key, img, transform, fit=1.0, fast=False):
        """(image, (x, y), alpha_box) of img under transform, placed relative to img.

        fit scales the sprite about its pivot (translation included). alpha_box
        is image's alpha bbox, or None when empty. Results are borrowed, read-only.
        fast: a miss is drawn BILINEAR and not kept (a 350 ms crossfade, or
        while the warm thread fills the BICUBIC entries), so the frame loop
        never pays a BICUBIC transform that the worker is about to provide.
        """
        if not isinstance(img, Image.Image) or img.width * img.height > MAX_PIXELS:
            raise ValueError('sprite exceeds pixel budget')
        fit = float(fit) if _finite(fit) and 0 < fit <= 1 else 1.0
        qx, qy, ai, si, ti = _quantise(transform, img.height, fit)
        ix, fx = divmod(qx, SUBPIXEL)
        iy, fy = divmod(qy, SUBPIXEL)
        unit = round(1 / SCALE_STEP)
        if fit == 1 and ai == 0 and si == ti == unit and fx == fy == 0:
            return img, (ix, iy), self._source(key, img).box
        ck = (key, fit, ai, si, ti, fx, fy)
        hit = self._get(ck)
        if hit is None:
            self.misses += 1
            src = self._source(key, img)
            hit = (self._render(src, fit, ai, si, ti, fx, fy, Image.Resampling.BILINEAR) if fast
                   else self._store(ck, self._render(src, fit, ai, si, ti, fx, fy)))
        else:
            self.hits += 1
        image, (x, y), box = hit
        return image, (x + ix, y + iy), box

    def fit(self, key, img, family, box_width, base_x=0):
        """Constant (factor, shift) for one sprite and motion family in a column.

        The family's worst-case horizontal alpha envelope over one span decides
        it once: factor 1 when it already fits, else the largest that does;
        shift moves the base position (never the motion) back inside. Exits
        (dash/leave) size for their tilt only and are clipped as they slide.
        """
        k = (key, family, box_width, base_x)
        with self._lock:
            held = self._fits.get(k)
            if held is not None:
                self._fits.move_to_end(k)
                return held
        src = self._source(key, img)
        hull, h = src.hull, img.height
        if not hull or not _finite(box_width) or box_width <= 0:
            return 1.0, 0
        span = SPANS.get(family) if isinstance(family, str) else None
        # Extremes sit at wave turning points (span/2 is sampled) or listed keyframes;
        # only the horizontal part of a transform matters here.
        times = [0] if span is None else sorted({span * i / 60 for i in range(61)}
                                                | {.1375, .14, .28, .2925, .42, .56})
        samples = {(qx, ai, si, ti) for qx, _, ai, si, ti in
                   (_quantise(motion(family, t) if span else IDENTITY, h, 1.0) for t in times)}
        # Few hull vertices can be extreme for any tilt within the clamped +-10 deg.
        cand = set()
        for half in range(-20, 21):
            u, v = math.cos(math.radians(half / 2)), -math.sin(math.radians(half / 2))
            values = [u*x + v*y for x, y in hull]
            cand.add(hull[values.index(max(values))])
            cand.add(hull[values.index(min(values))])
        low = high = None
        for qx, ai, si, ti in samples:
            a, b, _, _ = _linear(1.0, ai, si, ti)
            tx = 0 if family in SLIDES else qx / SUBPIXEL
            values = [a*x + b*y + tx for x, y in cand]
            low = min(values) if low is None else min(low, min(values))
            high = max(values) if high is None else max(high, max(values))
        # A shrunk sprite keeps 1 px of slack so a whole-pixel base shift fits it.
        factor = 1.0 if high - low <= box_width else (box_width - 1) / (high - low)
        pivot = base_x + img.width / 2
        lo, hi = -factor * low, box_width - factor * high
        shift = 0
        if pivot < lo:
            shift = math.ceil(lo - pivot)
        elif pivot > hi:
            shift = math.floor(hi - pivot)
        held = (factor, shift)
        with self._lock:
            self._fits[k] = held
            while len(self._fits) > 256:
                self._fits.popitem(last=False)
        return held

    def place(self, key, img, offset, family, transform, box_width, fast=False):
        """Fit, render and clip a column sprite: (image, (x, y), alpha_box).

        offset is the sprite's base position in the column; the result lies
        inside [0, box_width) horizontally.
        """
        factor, shift = self.fit(key, img, family, box_width, offset[0])
        image, (x, y), box = self.render(key, img, transform, factor, fast)
        x, y = x + offset[0] + shift, y + offset[1]
        if x < 0 or x + image.width > box_width:
            left, right = max(0, -x), min(image.width, box_width - x)
            if right <= left:
                return Image.new('RGBA', (1, 1)), (0, y), None
            image = image.crop((left, 0, right, image.height))
            x += left
            box = image.getchannel('A').getbbox()
        return image, (x, y), box

    @property
    def warming(self):
        """A warm thread is rendering the current plan's BICUBIC entries."""
        worker = self._worker
        return worker is not None and worker.is_alive()

    def cancel(self):
        with self._lock:
            self._generation += 1

    def warm(self, jobs, family, start):
        """Pre-render one span of family from motion time start on a daemon thread.

        jobs are (key, img, offset, box_width, seconds or None). Only PIL and
        this cache are touched; a newer warm() or cancel() stops the older one.
        """
        if family not in SPANS or not _finite(start) or not jobs:
            return None
        with self._lock:
            self._generation += 1
            generation = self._generation
        worker = threading.Thread(target=self._warm, args=(generation, tuple(jobs), family, start),
                                  name='ai-motion-warm', daemon=True)
        self._worker = worker
        worker.start()
        return worker

    def _warm(self, generation, jobs, family, start):
        try:
            span, seen, budget = SPANS[family], set(), self.max_pixels // 2
            plans = []
            for key, img, offset, width, seconds in jobs:
                factor, _ = self.fit(key, img, family, width, offset[0])
                plans.append((key, img, factor, span if seconds is None else min(span, seconds)))
            for step in range(round(span * 480) + 1):
                if step % 32 == 0:
                    time.sleep(0)       # hand the GIL back to the frame loop
                if generation != self._generation or budget <= 0:
                    return
                t = start + step / 480
                transform = motion(family, t)
                for key, img, factor, seconds in plans:
                    if step / 480 > seconds:
                        continue
                    qx, qy, ai, si, ti = _quantise(transform, img.height, factor)
                    ck = (key, factor, ai, si, ti, qx % SUBPIXEL, qy % SUBPIXEL)
                    if ck in seen:
                        continue
                    seen.add(ck)
                    if (factor == 1 and ai == 0 and si == ti == round(1 / SCALE_STEP)
                            and ck[5] == ck[6] == 0) or self._get(ck) is not None:
                        continue
                    image = self._store(ck, self._render(self._source(key, img), *ck[1:]))[0]
                    budget -= image.width * image.height
        except Exception:
            return              # a cold miss on the frame loop still renders correctly


def draw(canvas, fx, age, sprite_box, u, accent, glyph=None):
    """Paint a bounded finite effect in place, clipped to the AI character column.

    glyph is an optional already-loaded PIL font. Unknown effects (including
    upstream software cards) paint nothing. Time sampling is deterministic.
    """
    if (not isinstance(canvas, Image.Image) or canvas.mode != 'RGBA'
            or not isinstance(fx, str) or fx not in _EFFECTS or not _finite(age) or age < 0
            or not _finite(u) or not 0 < u <= 4 or not isinstance(sprite_box, (list, tuple))
            or len(sprite_box) != 4 or not all(_finite(v) for v in sprite_box)):
        return
    left, top, right, bottom = sprite_box
    if right <= left or bottom <= top:
        return
    age %= 3600  # finite input must also stay finite through phase multiplications
    width = min(canvas.width, math.ceil(LEFT_WIDTH * u))
    headroom = 34 if fx == 'thinking' else 28
    y0, y1 = max(0, math.floor(top - headroom * u)), min(canvas.height, math.ceil(bottom + 12 * u))
    if width <= 0 or y1 <= y0 or width * (y1 - y0) > MAX_PIXELS:
        return
    try:
        color = ImageColor.getrgb(accent) if isinstance(accent, str) else tuple(accent)[:3]
        if len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
            return
    except (TypeError, ValueError):
        return
    layer = Image.new('RGBA', (width, y1 - y0))
    pen = ImageDraw.Draw(layer)
    font = glyph if isinstance(glyph, ImageFont.ImageFont) or hasattr(glyph, 'getmask') else _FONT
    top, bottom = top - y0, bottom - y0
    h = bottom - top
    x1, x2 = max(5*u, min(width-5*u, left+5*u)), max(5*u, min(width-5*u, right-5*u))
    head = max(8*u, top-8*u)
    ink, warm, red = color + (220,), (255, 213, 126, 230), (244, 123, 132, 230)
    thick = max(1, round(u))

    def text(x, y, word, fill=ink):
        pen.text((x, y), word, font=font, fill=fill, anchor='mm')

    def star(x, y, radius=4*u, fill=warm):
        pts = [(x+math.cos(-math.pi/2+i*math.pi/4)*(radius if i % 2 == 0 else radius*.32),
                y+math.sin(-math.pi/2+i*math.pi/4)*(radius if i % 2 == 0 else radius*.32)) for i in range(8)]
        pen.polygon(pts, fill=fill)

    def heart(x, y, size=5*u):
        pen.ellipse((x-size, y-size*.75, x, y+size*.25), fill=red)
        pen.ellipse((x, y-size*.75, x+size, y+size*.25), fill=red)
        pen.polygon(((x-size, y), (x+size, y), (x, y+size)), fill=red)

    def moon(x, y, size=6*u):
        # A polygon crescent keeps its transparent interior; no erasing body pixels.
        pts = [(x+size*math.cos(a), y+size*math.sin(a)) for a in [math.pi*.3+i*math.pi*1.4/14 for i in range(15)]]
        pts += [(x+size*.32+size*.8*math.cos(a), y+size*.8*math.sin(a))
                for a in [math.pi*1.7-i*math.pi*1.4/14 for i in range(15)]]
        pen.polygon(pts, fill=warm)

    if fx == 'pat':
        for i, x in enumerate((x1, x2, (x1+x2)/2)):
            phase = (age*.5+i*.31) % 1
            heart(x, max(6*u, top+h*.2-phase*16*u), (3+2*(1-phase))*u)
    elif fx in ('sleeping', 'sleep'):
        moon(x1, head)
        for i in range(2):
            text(x2-i*6*u, max(7*u, top+12*u-((age*.4+i*.4)%1)*18*u), 'z' if i else 'Z')
    elif fx in ('idle', 'proud', 'victory', 'happy', 'celebrate'):
        for i, x in enumerate((x1, x2)):
            star(x, top+h*(.22+.2*i)+math.sin(age*2+i)*3*u, (3+math.sin(age*3+i))*u)
        if fx in ('happy', 'celebrate', 'victory'):
            for i in range(8):
                phase = (age/2.2+i/8) % 1
                x = 6*u + (max(0, width-12*u) * ((i*.618)%1))
                y = head + phase*min(h*.6, 75*u)
                pen.rectangle((x,y,x+2*u,y+3*u), fill=(red if i%2 else ink))
    elif fx == 'hum':
        for i, x in enumerate((x1,x2)):
            y = top+h*.25-((age*.4+i*.5)%1)*16*u
            pen.ellipse((x-3*u,y,x+2*u,y+3*u),fill=ink)
            pen.line((x+2*u,y+u,x+2*u,y-9*u,x+6*u,y-7*u),fill=ink,width=thick)
    elif fx == 'thinking':
        # The host supplies the visible alpha bounds, with dedicated headroom.
        # Keep even the smallest tail strictly above the art, then gently float
        # the complete cloud. A short/tight canvas scales the whole shape down.
        unit = min(u, max(0, (top + y0 - u - 1) / 32), max(0, (width - 2*u) / 54))
        if unit < .2:
            return
        x = max(9*unit, min(width-45*unit, (left+right)/2+16*unit))
        y = top-u-1-30.5*unit-1.5*unit*_wave(age, 2.4)
        white = (252, 252, 255, 250)
        outline = tuple(round(v*.2+43) for v in color) + (255,)
        edge = max(1, round(1.2*unit))
        # The two separate bubbles point toward the head rather than the face.
        for tx, ty, r in ((-1.5, 25, 2.5), (-6.5, 29, 1.5)):
            cx, cy, r = x+tx*unit, y+ty*unit, r*unit
            pen.ellipse((cx-r,cy-r,cx+r,cy+r), fill=white, outline=outline, width=edge)
        # One exterior curve avoids the seams of overlapping outlined ellipses.
        controls = (((7,22),(0,22),(0,14),(4,11)),
                    ((4,11),(2,5),(7,2),(13,5)),
                    ((13,5),(17,-1),(27,-1),(31,5)),
                    ((31,5),(36,2),(43,5),(41,11)),
                    ((41,11),(47,15),(42,22),(35,22)),
                    ((35,22),(28,22),(15,22),(7,22)))
        points = []
        for start, a, b, end in controls:
            for step in range(9):
                t = step/8; q = 1-t
                px = q*q*q*start[0]+3*q*q*t*a[0]+3*q*t*t*b[0]+t*t*t*end[0]
                py = q*q*q*start[1]+3*q*q*t*a[1]+3*q*t*t*b[1]+t*t*t*end[1]
                points.append((x+px*unit,y+py*unit))
        pen.polygon(points, fill=white)
        pen.line(points+[points[0]], fill=outline, width=edge, joint='curve')
        # Mix with white instead of lowering pixel alpha: dim dots remain legible
        # without punching transparent holes through the white cloud.
        dot = tuple(round(v*.68) for v in color)
        for i in range(3):
            bright = .2+.8*_wave(age-i*.3, 1.2)
            fill = tuple(round(white[k]*(1-bright)+dot[k]*bright) for k in range(3)) + (255,)
            cx, cy, r = x+(15+7*i)*unit, y+12*unit, 2.15*unit
            pen.ellipse((cx-r,cy-r,cx+r,cy+r), fill=fill)
    elif fx == 'surprised':
        text(x2, head, '!')
        for i in range(3):
            pen.line((x2+(i-1)*6*u,head-9*u,x2+(i-1)*8*u,head-13*u),fill=warm,width=thick)
    elif fx == 'oops':
        r=4*u; y=top+h*.18
        pen.line((x2-r,y-r,x2+r,y+r),fill=red,width=max(2,round(2*u)))
        pen.line((x2-r,y+r,x2+r,y-r),fill=red,width=max(2,round(2*u)))
    elif fx == 'tired':
        y = top+h*.2
        pen.rounded_rectangle((x2-8*u,y-4*u,x2+7*u,y+4*u),radius=u,outline=ink,width=thick)
        pen.rectangle((x2-6*u,y-2*u,x2-3*u,y+2*u),fill=red)
        pen.line((x2+8*u,y-u,x2+8*u,y+u),fill=ink,width=thick)
    elif fx == 'stretch':
        for i in range(6):
            x = x1 if i%2 else x2
            y = top+h*(.25+.06*i)+math.sin(age*2+i)*3*u
            r = (1.3+.5*math.sin(age*3+i))*u
            pen.ellipse((x-r,y-r,x+r,y+r),fill=warm)
    elif fx == 'yawn':
        text(x1,head,'~');heart(x2,head,3*u)
    elif fx in ('bubbles','steam'):
        for i in range(5):
            x = x1 if i%2 else x2
            phase=(age/(3+i*.2)+i*.2)%1
            y=top+h*.55-phase*min(h*.55,80*u)
            r=(2+i%3)*u
            if fx == 'bubbles':
                pen.ellipse((x-r,y-r,x+r,y+r),outline=(154,216,247,180),width=thick)
            else:
                pen.arc((x-r,y-r*2,x+r,y+r*2),-80,80,fill=(226,235,245,130),width=thick)
    elif fx in ('priceDown','priceUp'):
        y=top+h*.18;sign=-1 if fx=='priceUp' else 1
        pen.line((x2,y-5*u*sign,x2,y+5*u*sign),fill=ink,width=thick)
        pen.line((x2-3*u,y+2*u*sign,x2,y+5*u*sign,x2+3*u,y+2*u*sign),fill=ink,width=thick)
    elif fx in ('greet_morning','greet_noon'):
        pen.ellipse((x2-5*u,head-5*u,x2+5*u,head+5*u),fill=warm)
        for i in range(8):
            a=i*math.pi/4+age*.15
            pen.line((x2+math.cos(a)*7*u,head+math.sin(a)*7*u,x2+math.cos(a)*10*u,head+math.sin(a)*10*u),fill=warm,width=thick)
    elif fx in ('greet_night','greet_dawn','fest_midautumn'):
        moon(x2,head);star(x1,top+h*.25,3*u)
    elif fx in ('greet_evening','fest_halloween'):
        for i in range(5):
            x=6*u+(width-12*u)*((i*.618)%1);y=top+h*(.15+.08*i)+math.sin(age+i)*4*u
            r=(1.3+.5*math.sin(age*2+i))*u
            pen.ellipse((x-r,y-r,x+r,y+r),fill=warm)
    elif fx in ('greet_afternoon','fest_dragonboat'):
        for i,x in enumerate((x1,x2)):
            y=top+h*.2+((age*.15+i*.5)%1)*h*.4
            pen.polygon(((x-3*u,y),(x,y-5*u),(x+3*u,y),(x,y+5*u)),fill=(192,170,116,210) if fx=='greet_afternoon' else (145,207,161,210))
    elif fx == 'fest_christmas':
        for i in range(6):
            x=6*u+(width-12*u)*((i*.618)%1);y=head+((age*.15+i/6)%1)*min(h*.6,90*u)
            for a in (0,math.pi/3,2*math.pi/3):
                pen.line((x-math.cos(a)*3*u,y-math.sin(a)*3*u,x+math.cos(a)*3*u,y+math.sin(a)*3*u),fill=(230,242,255,210),width=thick)
    elif fx in ('fest_spring','fest_lantern'):
        for x in (x1,x2):
            y=head+math.sin(age)*2*u
            pen.ellipse((x-5*u,y-7*u,x+5*u,y+5*u),fill=(231,110,96,225),outline=warm,width=thick)
            pen.line((x,y+5*u,x,y+10*u),fill=warm,width=thick)
    elif fx in ('fest_newyear','fest_national'):
        phase=(age%1.7)/1.7
        for i in range(8):
            a=i*math.pi/4;r=(4+10*phase)*u;x=(x1+x2)/2
            pen.line((x+math.cos(a)*r*.65,head+math.sin(a)*r*.65,x+math.cos(a)*r,head+math.sin(a)*r),fill=color+(round(220*(1-phase)),),width=thick)
    canvas.alpha_composite(layer,(0,y0))
