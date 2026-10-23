"""Adverse transitions from the issue 94 repair reviews; all services are fixtures."""
import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from unittest.mock import patch
from pathlib import Path

from tests.babysitter_continuous_fixtures import AcceptedJob, legacy_source, plan
from tests.test_babysitter_continuous import (
    ContinuousCase, FakeHost, H1, H2, HELPER, observation, pr, continuous_sweep,
)
from tests.test_rebuild_installed import Sandbox, tree_digest, worker_result

URL = 'https://github.com/fixture/widgets/pull/12'
NOW = '2026-10-22T14:05:00Z'


class UpdateAndResolutionTest(ContinuousCase):
    def adapters(self):
        yield HELPER, continuous_sweep, HELPER.with_name('merge-pr.sh')
        package, _ = Sandbox(self.base / 'installed').install('babysitter')
        spec = importlib.util.spec_from_file_location('global9_installed_sweep',
                                                    package / 'scripts/continuous_sweep.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        yield package / 'scripts/continuous.py', adapter, package / 'scripts/merge-pr.sh'

    def row(self, shape, **kwargs):
        row = pr(required_contexts=['ci'], **kwargs)
        if shape == 'reader':
            row['head_oid'] = row.pop('head_sha')
            row.pop('checks')
            row.pop('required_contexts')
            row.update(pending_checks=[], failing=[], checks_complete=True,
                       required_contexts_known=False)
        return row

    def test_source_and_installed_adapter_update_is_reserved_before_helper_and_refreshes_gates(self):
        from tests import test_merge_pr as merge_fixture
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            for shape in ('full', 'reader'):
                with self.subTest(installed=index, shape=shape):
                    self.state = self.base / f'update-{index}-{shape}.json'
                    self.start(helper=helper)
                    test = self
                    initial_head, updated_head = merge_fixture.HEAD, 'b' * 40

                    class UpdateHost(FakeHost):
                        def dispatch(host, action, now):
                            state = json.loads(test.state.read_text())
                            row = state['prs'][URL]['dispatches'][-1]
                            test.assertEqual((row['kind'], row['status']), ('update-branch', 'reserved'))
                            for kind in ('fixer', 'merge', 'resolution', 'update-branch'):
                                refused = test.cli('dispatch', '--now', now, '--pr', URL,
                                    '--kind', kind, '--request-id', 'racing-' + kind,
                                    '--head', initial_head, '--reserve', helper=helper, ok=False)
                                test.assertIn('may not race', refused.stderr)
                            harness = merge_fixture.MergeTest()
                            harness.script = shell
                            result, calls = harness.run_helper('behind-then-green',
                                ['--update-only', '--expected-head', action['head']])
                            test.assertEqual(result.returncode, 0, result.stderr)
                            test.assertIn('UPDATED', result.stdout)
                            test.assertEqual([c for c in calls if not c.get('query')],
                                             [{'expected_head_sha': initial_head}])
                            test.assertFalse(any('mutation' in c.get('query', '') for c in calls))
                            return super().dispatch(action, now)

                    host = UpdateHost(observation(self.row(shape, head=initial_head,
                                                          merge_state='BEHIND')))
                    host.clock = '2026-10-22T14:00:00Z'
                    adapter.arm(host, self.state, host.clock)
                    result = adapter.tick(host, self.state, '2026-10-22T14:10:00Z')[0]
                    action = result['result']['actions'][0]
                    self.assertEqual(action['kind'], 'update-branch')
                    self.assertEqual(result['dispatched'][0]['recorded'], 'recorded')
                    self.assertEqual(len(host.dispatched), 1)
                    request = action['request_id']
                    again = adapter.tick(host, self.state, '2026-10-22T14:20:00Z')[0]
                    self.assertEqual(again['result']['actions'][0]['kind'], 'update-branch-pending')
                    self.assertEqual(len(host.dispatched), 1)
                    self.cli('observe', '--now', NOW, '--wake-id', 'early-green-new-head',
                        payload=observation(self.row(shape, head=updated_head)), helper=helper)
                    self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                             '--request-id', request, '--host-task-id', 'task-1',
                             '--status', 'succeeded', helper=helper)
                    self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                                     ['next_action']['kind'], 'wait-checks')
                    for head, checks_head, expected in (
                            (initial_head, initial_head, 'branch-update-refresh'),
                            (updated_head, initial_head, 'stale-head-checks')):
                        row = self.row(shape, head=head)
                        row['checks_head_sha'] = checks_head
                        report = self.cli('observe', '--now', NOW, '--wake-id', head,
                            payload=observation(row), helper=helper)
                        self.assertEqual(report['actions'][0]['blocked']['kind'], expected)
                        refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                            '--request-id', 'stale-landing', '--head', head, '--reserve',
                            helper=helper, ok=False)
                        self.assertIn('current action is wait-checks', refused.stderr)
                    fresh = self.cli('observe', '--now', NOW, '--wake-id', 'fresh',
                        payload=observation(self.row(shape, head=updated_head)), helper=helper)
                    self.assertEqual(fresh['actions'][0]['kind'], 'merge')
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', 'fresh-landing', '--head', updated_head, '--reserve', helper=helper)

    def test_update_reservation_rechecks_conflict_exclusion_ownership_and_inflight_writers(self):
        for index, (helper, _, _) in enumerate(self.adapters()):
            self.state = self.base / f'guards-{index}.json'
            self.start(helper=helper)
            for shape in ('full', 'reader'):
                for changed in (dict(mergeable='CONFLICTING'), dict(draft=True), dict(fork=True),
                                dict(owner={'thread_id': 'other', 'continuation': 'maintainer-live'})):
                    row = self.row(shape, merge_state='BEHIND', **changed)
                    self.cli('observe', '--now', NOW, '--wake-id', str(changed),
                             payload=observation(row), helper=helper)
                    before = self.state.read_bytes()
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                        '--request-id', 'retained-update', '--head', H1, '--reserve', helper=helper, ok=False)
                    self.assertEqual(self.state.read_bytes(), before)
                    self.cli('observe', '--now', NOW, '--wake-id', 'release-' + str(changed),
                        payload=observation(self.row(shape, merge_state='BEHIND',
                            owner={'thread_id': 'other', 'continuation': 'released'})), helper=helper)
            baseline = self.state.read_bytes()
            for kind in ('fixer', 'resolution', 'merge'):
                self.state.write_bytes(baseline)
                # A landing reserved on a clean head also excludes a later update.
                if kind == 'merge':
                    self.cli('observe', '--now', NOW, '--wake-id', 'clean',
                             payload=observation(pr()), helper=helper)
                self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                    '--request-id', 'writer', '--head', H1, '--reserve', helper=helper)
                self.cli('observe', '--now', NOW, '--wake-id', 'behind',
                         payload=observation(pr(merge_state='BEHIND')), helper=helper)
                self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                    '--request-id', 'racing-update', '--head', H1, '--reserve', helper=helper, ok=False)

    def test_uncertain_update_keeps_its_reservation_until_matching_host_receipt(self):
        class LostUpdateHost(FakeHost):
            def dispatch(self, action, now):
                super().dispatch(action, now)
                raise TimeoutError('update response lost')

        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'lost-update-{index}.json'
            self.start(helper=helper)
            host = LostUpdateHost(observation(pr(merge_state='BEHIND')))
            result = adapter.handle_wake(host, self.state, NOW, {'kind': 'event'})
            request = result['result']['actions'][0]['request_id']
            report = self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
            self.assertEqual(report['next_action']['dispatch_status'], 'uncertain')
            host.snapshot = observation(pr(head=H2))
            result = adapter.handle_wake(host, self.state, NOW, {'kind': 'event', 'wake_id': 'new-head'})
            self.assertEqual(result['result']['actions'][0]['kind'], 'update-branch-pending')
            self.assertEqual(len(host.dispatched), 1)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', request, '--host-task-id', 'recovered-update', helper=helper)
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', request, '--status', 'cancelled', helper=helper, ok=False)
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', request, '--host-task-id', 'recovered-update',
                '--status', 'cancelled', helper=helper)
            self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                             ['next_action']['kind'], 'merge')

    def test_real_update_helper_receipts_hold_same_head_and_reconcile_fresh_heads_in_both_adapters(self):
        from tests.test_merge_pr import MergeTest, HEAD
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            for mode in ('update-accepted', 'update-response-lost', 'update-rejected', 'behind-then-green'):
                with self.subTest(installed=index, mode=mode):
                    self.state = self.base / f'transport-{index}-{mode}.json'
                    self.start(helper=helper)
                    test = self

                    class UpdateHost(FakeHost):
                        def dispatch(host, action, now):
                            saved = json.loads(test.state.read_text())['prs'][URL]['dispatches'][-1]
                            test.assertEqual(saved['status'], 'reserved')
                            harness = MergeTest()
                            harness.script = shell
                            result, calls = harness.run_helper(mode,
                                ['--update-only', '--expected-head', action['head']],
                                repo='fixture/widgets', number=12)
                            test.assertEqual([c for c in calls if not c.get('query')],
                                             [{'expected_head_sha': HEAD}])
                            test.assertFalse(any('mutation' in c.get('query', '') for c in calls))
                            super().dispatch(action, now)
                            host.helper_result = {'request_id': action['request_id'],
                                                  'returncode': result.returncode, 'stdout': result.stdout}
                            return {'helper_result': host.helper_result}

                    host = UpdateHost(observation(self.row('reader', head=HEAD, merge_state='BEHIND')))
                    result = adapter.handle_wake(host, self.state, NOW, {'kind': 'event'})
                    request = result['result']['actions'][0]['request_id']
                    saved = json.loads(self.state.read_text())['prs'][URL]['dispatches'][0]
                    expected = {'update-rejected': 'rejected', 'behind-then-green': 'succeeded'}.get(mode, 'uncertain')
                    self.assertEqual(saved['status'], expected)
                    self.assertEqual(saved['update_outcome'], {
                        'update-accepted': 'accepted', 'update-response-lost': 'unknown',
                        'update-rejected': 'rejected', 'behind-then-green': 'updated'}[mode])
                    self.assertEqual(result['dispatched'][0]['status'], expected)
                    if expected == 'rejected':
                        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                            '--request-id', 'confirmed-rejection-retry', '--head', HEAD,
                            '--reserve', helper=helper)
                        continue
                    if expected == 'succeeded':
                        old = adapter.handle_wake(host, self.state, NOW,
                                                 {'kind': 'event', 'wake_id': 'old-head'})
                        self.assertEqual(old['result']['actions'][0]['blocked']['kind'], 'branch-update-refresh')
                        self.assertEqual(len(host.dispatched), 1)
                    for wake in (('same-head-1', 'same-head-2') if expected == 'uncertain' else ()):
                        again = adapter.handle_wake(host, self.state, NOW,
                                                     {'kind': 'event', 'wake_id': wake})
                        self.assertEqual(again['result']['actions'][0]['kind'], 'update-branch-pending')
                        self.assertEqual(len(host.dispatched), 1)
                        self.assertEqual(len(json.loads(self.state.read_text())['prs'][URL]['dispatches']), 1)
                        for kind in ('update-branch', 'merge', 'fixer', 'resolution'):
                            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                                '--request-id', wake + kind, '--head', HEAD, '--reserve',
                                helper=helper, ok=False)
                    transport = self.base / 'update-result.json'
                    transport.write_text(json.dumps(host.helper_result))
                    before = self.state.read_bytes()
                    for status in (('failed', 'cancelled', 'superseded', 'no-change', 'succeeded', 'rejected')
                                   if expected == 'uncertain' else ()):
                        for flags in ([], ['--result', str(transport)]):
                            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                                '--request-id', request, '--head', HEAD, '--status', status,
                                *flags, helper=helper, ok=False)
                            self.assertEqual(self.state.read_bytes(), before)
                    # A new head settles the synchronous PUT, but old-head check
                    # evidence must still block landing at that new head.
                    updated = 'b' * 40
                    stale = self.row('reader', head=updated)
                    stale['checks_head_sha'] = HEAD
                    host.snapshot = observation(stale)
                    later = adapter.handle_wake(host, self.state, NOW,
                                               {'kind': 'event', 'wake_id': 'new-head'})
                    self.assertEqual(later['result']['actions'][0]['blocked']['kind'], 'stale-head-checks')
                    self.assertEqual(len(host.dispatched), 1)
                    self.assertEqual(json.loads(self.state.read_text())['prs'][URL]
                                     ['dispatches'][0]['status'], 'succeeded')
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', 'stale-merge', '--head', updated, '--reserve', helper=helper, ok=False)
                    fresh = self.cli('observe', '--now', NOW, '--wake-id', 'fresh-new-head',
                        payload=observation(self.row('reader', head=updated)), helper=helper)
                    self.assertEqual(fresh['actions'][0]['kind'], 'merge')
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', 'fresh-merge', '--head', updated, '--reserve', helper=helper)
                    # Replaying the pending transport cannot reopen a settled update.
                    replay = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                        '--request-id', request, '--status', 'uncertain', '--result', str(transport), helper=helper)
                    self.assertEqual(replay['status'], 'stale')

    def test_uncertain_put_accepts_only_a_matching_confirmed_rejection(self):
        from tests.test_merge_pr import MergeTest, HEAD
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            self.state = self.base / f'confirmed-{index}.json'
            self.start(helper=helper)
            self.cli('observe', '--now', NOW,
                payload=observation(pr(head=HEAD, merge_state='BEHIND')), helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                     '--request-id', 'put-1', '--head', HEAD, '--reserve', helper=helper)
            before = self.state.read_bytes()
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-1', '--status', 'failed', helper=helper, ok=False)
            self.assertEqual(self.state.read_bytes(), before)
            harness = MergeTest()
            harness.script = shell
            receipts = {}
            for mode in ('update-accepted', 'update-rejected'):
                result, _ = harness.run_helper(mode, ['--update-only', '--expected-head', HEAD],
                                              repo='fixture/widgets', number=12)
                receipts[mode] = {'request_id': 'put-1', 'returncode': result.returncode,
                                  'stdout': result.stdout}
            transport = self.base / 'confirmed-result.json'
            transport.write_text(json.dumps(receipts['update-accepted']))
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-1', '--status', 'uncertain', '--result', str(transport), helper=helper)
            for wrong in ('fixture/widgets#99', 'update_head=' + H1, 'wrong-request'):
                original = 'fixture/widgets#12' if '#' in wrong else 'update_head=' + HEAD
                bad = {**receipts['update-rejected'],
                       'stdout': receipts['update-rejected']['stdout'].replace(original, wrong)}
                if wrong == 'wrong-request':
                    bad = {**receipts['update-rejected'], 'request_id': wrong}
                transport.write_text(json.dumps(bad))
                before = self.state.read_bytes()
                self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                    '--request-id', 'put-1', '--status', 'rejected', '--result', str(transport), helper=helper, ok=False)
                self.assertEqual(self.state.read_bytes(), before)
            transport.write_text(json.dumps(receipts['update-rejected']))
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-1', '--status', 'rejected', '--result', str(transport), helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-2', '--head', HEAD, '--reserve', helper=helper)
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-1', '--status', 'rejected', '--result', str(transport), helper=helper)
            saved = json.loads(self.state.read_text())['prs'][URL]['dispatches']
            self.assertEqual([row['status'] for row in saved], ['rejected', 'reserved'])
            # A host refusal before launching the helper is also a confirmed no-write.
            refused = adapter._close_dispatch(self.state, NOW,
                {'pr': URL, 'kind': 'update-branch', 'head': HEAD, 'request_id': 'put-2'},
                'rejected', 'host confirmed that the helper was never launched')
            self.assertEqual(refused['dispatch']['status'], 'rejected')

    def test_terminal_wrapper_does_not_prove_the_same_head_put_was_rejected(self):
        for index, (helper, _, _) in enumerate(self.adapters()):
            self.state = self.base / f'wrapper-{index}.json'
            self.start(helper=helper)
            self.cli('observe', '--now', NOW,
                payload=observation(pr(merge_state='BEHIND')), helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                     '--request-id', 'wrapper', '--head', H1, '--reserve', helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                     '--request-id', 'wrapper', '--host-task-id', 'update-task', helper=helper)
            before = self.state.read_bytes()
            for status in ('failed', 'cancelled', 'rejected', 'succeeded', 'superseded', 'no-change'):
                self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                    '--request-id', 'wrapper', '--host-task-id', 'update-task',
                    '--status', status, helper=helper, ok=False)
                self.assertEqual(self.state.read_bytes(), before)

    def test_live_resolution_is_next_action_until_matching_terminal_receipt_in_both_adapters(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            for shape in ('full', 'reader'):
                self.state = self.base / f'resolution-{index}-{shape}.json'
                self.start(helper=helper)
                host = FakeHost(observation(self.row(shape, threads=1)))
                host.clock = '2026-10-22T14:00:00Z'
                adapter.arm(host, self.state, host.clock)
                self.cli('observe', '--now', NOW, '--wake-id', 'threads',
                    payload=host.snapshot, helper=helper)
                self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                    '--request-id', 'reply-1', '--head', H1, '--reserve', helper=helper)
                for status in ('reserved', 'uncertain', 'pending'):
                    if status == 'uncertain':
                        self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                            '--request-id', 'reply-1', '--status', 'uncertain', helper=helper)
                    if status == 'pending':
                        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                            '--request-id', 'reply-1', '--host-task-id', 'reply-host', helper=helper)
                    host.snapshot = observation(self.row(shape, head=H2))
                    result = adapter.handle_wake(host, self.state, NOW,
                                                {'kind': 'event', 'wake_id': status})
                    action = result['result']['actions'][0]
                    self.assertEqual((action['kind'], action['request_id'], action['dispatch_status']),
                                     ('resolution-pending', 'reply-1', status))
                    self.assertEqual(action['host_task_id'], 'reply-host' if status == 'pending' else None)
                    self.assertEqual(host.dispatched, [])
                    report = self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                    for key in ('kind', 'request_id', 'host_task_id', 'dispatch_status'):
                        self.assertEqual(report['next_action'][key], action[key])
                    self.assertEqual(report['dispatches'][0]['status'], status)
                before = self.state.read_bytes()
                for request, kind, handle in (('wrong', 'resolution', 'reply-host'),
                                              ('reply-1', 'merge', 'reply-host'),
                                              ('reply-1', 'resolution', 'wrong'),
                                              ('reply-1', 'resolution', None)):
                    flags = ['--host-task-id', handle] if handle else []
                    self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', kind,
                        '--request-id', request, '--status', 'succeeded', *flags, helper=helper, ok=False)
                    self.assertEqual(self.state.read_bytes(), before)
                # Exclusion and explicit lifecycle close never erase the live request.
                self.cli('observe', '--now', NOW, '--wake-id', 'excluded',
                    payload=observation(self.row(shape, head=H2, draft=True)), helper=helper)
                self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                                 ['next_action']['kind'], 'resolution-pending')
                if shape == 'reader':
                    self.cli('resolve', '--now', NOW, '--pr', URL, '--resolution', 'closed',
                             '--head', H2, helper=helper)
                self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                                 ['dispatches'][0]['status'], 'pending')
                self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                    '--request-id', 'reply-1', '--host-task-id', 'reply-host', '--status', 'succeeded',
                    helper=helper)
                settled = self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                if shape == 'full':
                    self.assertIsNone(settled['next_action'])
                    self.assertEqual(settled['state'], 'excluded')
                fresh = self.cli('observe', '--now', NOW, '--wake-id', 'released',
                    payload=observation(self.row(shape, head=H2)), helper=helper)
                self.assertEqual(fresh['actions'][0]['kind'], 'merge')

    def test_cancelled_run_keeps_live_resolution_visible_without_proposing_followup_on_receipt(self):
        for index, (helper, _, _) in enumerate(self.adapters()):
            self.state = self.base / f'cancel-resolution-{index}.json'
            self.start(helper=helper)
            self.cli('observe', '--now', NOW, payload=observation(pr()), helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                     '--request-id', 'reply', '--reserve', helper=helper)
            self.cli('cancel', '--now', NOW, '--reason', 'owner stopped', helper=helper)
            self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                             ['next_action']['kind'], 'resolution-pending')
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                     '--request-id', 'reply', '--status', 'cancelled', helper=helper)
            self.assertIsNone(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]['next_action'])


