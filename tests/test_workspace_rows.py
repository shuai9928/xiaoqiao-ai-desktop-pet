"""I-51 right-hand workspace (方案 A 精修行列): status words, colour meanings, the quota table, hit boxes, type sizes
and the host wiring (press / hover / wheel / scrollbar / back) through the real Pet handlers.

Synthetic sessions and quota only; no Tk window, account file or network."""
import calendar
import itertools
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import flat_workspace as f
import ui_themes

NOW = 1800000000.0
H, D = 3600, 86400
OK = '完成'


def sess(i, agent, state, acts, age=20.0):
    """acts: oldest -> newest; a label, or (label, result, error)."""
    updated = NOW - age
    steps = []
    for j, a in enumerate(acts):
        label, result, err = (a, '', False) if isinstance(a, str) else a
        step = {'a': label, 'r': result, 't': updated - (len(acts) - j) * 40}
        if err:
            step['err'] = 1
        steps.append(step)
    return dict(id=f'{agent}-{i}', agent=agent, state=state, updated=updated, actions=list(reversed(steps)))


def q(name, *cycles, stale=False, t=NOW):
    """cycles: (label, used) or (label, used, reset seconds from NOW)."""
    return {'name': name, 'stale': stale, 't': t,
            'cycles': [{'label': c[0], 'used': c[1], 'reset': (NOW + c[2]) if len(c) > 2 else None, 'stale': stale}
                       for c in cycles]}


def busy():
    return [sess(0, 'native-codex', 'running', [('读 flat_workspace.py', OK, False), ('改 flat_workspace.py', OK, False),
                                                '跑测试 unittest'], age=5),
            sess(1, 'native-claude', 'waiting', [('读 ui_themes.py', OK, False), '改 ui_themes.py 颜色'], age=130),
            sess(2, 'zcode', 'error', [('改 fx.py', OK, False), ('跑测试 unittest', 'FAILED (errors=2)', True)], age=75)]


def calm():
    return [sess(0, 'native-codex', 'done', [('改 workflow_stages.py', OK, False), ('跑测试 unittest', 'OK', False)], age=12 * 60),
            sess(1, 'native-claude', 'done', [('改 apple_ui.py 布局', OK, False)], age=47 * 60),
            sess(2, 'zcode', 'waiting', [('读 hat_fx.py', OK, False), '改 hat_fx.py'], age=3 * H + 300)]   # stale by now


def many():
    states = ('running', 'waiting', 'error', 'done', 'done', 'done', 'done', 'done', 'done')
    rows = [sess(i, 'native-codex', st, [('读 fx.py', OK, False), ('改 fx.py', OK if st == 'done' else '', st == 'error')],
                 age=10 + i * 400) for i, st in enumerate(states)]
    return rows + [sess(20, 'native-claude', 'running', [('读 ai_quota.py', OK, False), '改 ai_quota.py'], age=40),
                   sess(21, 'zcode', 'done', [('读 fx.py', OK, False), ('改 fx.py', OK, False)], age=900)]


def steps_many():
    acts = [('调研 资料', OK, False), ('读 workflow_stages.py', OK, False), ('改 workflow_stages.py', OK, False),
            ('跑测试 unittest', OK, False), ('审核 diff', OK, False), ('改 fx.py', OK, False),
            ('委派子智能体 · 颜色与对比度', OK, False), ('委派子智能体 · 比例与尺寸', OK, False),
            ('跑测试 pytest', OK, False), ('构建 安装包', OK, False), ('提交', OK, False), '改 popup_material.py']
    return [sess(0, 'native-codex', 'running', acts, age=5)]


QUOTA = [q('Claude', ('5h', 85, 2 * H + 40 * 60), ('周', 91, 3 * D)), q('Codex', ('月', 99, 12 * D)),
         q('Codex WSL', ('月', 96, 12 * D))]


def ui_for(sessions, quota=QUOTA, agent='Codex', palette=None, **extra):
    ui = dict(now=NOW, mock=False, sessions=sessions, sel_session=sessions[0] if sessions else None,
              sel_key=sessions[0]['agent'] if sessions else None, quota=None, codex_quota=None, sources=[],
              quota_widget=quota, flat_agent=agent, panel_alpha=248)
    ui.update(extra)
    if palette is not None:
        ui['palette'] = palette
    return ui


