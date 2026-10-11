"""I-48: per-frame cost cuts that must not change a single pixel or miss new data.

Synthetic data only; no Tk window, model or personal files.
"""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

import flat_workspace as f
import native_session_sync as nss


def ui_with(sessions):
    return dict(sessions=sessions, sel_session=sessions[0] if sessions else None, quota={'fh': 10},
                codex_quota=None, codex_quota_error=False, mock=False, quota_widget=[{'name': 'Claude'}],
                flat_agent='Claude', panel_alpha=232)


class PanelKeyTests(unittest.TestCase):
    def setUp(self):
        self.owner = SimpleNamespace()
        self.sessions = [dict(id='s1', agent='native-claude', state='running', actions=[{'a': '读 x'}])]

    def test_data_part_equals_the_old_full_repr(self):
        ui = ui_with(self.sessions)
        self.assertEqual(f.panel_data_key(self.owner, ui), repr(tuple(ui.get(n) for n in f.PANEL_DATA)))

    def test_unchanged_objects_skip_the_full_repr(self):
        ui = ui_with(self.sessions)
        first = f.panel_data_key(self.owner, ui)
        calls = []
        real = repr
        with patch('builtins.repr', side_effect=lambda v: calls.append(type(v).__name__) or real(v)):
            again = f.panel_data_key(self.owner, dict(ui))
        self.assertIs(again, first)
        self.assertNotIn('tuple', calls)              # the big session tuple was not re-serialised

    def test_a_new_scan_list_changes_the_key_at_once(self):
        ui = ui_with(self.sessions)
        first = f.panel_data_key(self.owner, ui)
        fresh = [dict(self.sessions[0], state='done')]
        self.assertNotEqual(f.panel_data_key(self.owner, ui_with(fresh)), first)

    def test_cheap_fields_change_the_key_at_once(self):
        ui = ui_with(self.sessions)
        first = f.panel_data_key(self.owner, ui)
        self.assertNotEqual(f.panel_data_key(self.owner, dict(ui, panel_alpha=248)), first)
        self.assertNotEqual(f.panel_data_key(self.owner, dict(ui, flat_agent='Codex')), first)
        self.assertNotEqual(f.panel_data_key(self.owner, dict(ui, quota_widget=[{'name': 'Codex'}])), first)

    def test_an_in_place_edit_is_caught_within_the_recheck_window(self):
        ui = ui_with(self.sessions)
        clock = [100.0]
        with patch.object(f.time, 'monotonic', lambda: clock[0]):
            first = f.panel_data_key(self.owner, ui)
            self.sessions[0]['state'] = 'error'           # edited in place, same list object
            self.assertEqual(f.panel_data_key(self.owner, ui), first)
            clock[0] += f.PANEL_RECHECK
            self.assertNotEqual(f.panel_data_key(self.owner, ui), first)


class StaticSmallLayerTests(unittest.TestCase):
    def owner(self, theta):
        maps = []

        def art_small_map(sw):
            maps.append(sw['theta'])
            return (5 + sw['theta'] * 100, 7, .5)

        frame = SimpleNamespace(image=Image.new('RGBA', (20, 30), (255, 0, 0, 255)), offset=(1, 2))
        o = SimpleNamespace(_swing={'geo': {'u': 1.0, 'k': .2, 'O': (0, 0), 'flat': True}, 'ui': ui_with([]),
                                    'scene_l': 0, 'scene_t': 0, 'theta': theta},
                            _scene_art=Mock(), _ac=Mock(), hwnd=1, _art_small_map=art_small_map,
                            _static_look=lambda size: (frame, 0), _ui_theme=None)
        return o, maps

    def test_ai_bubble_layer_ignores_the_hidden_swing_and_is_scaled_once(self):
        o, maps = self.owner(theta=.2)
        small = Image.new('RGBA', (40, 40), (0, 0, 255, 255))
        with patch('pet.push_layered'), patch.object(Image.Image, 'resize', autospec=True,
                                                    side_effect=Image.Image.resize) as resize:
            f.push(o, small)
            resize.reset_mock()                           # the first frame also drew the panel
            o._swing['theta'] = -.3
            f.push(o, small)
        self.assertEqual(maps, [])                        # AI speech never enters the hidden rig
        self.assertEqual(resize.call_count, 0)            # second frame reused the scaled layer

    def test_no_layer_means_no_scaling_work(self):
        o, maps = self.owner(theta=.2)
        with patch('pet.push_layered'):
            f.push(o, None)
        self.assertEqual(maps, [])


