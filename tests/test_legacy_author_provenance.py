"""Invented pre-selection executions, external anchors and carried-task authors."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from core.jobs.store import canonical, digest
from shared.job_coordinator import actual_author_lineages
from shared import model_selection as models
from tests.model_selection_fixtures import canonical_selection_input


def legacy_fixture(root, *, bound=False, target_present=False):
    job_id, task_id, request = 'legacy-fixture', 'cell', 'cell-original'
    target = {'providerInstanceId': 'fixture-gateway', 'model': 'gateway/deepseek-example', 'options': {}}
    task = {'task_id': task_id, 'stage_id': 'work', 'logical_slot_id': 'cell',
            'worker_id': 'fixture/worker', 'role': 'worker', 'request_id': request,
            'target': deepcopy(target), 'handles': [], 'followups': [], 'attempt': 1}
    brief = {k: task[k] for k in ('task_id', 'stage_id', 'logical_slot_id', 'worker_id', 'request_id')}
    brief.update(schema_version=1, job_id=job_id, role='worker', revision=None, snapshot=None)
    if target_present:
        brief['target'] = deepcopy(target)
    brief['effective_brief_sha256'] = digest(canonical(brief))
    raw = canonical(brief)
    path = root / job_id / 'briefs' / (task_id + '-' + digest(request.encode()) + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    task['brief'] = {**{k: brief[k] for k in ('job_id', 'task_id', 'stage_id', 'logical_slot_id',
                     'worker_id', 'request_id', 'effective_brief_sha256')}, 'path': str(path), 'sha256': digest(raw)}
    identity = {'status': 'verified', 'providerInstanceId': target['providerInstanceId'], 'model': target['model']}
    handle = {'request_id': request, 'task_id': 'fixture-host', 'child_thread_id': 'fixture-child',
              'target': deepcopy(target), 'observed_identity': identity, 'status': 'completed',
              'work_state': 'result_available', 'has_pending_child_runs': False}
    task['handles'] = [handle]
    task['dispatch_history'] = [{'kind': 'accepted', 'request_id': request, 'host_task_id': 'fixture-host',
                                'child_thread_id': 'fixture-child', 'status_identity': deepcopy(target)}]
    record = models.freeze(canonical_selection_input())
    job = {'job_id': job_id, 'model_selection': record, 'policy': {'max_artifact_bytes': 1024 * 1024},
           'tasks': [task], 'history': [], 'stages': [], 'decisions': []}
    if bound:
        task['selection_binding'] = {'role': 'workhorse', 'selection_sha256': record['selection_sha256']}
        task['target'] = deepcopy(record['work']['workhorse'])
    return job, task, path


def native_proof(job, task, path):
    """Invented coordinator-owned native observation and explicit owner answer."""
    from shared.legacy_author_provenance import provenance_scope
    private = path.parent.parent.parent / 'private'
    private.mkdir(exist_ok=True)
    handle = task['handles'][0]
    raw = path.read_bytes()
    owner = private / 'owner.txt'
    quote = 'Reconcile only this invented task/request and the listed original hash.'
    owner.write_text(quote + '\n')
    native = private / 'native.json'
    item = {'itemId': 'original-command', 'runId': 'original-run', 'sourceThreadId': handle['child_thread_id'],
            'type': 'command_execution', 'status': 'completed', 'textTruncated': False,
            'text': 'sha256sum ' + str(path) + '\n' + digest(raw) + '  ' + str(path) + '\n'}
    native.write_bytes(canonical({'structuredContent': {'thread': {'threadId': handle['child_thread_id']}, 'items': [item]}}))
    def descriptor(p):
        return {'path': str(p), 'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size}
    proof = {'schema_version': 1, 'kind': 'legacy-author-provenance', 'job_id': job['job_id'],
             **{k: task[k] for k in ('task_id', 'stage_id', 'logical_slot_id', 'worker_id')},
             'request_id': handle['request_id'], 'host_task_id': handle['task_id'], 'target': deepcopy(handle['target']),
             'brief': descriptor(path), 'owner_source': descriptor(owner), 'owner_quote': quote,
             'native_observation': {**descriptor(native), 'item_id': item['itemId'],
                                    'thread_id': handle['child_thread_id'], 'run_id': item['runId']}}
    proof_path = private / 'proof.json'
    proof_path.write_bytes(canonical(proof))
    decision = {'id': 'original-anchor', 'scope': provenance_scope(job['job_id'], task['task_id'], handle['request_id']),
                'source': str(proof_path), 'source_sha256': digest(proof_path.read_bytes()), 'quote': quote}
    return decision, proof_path, native, owner


def modern_fixture(root, *, participant=False):
    job, task, path = legacy_fixture(root, bound=True, target_present=True)
    data = canonical_selection_input()
    if participant:
        data['operation'] = 'focus-group/run'
        data['work']['participant-01'] = data['work'].pop('workhorse')
        data['profiles']['roles']['participant-01'] = data['profiles']['roles']['workhorse']
    record = models.freeze(data); job['model_selection'] = record
    role = 'participant-01' if participant else 'workhorse'
    task['selection_binding'] = {'role': role, 'selection_sha256': record['selection_sha256']}
    task['target'] = deepcopy(record['work'][role])
    brief = json.loads(path.read_bytes()); brief.pop('effective_brief_sha256')
    brief['target'] = deepcopy(task['target'])
    brief['model_selection'] = {'selection_sha256': record['selection_sha256'], 'binding': deepcopy(task['selection_binding'])}
    brief['effective_brief_sha256'] = digest(canonical(brief))
    path.write_bytes(canonical(brief)); task['brief']['sha256'] = digest(path.read_bytes())
    task['handles'][0]['target'] = deepcopy(task['target'])
    task['handles'][0]['observed_identity'].update(providerInstanceId=task['target']['providerInstanceId'], model=task['target']['model'])
    return job, task, path


class LegacyAuthorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_anchored_original_author_is_known_without_fabricating_binding(self):
        job, task, path = legacy_fixture(self.root)
        before, raw = deepcopy(job), path.read_bytes()
        self.assertEqual(actual_author_lineages(job), {'openai', 'deepseek'})
        self.assertEqual(job, before)
        self.assertEqual(path.read_bytes(), raw)
        self.assertNotIn('selection_binding', task)

    def test_carried_legacy_execution_ignores_later_binding_and_routing(self):
        job, task, path = legacy_fixture(self.root, bound=True)
        before = deepcopy(job)
        self.assertEqual(actual_author_lineages(job), {'openai', 'deepseek'})
        self.assertEqual(job, before)

    def test_unverified_original_identity_stays_unknown(self):
        job, task, path = legacy_fixture(self.root)
        task['handles'][0]['observed_identity']['status'] = 'unreported'
        self.assertIn('unknown', actual_author_lineages(job))

    def test_unknown_custom_or_misleading_provider_never_infers_family(self):
        for provider, model in (('fixture-gateway', 'gateway/hy3-preview'), ('custom', 'custom-model'),
                                ('codex', 'gateway/unrecognised'), ('claudeAgent', 'hy-preview')):
            with self.subTest(provider=provider, model=model):
                job, task, path = legacy_fixture(self.root)
                target = {'providerInstanceId': provider, 'model': model, 'options': {}}
                task['handles'][0]['target'] = target
                task['handles'][0]['observed_identity'].update(providerInstanceId=provider, model=model)
                task['dispatch_history'][0]['status_identity'] = target
                self.assertIn('unknown', actual_author_lineages(job))

    def test_original_identity_and_target_absence_are_checked(self):
        mutations = [lambda t: t['handles'][0].pop('target'),
                     lambda t: t['handles'][0]['observed_identity'].update(model='gateway/qwen-example'),
                     lambda t: t['dispatch_history'].clear(),
                     lambda t: t['dispatch_history'][0]['status_identity'].pop('model'),
                     lambda t: t['handles'][0]['observed_identity'].update(driverKind='codex')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                job, task, path = legacy_fixture(self.root)
                mutate(task)
                before = deepcopy(job)
                self.assertIn('unknown', actual_author_lineages(job))
                self.assertEqual(job, before)

    def test_external_hash_refuses_recomputed_self_hash_and_wrong_correlation(self):
        for key in ('job_id', 'task_id', 'request_id', 'worker_id', 'stage_id', 'logical_slot_id', 'target', 'extra'):
            with self.subTest(key=key):
                job, task, path = legacy_fixture(self.root, target_present=True)
                brief = json.loads(path.read_bytes()); brief[key] = 'changed'
                brief.pop('effective_brief_sha256')
                brief['effective_brief_sha256'] = digest(canonical(brief))
                path.write_bytes(canonical(brief))
                self.assertIn('unknown', actual_author_lineages(job))

    def test_unanchored_retry_and_followup_stay_unknown(self):
        job, task, path = legacy_fixture(self.root)
        original = deepcopy(task)
        task.pop('brief')
        # An independent descriptor establishes the root, not this request's hash.
        anchor = deepcopy(original)
        anchor['handles'] = []
        anchor['brief']['request_id'] = 'other'
        anchor['brief']['path'] = str(path.parent / ('cell-' + digest(b'other') + '.json'))
        job['history'] = [{'tasks': [anchor]}]
        self.assertIn('unknown', actual_author_lineages(job))
        # Follow-up cannot borrow its parent's descriptor or request correlation.
        task['followups'] = [dict(task['handles'][0], request_id='followup', parent_task_id='fixture-host')]
        self.assertIn('unknown', actual_author_lineages(job))

    def test_native_anchor_reopens_owner_proof_and_original_observation(self):
        job, task, path = legacy_fixture(self.root)
        saved = deepcopy(task['brief'])
        d, proof, native, owner = native_proof(job, task, path)
        task.pop('brief')
        anchor = deepcopy(task); anchor['handles'] = []; anchor['brief'] = saved
        anchor['brief'] = dict(saved, request_id='root-only', path=str(path.parent / ('cell-' + digest(b'root-only') + '.json')))
        job['history'] = [{'tasks': [anchor]}]
        job['decisions'] = [d]
        self.assertEqual(actual_author_lineages(job), {'openai', 'deepseek'})
        before = deepcopy(job)
        for file in (owner, proof, native):
            raw = file.read_bytes(); file.write_bytes(raw + b' ')
            self.assertIn('unknown', actual_author_lineages(job))
            file.write_bytes(raw)
        self.assertEqual(job, before)
        data = json.loads(proof.read_bytes()); data['native_observation']['run_id'] = 'different'
        proof.write_bytes(canonical(data)); d['source_sha256'] = digest(proof.read_bytes())
        self.assertIn('unknown', actual_author_lineages(job))

    def test_duplicate_anchors_symlinks_conflicting_roots_and_limits_refuse(self):
        job, task, path = legacy_fixture(self.root)
        old = deepcopy(task); old['brief']['sha256'] = 'a' * 64
        job['history'] = [{'tasks': [old]}]
        self.assertIn('unknown', actual_author_lineages(job))
        job['history'] = []
        saved = path.read_bytes(); destination = path.with_suffix('.saved'); destination.write_bytes(saved)
        path.unlink(); path.symlink_to(destination)
        self.assertIn('unknown', actual_author_lineages(job))
        path.unlink(); path.write_bytes(saved)
        old['brief']['path'] = str(self.root / 'different' / 'briefs' / path.name)
        job['history'] = [{'tasks': [old]}]
        self.assertIn('unknown', actual_author_lineages(job))
        job['history'] = []; job['policy']['max_artifact_bytes'] = 10
        self.assertIn('unknown', actual_author_lineages(job))

    def test_legacy_review_is_not_author_but_participant_blocks_same_family(self):
        job, task, path = legacy_fixture(self.root)
        task['role'] = 'review'
        self.assertEqual(actual_author_lineages(job), {'openai'})
        task['role'] = 'worker'
        data = canonical_selection_input(); data['operation'] = 'focus-group/run'
        record = models.freeze(data); job['model_selection'] = record
        task['selection_binding'] = {'role': 'participant-01', 'selection_sha256': record['selection_sha256']}
        self.assertIn('deepseek', actual_author_lineages(job))
        with self.assertRaisesRegex(models.SelectionError, 'collision'):
            models.dispatch(record, role='reviewer', slot_id='review', author_lineages={'anthropic'})

    def test_modern_retry_keeps_its_binding_and_stripping_never_gets_fallback(self):
        job, task, path = legacy_fixture(self.root, bound=True, target_present=True)
        binding = task['selection_binding']
        brief = json.loads(path.read_bytes())
        brief['target'] = deepcopy(task['target'])
        brief['model_selection'] = {'selection_sha256': binding['selection_sha256'], 'binding': deepcopy(binding)}
        brief.pop('effective_brief_sha256'); brief['effective_brief_sha256'] = digest(canonical(brief))
        path.write_bytes(canonical(brief)); task['brief']['sha256'] = digest(path.read_bytes())
        task['handles'][0]['target'] = deepcopy(task['target'])
        task['handles'][0]['observed_identity'].update(providerInstanceId=task['target']['providerInstanceId'], model=task['target']['model'])
        task.pop('brief'); task['request_id'] = 'next-modern'
        # Another descriptor anchors only the directory, mirroring a later prepare.
        task['prepared_followup'] = {'task_id': 'cell', 'request_id': 'later',
            'path': str(path.parent / ('cell-' + digest(b'later') + '.json')), 'sha256': 'a' * 64}
        self.assertEqual(actual_author_lineages(job), {'openai'})
        for value in (None, [], {}, 'bad'):
            task['selection_binding'] = value
            self.assertIn('unknown', actual_author_lineages(job))
        task.pop('selection_binding')
        self.assertIn('unknown', actual_author_lineages(job))

    def test_enabling_selection_checks_prospective_bindings_without_dispatch_exemption(self):
        from shared.job_coordinator import selection_plan_revision, selection_for_task
        from core.jobs.store import JobError
        job, task, path = legacy_fixture(self.root)
        current = deepcopy(job); current.pop('model_selection')
        current['policy']['model_selection_required'] = False
        proposed = {'model_selection': job['model_selection'],
                    'model_selection_sha256': job['model_selection']['selection_sha256'],
                    'policy': {'model_selection_required': True}, 'tasks': [deepcopy(task)]}
        with self.assertRaisesRegex(JobError, 'selection binding'):
            selection_plan_revision(current, proposed)
        proposed['tasks'][0]['selection_binding'] = {'role': 'workhorse', 'selection_sha256': proposed['model_selection_sha256']}
        proposed['tasks'][0]['target'] = deepcopy(proposed['model_selection']['work']['workhorse'])
        selection_plan_revision(current, proposed)
        self.assertEqual(actual_author_lineages({**current, **proposed}), {'openai', 'deepseek'})
        with self.assertRaises(JobError):
            selection_for_task({**current, **proposed}, task)

    def test_followup_uses_its_own_anchor_identity_and_parent(self):
        job, task, path = legacy_fixture(self.root)
        parent = task['handles'][0]
        target = {'providerInstanceId': 'fixture-gateway', 'model': 'gateway/qwen-example', 'options': {}}
        handle = dict(deepcopy(parent), task_id='followup-host', request_id='followup-request',
                      parent_task_id=parent['task_id'], target=target)
        handle['observed_identity'].update(model=target['model'])
        task['followups'] = [handle]
        brief = json.loads(path.read_bytes()); brief.pop('effective_brief_sha256')
        brief.update(request_id=handle['request_id'], followup_of=parent['request_id'])
        brief['effective_brief_sha256'] = digest(canonical(brief))
        followup = path.parent/'followup'/('cell-'+digest(handle['request_id'].encode())+'.json')
        followup.parent.mkdir(); followup.write_bytes(canonical(brief))
        task['prepared_followup'] = {**task['brief'], 'request_id': handle['request_id'],
            'path': str(followup), 'sha256': digest(followup.read_bytes())}
        task['dispatch_history'].append({'kind': 'accepted', 'request_id': handle['request_id'],
                                        'host_task_id': handle['task_id'], 'status_identity': target})
        self.assertEqual(actual_author_lineages(job), {'openai', 'deepseek', 'qwen'})
        handle['parent_task_id'] = 'unrelated'
        self.assertIn('unknown', actual_author_lineages(job))

    def test_same_lineage_legacy_author_still_blocks_review(self):
        job, task, path = legacy_fixture(self.root)
        handle = task['handles'][0]
        handle['target']['model'] = 'gateway/claude-example'
        handle['observed_identity']['model'] = handle['target']['model']
        task['dispatch_history'][0]['status_identity']['model'] = handle['target']['model']
        authors = actual_author_lineages(job)
        self.assertEqual(authors, {'openai', 'anthropic'})
        with self.assertRaisesRegex(models.SelectionError, 'collision'):
            models.dispatch(job['model_selection'], role='reviewer', slot_id='review', author_lineages=authors)

    def test_modern_carried_handle_uses_archived_producing_binding(self):
        job, task, path = legacy_fixture(self.root, bound=True, target_present=True)
        original_binding = deepcopy(task['selection_binding'])
        brief = json.loads(path.read_bytes()); brief['target'] = deepcopy(task['target'])
        brief['model_selection'] = {'selection_sha256': original_binding['selection_sha256'], 'binding': original_binding}
        brief.pop('effective_brief_sha256'); brief['effective_brief_sha256'] = digest(canonical(brief))
        path.write_bytes(canonical(brief)); task['brief']['sha256'] = digest(path.read_bytes())
        task['handles'][0]['target'] = deepcopy(task['target'])
        task['handles'][0]['observed_identity'].update(providerInstanceId=task['target']['providerInstanceId'], model=task['target']['model'])
        old = deepcopy(task); original_record = job['model_selection']
        data = canonical_selection_input(); data['scope_id'] = 'new-scope'
        current = models.freeze(data)
        job['model_selection_history'] = {original_record['selection_sha256']: original_record}
        job['model_selection'] = current
        task['selection_binding']['selection_sha256'] = current['selection_sha256']
        job['history'] = [{'tasks': [old]}]
        self.assertEqual(actual_author_lineages(job), {'openai'})

    def test_modern_retry_without_any_remaining_descriptor_keeps_modern_policy(self):
        job, task, path = modern_fixture(self.root, participant=True)
        task.pop('brief'); task['request_id'] = 'charged-retry'
        before = deepcopy(job)
        self.assertEqual(actual_author_lineages(job), {'openai'})
        self.assertEqual(job, before)

    def test_modern_forbidden_followup_and_unreadable_brief_keep_modern_policy(self):
        job, task, path = modern_fixture(self.root, participant=True)
        task['followups'] = [dict(deepcopy(task['handles'][0]), request_id='unexpected',
            task_id='unexpected-host', parent_task_id='fixture-host', forbidden_followup=True)]
        self.assertEqual(actual_author_lineages(job), {'openai'})
        path.unlink()
        self.assertEqual(actual_author_lineages(job), {'openai'})

    def test_unrelated_bad_descriptor_does_not_reclassify_modern_execution(self):
        job, task, path = modern_fixture(self.root)
        other = deepcopy(task); other['task_id'] = 'other'; other['handles'] = []
        other['brief']['path'] = str(self.root/'unrelated'/'briefs'/'wrong.json')
        job['tasks'].append(other)
        self.assertEqual(actual_author_lineages(job), {'openai'})

    def test_superseded_copies_do_not_repeat_provenance_io(self):
        from shared import legacy_author_provenance as provenance
        job, task, path = legacy_fixture(self.root, bound=True)
        job['history'] = [{'tasks': [deepcopy(task)]} for _ in range(30)]
        before = deepcopy(job)
        with mock.patch.object(provenance, '_regular', wraps=provenance._regular) as opened:
            self.assertEqual(actual_author_lineages(job), {'openai', 'deepseek'})
        self.assertLessEqual(opened.call_count, 4, 'repeated snapshots must not multiply request-file I/O')
        self.assertEqual(job, before)


if __name__ == '__main__':
    unittest.main()