def drawn(ui, u=1.0, mode='live', offset=0):
    """Render through f.render and return (image, hits, texts, glyphs); texts = (string, fill, font px, ink box, image),
    glyphs = (colour, shape, image). Image objects are kept, so tile identities stay unique."""
    texts, glyphs = [], []
    real_text, real_glyph = ImageDraw.ImageDraw.text, f.glyph

    def text(self, xy, s, *a, **k):
        font, anchor = k.get('font'), k.get('anchor') or 'la'
        texts.append((str(s), k.get('fill'), font.size, self.textbbox(xy, s, font=font, anchor=anchor), self._image))
        return real_text(self, xy, s, *a, **k)

    def glyph(im, cx, cy, r, color, shape, uu, glow=False):
        glyphs.append((color, shape, im))
        return real_glyph(im, cx, cy, r, color, shape, uu, glow)

    with patch.object(ImageDraw.ImageDraw, 'text', text), patch.object(f, 'glyph', glyph):
        im, hits, _ = f.render(ui, u, mode, offset)
    return im, hits, texts, glyphs


def strings(texts):
    return [t[0] for t in texts]


class StatusWordTests(unittest.TestCase):
    def test_durations_and_ages(self):
        self.assertEqual([f.dur(s) for s in (-5, 0, 59, 60, 3599, 3600, 86399, 86400, 3 * D + 5)],
                         ['0秒', '0秒', '59秒', '1分钟', '59分钟', '1小时', '23小时', '1天', '3天'])
        self.assertEqual([f.ago(s) for s in (0, 59, 125, 3 * H + 5, 2 * D)], ['刚刚', '刚刚', '2分钟前', '3小时前', '2天前'])

    def test_status_says_how_long_and_never_ended(self):
        dim = '#123456'
        row = lambda st, age, **k: dict(state=st, updated=NOW - age, **k)
        self.assertEqual(f.status_of(row('waiting', 130), NOW, dim), ('等你确认 2分钟', f.COLORS['waiting']))
        self.assertEqual(f.status_of(row('error', 75), NOW, dim), ('出错 1分钟', f.COLORS['error']))
        self.assertEqual(f.status_of(row('running', 5, since=NOW - 185), NOW, dim), ('运行中 3分钟', dim))   # since the turn began
        self.assertEqual(f.status_of(row('running', 40), NOW, dim), ('运行中 40秒', dim))
        self.assertEqual(f.status_of(row('done', 12 * 60), NOW, dim), ('12分钟前', dim))
        self.assertEqual(f.status_of(row('done', 30), NOW, dim), ('刚刚', dim))
        self.assertEqual(f.status_of(row('idle', 3 * H + 1, stale=True), NOW, dim), ('更新于3小时前', dim))
        self.assertEqual(f.status_of(dict(state='running', updated=0, stale=True), NOW, dim), ('久未更新', dim))
        self.assertEqual(f.status_of(dict(state='waiting', updated=0), NOW, dim), ('等你确认', f.COLORS['waiting']))
        self.assertEqual(f.status_of(dict(state='idle', updated=0), NOW, dim), ('–', dim))

    def test_green_only_for_a_recent_finish(self):
        dim = '#123456'
        self.assertEqual(f.glyph_of(dict(state='done', updated=NOW - 29 * 60), NOW, dim)[0], f.COLORS['done'])
        self.assertEqual(f.glyph_of(dict(state='done', updated=NOW - 31 * 60), NOW, dim)[0], dim)
        self.assertEqual(f.glyph_of(dict(state='running', updated=NOW, stale=True), NOW, dim)[:2], (dim, 'dot'))
        self.assertEqual(f.glyph_of(dict(state='running', updated=NOW), NOW, dim)[:2], (f.COLORS['running'], 'star'))

    def test_no_ended_word_and_no_next_step_anywhere(self):
        for sessions, mode, agent in itertools.product((busy(), calm(), many(), steps_many(), []), ('live', 'tasks', 'steps'),
                                                       ('Codex', 'Claude', 'ZCode')):
            for s in sessions:
                s['next'] = '编写与修改'
            words = strings(drawn(ui_for(sessions, agent=agent), 1.5, mode)[2])
            self.assertFalse([w for w in words if '已结束' in w or '→' in w], (mode, agent, words))

    def test_live_groups_read_name_status_then_stage(self):
        _, hits, texts, _ = drawn(ui_for(busy()), 1.5)
        words = strings(texts)
        for name, status, stage in (('Codex', '运行中 2分钟', '测试与验证'), ('Claude', '等你确认 2分钟', '编写与修改'),
                                    ('ZCode', '出错 1分钟', '测试与验证')):
            i = words.index(name)
            self.assertEqual(words[i + 1], status)
            self.assertTrue(words[i + 2].startswith(stage), words[i + 2])
        self.assertEqual([h[5] for h in hits if h[4] == 'flat_task'], ['native-codex-0', 'native-claude-1', 'zcode-2'])

    def test_stale_and_finished_rows_are_dim_and_honest(self):
        ui = ui_for(calm())
        _, _, texts, glyphs = drawn(ui, 1.0)
        fills = {t[0]: t[1] for t in texts}
        self.assertEqual(fills['12分钟前'], f.DIM);self.assertEqual(fills['47分钟前'], f.DIM)
        self.assertEqual(fills['更新于3小时前'], f.DIM)                     # the waiting ZCode session went stale: no orange
        self.assertNotIn(f.COLORS['waiting'], [t[1] for t in texts])
        self.assertEqual([g[0] for g in glyphs[:3]], [f.COLORS['done'], f.DIM, f.DIM])   # 12 min green, 47 min and stale DIM


