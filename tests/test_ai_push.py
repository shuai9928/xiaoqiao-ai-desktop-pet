"""I-50 workstream 2: AI-mode compose & push.

Persistent canvas + dirty rect, partial UpdateLayeredWindowIndirect pushes, glyph tile
cache, scan-tick panel deferral and drag follow. Synthetic data only: user32 and the
GDI surface are faked wherever a call would reach a real window.
"""
import ctypes
import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageChops, ImageColor, ImageDraw

import ai_bubble
import ai_fx
import apple_ui
import flat_workspace as f
import pet
import ui_themes
from test_moon_house import snapshot

U, PAD = 1.5, 30


def sprite(w, h, tint):
    im = Image.new('RGBA', (w, h))
    d = ImageDraw.Draw(im)
    d.ellipse((2, h * .3, w - 3, h - 2), fill=(tint, 120, 200, 255))
    d.ellipse((w * .2, 2, w * .8, h * .5), fill=(240, 200, tint, 230))
    d.line((0, h // 2, w, h // 2), fill=(255, 255, 255, 90), width=3)   # translucent pixels too
    return im


# (size, offset in the art box, effect, speaking, preview label)
SPECS = [((200, 230), (29, 19), 'idle', False, False),
         ((204, 226), (27, 23), 'idle', False, False),
         ((190, 240), (34, 9), 'thinking', False, False),
         ((250, 249), (4, 0), 'thinking', True, False),
         ((120, 160), (-20, 60), 'happy', True, True),       # off the canvas' left edge
         ((180, 200), (200, 40), None, False, True),          # overhangs the AI column to the right
         ((60, 300), (100, -90), 'pat', True, False),         # reaches above the canvas top
         ((200, 230), (29, 19), 'sleeping', False, False),
         ((1, 1), (0, 0), None, False, False),                # fully transparent sprite
         ((200, 230), (29, 19), 'idle', True, False)]


class AiOwner:
    """Just enough host for flat_workspace.push in AI mode, painting real ai_fx effects and ai_bubble speech."""

    def __init__(self, ui=None):
        self._swing = {'geo': {'u': U, 'k': .2, 'O': (0, 0), 'flat': True, 'hat_fx_pad': PAD,
                               'size': (round(f.W * U), round(f.H * U) + PAD)},
                       'ui': ui or snapshot(), 'scene_l': 10, 'scene_t': 20, 'theta': 0}
        self._scene_art = Mock()
        self._ac = pet.Pet._ac
        self.hwnd = 1
        self._ui_theme = ui_themes.theme('claude')
        self._flat_mode = 'live'
        self.state = dict(frame=None, fx=None, speak=False, age=0.0)

    def _static_look(self, size):
        return (self.state['frame'], 0) if self.state['frame'] is not None else None

    def _static_effects(self, canvas, box, u):
        if self.state['fx']:
            ai_fx.draw(canvas, self.state['fx'], self.state['age'], box, u, '#baa3ed', apple_ui.font(round(12 * u), 420))

    def _static_speech(self, canvas, head_box, u):
        if not self.state['speak']:
            return
        art = ai_bubble.sprite('我在想一个有点长的问题,看看两行能不能放下', apple_ui.font(round(13 * u), 480), u,
                               min(round(max(0, head_box[1] - 4 * u)), round(55 * u)), (186, 163, 237))
        if art is not None:
            self._ac(canvas, art, *ai_bubble.placement(art, head_box, canvas.size, u))


def frames():
    out = []
    for i, (size, off, fx, speak, demo) in enumerate(SPECS):
        img = Image.new('RGBA', size) if size == (1, 1) else sprite(*size, 40 + 20 * i)
        frame = SimpleNamespace(image=img, offset=off)
        if i % 2:
            frame.alpha_box = img.getchannel('A').getbbox()   # workstream 1 supplies it; older producers do not
        out.append((frame, fx, speak, demo, i * .37))
    return out


class PersistentCanvasTests(unittest.TestCase):
    def test_dirty_path_is_byte_identical_to_a_fresh_compose_and_the_window_matches(self):
        live, fresh = AiOwner(), AiOwner()
        pushes = []
        recorder = Mock(side_effect=lambda hwnd, img, x, y, alpha=255, *, dirty=None: pushes.append((img, dirty)) or 1)
        window = prev = None
        seen = set()
        with patch('pet.push_layered', recorder):
            for i, (frame, fx, speak, demo, age) in enumerate(frames() * 2):
                for owner in (live, fresh):
                    owner.state.update(frame=frame, fx=fx, speak=speak, age=age)
                    owner._ai_pose_demo_until = 1e12 if demo else 0
                fresh._flat_live = None                      # reference: base.copy() every frame
                f.push(live, None)
                canvas, dirty = pushes[-1]
                f.push(fresh, None)
                expected = pushes[-1][0]
                self.assertEqual(canvas.tobytes(), expected.tobytes(), i)
                self.assertIs(live._swing['scene_canvas'], canvas)
                seen.add(id(canvas))
                # A window that keeps pixels outside prcDirty shows exactly the composed frame.
                full = pet.premult_bgra(canvas)
                if dirty is None:
                    self.assertEqual(i, 0)                   # only the first frame rebuilds and pushes everything
                    window = bytearray(full)
                else:
                    st = pet._Layered(canvas.size, 255, None, None, 0.0)
                    rect = pet._ulw_dirty(st, canvas.size, 255, None, 0.0, dirty)
                    pet._dib_write(memoryview(window), canvas.width * 4, canvas, rect)
                    changed = ImageChops.difference(prev, canvas).getbbox(alpha_only=False)
                    if changed:
                        self.assertTrue(rect[0] <= changed[0] and rect[1] <= changed[1]
                                        and changed[2] <= rect[2] and changed[3] <= rect[3], (i, changed, rect))
                self.assertEqual(bytes(window), full, i)
                prev = canvas.copy()
        self.assertEqual(len(seen), 1)                       # one persistent canvas, no per-frame copy

    def test_column_dirty_rect_and_rebuild_on_a_new_panel(self):
        owner = AiOwner()
        frame = frames()[0][0]
        owner.state['frame'] = frame
        dirties = []
        with patch('pet.push_layered', Mock(side_effect=lambda *a, dirty=None, **k: dirties.append(dirty) or 1)):
            f.push(owner, None)
            f.push(owner, None)
            owner._flat_cache = None                          # panel rebuilt: a different base object
            f.push(owner, None)
            f.push(owner, None)
            owner._swing.pop('scene_canvas')                  # e.g. _art_regeo dropped the canvas
            f.push(owner, None)
        col = math.ceil(174 * U) + 2
        self.assertEqual(dirties, [None, (0, 0, col, 441), None, (0, 0, col, 441), None])

    def test_xiaoqiao_flat_path_still_builds_a_fresh_canvas_and_pushes_it_whole(self):
        owner = AiOwner()
        owner._static_look = lambda size: None
        calls = []
        with patch.object(f, 'paint_xiaoqiao'), patch('agent_companion.paint_effect'), \
                patch('pet.push_layered', Mock(side_effect=lambda *a, **k: calls.append((a, k)) or 1)):
            f.push(owner, None)
            f.push(owner, None)
        self.assertIsNot(calls[0][0][1], calls[1][0][1])
        self.assertEqual([k for _, k in calls], [{}, {}])
        self.assertIsNone(owner._flat_live)

    def test_invalid_handle_reacquires_and_pushes_the_whole_frame_once(self):
        owner = AiOwner()
        owner.state['frame'] = frames()[0][0]
        owner._acquire_hwnd = Mock(side_effect=lambda: setattr(owner, 'hwnd', 9) or 9)
        with patch('pet.push_layered', Mock(return_value=1)):
            f.push(owner, None)
        for gle, retried in ((1400, True), (5, False)):
            owner.hwnd = 1
            push = Mock(side_effect=[0, 1])
            with patch('pet.push_layered', push), patch('ctypes.get_last_error', return_value=gle):
                f.push(owner, None)
            self.assertEqual(push.call_count, 2 if retried else 1, gle)
            self.assertIsNotNone(push.call_args_list[0].kwargs['dirty'])
            if retried:
                self.assertEqual(push.call_args.args[0], 9)
                self.assertIsNone(push.call_args.kwargs.get('dirty'))
                self.assertIs(push.call_args.args[1], owner._swing['scene_canvas'])


class ScanTickDeferralTests(unittest.TestCase):
    def changed_ui(self, ui):
        s = dict(ui['sel_session'], state='error')
        return dict(ui, sessions=[s], sel_session=s)

    def test_scan_tick_keeps_the_old_panel_and_hits_for_one_frame(self):
        owner = AiOwner()
        owner.state['frame'] = frames()[0][0]
        pushed = []
        with patch('pet.push_layered', Mock(side_effect=lambda h, img, *a, **k: pushed.append(img.copy()) or 1)):
            f.push(owner, None)
            old_key, old_base, old_hits = owner._flat_cache
            owner._swing['ui'] = self.changed_ui(owner._swing['ui'])
            owner._ai_scan_gen = 1                            # _scan_ai_sessions ran in this tick
            f.push(owner, None)
            self.assertIs(owner._flat_cache[1], old_base)
            self.assertIs(owner._swing['ui_hits'], old_hits)
            right = (300, 0, pushed[-1].width, pushed[-1].height)
            self.assertEqual(pushed[-1].crop(right).tobytes(), old_base.crop(right).tobytes())
            f.push(owner, None)                               # next tick: rebuilt
            key, base, hits = owner._flat_cache
        self.assertNotEqual(key, old_key)
        self.assertIs(owner._swing['ui_hits'], hits)
        self.assertNotEqual(base.crop(right).tobytes(), old_base.crop(right).tobytes())
        self.assertEqual(pushed[-1].crop(right).tobytes(), base.crop(right).tobytes())

    def test_structural_changes_and_xiaoqiao_mode_rebuild_at_once(self):
        owner = AiOwner()
        owner.state['frame'] = frames()[0][0]
        with patch('pet.push_layered', Mock(return_value=1)):
            f.push(owner, None)
            owner._flat_mode = 'tasks'                        # not a data-only change
            owner._ai_scan_gen = 1
            f.push(owner, None)
            self.assertEqual(owner._flat_cache[0][3], 'tasks')
        owner = AiOwner()
        owner._static_look = lambda size: None
        with patch.object(f, 'paint_xiaoqiao'), patch('agent_companion.paint_effect'), \
                patch('pet.push_layered', Mock(return_value=1)):
            f.push(owner, None)
            old = owner._flat_cache
            owner._swing['ui'] = self.changed_ui(owner._swing['ui'])
            owner._ai_scan_gen = 1
            f.push(owner, None)
        self.assertNotEqual(owner._flat_cache[0], old[0])

    def test_scan_bumps_the_generation_first_thing(self):
        p = pet.Pet.__new__(pet.Pet)
        p._demo_until = 1e12
        p._ai_sync_work = Mock()
        pet.Pet._scan_ai_sessions(p)
        pet.Pet._scan_ai_sessions(p)
        self.assertEqual(p._ai_scan_gen, 2)


class FakeUser32:
    def __init__(self):
        self.calls = []
        self.ok_indirect = self.ok_full = 1

    def UpdateLayeredWindow(self, hwnd, hdc, ppt, psize, hdc_src, ppt_src, key, blend, flags):
        pt = ppt._obj
        self.calls.append(('full' if hdc_src else 'move', hwnd, (pt.x, pt.y),
                           (psize._obj.cx, psize._obj.cy) if psize else None, hdc, ppt_src, blend, flags))
        return self.ok_full if hdc_src else 1

    def UpdateLayeredWindowIndirect(self, hwnd, info):
        i = info._obj
        rc = i.prcDirty.contents
        alpha = ctypes.cast(i.pblend, ctypes.POINTER(pet._Blend)).contents.SourceConstantAlpha
        self.calls.append(('indirect', hwnd, (i.pptDst.contents.x, i.pptDst.contents.y),
                           (i.psize.contents.cx, i.psize.contents.cy), (rc.left, rc.top, rc.right, rc.bottom),
                           i.dwFlags, i.cbSize, alpha))
        return self.ok_indirect


class PartialPushTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeUser32()
        self.clock = [100.0]
        self.dibs = {}

        def surface(w, h):
            buf = self.dibs.setdefault((w, h), (ctypes.c_ubyte * (w * h * 4))())
            return 11, 22, ctypes.c_void_p(ctypes.addressof(buf))
        self.patches = [patch.object(pet, 'user32', self.fake), patch.object(pet, '_gdi_surface', surface),
                        patch.object(pet, '_gdi_pool', {}), patch.object(pet, '_ulw_state', {}),
                        patch('pet.time.monotonic', lambda: self.clock[0])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def push(self, img, dirty=None, alpha=255, dt=.016, x=5, y=6):
        self.clock[0] += dt
        return pet.push_layered(7, img, x, y, alpha, dirty=dirty)

    def kinds(self):
        return [c[0] for c in self.fake.calls]

    def test_struct_is_the_64_bit_updatelayeredwindowinfo(self):
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(pet._ULWInfo), 80)
            self.assertEqual(pet._ULWInfo.prcDirty.offset, 72)

    def test_rows_land_inside_the_rect_and_leave_the_rest_untouched(self):
        a = Image.new('RGBA', (40, 30), (10, 200, 30, 255))
        ImageDraw.Draw(a).ellipse((3, 3, 35, 25), fill=(250, 30, 90, 120))
        b = Image.new('RGBA', (40, 30), (90, 10, 220, 77))      # differs everywhere, also outside the rect
        ImageDraw.Draw(b).rectangle((0, 0, 39, 29), outline=(255, 255, 255, 255))
        self.assertEqual(self.push(a, dirty=(0, 0, 1, 1)), 1)  # first push per window: whole frame
        rect = (7, 4, 23, 19)
        self.assertEqual(self.push(b, dirty=rect, x=50, y=60), 1)
        self.assertEqual(self.kinds(), ['full', 'indirect'])
        _, hwnd, pt, size, rc, flags, cb, alpha = self.fake.calls[-1]
        self.assertEqual((hwnd, pt, size, rc, flags, cb, alpha),
                         (7, (50, 60), (40, 30), rect, pet.ULW_ALPHA | pet.ULW_EX_NORESIZE, ctypes.sizeof(pet._ULWInfo), 255))
        dib = bytes(self.dibs[(40, 30)])
        mixed = a.copy()
        mixed.paste(b.crop(rect), rect[:2])
        self.assertEqual(dib, pet.premult_bgra(mixed))
        # full-width rects take the single-copy branch
        self.assertEqual(self.push(b, dirty=(-5, 10, 99, 12)), 1)
        self.assertEqual(self.fake.calls[-1][4], (0, 10, 40, 12))
        mixed.paste(b.crop((0, 10, 40, 12)), (0, 10))
        self.assertEqual(bytes(self.dibs[(40, 30)]), pet.premult_bgra(mixed))

    def test_full_versus_partial_rules(self):
        img, other = Image.new('RGBA', (20, 10), (1, 2, 3, 255)), Image.new('RGBA', (22, 10))
        d = (0, 0, 5, 5)
        self.push(img, dirty=d)                                 # first push
        self.push(img, dirty=None)                              # no dirty rect given
        self.push(img, dirty=d)                                 # partial
        self.push(img, dirty=d, alpha=200)                      # whole-window alpha changed
        self.push(img, dirty=d, alpha=200)                      # partial again
        self.push(other, dirty=d, alpha=200)                    # size changed
        self.push(other, dirty=d, alpha=200, dt=pet.ULW_GAP_S + .01)   # a pause (hidden, stopped ticking)
        self.assertEqual(self.push(other, dirty=(30, 30, 40, 40), alpha=200), 1)   # empty after clamping: 1 px
        self.assertEqual(self.kinds(), ['full', 'full', 'indirect', 'full', 'indirect', 'full', 'full', 'indirect'])
        self.assertEqual(self.fake.calls[-1][4], (0, 0, 1, 1))
        self.fake.calls.clear()
        self.clock[0] = 200.0                                   # exact binary steps below
        while self.clock[0] < 230:                              # periodic self-heal every ULW_HEAL_S
            self.push(other, dirty=d, alpha=200, dt=.125)
        fulls = [i for i, k in enumerate(self.kinds()) if k == 'full']
        self.assertGreaterEqual(len(fulls), 10)
        self.assertTrue(all(b - a == round(pet.ULW_HEAL_S / .125) for a, b in zip(fulls, fulls[1:])), fulls)

    def test_failures_fall_back_to_a_full_push_and_reset_state(self):
        img = Image.new('RGBA', (20, 10), (1, 2, 3, 255))
        self.push(img)
        self.fake.ok_indirect = 0
        self.assertEqual(self.push(img, dirty=(0, 0, 4, 4)), 1)  # partial failed, same call pushed everything
        self.assertEqual(self.kinds(), ['full', 'indirect', 'full'])
        self.fake.ok_indirect, self.fake.ok_full = 1, 0
        self.assertEqual(self.push(img), 0)
        self.assertNotIn(7, pet._ulw_state)
        self.fake.ok_full = 1
        self.push(img, dirty=(0, 0, 4, 4))
        self.assertEqual(self.kinds()[-1], 'full')               # nothing to build a partial on

    def test_premult_rgba_shortcut_is_byte_identical_for_every_value_and_alpha(self):
        data = bytes(v for a in range(256) for c in range(256) for v in (c, 255 - c, (c * 37) % 256, a))
        img = Image.frombytes('RGBA', (256, 256), data)
        expected = img.convert('RGBa').tobytes('raw', 'BGRa')
        self.assertEqual(pet.premult_bgra(img), expected)
        self.assertEqual(pet.premult_bgra(img.convert('RGBa')), expected)
        self.assertEqual(pet.premult_bgra(img.crop((3, 5, 77, 200))), img.crop((3, 5, 77, 200)).convert('RGBa').tobytes('raw', 'BGRa'))


class DragFollowTests(unittest.TestCase):
    def host(self, ai):
        return SimpleNamespace(_flat_panel_style=False, drag=None, last_interact=0, hwnd=77,
                               _scene_drag={'mx': 100, 'my': 100, 'press_x': 100, 'press_y': 100, 'moved': False},
                               _swing={'scene_l': 10, 'scene_t': 20, 'scene_w': 660, 'scene_h': 441},
                               _static_active=lambda: ai)

    def test_ai_mode_moves_the_window_at_once_position_only(self):
        fake = FakeUser32()
        for ai in (True, False):
            fake.calls.clear()
            p = self.host(ai)
            with patch.object(pet, 'user32', fake):
                pet.Pet.on_drag(p, SimpleNamespace(x_root=130, y_root=90, x=0, y=0))
            self.assertEqual((p._swing['scene_l'], p._swing['scene_t']), (40, 10))
            if ai:
                self.assertEqual(fake.calls, [('move', 77, (40, 10), None, None, None, None, 0)])
            else:
                self.assertEqual(fake.calls, [])                 # Xiaoqiao drag is unchanged: next frame moves it


def reference_glyph(im, cx, cy, r, color, shape, u, glow=False):
    """flat_workspace.glyph before I-50, verbatim (uncached)."""
    k=8;g=int((r+5)*2*u*k)+2;t=Image.new('RGBA',(g,g));td=ImageDraw.Draw(t);c=g/2;s=r*u*k;col=ImageColor.getrgb(color)
    if glow:e=(r+2.6)*u*k;td.ellipse((c-e,c-e,c+e,c+e),fill=col+(90,))
    if shape=='star':
        R=1.34*s;td.polygon([(c+(R if i%2==0 else R*.46)*math.cos(math.radians(-90+45*i)),c+(R if i%2==0 else R*.46)*math.sin(math.radians(-90+45*i))) for i in range(8)],fill=col)
    elif shape=='ring':
        td.ellipse((c-1.12*s,c-1.12*s,c+1.12*s,c+1.12*s),fill=col);td.ellipse((c-.52*s,c-.52*s,c+.52*s,c+.52*s),fill=(0,0,0,0))
    elif shape=='tri':
        td.polygon([(c,c-1.22*s),(c+1.12*s,c+.82*s),(c-1.12*s,c+.82*s)],fill=col)
    else:td.ellipse((c-s,c-s,c+s,c+s),fill=col)
    t=t.resize((max(1,round(g/k)),max(1,round(g/k))),Image.LANCZOS);im.alpha_composite(t,(round(cx*u-t.width/2),round(cy*u-t.height/2)))


class GlyphCacheTests(unittest.TestCase):
    def test_cached_tiles_are_pixel_identical_cold_and_warm(self):
        f._GLYPHS.clear()
        for u in (1, 1.5, 2):
            for shape in ('star', 'ring', 'tri', 'dot'):
                for r, color, glow in ((3.5, '#baa3ed', False), (4.2, '#efba70', True), (1.3, '#656772', False)):
                    for cx, cy in ((20, 20), (31.3, 17.8)):
                        want, cold, warm = (Image.new('RGBA', (90, 70), (20, 30, 40, 200)) for _ in range(3))
                        reference_glyph(want, cx, cy, r, color, shape, u, glow)
                        f._GLYPHS.pop((r, color, shape, u, glow), None)
                        f.glyph(cold, cx, cy, r, color, shape, u, glow)
                        f.glyph(warm, cx, cy, r, color, shape, u, glow)
                        self.assertEqual(cold.tobytes(), want.tobytes(), (u, shape, r))
                        self.assertEqual(warm.tobytes(), want.tobytes(), (u, shape, r))

    def test_panel_render_matches_the_uncached_glyphs(self):
        ui = snapshot()
        f._GLYPHS.clear()
        cold = f.render_live(ui, U)[0]
        warm = f.render_live(ui, U)[0]
        with patch.object(f, 'glyph', reference_glyph):
            want = f.render_live(ui, U)[0]
        self.assertEqual(cold.tobytes(), want.tobytes())
        self.assertEqual(warm.tobytes(), want.tobytes())

    def test_cache_is_a_bounded_lru(self):
        f._GLYPHS.clear()
        im = Image.new('RGBA', (60, 60))
        for i in range(150):
            f.glyph(im, 10, 10, 1 + i * .01, '#ffffff', 'dot', 1.5)
            self.assertLessEqual(len(f._GLYPHS), f.GLYPH_CACHE[0])
        self.assertIn((1 + 149 * .01, '#ffffff', 'dot', 1.5, False), f._GLYPHS)
        f.glyph(im, 10, 10, 1 + 100 * .01, '#ffffff', 'dot', 1.5)          # a hit moves to the young end
        self.assertEqual(next(reversed(f._GLYPHS)), (1 + 100 * .01, '#ffffff', 'dot', 1.5, False))
        f._GLYPHS.clear()
        for i in range(6):                                      # ~75k-pixel tiles: the pixel cap binds first
            f.glyph(im, 10, 10, 30, '#ffffff', 'dot', 3.9 - i * .01)
            self.assertLessEqual(sum(t.width * t.height for t in f._GLYPHS.values()), f.GLYPH_CACHE[1])
        self.assertLess(len(f._GLYPHS), 6)
        f._GLYPHS.clear()


if __name__ == '__main__':
    unittest.main()
