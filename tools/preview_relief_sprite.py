"""Compare relief body PNGs with the old procedural body in the real compositor.

Public art and synthetic UI only. No Pet initialization, window or user data.
Paired timing is diagnostic, not a complete desktop frame-budget acceptance.
"""
from pathlib import Path
import argparse
import json
import statistics
import sys
import time
from unittest.mock import patch

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preview_seated_actions import BASE_TIME, Clock, advance, labelled, matte, synthetic_owner
import pet
import sprite_animation


def load_body(owner):
    sa = owner._scene_art
    return sprite_animation.BodySpriteBank.load(
        ROOT / 'assets', sa.src['swing_studio'],
        {'meta': sa.meta, 'rig': owner.cfg['rig']['regions'], 'contact_gate_version': 1},
        2.8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/relief-sprite')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {'data': 'synthetic', 'scales': [], 'timing_scope': 'paired first draw; not desktop p95'}
    clock = Clock()
    for scale in (1., .76):
        old, new = (synthetic_owner(scale, (2880, 1800), 1.25) for _ in range(2))
        for owner in (old, new):
            owner._sprite_bank = sprite_animation.SpriteBank.load(ROOT / 'assets', owner.main_src, owner.cfg['eyes'])
        new._body_sprite_bank = load_body(new)
        assert new._body_sprite_bank.fallback_reason is None, new._body_sprite_bank.fallback_reason
        blank = Image.new('RGBA', (new.W, new.H))
        images, rows, cost = [], [], []
        clock.value = BASE_TIME
        with patch('pet.time.time', clock.now), patch('pet.push_layered'):
            for owner in (old, new):
                assert owner.perform_action('relief', source='demo')
            for index in range(30):
                age = index*.1
                clock.value = BASE_TIME+age
                pair, times = [], []
                for owner in (old, new):
                    advance(owner, clock.value, .1 if index else 0, age)
                    started = time.perf_counter()
                    owner._push_swing_art(blank)
                    times.append((time.perf_counter()-started)*1000)
                    pair.append(owner._swing['scene_canvas'].copy())
                maximum = max(channel.getextrema()[1] for channel in ImageChops.difference(*pair).split())
                rows.append({'elapsed_ms': round(age*1000), 'body_frame': new._last_body_frame,
                             'max_rgba_delta': maximum, 'old_ms': times[0], 'sprite_ms': times[1]})
                cost.append(times[1]-times[0])
                if index in (0, 4, 10, 18, 26, 29):
                    for label, image in zip(('procedural', 'sprite'), pair):
                        image.save(args.out / f'scale-{scale:.2f}-{round(age*1000):04d}ms-{label}.png')
                tiles = [labelled(pair[0], 'SIMULATED | procedural body'),
                         labelled(pair[1], 'SIMULATED | PNG body + procedural details')]
                comparison = Image.new('RGB', (sum(tile.width for tile in tiles), max(tile.height for tile in tiles)), '#242532')
                comparison.paste(tiles[0], (0, 0))
                comparison.paste(tiles[1], (tiles[0].width, 0))
                images.append(comparison)
        images[0].save(args.out / f'scale-{scale:.2f}-comparison.gif', save_all=True,
                       append_images=images[1:], duration=100, loop=0)
        images[10].save(args.out / f'scale-{scale:.2f}-comparison.png')
        report['scales'].append({'scale': scale, 'samples': rows,
                                 'paired_delta_median_ms': statistics.median(cost),
                                 'paired_delta_max_ms': max(cost)})
    (args.out / 'production-preview.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'scales': [1., .76], 'samples_each': 30,
                      'data': 'synthetic', 'output': str(args.out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