class ColourMeaningTests(unittest.TestCase):
    def test_state_colours_do_not_follow_the_theme(self):
        for key, theme in ui_themes.THEMES.items():
            P = theme.panel
            _, _, texts, glyphs = drawn(ui_for(busy(), palette=P), 1.0)
            fills = {t[0]: t[1] for t in texts}
            self.assertEqual(fills['等你确认 2分钟'], f.COLORS['waiting'], key)
            self.assertEqual(fills['出错 1分钟'], f.COLORS['error'], key)
            self.assertEqual(fills['运行中 2分钟'], P['DIM'], key)      # running is calm: lavender glyph, neutral words
            self.assertEqual([fills[n] for n in ('Codex', 'Claude', 'ZCode')], [P['INK']] * 3, key)   # names plain INK
            self.assertEqual([(g[0], g[1]) for g in glyphs[:3]],
                             [(f.COLORS['running'], 'star'), (f.COLORS['waiting'], 'ring'), (f.COLORS['error'], 'tri')], key)

    def test_no_pixel_depends_on_the_theme_accent(self):
        # Links, chips, chevrons, tracks and row tints are mixed from BG / INK / DIM only: swapping ACCENT for a
        # garish colour must not change a single pixel in any view.
        for key, theme in ui_themes.THEMES.items():
            loud = dict(theme.panel, ACCENT='#00ff00')
            for sessions, mode in ((busy(), 'live'), (many(), 'tasks'), (steps_many(), 'steps')):
                a = f.render(ui_for(sessions, palette=theme.panel), 1.5, mode, 30)[0]
                b = f.render(ui_for(sessions, palette=loud), 1.5, mode, 30)[0]
                self.assertEqual(a.tobytes(), b.tobytes(), (key, mode))

    def test_neutral_controls_never_equal_a_state_or_accent_colour(self):
        for key, theme in ui_themes.THEMES.items():
            ui = ui_for(busy(), palette=theme.panel);P = theme.panel
            neutral = {f.tint(ui, P['INK'], .13)[:7], f.tint(ui, P['INK'], .16)[:7], f.tint(ui, P['INK'], .055)[:7],
                       f.mix(P['BG'], P['DIM'], .62), f.track_colour(P), f.track_colour(P, 1.6), f.mix(P['DIM'], P['INK'], .35)}
            self.assertFalse(neutral & {P['ACCENT'].lower(), *f.COLORS.values()}, key)
            self.assertGreaterEqual(f.contrast(f.track_colour(P), P['BG']), 3.0, key)   # the quota track stays visible

    def test_running_is_lavender_in_the_agent_switcher_never_green(self):
        _, _, _, glyphs = drawn(ui_for(busy()), 1.0, 'tasks')
        stars = [g for g in glyphs if g[1] == 'star']
        self.assertTrue(stars);self.assertTrue(all(g[0] == f.COLORS['running'] for g in stars))
        self.assertNotIn(f.COLORS['done'], [g[0] for g in glyphs])     # nothing finished recently in this data

    def test_waiting_and_error_groups_get_a_subtle_tint_only(self):
        im = f.render(ui_for(busy()), 1.0, 'live')[0]
        y = lambda i: f.PY + f.LB0 + i * f.LP - 13                     # inside the group box, above the line-1 ink
        px = lambda i: im.getpixel((300, round(y(i))))[:3]             # between the name and the status
        self.assertEqual(px(0), Image.new('RGB', (1, 1), f.BG).getpixel((0, 0)))          # running: plain panel
        for i, st in ((1, 'waiting'), (2, 'error')):
            want = Image.new('RGB', (1, 1), f.mix(f.BG, f.COLORS[st], f.TINT)).getpixel((0, 0))
            self.assertEqual(px(i), want, st)


