"""I-52: character sprites are decoded and scaled off the frame loop.

The pack's own prewarm scales every pose it can show (idle first) and its
cameos within half the scaled budget; while a foreground switch is pending the
host warms the poses that switch shows first. Public packs and synthetic
fixtures only; no Tk window, model or personal data.
"""
import copy
import hashlib
import json
import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import appearance as ap
import pet
from ai_pet import AiPetDirector, _CST
from flat_workspace import static_layout
from test_appearance import shell

ASSETS = Path(pet.ASSETS)
BOX = static_layout(1.5, 30)[2]          # the live window: u=1.5 with the hat headroom
SMALL = static_layout(1.0, 0)[2]
ROLES = ('claude', 'codex', 'gemini', 'deepseek', 'glm')


def poses(cat, character):
    return tuple(cat.get(character).poses)


def pictures(cat, character):
    """(pose, index, blink) of every picture a pack can show."""
    out = [(pose, i, False) for pose in cat.get(character).poses for i in range(cat.frame_count(character, pose))]
    blink = cat.blink_index(character)
    return out + ([('idle', blink, True)] if blink is not None else [])


def cached(cat, character, size):
    return {(k[3], k[4], k[5]) for k in cat._scaled if k[0] == character and k[6:] == tuple(size)}


def recording(cat):
    """Patch cat.frame to record (args, result) of every call, e.g. prewarm's."""
    made, real = [], cat.frame

    def frame(*args, **kwargs):
        result = real(*args, **kwargs)
        made.append((args, result))
        return result
    return made, patch.object(cat, 'frame', side_effect=frame)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


def picture(folder, name, size=(100, 120), fill=(100, 120, 140, 255)):
    image = Image.new('RGBA', size)
    ImageDraw.Draw(image).ellipse((10, 5, size[0] - 10, size[1] - 1), fill=fill)
    image.save(folder / name)
    return {'file': name, 'size': list(size), 'foot_anchor': [size[0] / 2, size[1]],
            'sha256': hashlib.sha256((folder / name).read_bytes()).hexdigest()}


def fixture(root):
    """Host 'demo' (two idle variants and a blink, three more poses) and its cameo."""
    chars = root / 'characters'
    host = chars / 'demo'
    host.mkdir(parents=True)
    host_poses = {'idle': [picture(host, 'idle-0.png'), picture(host, 'idle-1.png', fill=(90, 160, 120, 255))],
                  'thinking': [picture(host, 'thinking.png', fill=(200, 80, 80, 255))],
                  'sleeping': [picture(host, 'sleeping.png', fill=(40, 40, 160, 255))],
                  'greet_noon': [picture(host, 'greet.png', fill=(240, 200, 40, 255))]}
    blink = dict(picture(host, 'blink.png', fill=(10, 10, 10, 255)), base='idle-1.png')
    write_json(host / 'manifest.json', {'schema_version': 2, 'id': 'demo', 'renderer': 'static', 'version': 1,
                                        'label': 'Demo', 'theme': 'claude', 'reference_size': [100, 120],
                                        'poses': host_poses, 'blink': blink})
    egg = chars / 'egg-demo'
    egg.mkdir()
    egg_poses = {pose: [picture(egg, pose + '.png', (80, 100), (40 * i, 90, 200, 255))]
                 for i, pose in enumerate(('pop', 'pretend', 'caught', 'bye'))}
    info = {'host': 'demo', 'caption': 'Hi', 'aura': '#ffd9b0'}
    write_json(egg / 'manifest.json', {'schema_version': 2, 'id': 'egg-demo', 'renderer': 'static', 'version': 1,
                                       'label': 'Egg', 'theme': 'claude', 'reference_size': [80, 100],
                                       'poses': egg_poses, 'egg': info})
    write_json(chars / 'registry.json', {
        'schema_version': 2, 'themes': {'claude': 'Claude'},
        'characters': [{'id': 'demo', 'label': 'Demo', 'theme': 'claude', 'manifest': 'demo/manifest.json'},
                       {'id': 'egg-demo', 'manifest': 'egg-demo/manifest.json', 'egg': info}],
        'providers': {'demo': {'character': 'demo', 'theme': 'claude', 'windows_apps': ['Demo.exe']}}})
    return host, egg