class ReservationSafetyTest(ContinuousCase):
    def reserve(self, kind, request, **kwargs):
        return self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                        '--request-id', request, '--head', H1, '--reserve', **kwargs)

    def test_red_required_check_cannot_reserve_a_merge_or_block_its_fixer(self):
        self.start()
        red = pr(merge_state='BLOCKED', checks_state='FAILURE', required_contexts=['lint'],
                 checks=[{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE',
                          'head_sha': H1}])
        action = self.observe(NOW, observation(red), wake='red')['actions'][0]
        self.assertEqual(action['kind'], 'dispatch-fixer')
        before = self.state.read_bytes()
        refused = self.reserve('merge', 'stale-merge', ok=False)
        self.assertIn('current action is dispatch-fixer', refused.stderr)
        self.assertEqual(self.state.read_bytes(), before)
        reserved = self.reserve('fixer', action['request_id'])
        self.assertTrue(reserved['fixer']['in_flight'])

    def test_merge_dispatch_rechecks_gates_after_a_green_action_at_the_same_head(self):
        self.start()
        green = self.observe(NOW, observation(pr()), wake='green')['actions'][0]
        for index, changed in enumerate((
                pr(threads=1), pr(checks_state='PENDING', checks=[{
                    'name': 'ci', 'status': 'QUEUED', 'created_at': NOW}]),
                {**pr(), 'checks_complete': False},
                {**pr(), 'review_threads_complete': False},
                pr(merge_state=None))):
            with self.subTest(changed=changed):
                self.observe(NOW, observation(changed), wake=f'gate-{index}')
                before = self.state.read_bytes()
                # Both reserve-before-launch and the legacy direct-record path must
                # reject an action retained from the earlier green observation.
                for reserve in (('--reserve',), ()):
                    refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', green['request_id'], '--head', H1, *reserve, ok=False)
                    self.assertIn('current action is', refused.stderr)
                    self.assertEqual(self.state.read_bytes(), before)

    def test_installed_helper_rejects_unknown_and_red_gates_but_keeps_a_green_landing_lock(self):
        box = Sandbox(self.base / 'installed')
        package, manifest = box.install('babysitter')
        self.assertTrue(manifest['version'].startswith('1.3.0'))
        helper = package / 'scripts/continuous.py'
        self.start(helper=helper)
        for index, gate in enumerate((None, '', 'UNKNOWN', 'BLOCKED')):
            row = pr(merge_state=gate)
            if gate == 'BLOCKED':
                row.update(checks_state='FAILURE', required_contexts=['lint'], checks=[{
                    'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE', 'head_sha': H1}])
            result = self.cli('observe', '--now', NOW, '--wake-kind', 'event',
                '--wake-id', f'installed-{index}', payload=observation(row), helper=helper)
            self.assertEqual(result['actions'][0]['kind'],
                             'dispatch-fixer' if gate == 'BLOCKED' else 'diagnose-gate')
            before = self.state.read_bytes()
            refused = self.reserve('merge', 'bad-merge', helper=helper, ok=False)
            self.assertIn('current action is', refused.stderr)
            self.assertEqual(self.state.read_bytes(), before)
        self.cli('observe', '--now', NOW, '--wake-kind', 'event', '--wake-id', 'green',
                 payload=observation(pr()), helper=helper)
        self.reserve('merge', 'green-merge', helper=helper)
        self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
                 '--request-id', 'green-merge', '--status', 'armed', helper=helper)
        refused = self.reserve('fixer', 'racing-fixer', helper=helper, ok=False)
        self.assertIn('a fixer may not race', refused.stderr)

    def test_reservation_rechecks_exclusion_ownership_and_closed_lifecycle(self):
        self.start()
        action = self.observe(NOW, observation(pr()), wake='green')['actions'][0]
        for index, changed in enumerate((pr(draft=True), pr(fork=True),
                pr(owner={'thread_id': 'other', 'status': 'running'}), pr(state='CLOSED'))):
            self.observe(NOW, observation(changed), wake=f'changed-{index}')
            before = self.state.read_bytes()
            refused = self.reserve('merge', action['request_id'], ok=False)
            self.assertRegex(refused.stderr, 'eligible|owned elsewhere')
            self.assertEqual(self.state.read_bytes(), before)
            self.observe(NOW, observation(pr(owner={'thread_id': 'other',
                'continuation': 'handed-back'})), wake=f'release-{index}')

    def test_resolution_reservations_exclude_every_other_write(self):
        self.start()
        self.observe(NOW, observation(pr()), wake='green')
        for first in ('resolution', 'merge', 'fixer'):
            for second in ('resolution', 'merge', 'fixer'):
                state = self.base / f'{first}-{second}.json'
                state.write_bytes(self.state.read_bytes())
                self.reserve(first, 'first', state=state)
                refused = self.reserve(second, 'second', state=state, ok=False)
                self.assertRegex(refused.stderr, 'race|in flight|pending')

    def test_lost_response_keeps_actual_started_writer_held_then_attaches_matching_handle(self):
        class LostResponseHost(FakeHost):
            def dispatch(self, action, now):
                super().dispatch(action, now)  # side effect succeeded; response was lost
                raise TimeoutError('lost response')

        host = LostResponseHost(observation(pr(checks=[{
            'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}])))
        host.clock = '2026-10-22T14:00:00Z'
        self.start()
        continuous_sweep.arm(host, self.state, host.clock)
        delivered = continuous_sweep.tick(host, self.state, '2026-10-22T14:10:00Z')
        action = delivered[0]['dispatched'][0]['action']
        self.assertEqual(len(host.dispatched), 1)
        green = self.observe('2026-10-22T14:11:00Z', observation(pr()), wake='green')
        self.assertEqual(green['actions'][0]['kind'], 'wait-fixer')
        fixture = AcceptedJob(self.base / 'recovered-job', action['request_id'], 'recovered-host')
        attached = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'fixer',
                            '--request-id', action['request_id'], '--host-task-id', fixture.host)
        self.assertTrue(attached['attached'])
        fixture.complete()
        self.cli('fixer-done', '--now', NOW, '--pr', URL, '--request-id', action['request_id'],
                 '--host-task-id', fixture.host, '--result', str(fixture.transport))
        self.assertEqual(self.observe(NOW, observation(pr()), wake='done')['actions'][0]['kind'], 'merge')


class AcceptedReceiptTest(ContinuousCase):
    def test_adopted_identity_can_be_filled_but_never_replaced_and_needs_ingested_result(self):
        self.start()
        owner = {'thread_id': 'self', 'status': 'running', 'fixer_in_flight': True}
        self.observe(NOW, observation(pr(owner=owner)), wake='no-handle')
        owner['host_task_id'] = 'task-live'
        self.observe(NOW, observation(pr(owner=owner)), wake='identified')
        guard = json.loads(self.state.read_text())['prs'][URL]['fixer']
        self.assertEqual(guard['host_task_id'], 'task-live')
        self.observe(NOW, observation(pr(owner={**owner, 'thread_id': 'new-writer',
                                                'host_task_id': 'different-task'})), wake='other')
        self.assertEqual(json.loads(self.state.read_text())['prs'][URL]['fixer']['host_task_id'], 'task-live')
        bogus = self.base / 'bogus.txt'
        bogus.write_text('not a task result')
        before = self.state.read_bytes()
        refused = self.cli('fixer-done', '--now', NOW, '--pr', URL, '--request-id', 'unrelated',
                           '--host-task-id', 'task-live', '--result', str(bogus), ok=False)
        self.assertIn('accepted job', refused.stderr)
        self.assertEqual(self.state.read_bytes(), before)
        fixture = AcceptedJob(self.base / 'job', 'real-request', 'task-live')
        raw_result = fixture.box.private / 'unaccepted.json'
        raw_result.write_text(worker_result(fixture.brief))
        premature = self.cli('fixer-done', '--now', NOW, '--pr', URL,
            '--request-id', 'real-request', '--host-task-id', fixture.host,
            '--job', str(fixture.directory), '--result', str(raw_result), ok=False)
        self.assertIn('job-retained transport', premature.stderr)
        fixture.complete()
        wrong = self.cli('fixer-done', '--now', NOW, '--pr', URL,
            '--request-id', 'unrelated', '--host-task-id', fixture.host,
            '--result', str(fixture.transport), ok=False)
        self.assertIn('job-retained transport', wrong.stderr)
        self.cli('fixer-done', '--now', NOW, '--pr', URL, '--request-id', 'real-request',
                 '--host-task-id', fixture.host, '--result', str(fixture.transport))
        self.assertFalse(json.loads(self.state.read_text())['prs'][URL]['fixer']['in_flight'])

    def test_malformed_ingested_result_cannot_release_an_adopted_guard(self):
        fixture = AcceptedJob(self.base / 'job', 'real-request', 'task-live')
        fixture.complete(malformed=True)
        self.start()
        self.observe(NOW, observation(pr(owner={'thread_id': 'self', 'status': 'running',
            'fixer_in_flight': True, 'host_task_id': fixture.host})), wake='adopt')
        refused = self.cli('fixer-done', '--now', NOW, '--pr', URL, '--request-id', 'real-request',
            '--host-task-id', fixture.host, '--result', str(fixture.transport), ok=False)
        self.assertIn('no matching accepted', refused.stderr)
        # A correlated terminal malformed ingestion is a failed attempt, so routine
        # retry can proceed without pretending that the worker is still running.
        failed = self.cli('receipt', '--now', NOW, '--pr', URL, '--request-id', 'real-request',
            '--host-task-id', fixture.host, '--result', str(fixture.transport), '--status', 'failed',
            '--kind', 'fixer')
        self.assertFalse(failed['fixer']['in_flight'])

    def test_partial_owner_status_never_erases_identity_or_continuation(self):
        self.start()
        self.observe(NOW, observation(pr(owner={'thread_id': 'other', 'status': 'running',
            'continuation': 'maintainer-live'})), wake='live')
        partial = self.observe(NOW, observation(pr(owner={'status': 'completed'})), wake='partial')
        self.assertEqual(partial['actions'][0]['kind'], 'owned-elsewhere')
        owner = json.loads(self.state.read_text())['prs'][URL]['owner']
        self.assertEqual((owner['thread_id'], owner['continuation']), ('other', 'maintainer-live'))
        unknown = self.observe(NOW, observation(pr(owner={'status': 'completed',
            'thread_id': None, 'continuation': None})), wake='null-fields')
        self.assertEqual(unknown['actions'][0]['kind'], 'owned-elsewhere')


class OwnershipReleaseTest(ContinuousCase):
    STATUSES = (
        'active', 'preparing', 'queued', 'starting', 'running', 'waiting',
        'parked', 'idle', 'completed', 'failed', 'interrupted', 'cancelled',
        'rolled_back', 'stopped', 'handed-back', 'released', 'none',
        'unfamiliar-status', '', None, 'STOPPED', 'CANCELLED',
    )
    RELEASES = ('handed-back', 'released', 'none', 'stopped', 'cancelled')

    def test_status_continuation_matrix_requires_explicit_release_before_reservation(self):
        continuous = continuous_sweep.continuous
        self.start()
        initial = self.state.read_bytes()
        snapshot = self.base / 'owner-matrix.json'
        continuations = ({}, *({'continuation': value} for value in (
            None, '', 'maintainer-live', 'watching', 'unknown', 'still-maintaining',
            'RELEASED', *self.RELEASES)))
        for status in self.STATUSES:
            for continuation in continuations:
                with self.subTest(status=status, **continuation):
                    self.state.write_bytes(initial)
                    snapshot.write_text(json.dumps(observation(pr(owner={
                        'thread_id': 'other', 'status': status, **continuation}))))
                    result = continuous.cmd_observe(Namespace(state=str(self.state), now=NOW,
                        observation=str(snapshot), wake_id='matrix', wake_kind='event'))
                    released = continuation.get('continuation') in self.RELEASES
                    self.assertEqual(result['actions'][0]['kind'],
                                     'merge' if released else 'owned-elsewhere')
                    owner = json.loads(self.state.read_text())['prs'][URL]['owner']
                    self.assertEqual(owner['thread_id'], 'other')
                    before = self.state.read_bytes()
                    for kind in ('merge', 'fixer', 'resolution'):
                        args = Namespace(state=str(self.state), now=NOW, pr=URL, kind=kind,
                            request_id=f'takeover-{kind}', head=H1, reserve=True,
                            host_task_id=None, attempt=None, review_triage=False)
                        if released:
                            reserved = continuous.cmd_dispatch(args)
                            self.assertEqual(reserved['status'], 'recorded')
                            self.state.write_bytes(before)
                        else:
                            with self.assertRaisesRegex(continuous.ContinuousError, 'owned elsewhere'):
                                continuous.cmd_dispatch(args)
                            self.assertEqual(self.state.read_bytes(), before)

    def test_partial_terminal_updates_preserve_identity_and_live_continuation(self):
        self.start()
        for status in ('idle', 'completed', 'failed', 'interrupted', 'cancelled',
                       'rolled_back', 'stopped', 'handed-back', 'released'):
            for fields in ({}, {'thread_id': None},
                           {'thread_id': None, 'continuation': None}, {'continuation': ''}):
                with self.subTest(status=status, fields=fields):
                    self.observe(NOW, observation(pr(owner={'thread_id': 'other',
                        'status': 'running', 'continuation': 'maintainer-live',
                        'host_task_id': 'maintainer-task'})), wake=f'live-{status}-{fields}')
                    still = self.observe(NOW, observation(pr(owner={'status': status, **fields})),
                                         wake=f'partial-{status}-{fields}')
                    self.assertEqual(still['actions'][0]['kind'], 'owned-elsewhere')
                    owner = json.loads(self.state.read_text())['prs'][URL]['owner']
                    self.assertEqual((owner['thread_id'], owner['continuation'], owner['host_task_id']),
                                     ('other', 'maintainer-live', 'maintainer-task'))

    def test_installed_helper_refuses_terminal_status_takeover_until_explicit_handoff(self):
        box = Sandbox(self.base / 'installed')
        package, _ = box.install('babysitter')
        helper = package / 'scripts/continuous.py'
        self.start(helper=helper)
        for status in ('completed', 'failed', 'interrupted', 'cancelled', 'rolled_back',
                       'stopped', 'handed-back', 'released'):
            for continuation in ({}, {'continuation': 'maintainer-live'},
                                 {'continuation': 'still-maintaining'}):
                result = self.cli('observe', '--now', NOW, '--wake-kind', 'event',
                    '--wake-id', f'installed-{status}-{continuation}',
                    payload=observation(pr(owner={'thread_id': 'other', 'status': status,
                                                  **continuation})), helper=helper)
                self.assertEqual(result['actions'][0]['kind'], 'owned-elsewhere')
                before = self.state.read_bytes()
                for kind in ('merge', 'fixer', 'resolution'):
                    refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                        '--request-id', f'takeover-{kind}', '--head', H1, '--reserve',
                        helper=helper, ok=False)
                    self.assertIn('owned elsewhere', refused.stderr)
                    self.assertEqual(self.state.read_bytes(), before)
        released = self.cli('observe', '--now', NOW, '--wake-kind', 'event',
            '--wake-id', 'verified-handoff', payload=observation(pr(owner={
                'status': 'stopped', 'continuation': 'handed-back'})), helper=helper)
        self.assertEqual(released['actions'][0]['kind'], 'merge')
        self.assertEqual(json.loads(self.state.read_text())['prs'][URL]['owner']['thread_id'], 'other')
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', released['actions'][0]['request_id'], '--head', H1,
            '--reserve', helper=helper)


class LiveMergeHeadChangeTest(ContinuousCase):
    def exercise_live_merge(self, status, helper=HELPER):
        self.start(helper=helper)
        self.cli('observe', '--now', NOW, '--wake-kind', 'event', '--wake-id', 'green',
                 payload=observation(pr()), helper=helper)
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', 'merge-a', '--head', H1, '--reserve', helper=helper)
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', 'merge-a', '--host-task-id', 'merge-host-1', helper=helper)
        if status == 'armed':
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
                '--request-id', 'merge-a', '--status', 'armed', helper=helper)
        red = pr(head=H2, merge_state='BLOCKED', checks_state='FAILURE',
            required_contexts=['lint'], checks=[{'name': 'lint', 'status': 'COMPLETED',
                'conclusion': 'FAILURE', 'head_sha': H2}])
        for index, row in enumerate((pr(head=H2), red)):
            moved = self.cli('observe', '--now', NOW, '--wake-kind', 'event',
                '--wake-id', f'moved-{index}', payload=observation(row), helper=helper)
            self.assertEqual(moved['actions'][0]['kind'], 'merge-pending')
            dispatch = json.loads(self.state.read_text())['prs'][URL]['dispatches'][0]
            self.assertEqual(dispatch['status'], status)
            self.assertNotIn('completed_at', dispatch)
            self.assertEqual(dispatch['stale_at_head'], H2)
            for kind in ('merge', 'fixer', 'resolution'):
                before = self.state.read_bytes()
                refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                    '--request-id', f'racing-{kind}', '--head', H2, '--reserve',
                    helper=helper, ok=False)
                self.assertIn('merge merge-a', refused.stderr)
                self.assertEqual(self.state.read_bytes(), before)
        before = self.state.read_bytes()
        for handle in ((), ('--host-task-id', 'unrelated-host')):
            refused = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
                '--request-id', 'merge-a', '--head', H1, '--status', 'cancelled',
                *handle, helper=helper, ok=False)
            self.assertIn('handle', refused.stderr)
            self.assertEqual(self.state.read_bytes(), before)
        terminal = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', 'merge-a', '--host-task-id', 'merge-host-1', '--head', H1,
            '--status', 'cancelled', helper=helper)
        self.assertEqual(terminal['dispatch']['status'], 'cancelled')
        self.assertIn('completed_at', terminal['dispatch'])
        ready = self.cli('observe', '--now', NOW, '--wake-kind', 'event', '--wake-id', 'settled',
            payload=observation(red), helper=helper)
        self.assertEqual(ready['actions'][0]['kind'], 'dispatch-fixer')
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'fixer',
            '--request-id', ready['actions'][0]['request_id'], '--head', H2,
            '--reserve', helper=helper)
        before = self.state.read_bytes()
        duplicate = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', 'merge-a', '--host-task-id', 'merge-host-1', '--head', H1,
            '--status', 'cancelled', helper=helper)
        self.assertEqual(duplicate['status'], 'duplicate')
        self.assertEqual(self.state.read_bytes(), before)
        self.assertTrue(json.loads(before)['prs'][URL]['fixer']['in_flight'])

    def test_pending_merge_handle_survives_green_and_red_head_changes(self):
        self.exercise_live_merge('pending')

    def test_armed_merge_handle_survives_green_and_red_head_changes(self):
        self.exercise_live_merge('armed')

    def test_installed_helper_preserves_an_armed_stale_merge_until_matching_terminal_receipt(self):
        box = Sandbox(self.base / 'installed')
        package, _ = box.install('babysitter')
        self.exercise_live_merge('armed', helper=package / 'scripts/continuous.py')


