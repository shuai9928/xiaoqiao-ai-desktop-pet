"""Bounded speech art for the AI character column, independent of the old rig.

Fonts and colours are supplied by the host. No clocks, timers, files or UI live
here; the host keeps one cached sprite and applies its existing speech fade.
"""
import math
from PIL import Image, ImageDraw

LEFT_WIDTH = 174
# Reserve both a readable line and the existing hop/jump/scale envelope. This
# fixed band prevents speech flickering as the character rises; feet stay put.
HEADROOM = 50
MIN_DURATION = 6.0
MAX_DURATION = 10.0
MAX_TEXT = 240


def duration(text):
    return min(MAX_DURATION, max(MIN_DURATION, 2.0 + len(str(text)[:MAX_TEXT]) * .18))


def sprite(text, font, u, max_height, accent):
    """Fit at most two lines, with an ellipsis, to available headroom."""
    if not (type(u) in (int, float) and math.isfinite(u) and .5 <= u <= 4
            and type(max_height) in (int, float) and math.isfinite(max_height)):
        return None
    text = ' '.join(str(text).split())[:MAX_TEXT]
    if not text:
        return None
    pad, tail = round(9*u), max(2, round(3*u))
    line_h = math.ceil(font.getbbox('国Ag')[3] - font.getbbox('国Ag')[1] + 3*u)
    vertical = round(7*u)
    rows = min(2, int((max_height - vertical - tail) // line_h))
    if rows < 1:
        return None
    limit = round((LEFT_WIDTH-8)*u) - 2*pad
    lines, rest = [], text
    for _ in range(rows):
        line = ''
        while rest and font.getlength(line+rest[0]) <= limit:
            line, rest = line+rest[0], rest[1:]
        lines.append(line)
        if not rest:
            break
    if rest:
        while lines[-1] and font.getlength(lines[-1]+'…') > limit:
            lines[-1] = lines[-1][:-1]
        lines[-1] += '…'
    w = max(round(40*u), math.ceil(max(font.getlength(line) for line in lines))+2*pad)
    h = line_h*len(lines)+vertical
    art = Image.new('RGBA', (w, h+tail))
    pen = ImageDraw.Draw(art)
    # A light speech surface stays distinct from all five dark work themes.
    edge = tuple(round(v*.72) for v in accent[:3]) + (255,)
    fill, ink = (250, 249, 247, 246), (47, 42, 51, 255)
    thick = max(1, round(1.3*u))
    radius = min(round(10*u), h//2)
    pen.rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=fill, outline=edge, width=thick)
    cx = w//2
    pen.polygon(((cx-round(4*u),h-2),(cx+round(4*u),h-2),(cx,h+tail-1)), fill=fill)
    pen.line(((cx-round(4*u),h-1),(cx,h+tail-1),(cx+round(4*u),h-1)), fill=edge, width=thick)
    for i, line in enumerate(lines):
        box = font.getbbox(line)
        pen.text(((w-font.getlength(line))/2, vertical/2+i*line_h-box[1]), line, font=font, fill=ink)
    return art


def placement(art, head_box, canvas_size, u):
    """Anchor just above actual alpha bounds, always inside the left column."""
    left, top, right, _ = head_box
    width = min(canvas_size[0], round(LEFT_WIDTH*u))
    x = max(round(2*u), min(round((left+right-art.width)/2), width-art.width-round(2*u)))
    y = max(round(2*u), round(top-art.height-2*u))
    return x, min(y, canvas_size[1]-art.height)
