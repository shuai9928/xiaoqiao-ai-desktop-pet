"""I-52: the frame loop reads ai_sessions/ on a background thread and applies the result on a later frame.

Direct calls (_scan_ai_sessions()) stay synchronous; demo data never touches the disk; a read error retries in 5 s
as before; scan_ai_sessions is safe to call from two threads at once. No window, no user data."""
import json
import os
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import pet


def shell():
    p = pet.Pet.__new__(pet.Pet)
    p.mainq = queue.Queue()
    p._next_ai_scan = 0.0
    p._poll_foreground = Mock()
    p.cmd_path, p._cmd_seen = os.path.join(tempfile.gettempdir(), 'xq-i52-no-such-cmd.json'), 0.0
    p._exec_cmd = Mock()
    return p


def finish(p):
    job = getattr(p, '_ai_scan_job', None)
    if job is not None:
        job[0].join(5)


class BackgroundScanTests(unittest.TestCase):
    def test_read_runs_off_the_main_thread_and_is_applied_on_a_later_frame(self):
        p = shell()
        seen, every = [], [{'id': 'a'}]
        p._scan_ai_sessions = Mock()

        def fake(dir_path, cap=None, now=None):
            seen.append(threading.current_thread().name)
            return every
        with patch.object(pet, 'scan_ai_sessions', side_effect=fake):
            p._pump()
            p._scan_ai_sessions.assert_not_called()          # this frame only started the read
            finish(p)
            p._pump()
        self.assertEqual(seen, ['ai-scan'])
        p._scan_ai_sessions.assert_called_once_with(scanned=every)
        self.assertIsNone(p._ai_scan_job)

    def test_a_slow_read_never_blocks_or_doubles(self):
        p = shell()
        gate, calls = threading.Event(), []
        p._scan_ai_sessions = Mock()

        def slow(dir_path, cap=None, now=None):
            calls.append(1)
            gate.wait(5)
            return []
        with patch.object(pet, 'scan_ai_sessions', side_effect=slow):
            p._pump()
            for _ in range(5):
                t = time.perf_counter()
                p._pump()                                     # still reading: return at once, no second thread
                self.assertLess(time.perf_counter() - t, 0.5)
            p._scan_ai_sessions.assert_not_called()
            gate.set()
            finish(p)
            p._pump()
        self.assertEqual(len(calls), 1)
        p._scan_ai_sessions.assert_called_once_with(scanned=[])

    def test_a_read_error_retries_in_five_seconds(self):
        p = shell()
        p._scan_ai_sessions = Mock()
        with patch.object(pet, 'scan_ai_sessions', side_effect=OSError('locked')):
            p._pump()
            finish(p)
            before = time.time()
            p._pump()
        p._scan_ai_sessions.assert_not_called()
        self.assertIsNone(p._ai_scan_job)
        self.assertGreaterEqual(p._next_ai_scan, before + 4.9)

    def test_demo_data_is_applied_at_once_without_a_thread(self):
        p = shell()
        p._demo_until = time.time() + 60
        p._scan_ai_sessions = Mock()
        with patch.object(pet, 'scan_ai_sessions', side_effect=AssertionError('demo must not read the disk')):
            p._pump()
        p._scan_ai_sessions.assert_called_once_with()
        self.assertIsNone(getattr(p, '_ai_scan_job', None))

    def test_an_applied_result_matches_a_direct_scan(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(pet, 'AI_SESSION_DIR', tmp):
            for i, state in enumerate(('running', 'done', 'waiting')):
                with open(os.path.join(tmp, f's{i}.json'), 'w', encoding='utf-8') as f:
                    json.dump({'id': f's{i}', 'agent': 'zcode', 'state': state, 'updated': time.time() - 10 * i,
                               'actions': [{'t': time.time() - 10 * i, 'a': '读 a.py'}]}, f)

            def run(p):
                p.state, p.ai_lights, p._ai_sessions, p._ai_states = 'idle', True, [], {}
                p._ai_key_last, p._ai_last_say, p.last_interact = {}, 0.0, 0.0
                p._lid, p._lid_mode, p._lid_until, p._lid_pending = 0.0, '', 0.0, None
                p.say, p.hop, p.hearts = Mock(), Mock(), Mock()
                p._spr_disp_h = Mock(return_value=200)
                return p
            direct = run(shell())
            direct._scan_ai_sessions()
            frame = run(shell())
            frame._pump()
            finish(frame)
            frame._pump()
            self.assertEqual(repr(frame._ai_work_sessions), repr(direct._ai_work_sessions))
            self.assertEqual(repr(frame._ai_sessions), repr(direct._ai_sessions))
            self.assertEqual(frame._ai_states, direct._ai_states)
            self.assertEqual(frame._ai_scan_gen, 1)
            self.assertGreater(frame._next_ai_scan, time.time() + 1)


class ScanLockTests(unittest.TestCase):
    def test_two_threads_scanning_one_dir_agree_with_a_fresh_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            def write(i, n):
                with open(os.path.join(tmp, f's{i}.json'), 'w', encoding='utf-8') as f:
                    json.dump({'id': f's{i}', 'agent': 'zcode', 'state': 'running', 'updated': 1000.0 + n,
                               'actions': [{'t': 1000.0 + n, 'a': f'改 f{n}.py'}]}, f)
            for i in range(6):
                write(i, i)
            errors, stop = [], threading.Event()

            def hammer():
                try:
                    while not stop.is_set():
                        pet.scan_ai_sessions(tmp, cap=None, now=2000.0)
                except Exception as exc:          # pragma: no cover - the assertion below reports it
                    errors.append(exc)
            workers = [threading.Thread(target=hammer) for _ in range(2)]
            for w in workers:
                w.start()
            for n in range(40):
                write(n % 6, 10 + n)
            stop.set()
            for w in workers:
                w.join(5)
            self.assertEqual(errors, [])
            pet._AI_SCAN_CACHE.clear()
            fresh = pet.scan_ai_sessions(tmp, cap=None, now=2000.0)
            self.assertEqual(repr(pet.scan_ai_sessions(tmp, cap=None, now=2000.0)), repr(fresh))


if __name__ == '__main__':
    unittest.main()
