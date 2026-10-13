"""Pass 10 regressions for the accepted pass 9 Stage 3 findings; synthetic data only, no live models."""
import contextlib
import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from core import schema
from core.jobs import prepare, record_dispatch, record_result, retry_task, revise_plan, JobError
from core.jobs.store import MAX_STATE_BYTES, _atomic, _regular, canonical, digest, strict_load
from shared.job_acceptance import _adapter, _check_slots, _ready_slots, AcceptanceError
from shared.job_coordinator import prepare_followup, prepare_task, record_observation
from tests import test_jobs_review_r3 as job_fixtures
from tests.test_jobs_review import fixture_decision

ROOT = Path(__file__).resolve().parents[1]
WORKER = {'providerInstanceId': 'claudeAgent', 'model': 'claude-haiku-0', 'lineage': 'anthropic'}
REVIEWER = {'providerInstanceId': 'codex', 'model': 'gpt-0-luna', 'lineage': 'openai'}
SCOPE = {'mode': 'worker-evidence', 'path': 'artifacts/tasks/t0'}


class Pass10Fixture(unittest.TestCase):
    def setUp(self):
        self.fx = job_fixtures.Stage3Repair5Tests(); self.fx.setUp()
        self.caller = self.fx.caller()

    def result_for(self, brief_path, verdict=None, requirements=None):
        brief = json.loads(Path(brief_path).read_text())
        result = self.fx.fx.valid_result()
        for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256', 'revision'):
            result[key] = brief[key]
        result['binding'] = brief['snapshot']
        result['requirements'] = requirements or [{'id': r['id'], 'status': 'passed', 'evidence': ['fixture']} for r in brief['requirements']]
        result['review_verdict'] = verdict
        return result

    def ingest(self, store, task_id, result):
        return record_result(store, self.caller, task_id, {'request_id': result['request_id'],
            'completion_id': result['request_id'] + '-done', 'result': json.dumps(result).encode()})

    def observe(self, store, task_id, kind, request, host, **extra):
        event = {'kind': kind, 'request_id': request, 'host_task_id': host, 'child_thread_id': 'child-' + host,
                 'status': 'running', 'work_state': 'working', 'has_pending_child_runs': False}
        if kind in ('completion', 'reconciled'):
            event.update(status='completed', work_state='result_available', completion_id=host + '-done')
        event.update(extra)
        return record_dispatch(store, self.caller, task_id, event)

    def edit(self, store, change):
        state = store.load(); change(state); _atomic(store.file, canonical(state))


