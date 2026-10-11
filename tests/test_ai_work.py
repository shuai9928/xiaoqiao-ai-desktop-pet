"""Pure snapshot tests: synthetic actions only, no session files or Pet."""
import math
import unittest
from ai_work import WorkTracker, pose_for_tool, MAX_EVENTS, MAX_SESSIONS


def action(label, t=100, result='', err=0):
    return dict(a=label, t=t, r=result, err=err)


def session(state='running', *, sid='synthetic', agent='native-claude', updated=100,
            actions=None, stale=False, since=100):
    return dict(id=sid, agent=agent, state=state, updated=updated, since=since,
                actions=actions or [], stale=stale)


def kinds(tracker, c='claude'):
    return [e['kind'] for e in tracker.drain(c)]


class TrackerTests(unittest.TestCase):
    def test_first_scan_is_baseline_even_for_failed_completed_work(self):
        t = WorkTracker()
        t.update([session('done', actions=[action('写 x', err=1), {'turn': 1, 't': 99}]),
                  session('error', sid='mac', agent='mac-claude')], 100)
        self.assertEqual(kinds(t), [])
        self.assertIsNone(t.recent_turn(100))
        self.assertIsNone(t.level('claude', 100))

    def test_agent_mapping_has_no_current_or_background_follow_alias(self):
        t = WorkTracker()
        t.update([session(agent='zcode'), session(sid='b', agent='native-codex'),
                  session(sid='c', agent='mac-claude'), session(sid='unknown', agent='random')], 100)
        for c in ('glm', 'codex', 'claude'):
            self.assertEqual(t.level(c, 100), 'thinking')
        for c in ('gemini', 'deepseek', 'current', None, []):
            self.assertIsNone(t.level(c, 100))

    def test_waiting_wins_then_freshest_running_wins(self):
        t = WorkTracker()
        rows = [session(actions=[action('读文件', 99)], updated=99),
                session(sid='new', actions=[action('写 patch', 100)]),
                session('waiting', sid='ask', updated=98)]
        t.update(rows, 100)
        self.assertEqual(t.level('claude', 100), 'asking')
        t.update(rows[:2], 101)
        self.assertEqual(t.level('claude', 101), 'writing')

    def test_chinese_action_mapping_and_delegated_wait(self):
        cases = {'问你问题': 'asking', '委派子智能体 · 颜色': 'delegating',
                 '跟进子智能体': 'delegating', '读网页': 'searching', '搜网页': 'searching',
                 '读 book.py': 'reading', '搜索 code': 'reading', '改 fx': 'writing',
                 '写 file': 'writing', '跑测试 unittest': 'running', '构建 py': 'running',
                 '远程 mac': 'running', '命令 git': 'running', '执行工具': 'running',
                 '等结果': 'running', '调用工具 image_gen': 'drawing'}
        for label, expected in cases.items():
            with self.subTest(label=label):
                t = WorkTracker(); t.update([session(actions=[action(label)])], 100)
                self.assertEqual(t.level('claude', 100), expected)
        t = WorkTracker(); t.update([session(actions=[action('等结果'), action('委派子智能体')])], 100)
        self.assertEqual(t.level('claude', 100), 'delegating')

    def test_upstream_name_priority_and_fallback(self):
        for name, expected in (('request_user_input', 'asking'), ('image_gen', 'drawing'),
                ('view_image', 'reading'), ('read_url_content', 'searching'),
                ('browser_subagent', 'searching'), ('TaskList', 'reading'),
                ('TodoWrite', 'writing'), ('ToolSearch', 'searching'),
                ('TaskOutput', 'delegating'), ('LS', 'running'), (None, 'running')):
            self.assertEqual(pose_for_tool(name), expected)

    def test_empty_result_does_not_finish_a_tool(self):
        t = WorkTracker(); t.update([session(actions=[action('写 code')])], 100)
        self.assertEqual(t.level('claude', 104), 'writing')

    def test_result_already_present_gets_observed_dwell(self):
        t = WorkTracker(); t.update([session(actions=[action('改 code', 99, '完成')])], 100)
        self.assertEqual(t.level('claude', 102.49), 'writing')
        self.assertEqual(t.level('claude', 102.5), 'thinking')

    def test_late_result_after_displayed_dwell_restores_thinking(self):
        t = WorkTracker(); t.update([session(actions=[action('跑测试')])], 100)
        t.update([session(updated=104, actions=[action('跑测试', result='已返回')])], 104)
        self.assertEqual(t.level('claude', 104), 'thinking')

    def test_action_stuck_returns_thinking_but_waiting_stays_asking(self):
        t = WorkTracker(); t.update([session(actions=[action('命令 long')])], 100)
        self.assertEqual(t.level('claude', 190), 'running')
        self.assertEqual(t.level('claude', 190.01), 'thinking')
        t.update([session('waiting', updated=200, actions=[action('问你问题')])], 200)
        self.assertEqual(t.level('claude', 400), 'asking')

    def test_legacy_string_action_ages_from_first_observation(self):
        t = WorkTracker(); t.update([session(agent='mac-codex', actions=['读 code'])], 100)
        self.assertEqual(t.level('codex', 100), 'reading')
        t.update([session(agent='mac-codex', updated=180, actions=['读 code'])], 180)
        self.assertEqual(t.level('codex', 191), 'thinking')
        self.assertEqual(kinds(t, 'codex'), [])

    def test_status_only_and_previous_turn_actions_are_not_counted(self):
        t = WorkTracker()
        rows = [action('收到新任务'), {'turn': 1, 't': 100}, action('写 old', 90)]
        t.update([session(actions=rows)], 100)
        self.assertEqual(t.level('claude', 100), 'thinking')
        t.update([session('done', updated=102, actions=[action('本轮已结束', 102)]+rows)], 102)
        done = next(e for e in t.drain('claude') if e['kind'] == 'done')
        self.assertEqual(done['n_tools'], 0)

    def test_new_turn_only_once_and_local_recent_query(self):
        t = WorkTracker(); t.update([session('idle')], 100)
        row = session(updated=102, actions=[{'turn': 1, 't': 102}])
        t.update([row], 102)
        self.assertEqual(kinds(t), ['activity', 'turn'])
        self.assertEqual(t.recent_turn(132, window=30), 'claude')
        self.assertIsNone(t.recent_turn(132.1))
        t.update([row], 104); self.assertEqual(kinds(t), [])

    def test_fresh_new_nonterminal_session_is_a_turn_and_not_a_finish(self):
        t=WorkTracker();t.update([],100)
        t.update([session(updated=102,actions=[action('读 public',102)])],102)
        self.assertEqual(kinds(t),['activity','turn'])
        self.assertEqual(t.level('claude',102),'reading')

    def test_local_evidence_window_is_inclusive_at_twenty_seconds(self):
        for stamp,expected in ((80,True),(79.999,False)):
            t=WorkTracker();t.update([],100)
            t.update([session('done',updated=stamp)],100)
            self.assertEqual('done' in kinds(t),expected)

    def test_future_and_nonfinite_actions_do_not_refresh_activity_or_fail(self):
        t=WorkTracker();t.update([session(actions=[])],100)
        before=t.last_activity('claude')
        for stamp in (102,float('inf'),float('nan'),True,None):
            t.update([session(updated=101,actions=[action('命令 false',stamp,'失败',1)])],101)
            self.assertEqual(kinds(t),[])
            self.assertEqual(t.last_activity('claude'),before)

    def test_new_failed_result_is_an_edge_even_if_tool_started_earlier(self):
        t = WorkTracker(); t.update([session(actions=[action('命令 long')])], 100)
        row = session(updated=130, actions=[action('命令 long', result='失败', err=1)])
        t.update([row], 130)
        self.assertEqual(kinds(t), ['activity', 'oops'])
        t.update([row], 132); self.assertEqual(kinds(t), [])

    def test_done_count_is_observed_rows_and_not_raw_status_or_old_turn(self):
        tools = [action('写 item'+str(i), 100-i*.01) for i in range(8)]
        t=WorkTracker(); t.update([session(actions=tools+[{'turn': 1, 't': 99}])], 100)
        t.update([session('done', updated=102, actions=[action('本轮已结束', 102)]+tools+[
            {'turn': 1, 't': 99}, action('改 old', 98)])], 102)
        done = [e for e in t.drain('claude') if e['kind'] == 'done']
        self.assertEqual(len(done), 1); self.assertEqual(done[0]['n_tools'], 8)

    def test_terminal_marker_without_state_change_is_completed(self):
        t=WorkTracker();t.update([session(actions=[action('写 code')])],100)
        t.update([session(updated=102, actions=[action('本轮已结束',102),action('写 code')])],102)
        self.assertIn('done', kinds(t));self.assertIsNone(t.level('claude',102))

    def test_interrupt_marker_and_direct_idle_transition(self):
        for actions in ([], [action('本轮已中断', 102)]):
            t=WorkTracker();t.update([session('waiting')],100)
            t.update([session('idle',updated=102,actions=actions)],102)
            self.assertEqual(kinds(t),['activity','interrupt'])

    def test_missing_or_stale_session_does_not_claim_interrupt_or_finish(self):
        t=WorkTracker();t.update([session()],100)
        t.update([],102);self.assertEqual(kinds(t),[])
        t.update([session('idle',updated=104,stale=True)],104)
        self.assertEqual(kinds(t),[]);self.assertIsNone(t.level('claude',104))

    def test_old_local_evidence_is_baselined_without_edges(self):
        t=WorkTracker();t.update([],100)
        t.update([session('done',updated=79,actions=[action('本轮已结束',79)])],100)
        self.assertEqual(kinds(t),[])
        t.update([session(updated=100,actions=[{'turn':1,'t':79}])],101)
        self.assertNotIn('turn',kinds(t));self.assertIsNone(t.recent_turn(101))

    def test_mac_edges_are_observed_now_and_never_local_follow_candidates(self):
        t=WorkTracker();t.update([session('idle',agent='mac-claude',updated=80)],100)
        t.update([session(agent='mac-claude',updated=82,actions=['读 public'])],102)
        self.assertIn('turn',kinds(t));self.assertIsNone(t.recent_turn(102))
        t.update([session('error',agent='mac-claude',updated=82)],104)
        self.assertIn('oops',kinds(t));self.assertIsNone(t.level('claude',104))

    def test_mixed_source_queue_expiry_drops_local_edge_behind_mac_edge(self):
        t=WorkTracker();t.update([],100)
        rows=[session('done',agent='mac-claude',sid='m',updated=80),session('done',sid='l',updated=101)]
        t.update(rows,101);t.update(rows,122)
        events=t.drain('claude')
        self.assertTrue(events);self.assertEqual({e['source'] for e in events},{'mac'})
        t.update(rows,282);self.assertEqual(kinds(t),[])

    def test_heartbeats_do_not_refresh_activity_or_create_events(self):
        t=WorkTracker();t.update([session(actions=[action('读 public')])],100)
        before=t.last_activity('claude')
        t.update([session(updated=110,actions=[action('读 public')])],110)
        self.assertEqual(t.last_activity('claude'),before);self.assertEqual(kinds(t),[])

    def test_events_never_export_labels_ids_titles_or_results(self):
        secret='not-to-be-exported'
        t=WorkTracker();t.update([],100)
        t.update([session('done',sid=secret,updated=101,actions=[action('写 '+secret,101,secret)])],101)
        out=t.drain('claude')
        self.assertNotIn(secret,repr(out))
        self.assertEqual(set(out[-1]),{'kind','at','source','n_tools'})
        self.assertNotIn(secret,repr(t.__dict__))

    def test_invalid_and_future_values_do_not_replay_edges(self):
        for now in (True,float('nan'),float('inf'),-1):
            t=WorkTracker();t.update([session()],now)
            self.assertIsNone(t.level('claude',now));self.assertEqual(kinds(t),[])
        t=WorkTracker();t.update([],100)
        for value in (None,[],{},session(updated=1000),session(updated=float('nan'))):
            t.update([value],100);self.assertIsNone(t.level('claude',100));self.assertEqual(kinds(t),[])

    def test_backwards_clock_resets_baseline_and_queues(self):
        t=WorkTracker();t.update([],100)
        t.update([session('done',updated=101)],101)
        t.update([session('done',updated=50)],50)
        self.assertEqual(kinds(t),[])

    def test_storage_is_bounded_and_drain_returns_copies(self):
        t=WorkTracker();t.update([],100)
        for n in range(MAX_SESSIONS+20):
            t.update([session('done',sid=str(n),updated=101)],101)
        self.assertLessEqual(len(t._sessions),MAX_SESSIONS)
        self.assertLessEqual(len(t.drain('claude')),MAX_EVENTS)
        self.assertEqual(t.drain('claude'),())


    def test_mac_heartbeat_cannot_override_newer_local_action(self):
        t = WorkTracker()
        remote = session(sid='m', agent='mac-claude', actions=[action('读 remote')])
        local = session(sid='l', actions=[action('读 local')])
        t.update([remote, local], 100)
        local = session(sid='l', updated=102, actions=[action('写 local', 102)])
        remote = session(sid='m', agent='mac-claude', updated=103, actions=[action('读 remote')])
        t.update([remote, local], 103)
        self.assertEqual(t.level('claude', 103), 'writing')
        kinds(t)
        remote['updated'] = 110
        t.update([remote, local], 110)
        self.assertEqual(t.level('claude', 110), 'writing')
        self.assertEqual(kinds(t), [])

    def test_newer_real_mac_action_wins_despite_local_heartbeat(self):
        t = WorkTracker()
        t.update([session(sid='l', updated=105, actions=[action('写 local', 102)]),
                  session(sid='m', agent='mac-claude', updated=104,
                          actions=[action('读 remote', 104)])], 105)
        self.assertEqual(t.level('claude', 105), 'reading')

    def test_real_new_turn_without_tools_can_replace_older_work(self):
        t = WorkTracker()
        t.update([session(sid='l', updated=111, actions=[action('写 local', 102)]),
                  session(sid='m', agent='mac-claude', updated=111,
                          actions=[action('收到新任务', 110), {'turn':1, 't':110}])], 111)
        self.assertEqual(t.level('claude', 111), 'thinking')

    def test_legacy_action_first_observation_does_not_follow_heartbeats(self):
        t = WorkTracker()
        remote = session(sid='m', agent='mac-claude', actions=['读 remote'])
        t.update([remote], 100)
        remote['updated'] = 105
        t.update([remote, session(sid='l', updated=103, actions=[action('写 local', 103)])], 105)
        self.assertEqual(t.level('claude', 105), 'writing')

    def test_action_time_also_orders_reinserted_parallel_result_rows(self):
        t = WorkTracker()
        t.update([session(updated=104, actions=[action('读 older', 100, '返回'),
                                               action('写 newer', 102)])], 104)
        self.assertEqual(t.level('claude', 104), 'writing')

    def test_old_hook_result_change_uses_recent_observation_not_start_time(self):
        t = WorkTracker()
        row = session(agent='zcode', actions=[action('命令 long')])
        t.update([row], 100)
        t.update([row], 118)
        t.update([row], 128)
        failed = session(agent='zcode', actions=[action('命令 long', result='失败', err=1)])
        t.update([failed], 130)  # old hook left both updated and tool t at 100
        self.assertEqual(kinds(t, 'glm'), ['activity', 'oops'])
        self.assertEqual(t.last_activity('glm'), 130)
        self.assertIsNone(t.recent_turn(130))
        t.update([failed], 132)
        self.assertEqual(kinds(t, 'glm'), [])

    def test_result_without_error_also_supplies_recent_activity(self):
        t = WorkTracker()
        row = session(actions=[action('命令 long')])
        t.update([row], 100)
        t.update([row], 128)
        t.update([session(actions=[action('命令 long', result='返回')])], 130)
        self.assertEqual(kinds(t), ['activity'])
        self.assertEqual(t.level('claude', 130), 'thinking')

    def test_result_observation_window_is_inclusive_but_not_unbounded(self):
        for gap, expected in ((20, ['activity','oops']), (20.001, [])):
            with self.subTest(gap=gap):
                t = WorkTracker()
                t.update([session(actions=[action('命令 old')])], 200)
                t.update([session(actions=[action('命令 old', result='失败', err=1)])], 200+gap)
                self.assertEqual(kinds(t), expected)

    def test_first_discovery_of_old_local_error_is_not_a_new_error(self):
        for updated in (100, 130):
            with self.subTest(updated=updated):
                t = WorkTracker(); t.update([], 100)
                t.update([session(updated=updated,
                                  actions=[action('命令 historical', 100, '失败', 1)])], 130)
                self.assertNotIn('oops', kinds(t))

    def test_stale_or_future_result_never_uses_observation_fallback(self):
        for kwargs in ({'stale':True}, {'updated':1000}):
            t = WorkTracker()
            row = session(actions=[action('命令 long')])
            t.update([row], 100); t.update([row], 128)
            t.update([session(actions=[action('命令 long', result='失败', err=1)], **kwargs)], 130)
            self.assertEqual(kinds(t), [])
            self.assertIsNone(t.level('claude', 130))

    def test_new_round_cannot_borrow_old_action_observation_evidence(self):
        t = WorkTracker()
        t.update([session(actions=[action('命令 repeated'), {'turn':1, 't':99}])], 128)
        t.update([session(actions=[action('命令 repeated', result='失败', err=1),
                                   {'turn':1, 't':98}])], 130)
        self.assertNotIn('oops', kinds(t))

    def test_waiting_still_wins_and_stale_remote_work_is_excluded(self):
        t = WorkTracker()
        local = session(sid='l', updated=102, actions=[action('写 local',102)])
        remote = session('waiting', sid='m', agent='mac-claude', updated=103)
        t.update([local, remote], 103)
        self.assertEqual(t.level('claude',103), 'asking')
        remote['stale'] = True
        t.update([local, remote],104)
        self.assertEqual(t.level('claude',104), 'writing')

    def test_unknown_state_cannot_claim_a_result_or_interrupt(self):
        for state in ('unknown', None, [], {}):
            with self.subTest(state=state):
                t = WorkTracker()
                row = session(actions=[action('命令 long')])
                t.update([row],100); t.update([row],128)
                t.update([session(state, actions=[action('命令 long',result='失败',err=1)])],130)
                self.assertEqual(kinds(t),[])
                self.assertIsNone(t.level('claude',130))

    def test_future_or_malformed_turn_cannot_override_real_current_work(self):
        for stamp in (10000, float('inf'), float('nan'), True, None, -1):
            with self.subTest(stamp=stamp):
                t = WorkTracker()
                local = session(sid='l', updated=102, actions=[action('写 patch',102)])
                t.update([local],102)
                suspect = session(sid='bad', updated=103,
                                  actions=[{'turn':1,'t':stamp}, action('读 historical',100)])
                t.update([local, suspect],103)
                self.assertEqual(t.level('claude',103),'writing')
                self.assertEqual(kinds(t),[])
                self.assertIsNone(t.recent_turn(103))

    def test_future_or_malformed_start_cannot_override_real_current_work(self):
        for stamp in (10000,float('inf'),float('nan'),True,-1):
            with self.subTest(stamp=stamp):
                t = WorkTracker()
                local = session(sid='l',updated=102,actions=[action('写 patch',102)])
                t.update([local],102)
                t.update([local,session(sid='bad',updated=103,since=stamp)],103)
                self.assertEqual(t.level('claude',103),'writing')
                self.assertEqual(kinds(t),[])


