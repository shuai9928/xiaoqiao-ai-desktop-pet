"""I-52: the native session sync writes each session file once per tick, only when it changed.

A Codex sub-agent rollout repeats its parent's session_meta on line 2, so it publishes under the
parent's id. The old loop wrote once per reader: with 2-4 readers on one id it rewrote that file
every 2 s and always ended on the same bytes. These checks pin the fix and compare every tick with
a frozen copy of the old loop: same files, same bytes, same reader state (isolated temp data).
"""
import datetime
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import native_session_sync
from ai_lights_core import write_json
from native_session_sync import NativeSessions, stamp

NOW = stamp('2026-10-06T04:00:00Z')
PARENT = '01a10eb1-e360-7890-862a-b63085b2dde5'
KIDS = ('01a11f83-e3db-7c01-b765-5b8cdcb1d9bc', '01a11f87-6e49-7d62-a0e4-12b9f7925fbb',
        '01a12999-0000-7000-8000-000000000001')


class OldSessions(NativeSessions):
    """Frozen copy of the tick before I-52 (one write per reader, metadata read per Claude reader)."""

    def tick(self, now=None):
        now = time.time() if now is None else now
        if now - self.last_discovery >= 10:
            self.last_discovery = now
            for folder, pattern, agent in (
                    (self.home / '.codex' / 'sessions', '*/*/*/*.jsonl', 'native-codex'),
                    (self.home / '.claude' / 'projects', '*/*.jsonl', 'native-claude')):
                candidates = []
                for path in folder.glob(pattern):
                    try:
                        modified = path.stat().st_mtime
                        if now - modified < 7 * 86400:
                            candidates.append((modified, path))
                    except OSError:
                        pass
                for _, path in sorted(candidates, reverse=True)[:24]:
                    self.readers.setdefault(path, native_session_sync.Transcript(path, agent))
        self.dest.mkdir(parents=True, exist_ok=True)
        for reader in list(self.readers.values()):
            try:
                reader.poll()
                if reader.agent == 'native-claude':
                    for path in (self.home / '.claude' / 'sessions').glob('*.json'):
                        try:
                            metadata = json.loads(path.read_text(encoding='utf-8'))
                        except (OSError, ValueError):
                            continue
                        if not isinstance(metadata, dict):
                            continue
                        if metadata.get('sessionId') != reader.sid:
                            continue
                        when = float(metadata.get('statusUpdatedAt') or 0) / 1000
                        status = metadata.get('status')
                        if when >= reader.updated and status in ('idle', 'running', 'waiting'):
                            reader.state_at(status, when)
                            if not reader.actions:
                                reader.action('等待新任务' if status == 'idle' else '正在处理任务', when)
                data = reader.snapshot(now)
                if not data['actions']:
                    continue
                serialized = json.dumps(data, ensure_ascii=False)
                if self.saved.get(data['id']) != serialized:
                    native_session_sync.write_json(str(self.dest / (data['id'] + '.json')), data)
                    self.saved[data['id']] = serialized
                if len(reader.calls) > 128:
                    reader.calls = dict(list(reader.calls.items())[-64:])
            except (OSError, ValueError, TypeError):
                continue


