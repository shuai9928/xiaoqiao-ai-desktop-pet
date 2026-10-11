"""I-52: the panel key survives a new scan list that holds the very same session dicts.

The scan builds a new list every 2 s; when every dict in it is the same object as
before, the full repr of all sessions must not run in that tick. Everything else
keeps its old meaning: a changed dict changes the key at once, and a full repr
still runs at least every PANEL_RECHECK seconds. Synthetic data only.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import flat_workspace as f


QUOTA = {'fh': 10}         # one sample object, as between two quota reads


def ui_with(sessions, **extra):
    ui = dict(sessions=sessions, sel_session=sessions[0] if sessions else None, quota=QUOTA,
              codex_quota=None, codex_quota_error=False, mock=False, quota_widget=[{'name': 'Claude'}],
              flat_agent='Claude', panel_alpha=232)
    ui.update(extra)
    return ui


class Tagged(list):
    """A list whose repr differs from a plain list holding the same items."""

    def __repr__(self):
        return 'Tagged' + list.__repr__(self)


def full(ui):
    return repr(tuple(ui.get(n) for n in f.PANEL_DATA))


class PanelKeyMemoTests(unittest.TestCase):
    def setUp(self):
        self.owner = SimpleNamespace()
        self.sessions = [dict(id=f's{i}', agent='native-claude', state='running', actions=[{'a': f'读 {i}'}])
                         for i in range(5)]
        self.clock = [100.0]
        patcher = patch.object(f.time, 'monotonic', lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def key(self, ui):
        """panel_data_key, and whether it ran the full repr of the data tuple."""
        calls, real = [], repr
        with patch('builtins.repr', side_effect=lambda v: calls.append(type(v)) or real(v)):
            key = f.panel_data_key(self.owner, ui)
        return key, tuple in calls

    def test_a_new_list_of_the_same_dicts_skips_the_full_repr(self):
        ui = ui_with(self.sessions)
        first, ran = self.key(ui)
        self.assertTrue(ran)
        self.clock[0] += .5
        rescanned = list(self.sessions)
        again, ran = self.key(ui_with(rescanned, sel_session=ui['sel_session']))
        self.assertFalse(ran)
        self.assertIs(again, first)
        self.assertEqual(again, full(ui_with(rescanned, sel_session=ui['sel_session'])))
        self.assertIs(self.owner._flat_key_memo[3][0], rescanned)          # adopted: the next frame is the plain hit
        self.assertEqual(self.key(ui_with(rescanned, sel_session=ui['sel_session'])), (first, False))

    def test_a_new_dict_or_a_different_list_shape_changes_the_key_at_once(self):
        ui = ui_with(self.sessions)
        first, _ = self.key(ui)
        sel = ui['sel_session']
        for name, sessions in (('one dict replaced', self.sessions[:2] + [dict(self.sessions[2], state='done')]
                                + self.sessions[3:]),
                               ('reordered', self.sessions[::-1]), ('shorter', self.sessions[:-1]),
                               ('longer', self.sessions + [dict(id='new')]), ('tuple', tuple(self.sessions)),
                               ('list subclass', Tagged(self.sessions))):
            with self.subTest(name):
                new = ui_with(sessions, sel_session=sel)
                key, ran = self.key(new)
                self.assertTrue(ran)
                self.assertEqual(key, full(new))
                self.assertNotEqual(key, first)
                self.key(ui)                                               # back to the original list

    def test_other_inputs_still_change_the_key_with_a_rescanned_list(self):
        ui = ui_with(self.sessions)
        first, _ = self.key(ui)
        rescanned = list(self.sessions)
        for name, change in (('selection', dict(sel_session=self.sessions[1])), ('quota', dict(quota={'fh': 10})),
                             ('codex quota', dict(codex_quota={'cycles': []})), ('error', dict(codex_quota_error=True)),
                             ('mock', dict(mock=True)), ('widget', dict(quota_widget=[{'name': 'Codex'}])),
                             ('agent', dict(flat_agent='Codex')), ('alpha', dict(panel_alpha=248))):
            with self.subTest(name):
                new = ui_with(rescanned, **dict(dict(sel_session=ui['sel_session']), **change))
                key, ran = self.key(new)
                self.assertTrue(ran)
                self.assertEqual(key, full(new))
                self.key(ui)

    def test_adopting_a_list_keeps_the_recheck_clock(self):
        ui = ui_with(self.sessions)
        sel = ui['sel_session']
        first, _ = self.key(ui)                                            # full repr at t=100
        self.clock[0] = 100.5
        rescanned = list(self.sessions)
        self.assertEqual(self.key(ui_with(rescanned, sel_session=sel)), (first, False))
        self.sessions[3]['state'] = 'error'                                # edited in place, same objects
        self.clock[0] = 100.0 + f.PANEL_RECHECK - .01
        self.assertEqual(self.key(ui_with(rescanned, sel_session=sel)), (first, False))
        self.clock[0] = 100.0 + f.PANEL_RECHECK
        key, ran = self.key(ui_with(rescanned, sel_session=sel))
        self.assertTrue(ran)
        self.assertNotEqual(key, first)
        self.assertEqual(key, full(ui_with(rescanned, sel_session=sel)))

    def test_a_full_repr_still_runs_every_recheck_period_under_steady_rescans(self):
        sel = self.sessions[0]
        runs = []
        for step in range(40):                                             # a new list every frame-ish tick
            self.clock[0] = 100.0 + step * .25
            key, ran = self.key(ui_with(list(self.sessions), sel_session=sel))
            if ran:
                runs.append(self.clock[0])
        gaps = [b - a for a, b in zip(runs, runs[1:])]
        self.assertGreaterEqual(len(runs), 9)
        self.assertTrue(all(gap <= f.PANEL_RECHECK for gap in gaps), gaps)


if __name__ == '__main__':
    unittest.main()
