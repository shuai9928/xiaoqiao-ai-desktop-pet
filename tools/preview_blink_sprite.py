"""Render the configured blink through the current flat/scene compositor.

Public art and synthetic UI only; never constructs Pet, reads saved data,
creates a window, calls a model, or takes a desktop screenshot.
"""
from pathlib import Path
import argparse
import json
import sys
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preview_seated_actions import BASE_TIME, Clock, labelled, matte, synthetic_owner
import pet
import sprite_animation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/blink-sprite')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    clock, report = Clock(), []
    for scale in (1.0, .76):
        p = synthetic_owner(scale, (2880, 1800), 1.25)
        p._sprite_bank = sprite_animation.SpriteBank.load(ROOT / 'assets', p.main_src, p.cfg['eyes'])
        assert p._sprite_bank.duration('blink') is not None, p._sprite_bank.fallback_reason
        p._begin_blink(BASE_TIME)
        small, frames, tiles = Image.new('RGBA', (p.W, p.H)), [], []
        with patch('pet.push_layered'), patch('pet.time.time', clock.now):
            for elapsed in (0., .025, .080, .155, .230):
                clock.value = BASE_TIME + elapsed
                p._last_face_key = p._face_texture_key(clock.value, elapsed, False)
                p._push_swing_art(small)
                frame = p._swing['scene_canvas'].copy()
                filename = f'scale-{scale:.2f}-{round(elapsed*1000):03d}ms.png'
                frame.save(args.out / filename)
                frames.append(matte(frame))
                tiles.append(labelled(frame, f'simulated | {elapsed*1000:.0f}ms'))
                report.append({'scale': scale, 'elapsed_ms': round(elapsed*1000),
                               'face_key': p._last_face_key, 'file': filename})
        # The 25ms still is useful for checking repeated frame identity, but is
        # not an extra playback step. Keep the GIF at the manifest's 180ms.
        playback = [frames[index] for index in (0, 2, 3, 4)]
        playback[0].save(args.out / f'scale-{scale:.2f}-blink.gif', save_all=True,
                         append_images=playback[1:], duration=[40, 100, 40, 900], loop=0)
        sheet = Image.new('RGB', (sum(t.width for t in tiles), max(t.height for t in tiles)), '#22232f')
        left = 0
        for tile in tiles:
            sheet.paste(tile, (left, 0))
            left += tile.width
        sheet.save(args.out / f'scale-{scale:.2f}-contact.png')
    (args.out / 'production-preview.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'scales': [1., .76], 'frames': len(report),
                      'data': 'synthetic', 'output': str(args.out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