class PrewarmScalingTests(unittest.TestCase):
    def setUp(self):
        natives = patch.object(ap, 'MAX_NATIVE_CACHE', 256)      # decode each picture once per test
        natives.start()
        self.addCleanup(natives.stop)

    def test_prewarm_scales_every_pose_and_cameo_idle_and_blink_first(self):
        cat = ap.CharacterCatalog.load(ASSETS)
        made, spy = recording(cat)
        with spy:
            self.assertTrue(cat.prewarm('claude', poses(cat, 'claude'), box_size=BOX))
        order = [(a[0], a[1], a[3], a[4]) for a, _ in made]
        blink = cat.blink_index('claude')
        idle = [('claude', 'idle', i, False) for i in range(cat.frame_count('claude', 'idle'))]
        self.assertEqual(order[:len(idle) + 1], idle + [('claude', 'idle', blink, True)])
        self.assertEqual(len(order), len(set(order)))                     # each picture once
        self.assertEqual(cached(cat, 'claude', BOX), set(pictures(cat, 'claude')))
        self.assertEqual(cached(cat, 'egg-claude', BOX), set(pictures(cat, 'egg-claude')))
        self.assertEqual({k[0] for k in cat._scaled}, {'claude', 'egg-claude'})
        # The frame loop then neither decodes nor resamples: every pose is the cached object.
        with patch.object(ap.CharacterCatalog, '_decode', side_effect=AssertionError('decoded')):
            for pose, index, blinking in pictures(cat, 'claude'):
                frame = cat.frame('claude', pose, BOX, index, blinking)
                self.assertIs(cat._scaled[frame.ref], frame)

    def test_a_scaled_tuple_limits_scaling_and_skips_cameos(self):
        cat = ap.CharacterCatalog.load(ASSETS)
        self.assertTrue(cat.prewarm('codex', ('thinking', 'idle', 'tired', 'nonsense'), box_size=BOX,
                                    scaled=('thinking', 'idle')))
        idle = {('idle', i, False) for i in range(cat.frame_count('codex', 'idle'))}
        self.assertEqual(cached(cat, 'codex', BOX),
                         idle | {('idle', cat.blink_index('codex'), True), ('thinking', 0, False)})
        self.assertFalse(cached(cat, 'egg-codex', BOX))
        tired = cat._spec('codex', 'tired')
        self.assertIn(('codex', tired.path, tired.sha), cat._natives)    # decoded, not scaled
        cat.clear_scaled_cache()
        self.assertTrue(cat.prewarm('codex', ('idle',)))                  # no box: decode only, as before
        self.assertFalse(cat._scaled)

    def test_one_call_uses_at_most_half_the_entries_and_never_evicts_its_own(self):
        cat = ap.CharacterCatalog.load(ASSETS)
        self.assertTrue(cat.prewarm('claude', poses(cat, 'claude'), box_size=BOX))
        with patch.object(ap, 'MAX_SCALED_CACHE', 24):
            shown = [cat.frame('claude', 'idle', BOX, i) for i in range(3)]    # what is on screen now
            made, spy = recording(cat)
            with spy:
                self.assertTrue(cat.prewarm('codex', poses(cat, 'codex'), box_size=BOX))
            own = [frame for _, frame in made]
            self.assertEqual(len(own), 12)
            self.assertTrue(all(frame is not None and cat._scaled.get(frame.ref) is frame for frame in own))
            self.assertEqual([f.pose for f in own[:4]], ['idle'] * 4)
            self.assertEqual(len(cat._scaled), 24)
            for frame in shown:
                self.assertIs(cat._scaled.get(frame.ref), frame)

    def test_one_call_uses_at_most_half_the_pixels_and_never_evicts_its_own(self):
        cat = ap.CharacterCatalog.load(ASSETS)
        limit = 20 * BOX[0] * BOX[1]
        with patch.object(ap, 'MAX_SCALED_PIXELS', limit):
            made, spy = recording(cat)
            with spy:
                self.assertTrue(cat.prewarm('deepseek', poses(cat, 'deepseek'), box_size=BOX))
            own = [frame for _, frame in made]
            self.assertLessEqual(sum(f.image.width * f.image.height for f in own), limit // 2)
            self.assertGreater(len(own), 4)
            self.assertTrue(all(cat._scaled.get(f.ref) is f for f in own))
            self.assertLess(len(own), len(pictures(cat, 'deepseek')))       # the rest scale on first use
            self.assertIsNotNone(cat.frame('deepseek', 'yawn', BOX))
            self.assertLessEqual(cat._scaled_pixels, limit)

    def test_every_pack_stays_within_the_pixel_bound_which_is_the_real_limit(self):
        cat = ap.CharacterCatalog.load(ASSETS)
        for size in (SMALL, BOX):
            cat.clear_scaled_cache()
            for role in ROLES:
                self.assertTrue(cat.prewarm(role, poses(cat, role), box_size=size))
                self.assertEqual(cached(cat, role, size), set(pictures(cat, role)))     # the latest is whole
                self.assertEqual(cached(cat, 'egg-' + role, size), set(pictures(cat, 'egg-' + role)))
                self.assertLessEqual(cat._scaled_pixels, ap.MAX_SCALED_PIXELS)
                self.assertLessEqual(len(cat._scaled), ap.MAX_SCALED_CACHE)
            everything = sum(len(pictures(cat, r)) + len(pictures(cat, 'egg-' + r)) for r in ROLES)
            if size == SMALL:
                self.assertEqual(len(cat._scaled), everything)            # all five packs fit by count
            else:
                self.assertLess(len(cat._scaled), everything)             # pixels bound the big box
                self.assertGreater(cat._scaled_pixels, ap.MAX_SCALED_PIXELS * 9 // 10)

    def test_frames_are_identical_whether_scaled_in_prewarm_or_at_first_use(self):
        warm, cold = ap.CharacterCatalog.load(ASSETS), ap.CharacterCatalog.load(ASSETS)
        for role in ('claude', 'gemini'):
            for size in (BOX, SMALL):
                self.assertTrue(warm.prewarm(role, poses(warm, role), box_size=size))
                for character in (role, 'egg-' + role):
                    for pose, index, blink in pictures(warm, character):
                        key = next(k for k in warm._scaled
                                   if k[0] == character and k[3:6] == (pose, index, blink) and k[6:] == size)
                        a, b = warm._scaled[key], cold.frame(character, pose, size, index, blink)
                        self.assertEqual((a.ref, a.pose, a.index, a.offset, a.alpha_box, a.image.mode, a.image.size),
                                         (b.ref, b.pose, b.index, b.offset, b.alpha_box, b.image.mode, b.image.size))
                        self.assertEqual(a.image.tobytes(), b.image.tobytes())


class PrewarmFailureTests(unittest.TestCase):
    def test_a_broken_cameo_disables_only_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, egg = fixture(Path(tmp))
            cat = ap.CharacterCatalog.load(Path(tmp))
            self.assertEqual(cat.eggs_for('demo'), ('egg-demo',))
            (egg / 'pop.png').unlink()
            self.assertTrue(cat.prewarm('demo', poses(cat, 'demo'), box_size=(90, 110)))
            self.assertTrue(cat.get('demo').available)
            self.assertFalse(cat.get('egg-demo').available)
            self.assertEqual(cat.eggs_for('demo'), ())
            self.assertEqual(cached(cat, 'demo', (90, 110)), set(pictures(cat, 'demo')))
            self.assertFalse(any(k[0] == 'egg-demo' for k in list(cat._scaled) + list(cat._natives)))

    def test_cameos_of_a_good_fixture_are_scaled(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(Path(tmp))
            cat = ap.CharacterCatalog.load(Path(tmp))
            self.assertTrue(cat.prewarm('demo', poses(cat, 'demo'), box_size=(90, 110)))
            self.assertEqual(cached(cat, 'egg-demo', (90, 110)), set(pictures(cat, 'egg-demo')))
            self.assertEqual(cached(cat, 'demo', (90, 110)),
                             {('idle', 0, False), ('idle', 1, False), ('idle', 1, True), ('thinking', 0, False),
                              ('sleeping', 0, False), ('greet_noon', 0, False)})

    def test_a_missing_host_picture_still_disables_the_whole_pack_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, _ = fixture(Path(tmp))
            cat = ap.CharacterCatalog.load(Path(tmp))
            (host / 'thinking.png').unlink()
            self.assertFalse(cat.prewarm('demo', poses(cat, 'demo'), box_size=(90, 110)))
            self.assertFalse(cat.get('demo').available)
            self.assertFalse(any(k[0] == 'demo' for k in list(cat._scaled) + list(cat._natives)))
            self.assertIsNone(cat.frame('demo', 'idle', (90, 110)))

    def test_disable_while_scaling_stops_prewarm_and_drops_the_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(Path(tmp))
            cat = ap.CharacterCatalog.load(Path(tmp))
            real = cat.frame

            def frame(*args):
                result = real(*args)
                cat.disable('demo', 'image_missing')        # e.g. the frame loop met a broken file
                return result
            with patch.object(cat, 'frame', side_effect=frame):
                self.assertFalse(cat.prewarm('demo', poses(cat, 'demo'), box_size=(90, 110)))
            self.assertFalse(cat.get('demo').available)
            self.assertFalse(any(k[0] == 'demo' for k in list(cat._scaled) + list(cat._natives)))


def noon(month=6, day=10, hour=12):
    return datetime(2026, month, day, hour, 0, tzinfo=_CST).timestamp()


class EntryPoseTests(unittest.TestCase):
    """entry_poses must cover what pet._apply_look's switch shows in its first second."""
    def setUp(self):
        self.cat = ap.CharacterCatalog.load(ASSETS)

    def shown_after_switch(self, memory, target, now, level, low, chat_open, model_thinking, seed):
        d = AiPetDirector(self.cat, rng=random.Random(seed), memory=memory)
        d.set_character('claude' if target != 'claude' else 'gemini', now - 30, 'entered')
        d.tick(now - 30)
        d.set_character(target, now, 'foreground')                    # as pet._apply_look
        d.on_work(level, [], now)
        if target in ('claude', 'codex'):
            d.set_quota(low, (), now)
        seen = set()
        for k in range(61):
            view = d.tick(now + k / 60, chat_open=chat_open, model_thinking=model_thinking)
            seen.add(view.art_pose)
            if view.fade_from and view.fade_from[0] == target:
                seen.add(view.fade_from[1])
        return seen

    def test_entry_poses_cover_the_first_second_of_a_switch(self):
        cases = 0
        for target in ('codex', 'claude', 'gemini'):
            for saved_low in (False, True):
                for low in (False, True):
                    for level in (None, 'searching', 'thinking'):
                        for chat_open, thinking in ((False, False), (True, False), (False, True)):
                            for now in (noon(), noon(10, 1), noon(12, 25, 23), noon(hour=4)):
                                memory = {'quota': {target: {'low': saved_low}}}
                                d = AiPetDirector(self.cat, rng=random.Random(1), memory=memory)
                                before = copy.deepcopy(memory)
                                entry = d.entry_poses(target, now, level, chat_open=chat_open, model_thinking=thinking)
                                self.assertEqual(memory, before)               # read-only
                                self.assertIsNone(d.character)
                                warmed = {self.cat.resolve(target, p) for p in entry}
                                for seed in (3, 4):
                                    shown = self.shown_after_switch(copy.deepcopy(memory), target, now, level,
                                                                    low, chat_open, thinking, seed)
                                    self.assertLessEqual(shown, warmed, (target, saved_low, low, level,
                                                                         chat_open, thinking, now, entry))
                                cases += 1
        self.assertGreater(cases, 400)

    def test_entry_poses_order_and_unavailable_packs(self):
        d = AiPetDirector(self.cat, rng=random.Random(1), memory={'quota': {'codex': {'low': True}}})
        self.assertEqual(d.entry_poses('codex', noon(), 'searching'), ('tired', 'idle', 'searching', 'greet_noon'))
        self.assertEqual(d.entry_poses('gemini', noon(10, 1)), ('idle', 'fest_national', 'greet_noon'))
        self.assertEqual(d.entry_poses('glm', noon(), None, chat_open=True), ('idle', 'listening', 'greet_noon'))
        self.assertEqual(d.entry_poses('egg-claude', noon()), ())
        self.assertEqual(d.entry_poses('nobody', noon()), ())
        self.assertEqual(d.entry_poses('glm', float('nan')), ('idle',))


class FakeThread:
    """Records workers instead of running them; is_alive is under test control."""
    made = []
    alive = False

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs, self.daemon = target, args, kwargs or {}, daemon
        FakeThread.made.append(self)

    def start(self):
        pass

    def is_alive(self):
        return FakeThread.alive


class CandidatePrewarmHostTests(unittest.TestCase):
    def setUp(self):
        FakeThread.made, FakeThread.alive = [], False
        for job in (patch('foreground_ai.ForegroundProcess.current', return_value=None),
                    patch('pet.threading.Thread', FakeThread)):
            job.start()
            self.addCleanup(job.stop)
        self.p = shell(_swing={'geo': {'flat': True, 'u': 1.5, 'hat_fx_pad': 30}})
        self.p._fg_probe = Mock()
        self.p._fg_probe.current.return_value = 'claude.exe'
        self.now, self.mono = 1000.0, 100.0

    def poll(self, app, advance=.25):
        """One foreground poll (FG_POLL_S after the last); the selector's clock moves by advance."""
        self.p._fg_probe.current.return_value = app
        self.now += self.p.FG_POLL_S
        self.mono += advance
        with patch('pet.time.monotonic', return_value=self.mono):
            self.p._poll_foreground(self.now)

    def candidates(self):
        return [t for t in FakeThread.made if 'scaled' in t.kwargs]

    def test_one_worker_per_pending_candidate_with_the_switch_poses(self):
        self.assertTrue(self.p.set_appearance_mode('ai'))
        self.assertEqual(self.p._appearance.selection.character, 'claude')
        full = [t for t in FakeThread.made if 'scaled' not in t.kwargs]
        self.assertEqual([(t.args[0], t.kwargs) for t in full], [('claude', {'box_size': BOX})])   # _apply_look as before
        self.poll('ChatGPT.exe')
        self.poll('ChatGPT.exe')
        (worker,) = self.candidates()
        self.assertEqual(worker.target, self.p._appearance.catalog.prewarm)
        self.assertEqual(worker.args[0], 'codex')
        self.assertEqual(worker.args[1][:2], ('idle', 'tired'))
        self.assertEqual(worker.kwargs, {'box_size': BOX, 'scaled': worker.args[1]})
        self.assertTrue(worker.daemon)
        self.poll('ChatGPT.exe')                                       # 0.75 s: the switch commits
        self.assertEqual(self.p._appearance.selection.character, 'codex')
        self.poll('ChatGPT.exe')
        self.assertEqual(len(self.candidates()), 1)
        self.assertEqual([t.args[0] for t in FakeThread.made if 'scaled' not in t.kwargs], ['claude', 'codex'])
        self.poll('claude.exe')
        self.poll('claude.exe')
        self.assertEqual([t.args[0] for t in self.candidates()], ['codex', 'claude'])

    def test_the_work_pose_of_the_candidate_is_warmed(self):
        self.p.set_appearance_mode('ai')
        now = pet.time.time()
        rows = [dict(id='simulated-codex', agent='native-codex', state='running', updated=now,
                     since=now, stale=False, actions=[dict(a='读 合成资料', r='', t=now)])]
        self.p._ai_work_sessions = rows
        self.p._ai_sessions_scanned = True
        self.p._ai_sync_work(now, rows)
        level = self.p._ai_work.level('codex', pet.time.time())
        self.assertIsNotNone(level)
        self.poll('ChatGPT.exe')
        (worker,) = self.candidates()
        self.assertEqual(worker.args[1][2], level)

    def test_no_worker_for_the_shown_character_xiaoqiao_mode_or_a_pin(self):
        self.p.set_appearance_mode('ai')
        for _ in range(4):
            self.poll('claude.exe')
        self.poll('explorer.exe')
        self.assertEqual(self.candidates(), [])
        self.p.set_appearance_mode('xiaoqiao')
        for _ in range(4):
            self.poll('ChatGPT.exe')
        self.assertEqual(self.candidates(), [])
        self.p.set_appearance_mode('ai', pin='gemini')
        for _ in range(4):
            self.poll('ChatGPT.exe')
        self.assertEqual(self.p._appearance.selection.character, 'gemini')
        self.assertEqual(self.candidates(), [])

    def test_one_worker_at_a_time_and_a_new_box_or_episode_warms_again(self):
        self.p.set_appearance_mode('ai')
        self.poll('ChatGPT.exe')
        FakeThread.alive = True                                        # codex's worker is still decoding
        self.poll('antigravity.exe')
        self.poll('antigravity.exe', advance=.1)
        self.assertEqual([t.args[0] for t in self.candidates()], ['codex'])
        FakeThread.alive = False
        self.poll('antigravity.exe', advance=.1)                       # gemini, still not stable
        self.assertEqual(self.p._appearance.selection.character, 'claude')
        self.assertEqual([t.args[0] for t in self.candidates()], ['codex', 'gemini'])
        self.p._swing['geo']['u'] = 1.0                                # the window was rescaled
        self.poll('antigravity.exe', advance=.1)
        self.assertEqual([(t.args[0], t.kwargs['box_size']) for t in self.candidates()][-1],
                         ('gemini', static_layout(1.0, 30)[2]))
        self.poll('explorer.exe')                                      # dropped before it was stable...
        self.poll('antigravity.exe')                                   # ...so this is a new candidate
        self.assertEqual([t.args[0] for t in self.candidates()], ['codex', 'gemini', 'gemini', 'gemini'])

    def test_art_box_matches_the_workspace_layout(self):
        self.assertEqual(self.p._static_art_box(), BOX)
        self.p._swing = {'geo': {'flat': False, 'u': 1.5}}
        self.assertIsNone(self.p._static_art_box())
        self.p._swing = None
        self.assertIsNone(self.p._static_art_box())


if __name__ == '__main__':
    unittest.main()
