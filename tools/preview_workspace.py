"""Render today's workspace with synthetic tasks and no account/session I/O."""
from pathlib import Path
import argparse
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))


def snapshot():
    now = 1800000000.0
    examples = [('native-codex', 'running', ['读 workflow_stages.py', '改 workflow_stages.py']),
                ('native-claude', 'waiting', ['委派子智能体 · 颜色与对比度', '委派子智能体 · 比例与尺寸']),
                ('zcode', 'running', ['读 fx.py', '改 fx.py', '跑测试 unittest'])]
    sessions = []
    for i, (agent, state, actions) in enumerate(examples):
        steps = [{'a': a, 'r': '', 't': now - len(actions) + j} for j, a in enumerate(actions)]
        sessions.append(dict(id=f'simulated-{i}', agent=agent, state=state, updated=now,
                             actions=list(reversed(steps))))
    return dict(now=now, mock=True, sessions=sessions, sel_session=sessions[0],
                sel_key='native-codex', quota=None, codex_quota=None, sources=[])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs' / 'current-workspace.png')
    parser.add_argument('--mode', choices=('live', 'tasks', 'steps'), default='live')
    parser.add_argument('--look', default='xiaoqiao',
                        help='xiaoqiao, or an AI character id (claude, codex, gemini, deepseek, glm)')
    parser.add_argument('--pose', default=None, help='force a static pose (idle, thinking, waiting, ...)')
    parser.add_argument('--screen-height', type=int, default=1800,
                        help='1080 renders the 1.0 density, 1800 the 1.5 density')
    args = parser.parse_args()
    from PIL import Image
    from tools.assets.export_house_stage import owner
    import pet
    p = owner(1.25)
    p.sw, p.sh = round(args.screen_height * 1.6), args.screen_height
    p._flat_panel_style = p._studio_style = True
    p._house_on = False
    p.settings = {}
    p.save_settings = lambda: None
    p.say = lambda *args, **kwargs: None
    p._flat_mode = args.mode
    p._flat_quota_raw = None
    geo = p._art_geo(1)
    p._swing = dict(geo=geo, theta=0, scene_l=0, scene_t=0, ui=snapshot(), art=True)
    if args.look != 'xiaoqiao':
        # AI pet mode with a pinned character; the pose follows the simulated
        # sessions unless --pose forces one.
        import time
        p.t0, p.thinking_now, p.chatbox, p.drag = time.time(), False, None, None
        p._ai_work_sessions = []
        p._appearance = None
        selector = pet.Pet._appearance_ready(p)
        selector.set_pin(args.look)
        p._apply_selection(selector.set_mode('ai'))
        p.ui_reduced_anim = True               # no breathing offset in a still
        if args.pose:
            p._ai_pet_ready().dev_show(args.pose, 15, time.time())
    # No Tk instance, model, live collector, screen capture or layered-window push.
    with patch('pet.push_layered'):
        p._push_swing_art(Image.new('RGBA', (p.W, p.H)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    p._swing['scene_canvas'].save(args.out)
    print(f'Saved simulated production render: {args.out}')


if __name__ == '__main__':
    main()
