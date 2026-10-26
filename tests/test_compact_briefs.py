"""Installed public compact transport, adversarial admission and exact byte fixtures.

All packages, jobs, owner answers and source mutations are isolated test data.
No model is launched. The approved source/map oracle remains a separate suite.
"""
from __future__ import annotations

import copy
import io
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

from core.jobs.store import JobError, canonical, digest
from core.schema import errors
from shared.compact_briefs import COMPACT, LEGACY, MAGIC, BODY, deserialize, serialize
import shared.compact_briefs as compact_briefs
from tests.test_rebuild_installed import Sandbox, worker_result

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ('imps', 'ape', 'babysitter', 'agent-tuneup', 'elephant-goldfish', 'focus-group', 'ralph', 'plan', 'tests-omg')
PLANNING_PLUGINS = ('imps', 'ape', 'babysitter', 'agent-tuneup', 'elephant-goldfish', 'focus-group', 'ralph', 'plan')
ADDITIONS = {'shared/compact_briefs.py', 'shared/agents/worker-brief-compact-v2.schema.json'}


def account(value):
    """Exact canonical member bytes, including each separator and outer framing."""
    result = {'outer_framing': 3}  # braces and trailing newline
    for index, key in enumerate(sorted(value)):
        result[key] = len(canonical({key: value[key]})) - 3 + bool(index)
    assert sum(result.values()) == len(canonical(value))
    return result


def procedural_bytes(view):
    # Actual serialized contribution with all key names, escaping and framing.
    measured = {'schema_version': 2, 'transport': COMPACT,
                **{k: view[k] for k in ('definition', 'transport_instructions', 'result_contract', 'artifact_limit_bytes', 'verification_tool') if k in view}}
    additional = [r for r in view.get('resources', {}).get('planning_snapshot', {}).get('rubrics', []) if 'text' in r]
    if additional:
        measured['resources'] = {'planning_snapshot': {'rubrics': additional}}
    return serialize(measured)


def assert_result_version_instruction(test, view):
    # Textual conflict regression only; this does not claim live-model obedience.
    test.assertEqual(view['schema_version'], 2)
    test.assertEqual(view['result_contract']['schema_version'], 1)
    test.assertIn('Return worker-result-v1 with schema_version=1, overriding the procedure copy rule.',
                  view['transport_instructions'])
    test.assertIn('Copy schema_version, job_id,', view['definition'])


class CompactInstalledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='compact-installed-')
        cls.box = Sandbox(Path(cls.tmp.name))
        cls.packages = {plugin: cls.box.install(plugin) for plugin in PLUGINS}
        cls.ids = itertools.count()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_compact_invalid_utf8_is_a_controlled_job_error(self):
        body = b'\xff'
        header = {'schema_version': 2, 'transport': COMPACT,
                  'definition': {'encoding': 'inline-utf-8', 'sha256': digest(body), 'bytes': len(body)}}
        with self.assertRaisesRegex(JobError, 'compact_inline_definition_invalid_utf8'):
            deserialize(MAGIC + canonical(header) + BODY + body)

    def test_schema_valid_retention_rule_without_inline_text_is_refused(self):
        with self.assertRaisesRegex(JobError, 'retention_rule_invalid'):
            compact_briefs.validate_retention_rules({'rules': [
                {'disposition': 'inline', 'source_id': 'fixture'}]})

    def test_release_version_bump_is_allowed_but_other_manifest_changes_refuse(self):
        source = self.box.source_copy('imps')
        manifest_path = source / 'plugins/imps/plugin.json'
        manifest = json.loads(manifest_path.read_text())
        version = manifest['version'].split('.')
        bumped = '.'.join((version[0], version[1], str(int(version[2]) + 1)))
        old_field = f'"version": "{manifest["version"]}"'.encode()
        new_field = f'"version": "{bumped}"'.encode()
        original = manifest_path.read_bytes()
        self.assertEqual(original.count(old_field), 1)
        manifest_path.write_bytes(original.replace(old_field, new_field))
        case = self.make('imps/reviewer', source=source)
        self.assertIn(bumped, case['package'].name)
        self.prepare(case)
        self.assertEqual(self.ingest(case)['status'], 'awaiting-acceptance')

        changed_source = self.box.source_copy('imps')
        changed_path = changed_source / 'plugins/imps/plugin.json'
        changed = changed_path.read_bytes()
        original_description = json.loads(changed)['description'].encode()
        self.assertEqual(changed.count(original_description), 1)
        changed_path.write_bytes(changed.replace(original_description,
                                                 original_description + b' Tampered contract.'))
        rejected = self.make('imps/reviewer', source=changed_source)
        self.assert_refusal(self.prepare(rejected, check=False), 'retention_manifest_source_changed')

    def test_manifest_major_version_change_needs_a_new_retention_assessment(self):
        source = self.box.source_copy('imps')
        manifest_path = source / 'plugins/imps/plugin.json'
        manifest = json.loads(manifest_path.read_text())
        version = manifest['version'].split('.')
        bumped = '.'.join((str(int(version[0]) + 1), version[1], version[2]))
        old_field = f'"version": "{manifest["version"]}"'.encode()
        new_field = f'"version": "{bumped}"'.encode()
        original = manifest_path.read_bytes()
        self.assertEqual(original.count(old_field), 1)
        manifest_path.write_bytes(original.replace(old_field, new_field))
        case = self.make('imps/reviewer', source=source)
        self.assert_refusal(self.prepare(case, check=False), 'retention_manifest_source_changed')

    def make(self, worker='imps/investigator', *, compact=True, task_changes=None, job_changes=None,
             source=None, dependencies=None):
        plugin = worker.partition('/')[0]
        package, receipt = self.packages[plugin] if source is None else self.box.install(plugin, source=source)
        job_id = 'compact-' + str(next(self.ids)).zfill(8)
        task = {'task_id': 'work', 'stage_id': 'stage', 'logical_slot_id': 'primary',
                'request_id': job_id + '-r0', 'dependency_key': plugin, 'worker_id': worker,
                'target': {'providerInstanceId': 'fixture-work', 'model': 'alpha-work',
                           'lineage': 'openai', 'options': {'reasoningEffort': 'high'}},
                'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/work'}}
        if task_changes:
            task.update(task_changes)
        deps = copy.deepcopy(dependencies or [{'key': plugin, 'plugin': plugin}])
        for dep in deps:
            selected_package = package if dep['plugin'] == plugin else self.packages[dep['plugin']][0]
            dep['package_dir'] = str(selected_package)
        job = {'schema_version': 1, 'job_id': job_id, 'installation_id': receipt['installation_id'],
               'workflow': 'fixture/compact', 'owner': 'fixture-owner', 'objective': 'Inspect this assigned fixture.',
               'requirements': {'R1': 'Preserve the exact assigned evidence and scope.'},
               'authorization': {'actions': ['read'], 'sharing': ['fixture-work'], 'remote': []},
               'constraints': ['Do not dispatch children or grant new authority.'],
               'snapshot': {'head': 'a' * 40, 'content_hash': 'b' * 64},
               'dependencies': deps, 'pins': {},
               'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216,
                          **({'worker_brief_transport': COMPACT} if compact else {})},
               'result_contract': {'schema_version': 1, 'transport': 'worker-result-v1'},
               'stages': [{'id': 'stage', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                           'revision': 'r1', 'resources': {'evidence': 'Only the assigned evidence.'},
                           'stop_conditions': ['Stop blocked if an input or binding differs.']}],
               'tasks': [task], 'decisions': [], 'history': [], 'metrics': {}}
        if job_changes:
            job.update(job_changes)
        self.box.create(package, job)
        caller = self.box.caller(receipt, job['workflow'])
        return {'package': package, 'receipt': receipt, 'job': job_id, 'caller': caller, 'worker': worker}

    def prepare(self, case, *, check=True):
        out = self.box.job(case['package'], 'prepare', case['job'],
                           {'caller': case['caller'], 'task_id': 'work'}, check=check)
        if check:
            raw = Path(out['path']).read_bytes()
            self.assertEqual((digest(raw), len(raw)), (out['sha256'], out['bytes']))
            case.update(descriptor=out, brief=deserialize(raw))
        return out

    def ingest(self, case, result=None, *, check=True):
        return self.box.job(case['package'], 'result', case['job'],
            {'caller': case['caller'], 'task_id': 'work', 'request_id': case['brief']['request_id'],
             'completion_id': case['job'] + '-done',
             'result': {'json': result if result is not None else worker_result(case['brief'])}}, check=check)

    def state_path(self, case):
        return self.box.jobs / case['job'] / 'job.json'

    def edit_state(self, case, edit):
        path = self.state_path(case)
        state = json.loads(path.read_bytes())
        edit(state)
        path.write_bytes(canonical(state))

    def forge_view(self, case, edit):
        view = copy.deepcopy(case['brief'])
        edit(view)
        view.pop('effective_brief_sha256', None)
        view['effective_brief_sha256'] = digest(canonical(view))
        header = copy.deepcopy(view)
        body = header.pop('definition').encode()
        header['definition'] = {'encoding': 'inline-utf-8', 'sha256': digest(body), 'bytes': len(body)}
        raw = MAGIC + canonical(header) + BODY + body
        Path(case['descriptor']['path']).write_bytes(raw)
        def forge(state):
            task = state['tasks'][0]
            task['brief'].update(sha256=digest(raw), effective_brief_sha256=view['effective_brief_sha256'])
            task['brief_authorities'][view['request_id']].update(transport_sha256=digest(raw), transport_bytes=len(raw))
        self.edit_state(case, forge)
        return view

    def assert_refusal(self, proc, diagnostic):
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn(diagnostic, proc.stderr)

    def test_every_worker_installed_definition_identity_and_real_result_admission(self):
        workers = [w['id'] for p in PLUGINS for w in json.loads((ROOT / 'plugins' / p / 'plugin.json').read_text())['workers']]
        manifest = json.loads((ROOT / 'shared/agents/worker-retention.json').read_text())
        for worker in workers:
            with self.subTest(worker=worker):
                changes = None
                if worker == 'elephant-goldfish/cold-reader':
                    document = self.box.private / 'cold-document.md'
                    document.write_text('# Supplied document\nComplete fixture instructions.\n')
                    changes = {'context_policy': 'document-only', 'document': {'path': str(document), 'sha256': digest(document.read_bytes())},
                               'write_scope': {'mode': 'coordinator-only'}}
                case = self.make(worker, task_changes=changes)
                self.prepare(case)
                shown = json.loads(self.box.t3('agents', 'show', *worker.split('/'), '--compact').stdout)
                view = case['brief']
                assert_result_version_instruction(self, view)
                self.assertEqual(canonical(shown['definition']), canonical(view['definition']))
                self.assertEqual(shown['definition_sha256'], view['authority']['definition_sha256'])
                self.assertEqual(view['schema_version'], 2)
                self.assertNotIn('dependency_pins', view)
                self.assertNotIn('effective_definition', view)
                self.assertNotIn('worker-retention.json', json.dumps(view))
                profile = next(p for p in manifest['profiles'] if p['id'] == worker)
                prose = view['definition']
                for rule in profile['rules']:
                    if rule['disposition'] == 'inline':
                        self.assertIn(rule['inline_text'], prose)
                self.assertEqual(prose.encode(), profile['procedure']['text'].encode())
                self.assertEqual(view['authority']['procedure_sha256'], profile['procedure']['sha256'])
                self.assertEqual(self.ingest(case)['status'], 'awaiting-acceptance')

    def test_default_v1_full_definition_and_schema_stay_identical(self):
        case = self.make(compact=False)
        self.prepare(case)
        self.assertEqual(case['brief']['schema_version'], 1)
        shown = json.loads(self.box.t3('agents', 'show', 'imps', 'investigator').stdout)
        self.assertEqual(case['brief']['effective_definition']['bytes'], shown['definition'])
        self.assertEqual(errors(case['brief'], json.loads((ROOT / 'shared/agents/worker-brief.schema.json').read_text())), [])
        self.assertEqual(self.ingest(case)['status'], 'awaiting-acceptance')

    def test_multiple_dependencies_and_unused_workers_do_not_enter_view(self):
        case = self.make(dependencies=[{'key': 'imps', 'plugin': 'imps'}, {'key': 'ape', 'plugin': 'ape'}])
        self.prepare(case)
        raw = Path(case['descriptor']['path']).read_bytes()
        self.assertNotIn(b'ape/source-researcher', raw)
        self.assertNotIn(b'imps/stage-executor', raw)
        self.assertNotIn(b'job.schema.json', raw)
        self.assertEqual(self.ingest(case)['status'], 'awaiting-acceptance')

    def test_unused_worker_and_schema_changes_leave_transmitted_size_unchanged(self):
        first = self.make(); self.prepare(first)
        source = self.box.source_copy('imps')
        (source / 'shared/agents/unused-fixture.schema.json').write_text('{"title":"Unassigned schema","type":"object"}\n')
        second = self.make(source=source, dependencies=[{'key': 'imps', 'plugin': 'imps'}, {'key': 'ape', 'plugin': 'ape'}]); self.prepare(second)
        self.assertEqual(first['brief']['definition'], second['brief']['definition'])
        self.assertEqual(first['descriptor']['bytes'], second['descriptor']['bytes'])
        self.assertNotIn('ape/source-researcher', json.dumps(second['brief']))
        self.assertNotIn('Unassigned schema', json.dumps(second['brief']))

    def test_necessary_task_evidence_growth_is_separate_from_procedure(self):
        first = self.make(); self.prepare(first)
        second = self.make()
        evidence = {'source': 'fixture:assigned-recovery-receipt',
                    'observation': 'The assigned interrupted-read case preserves its original receipt and reports unavailable evidence.'}
        self.edit_state(second, lambda state: state['stages'][0]['resources'].update(required_observation=evidence))
        self.prepare(second)
        self.assertEqual(procedural_bytes(first['brief']), procedural_bytes(second['brief']))
        self.assertGreater(second['descriptor']['bytes'], first['descriptor']['bytes'])
        self.assertEqual(second['brief']['resources']['required_observation'], evidence)

    def test_real_public_execution_after_package_relocation(self):
        from tests.test_plan_review_installed_matrix import relocate
        with tempfile.TemporaryDirectory(prefix='compact-relocated-') as directory:
            box = Sandbox(Path(directory))
            packages = {'imps': box.install('imps')}
            before = json.loads(box.t3('agents', 'show', 'imps', 'investigator', '--compact').stdout)
            packages = relocate(box, packages)
            fixture = CompactInstalledTest()
            fixture.box, fixture.packages, fixture.ids = box, packages, itertools.count()
            case = fixture.make(); fixture.prepare(case)
            self.assertEqual(case['brief']['definition'].encode(), before['definition'].encode())
            self.assertEqual(fixture.ingest(case)['status'], 'awaiting-acceptance')

    def test_worker_cannot_supply_authoritative_admission_metadata(self):
        case = self.make(); self.prepare(case)
        forged = dict(case['caller'], actor='worker', task_id='work', stage_id='stage')
        proc = self.box.job(case['package'], 'result', case['job'],
            {'caller': forged, 'task_id': 'work', 'request_id': case['brief']['request_id'],
             'completion_id': 'forged', 'result': {'json': worker_result(case['brief'])}}, check=False)
        self.assert_refusal(proc, 'coordinator-only')

    def test_native_verification_slot_has_exact_helper_without_full_pin_discovery(self):
        case = self.make('imps/stage-executor')
        gate = {'state_root': str(self.box.private / 'declared-gate'), 'run_id': 'fixture-native-run'}
        self.edit_state(case, lambda state: state['stages'][0]['resources'].update(gate=gate))
        self.prepare(case)
        tool = case['brief']['verification_tool']
        self.assertEqual(tool['argv_prefix'], ['python3', str(case['package'] / 'cli.py')])
        self.assertEqual(tool['sha256'], digest((case['package'] / 'cli.py').read_bytes()))
        self.assertEqual(tool['actions'], ['snapshot', 'check', 'evidence'])
        self.assertEqual(tool['gate_flags'], ['--state-root', gate['state_root'], '--run-id', gate['run_id']])
        self.assertLessEqual(len(procedural_bytes(case['brief'])), 24576)
        self.forge_view(case, lambda view: view['verification_tool']['argv_prefix'].append('unapproved-wrapper'))
        self.assert_refusal(self.ingest(case, check=False), 'compact_projection_authority_mismatch')

    def test_required_task_rubrics_are_inline_and_drift_refuses_public_admission(self):
        rubric = self.packages['imps'][0] / 'references/plan-review-rubric.md'
        case = self.make('imps/reviewer')
        descriptor = {'path': str(rubric), 'sha256': digest(rubric.read_bytes()), 'bytes': rubric.stat().st_size}
        self.edit_state(case, lambda state: state['stages'][0]['resources'].update(planning_snapshot={'rubrics': [descriptor]}))
        self.prepare(case)
        supplied = case['brief']['resources']['planning_snapshot']['rubrics'][0]
        if 'text' in supplied:
            self.assertEqual(supplied['text'], rubric.read_text())
        else:
            self.assertIs(supplied.get('inline_definition'), True)
            self.assertIn(rubric.read_text(), case['brief']['definition'])
        self.assertNotIn('path', supplied)
        self.assertLessEqual(len(procedural_bytes(case['brief'])), 24576)
        original = rubric.read_bytes()
        try:
            rubric.write_bytes(original + b'Changed required procedure.\n')
            self.assert_refusal(self.ingest(case, check=False), 'installed package integrity failure')
        finally:
            rubric.write_bytes(original)

    def test_unfrozen_rubric_path_is_refused_before_reading(self):
        rubric = self.box.private / 'unfrozen-rubric.md'
        rubric.write_text('Do not read arbitrary coordinator files.\n')
        descriptor = {'path': str(rubric), 'sha256': digest(rubric.read_bytes()), 'bytes': rubric.stat().st_size}
        with self.assertRaisesRegex(JobError, 'compact_required_rubric_not_frozen'):
            compact_briefs.read_required_rubric(descriptor, set())

    def test_project_rejects_self_hashed_arbitrary_rubric(self):
        rubric = self.box.private / 'arbitrary-project-rubric.md'
        rubric.write_text('Private coordinator content must not reach the worker.\n')
        raw = rubric.read_bytes()
        case = self.make('imps/reviewer')
        descriptor = {'path': str(rubric), 'sha256': digest(raw), 'bytes': len(raw)}
        self.edit_state(case, lambda state: state['stages'][0]['resources'].update(
            planning_snapshot={'rubrics': [descriptor]}))
        self.assert_refusal(self.prepare(case, check=False), 'compact_required_rubric_not_frozen')

    def test_frozen_rubric_hash_is_admitted(self):
        rubric = self.packages['imps'][0] / 'references/plan-review-rubric.md'
        raw = rubric.read_bytes()
        descriptor = {'path': str(rubric), 'sha256': digest(raw), 'bytes': len(raw)}
        self.assertEqual(compact_briefs.read_required_rubric(descriptor, {digest(raw)}), raw)

    def test_required_task_rubric_symlink_alias_is_refused(self):
        rubric = self.box.private / 'rubric-target.md'
        rubric.write_text('Synthetic authorized rubric text.\n')
        alias = self.box.private / 'rubric-alias.md'
        alias.symlink_to(rubric)
        descriptor = {'path': str(alias), 'sha256': digest(rubric.read_bytes()), 'bytes': rubric.stat().st_size}
        with self.assertRaisesRegex(JobError, 'compact_required_rubric_descriptor_invalid'):
            compact_briefs.read_required_rubric(descriptor, set())

    def test_required_rubric_already_inline_is_not_transmitted_twice(self):
        rubric = self.packages['imps'][0] / 'references/plan-review-rubric.md'
        case = self.make('imps/reviewer')
        descriptor = {'path': str(rubric), 'sha256': digest(rubric.read_bytes()), 'bytes': rubric.stat().st_size}
        self.edit_state(case, lambda state: state['stages'][0]['resources'].update(planning_snapshot={'rubrics': [descriptor]}))
        self.prepare(case)
        self.assertIn(rubric.read_text(), case['brief']['definition'])
        self.assertEqual(case['brief']['resources']['planning_snapshot']['rubrics'],
                         [{'sha256': descriptor['sha256'], 'bytes': descriptor['bytes'], 'inline_definition': True}])

    def test_malformed_frames_and_unknown_policy_refuse(self):
        for raw in (MAGIC + b'[]\n' + BODY, MAGIC + b'{}\nmissing body', b'T3-COMPACT-BRIEF/99\n'):
            case = self.make(); self.prepare(case)
            Path(case['descriptor']['path']).write_bytes(raw)
            self.edit_state(case, lambda state: state['tasks'][0]['brief'].update(sha256=digest(raw)))
            proc = self.ingest(case, check=False)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        case = self.make()
        self.edit_state(case, lambda state: state['policy'].update(worker_brief_transport='future-unknown'))
        self.assert_refusal(self.prepare(case, check=False), 'brief_transport_unsupported')

    def test_public_plan_revision_cannot_change_a_jobs_transport(self):
        case = self.make(compact=False)
        proc = self.box.job(case['package'], 'plan-revision', case['job'],
            {'caller': case['caller'], 'revision': {'id': 'switch-transport'},
             'new_plan': {'policy': {'worker_brief_transport': COMPACT}}}, check=False)
        self.assert_refusal(proc, 'brief_transport_is_immutable')
        self.assertNotIn('worker_brief_transport', self.box.state_of(case['job'])['policy'])

    def test_enabled_override_is_pinned_once_and_remains_frozen_after_live_edit(self):
        override = self.box.agents / 'overrides/imps/investigator.md'
        override.parent.mkdir(parents=True, exist_ok=True)
        override.write_text('---\nworker_id: imps/investigator\n---\nAdvisory: inspect the assigned fixture carefully.\n')
        receipt = self.packages['imps'][1]
        self.box.t3('agents', 'enable-override', 'imps/investigator', '--base-digest', receipt['bundle_digest'])
        try:
            case = self.make()
            self.prepare(case)
            self.assertEqual(json.dumps(case['brief']).count('Advisory: inspect the assigned fixture carefully.'), 1)
            shown = json.loads(self.box.t3('agents', 'show', 'imps', 'investigator', '--compact').stdout)
            self.assertEqual(shown['definition'], case['brief']['definition'])
            override.write_text('---\nworker_id: imps/investigator\n---\nA later unrelated override is not adopted.\n')
            self.assertEqual(self.ingest(case)['status'], 'awaiting-acceptance')
            def tamper_pin(state):
                state['pins']['imps']['effective_workers']['imps/investigator']['override_bytes'] += 'Changed pinned bytes.'
            self.edit_state(case, tamper_pin)
            self.assert_refusal(self.ingest(case, check=False), 'pin_mismatch')
        finally:
            self.box.t3('agents', 'disable-override', 'imps/investigator', '--base-digest', receipt['bundle_digest'])

    def test_prior_findings_responses_and_ordinary_reviewer_subjects_remain(self):
        document = self.box.private / 'review-subject.md'
        document.write_text('# Exact review subject\n')
        prior = {'findings': [{'id': 'PRIOR-1', 'severity': 'minor', 'scenario': 'Preserved objection.'}],
                 'responses': [{'finding_key': 'PRIOR-1', 'status': 'open'}]}
        case = self.make('imps/reviewer', task_changes={'role': 'review',
            'reviewed_documents': [{'path': str(document), 'sha256': digest(document.read_bytes())}]})
        self.edit_state(case, lambda state: state['stages'][0]['resources'].update(prior=prior))
        self.prepare(case)
        self.assertEqual(case['brief']['resources']['prior'], prior)
        self.assertTrue(case['brief']['review_inputs'])
        result = json.loads(worker_result(case['brief']))
        result['review_verdict'] = 'approve'
        self.assertEqual(self.ingest(case, json.dumps(result))['status'], 'awaiting-acceptance')

    def test_cold_scope_has_no_history_authors_prior_findings_or_reference_grants(self):
        document = self.box.private / 'isolated-doc.md'; document.write_text('# Document\n')
        context = self.box.private / 'declared.txt'; context.write_text('Declared context only.\n')
        marker = 'UNSUPPLIED-HISTORY-793af'
        case = self.make('elephant-goldfish/cold-reader', task_changes={
            'context_policy': 'document-only', 'document': {'path': str(document), 'sha256': digest(document.read_bytes())},
            'context_files': [{'path': str(context), 'sha256': digest(context.read_bytes())}],
            'write_scope': {'mode': 'coordinator-only'}}, job_changes={
                'objective': marker, 'constraints': [marker], 'snapshot': {'private_history': marker}})
        self.edit_state(case, lambda state: state['stages'][0]['resources'].update(prior_findings=marker))
        self.assert_refusal(self.prepare(case, check=False), 'cold reader must read only its supplied document')
        self.edit_state(case, lambda state: state['tasks'][0].pop('context_files'))
        self.prepare(case)
        view = case['brief']
        self.assertNotIn(marker, json.dumps(view))
        for key in ('objective', 'resources', 'owner_decisions', 'review_inputs', 'consumed_outputs', 'dependency_pins'):
            self.assertNotIn(key, view)
        self.assertEqual(view['authorization']['read'], [str(document)])
        self.assertIsNone(view['revision'])
        self.forge_view(case, lambda value: value.update(resources={'history': marker}))
        self.assert_refusal(self.ingest(case, check=False), 'compact_projection_authority_mismatch')
        self.forge_view(case, lambda value: value['authorization']['read'].append(str(self.state_path(case))))
        self.assert_refusal(self.ingest(case, check=False), 'compact_projection_authority_mismatch')

    def test_tampered_serialized_bytes_fail_before_result_admission(self):
        case = self.make(); self.prepare(case)
        path = Path(case['descriptor']['path']); path.write_bytes(path.read_bytes() + b' ')
        self.assert_refusal(self.ingest(case, check=False), 'prepared brief bytes changed')

    def test_rehashed_essential_domain_and_result_schema_substitutions_fail(self):
        def weaken_rule(view):
            self.assertIn('Do not dispatch', view['definition'])
            view['definition'] = view['definition'].replace('Do not dispatch', 'You may dispatch')
        def weaken_shape(view):
            shape = json.loads((ROOT / 'shared/agents/worker-result.schema.json').read_text())
            original = json.dumps(shape, ensure_ascii=False, separators=(',', ':'))
            shape['required'].remove('binding')
            self.assertIn(original, view['definition'])
            view['definition'] = view['definition'].replace(original, json.dumps(shape, ensure_ascii=False, separators=(',', ':')))
        for edit in (weaken_rule, weaken_shape,
                     lambda v: v.update(definition='Read the registry for required rules.'),
                     lambda v: v['authority'].update(procedure_sha256='0' * 64)):
            with self.subTest(edit=edit):
                case = self.make(); self.prepare(case); self.forge_view(case, edit)
                self.assert_refusal(self.ingest(case, check=False), 'compact_projection_authority_mismatch')
        for worker, clause in (('agent-tuneup/config-verifier', 'Never apply, restore, edit'),
                               ('focus-group/fidelity-reviewer', 'a hidden dissent')):
            with self.subTest(domain=worker):
                case = self.make(worker); self.prepare(case)
                self.assertIn(clause, case['brief']['definition'])
                self.forge_view(case, lambda view: view.update(definition=view['definition'].replace(clause, 'An omitted domain obligation')))
                self.assert_refusal(self.ingest(case, check=False), 'compact_projection_authority_mismatch')

    def test_changed_task_snapshot_selection_options_and_revision_refuse(self):
        mutations = [lambda s: s['snapshot'].update(head='c' * 40),
                     lambda s: s['stages'][0].update(revision='changed'),
                     lambda s: s['tasks'][0]['target']['options'].update(reasoningEffort='low'),
                     lambda s: s['tasks'][0]['selection_binding'].update(selection_sha256='0' * 64),
                     lambda s: s['authorization']['actions'].append('write'),
                     lambda s: s['tasks'][0].update(worker_id='imps/auditor')]
        for edit in mutations:
            with self.subTest(edit=edit):
                case = self.make(); self.prepare(case); self.edit_state(case, edit)
                proc = self.ingest(case, check=False)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertRegex(proc.stderr, 'compact_authority_current_state_mismatch|model_selection:')

    def test_copied_hash_and_worker_forged_authority_linkage_refuse(self):
        first = self.make(); self.prepare(first)
        second = self.make(); self.prepare(second)
        def copy_link(state):
            state['tasks'][0]['brief_authorities'][second['brief']['request_id']] = copy.deepcopy(
                self.box.state_of(first['job'])['tasks'][0]['brief_authorities'][first['brief']['request_id']])
        self.edit_state(second, copy_link)
        self.assert_refusal(self.ingest(second, check=False), 'compact_authority_link_missing')
        result = json.loads(worker_result(first['brief']))
        result['effective_brief_sha256'] = second['brief']['effective_brief_sha256']
        out = self.ingest(first, json.dumps(result))
        self.assertEqual(out['last_execution_status'], 'malformed-result')

    def test_unknown_mixed_and_v1_only_consumer_versions_refuse(self):
        for edit in (lambda v: v.update(schema_version=99), lambda v: v.update(schema_version=1),
                     lambda v: v.update(transport=LEGACY)):
            case = self.make(); self.prepare(case); self.forge_view(case, edit)
            proc = self.ingest(case, check=False)
            self.assertEqual(proc.returncode, 2)
            self.assertRegex(proc.stderr, 'brief_transport_unsupported_or_mixed|mixed_brief_transport_versions')
        case = self.make(); self.prepare(case)
        self.assertTrue(errors(case['brief'], json.loads((ROOT / 'shared/agents/worker-brief.schema.json').read_text())))

    def test_unsafe_brief_and_private_authority_aliases_refuse(self):
        for private in (False, True):
            case = self.make(); self.prepare(case)
            state = self.box.state_of(case['job'])
            ref = state['tasks'][0]['brief_authorities'][case['brief']['request_id']] if private else case['descriptor']
            path = Path(ref['path']); saved = self.box.private / (case['job'] + '-saved.json')
            shutil.move(path, saved); path.symlink_to(saved)
            self.assert_refusal(self.ingest(case, check=False), 'symbolic links')

    def test_malformed_and_oversize_results_remain_real_failed_executions(self):
        case = self.make(); self.prepare(case)
        copied_version = json.loads(worker_result(case['brief']))
        copied_version['schema_version'] = case['brief']['schema_version']
        self.assertEqual(copied_version['schema_version'], 2)
        out = self.ingest(case, json.dumps(copied_version))
        self.assertEqual(out['last_execution_status'], 'malformed-result')
        self.assertTrue(out['execution_history'][-1]['malformed'])
        for raw in ('{}', 'x' * 32769, '{"schema_version":1,"schema_version":1}'):
            case = self.make(); self.prepare(case)
            out = self.ingest(case, raw)
            self.assertEqual(out['last_execution_status'], 'malformed-result')
            self.assertTrue(out['execution_history'][-1]['malformed'])

    def test_artifact_envelope_and_exact_task_owned_evidence(self):
        case = self.make(); self.prepare(case)
        result = json.loads(worker_result(case['brief']))
        directory = self.box.jobs / case['job'] / 'artifacts/tasks/work'; directory.mkdir(parents=True)
        artifact = directory / 'full-result.json'; raw = canonical(result); artifact.write_bytes(raw)
        correlation = {k: result[k] for k in ('schema_version', 'job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256', 'revision', 'binding')}
        envelope = {'schema_version': 1, 'artifact': {'path': 'artifacts/tasks/work/full-result.json',
                    'sha256': digest(raw), 'finding_count': 0, 'finding_ids': []}, 'correlation': correlation}
        self.assertEqual(self.ingest(case, json.dumps(envelope))['status'], 'awaiting-acceptance')

    def test_missing_changed_source_schema_rubric_map_and_dependency_refuse(self):
        attacks = [('shared/agents/worker-retention.json', lambda p: p.write_bytes(p.read_bytes() + b' ')),
                   ('shared/agents/worker-retention.schema.json', lambda p: p.unlink()),
                   ('shared/agents/worker-result.schema.json', lambda p: p.write_text('{"type":"object"}')),
                   ('references/plan-review-rubric.md', lambda p: p.write_text('A weakened rubric.')),
                   ('shared/agents/boundaries.md', lambda p: p.write_text('Workers can accept their output.')),
                   ('plugins/imps/agents/auditor.md', lambda p: p.write_text(p.read_text() + '\nChanged original source.\n')),
                   ('plugins/imps/plugin.json', lambda p: p.write_bytes(p.read_bytes() + b' '))]
        for relative, edit in attacks:
            with self.subTest(relative=relative):
                source = self.box.source_copy('imps')
                target = source / ('plugins/imps/' + relative if relative.startswith('references/') else relative)
                edit(target)
                case = self.make('imps/reviewer', source=source)
                proc = self.prepare(case, check=False)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertRegex(proc.stderr, 'retention_|missing|No such file')
        case = self.make(); self.prepare(case)
        self.edit_state(case, lambda s: s['pins'].pop('imps'))
        self.assert_refusal(self.ingest(case, check=False), 'pin/dependency mismatch')

    def test_rehashed_weakened_map_never_renews_semantic_approval(self):
        source = self.box.source_copy('imps')
        path = source / 'shared/agents/worker-retention.json'
        value = json.loads(path.read_text())
        profile = next(p for p in value['profiles'] if p['id'] == 'imps/investigator')
        profile['procedure']['text'] = 'A very small replacement; load all instructions later.'
        profile['procedure'].update(bytes=len(profile['procedure']['text'].encode()), sha256=digest(profile['procedure']['text'].encode()))
        path.write_bytes(canonical(value))
        case = self.make(source=source)
        self.assert_refusal(self.prepare(case, check=False), 'retention_approval_changed')

    def test_exact_serialized_measurements_and_dependency_only_control(self):
        case = self.make('imps/reviewer'); self.prepare(case)
        state = self.box.state_of(case['job'])
        authority = state['tasks'][0]['brief_authorities'][case['brief']['request_id']]
        full = json.loads(Path(authority['path']).read_bytes())
        baseline = copy.deepcopy(full); baseline['effective_brief_sha256'] = digest(canonical(full))
        controlled = copy.deepcopy(full); controlled.pop('dependency_pins')
        controlled['effective_brief_sha256'] = digest(canonical(controlled))
        self.assertEqual({k: v for k, v in baseline.items() if k not in ('dependency_pins', 'effective_brief_sha256')},
                         {k: v for k, v in controlled.items() if k != 'effective_brief_sha256'})
        self.assertLessEqual(len(canonical(controlled)), len(canonical(baseline)) / 2)
        self.assertEqual(sum(account(baseline).values()), len(canonical(baseline)))
        manifest = json.loads((ROOT / 'shared/agents/worker-retention.json').read_text())
        for profile in manifest['profiles']:
            shown = json.loads(self.box.t3('agents', 'show', *profile['id'].split('/'), '--compact').stdout)
            measured = {'definition': shown['definition'], 'transport_instructions': case['brief']['transport_instructions'],
                        'result_contract': {'schema_version': 1, 'transport': 'worker-result-v1'}, 'artifact_limit_bytes': 16777216}
            self.assertLessEqual(len(procedural_bytes(measured)), 24576, profile['id'])

    def test_public_ape_prepare_dispatch_result_and_real_acceptance(self):
        from tests.test_rebuild_integration import ApeJob
        job = ApeJob(self, self.box, 'compact-real-ape-' + str(next(self.ids)))
        plan = job.plan(); plan['policy']['worker_brief_transport'] = COMPACT
        self.box.create(job.pkg, plan)
        job.run_stage('s1')
        self.assertEqual(job.statuses()['s1'], 'accepted-at-snapshot')
        assigned = deserialize(Path(self.box.state_of(job.job_id)['tasks'][0]['brief']['path']).read_bytes())
        self.assertEqual(assigned['transport'], COMPACT)
        # Refusing a changed projection is observable at public acceptance too.
        path = Path(self.box.state_of(job.job_id)['tasks'][0]['brief']['path'])
        path.write_bytes(path.read_bytes() + b' ')
        proc = self.box.accept(job.pkg, 'validate', job.job_id, {'stage_id': 's1'})
        self.assertNotEqual(proc.returncode, 0)