class Pass10JobsTests(Pass10Fixture):
    def review_store(self, root, reviewer_target):
        job = self.fx.fx.base_job('lineage')
        job['pins']['ape']['effective_workers'] = {
            'ape/source-researcher': {'bytes': 'synthetic pinned worker', 'sha256': 'b' * 64}}
        worker = job['tasks'][0]
        worker.update(target=WORKER, review_required=True, review_task_ids=['t1'])
        job['tasks'].append({**{k: v for k, v in worker.items() if k not in ('review_required', 'review_task_ids')},
                             'task_id': 't1', 'logical_slot_id': 'review', 'request_id': 'req1', 'role': 'review',
                             'reviewed_task_ids': ['t0'], 'target': reviewer_target, 'handles': [], 'followups': [],
                             'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/t1'}})
        from core.jobs import create_job
        from core.jobs.store import Store
        create_job(job, root, job['pins'])
        store = Store(root, 'lineage')
        ref = prepare(store, self.caller, 't0', lambda *_: True, lambda *_: True)
        self.observe(store, 't0', 'accepted', 'req0', 'host0')
        self.ingest(store, 't0', self.result_for(ref['path']))
        self.observe(store, 't0', 'completion', 'req0', 'host0')
        return store

    def review(self, store):
        ref = prepare_task(store, self.caller, 't1', lambda *_: True, lambda *_: True)
        self.observe(store, 't1', 'accepted', 'req1', 'host1')
        self.ingest(store, 't1', self.result_for(ref['path'], 'approve'))
        self.observe(store, 't1', 'completion', 'req1', 'host1')

    def test_r9_st_01_required_review_needs_a_different_target_and_known_lineage(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.review_store(td, REVIEWER); self.review(store)
            state = store.load()
            _check_slots(store, state, state['stages'][0])  # positive control: distinct lineage
            for name, target, message in (
                    ('same-target', WORKER, 'different model target'),
                    ('same-lineage', dict(WORKER, model='claude-opus-0'), 'different model target'),
                    ('unknown-lineage', {k: v for k, v in REVIEWER.items() if k != 'lineage'}, 'lineage is unknown')):
                with self.subTest(handle=name):
                    tampered = store.load(); tampered['tasks'][1]['handles'][0]['target'] = target
                    with self.assertRaisesRegex(AcceptanceError, message):
                        _check_slots(store, tampered, tampered['stages'][0])
        for name, target in (('same-target', WORKER), ('unknown-lineage', None)):
            with self.subTest(declared=name), tempfile.TemporaryDirectory() as td:
                store = self.review_store(td, target); before = store.file.read_bytes()
                with self.assertRaisesRegex(JobError, 'lineage'):
                    prepare_task(store, self.caller, 't1', lambda *_: True, lambda *_: True)
                self.assertEqual(store.file.read_bytes(), before)

    def test_r9_st_02_second_host_for_an_owned_followup_is_refused_and_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            ref = prepare(store, self.caller, 't0', lambda *_: True, lambda *_: True)
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.ingest(store, 't0', self.result_for(ref['path']))  # R16-ST-01: read the terminal result before staging the parent's follow-up
            self.observe(store, 't0', 'completion', 'req0', 'host0')
            prepare_followup(store, self.caller, 't0', 'req-f')
            event = {'kind': 'followup', 'request_id': 'req-f', 'host_task_id': 'host1',
                     'parent_host_task_id': 'host0', 'target': None, 'scope': SCOPE}
            record_observation(store, self.caller, 't0', event)
            record_observation(store, self.caller, 't0', event)  # same host stays idempotent
            before = store.file.read_bytes()
            with self.assertRaisesRegex(JobError, 'already has an accepted host handle'):
                record_dispatch(store, self.caller, 't0', dict(event, host_task_id='host2'))
            self.assertEqual(store.file.read_bytes(), before)
            with self.assertRaisesRegex(JobError, 'already has an accepted host handle'):
                record_observation(store, self.caller, 't0', dict(event, host_task_id='host2'))
            state = store.load(); task = state['tasks'][0]
            self.assertEqual([h['task_id'] for h in task['followups']], ['host1'])
            self.assertEqual(task['host_conflicts'][0]['host_task_id'], 'host2')
            self.assertTrue(any(b['kind'] == 'conflicting-host-handle' and b['host_task_id'] == 'host2' for b in state['blockers']))
            with self.assertRaisesRegex(AcceptanceError, 'conflicting host handle'):
                _check_slots(store, state, state['stages'][0])

    def test_r9_st_03_uncertain_original_needs_authoritative_observation_before_ingestion(self):
        for calls in (1, 3):
            with self.subTest(calls=calls), tempfile.TemporaryDirectory() as td:
                store = self.fx.store(td)
                ref = prepare(store, self.caller, 't0', lambda *_: True, lambda *_: True)
                for _ in range(calls):
                    record_dispatch(store, self.caller, 't0', {'kind': 'uncertain', 'request_id': 'req0'})
                before = store.file.read_bytes(); result = self.result_for(ref['path'])
                with self.assertRaisesRegex(JobError, 'not for an owned request'):
                    self.ingest(store, 't0', result)
                self.assertEqual(store.file.read_bytes(), before)
                self.observe(store, 't0', 'accepted', 'req0', 'host0')  # authoritative reconciliation
                self.ingest(store, 't0', result)
                state = store.load(); self.assertEqual(state['tasks'][0]['status'], 'awaiting-acceptance')
                # Pass 11 (R10-ST-03): acceptance also needs the handle terminal with result_available.
                self.observe(store, 't0', 'completion', 'req0', 'host0')
                state = store.load()
                _check_slots(store, state, state['stages'][0])

    def test_r9_st_03_acceptance_refuses_unreconciled_uncertainty(self):
        for fields in ({'uncertain_calls': 3, 'blocked_reason': 'uncertain_dispatch'}, {'uncertain_calls': 1},
                       {'blocked_reason': 'uncertain_dispatch'}):
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as td:
                store = self.fx.store(td)
                ref = prepare(store, self.caller, 't0', lambda *_: True, lambda *_: True)
                self.ingest(store, 't0', self.result_for(ref['path']))
                state = store.load(); _check_slots(store, state, state['stages'][0])  # positive control
                self.edit(store, lambda s: s['tasks'][0].update(fields))
                state = store.load()
                with self.assertRaisesRegex(AcceptanceError, 'uncertain dispatch'):
                    _check_slots(store, state, state['stages'][0])

    def test_r9_st_04_superseded_followup_result_uses_followup_brief(self):
        # R16-ST-01: an owned terminal result must be read before a supersession. The follow-up result is
        # therefore ingested through its own frozen follow-up brief before the retry, and the retry then
        # supersedes a task whose follow-up execution is already retained.
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            ref = prepare(store, self.caller, 't0', lambda *_: True, lambda *_: True)
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.ingest(store, 't0', self.result_for(ref['path']))  # read the original result before any supersession
            self.observe(store, 't0', 'completion', 'req0', 'host0')
            followup = prepare_followup(store, self.caller, 't0', 'req-f')
            record_dispatch(store, self.caller, 't0', {'kind': 'followup', 'request_id': 'req-f', 'host_task_id': 'host1',
                                                       'parent_host_task_id': 'host0', 'target': None, 'scope': SCOPE})
            self.observe(store, 't0', 'reconciled', 'req-f', 'host1')
            self.ingest(store, 't0', self.result_for(followup['path']))  # resolves the follow-up brief, not the current one
            read = store.load()['tasks'][0]
            self.assertEqual(read['execution_history'][-1]['request_id'], 'req-f')
            self.assertNotIn('malformed', read['execution_history'][-1])
            retry_task(store, self.caller, 't0', 'superseded follow-up')
            task = store.load()['tasks'][0]
            self.assertEqual(task['status'], 'pending')
            self.assertNotEqual(task['request_id'], 'req-f')
            self.assertEqual([h['request_id'] for h in task['execution_history']], ['req0', 'req-f'])

    def test_r9_st_05_plan_decision_source_is_reverified_when_used(self):
        for tamper in (False, True):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as td:
                store = self.fx.store(td)
                fixture_decision(store, self.caller, {'id': 'd1', 'quote': 'Owner approves dropping the constraint', 'scope': 'plan:rev1'})
                if tamper:
                    source = Path(store.load()['decisions'][0]['source'])
                    source.write_text(source.read_text() + 'edited after recording\n')
                plan = store.load(); plan['constraints'] = []
                revision = {'id': 'rev1', 'owner_decision_id': 'd1'}
                if tamper:
                    with self.assertRaisesRegex(JobError, 'owner decision required'):
                        revise_plan(store, self.caller, revision, plan)
                else:
                    revise_plan(store, self.caller, revision, plan)
                    self.assertEqual(store.load()['constraints'], [])

    def test_r9_st_05_waiver_source_is_reverified_at_ingestion_and_acceptance(self):
        for stage in ('ingestion', 'acceptance'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as td:
                store = self.fx.store(td)
                self.edit(store, lambda s: s['policy'].update(waivable_requirements=['R1']))
                fixture_decision(store, self.caller, {'id': 'w1', 'quote': 'Owner waives R1', 'scope': 'waiver:t0',
                                                      'requirement_ids': ['R1']})
                owner = store.load()['decisions'][0]; source = Path(owner['source'])
                ref = prepare(store, self.caller, 't0', lambda *_: True, lambda *_: True)
                waived = [{'id': 'R1', 'status': 'waived', 'evidence': ['owner'], 'reason': 'fixture', 'owner_evidence': owner}]
                result = self.result_for(ref['path'], requirements=waived)
                if stage == 'ingestion':
                    source.write_text('replaced owner text\n')
                    self.ingest(store, 't0', result)
                    task = store.load()['tasks'][0]
                    self.assertEqual(task['status'], 'failed')
                    self.assertIn('waiver is not a recorded', task['execution_history'][-1]['reason'])
                else:
                    self.ingest(store, 't0', result)
                    state = store.load(); _check_slots(store, state, state['stages'][0])  # positive control
                    source.write_text(source.read_text() + 'edited after ingestion\n')
                    with self.assertRaisesRegex(AcceptanceError, 'waiver is not a recorded'):
                        _ready_slots(store, state, state['stages'][0])

    def test_r9_st_06_descriptor_reads_are_bounded_before_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); large = base / 'large.json'
            with open(large, 'wb') as handle:
                handle.truncate(MAX_STATE_BYTES + 1)
            with self.assertRaisesRegex(JobError, 'oversized'):
                _regular(large)
            pkg = base / 'pkg'; (pkg / 'scripts').mkdir(parents=True)
            program = pkg / 'scripts' / 'validate_stage.py'; program.write_text('# synthetic adapter\n')
            observations = base / 'bounded' / 'observations'; observations.mkdir(parents=True)
            state_root = str(base / 'state'); plan = base / 'final-plan.json'
            descriptor = observations / 's0.json'
            descriptor.write_text(json.dumps({'state_root': state_root, 'final_plan': str(plan)}))
            raw = descriptor.read_bytes()
            job = {'job_id': 'bounded', 'dependencies': [{'key': 'imps', 'plugin': 'imps'}],
                   'pins': {'imps': {'package_dir': str(pkg)}}, 'policy': {'max_artifact_bytes': 1024}, 'decisions': []}
            stage = {'id': 's0', 'validator_dependency': 'imps',
                     'observation_ref': {'path': str(descriptor), 'root': str(observations), 'sha256': digest(raw), 'bytes': len(raw)},
                     'validator_contract': {'final_plan': {'required_stages': ['s'], 'stages': []}}}
            argv = [str(program), '--state-root', state_root, '--final-plan', str(plan)]
            document = json.dumps({'state_root': state_root, 'required_stages': ['s'], 'stages': []})
            plan.write_text(document)
            self.assertEqual(_adapter(job, stage, argv, str(descriptor))[2]['expected_outcome_ids'], ['imps-stage-s'])
            plan.write_text(document + ' ' * 2048)
            with self.assertRaisesRegex(JobError, 'oversized'):
                _adapter(job, stage, argv, str(descriptor))


class Pass10InputTests(unittest.TestCase):
    DEEP = '[' * 100000 + ']' * 100000

    def test_r9_st_07_deeply_nested_json_exits_2_with_an_error(self):
        from shared import job_acceptance_cli, job_cli
        with self.assertRaisesRegex(JobError, 'invalid JSON'):
            strict_load(self.DEEP)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'deep.json'; path.write_text(self.DEEP)
            state = str(Path(td) / 'state')
            for name, main, argv in (
                    ('job_cli', job_cli.main, ['create', '--state-root', state, '--job', 'deep', '--input', str(path),
                                               '--prefix', td, '--agents-root', td]),
                    ('job_acceptance_cli', job_acceptance_cli.main, ['validate', '--state-root', state, '--job', 'deep',
                                                                     '--input', str(path)])):
                with self.subTest(cli=name):
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        self.assertEqual(main(argv), 2)
                    self.assertIn('invalid JSON', err.getvalue())
            # Recursion raised after parsing is also an invalid-input exit, not a traceback.
            path.write_text(json.dumps({'job_id': 'deep'}))
            err = io.StringIO()
            with mock.patch('shared.job_cli.create_pinned_job', side_effect=RecursionError('nested')), contextlib.redirect_stderr(err):
                self.assertEqual(job_cli.main(['create', '--state-root', state, '--job', 'deep', '--input', str(path),
                                               '--prefix', td, '--agents-root', td]), 2)
            self.assertIn('job_error', err.getvalue())

    def test_r9_st_08_every_shared_agent_schema_loads_and_resolves(self):
        files = sorted((ROOT / 'shared' / 'agents').glob('*.schema.json'))
        self.assertGreaterEqual(len(files), 8)
        for path in files:
            with self.subTest(schema=path.name):
                loaded = schema.load_schema_file(path)
                pending = [loaded]
                while pending:
                    node = pending.pop()
                    if isinstance(node, dict):
                        if '$ref' in node:
                            schema._resolve(loaded, node['$ref'])
                        pending.extend(node.values())
                    elif isinstance(node, list):
                        pending.extend(node)

    def test_r9_st_08_envelope_and_manifest_schemas_validate_their_variants(self):
        agents = ROOT / 'shared' / 'agents'
        envelope = schema.load_schema_file(agents / 'result-envelope.schema.json')
        full = schema.load_schema_file(agents / 'worker-result.schema.json')
        self.assertEqual(envelope['$defs']['worker_result'], {k: v for k, v in full.items() if k != '$schema'})
        from tests.test_jobs_review import JobReviewTests
        result = JobReviewTests().valid_result()
        artifact = {'schema_version': 1, 'correlation': {}, 'artifact': {
            'path': 'artifacts/tasks/t0/full.json', 'sha256': 'a' * 64, 'finding_count': 0, 'finding_ids': []}}
        self.assertEqual(schema.errors(result, envelope), [])
        self.assertEqual(schema.errors(artifact, envelope), [])
        self.assertTrue(schema.errors({'schema_version': 1}, envelope))
        manifest = schema.load_schema_file(agents / 'manifest.schema.json')
        record = {'schema_version': 1, 'installation_id': str(uuid.uuid4()), 'plugin': 'ape', 'package_version': '1.0.0',
                  'package_digest': 'a' * 64, 'assets': [{'path': 'workers/x.md', 'sha256': 'b' * 64, 'size': 1}]}
        self.assertEqual(schema.errors(record, manifest), [])
        self.assertTrue(schema.errors(dict(record, installation_id='not-a-uuid'), manifest))


if __name__ == '__main__':
    unittest.main()