class QuotaTests(unittest.TestCase):
    def test_the_limiting_window_is_shown(self):
        c = lambda *cy: {'cycles': [{'label': l, 'used': v} for l, v in cy]}
        self.assertEqual(f.quota_pick(c(('5h', 50), ('周', 85)))['label'], '周')
        self.assertEqual(f.quota_pick(c(('5h', 85), ('周', 91)))['label'], '周')
        self.assertEqual(f.quota_pick(c(('5h', 95), ('周', 85)))['label'], '5h')
        self.assertEqual(f.quota_pick(c(('5h', 30), ('周', 79)))['label'], '5h')
        self.assertEqual(f.quota_pick(c(('5h', None), ('周', 85)))['label'], '周')
        self.assertEqual(f.quota_pick(c(('月', 12)))['label'], '月')
        self.assertIsNone(f.quota_pick({'cycles': []}))

    def test_level_colours(self):
        P = f.PALETTE
        level = lambda v, **k: f.quota_colour(dict({'label': '月', 'used': v, 'reset': None, 'stale': False}, **k), NOW, P)
        self.assertEqual(level(69)[0], P['INK']);self.assertEqual(level(0)[0], P['INK'])
        self.assertEqual(level(70), (f.COLORS['waiting'],) * 2);self.assertEqual(level(89.6)[0], f.COLORS['waiting'])
        self.assertEqual(level(90), (f.COLORS['error'],) * 2);self.assertEqual(level(100)[0], f.COLORS['error'])
        self.assertEqual(level(95, stale=True), (P['DIM'], None));self.assertEqual(level(None), (P['DIM'], None))
        self.assertEqual(f.quota_colour(None, NOW, P), (P['DIM'], None))
        # 60 % three hours into a five-hour window runs out before the reset: orange although below 70 %
        fast = {'label': '5h', 'used': 60, 'reset': NOW + 2 * H, 'stale': False}
        self.assertEqual(f.quota_colour(fast, NOW, P)[0], f.COLORS['waiting'])
        self.assertEqual(f.quota_colour(dict(fast, used=30), NOW, P)[0], P['INK'])

    def test_notes_for_fresh_stale_and_unknown_rows(self):
        fresh = q('Claude', ('5h', 40, 2 * H + 40 * 60));stale = q('Claude', ('5h', 40), stale=True, t=NOW - 3 * H - 60)
        with patch.object(f.time, 'localtime', time.gmtime):
            self.assertEqual(f.quota_note(fresh, f.quota_pick(fresh), NOW), f.reset_note(NOW + 2 * H + 40 * 60, NOW))
        self.assertEqual(f.quota_note(stale, f.quota_pick(stale), NOW), '更新于3小时前')
        self.assertEqual(f.quota_note(dict(stale, t=None), f.quota_pick(stale), NOW), '久未更新')
        self.assertEqual(f.quota_note({'name': 'Codex', 'stale': True, 'cycles': []}, None, NOW), '暂无数据')
        self.assertEqual(f.quota_note(q('Codex', ('5h', None)), f.quota_pick(q('Codex', ('5h', None))), NOW), '暂无数据')
        self.assertEqual(f.quota_note(q('Codex', ('5h', 20)), f.quota_pick(q('Codex', ('5h', 20))), NOW), '')   # no reset known

    def test_reset_note_formats_independent_of_the_time_zone(self):
        sat = calendar.timegm((2026, 10, 10, 16, 0, 0, 0, 0, 0))        # a Saturday, read back with gmtime below
        with patch.object(f.time, 'localtime', time.gmtime):
            note = lambda d, now=sat: f.reset_note(now + d, now)
            self.assertEqual(note(2 * H + 40 * 60), '18:40重置')
            self.assertEqual(note(19 * H), '11:00重置')                                    # tomorrow, within 20 h
            self.assertEqual(note(22 * H + 50 * 60, calendar.timegm((2026, 10, 10, 0, 10, 0, 0, 0, 0))), '23:00重置')   # later today
            self.assertEqual(note(3 * D), '周二重置')
            self.assertEqual(note(5 * D), '周四重置')
            self.assertEqual(note(6 * D + 20 * H), '10/17重置')                           # next Saturday: never '周六' (today's weekday)
            self.assertEqual(note(12 * D), '10/22重置')
            self.assertEqual(note(3 * D, calendar.timegm((2026, 12, 30, 12, 0, 0, 0, 0, 0))), '周六重置')   # across new year
            self.assertIsNone(note(0));self.assertIsNone(note(-60));self.assertIsNone(f.reset_note(None, sat))

    def test_rendered_table_rows(self):
        quota = [q('Claude', ('5h', 40, 2 * H), ('周', 63, 4 * D), stale=True, t=NOW - 3 * H - 120),
                 {'name': 'Codex', 'stale': True, 't': None, 'cycles': []}]
        _, _, texts, _ = drawn(ui_for(busy(), quota=quota), 1.5)
        words = strings(texts);fills = {t[0]: t[1] for t in texts}
        self.assertEqual(words[words.index('已用额度'):], ['已用额度', '聊聊', 'Claude', '5h', '40%', '更新于3小时前', 'Codex', '–', '暂无数据'])
        self.assertEqual(fills['40%'], f.DIM);self.assertEqual(fills['–'], f.DIM)   # stale / unknown: no colour, no bar
        _, _, texts, _ = drawn(ui_for(busy(), mock=True), 1.5)
        self.assertIn('已用额度 · 模拟', strings(texts))
        _, _, texts, _ = drawn(ui_for([], quota=[]), 1.5)                              # AIQuota missing
        self.assertEqual(strings(texts)[-6:], ['Claude', '–', '暂无数据', 'Codex', '–', '暂无数据'])