class PinnedLegacyRuntimeTest(unittest.TestCase):
    def test_old_installed_runtime_really_resumes_v1_and_rejects_new_schema(self):
        with tempfile.TemporaryDirectory(prefix='compact-legacy-') as directory:
            root = Path(directory)
            archive = subprocess.run(['git', 'archive', 'HEAD'], cwd=ROOT, capture_output=True, check=True).stdout
            source = root / 'old-source'; source.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                for member in tar.getmembers():
                    path = Path(member.name)
                    if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():
                        raise AssertionError('unsafe legacy source archive')
                    tar.extract(member, source)
            box = Sandbox(root / 'sandbox')
            result = box.run([sys.executable, source / 'scripts/install.py', '--plugin', 'imps',
                              '--prefix', box.prefix, '--agents-root', box.agents])
            package = Path(json.loads(result.stdout)['data']['version_dir'])
            receipt = json.loads((package / 'install-manifest.json').read_text())
            before = {p.relative_to(package).as_posix(): digest(p.read_bytes()) for p in package.rglob('*') if p.is_file()}
            self.assertEqual(before['shared/compact_briefs.py'], digest((package / 'shared/compact_briefs.py').read_bytes()))
            fixture = CompactInstalledTest(methodName='test_default_v1_full_definition_and_schema_stay_identical')
            fixture.box, fixture.packages, fixture.ids = box, {'imps': (package, receipt)}, itertools.count()
            case = fixture.make(compact=False); fixture.prepare(case)
            self.assertEqual(case['brief']['schema_version'], 1)
            self.assertNotIn('transport', case['brief'])
            first = fixture.ingest(case)
            self.assertEqual(first['status'], 'awaiting-acceptance')
            resumed = box.job(package, 'overview', case['job'])
            self.assertEqual(resumed['job_id'], case['job'])
            # Execute the old installed validator, not the current source schema.
            new_box = Sandbox(root / 'new-sandbox')
            new_package, new_receipt = new_box.install('imps')
            new_fixture = CompactInstalledTest()
            new_fixture.box, new_fixture.packages, new_fixture.ids = new_box, {'imps': (new_package, new_receipt)}, itertools.count()
            new_case = new_fixture.make(); new_fixture.prepare(new_case)
            candidate = Path(new_case['descriptor']['path'])
            self.assertTrue(candidate.read_bytes().startswith(MAGIC))
            probe = box.private / 'old-consumer.py'
            probe.write_text("import json,sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom core.schema import errors\nfrom core.jobs.store import strict_load\np=Path(sys.argv[1])\ntry:\n value=strict_load(Path(sys.argv[2]).read_bytes())\nexcept ValueError:\n print('old installed consumer rejects the actual compact frame')\nelse:\n assert errors(value,json.loads((p/'shared/agents/worker-brief.schema.json').read_text())), 'old consumer partially accepted new format'\n")
            box.run([sys.executable, probe, package, candidate])
            after = {p.relative_to(package).as_posix(): digest(p.read_bytes()) for p in package.rglob('*') if p.is_file()}
            self.assertEqual(after, before)


