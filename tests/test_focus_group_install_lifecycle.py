"""Installed lifecycle cases split to retain the 600-second module deadline."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.focus_group_install_fixtures import (  # noqa: E402
    HandoffHost, RelocatedInstallCase, STATE, Swap, audit_rows, audited,
    setUpModule, sha, tearDownModule,
)


class RelocatedInstallTest(RelocatedInstallCase):
    def test_8_locally_missing_material_refuses_admission_without_a_charge(self):
        self.adopt()
        base = STATE['base'] / 'handoff-missing'
        base.mkdir()
        with Swap(self.inst, self.inst['env'], base):
            h = HandoffHost(base, self.inst['package'])
            h.start(mode='capture-only')
            before = h.charged()
            path = Path(h.stimulus(h.view['study_id'])['files'][0]['path'])
            data = path.read_bytes()
            path.unlink()
            code, out = h.admit_slot(0, 'first-impression', 'fi-01-r0')
            self.assertEqual((code, out['error']['code']), (1, 'inputs_changed'), out)
            self.assertEqual(h.charged(), before)

            path.write_bytes(data)
            # A locally detectable missing mapping is also held before spending, through the real plan route.
            job = h.job_state()
            tasks = copy.deepcopy(job['tasks'])
            tasks[0]['context_files'] = []
            source = base / 'fixture-owner.txt'
            quote = 'Approve fixture missing mapping plan revision'
            source.write_text(quote)
            h.job_ok('decision', {'caller': h.caller, 'decision': {
                'id': 'fixture-missing-mapping-owner', 'scope': 'plan:fixture-missing-mapping',
                'quote': quote, 'source': str(source), 'source_sha256': sha(source.read_bytes()),
                'reason': 'invented regression fixture'}})
            h.job_ok('plan-revision', {'caller': h.caller, 'revision': {
                'id': 'fixture-missing-mapping', 'owner_decision_id': 'fixture-missing-mapping-owner'},
                                       'new_plan': {'tasks': tasks}})
            code, out = h.admit_slot(0, 'first-impression', 'fi-01-r0')
            self.assertEqual((code, out['error']['code']), (1, 'job_slot_stale'), out)
            self.assertEqual(h.charged(), before)


    def test_9_exhausted_pilot_keeps_rejected_transports_traces_charges_and_approval(self):
        self.adopt()
        base = STATE['base'] / 'handoff-exhausted'
        base.mkdir()
        with Swap(self.inst, self.inst['env'], base):
            h = HandoffHost(base, self.inst['package'])
            limits = h.draft()['limits']
            limits['max_attempts_per_slot'] = 2
            h.start(mode='capture-only', limits=limits)

            def invalid_transport(result):
                result['artifacts'][0]['size'] = result['artifacts'][0].pop('bytes')

            initial = h.begin()
            self.assertEqual(h.trace(initial)[0], 0)
            self.assertEqual(h.finish(initial, invalid_transport)[1][0], 1)
            study = h.root / h.view['study_id']
            retained = {p: p.read_bytes() for folder in ('results', 'focus-group/sessions',
                         'focus-group/evidence/traces', 'focus-group/approvals') for p in (study / folder).rglob('*')
                        if p.is_file()}
            self.assertTrue(retained)
            h.job_ok('retry', {'caller': h.caller, 'task_id': initial['task'], 'reason': 'fixture transport repair'})
            request = next(t['request_id'] for t in h.job_state()['tasks'] if t['task_id'] == initial['task'])
            repair = h.begin(request=request)
            self.assertEqual(h.trace(repair)[0], 0)
            self.assertEqual(h.finish(repair, invalid_transport)[1][0], 1)
            before = h.charged()
            code, out = h.admit_slot(0, 'first-impression', 'silent-third-attempt', purpose='repair')
            self.assertEqual((code, out['error']['code']), (1, 'budget_exhausted'), out)
            code, out = h.job('retry', {'caller': h.caller, 'task_id': initial['task'], 'reason': 'silent third'})
            self.assertNotEqual(code, 0, out)
            self.assertEqual(h.charged(), before)
            self.assertEqual(before, {'first': 1, 'participant_repairs': 1})
            for path, data in retained.items():
                self.assertEqual(path.read_bytes(), data, path.name)


    def test_9b_fresh_retry_uses_normal_brief_and_accepts_without_losing_retired_trace(self):
        self.adopt()
        base = STATE['base'] / 'handoff-fresh-retry'
        base.mkdir()
        with Swap(self.inst, audited(self.inst['env'], base), base):
            h = HandoffHost(base, self.inst['package'])
            h.start(personas=1, mode='capture-only')
            initial = h.begin()
            initial_bound = self.assert_prepared_binding(h, initial)
            self.assertEqual(h.trace(initial)[0], 0)

            def invalid_transport(result):
                result['artifacts'][0]['size'] = result['artifacts'][0].pop('bytes')

            self.assertEqual(h.finish(initial, invalid_transport)[1][0], 1)
            study = h.root / h.view['study_id']
            retained = {p: p.read_bytes() for folder in ('briefs', 'results', 'focus-group/sessions',
                         'focus-group/evidence/traces', 'focus-group/approvals') for p in (study / folder).rglob('*')
                        if p.is_file()}
            h.job_ok('retry', {'caller': h.caller, 'task_id': initial['task'], 'reason': 'fixture transport repair'})
            request = next(t['request_id'] for t in h.job_state()['tasks'] if t['task_id'] == initial['task'])
            repair = h.begin(request=request)
            self.assertNotEqual(repair['host'], initial['host'])
            self.assertNotEqual(request, initial['request'])
            self.assertEqual(Path(repair['outer']['path']),
                             study / 'briefs' / f'{repair["task"]}-{sha(request.encode())}.json')
            self.assertFalse((study / 'briefs/followup').exists())
            self.assertEqual(self.assert_prepared_binding(h, initial), initial_bound)
            repair_bound = self.assert_prepared_binding(h, repair)
            self.assertNotEqual(initial_bound, repair_bound)
            self.assertNotEqual(initial['brief']['effective_brief_sha256'], repair['brief']['effective_brief_sha256'])

            # Damage only disposable brief files. Keep the cached run and persisted job/history
            # untouched so each refusal comes from the real installed validator, not the fixture.
            retired_path = Path(initial_bound['path'])
            retired_bytes = retired_path.read_bytes()
            tampered = json.loads(retired_bytes)
            tampered['constraints'].append('Invented altered constraint')
            tampered.pop('effective_brief_sha256')
            tampered['effective_brief_sha256'] = sha((json.dumps(
                tampered, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode())
            before_job, before_ledger = (study / 'job.json').read_bytes(), h.ledger_bytes()
            for damage, replacement, message in (
                    ('missing', None, 'no readable prepared JSON brief'),
                    ('foreign', Path(repair_bound['path']).read_bytes(), 'differs from this task, request'),
                    ('tampered', json.dumps(tampered).encode(), 'differs from an earlier trace binding')):
                with self.subTest(retired_brief=damage):
                    try:
                        if replacement is None:
                            retired_path.unlink()
                        else:
                            retired_path.write_bytes(replacement)
                        code, refused = h.trace(initial)
                        self.assertEqual((code, refused.get('error', {}).get('code')), (1, 'trace_unbound'), refused)
                        self.assertIn(message, refused['error']['message'])
                    finally:
                        retired_path.write_bytes(retired_bytes)
                    self.assertEqual((study / 'job.json').read_bytes(), before_job)
                    self.assertEqual(h.ledger_bytes(), before_ledger)
                    for path, data in retained.items():
                        self.assertEqual(path.read_bytes(), data, path.name)
            self.assertEqual(self.assert_prepared_binding(h, initial), initial_bound)
            self.assertEqual(h.trace(initial)[0], 0)  # retired normal brief remains bound after replacement
            code, trace = h.trace(repair)
            self.assertEqual((code, trace['data']['attempt_compliance']), (0, 'clean-in-trace'), trace)
            delivered, outcome = h.finish(repair)
            self.assertEqual((delivered[0], outcome[0]), (0, 0), (delivered, outcome))
            task = next(t for t in h.job_state()['tasks'] if t['task_id'] == repair['task'])
            self.assertEqual([r['request_id'] for r in task['execution_history']], [initial['request'], request])
            self.assertTrue(task['execution_history'][0]['malformed'])
            self.assertEqual(task['attempt'], 2)
            self.assertEqual(h.charged(), {'first': 1, 'participant_repairs': 1})
            for path, data in retained.items():
                self.assertEqual(path.read_bytes(), data, path.name)
            for n in range(1, len(h.view['cells'])):
                run = h.begin(n)
                self.assertEqual(h.trace(run)[0], 0)
                self.assertEqual(h.finish(run)[1][0], 0)
            code, gate = h.accept('first-impression')
            self.assertEqual((code, gate.get('accepted')), (0, True), gate)
        rows = audit_rows(base)
        self.assertIn('validate_study.py', {Path(r['script']).name for r in rows})
        self.assertEqual(sorted({hit for row in rows for hit in row['hits']}), [])


    def test_9c_same_child_followup_is_refused_and_unexpected_host_work_stays_non_accepting(self):
        self.adopt()
        base = STATE['base'] / 'handoff-forbidden-followup'
        base.mkdir()
        with Swap(self.inst, audited(self.inst['env'], base), base):
            h = HandoffHost(base, self.inst['package'])
            h.start(mode='capture-only')
            initial = h.begin()
            self.assertEqual(h.trace(initial)[0], 0)

            def invalid_transport(result):
                result['artifacts'][0]['size'] = result['artifacts'][0].pop('bytes')

            self.assertEqual(h.finish(initial, invalid_transport)[1][0], 1)
            study = h.root / h.view['study_id']
            before, ledger = (study / 'job.json').read_bytes(), h.ledger_bytes()
            request, host, completion = 'fi-01-forbidden', 'host-forbidden', 'done-forbidden'
            code, error = h.job('followup-prepare', {'caller': h.caller, 'task_id': initial['task'],
                                                   'request_id': request})
            self.assertEqual(code, 2, error)
            self.assertIn('document-only slots require a fresh declared execution', error)
            self.assertEqual((study / 'job.json').read_bytes(), before)
            self.assertEqual(h.ledger_bytes(), ledger)
            self.assertFalse((study / 'briefs/followup').exists())
            # Even a study admission cannot authorise a same-child continuation. Record unexpected
            # host work through the public helper so it remains an owned reconciliation obligation.
            self.assertEqual(h.admit_slot(0, 'first-impression', request, purpose='repair')[0], 0)
            task = next(t for t in h.job_state()['tasks'] if t['task_id'] == initial['task'])
            self.assertEqual(h.observe(initial['task'], kind='followup', request_id=request, host_task_id=host,
                                       parent_host_task_id=initial['host'], child_thread_id=f'thread-{initial["host"]}',
                                       target=task['target'], scope=task['write_scope'],
                                       status_identity=h.target_of(0))[0], 0)
            current = next(t for t in h.job_state()['tasks'] if t['task_id'] == initial['task'])
            self.assertTrue(current['followups'][0]['forbidden_followup'])
            self.assertIsNone(current['forbidden_followups'][0]['reconciled'])
            self.assertEqual((current['request_id'], current['brief']), (initial['request'], initial['outer']))
            code, trace = h.trace(dict(initial, request=request, host=host))
            self.assertEqual((code, trace['error']['code']), (1, 'trace_unbound'), trace)
            self.assertEqual(h.complete(initial['task'], request, host, completion)[0], 0)
            transport = h.transport(h.worker_result(initial['brief'], [initial['item']], request_id=request))
            self.assertEqual(h.deliver(initial['task'], request, completion, transport)[0], 0)
            current = next(t for t in h.job_state()['tasks'] if t['task_id'] == initial['task'])
            execution = current['execution_history'][-1]
            self.assertEqual((execution['request_id'], execution['accepted_execution'], execution['quarantined']),
                             (request, False, True))
            self.assertEqual((study / 'results/quarantine' / f'{request}.json').read_bytes(), transport.read_bytes())
            self.assertEqual(current.get('result_ref'), task.get('result_ref'))
            code, refused = h.ingest(initial['task'], request, completion, transport)
            self.assertEqual((code, refused['error']['code']), (1, 'malformed_result'), refused)
            self.assertIn('forbidden continued review or document-only follow-up', refused['error']['message'])
            self.assertEqual(h.complete(initial['task'], request, host, completion, kind='reconciled')[0], 0)
            h.reconcile()
            current = next(t for t in h.job_state()['tasks'] if t['task_id'] == initial['task'])
            self.assertIsNotNone(current['forbidden_followups'][0]['reconciled'])
            self.assertEqual(current['attempt'], 2)
            self.assertEqual(h.charged(), {'first': 1, 'participant_repairs': 1})
            self.assertFalse((study / 'briefs/followup').exists())
            self.assertEqual(h.trace(initial)[0], 0)
            code, gate = h.accept('first-impression')
            self.assertFalse(gate.get('accepted'), (code, gate))
        self.assertEqual(sorted({hit for row in audit_rows(base) for hit in row['hits']}), [])



if __name__ == '__main__':
    unittest.main()