class HitBoxTests(unittest.TestCase):
    CASES = ((busy(), 'live', 0), (calm(), 'live', 0), ([], 'live', 0), (many(), 'tasks', 0), (many(), 'tasks', 47),
             (steps_many(), 'steps', 0), (steps_many(), 'steps', 61), ([], 'tasks', 0), ([], 'steps', 0))

    def test_one_click_target_per_live_group(self):
        for sessions in (busy(), calm(), busy()[:1], []):
            ui = ui_for(sessions)
            _, hits, _, _ = drawn(ui, 1.5)
            groups = [h for h in hits if h[4] == 'flat_task']
            self.assertEqual([h[5] for h in groups], [r['id'] for r in f.agent_rows(ui)])
            self.assertNotIn('flat_agent', [h[4] for h in hits])

    def test_hits_stay_in_the_panel_never_overlap_and_are_known(self):
        for (sessions, mode, offset), u in itertools.product(self.CASES, (1.0, 1.25, 1.5, 2.0)):
            _, hits, _, _ = drawn(ui_for(sessions), u, mode, offset)
            bottom = f.PY + (f.LIVE_H if mode == 'live' else f.PH)
            for x, y, w, h, kind, _ in hits:
                self.assertTrue(kind == 'swallow' or kind in f.CLICKABLE, kind)
                self.assertTrue(round((f.QX - 5) * u) <= x and x + w <= round((f.SB_X + 7) * u), (mode, u, kind, x, w))
                self.assertTrue(round(f.PY * u) <= y and y + h <= round(bottom * u), (mode, u, kind, y, h))
            for a, b in itertools.combinations(hits, 2):
                apart = a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]
                self.assertTrue(apart, (mode, u, offset, a, b))

    def test_scrollbar_column_is_page_thumb_page(self):
        _, hits, _, _ = drawn(ui_for(many()), 1.5, 'tasks', 47)
        bar = [(h[4], h[5]) for h in hits if h[0] == round((f.SB_X - 4) * 1.5)]
        self.assertEqual(bar, [('flat_page', -1), ('flat_thumb', None), ('flat_page', 1)])
        col = sorted(h for h in hits if h[0] == round((f.SB_X - 4) * 1.5))
        self.assertTrue(all(a[1] + a[3] == b[1] for a, b in zip(col, col[1:])))     # contiguous, the whole track
        self.assertEqual((col[0][1], col[-1][1] + col[-1][3]), (round(f.LIST[1] * 1.5), round((f.LIST[1] + f.LIST[3]) * 1.5)))

    def test_rows_scrolled_to_a_sliver_take_no_clicks(self):
        _, hits, _, _ = drawn(ui_for(many()), 1.0, 'tasks', 0)          # the fourth group shows 2 units at the bottom
        rows = [h for h in hits if h[4] == 'flat_task']
        self.assertEqual(len(rows), f.LIST[3] // f.TROW)
        self.assertTrue(all(h[3] >= f.MIN_HIT for h in hits if h[4] in ('flat_task', 'detail')))


class TypeAndFitTests(unittest.TestCase):
    LONG = [sess(0, 'native-codex', 'running', [('调研 资料', OK, False), '委派子智能体 · 工作流与进度'], age=5),
            sess(1, 'native-claude', 'waiting', [('读 popup_material.py', OK, False), '跟进子智能体 · 颜色与对比度'], age=50 * 60),
            sess(2, 'zcode', 'running', [('调研 workflow_stages.py 工作流', OK, False), '读 workflow_stages.py'], age=23 * H + 600)]
    LONG_QUOTA = [q('Codex WSL', ('月', 100, 12 * D)), q('Claude', ('5h', 100, 4 * H + 59 * 60), ('周', 100, 6 * D)),
                  q('Codex', ('5h', 88), stale=True, t=NOW - 23 * H)]

    def test_nothing_below_11_px_and_longest_labels_fit(self):
        for u, mode, theme in itertools.product((1.0, 1.25, 1.5, 2.0), ('live', 'tasks', 'steps'), ui_themes.THEMES.values()):
            for sessions in (self.LONG, busy(), many(), steps_many(), []):
                im, _, texts, glyphs = drawn(ui_for(sessions, quota=self.LONG_QUOTA, palette=theme.panel, mock=True), u, mode, 17)
                for s, _, px, _, _ in texts:
                    self.assertGreaterEqual(px / u, 11 - 1e-9, (s, px, u))
                    self.assertNotIn('…', s)                              # nothing had to be cut
                win = [t for t in texts if t[4] is im]
                col = ((f.QX - 5) * u, f.PY * u, (f.XR + 5) * u, (f.PY + (f.LIVE_H if mode == 'live' else f.PH)) * u)
                for s, _, _, bb, _ in win:
                    self.assertTrue(col[0] <= bb[0] and bb[2] <= col[2] and col[1] <= bb[1] and bb[3] <= col[3], (s, bb, u, mode))
                for a, b in itertools.combinations(texts, 2):
                    if a[4] is b[4]:
                        A, B = a[3], b[3]
                        self.assertFalse(A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3], (a[0], b[0], u, mode))

    def test_quota_columns_do_not_collide(self):
        for u in (1.0, 1.5):
            with patch.object(f.time, 'localtime', time.gmtime):
                _, _, texts, _ = drawn(ui_for(self.LONG, quota=self.LONG_QUOTA), u)
            box = {t[0]: t[3] for t in texts}
            self.assertLess(box['月'][2], box['100%'][0])                   # 'Codex WSL 月' ends before the percentage
            self.assertLess(box['100%'][2], f.QBAR[0] * u)                  # the percentage ends before the bar
            self.assertGreater(box['1/27重置'][0], f.QBAR[1] * u)            # the reset note starts after the bar

    def test_empty_states(self):
        for u in (1.0, 1.5):
            _, hits, texts, _ = drawn(ui_for([]), u)
            self.assertEqual(strings(texts)[:2], ['暂无 AI 会话', '开始工作后会显示在这里'])
            self.assertFalse([h for h in hits if h[4] == 'flat_task'])
            for mode, word in (('tasks', '暂无会话记录'), ('steps', '暂无步骤记录')):
                _, hits, texts, _ = drawn(ui_for([]), u, mode)
                self.assertIn(word, strings(texts))
                self.assertFalse([h for h in hits if h[4] in ('flat_task', 'detail', 'flat_page', 'flat_thumb')])
                well = [h for h in hits if h[4] == 'swallow' and h[1] == round(f.LIST[1] * u)]
                self.assertEqual([h[3] for h in well], [round((f.LIST[1] + f.LIST[3]) * u) - round(f.LIST[1] * u)])