class CompactAdopterPathsTest(unittest.TestCase):
    """Run existing real domain scenarios with explicit new-format creation.

    Their validators, observations, failures, repairs and acceptance assertions
    remain intact. Only NEW fixture job creation opts into transport v2.
    """
    def run_scenario(self, cls, method, patcher):
        result = unittest.TestResult()
        if hasattr(cls, 'setUpClass'):
            cls.setUpClass()
        try:
            with patcher:
                cls(method).run(result)
        finally:
            if hasattr(cls, 'tearDownClass'):
                cls.tearDownClass()
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.errors + result.failures, [], '\n'.join(t for _, t in result.errors + result.failures))

    def test_imps_native_gate_repair_stage_and_final_acceptance(self):
        from tests.test_imps_workflow import ImpsWholeJobTest
        from tests import imps_plan_review_fixtures as fixture
        original = fixture.select_legacy_imps_job
        def chosen(job, *args, **kwargs):
            job['policy']['worker_brief_transport'] = COMPACT
            return original(job, *args, **kwargs)
        self.run_scenario(ImpsWholeJobTest, 'test_installed_job_runs_stage_gate_and_final_gate',
                          mock.patch.object(fixture, 'select_legacy_imps_job', side_effect=chosen))

    def test_babysitter_repair_followup_and_acceptance(self):
        from tests.test_babysitter_workflow import SyntheticJobTest
        original = SyntheticJobTest.plan
        def chosen(case, *args, **kwargs):
            plan = original(case, *args, **kwargs)
            plan['policy']['worker_brief_transport'] = COMPACT
            return plan
        self.run_scenario(SyntheticJobTest, 'test_repeated_needs_followup_escalates_instead_of_stranding_the_slot',
                          mock.patch.object(SyntheticJobTest, 'plan', new=chosen))

    def test_configuration_audit_and_real_validator(self):
        from tests.test_agent_tuneup_workflow import SyntheticJobTest
        original = SyntheticJobTest.create
        def chosen(case, job):
            job['policy']['worker_brief_transport'] = COMPACT
            return original(case, job)
        self.run_scenario(SyntheticJobTest, 'test_audit_job_accepts_reported_findings_and_rejects_settings_changes',
                          mock.patch.object(SyntheticJobTest, 'create', new=chosen))

    def test_factual_and_cold_read_stronger_gates_and_isolation(self):
        from tests.test_elephant_goldfish_repairs import ElephantRepairJobTests
        original = ElephantRepairJobTests.create
        def chosen(case, job):
            job.setdefault('policy', {})['worker_brief_transport'] = COMPACT
            return original(case, job)
        self.run_scenario(ElephantRepairJobTests, 'test_factual_and_cold_read_acceptance_stay_distinct_and_cold_reader_is_isolated',
                          mock.patch.object(ElephantRepairJobTests, 'create', new=chosen))

    def test_all_declared_planning_workers_use_installed_public_lifecycle(self):
        from tests.test_planning_review import PlanningReviewTests
        PlanningReviewTests.setUpClass()
        try:
            for plugin in PLANNING_PLUGINS:
                with self.subTest(plugin=plugin):
                    case = PlanningReviewTests('test_delegated_public_acceptance_and_installed_parent_consumption')
                    case.setUp()
                    case.package, case.manifest = case.box.install(plugin)
                    meta = json.loads((case.package / 'plugin.json').read_text())
                    case.snapshot_data['output_type'] = meta['planning_review']['output_types'][0]
                    original = case.cli
                    def installed(command, data=None, **kwargs):
                        kwargs['installed'] = True
                        return original(command, data, **kwargs)
                    case.cli = installed
                    case.create(extra={'plugin': plugin, 'worker_brief_transport': COMPACT}, installed=True)
                    attempt = case.attempt()
                    brief = deserialize(Path(attempt['path']).read_bytes())
                    assert_result_version_instruction(self, brief)
                    self.assertEqual(brief['worker_id'], meta['planning_review']['worker_id'])
                    self.assertNotEqual(brief['worker_id'], 'imps/auditor')
                    self.assertEqual(brief['transport'], COMPACT)
                    supplied = brief['resources']['planning_snapshot']['rubrics'][0]
                    if 'text' in supplied:
                        self.assertEqual(supplied['text'], case.rubric.read_text())
                    else:
                        self.assertIs(supplied.get('inline_definition'), True)
                        self.assertIn(case.rubric.read_text(), brief['definition'])
                    self.assertNotIn('path', brief['resources']['planning_snapshot']['rubrics'][0])
                    self.assertEqual(case.result(attempt)['outcome'], 'approved')
                    reference = case.finish()
                    case.cli('validate', {'reference': reference, 'expected_snapshot': case.snapshot['sha256']})
                    case.doCleanups()
        finally:
            PlanningReviewTests.tearDownClass()


if __name__ == '__main__':
    unittest.main()