if __name__=='__main__':
    unittest.main()

class TurnEdgeRegressionTests(unittest.TestCase):
    """I-50 review: turns finishing between scans, re-stamped endings, Mac reconnects."""

    def test_a_zcode_turn_that_finishes_between_scans_still_celebrates(self):
        t = WorkTracker()
        t.update([session('done', agent='zcode', actions=[{'turn': 1, 't': 90}])], 100)
        t.update([session('done', agent='zcode', updated=110,
                          actions=[action('命令 git status', 106), {'turn': 1, 't': 105}])], 111)
        self.assertEqual(kinds(t, 'glm'), ['activity', 'turn', 'done'])
        t.update([session('done', agent='zcode', updated=110,
                          actions=[action('命令 git status', 106), {'turn': 1, 't': 105}])], 125)
        self.assertEqual(kinds(t, 'glm'), [])                        # nothing new: no second done

    def test_a_restamped_closing_row_is_one_celebration(self):
        t = WorkTracker()
        running = session(actions=[action('改 x', 101), {'turn': 1, 't': 100}])
        t.update([running], 101)
        end1 = session('done', updated=105, actions=[action('本轮已结束', 105, '已结束'),
                                                      action('改 x', 101), {'turn': 1, 't': 100}])
        t.update([end1], 106)
        self.assertIn('done', kinds(t))
        end2 = session('done', updated=107, actions=[action('本轮已结束', 107, '已结束'),
                                                      action('改 x', 101), {'turn': 1, 't': 100}])
        t.update([end2], 108)                                        # stop hook re-stamped the row
        self.assertNotIn('done', kinds(t))
        t.update([dict(end2, state='idle', updated=109)], 110)       # metadata flip...
        t.update([dict(end2, updated=111)], 112)                     # ...and back
        self.assertNotIn('done', kinds(t))

    def test_a_mac_round_finishing_between_polls_celebrates(self):
        t = WorkTracker()
        mac = lambda since, updated: session('done', agent='mac-claude', since=since,
                                            updated=updated, actions=['改 notes.md'])
        t.update([mac(80, 90)], 100)
        t.update([mac(150, 160)], 220)                               # a whole new round in between
        self.assertIn('done', kinds(t))
        t.update([mac(150, 160)], 340)
        self.assertNotIn('done', kinds(t))

    def test_a_mac_reconnect_does_not_replay_the_same_round(self):
        t = WorkTracker()
        live = session('error', agent='mac-claude', since=50, updated=100, actions=['跑测试 py'])
        t.update([live], 100)
        t.update([dict(live, stale=True, state='idle', actions=[])], 900)   # outage
        t.update([dict(live, updated=1000)], 1000)                           # same round is back
        self.assertNotIn('oops', kinds(t))
        running = session('running', agent='mac-claude', since=50, updated=1000, actions=['改 x'])
        t.update([running], 1001)
        t.update([dict(running, stale=True, state='idle', actions=[])], 1800)
        t.update([dict(running, updated=1900)], 1900)
        self.assertNotIn('turn', kinds(t))
        t.update([dict(running, since=1850, updated=1950)], 1950)            # a new round after it
        self.assertIn('turn', kinds(t))

    def test_codex_polling_a_running_command_is_running_not_writing(self):
        import ai_lights_core
        self.assertEqual(pose_for_tool('write_stdin'), 'running')
        self.assertEqual(ai_lights_core.action_label('write_stdin', {'session_id': 1, 'chars': ''}), '命令 等输出')
        t = WorkTracker()
        t.update([session(agent='native-codex', actions=[action('write_stdin')])], 100)
        self.assertEqual(t.level('codex', 100), 'running')