class HostWiringTests(unittest.TestCase):
    """The real Pet press / release / drag / wheel / hover handlers against the hits the real push produced."""

    def setUp(self):
        import pet
        from tools.assets.export_house_stage import owner
        self.pet = pet
        p = self.p = owner(1.25)
        p.sw, p.sh = 2880, 1800
        p._flat_panel_style = p._studio_style = True
        p._house_on = False
        p.settings = {}
        p._flat_mode = 'live'
        p.root = Mock();p.open_chat = Mock();p._ai_work_panel = Mock(closed=False);p.drag = None
        p._wake_from_nap = lambda: False
        for name in ('_catch_collect', '_pop_bubble', '_catch_ball', '_catch_leaf', '_catch_flower', '_catch_snow'):
            setattr(p, name, lambda x, y: False)
        sessions = many() + busy()[2:]
        p._swing = dict(geo=p._art_geo(1), theta=0, scene_l=0, scene_t=0, art=True,
                        ui=dict(now=NOW, mock=True, sessions=sessions, sel_session=sessions[0], sel_key=sessions[0]['agent'],
                                quota=None, codex_quota=None, sources=[]))
        self.push()

    def push(self):
        with patch('pet.push_layered'):
            self.p._push_swing_art(Image.new('RGBA', (self.p.W, self.p.H)))
        return self.p._swing['ui_hits']

    def at(self, kind, payload=None, nth=0):
        hits = [h for h in self.p._swing['ui_hits'] if h[4] == kind and (payload is None or h[5] == payload)]
        x, y, w, h = hits[nth][:4]
        return SimpleNamespace(x=x + w / 2, y=y + h / 2, x_root=x + w / 2, y_root=y + h / 2, delta=0)

    def press(self, e, release=True):
        self.pet.Pet.on_press(self.p, e)
        if release:
            self.pet.Pet.on_release(self.p, e)
        return self.push()

    def hover(self, e):
        self.p.root.configure.reset_mock();self.p._house_hover = None
        self.pet.Pet.on_hover(self.p, e)
        return [c.kwargs.get('cursor') for c in self.p.root.configure.call_args_list]

    def test_every_clickable_kind_shows_the_hand_and_swallow_does_not(self):
        seen = set()
        for mode in ('live', 'tasks', 'steps'):
            self.p._flat_mode, self.p._flat_agent = mode, 'Codex'
            self.p._flat_cache = None
            for x, y, w, h, kind, payload in self.push():
                e = SimpleNamespace(x=x + w / 2, y=y + h / 2)
                self.assertEqual(self.hover(e), ['hand2'] if kind in f.CLICKABLE else [], (mode, kind))
                seen.add(kind)
        self.assertEqual(seen, {'flat_task', 'flat_mode', 'flat_back', 'flat_agent', 'flat_page', 'flat_thumb', 'house_chat',
                                'detail', 'swallow'})

    def test_live_group_opens_its_steps_and_back_returns_to_live(self):
        self.press(self.at('flat_task', 'zcode-2'))
        self.assertEqual((self.p._flat_mode, self.p._flat_agent, self.p._book_sel), ('steps', 'ZCode', ('sid', 'zcode-2')))
        self.press(self.at('flat_back'))
        self.assertEqual(self.p._flat_mode, 'live')
        self.press(self.at('house_chat'))
        self.p.open_chat.assert_called_once()

    def test_tasks_rows_scroll_page_drag_open_and_come_back(self):
        p = self.p
        self.press(self.at('flat_task', 'native-codex-0'));self.press(self.at('flat_agent', 'Codex'))   # live -> steps -> switcher
        self.assertEqual((p._flat_mode, p._flat_agent), ('tasks', 'Codex'))
        well = self.at('flat_task')
        self.pet.Pet.on_wheel_scene(p, SimpleNamespace(x=well.x, y=well.y, delta=-120));self.push()
        self.assertEqual(p._flat_scroll, f.TROW)                        # one notch = one group
        self.pet.Pet.on_wheel_scene(p, SimpleNamespace(x=well.x, y=well.y, delta=120));self.push()
        self.assertEqual(p._flat_scroll, 0)
        page = f.LIST[3] // f.TROW * f.TROW
        self.press(self.at('flat_page', 1));self.assertEqual(p._flat_scroll, page)          # track below the thumb pages
        self.assertIsNone(getattr(p, '_flat_bar_drag', None))
        thumb = self.at('flat_thumb')
        self.pet.Pet.on_press(p, thumb)                                  # the thumb drags, all the way down
        self.pet.Pet.on_drag(p, SimpleNamespace(x=thumb.x, y=thumb.y + 400, x_root=0, y_root=0))
        self.pet.Pet.on_release(p, SimpleNamespace(x=thumb.x, y=thumb.y + 400, x_root=0, y_root=0));self.push()
        limit = len(f.rows_for(f.owner_ui(p, p._swing['ui']), 'tasks')) * f.TROW - f.LIST[3]
        self.assertEqual((p._flat_scroll, p._flat_bar_drag), (limit, None))
        self.press(self.at('flat_page', -1));self.assertEqual(p._flat_scroll, limit - page)
        row = self.at('flat_task', nth=1);sid = [h for h in p._swing['ui_hits'] if h[4] == 'flat_task'][1][5]
        self.press(row)
        self.assertEqual((p._flat_mode, p._book_sel), ('steps', ('sid', sid)))
        self.press(self.at('flat_back'))
        self.assertEqual((p._flat_mode, p._flat_scroll), ('tasks', limit - page))   # back where the user was
        self.press(self.at('flat_mode', 'live'))
        self.assertEqual(p._flat_mode, 'live')

    def test_steps_row_opens_the_work_panel_on_that_step(self):
        self.press(self.at('flat_task', 'native-codex-0'))
        payload = [h for h in self.p._swing['ui_hits'] if h[4] == 'detail'][0][5]
        self.press(self.at('detail'))
        self.p._ai_work_panel.show_detail.assert_called_once_with(payload)
        panel = Mock(closed=False);self.p._ai_work_panel = None          # closed panel: the click opens it first
        self.p.open_ai_panel = Mock();self.p._sync_ai_panel = Mock(side_effect=lambda sw, ui: setattr(self.p, '_ai_work_panel', panel))
        self.press(self.at('detail'))
        self.p.open_ai_panel.assert_called_once();panel.show_detail.assert_called_once_with(payload)

    def test_ai_mode_press_reaches_the_same_hits(self):
        e = self.at('flat_task', 'native-claude-20')
        self.p._static_active = lambda: True                           # AI pet mode skips her catch / nap handling
        self.pet.Pet.on_press(self.p, e);self.pet.Pet.on_release(self.p, e)
        del self.p._static_active
        self.assertEqual((self.p._flat_mode, self.p._flat_agent), ('steps', 'Claude'))



