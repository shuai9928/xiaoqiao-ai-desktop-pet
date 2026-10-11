"""Bake the existing eye renderer into a small, source-bound PNG clip.

Reads checked-in config/art only. No Pet.__init__, window, user data or model.
Default output is a preview; --write-assets explicitly updates the public pack.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def half_closed(p, source):
    """Bake a tilted curved lid, avoiding the old half-lid's straight crop."""
    p._ensure_blink_patches()
    eyes = p.cfg['eyes']
    left, right = eyes['left'], eyes['right']
    eye_dx = (right[0]-left[0])*source.width
    slope = max(-.45, min(.45, (right[1]-left[1])*source.height/eye_dx))
    painted = source.copy()
    for cx, cy, patch in p._blink_patches:
        pw, ph = patch.size
        px, py = int(cx-pw/2), int(cy-ph*.42)
        def edge(dx):
            u = max(-1., min(1., dx/(pw*.30)))
            return cy+slope*dx-ph*.10+ph*.10*(1-u*u)
        boundary = [(n, edge(px+n-cx)-py) for n in range(pw)]
        mask = Image.new('L', (pw, ph))
        ImageDraw.Draw(mask).polygon([(0, 0), (pw-1, 0)]+list(reversed(boundary)), fill=255)
        mask = ImageChops.multiply(mask, patch.getchannel('A'))
        painted.paste(patch, (px, py), mask)
        points = [(cx+(u/32-.5)*pw*.60, edge((u/32-.5)*pw*.60)) for u in range(33)]
        ImageDraw.Draw(painted, 'RGBA').line(points, fill=(66, 46, 82, 235), width=3, joint='curve')
    painted.putalpha(source.getchannel('A'))
    return painted


def bake(output):
    import pet
    cfg = json.loads((ROOT / 'assets/config.json').read_text(encoding='utf-8'))
    with Image.open(ROOT / 'assets/main.png') as im:
        source = im.convert('RGBA')
    p = pet.Pet.__new__(pet.Pet)
    p.cfg, p.main_src, p.spr2, p.scale = cfg, source, source.copy(), 1.0
    p._blink_patches = None
    p._mouth_rel = tuple(cfg.get('mouth', (.487, .55)))
    frames, boxes = {}, []
    for label in ('half', 'closed'):
        painted = half_closed(p, source) if label == 'half' else p._face_texture(
            None, ('', 0, True, 1., ''), base=source)
        channels = ImageChops.difference(painted.convert('RGB'), source.convert('RGB')).split()
        mask = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
        mask = mask.point(lambda value: 255 if value else 0)
        # Host restores the original portrait alpha after compositing. Keep the
        # painted RGB exact, including edge pixels with fractional source alpha.
        overlay = painted.copy()
        overlay.putalpha(mask)
        frames[label] = (painted, overlay)
        boxes.append(mask.getbbox())
    assert all(boxes), 'Public eye geometry produced no frames.'
    rect = (min(bb[0] for bb in boxes), min(bb[1] for bb in boxes),
            max(bb[2] for bb in boxes), max(bb[3] for bb in boxes))
    x, y, right, bottom = rect
    output.mkdir(parents=True, exist_ok=True)
    for name, (painted, overlay) in frames.items():
        overlay.crop(rect).save(output / f'blink-{name}.png')
        restored = source.copy()
        restored.alpha_composite(overlay.crop(rect), (x, y))
        restored.putalpha(source.getchannel('A'))
        assert restored.tobytes() == painted.tobytes(), 'Native frame baking is not pixel-equivalent.'
    manifest = {
        'version': 1,
        'source': {
            'size': list(source.size),
            'rgba_sha256': hashlib.sha256(source.tobytes()).hexdigest(),
            'eyes_sha256': hashlib.sha256(json.dumps(cfg['eyes'], sort_keys=True,
                                                    ensure_ascii=True).encode()).hexdigest(),
        },
        'clips': {'blink': {
            'layer': 'expression', 'canvas': list(source.size),
            'rect': [x, y, right-x, bottom-y], 'anchor': [x, y],
            'loop': False, 'return_to': 'base',
            'frames': [{'file': 'blink-half.png', 'duration_ms': 40},
                       {'file': 'blink-closed.png', 'duration_ms': 100},
                       {'file': 'blink-half.png', 'duration_ms': 40}],
        }},
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return source, frames, rect


def preview(output, source, frames, rect):
    # Focus on eyes for diagnosis; the production overlay uses unmodified body art.
    x, y, right, bottom = rect
    box = (max(0, x-28), max(0, y-28), min(source.width, right+28), min(source.height, bottom+28))
    crops = [('原图', source), ('半闭', frames['half'][0]), ('闭眼', frames['closed'][0])]
    width, height = box[2]-box[0], box[3]-box[1]
    sheet = Image.new('RGB', (width*3, height+30), (27, 24, 43))
    for index, (_, im) in enumerate(crops):
        sheet.paste(im.crop(box), (index*width, 30))
    # ASCII labels avoid dependence on fonts in isolated checks.
    draw = ImageDraw.Draw(sheet)
    for index, label in enumerate(('BASE', 'HALF', 'CLOSED')):
        draw.text((index*width+6, 8), label, fill=(235, 225, 210))
    sheet.save(output / 'blink-contact-sheet.png')
    sequence = [source, frames['half'][0], frames['closed'][0], frames['half'][0], source]
    gif = []
    for image in sequence:
        matte = Image.new('RGBA', image.size, (35, 30, 50, 255))
        matte.alpha_composite(image)
        gif.append(matte.convert('RGB').crop(box))
    gif[0].save(output / 'blink-preview.gif', save_all=True, append_images=gif[1:],
                duration=[900, 40, 100, 40, 900], loop=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/blink-sprite')
    parser.add_argument('--write-assets', action='store_true')
    args = parser.parse_args()
    assets = ROOT / 'assets/animations' if args.write_assets else args.out
    source, frames, rect = bake(assets)
    args.out.mkdir(parents=True, exist_ok=True)
    preview(args.out, source, frames, rect)
    print(json.dumps({'canvas': source.size, 'rect': rect,
                      'frames': 3, 'images': 2, 'duration_ms': 180,
                      'native_pixel_equivalence': True, 'output': str(args.out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