class RevocationTest(ContinuousCase):
    def test_revoke_blocks_a_due_host_wake_until_owned_stop_is_verified(self):
        host = FakeHost(observation(pr()))
        host.clock = '2026-10-22T14:00:00Z'
        self.start()
        continuous_sweep.arm(host, self.state, host.clock)
        revoked = self.cli('scheduler', '--now', NOW, '--available', 'yes', '--authorized', 'no')
        self.assertEqual(revoked['coverage'], 'stop-unverified')
        self.assertTrue(revoked['scheduler_stop'])
        delivered = continuous_sweep.tick(host, self.state, '2026-10-22T14:10:00Z')
        self.assertEqual(delivered[0]['result']['status'], 'scheduled-continuation-blocked')
        self.assertEqual(host.dispatched, [])
        blocked = self.observe(NOW, observation(pr()), wake='late-timer')
        self.assertEqual(blocked['status'], 'scheduled-continuation-blocked')
        self.assertEqual(host.delete_schedule(revoked['scheduler_stop']), {'verified': True})
        self.cli('schedule-stop', '--now', NOW, '--schedule-id', revoked['scheduler']['schedule_id'],
                 '--verified', 'yes')
        self.assertEqual(self.cli('status')['coverage'], 'event-only')

    def test_identical_run_inputs_still_create_unique_persistent_schedule_keys(self):
        first = self.start()
        other = self.base / 'other.json'
        second = self.cli('start', '--now', '2026-10-22T14:00:00Z', '--scope-kind', 'org',
            '--scope-value', 'fixture', '--thread-id', 'self', '--scheduler', 'scheduled',
            '--authorization-source', str(self.request), state=other)
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertNotEqual(self.cli('schedule-plan')['request']['key'],
                            self.cli('schedule-plan', state=other)['request']['key'])