class RebuildCost(unittest.TestCase):
    """I-51 review: a panel rebuild must not re-parse every session's history (43 real sessions cost ~5 ms in the rank
    sort and ~11 ms in the tasks list, enough to drop a 60 fps frame on every scan while an agent works)."""

    def sessions(self):
        rows = [sess(0, 'native-codex', 'running', [('读 a.py', OK, False), '改 a.py'], age=5),
                sess(1, 'native-claude', 'waiting', ['改 b.py'], age=7300),        # waiting > 2 h: stale
                sess(2, 'zcode', 'error', [('跑测试', 'FAILED', True)], age=100),
                sess(3, 'native-codex', 'running', ['读 c.py'], age=2500),          # running > 40 min: stale
                sess(4, 'native-codex', 'done', [('改 d.py', OK, False)], age=60),
                dict(sess(5, 'mac-claude', 'running', ['读 e.py'], age=1), stale=True),
                {}, {'state': 'running'}, {'state': 'weird', 'updated': NOW + 50}]
        return rows

    def test_stale_verdict_matches_the_workflow_reader(self):
        from moon_board import workflow
        for now in (NOW, NOW + 3000, NOW + 8000):
            ui = {'now': now}
            for s in self.sessions():
                self.assertEqual(f._stale(ui, s), workflow(dict(ui, sel_session=s))['stale'], (now, s.get('id')))

    def test_rank_and_lights_never_parse_the_history(self):
        ui = dict(now=NOW, sessions=self.sessions())
        with patch('moon_board.workflow', side_effect=AssertionError('parsed')),                 patch.object(f, 'workflow', side_effect=AssertionError('parsed')):
            self.assertEqual(f.agent_lights(ui), [('Codex', 'running'), ('Claude', 'idle'), ('ZCode', 'error'), ('AI', 'idle')])   # agent-less rows: AI
            self.assertEqual(f.session_for(ui, 'Codex', prefer_current=False)['id'], 'native-codex-0')

    def test_session_row_is_memoised_on_content_and_staleness(self):
        f._ROWS.clear()
        s = sess(0, 'native-codex', 'running', [('读 a.py', OK, False), '改 a.py'], age=5)
        ui = {'now': NOW}
        first = f.session_row(ui, s)
        with patch.object(f, 'stages', side_effect=AssertionError('re-parsed')):
            again = f.session_row(ui, dict(s))                                 # a new scan, same content: no parse
        self.assertEqual(again, first)
        again['title'] = 'changed'                                            # callers get copies, never the cache entry
        self.assertEqual(f.session_row(ui, s), first)
        grown = dict(s, actions=[{'a': '跑测试 unittest', 't': NOW - 1}] + s['actions'], updated=NOW - 1)
        self.assertEqual(f.session_row(ui, grown)['title'], '测试与验证')       # new content: parsed again
        late = f.session_row({'now': NOW + 3000}, s)                           # crossing the stale age: parsed again
        self.assertEqual((late['state'], late['stale']), ('idle', True))
        self.assertEqual((first['state'], first['stale']), ('running', False))
        for i in range(f.ROW_CACHE + 20):
            f.session_row(ui, sess(i, 'zcode', 'done', ['读 x.py'], age=i))
        self.assertLessEqual(len(f._ROWS), f.ROW_CACHE)
        f._ROWS.clear()


if __name__ == '__main__':
    unittest.main()
