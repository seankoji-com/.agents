"""Pass 14 regressions for the accepted pass 13 Stage 3 findings (R13-ST-01..03) and the
identity sweep they prompted; synthetic data only, no live models."""
import json
import tempfile
import unittest
from pathlib import Path

from core.jobs import JobError, create_job, prepare, record_dispatch, record_result, retry_task, revise_plan
from core.jobs.store import Store, digest
from shared.job_coordinator import dispose_finding, prepare_followup
from tests.test_issue28_pass10 import Pass10Fixture
from tests.test_jobs_review import fixture_decision

STAGE_CONTRACT = ('id', 'depends_on', 'requirements', 'criteria', 'resources', 'validator_dependency',
                  'validator_contract', 'revision', 'outputs', 'stop_conditions', 'execution_mode', 'validator_limits')


def ok(*_):
    return True


class Pass14Fixture(Pass10Fixture):
    def store(self, root, extra=()):
        """t0 in slot s0/primary plus extra (task_id, slot, request) worker slots in s0."""
        job = self.fx.fx.base_job('identity')
        job['pins']['ape']['effective_workers'] = {
            'ape/source-researcher': {'bytes': 'synthetic pinned worker', 'sha256': 'b' * 64}}
        for task_id, slot, request in extra:
            job['tasks'].append({**job['tasks'][0], 'task_id': task_id, 'logical_slot_id': slot, 'request_id': request,
                                 'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task_id}})
        create_job(job, root, job['pins'])
        return Store(root, 'identity')

    def ready(self, store, task_id='t0', request='req0', host='host0', observe=True, completion=None, result=None):
        ref = prepare(store, self.caller, task_id, ok, ok)
        if observe:
            self.observe(store, task_id, 'accepted', request, host)
        body = result(ref['path']) if result else self.result_for(ref['path'])
        record_result(store, self.caller, task_id, {'request_id': request, 'completion_id': completion or request + '-done',
                                                    'result': json.dumps(body).encode()})
        if observe:
            self.observe(store, task_id, 'completion', request, host)
        return ref

    def revision(self, store, revision_id, edit):
        fixture_decision(store, self.caller, {'id': 'd-' + revision_id, 'quote': 'Owner approves plan ' + revision_id,
                                              'scope': 'plan:' + revision_id})
        plan = store.load()
        edit(plan)
        return lambda: revise_plan(store, self.caller, {'id': revision_id, 'owner_decision_id': 'd-' + revision_id}, plan)

    def slot(self, task_id, request, slot='primary'):
        return {'task_id': task_id, 'stage_id': 's0', 'logical_slot_id': slot, 'request_id': request,
                'worker_id': 'ape/source-researcher', 'dependency_key': 'ape',
                'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task_id}}

    def replace_slot(self, store, revision_id, old, new):
        """Owner-approved revision removing task ``old`` and adding ``new`` (same stage)."""
        return self.revision(store, revision_id, lambda p: p.update(tasks=[t for t in p['tasks'] if t['task_id'] != old] + [new]))

    def refused(self, store, call, message):
        before = store.file.read_bytes()
        with self.assertRaisesRegex(JobError, message):
            call()
        self.assertEqual(store.file.read_bytes(), before)

    def task(self, store, task_id):
        return next(t for t in store.load()['tasks'] if t['task_id'] == task_id)


class Pass14StageIdentityTests(Pass14Fixture):
    """R13-ST-01: a stage ID retained by superseded-plan history cannot return with a fresh validation budget."""

    def test_r13_st_01_removed_exhausted_stage_cannot_be_restored_with_reset_counters(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            # s1 is a direct stage whose initial validation plus three repairs are spent (policy max_repair_cycles=3).
            self.edit(store, lambda s: s['stages'][1].update(execution_mode='direct', cycle=3, validated_cycle=3,
                                                             acceptance_runs=4, status='failed'))
            declared = {k: v for k, v in store.load()['stages'][1].items() if k in STAGE_CONTRACT}
            self.revision(store, 'drop-s1', lambda p: p.update(stages=p['stages'][:1]))()
            self.assertEqual([s['id'] for s in store.load()['stages']], ['s0'])
            history = [s for h in store.load()['history'] for s in h.get('stages', []) if s['id'] == 's1']
            self.assertEqual([(s['cycle'], s['acceptance_runs']) for s in history], [(3, 4)])
            restore = self.revision(store, 'restore-s1', lambda p: p['stages'].append({**declared, 'status': 'pending'}))
            self.refused(store, restore, 'retained by job history')
            self.assertEqual([s['id'] for s in store.load()['stages']], ['s0'])
            # Positive control: an owner-approved stage under a fresh identity is still a legitimate expansion.
            self.revision(store, 'add-s2', lambda p: p['stages'].append({**declared, 'id': 's2', 'status': 'pending'}))()
            self.assertEqual([s['id'] for s in store.load()['stages']], ['s0', 's2'])


class Pass14CompletionIdentityTests(Pass14Fixture):
    """R13-ST-02: completion IDs stay bound to one request across removed tasks and retries."""

    def replacement(self, store):
        """Ingest t0 directly with completion-shared, remove it, add t1 in the same slot and charge its repair."""
        self.ready(store, observe=False, completion='completion-shared')
        self.replace_slot(store, 'replace-t0', 't0', self.slot('t1', 'req-t1'))()
        retry_task(store, self.caller, 't1', 'charged replacement for the inherited slot budget')
        request = self.task(store, 't1')['request_id']
        ref = prepare(store, self.caller, 't1', ok, ok)
        raw = json.dumps(self.result_for(ref['path'])).encode()
        return request, lambda cid: record_result(store, self.caller, 't1', {'request_id': request, 'completion_id': cid, 'result': raw})

    def test_r13_st_02_removed_task_completion_id_cannot_be_ingested_for_a_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            request, ingest = self.replacement(store)
            self.refused(store, lambda: ingest('completion-shared'), 'belongs to another request')
            self.assertFalse((store.path / 'results' / (request + '.json')).exists())
            self.assertEqual(self.task(store, 't1')['attempt'], 1)  # inherited charge only; refusal charged nothing
            # Positive control: a fresh completion identity is ingested normally.
            self.assertEqual(ingest('completion-t1')['status'], 'awaiting-acceptance')

    def test_r13_st_02_host_completion_notification_cannot_reuse_a_removed_task_completion(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            request, _ = self.replacement(store)
            self.observe(store, 't1', 'accepted', request, 'host1')
            self.refused(store, lambda: self.observe(store, 't1', 'completion', request, 'host1', completion_id='completion-shared'),
                         'cannot belong to another request')
            self.observe(store, 't1', 'completion', request, 'host1', completion_id='host1-done')
            self.assertEqual([n['completion_id'] for n in store.load()['notifications']], ['host1-done'])

    def test_r13_sweep_retry_reusing_its_own_prior_completion_id_is_refused_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store, observe=False, completion='c0')
            retry_task(store, self.caller, 't0', 'repair')
            request = self.task(store, 't0')['request_id']
            ref = prepare(store, self.caller, 't0', ok, ok)
            raw = json.dumps(self.result_for(ref['path'])).encode()
            ingest = lambda cid: record_result(store, self.caller, 't0', {'request_id': request, 'completion_id': cid, 'result': raw})
            self.refused(store, lambda: ingest('c0'), 'belongs to another request')
            self.assertEqual(ingest('c1')['status'], 'awaiting-acceptance')
            self.assertEqual([h['completion_id'] for h in self.task(store, 't0')['execution_history']], ['c0', 'c1'])
            self.assertEqual(ingest('c1')['attempt'], 2)  # same request + completion stays idempotent


class Pass14BriefPathTests(Pass14Fixture):
    """R13-ST-03: normal and follow-up briefs use distinct, fixed-width encodings."""

    def test_r13_st_03_followup_and_normal_briefs_cannot_collide(self):
        followup = digest(b'reqX')  # a valid request ID that formerly aliased task t0-followup's normal brief
        for order in ('followup-first', 'normal-first'):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as td:
                store = self.store(td, [('t0-followup', 'support', 'reqX')])
                self.ready(store)
                stage = lambda: prepare_followup(store, self.caller, 't0', followup)
                fresh = lambda: prepare(store, self.caller, 't0-followup', ok, ok)
                if order == 'followup-first':
                    staged, normal = stage(), fresh()
                else:
                    normal, staged = fresh(), stage()
                self.assertNotEqual(staged['path'], normal['path'])
                self.assertEqual(Path(staged['path']).parent, store.path / 'briefs' / 'followup')
                self.assertEqual(Path(normal['path']).parent, store.path / 'briefs')
                self.assertEqual(json.loads(Path(staged['path']).read_text())['task_id'], 't0')
                self.assertEqual(json.loads(Path(normal['path']).read_text())['task_id'], 't0-followup')

    def test_r13_st_03_followup_result_uses_the_followup_brief_directory(self):
        # R16-ST-01: the follow-up result is available here, so it is read before the retry supersedes it.
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            staged = prepare_followup(store, self.caller, 't0', 'fu1')
            self.assertEqual(staged['path'], str(store.path / 'briefs' / 'followup' / ('t0-' + digest(b'fu1') + '.json')))
            self.observe(store, 't0', 'followup', 'fu1', 'host-f', parent_host_task_id='host0', target=None,
                         scope={'mode': 'worker-evidence', 'path': 'artifacts/tasks/t0'})
            self.observe(store, 't0', 'reconciled', 'fu1', 'host-f')
            self.ingest(store, 't0', self.result_for(staged['path']))
            read = self.task(store, 't0')
            followup = [h for h in read['execution_history'] if h['request_id'] == 'fu1']
            self.assertEqual(len(followup), 1)
            self.assertFalse(followup[0].get('malformed'))
            self.assertEqual(read['request_id'], 'fu1')  # the follow-up adopted the task under its frozen brief
            retry_task(store, self.caller, 't0', 'repair after follow-up')
            task = self.task(store, 't0')
            self.assertEqual(task['status'], 'pending')
            self.assertEqual([h['request_id'] for h in task['execution_history']], ['req0', 'fu1'])


class Pass14IdentitySweepTests(Pass14Fixture):
    """Siblings of 'identity released or reset by plan history, retry or follow-up'."""

    def test_sweep_host_task_id_of_a_removed_task_cannot_be_accepted_for_another_request(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.ready(store, 't1', 'req1', 'host1')
            self.revision(store, 'drop-t1', lambda p: p.update(tasks=p['tasks'][:1]))()
            prepare(store, self.caller, 't0', ok, ok)
            self.refused(store, lambda: self.observe(store, 't0', 'accepted', 'req0', 'host1'), 'already belongs to another request')
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.assertEqual([h['task_id'] for h in self.task(store, 't0')['handles']], ['host0'])

    def test_sweep_capacity_notification_is_consumed_once_per_job(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1'), ('t2', 'review-slot', 'req2')])
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.observe(store, 't0', 'completion', 'req0', 'host0')
            deferred = {'kind': 'capacity-deferred', 'completion_id': 'host0-done'}
            record_dispatch(store, self.caller, 't1', dict(deferred, request_id='req1'))
            self.refused(store, lambda: record_dispatch(store, self.caller, 't2', dict(deferred, request_id='req2')),
                         'new owned completion notification')
            record_dispatch(store, self.caller, 't2', {'kind': 'capacity-deferred', 'request_id': 'req2'})  # deferral without a retry claim
            self.assertNotIn('capacity_retry_events', self.task(store, 't2'))

    def test_sweep_replacement_slot_inherits_the_followup_budget(self):
        scope = {'mode': 'worker-evidence', 'path': 'artifacts/tasks/t0'}
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            staged = prepare_followup(store, self.caller, 't0', 'fu1')
            self.observe(store, 't0', 'followup', 'fu1', 'host-f', parent_host_task_id='host0', target=None, scope=scope)
            self.observe(store, 't0', 'reconciled', 'fu1', 'host-f')
            self.ingest(store, 't0', self.result_for(staged['path']))  # R15-ST-02: an accepted result must be ingested before its slot can be replaced
            self.replace_slot(store, 'replace-t0', 't0', self.slot('t1', 'req-t1'))()
            retry_task(store, self.caller, 't1', 'charged replacement')
            self.ready(store, 't1', self.task(store, 't1')['request_id'], 'host1')
            self.refused(store, lambda: prepare_followup(store, self.caller, 't1', 'fu2'), 'exceeds its declared slot')
            # Positive control: a fresh logical slot keeps its own declared follow-up.
            self.revision(store, 'add-t2', lambda p: p['tasks'].append(self.slot('t2', 'req-t2', 'other')))()
            self.ready(store, 't2', self.task(store, 't2')['request_id'], 'host2')
            prepare_followup(store, self.caller, 't2', 'fu3')

    def test_sweep_staged_followup_cannot_attach_to_a_later_attempt(self):
        scope = {'mode': 'worker-evidence', 'path': 'artifacts/tasks/t0'}
        event = lambda request, host, parent: {'kind': 'followup', 'request_id': request, 'host_task_id': host,
                                               'parent_host_task_id': parent, 'target': None, 'scope': scope}
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            prepare_followup(store, self.caller, 't0', 'fu1')
            retry_task(store, self.caller, 't0', 'repair before the follow-up launched')
            current = self.task(store, 't0')['request_id']
            # The old parent no longer owns the current request: the retry request cannot be replaced by fu1.
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', event('fu1', 'host-f', 'host0')), 'superseded request')
            self.ready(store, 't0', current, 'host-n')
            # Even under the new terminal parent, fu1's frozen brief follows req0, not the current attempt.
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', event('fu1', 'host-f', 'host-n')), 'superseded request')
            self.assertEqual(self.task(store, 't0')['request_id'], current)
            prepare_followup(store, self.caller, 't0', 'fu2')
            record_dispatch(store, self.caller, 't0', event('fu2', 'host-f2', 'host-n'))
            self.assertEqual(self.task(store, 't0')['request_id'], 'fu2')

    def test_sweep_removal_cannot_release_an_unresolved_major_finding(self):
        def adverse(path):
            body = self.result_for(path)
            body.update(review_verdict='adverse', findings=[{'id': 'F1', 'severity': 'major', 'scenario': 'synthetic',
                                                             'source_evidence': ['fixture']}])
            return body
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.ready(store, 't1', 'req1', 'host1', result=adverse)
            drop = lambda name: self.revision(store, name, lambda p: p.update(tasks=p['tasks'][:1]))
            self.refused(store, drop('drop-t1'), 'unresolved blocker or major finding')
            evidence = Path(td) / 'owner-rejection.txt'
            evidence.write_bytes(b'Owner rejects F1 for the abandoned support slot.\n')
            raw = evidence.read_bytes()
            dispose_finding(store, self.caller, 't1', 'F1', 'rejected', {'path': str(evidence), 'sha256': digest(raw), 'bytes': len(raw)})
            drop('drop-t1-disposed')()
            self.assertEqual([t['task_id'] for t in store.load()['tasks']], ['t0'])


if __name__ == '__main__':
    unittest.main()