def iso(seconds):
    return datetime.datetime.fromtimestamp(NOW + seconds, datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def line(**row):
    return (json.dumps(row) + '\n').encode()


def meta(sid, parent=None, at=0):
    payload = {'id': sid, 'source': 'vscode'}
    if parent:
        payload.update(forked_from_id=parent, source={'subagent': {'thread_spawn': {'parent_thread_id': parent}}})
    return line(type='session_meta', timestamp=iso(at), payload=payload)


def call(name, at, cid='c'):
    return line(type='response_item', timestamp=iso(at), payload={
        'type': 'function_call', 'name': name, 'arguments': '{}', 'call_id': cid})


def started(at):
    return line(type='event_msg', timestamp=iso(at), payload={'type': 'task_started'})


def tool_uses(lo, hi, at):
    return b''.join(line(type='assistant', timestamp=iso(at), message={'content': [
        {'type': 'tool_use', 'id': 's%d' % n, 'name': 'Read', 'input': {'file_path': 'x%d.py' % n}}]})
        for n in range(lo, hi))


def tool_result(n, at):
    return line(type='user', timestamp=iso(at), message={'content': [
        {'type': 'tool_result', 'tool_use_id': 's%d' % n, 'is_error': False}]})


def rollout(home, sid, data, age):
    path = home / '.codex' / 'sessions' / '2026' / '10' / '06' / ('rollout-2026-10-06T04-00-00-' + sid + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (NOW - age, NOW - age))   # discovery order = newest first; the oldest reader lands last
    return path


def claude(home, sid, data, age):
    path = home / '.claude' / 'projects' / 'proj' / (sid + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (NOW - age, NOW - age))
    return path


def append(path, data):
    with open(path, 'ab') as f:
        f.write(data)


def files(folder):
    return {p.name: p.read_bytes() for p in Path(folder).glob('*')}


def reader_state(sync):
    return ([(str(p), r.sid, r.state, r.since, r.updated, r.actions, r.offset, r.pending, list(r.calls.items()))
             for p, r in sync.readers.items()], sorted(sync.saved.items()))


class NativeSyncWritesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'home'
        self.out = Path(tmp.name) / 'out'
        self.writes, self.locked = [], set()
        def fake_write(path, data):
            self.writes.append(Path(path))
            if Path(path).name in self.locked:     # what write_json raises when its retries run out
                raise PermissionError(13, 'sharing violation', path)
            write_json(path, data)
        patcher = mock.patch.object(native_session_sync, 'write_json', side_effect=fake_write)
        patcher.start()
        self.addCleanup(patcher.stop)

    def family(self):
        """A parent rollout and two real-shaped sub-agent rollouts, all publishing the parent's id."""
        rollout(self.home, PARENT, started(0) + call('shell', 1), age=10)
        rollout(self.home, KIDS[0], meta(KIDS[0], PARENT) + meta(PARENT) + call('apply_patch', 2), age=20)
        return rollout(self.home, KIDS[1], meta(KIDS[1], PARENT) + meta(PARENT) + started(3) + call('view_image', 4), age=30)

    def test_shared_parent_id_written_once_per_tick_and_not_rewritten(self):
        self.family()
        sync = NativeSessions(self.home, self.out)
        sync.tick(NOW + 5)
        target = self.out / ('native-codex-' + PARENT + '.json')
        self.assertEqual(self.writes, [target])           # was: one write per reader (3)
        old = OldSessions(self.home, self.out.with_name('old'))
        old.tick(NOW + 5)
        self.assertEqual(files(self.out), files(old.dest))
        self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['actions'][0]['a'],
                         old.readers[next(reversed(old.readers))].actions[0]['a'])   # the last reader still wins
        for step in (7, 9, 11):                           # no growth: nothing to write
            self.writes.clear()
            sync.tick(NOW + step)
            self.assertEqual(self.writes, [])

    def test_claude_session_metadata_read_once_per_tick(self):
        for n in range(3):
            claude(self.home, 'sid%d' % n, tool_uses(n, n + 1, n), age=n)
        sessions = self.home / '.claude' / 'sessions'
        sessions.mkdir(parents=True)
        (sessions / '1.json').write_text(json.dumps({'sessionId': 'sid1', 'status': 'idle',
                                                     'statusUpdatedAt': (NOW + 9) * 1000}))
        (sessions / '2.json').write_text('{bad')
        reads = []
        real = Path.read_text
        def counting(path, *args, **kwargs):
            if path.parent == sessions:
                reads.append(path.name)
            return real(path, *args, **kwargs)
        sync = NativeSessions(self.home, self.out)
        with mock.patch.object(Path, 'read_text', counting):
            sync.tick(NOW + 10)
        self.assertEqual(sorted(reads), ['1.json', '2.json'])   # was: once per Claude reader (6)
        old = OldSessions(self.home, self.out.with_name('old'))
        old.tick(NOW + 10)
        self.assertEqual(files(self.out), files(old.dest))
        self.assertEqual(json.loads((self.out / 'native-claude-sid1.json').read_text(encoding='utf-8'))['state'], 'idle')

    def test_failed_write_keeps_calls_and_retries_next_tick(self):
        big = claude(self.home, 'big', tool_uses(0, 140, 0), age=0)
        name = 'native-claude-big.json'
        sync = NativeSessions(self.home, self.out)
        self.locked = {name}
        sync.tick(NOW + 1)
        self.assertFalse((self.out / name).exists())
        reader = sync.readers[big]
        self.assertEqual(len(reader.calls), 140)          # the old loop kept them when its write failed
        append(big, tool_result(3, 2))
        self.locked = set()
        sync.tick(NOW + 3)
        data = json.loads((self.out / name).read_text(encoding='utf-8'))
        self.assertEqual((data['actions'][0]['a'], data['actions'][0]['r']), ('读 x3.py', '已返回'))
        self.assertEqual(len(reader.calls), 64)

    def test_every_tick_matches_the_old_loop_byte_for_byte(self):
        kid = self.family()
        rollout(self.home, '01a0ffff-0000-7000-8000-00000000000a', meta('01a0ffff-0000-7000-8000-00000000000a')
                + line(type='response_item', timestamp=iso(1), payload={'type': 'reasoning'}), age=5)  # never any actions
        big = claude(self.home, 'big', tool_uses(0, 140, 0), age=1)
        other = claude(self.home, 'other', tool_uses(500, 501, 0), age=2)
        sessions = self.home / '.claude' / 'sessions'
        sessions.mkdir(parents=True)
        new = self.home / '.codex' / 'sessions' / '2026' / '10' / '06' / ('rollout-2026-10-06T05-00-00-' + KIDS[2] + '.jsonl')
        half = call('spawn_agent', 30, 'k')
        steps = {   # after tick i: change the inputs; locked = dest files whose writes fail during tick i
            0: lambda: append(big, tool_result(3, 1)),
            1: lambda: (append(kid, call('shell', 12, 'k2')), append(big, tool_uses(140, 210, 2))),
            2: lambda: (append(big, tool_result(80, 3) + tool_result(20, 4)), append(kid, half[:17])),
            3: lambda: (append(kid, half[17:]), new.write_bytes(meta(KIDS[2], PARENT) + meta(PARENT))),
            5: lambda: append(new, started(40) + call('shell', 41)),
            6: lambda: ((sessions / 'a.json').write_text(json.dumps({'sessionId': 'big', 'status': 'idle',
                                                                       'statusUpdatedAt': (NOW + 50) * 1000})),
                        (sessions / 'b.json').write_text(json.dumps({'sessionId': 'other', 'status': 'idle',
                                                                       'statusUpdatedAt': 'not-a-number'}))),
            7: lambda: ((sessions / 'b.json').unlink(), kid.unlink()),
        }
        locks = {0: {'native-claude-big.json'}, 1: {'native-codex-' + PARENT + '.json'},
                 2: {'native-claude-big.json', 'native-codex-' + PARENT + '.json'}, 6: {'native-claude-big.json'}}
        sync = NativeSessions(self.home, self.out)
        old = OldSessions(self.home, self.out.with_name('old'))
        for i in range(12):
            self.locked = locks.get(i, set())
            self.writes.clear()
            sync.tick(NOW + 10 + 2 * i)
            new_writes = len(self.writes)
            old.tick(NOW + 10 + 2 * i)
            self.assertEqual(files(self.out), files(old.dest), 'tick %d' % i)
            self.assertEqual(reader_state(sync), reader_state(old), 'tick %d' % i)
            if i >= 9:
                self.assertEqual(new_writes, 0, 'tick %d' % i)
            steps.get(i, lambda: None)()
        last = json.loads((self.out / ('native-codex-' + PARENT + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(last['actions'][0]['a'], native_session_sync.action_label('shell', {}))   # newest rollout wins
        self.assertIn(('读 x80.py', '已返回'), [(a.get('a'), a.get('r')) for a in sync.readers[big].actions])


if __name__ == '__main__':
    unittest.main()