class PollTests(unittest.TestCase):
    def test_an_unchanged_transcript_is_not_reopened(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rollout.jsonl'
            path.write_text('{"type": "x"}\n', encoding='utf-8')
            reader = SimpleNamespace(path=path, offset=None, pending=b'', consume=Mock())
            nss.Transcript.poll(reader)
            self.assertEqual(reader.offset, path.stat().st_size)
            with patch.object(Path, 'open', side_effect=AssertionError('reopened')):
                nss.Transcript.poll(reader)
            with path.open('a', encoding='utf-8') as out:
                out.write('{"type": "y"}\n')
            nss.Transcript.poll(reader)
            self.assertEqual(reader.consume.call_count, 2)


class AiRenderBranchTests(unittest.TestCase):
    def test_ai_speech_is_drawn_by_the_compositor_without_old_full_layer(self):
        import pet
        p = pet.Pet.__new__(pet.Pet)
        p.state, p._swing, p.W, p.H, p.bubble = 'swing', {'art': True}, 120, 160, None
        p._push_swing = Mock()
        p._bubble_sprite = Mock(return_value=Image.new('RGBA', (40, 20), (9, 9, 9, 255)))
        p._bubble_alpha = Mock(return_value=1.0)
        with patch.object(pet.Pet, '_static_active', return_value=True):
            p.render(10.0, 0)
            self.assertIsNone(p._push_swing.call_args[0][0])     # nothing to scale without speech
            p.bubble = ('你好', 20.0)
            p.render(10.1, 0)
            p.render(10.2, 0)
        first, second = (c[0][0] for c in p._push_swing.call_args_list[1:3])
        self.assertIs(first, second)
        self.assertEqual(p._bubble_sprite.call_count, 0)


class CommandPollTests(unittest.TestCase):
    def shell(self, path):
        import pet
        p = pet.Pet.__new__(pet.Pet)
        p.mainq = __import__('queue').Queue()
        p._next_ai_scan = float('inf')
        p._poll_foreground = Mock()
        p.cmd_path, p._cmd_seen = str(path), 0.0
        p._exec_cmd = Mock()
        return p

    def test_every_frame_sees_a_new_command_with_one_stat(self):
        # pet_cmd.json is a single slot: polling must not back off, or a second
        # command written soon after would overwrite the first one unseen.
        import os
        import pet
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pet_cmd.json'
            p = self.shell(path)
            real_stat = os.stat
            stats = []
            with patch.object(pet.os, 'stat', side_effect=lambda f: stats.append(f) or real_stat(f)):
                p._pump()                                          # no file yet
                path.write_text('{"op": "a"}', encoding='utf-8')
                os.utime(path, (1000.0, 1000.0))
                p._pump()
                path.write_text('{"op": "b"}', encoding='utf-8')
                os.utime(path, (1000.5, 1000.5))
                p._pump()
                p._pump()                                          # unchanged: nothing run
            self.assertEqual([c[0][0] for c in p._exec_cmd.call_args_list], [{'op': 'a'}, {'op': 'b'}])
            self.assertEqual(len(stats), 4)                        # one stat per poll

    def test_a_half_written_command_is_retried_every_frame(self):
        import pet
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pet_cmd.json'
            path.write_text('', encoding='utf-8')
            p = self.shell(path)
            p._pump()
            path.write_text('{"op": "pet"}', encoding='utf-8')
            os_mt = path.stat().st_mtime
            p._pump()
            self.assertEqual(p._exec_cmd.call_count, 1)
            self.assertEqual(p._cmd_seen, os_mt)


if __name__ == '__main__':
    unittest.main()