class RealLegacyUpgradeTest(ContinuousCase):
    def test_historical_source_extraction_works_without_git_or_subprocesses(self):
        with patch('subprocess.run', side_effect=AssertionError('fixture extraction must be offline')):
            source = legacy_source(self.base)
        self.assertEqual(json.loads((source / 'plugins/babysitter/plugin.json').read_text())['version'],
                         '1.2.10')

    def test_real_legacy_pin_upgrade_retains_evidence_and_resumes_with_verified_receipt(self):
        self.exercise_upgrade()

    def test_previous_helper_state_migrates_its_real_legacy_fingerprint(self):
        self.exercise_upgrade('17e636c1c24be77566f24062f93a8b1dc17d94c8')

    def exercise_upgrade(self, revision=None):
        box = Sandbox(self.base / 'sandbox')
        source = legacy_source(self.base, revision) if revision else legacy_source(self.base)
        old, old_manifest = box.install('babysitter', source=source)
        caller = box.caller(old_manifest, 'babysitter/repo')
        job_id = 'legacy-upgrade'
        box.create(old, plan(old_manifest, job_id))
        self.assertEqual(box.pinned_package(job_id, 'babysitter'), old)
        self.assertEqual((old / 'scripts/continuous.py').exists(), bool(revision))
        if revision:
            self.start(helper=old / 'scripts/continuous.py', job_id=job_id)
        brief = box.dispatch(old, job_id, caller, 'fix', 'old-host')
        box.complete(old, job_id, caller, 'fix', brief, 'old-host', worker_result(brief))
        box.job(old, 'decision', job_id, {'caller': caller, 'decision': box.owner_decision(
            'owner-upgrade', 'Upgrade this synthetic job.', 'plan:upgrade-1')})
        job_file = box.jobs / job_id / 'job.json'
        before_job = job_file.read_bytes()
        before_evidence = tree_digest(job_file.parent / 'briefs', job_file.parent / 'results', old)
        current, manifest = box.install('babysitter')
        helper = current / 'scripts/continuous.py'
        identity_proc = box.run([sys.executable, helper, 'version'])
        identity = json.loads(identity_proc.stdout)
        self.assertEqual(identity['digest'], manifest['package_digest'])
        preflight = self.cli('preflight', '--job', str(job_file), '--now', NOW, helper=helper)
        self.assertEqual(preflight['status'], 'ready' if revision else 'legacy-job')
        self.assertEqual(job_file.read_bytes(), before_job)
        self.assertEqual(box.pinned_package(job_id, 'babysitter'), old)
        upgrade = box.job(current, 'upgrade-package', job_id, {
            'caller': caller, 'revision': {'id': 'upgrade-1', 'owner_decision_id': 'owner-upgrade',
                'reason': 'Adopt continuous mode while retaining original evidence.'},
            'dependency_key': 'babysitter',
            'expected_state_sha256': hashlib.sha256(before_job).hexdigest(),
            'expected_package_digest': manifest['package_digest']},
            extra=('--prefix', box.prefix, '--agents-root', box.agents))
        self.assertEqual(box.pinned_package(job_id, 'babysitter'), current)
        self.assertEqual(Path(upgrade['previous_state']['path']).read_bytes(), before_job)
        self.assertEqual(tree_digest(job_file.parent / 'briefs', job_file.parent / 'results', old),
                         before_evidence)
        receipt = self.base / 'upgrade.json'
        receipt.write_text(json.dumps(upgrade))  # exact supported CLI result, no fabricated fields
        if not revision:
            self.start(helper=helper)
        state = json.loads(self.state.read_text())
        if not revision:
            # The original continuous-1 helper wrote no fingerprint or job identity.
            state['package'] = {'pinned_version': old_manifest['version']}
            state.pop('job_id', None)
            state.pop('job', None)
            self.state.write_text(json.dumps(state))
        original_state = self.state.read_bytes()
        required = self.cli('resume', '--now', NOW, helper=helper)
        self.assertEqual(required['status'], 'migration-required')
        for decision_id, error in [('never-recorded', 'no matching supported'),
                                   ('owner-upgrade', None)]:
            if error:
                refused = self.cli('resume', '--now', NOW, '--accept-migration',
                    '--owner-decision-id', decision_id, '--upgrade-receipt', str(receipt),
                    '--job', str(job_file), helper=helper, ok=False)
                self.assertIn(error, refused.stderr)
                self.assertEqual(self.state.read_bytes(), original_state)
            else:
                resumed = self.cli('resume', '--now', NOW, '--accept-migration',
                    '--owner-decision-id', decision_id, '--upgrade-receipt', str(receipt),
                    '--job', str(job_file), helper=helper)
                self.assertEqual(resumed['status'], 'resumed')
                self.assertEqual(resumed['migration']['upgrade_receipt']['job_id'], job_id)
        after_job = job_file.read_bytes()
        self.assertEqual(tree_digest(job_file.parent / 'briefs', job_file.parent / 'results', old),
                         before_evidence)
        self.assertEqual(self.cli('resume', '--now', NOW, helper=helper)['status'], 'resumed')
        self.assertEqual(job_file.read_bytes(), after_job)
        self.assertEqual(self.cli('status', helper=helper)['run_id'], state['run_id'])
        # The actual installed package rejects tampering instead of inventing another identity.
        (current / 'references/continuous.md').write_text('tampered fixture')
        tampered = box.run([sys.executable, helper, 'version'], check=False)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn('integrity failure', tampered.stderr)
