"""Pass 11 regressions for the accepted pass 10 Stage 3 findings; synthetic data only, no live models."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.jobs import JobError, prepare, record_dispatch, retry_task
from core.jobs.store import canonical, digest
from shared.job_acceptance import AcceptanceError, _check_slots, _pending
from shared.job_coordinator import dispose_finding, prepare_followup, record_observation
from tests.test_issue28_pass10 import SCOPE, Pass10Fixture


def ok(*_):
    return True


class Pass11JobsTests(Pass10Fixture):
    def ready(self, store, request='req0', host='host0', **extra):
        """Prepare, accept, ingest and terminally reconcile the current request."""
        ref = prepare(store, self.caller, 't0', ok, ok)
        self.observe(store, 't0', 'accepted', request, host)
        result = self.result_for(ref['path'])
        result.update(extra)
        self.ingest(store, 't0', result)
        self.observe(store, 't0', 'completion', request, host)
        return ref

    def check(self, store):
        state = store.load()
        _check_slots(store, state, state['stages'][0])

    def refused(self, store, call, error, message):
        before = store.file.read_bytes()
        with self.assertRaisesRegex(error, message):
            call()
        self.assertEqual(store.file.read_bytes(), before)

    def test_r10_st_01_conflicting_host_blocks_retry_followup_and_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            ref = prepare(store, self.caller, 't0', ok, ok)
            self.observe(store, 't0', 'accepted', 'req0', 'h1')
            second = {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'h2', 'child_thread_id': 'child-h2',
                      'status': 'running', 'work_state': 'working', 'has_pending_child_runs': False}
            with self.assertRaisesRegex(JobError, 'already has an accepted host handle'):
                record_observation(store, self.caller, 't0', second)
            self.observe(store, 't0', 'completion', 'req0', 'h1')
            self.ingest(store, 't0', self.result_for(ref['path']))
            message = 'conflicting host handle remains unreconciled'
            self.refused(store, lambda: retry_task(store, self.caller, 't0', 'replace while h2 is live'), JobError, message)
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'req-f'), JobError, message)
            with self.assertRaisesRegex(AcceptanceError, message):
                self.check(store)
            self.assertTrue(_pending(store.load(), store.load()['stages'][0]))
            # Conflict reconciliation must be authoritative and terminal for the retained request.
            reconcile = {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'h2',
                         'status': 'cancelled', 'work_state': 'idle', 'has_pending_child_runs': False}
            for bad, why in ((dict(reconcile, status='running'), 'terminal'),
                             (dict(reconcile, has_pending_child_runs=True), 'terminal'),
                             (dict(reconcile, request_id='other'), 'request differs'),
                             ({k: v for k, v in reconcile.items() if k != 'work_state'}, 'missing work_state')):
                with self.subTest(bad=why):
                    self.refused(store, lambda: record_observation(store, self.caller, 't0', bad), JobError, why)
            record_observation(store, self.caller, 't0', reconcile)
            state = store.load()
            self.assertEqual(state['tasks'][0]['host_conflicts'][0]['reconciled']['status'], 'cancelled')
            self.assertTrue(all(b.get('reconciled') for b in state['blockers'] if b['kind'] == 'conflicting-host-handle'))
            self.check(store)  # positive control after explicit reconciliation
            with self.assertRaisesRegex(JobError, 'already has an accepted host handle'):
                record_observation(store, self.caller, 't0', second)  # a stale repeat is refused but stays reconciled
            self.assertEqual(len(store.load()['tasks'][0]['host_conflicts']), 1)
            self.check(store)
            retry_task(store, self.caller, 't0', 'charged repair after reconciliation')

    def test_r10_st_01_conflict_on_any_request_blocks_replacement_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            self.ready(store)
            self.check(store)  # positive control
            conflict = {'request_id': 'superseded-req', 'host_task_id': 'h2', 'parent_host_task_id': None,
                        'child_thread_id': 'child-h2', 'observation_kind': 'accepted', 'reason': 'fixture'}
            self.edit(store, lambda s: s['tasks'][0].update(host_conflicts=[conflict]))
            with self.assertRaisesRegex(AcceptanceError, 'conflicting host handle remains unreconciled'):
                self.check(store)
            self.edit(store, lambda s: (s['tasks'][0].pop('host_conflicts'), s.setdefault('blockers', []).append(
                {**conflict, 'kind': 'conflicting-host-handle', 'task_id': 't0'})))
            with self.assertRaisesRegex(AcceptanceError, 'conflicting host handle remains unreconciled'):
                self.check(store)

    def test_r10_st_02_uncertain_prepared_followup_blocks_replacement_retry_and_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            self.ready(store)
            followup = prepare_followup(store, self.caller, 't0', 'req-f')
            uncertain = {'kind': 'uncertain', 'request_id': 'req-f'}
            record_observation(store, self.caller, 't0', uncertain)
            task = store.load()['tasks'][0]
            self.assertEqual((task['request_id'], task['followup_dispatch']['uncertain_calls']), ('req0', 1))
            message = 'uncertain follow-up dispatch'
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'req-f2'), JobError, message)
            self.refused(store, lambda: retry_task(store, self.caller, 't0', 'replace uncertain follow-up'), JobError, message)
            with self.assertRaisesRegex(AcceptanceError, message):
                self.check(store)
            record_observation(store, self.caller, 't0', uncertain)
            record_observation(store, self.caller, 't0', uncertain)
            dispatch = store.load()['tasks'][0]['followup_dispatch']
            self.assertEqual((dispatch['uncertain_calls'], dispatch['blocked_reason']), (3, 'uncertain_dispatch'))
            self.refused(store, lambda: record_observation(store, self.caller, 't0', uncertain), JobError, 'exhausted')
            # Same-ID authoritative host observation reconciles the uncertain follow-up.
            record_observation(store, self.caller, 't0', {'kind': 'followup', 'request_id': 'req-f', 'host_task_id': 'host1',
                                                          'parent_host_task_id': 'host0', 'target': None, 'scope': SCOPE})
            self.refused(store, lambda: record_observation(store, self.caller, 't0', uncertain), JobError, 'request differs|cannot become uncertain')
            self.ingest(store, 't0', self.result_for(followup['path']))
            self.observe(store, 't0', 'completion', 'req-f', 'host1')
            self.check(store)  # positive control

    def test_r10_st_03_acceptance_requires_result_available_work_state(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            ref = prepare(store, self.caller, 't0', ok, ok)
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.observe(store, 't0', 'reconciled', 'req0', 'host0', work_state='working')
            self.ingest(store, 't0', self.result_for(ref['path']))
            state = store.load()
            self.assertEqual(state['tasks'][0]['status'], 'awaiting-acceptance')
            self.assertTrue(_pending(state, state['stages'][0]))
            with self.assertRaisesRegex(AcceptanceError, 'result_available'):
                self.check(store)
            self.observe(store, 't0', 'reconciled', 'req0', 'host0')
            state = store.load()
            self.assertFalse(_pending(state, state['stages'][0]))
            self.check(store)  # positive control

    def test_r10_st_04_reused_finding_id_with_changed_content_is_a_distinct_obligation(self):
        def finding(severity, scenario):
            return {'id': 'F', 'severity': severity, 'scenario': scenario, 'summary': severity + ' finding',
                    'source_evidence': ['fixture']}
        minor, major = finding('minor', 'cosmetic wording'), finding('major', 'data loss on retry')
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            evidence = Path(td) / 'disposition.txt'; evidence.write_text('coordinator rejection evidence\n')
            ref = {'path': str(evidence), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                   'bytes': evidence.stat().st_size}
            self.ready(store, findings=[minor])
            dispose_finding(store, self.caller, 't0', 'F', 'rejected', ref)
            retry_task(store, self.caller, 't0', 'repair pass 1')
            first = store.load()['tasks'][0]['request_id']
            self.ready(store, first, 'host1', findings=[major], review_verdict='adverse')
            retry_task(store, self.caller, 't0', 'repair pass 2')
            request = store.load()['tasks'][0]['request_id']
            self.ready(store, request, 'host2', findings=[minor])  # identical re-report deduplicates
            with self.assertRaisesRegex(AcceptanceError, 'unresolved retained blocker or major finding'):
                self.check(store)
            rows = store.load()['tasks'][0]['finding_dispositions']
            self.assertEqual([(r['finding']['severity'], r.get('request_id')) for r in rows], [('minor', 'req0'), ('major', first)])
            self.assertEqual(rows[1]['finding_sha256'], digest(canonical(major)))
            self.refused(store, lambda: dispose_finding(store, self.caller, 't0', 'F', 'rejected', ref), JobError, 'finding_sha256')
            dispose_finding(store, self.caller, 't0', 'F', 'rejected', ref, digest(canonical(major)))
            self.check(store)  # positive control after its own disposition

    def test_disposition_names_fit_ecryptfs_with_the_atomic_temp_suffix(self):
        # ecryptfs allows 143-byte names; _atomic writes '.' + name + '.' + 24 hex chars first.
        finding = {'id': 'B1R2-01', 'severity': 'major', 'scenario': 'mismatch accepted', 'summary': 'major',
                   'source_evidence': ['fixture']}
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            evidence = Path(td) / 'disposition.txt'; evidence.write_text('fixed in the repair commit\n')
            ref = {'path': str(evidence), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                   'bytes': evidence.stat().st_size}
            self.ready(store, findings=[finding], review_verdict='adverse')
            row = dispose_finding(store, self.caller, 't0', 'B1R2-01', 'fixed', ref)
            name = Path(row['evidence']['path']).name
            self.assertLessEqual(len('.' + 'pr-b1-review' + name[len('t0'):] + '.' + 'f' * 24), 143)
            self.assertEqual(Path(row['evidence']['path']).read_bytes(), evidence.read_bytes())
            self.assertEqual(store.load()['tasks'][0]['finding_dispositions'][0]['disposition'], 'fixed')


if __name__ == '__main__':
    unittest.main()
