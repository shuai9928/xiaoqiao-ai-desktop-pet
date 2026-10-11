"""Verify manual art replacement on a synthetic, isolated Windows app copy.

Draws our own geometric robot, never edits the repository's supplied artwork.
Runs the actual Pet/SceneArt compositor, with accounts/network disabled.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def replace_art(root):
    from PIL import Image, ImageDraw
    assets = root / 'assets'
    meta = json.loads((assets/'scene/meta.json').read_text(encoding='utf-8'))
    x0, y0, x1, y1 = meta['girl_bbox']
    robot = Image.new('RGBA', (x1-x0, y1-y0))
    d = ImageDraw.Draw(robot)
    # Original drawing with no borrowed character pixels.
    d.rounded_rectangle((170, 195, 710, 610), radius=85, fill='#67c6c4', outline='#203e4c', width=14)
    d.rounded_rectangle((225, 650, 670, 950), radius=60, fill='#52667f', outline='#203e4c', width=14)
    for ex in (320, 590):
        d.ellipse((ex-40, 335, ex+40, 415), fill='#203e4c')
    d.arc((365, 420, 545, 510), 0, 180, fill='#203e4c', width=12)
    d.rectangle((275, 950, 340, 1165), fill='#67c6c4')
    d.rectangle((555, 950, 620, 1165), fill='#67c6c4')
    robot.save(assets/'main.png')
    full = Image.new('RGBA', tuple(meta['size']))
    full.alpha_composite(robot, (x0, y0))
    full.save(assets/'scene/girl.png')
    # Both runtime bodies must change. Never overlay on the original person.
    swing = full.copy()
    sd = ImageDraw.Draw(swing)
    for px, py in (meta['pivot_l'], meta['pivot_r']):
        sd.line((px, py, px, meta['seat_line_y']), fill='#a7bcc5', width=10)
    sd.rounded_rectangle((450, 930, 1000, 970), radius=20, fill='#203e4c')
    for name in ('swing.png', 'swing_studio.png'):
        swing.save(assets/'scene'/name)
    # Keep the original coordinate system, calibrate our new robot's eyes/mouth.
    cfg = json.loads((assets/'config.json').read_text(encoding='utf-8'))
    cfg['eyes'].update(left=[320/robot.width, 375/robot.height], right=[590/robot.width, 375/robot.height],
                       skin_at=[[280/robot.width, 430/robot.height], [620/robot.width, 430/robot.height]])
    cfg['mouth'] = [455/robot.width, 470/robot.height]
    meta['face'] = dict(eye_l=[x0+320, y0+375], eye_r=[x0+590, y0+375], mouth=[x0+455, y0+470])
    meta['bbox']['swing'] = list(swing.getbbox())
    (assets/'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
    (assets/'scene/meta.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')


def worker(output, custom):
    from tools.run_checks import _disable_network
    _disable_network()
    if custom:
        replace_art(ROOT)
    from PIL import Image
    from unittest.mock import patch
    import tkinter as tk
    import pet
    import ai_chat
    import scene_art
    import sprite_animation
    output.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT/'assets/config.json').read_text(encoding='utf-8'))
    sa = scene_art.SceneArt.load(str(ROOT/'assets/scene'))
    assert sa is not None
    portrait = Image.open(ROOT/'assets/main.png').convert('RGBA')
    blink = sprite_animation.SpriteBank.load(ROOT/'assets', portrait, cfg['eyes'])
    body = sprite_animation.BodySpriteBank.load(ROOT/'assets', sa.src['swing_studio'],
        {'meta': sa.meta, 'rig': cfg['rig']['regions'], 'contact_gate_version': 1}, 2.8)
    if custom:
        assert blink.fallback_reason == body.fallback_reason == 'source_mismatch'
    errors = []
    with patch.object(ai_chat, 'AIBrain', return_value=None), \
         patch.object(pet.Pet, 'start_tray', autospec=True, side_effect=lambda obj: setattr(obj, '_tray', None)):
        root = tk.Tk()
        root.report_callback_exception = lambda *args: errors.append(str(args[1]))
        p = pet.Pet(root, selftest=True)
        try:
            # Use the shipped flat layout while retaining selftest's account isolation.
            p._flat_panel_style = p._studio_style = True
            p._house_on = False
            p.topmost = False
            p.open_swing_scene()
            p.bubble = None
            p.play_emotion('happy', 2.0)
            now = pet.time.time()+.6
            p.render(now, now-p.t0)
            root.update_idletasks()
            image = p._swing['scene_canvas'].copy()
            image.save(output/('custom-robot-workspace.png' if custom else 'stickers-workspace.png'))
            if custom:
                portrait.save(output/'custom-main.png')
            else:
                # Rapid pat/emotion renewal retains its image and current scale/opacity.
                original = p.sticker
                pose = p._sticker_pose(original, now)
                with patch.object(pet.time, 'time', return_value=now):
                    p.play_emotion('happy', 2.0)
                assert p.sticker is original and p._sticker_pose(original, now) == pose
                for i in range(20):
                    with patch.object(pet.time, 'time', return_value=now+i*.03):
                        p.play_emotion('happy', 2.0)
                    assert p.sticker is original
                p.set_appearance_mode('ai', pin='codex')
                assert p.sticker is None and p._sticker_previous is None
                assert not p.play_emotion('happy', 2)
                now = pet.time.time()+.3
                p.render(now, now-p.t0)
                p._swing['scene_canvas'].save(output/'ai-without-xiaoqiao-sticker.png')
                p.set_appearance_mode('xiaoqiao')
                assert p.sticker is None
            assert not errors, errors
            report = dict(custom_art=custom, real_windows_compositor=True,
                          window_size=list(image.size), blink_fallback=blink.fallback_reason,
                          body_fallback=body.fallback_reason, callback_errors=errors,
                          network_disabled=True, personal_data='synthetic temporary directory only')
            (output/('customization.json' if custom else 'stickers.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            p.quit()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'outputs/customization')
    parser.add_argument('--stickers-only', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Run with Windows Python; test windows close automatically.')
    if args.worker:
        if os.environ.get('XIAOQIAO_CHECKS_ISOLATED') != '1':
            raise SystemExit('Worker requires the isolated runner.')
        return worker(args.out.resolve(), not args.stickers_only)
    from tools.run_checks import prepare_stage, isolated_environment
    with tempfile.TemporaryDirectory(prefix='xiaoqiao-customize-') as directory:
        stage = Path(directory)
        home = prepare_stage(ROOT, stage)
        command = [sys.executable, '-X', 'utf8', str(stage/'tools/release/test_customization.py'),
                   '--worker', '--out', str(args.out.resolve())]
        if args.stickers_only:
            command.append('--stickers-only')
        return subprocess.run(command, cwd=stage, env=isolated_environment(stage, home)).returncode


if __name__ == '__main__':
    raise SystemExit(main())
