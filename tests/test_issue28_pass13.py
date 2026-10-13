"""Pass 13 regressions for the accepted pass 12 Stage 3 finding (R12-ST-01); synthetic data only, no live models."""
import json
import tempfile
import unittest
from pathlib import Path

from core.jobs import JobError, create_job, prepare, record_result, retry_task, revise_plan
from core.jobs.store import Store, _atomic, digest
from shared.job_coordinator import prepare_followup
from tests.test_issue28_pass10 import Pass10Fixture
from tests.test_jobs_review import fixture_decision


def ok(*_):
    return True


def retry_id(request, cycle):
    return request[:96] + '-' + digest(request.encode())[:8] + '-a' + str(cycle)


class Pass13RequestIdentityTests(Pass10Fixture):
    """R12-ST-01: request and task identities stay bound to the execution evidence that first used them."""

    def store(self, root, two_tasks=False, t1_request='req1'):
        job = self.fx.fx.base_job('identity', two_tasks=two_tasks)
        job['pins']['ape']['effective_workers'] = {
            'ape/source-researcher': {'bytes': 'synthetic pinned worker', 'sha256': 'b' * 64}}
        if two_tasks:
            job['tasks'][1]['request_id'] = t1_request
        create_job(job, root, job['pins'])
        return Store(root, 'identity')

    def ready(self, store, task_id='t0', request='req0', host='host0', observe=True):
        ref = prepare(store, self.caller, task_id, ok, ok)
        if observe:
            self.observe(store, task_id, 'accepted', request, host)
        self.ingest(store, task_id, self.result_for(ref['path']))
        if observe:
            self.observe(store, task_id, 'completion', request, host)
        return ref

    def revision(self, store, revision_id, edit):
        fixture_decision(store, self.caller, {'id': 'd-' + revision_id, 'quote': 'Owner approves plan ' + revision_id,
                                              'scope': 'plan:' + revision_id})
        plan = store.load()
        edit(plan)
        return lambda: revise_plan(store, self.caller, {'id': revision_id, 'owner_decision_id': 'd-' + revision_id}, plan)

    def add_slot(self, store, revision_id, request, task_id='t1', slot='support'):
        def edit(plan):
            base = plan['tasks'][0]
            plan['tasks'].append({'task_id': task_id, 'stage_id': base['stage_id'], 'logical_slot_id': slot,
                                  'request_id': request, 'worker_id': base['worker_id'],
                                  'dependency_key': base['dependency_key'],
                                  'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task_id}})
        return self.revision(store, revision_id, edit)

    def refused(self, store, call, message):
        before = store.file.read_bytes()
        with self.assertRaisesRegex(JobError, message):
            call()
        self.assertEqual(store.file.read_bytes(), before)

    def transport_intact(self, store, request='req0'):
        path = store.path / 'results' / (request + '.json')
        rows = [h for t in store.load()['tasks'] for h in t.get('execution_history', []) if h['request_id'] == request]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['transport_ref']['transport_path'], str(path))
        self.assertEqual(digest(path.read_bytes()), rows[0]['transport_ref']['transport_sha256'])

    def test_r12_st_01_owner_revision_cannot_reuse_a_request_retained_by_execution_history(self):
        """Review scenario: charged retry leaves req0 only in history; a new owner-approved slot cannot take it."""
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            retry_task(store, self.caller, 't0', 'charged repair')
            t0 = store.load()['tasks'][0]
            self.assertNotEqual(t0['request_id'], 'req0')
            self.assertEqual([h['request_id'] for h in t0['execution_history']], ['req0'])
            self.refused(store, self.add_slot(store, 'add-reused', 'req0'), 'retained by job history')
            self.assertEqual([t['task_id'] for t in store.load()['tasks']], ['t0'])
            self.transport_intact(store)
            # Positive control: a fresh request ID is still a legitimate owner-approved slot.
            self.add_slot(store, 'add-fresh', 'req-t1')()
            self.ready(store, 't1', 'req-t1', 'host1')
            self.transport_intact(store)
            self.transport_intact(store, 'req-t1')

    def test_r12_st_01_reserved_ids_cover_handles_retired_requests_and_removed_slots(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, two_tasks=True)
            self.ready(store)
            retry_task(store, self.caller, 't0', 'first repair')
            first_retry = store.load()['tasks'][0]['request_id']
            self.edit(store, lambda s: s['tasks'][0].update(status='failed'))
            retry_task(store, self.caller, 't0', 'second repair')  # first_retry was never dispatched
            self.assertEqual(store.load()['tasks'][0]['retired_request_ids'], ['req0', first_retry])
            # Remove the completed support slot t1: its request and task IDs stay in superseded history.
            self.ready(store, 't1', 'req1', 'host1')
            self.revision(store, 'drop-t1', lambda p: p.update(tasks=p['tasks'][:1]))()
            self.assertEqual([t['task_id'] for t in store.load()['tasks']], ['t0'])
            for name, request, task_id in (('handle-and-history', 'req0', 't9'), ('retired-undispatched', first_retry, 't9'),
                                           ('removed-slot-request', 'req1', 't9'), ('removed-task-id', 'req-new', 't1')):
                with self.subTest(source=name):
                    self.refused(store, self.add_slot(store, 'add-' + name, request, task_id), 'retained by job history')
            self.add_slot(store, 'add-fresh', 'req9', 't9')()
            self.assertEqual([t['task_id'] for t in store.load()['tasks']], ['t0', 't9'])

    def test_r12_st_01_retry_refuses_a_generated_request_retained_by_a_removed_slot(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, two_tasks=True, t1_request=retry_id('req0', 1))
            self.ready(store, 't1', retry_id('req0', 1), 'host1')
            self.revision(store, 'drop-t1', lambda p: p.update(tasks=p['tasks'][:1]))()
            self.ready(store)
            self.refused(store, lambda: retry_task(store, self.caller, 't0', 'repair'), 'retry request ID is retained')
            self.assertEqual(store.load()['tasks'][0]['request_id'], 'req0')

    def test_r12_st_01_followup_cannot_reuse_a_request_retained_only_by_execution_history(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, two_tasks=True)
            self.ready(store, observe=False)  # ingested without a host handle: req0 survives only in history
            retry_task(store, self.caller, 't0', 'repair')
            self.ready(store, 't1', 'req1', 'host1')
            self.refused(store, lambda: prepare_followup(store, self.caller, 't1', 'req0'), 'request identity')
            self.assertFalse((store.path / 'briefs' / 't1-followup-req0.json').exists())
            self.assertFalse((store.path / 'briefs' / 'followup' / ('t1-' + digest(b'req0') + '.json')).exists())  # pass14 path encoding
            self.transport_intact(store)
            prepare_followup(store, self.caller, 't1', 'fu1')
            prepare_followup(store, self.caller, 't1', 'fu1')  # re-presenting the staged follow-up stays idempotent

    def test_r12_st_01_replaced_staged_followup_request_stays_reserved(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            prepare_followup(store, self.caller, 't0', 'fu1')
            prepare_followup(store, self.caller, 't0', 'fu2')
            self.assertEqual(store.load()['tasks'][0]['retired_request_ids'], ['fu1'])
            self.refused(store, self.add_slot(store, 'add-fu1', 'fu1'), 'retained by job history')
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'request identity')

    def test_r12_st_01_result_transport_is_create_exclusive(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            ref = prepare(store, self.caller, 't0', ok, ok)
            raw = json.dumps(self.result_for(ref['path'])).encode()
            transport = store.path / 'results' / 'req0.json'
            transport.parent.mkdir(mode=0o700)
            transport.write_bytes(b'{"retained": "other execution"}')
            ingest = lambda: record_result(store, self.caller, 't0', {'request_id': 'req0', 'completion_id': 'c0', 'result': raw})
            self.refused(store, ingest, 'already retained')
            self.assertEqual(transport.read_bytes(), b'{"retained": "other execution"}')
            transport.write_bytes(raw)  # identical bytes may be re-presented (crash-safe replay)
            self.assertEqual(ingest()['status'], 'awaiting-acceptance')
            self.transport_intact(store)

    def test_r12_st_01_exclusive_write_primitive_never_replaces(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'evidence.json'
            _atomic(path, b'first', exclusive=True)
            with self.assertRaises(FileExistsError):
                _atomic(path, b'second', exclusive=True)
            self.assertEqual(path.read_bytes(), b'first')
            self.assertEqual(sorted(p.name for p in Path(td).iterdir()), ['evidence.json'])

    def test_r12_st_01_completion_id_cannot_be_reused_by_another_task(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, two_tasks=True)
            self.ready(store)
            ref = prepare(store, self.caller, 't1', ok, ok)
            raw = json.dumps(self.result_for(ref['path'])).encode()
            self.refused(store, lambda: record_result(store, self.caller, 't1', {'request_id': 'req1', 'completion_id': 'req0-done', 'result': raw}),
                         'belongs to another request')
            self.assertFalse((store.path / 'results' / 'req1.json').exists())

    def test_r12_st_01_tampered_state_reusing_a_retained_request_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, two_tasks=True)
            self.ready(store)
            retry_task(store, self.caller, 't0', 'repair')
            before = store.file.read_bytes()
            self.edit(store, lambda s: s['tasks'][1].update(request_id='req0'))
            with self.assertRaisesRegex(JobError, 'retained by another task execution'):
                prepare(store, self.caller, 't1', ok, ok)
            self.assertFalse(any(p.name.startswith('t1-') for p in (store.path / 'briefs').iterdir()))
            store.file.write_bytes(before)
            self.transport_intact(store)


if __name__ == '__main__':
    unittest.main()
