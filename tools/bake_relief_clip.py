"""Pre-render relief's body channel from public art and its existing mesh.

No new drawing, Pet instance, personal data, network or model is involved.
The pack owns only body breath: face, ropes, hands and seat are protected.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scene_art
import seat_motion


def geometry(sa, cfg):
    return {'meta': sa.meta, 'rig': cfg['rig']['regions'], 'contact_gate_version': 1}


def difference(first, second):
    channels = ImageChops.difference(first, second).split()
    result = channels[0]
    for channel in channels[1:]:
        result = ImageChops.lighter(result, channel)
    return result


def bake(folder):
    cfg = json.loads((ROOT / 'assets/config.json').read_text(encoding='utf-8'))
    sa = scene_art.SceneArt.load(str(ROOT / 'assets/scene'))
    assert sa and sa.studio
    sa.set_rig(cfg['rig']['regions'])
    source = sa.src['swing_studio']
    off = sa.bbox['swing_studio'][:2]
    # Protect the existing face and all contact pixels in scene coordinates.
    # Only body pixels can change, including fractional silhouette alpha.
    allowed = Image.new('L', source.size)
    allowed.putdata([
        255 if sa._rig_w('body', x+off[0], y+off[1]) > 0
        and sa._rig_w('face', x+off[0], y+off[1]) == 0
        and sa.contact_gate(x+off[0], y+off[1]) > 0 else 0
        for y in range(source.height) for x in range(source.width)])
    protected = ImageChops.invert(allowed)
    motion = seat_motion.SeatMotion()
    motion.start('relief', 0)
    # Fourteen 200ms steps match the existing 2.8s action. Quantized body
    # amplitudes reuse PNGs; SeatMotion remains the host's only action clock.
    steps = [round(motion.breath(index*.2, 0)*4)/4 for index in range(14)]
    images = {}
    for level in sorted(set(steps)):
        if level == 0:
            images[level] = source.copy()
            continue
        pose = {'look': (0, 0), 'hat': (0, 0), 'hair': 0, 'breath': level}
        warped, at = sa.pose_keystone(source, off, 1, 0, 0, pose)
        left, top = round(off[0]-at[0]), round(off[1]-at[1])
        warped = warped.crop((left, top, left+source.width, top+source.height))
        images[level] = Image.composite(warped, source, allowed)
        assert ImageChops.multiply(difference(images[level], source), protected).getbbox() is None
    boxes = [difference(image, source).getbbox() for image in images.values()]
    boxes = [box for box in boxes if box]
    assert boxes, 'Existing relief has no measurable body channel.'
    rect = (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))
    x, y, right, bottom = rect
    assert (right-x)*(bottom-y)*len(images) <= 4_000_000
    folder.mkdir(parents=True, exist_ok=True)
    names = {}
    for level, image in images.items():
        names[level] = f'breath-{"m" if level < 0 else "p"}{abs(round(level*4)):02d}.png'
        image.crop(rect).save(folder / names[level])
        restored = source.copy()
        restored.paste(image.crop(rect), (x, y))  # No alpha mask: clear old holes.
        assert restored.tobytes() == image.tobytes()
    entries = []
    for level in steps:
        if entries and entries[-1]['file'] == names[level]:
            entries[-1]['duration_ms'] += 200
        else:
            entries.append({'file': names[level], 'duration_ms': 200, 'baked_breath': level})
    manifest = {'version': 1,
                'source': {'size': list(source.size),
                           'rgba_sha256': hashlib.sha256(source.tobytes()).hexdigest(),
                           'geometry_sha256': hashlib.sha256(json.dumps(
                               geometry(sa, cfg), sort_keys=True, ensure_ascii=True,
                               allow_nan=False).encode()).hexdigest()},
                'clip': {'action': 'relief', 'channel': 'breath',
                         'canvas': list(source.size), 'rect': [x, y, right-x, bottom-y],
                         'anchor': [x, y], 'loop': False, 'return_to': 'base',
                         'frames': entries}}
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    report = {'canvas': source.size, 'scene_offset': off,
              'rect': [x, y, right-x, bottom-y], 'steps': len(steps), 'entries': len(entries),
              'unique_images': len(images), 'duration_ms': 2800,
              'decoded_pixels': (right-x)*(bottom-y)*len(images),
              'png_bytes': sum((folder/name).stat().st_size for name in names.values()),
              'protected_native_pixels_unchanged': True, 'rgba_replacement_exact': True,
              'levels': steps, 'data': 'public art only'}
    return source, images, steps, report


def preview(output, source, images, steps, report):
    output.mkdir(parents=True, exist_ok=True)
    frames = []
    for level in steps:
        frame = Image.new('RGBA', source.size, '#242532')
        frame.alpha_composite(images[level])
        frames.append(frame.convert('RGB').resize((272, 376), Image.Resampling.LANCZOS))
    frames[0].save(output / 'body-channel.gif', save_all=True, append_images=frames[1:],
                   duration=200, loop=0)
    x, y, width, height = report['rect']
    sheet = Image.new('RGB', (width*3, height), '#242532')
    for index, level in enumerate((0., max(images), min(images))):
        frame = Image.new('RGBA', source.size, '#242532')
        frame.alpha_composite(images[level])
        sheet.paste(frame.convert('RGB').crop((x, y, x+width, y+height)), (width*index, 0))
    sheet.save(output / 'body-contact-sheet.png')
    (output / 'bake-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/relief-sprite')
    parser.add_argument('--write-assets', action='store_true')
    args = parser.parse_args()
    folder = ROOT / 'assets/animations/relief-body' if args.write_assets else args.out / 'pack'
    source, images, steps, report = bake(folder)
    preview(args.out, source, images, steps, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
