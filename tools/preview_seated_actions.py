"""Preview the production seated timelines using public assets and synthetic data.

No Pet.__init__, Tk window, account collector, model, sound or screen capture runs.
Only the final layered-window push is disabled; Windows imports remain real.
GIFs use a plain matte because GIF cannot retain the workspace's fractional alpha.
PNG keyframes retain the original production RGBA pixels.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GROUPS = {
    'A-companion': ('glance', 'nudge', 'startle', 'relief'),
    'B-touch': ('pat', 'flick', 'push', 'shy'),
}
LABELS = {
    'glance': '看一眼工作流', 'nudge': '等你时提醒', 'startle': '出错时一惊',
    'relief': '完成后松口气', 'pat': '摸头蹭手心', 'flick': '弹帽尖抬头',
    'push': '推一把秋千', 'shy': '长按害羞躲开',
}
BASE_TIME = 1_800_000_000.0


class Clock:
    value = BASE_TIME

    def now(self):
        return self.value


def synthetic_ui():
    """Explicit mock marker bypasses all live quota/session reads in live_ui."""
    rows = []
    for i, (agent, state, action) in enumerate((
            ('native-codex', 'running', '编写与修改 · 角色动作'),
            ('native-claude', 'running', '测试与验证 · 角色动作'),
            ('zcode', 'idle', '阅读资料与调研'))):
        rows.append(dict(id=f'simulated-seated-{i}', agent=agent, state=state,
                         updated=BASE_TIME,
                         actions=[dict(a=action, r='', t=BASE_TIME)]))
    return dict(now=BASE_TIME, mock=True, sessions=rows, sel_session=rows[0],
                sel_key='native-codex', quota=None, codex_quota=None, sources=[])


def synthetic_owner(scene_scale, screen, pet_scale):
    """Construct an artwork shell, reading only checked-in config/art assets."""
    from collections import OrderedDict
    from PIL import Image
    import life
    import pet
    import scene_art

    p = pet.Pet.__new__(pet.Pet)
    p.scale = pet_scale
    p.W, p.H = round(pet.BASE_W * pet_scale), round(pet.BASE_H * pet_scale)
    p.FOOT_Y = p.H - round(30 * pet_scale)
    p.cfg = json.loads((ROOT / 'assets' / 'config.json').read_text(encoding='utf-8'))
    p._sprite_h = int(p.cfg.get('sprite_h', pet.SPRITE_H))
    p._sprite_center_rel = float(p.cfg.get('sprite_center_rel', .5))
    p._mouth_rel = tuple(p.cfg.get('mouth', (.487, .55)))
    with Image.open(ROOT / 'assets' / 'main.png') as src:
        p.main_src = src.convert('RGBA')
    h = int(p._sprite_h * pet_scale * pet.SS)
    p.spr2 = p.main_src.resize((int(p.main_src.width * h / p.main_src.height), h),
                              Image.Resampling.LANCZOS)
    p._blink_patches = None
    p._scene_art = scene_art.SceneArt.load(str(ROOT / 'assets' / 'scene'))
    if p._scene_art is None:
        raise RuntimeError('Public scene artwork is missing; preview cannot run.')
    p._scene_art.set_rig(p.cfg['rig']['regions'])
    p._ks_cache = scene_art.KeystoneCache(cap=40)  # Pet.__init__ production limit.
    p._art_face_cache = OrderedDict()
    p.glow_cache = OrderedDict()
    p._last_depth_pose = (0.0,) * 6
    p._last_face_key = None
    p._chain_rect_local = p._art_small_back = None
    p._house_on = p._house_suspended = False
    p._flat_panel_style = p._studio_style = True
    p._flat_mode = 'live'
    p._flat_quota_raw = None
    p.settings = {}
    p.sw, p.sh = screen
    p.state, p._nap_on_swing = 'swing', False
    p.drag = p._scene_drag = None
    p.ui_reduced_anim = p.singing = False
    p.blink_until = 0.0
    p.last_interact = BASE_TIME
    p.life = life.LifeMotion()
    p.hwnd = 0
    geo = p._art_geo(scene_scale)
    p._swing = dict(geo=geo, theta=0.0, omega=0.0, scene_l=0, scene_t=0,
                    scene_w=geo['size'][0], scene_h=geo['size'][1], art=True,
                    scene_scale=scene_scale, ui=synthetic_ui(),
                    pend=life.Pendulum(period=pet.SWING_PERIOD, idle_amp=.085,
                                       max_amp=pet.SWING_MAX_AMP))
    p.x = p.fy = 0.0
    # Direct push's existing sparkle/sound outputs are intentionally unrendered.
    # The production _seat_push/_swing_impulse still deliver the real impulse.
    p.add_part = lambda *args, **kwargs: None

    class SilentSound:
        def play(self, *args, **kwargs):
            pass
    p.sfx = SilentSound()
    return p


class MeshProbe:
    """Time actual cache-miss mesh calls, without replacing their result."""
    def __init__(self, owner):
        self.calls = []
        original = owner._scene_art.pose_keystone

        def measured(*args, **kwargs):
            start = time.perf_counter()
            result = original(*args, **kwargs)
            self.calls.append((time.perf_counter() - start) * 1000)
            return result
        owner._scene_art.pose_keystone = measured


def advance(owner, now, dt, age):
    """Run production action/pendulum and life methods, in the frame loop's order.

    This reproduces only the swing inertia glue from Pet.tick; it deliberately
    omits cursor following, AI announcements, spontaneous kicks and user data.
    Those neutral inputs are identical in both benchmark arms.
    """
    import life
    import pet
    sw = owner._swing
    start = time.perf_counter()
    sw['theta'], sw['omega'] = owner._seat_swing_step(sw, dt, now)
    sw['persp'] = 1.0 + pet.SWING_PERSP * math.sin(sw['theta'])
    inertia = life.clamp((sw['persp'] - sw.get('prev_persp', 1.0)) * 40, -.10, .10)
    owner.life.hat_rot.impulse(inertia * .30)
    owner.life.impulse_hair(inertia * .55)
    owner.life.leg_l.impulse(inertia * .20)
    owner.life.leg_r.impulse(inertia * .16)
    owner.life.knee_l.impulse(inertia * .9)
    owner.life.knee_r.impulse(inertia * .8)
    owner.life.hem.impulse(inertia * .9)
    sw['prev_persp'] = sw['persp']
    ox, oy, scale = owner._art_small_map(sw)
    owner.x = int(ox + owner.W / 2 * scale - owner.W / 2)
    owner.fy = oy + owner.FOOT_Y * scale
    owner.life.update(now, 'swing', False, owner.x, owner.fy, t=age)
    owner._last_face_key = owner._face_texture_key(now, age, False)
    sw['ui']['now'] = now
    return (time.perf_counter() - start) * 1000


def draw(owner, small, probe):
    before = len(probe.calls)
    start = time.perf_counter()
    owner._push_swing_art(small)
    elapsed = (time.perf_counter() - start) * 1000
    return elapsed, probe.calls[before:]


def summary(values):
    values = sorted(values)
    if not values:
        return dict(n=0, mean=None, median=None, p95=None, max=None)
    return dict(n=len(values), mean=statistics.mean(values),
                median=statistics.median(values),
                p95=values[min(len(values) - 1, math.ceil(len(values) * .95) - 1)],
                max=values[-1])


def matte(image):
    from PIL import Image
    result = Image.new('RGBA', image.size, '#22232f')
    result.alpha_composite(image)
    return result.convert('RGB')


def labelled(image, title):
    from PIL import Image, ImageDraw
    from apple_ui import font
    tile = Image.new('RGB', (image.width, image.height + 24), '#22232f')
    tile.paste(matte(image), (0, 24))
    ImageDraw.Draw(tile).text((7, 4), title, fill='#d9d9eb', font=font(12))
    return tile


def render_action(name, scene_scale, args, clock, output):
    from PIL import Image
    import seat_motion
    owners = [synthetic_owner(scene_scale, args.screen, args.pet_scale) for _ in range(2)]
    probes = [MeshProbe(owner) for owner in owners]
    smalls = [Image.new('RGBA', (owner.W, owner.H)) for owner in owners]
    dt = 1.0 / args.fps
    # Prewarm ordinary artwork/UI startup equally. Cache misses caused by new
    # action poses remain in the first-pass measurements below.
    startup = []
    for i in range(10):
        age = (i - 10) * dt
        clock.value = BASE_TIME + age
        for arm in (0, 1):
            advance(owners[arm], clock.value, dt, age)
            elapsed, meshes = draw(owners[arm], smalls[arm], probes[arm])
            startup.append(dict(arm=arm, render_ms=elapsed, mesh_ms=meshes))
    clock.value = BASE_TIME
    if name == 'push':
        owners[1]._seat_push()
        if owners[1]._seat_motion.name != 'push':
            raise RuntimeError('Production push entrypoint did not start the action')
    elif not owners[1].start_seat_action(name):
        raise RuntimeError(f'Production start_seat_action rejected {name}')

    frames, rows, raw = [], [], []
    duration = seat_motion.ACTIONS[name]['dur'] + .6
    count = math.ceil(duration * args.fps) + 1
    for i in range(count):
        age = i * dt
        clock.value = BASE_TIME + age
        pair = [None, None]
        # Alternating order reduces bias from background load and CPU warming.
        for arm in ((0, 1) if i % 2 == 0 else (1, 0)):
            owner = owners[arm]
            logic_ms = advance(owner, clock.value, dt, age)
            first_ms, meshes = draw(owner, smalls[arm], probes[arm])
            warm_ms = []
            for _ in range(args.repeats):
                elapsed, extra_meshes = draw(owner, smalls[arm], probes[arm])
                if extra_meshes:
                    raise RuntimeError('Same-pose repeat unexpectedly missed the production cache')
                warm_ms.append(elapsed)
            pose = owner._art_pose(round(owner._swing['theta'] / .008) * .008)
            pair[arm] = dict(logic_ms=logic_ms, first_render_ms=first_ms,
                             first_frame_ms=logic_ms + first_ms,
                             cached_frame_ms=logic_ms + statistics.median(warm_ms),
                             cold_mesh_ms=meshes, q=list(pose['q']),
                             theta=owner._swing['theta'], omega=owner._swing['omega'],
                             face=list(owner._last_face_key))
        rows.append(dict(age=age, idle=pair[0], action=pair[1],
                         delta_first_frame_ms=pair[1]['first_frame_ms'] - pair[0]['first_frame_ms'],
                         delta_cached_frame_ms=pair[1]['cached_frame_ms'] - pair[0]['cached_frame_ms']))
        frame = owners[1]._swing['scene_canvas'].copy()
        raw.append(frame)
        frames.append(labelled(frame, f'模拟 · {LABELS[name]} · {scene_scale:.0%} · {age:.2f}s'))

    action_dir = output / name
    action_dir.mkdir(parents=True, exist_ok=True)
    frames[0].save(action_dir / 'simulated.gif', save_all=True, append_images=frames[1:],
                   duration=round(1000 / args.fps), loop=0, disposal=2, optimize=False)
    keys = [0, min(count - 1, round(seat_motion.ACTIONS[name]['dur'] * .4 * args.fps)), count - 1]
    tiles = []
    for index, label in zip(keys, ('开始', '动作中', '回落')):
        raw[index].save(action_dir / f'key-{index:03d}-simulated.png')
        tiles.append(labelled(raw[index], f'模拟 · {LABELS[name]} · {label} {index / args.fps:.2f}s'))
    idle_mesh = [v for row in rows for v in row['idle']['cold_mesh_ms']]
    action_mesh = [v for row in rows for v in row['action']['cold_mesh_ms']]
    record = dict(name=name, label=LABELS[name], scene_scale=scene_scale,
                  canvas_size=list(raw[0].size), duration=duration, fps=args.fps,
                  startup=startup, frames=rows,
                  first_frame_idle_ms=summary([r['idle']['first_frame_ms'] for r in rows]),
                  first_frame_action_ms=summary([r['action']['first_frame_ms'] for r in rows]),
                  delta_first_frame_ms=summary([r['delta_first_frame_ms'] for r in rows]),
                  delta_cached_frame_ms=summary([r['delta_cached_frame_ms'] for r in rows]),
                  cold_mesh_idle_ms=summary(idle_mesh), cold_mesh_action_ms=summary(action_mesh),
                  cold_mesh_idle_frames=sum(bool(r['idle']['cold_mesh_ms']) for r in rows),
                  cold_mesh_action_frames=sum(bool(r['action']['cold_mesh_ms']) for r in rows))
    return record, tiles


def contact_sheet(groups, output, scale):
    from PIL import Image
    for group, tiles in groups.items():
        width, height = tiles[0][0].size
        image = Image.new('RGB', (width * 3, height * 4), '#22232f')
        for row, triplet in enumerate(tiles):
            for col, tile in enumerate(triplet):
                image.paste(tile, (col * width, row * height))
        image.save(output / f'{group}-{scale:.0%}-contact-simulated.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs' / 'seated-actions')
    parser.add_argument('--scales', type=float, nargs='+', default=[1.0, .76])
    parser.add_argument('--screen', type=int, nargs=2, default=[2880, 1800])
    parser.add_argument('--pet-scale', type=float, default=1.25)
    parser.add_argument('--fps', type=int, default=20)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.fps != 20:
        parser.error('Production swing step is capped at 0.05s; use --fps 20 for this comparison')
    if not 1 <= args.repeats <= 10 or any(not .4 <= value <= 2 for value in args.scales):
        parser.error('Use 1..10 repeats and scene scales in .4..2')
    args.out.mkdir(parents=True, exist_ok=True)
    clock = Clock()
    result = dict(simulated=True, screenshot=False, production_entrypoints=[
        'Pet.start_seat_action', 'Pet._seat_push', 'Pet._seat_swing_step',
        'LifeMotion.update', 'Pet._face_texture_key', 'Pet._art_pose', 'Pet._push_swing_art'],
        screen=args.screen, pet_scale=args.pet_scale, scene_scales=args.scales,
        cache_limit=40, budget_ms=2.0, repeats=args.repeats, actions=[],
        source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                       for name in ('seat_motion.py', 'pet.py', 'life.py',
                                    'scene_art.py', 'flat_workspace.py')},
        notes=[
            'Only public artwork/config and synthetic workflow data are loaded; no user state or AI.',
            'Only final window push is disabled. No native Windows API shim or screenshot is used.',
            'Neutral cursor/depth inputs; no random kicks, companion marks or old click sparkles.',
            'First-pass cost includes real action-induced cache misses; cache repeats are reported separately.',
            'Cold mesh rows time real pose_keystone calls; initial artwork/UI startup is separately retained.',
            'GIF uses a plain matte; keyframe PNG retains production RGBA pixels.',
        ])
    with patch('pet.push_layered'), patch('pet.time.time', clock.now):
        for scale in args.scales:
            output = args.out / f'scale-{round(scale * 100):03d}'
            output.mkdir(parents=True, exist_ok=True)
            sheets = {group: [] for group in GROUPS}
            for group, names in GROUPS.items():
                for name in names:
                    record, tiles = render_action(name, scale, args, clock, output)
                    result['actions'].append(record)
                    sheets[group].append(tiles)
                    first = record['delta_first_frame_ms']
                    cached = record['delta_cached_frame_ms']
                    print(f'{scale:.0%} {name}: first delta mean={first["mean"]:.3f} '
                          f'median={first["median"]:.3f}ms; cached median={cached["median"]:.3f}ms; '
                          f'mesh frames={record["cold_mesh_action_frames"]}/{first["n"]}', flush=True)
            contact_sheet(sheets, output, scale)
    # Budget is reported for every action/scale, rather than hidden in a global average.
    result['first_pass_mean_budget_pass'] = all(
        item['delta_first_frame_ms']['mean'] <= 2 for item in result['actions'])
    result['cached_median_budget_pass'] = all(
        item['delta_cached_frame_ms']['median'] <= 2 for item in result['actions'])
    (args.out / 'performance-simulated.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Saved simulated production evidence: {args.out}', flush=True)
    print(f'First-pass mean <=2ms in every action/scale: {result["first_pass_mean_budget_pass"]}', flush=True)


if __name__ == '__main__':
    main()
