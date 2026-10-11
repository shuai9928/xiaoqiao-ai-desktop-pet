"""scan_ai_sessions 增量缓存回归(I-52):输出必须和改动前的全量读逐字一致。

改动前的函数原样冻结在本文件(_old_scan),每扫一次都拿两边的 repr 比。另外钉住
缓存的约定:没变的文件不再打开、返回上轮同一个 dict;内容或 stale 判定一变给新
对象、旧对象不被改;外层列表每次是新的;1ms 内同尺寸重写(mtime/size 都不变)
照样读到;time.time 被钉在 10000 时一律重读;两个目录的同名文件互不串;
被占用读不出来的文件不进缓存;删掉的文件/目录不留旧账。全用临时目录。
"""
import builtins
import json
import os
import random
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import pet


def _old_scan(dir_path, cap=pet.AI_SESSION_CAP, now=None):
    """改动前的 pet.scan_ai_sessions,一字不改(只把模块常量写成 pet.xxx)。"""
    now = time.time() if now is None else now
    try:
        names = os.listdir(dir_path)
    except OSError:
        return []
    out = []
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(dir_path, n), "r", encoding="utf-8") as f:
                s = json.load(f)
            if not isinstance(s, dict):
                continue
            raw_acts = s.get("actions")
            norm = []
            for a in (raw_acts if isinstance(raw_acts, list) else []):
                if isinstance(a, dict):
                    if a.get("turn"):
                        norm.append({"turn": 1, "t": float(a.get("t") or 0)})
                    elif a.get("a"):
                        norm.append({"t": float(a.get("t") or 0),
                                     "a": str(a.get("a")),
                                     "r": str(a.get("r")) if a.get("r") else "",
                                     "err": 1 if a.get("err") else 0})
                elif isinstance(a, str) and a:
                    norm.append({"a": str(a)})     # 旧格式兼容
            acts = norm
            state = s.get("state") if s.get("state") in pet.AI_SESSION_STATES else "idle"
            stale = bool(s.get("stale")) or (
                s.get("source") == "mac"
                and now - float(s.get("syncedAt") or s.get("updated") or 0) > pet.AI_MAC_SYNC_STALE)
            out.append({"id": str(s.get("id") or n[:-5]),
                        "agent": str(s.get("agent", "?")),
                        "state": "idle" if stale else state,
                        "title": str(s.get("title", ""))[:40],
                        "updated": float(s.get("updated", 0) or 0),
                        "since": float(s.get("since", 0) or 0),
                        "stale": stale,
                        "actions": acts[:48]})
        except Exception:
            continue
    out.sort(key=lambda s: -s["updated"])
    return out[:cap]


def write(path, data, mtime_ns=None, replace=False):
    """写一个文件(str 按 utf-8;bytes 原样);replace=True 走 tmp+os.replace(和 write_json 一样)。
    mtime_ns 给了就把 mtime 改成它:模拟「很久以前写的」或「同一个时钟刻里又写了一次」。"""
    target = path + ".%d.tmp" % random.randrange(10 ** 9) if replace else path
    if isinstance(data, bytes):
        with open(target, "wb") as f:
            f.write(data)
    else:
        with open(target, "w", encoding="utf-8") as f:
            f.write(data)
    if replace:
        os.replace(target, path)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))


def session(sid, **kw):
    s = {"id": sid, "agent": "zcode", "state": "running", "title": "t-" + sid,
         "updated": 1_000.0, "actions": [{"t": 1.0, "a": "读 a.py", "r": "ok"}]}
    s.update(kw)
    return json.dumps(s, ensure_ascii=False)


class Opens:
    """数 pet 里打开了哪些文件;fail 里的文件名抛 PermissionError(冻结的旧函数也看到同样的失败,但不计数)。"""

    def __init__(self, fail=()):
        self.names = []
        self.fail = set(fail)

    def _open(self, path, *a, **k):
        if os.path.basename(path) in self.fail:
            raise PermissionError(13, "被别的进程占着", path)
        return builtins.open(path, *a, **k)

    def __call__(self, path, *a, **k):
        self.names.append(os.path.basename(path))
        return self._open(path, *a, **k)

    def __enter__(self):
        self._patches = [patch("pet.open", self, create=True),
                         patch(__name__ + ".open", self._open, create=True)]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()


class ScanCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xq-scan-cache-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.seen = {}                  # id(obj) -> (obj, 第一次返回时的 repr)
        self.t0 = time.time()
        self.aged = 0

    def aged_ns(self):
        """一个远早于现在、且每次都不同的 mtime:真实的每次写入 mtime 都是新的。"""
        self.aged += 1
        return int((self.t0 - 5000) * 1e9) - self.aged * 1_000_003

    def folder(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        return d

    def scan(self, d, cap=None, now=None):
        """新旧各扫一遍,repr 必须一模一样;记下返回过的对象,之后不许被改。"""
        got = pet.scan_ai_sessions(d, cap=cap, now=now)
        want = _old_scan(d, cap=cap, now=now)
        self.assertEqual(repr(got), repr(want))
        self.assertEqual(got, want)
        for s in got:
            for o in (s, s["actions"], *s["actions"]):
                self.seen.setdefault(id(o), (o, repr(o)))
        return got

    def assert_untouched(self):
        for o, r in self.seen.values():
            self.assertEqual(repr(o), r)

    def assert_identity(self, prev, got, written=()):
        """同一个文件:和上轮内容一样 → 同一个对象;不一样 → 全新的 dict/actions/动作 dict。
        written:上轮之后被写过的 id —— 文件真改了但输出碰巧一样(比如 stale 盖住了 state),给新对象也对。"""
        before = {s["id"]: s for s in prev}
        for s in got:
            o = before.get(s["id"])
            if o is None:
                continue
            if repr(s) == repr(o):
                if s["id"] not in written:
                    self.assertIs(s, o)
            else:
                self.assertIsNot(s, o)
                self.assertIsNot(s["actions"], o["actions"])
                old_ids = {id(a) for a in o["actions"]}
                self.assertFalse([a for a in s["actions"] if id(a) in old_ids])


class EquivalenceTests(ScanCase):
    def test_scripted_sequence_matches_the_old_scan(self):
        d = self.folder("a")
        t = self.t0
        p = lambda n: os.path.join(d, n)
        write(p("s1.json"), session("s1", updated=t - 10), self.aged_ns())
        write(p("s2.json"), session("s2", updated=t - 20, actions=[
            "old string", "", 5, None, {"turn": 1, "t": "3"}, {"a": "x", "r": 0, "err": "yes", "t": None},
            {"a": ""}, {"t": 1}, *[{"t": i, "a": "a%d" % i, "r": "ok"} for i in range(60)]]),
            self.aged_ns(), replace=True)
        write(p("s3.json"), session("s3", updated=t - 10, state="bogus", title="T" * 90, since="12.5"),
              self.aged_ns())
        write(p("noid.json"), json.dumps({"agent": "native-codex", "updated": t - 5}), self.aged_ns())
        write(p("mac-a.json"), session("mac-a", agent="mac-claude", source="mac", updated=t - 100,
                                       syncedAt=t - 700), self.aged_ns())
        write(p("mac-b.json"), session("mac-b", agent="mac-codex", source="mac", state="waiting",
                                       updated=t - 650), self.aged_ns())
        write(p("mac-c.json"), session("mac-c", source="mac", syncedAt="garbage"), self.aged_ns())
        write(p("mac-d.json"), session("mac-d", source="mac", syncedAt="garbage", stale=True), self.aged_ns())
        write(p("bad-t.json"), session("bad-t", actions=[{"t": "abc", "a": "x"}]), self.aged_ns())
        write(p("bad-since.json"), session("bad-since", since="x"), self.aged_ns())
        write(p("list.json"), "[1, 2, 3]", self.aged_ns())
        write(p("trunc.json"), '{"id": "trunc", "agent": ', self.aged_ns())
        write(p("bom.json"), b"\xef\xbb\xbf" + session("bom").encode(), self.aged_ns())
        write(p("badutf8.json"), b'{"id": "\xff\xfe", "updated": 2}', self.aged_ns())
        write(p("bigint.json"), '{"id": "big", "source": "mac", "syncedAt": 1%s}' % ("0" * 400),
              self.aged_ns())
        write(p("note.txt"), "{}")
        write(p("a.json.1.tmp"), "{}")
        os.mkdir(p("dir.json"))
        prev = []
        def step(now, cap=None):
            nonlocal prev
            got = self.scan(d, cap=cap, now=now)
            self.assert_identity(prev, got)
            prev = got
            return got
        for cap in (None, None, 5, 0, 2, None):
            step(t, cap)
        # 追加一条动作(真写:新的 mtime)
        write(p("s1.json"), session("s1", updated=t - 1, actions=[
            {"t": t, "a": "改 b.py"}, {"t": 1.0, "a": "读 a.py", "r": "ok"}]), self.aged_ns(), replace=True)
        step(t)
        # 同尺寸、同一个时钟刻里重写:mtime 和 size 都不变,仍然要读到
        write(p("s1.json"), session("s1", updated=t))
        st = os.stat(p("s1.json"))
        step(t)
        write(p("s1.json"), session("s1", updated=t).replace('"running"', '"waiting"'),
              st.st_mtime_ns, replace=True)
        st2 = os.stat(p("s1.json"))
        self.assertEqual((st2.st_mtime_ns, st2.st_size), (st.st_mtime_ns, st.st_size))
        self.assertEqual([s["state"] for s in step(t) if s["id"] == "s1"], ["waiting"])
        # 删、加、坏掉、修好、变成不是 dict
        os.remove(p("s3.json"))
        step(t)
        write(p("new.json"), session("new", updated=t + 5), self.aged_ns())
        step(t, 5)
        write(p("new.json"), '{"id": "new", "agent": ', self.aged_ns())
        step(t)
        step(t)
        write(p("new.json"), session("new", state="done", updated=t + 6), self.aged_ns())
        step(t)
        write(p("new.json"), "[1, 2]", self.aged_ns())
        step(t)
        write(p("new.json"), session("new", state="error", updated=t + 7), self.aged_ns())
        # Mac 判熄跟着 now 走,来回穿过 720 秒
        for dt in (0, 19, 21, 50, 21, 19, -10, 600, 721, 5000, -5000, 0, 0):
            step(t + dt)
        # 奇怪的 now:Mac 文件(没标 stale 的)在旧代码里会抛进 per-file try 被跳过
        step("x")
        step(t)
        # 被删掉又补回来、整个目录没了
        os.remove(p("s2.json"))
        step(t)
        shutil.rmtree(d)
        self.assertEqual(step(t), [])
        self.assert_untouched()

    def test_randomized_sequences_match_the_old_scan(self):
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                self._fuzz(random.Random(seed), os.path.join(self.tmp, "fuzz%d" % seed), 300)
        self.assert_untouched()

    def _fuzz(self, rng, root, steps):
        base = self.t0
        dirs = [os.path.join(root, "A"), os.path.join(root, "B")]
        for d in dirs:
            os.makedirs(d)
        names = ["s%d.json" % i for i in range(6)] + ["mac0.json", "mac1.json", "odd.json", "note.txt"]
        labels = ["读 a.py", "改 b.py", "跑测试 pytest", "搜索 foo", "命令 git", "问你问题"]
        fresh = {}                      # path -> 最近一次「没改 mtime 的真写」的时刻
        written = {d: set() for d in dirs}  # 上次扫这个目录之后写过/删过的文件(按 id)
        swap = {"done": "idle", "idle": "done", "running": "waiting", "waiting": "running"}

        def put(path, text):
            written[os.path.dirname(path)].add(os.path.basename(path)[:-5])
            replace = rng.random() < .5
            if rng.random() < .6:
                write(path, text, self.aged_ns(), replace=replace)
                fresh.pop(path, None)
            else:
                write(path, text, replace=replace)
                fresh[path] = time.time()

        def make(n):
            acts = []
            for i in range(rng.randrange(0, 60)):
                r = rng.random()
                if r < .7:
                    acts.append({"t": base - i, "a": rng.choice(labels), "r": rng.choice(["", "ok"]),
                                 "err": rng.random() < .1})
                elif r < .8:
                    acts.append({"turn": 1, "t": base - i})
                elif r < .9:
                    acts.append(rng.choice(["old string", "", 5, None, {"t": 1}]))
                elif r < .91:
                    acts.append({"t": "abc", "a": "x"})          # 整个文件被跳过
            s = {"id": n[:-5], "agent": rng.choice(["zcode", "mac-claude", "native-codex"]),
                 "state": rng.choice(["running", "waiting", "done", "idle", "error", "bogus"]),
                 "title": rng.choice(["", "fix bug", "T" * 50]), "updated": base - rng.randrange(0, 3000),
                 "actions": acts}
            if rng.random() < .3:
                del s["id"]                                     # 退回用文件名
            if n.startswith("mac"):
                s["source"] = "mac"
                s["syncedAt"] = rng.choice([base, base - 100, base - 700, base - 719, base - 721,
                                            base - 1500, "garbage", None])
                if rng.random() < .2:
                    s["stale"] = True
            if rng.random() < .05:
                s["since"] = "x"
            return s

        offset = 0.0
        prev = {d: [] for d in dirs}
        for _ in range(steps):
            d = rng.choice(dirs)
            path = os.path.join(d, rng.choice(names))
            op = rng.random()
            if op < .35:
                put(path, json.dumps(make(os.path.basename(path)), ensure_ascii=False))
            elif op < .45:                                       # 追加动作
                try:
                    with open(path, encoding="utf-8") as f:
                        s = json.load(f)
                except (OSError, ValueError):
                    s = None
                if isinstance(s, dict):
                    s["actions"] = ([{"t": base + offset, "a": rng.choice(labels)}]
                                    + (s.get("actions") if isinstance(s.get("actions"), list) else []))[:48]
                    put(path, json.dumps(s, ensure_ascii=False))
            elif op < .55:
                # 同一个时钟刻里的同尺寸重写:mtime/size 原样,只能发生在刚写过的文件上
                s = None
                if path in fresh and time.time() - fresh[path] < 1.0:
                    with open(path, "rb") as f:
                        raw = f.read()
                    try:
                        s = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        pass
                if isinstance(s, dict) and s.get("state") in swap:
                    s["state"] = swap[s["state"]]
                    raw2 = json.dumps(s, ensure_ascii=False).encode("utf-8")
                    if len(raw2) == len(raw) and raw2 != raw:
                        written[d].add(os.path.basename(path)[:-5])
                        st = os.stat(path)
                        write(path, raw2, st.st_mtime_ns, replace=rng.random() < .5)
            elif op < .62:
                if os.path.isfile(path):
                    os.remove(path)
                    fresh.pop(path, None)
                    written[d].add(os.path.basename(path)[:-5])
            elif op < .70:
                put(path, rng.choice(['{"id": ', "[1, 2]", "null", '"str"', "{}", '{"updated": "x"}',
                                      '{"actions": {"not": "a list"}, "updated": null}']))
            elif op < .80:
                offset += rng.choice([-900, -721, -30, 0, 15, 300, 719, 721, 1500])
            got = self.scan(d, cap=rng.choice([None, None, 5, 2, 0]), now=base + offset)
            self.assert_identity(prev[d], got, written[d])
            prev[d], written[d] = got, set()

    def test_missing_dir_default_cap_and_path_objects(self):
        from pathlib import Path
        self.assertEqual(self.scan(os.path.join(self.tmp, "no", "such")), [])
        d = self.folder("cap")
        for i in range(8):
            write(os.path.join(d, "s%d.json" % i), session("s%d" % i, updated=self.t0 - i), self.aged_ns())
        with patch("pet.time.time", return_value=self.t0):
            got = pet.scan_ai_sessions(d)
            self.assertEqual(repr(got), repr(_old_scan(d)))
            self.assertEqual(len(got), pet.AI_SESSION_CAP)
            self.assertEqual(repr(pet.scan_ai_sessions(Path(d), cap=None)), repr(_old_scan(Path(d), cap=None)))


class CacheContractTests(ScanCase):
    def test_unchanged_files_are_not_reopened_and_keep_their_dicts(self):
        d = self.folder("steady")
        for i in range(6):
            write(os.path.join(d, "s%d.json" % i), session("s%d" % i, updated=self.t0 - i), self.aged_ns())
        with Opens() as opens:
            first = self.scan(d, now=self.t0)
        self.assertEqual(sorted(n for n in opens.names if n.startswith("s")),
                         ["s%d.json" % i for i in range(6)])
        with Opens() as opens:
            got = pet.scan_ai_sessions(d, cap=None, now=self.t0)
        self.assertEqual(opens.names, [])                          # 稳态:一个文件都不打开
        self.assertIsNot(got, first)                               # 外层列表每次都是新的
        self.assertEqual([id(s) for s in got], [id(s) for s in first])
        self.assertIs(got[0]["actions"], first[0]["actions"])
        first.clear()                                              # 调用方改自己的列表不影响下一轮
        self.assertEqual(len(pet.scan_ai_sessions(d, cap=None, now=self.t0)), 6)
        before = repr(got[2])
        write(os.path.join(d, "s2.json"), session("s2", updated=self.t0 - 2, state="done"), self.aged_ns(),
              replace=True)
        with Opens() as opens:
            again = self.scan(d, now=self.t0)
        self.assertEqual(opens.names, ["s2.json"])
        self.assertEqual(repr(got[2]), before)                     # 旧对象没被改
        self.assertIsNot(again[2], got[2])
        self.assertEqual(again[2]["state"], "done")
        self.assertEqual([again[i] is got[i] for i in range(6)], [True, True, False, True, True, True])

    def test_same_size_rewrite_within_one_tick_is_seen(self):
        d = self.folder("racy")
        path = os.path.join(d, "s.json")
        write(path, session("s", state="running"))
        st = os.stat(path)
        with Opens() as opens:
            self.assertEqual(self.scan(d, now=self.t0)[0]["state"], "running")
            self.scan(d, now=self.t0)
        self.assertEqual(opens.names, ["s.json", "s.json"])        # 刚写的文件每轮都重读
        write(path, session("s", state="waiting"), st.st_mtime_ns, replace=True)
        st2 = os.stat(path)
        self.assertEqual((st2.st_mtime_ns, st2.st_size), (st.st_mtime_ns, st.st_size))
        self.assertEqual(self.scan(d, now=self.t0)[0]["state"], "waiting")

    def test_clock_pinned_at_10000_always_rereads(self):
        d = self.folder("pinned")
        for i in range(3):
            write(os.path.join(d, "s%d.json" % i), session("s%d" % i, updated=i), self.aged_ns())
        path = os.path.join(d, "s1.json")
        with patch("pet.time.time", return_value=10_000.0):
            first = self.scan(d)
            st = os.stat(path)
            write(path, session("s1", updated=1, state="waiting"), st.st_mtime_ns, replace=True)
            with Opens() as opens:
                got = self.scan(d)
            self.assertEqual(sorted(opens.names), ["s0.json", "s1.json", "s2.json"])
            self.assertEqual({s["id"]: s["state"] for s in got}["s1"], "waiting")
            self.assert_identity(first, got)                       # 重读但没变的照样给同一个 dict
            self.assertIs(got[0], first[0])

    def test_mac_staleness_follows_now_with_a_cached_parse(self):
        d = self.folder("mac")
        t = self.t0
        write(os.path.join(d, "m.json"), session("m", agent="mac-claude", source="mac", state="error",
                                                 updated=t - 100, syncedAt=t - 700,
                                                 actions=[{"t": 1, "a": "x"}, {"turn": 1, "t": 2}]),
              self.aged_ns())
        live = self.scan(d, now=t)[0]
        self.assertEqual((live["state"], live["stale"]), ("error", False))
        with Opens() as opens:
            dead = self.scan(d, now=t + 21)[0]
            dead2 = self.scan(d, now=t + 5000)[0]
            back = self.scan(d, now=t)[0]
            back2 = self.scan(d, now=t + 19)[0]
        self.assertEqual(opens.names, [])
        self.assertEqual((dead["state"], dead["stale"]), ("idle", True))
        self.assertIs(dead2, dead)
        self.assertIsNot(dead, live)
        self.assertIsNot(dead["actions"], live["actions"])
        self.assertFalse({id(a) for a in dead["actions"]} & {id(a) for a in live["actions"]})
        self.assertEqual(back, live)
        self.assertIsNot(back, live)
        self.assertIsNot(back, dead)
        self.assertIs(back2, back)
        self.assertEqual((live["state"], live["stale"]), ("error", False))      # 旧对象没被改
        # 文件真改了、只是被 stale 盖住看不出来:也给新对象
        write(os.path.join(d, "m.json"), session("m", agent="mac-claude", source="mac", state="done",
                                                 updated=t - 100, syncedAt=t - 700,
                                                 actions=[{"t": 1, "a": "x"}, {"turn": 1, "t": 2}]),
              self.aged_ns(), replace=True)
        masked = self.scan(d, now=t + 21)[0]
        self.assertEqual(masked, dead)
        self.assertIsNot(masked, dead)
        self.assert_untouched()

    def test_two_dirs_with_the_same_file_names_do_not_mix(self):
        a, b = self.folder("A"), self.folder("B")
        ns = self.aged_ns()
        write(os.path.join(a, "s.json"), session("s", state="done"), ns)
        write(os.path.join(b, "s.json"), session("s", state="idle"), ns)
        for _ in range(3):
            with Opens() as opens:
                self.assertEqual(self.scan(a, now=self.t0)[0]["state"], "done")
                self.assertEqual(self.scan(b, now=self.t0)[0]["state"], "idle")
                self.assertEqual(self.scan(a + os.sep, now=self.t0)[0]["state"], "done")
        self.assertEqual(opens.names, [])
        self.assertIsNot(self.scan(a, now=self.t0)[0], self.scan(b, now=self.t0)[0])

    def test_unreadable_file_is_not_cached(self):
        d = self.folder("locked")
        write(os.path.join(d, "a.json"), session("a"), self.aged_ns())
        write(os.path.join(d, "b.json"), session("b"), self.aged_ns())
        with Opens(fail={"a.json"}):
            self.assertEqual([s["id"] for s in self.scan(d, now=self.t0)], ["b"])
        self.assertEqual([s["id"] for s in self.scan(d, now=self.t0)], ["a", "b"])
        with Opens(fail={"a.json"}):                               # 已缓存的不受影响,也不再打开
            self.assertEqual([s["id"] for s in pet.scan_ai_sessions(d, now=self.t0)], ["a", "b"])

    def test_deleted_file_and_dir_are_forgotten(self):
        d = self.folder("gone")
        path = os.path.join(d, "s.json")
        ns = self.aged_ns()
        write(path, session("s", state="done"), ns)
        self.scan(d, now=self.t0)
        os.remove(path)
        self.assertEqual(self.scan(d, now=self.t0), [])
        write(path, session("s", state="idle"), ns)                # 同名、同尺寸、同 mtime,内容不同
        self.assertEqual(self.scan(d, now=self.t0)[0]["state"], "idle")
        shutil.rmtree(d)
        self.assertEqual(self.scan(d, now=self.t0), [])
        os.mkdir(d)
        write(path, session("s", state="done"), ns)
        self.assertEqual(self.scan(d, now=self.t0)[0]["state"], "done")


if __name__ == "__main__":
    unittest.main()
