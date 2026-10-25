"""Planning draft diagnostics through the public source and installed CLI."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from core.jobs.store import canonical, digest
from shared import planning_review as planning
from tests import test_planning_review as fixtures
from tests.test_rebuild_installed import tree_digest


class DraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PlanningReviewTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.PlanningReviewTests.tearDownClass()

    def setUp(self):
        self.f = fixtures.PlanningReviewTests()
        self.f.setUp()
        self.f.create(installed=True)
        self.attempt = self.f.attempt()
        self.job_dir = Path(self.attempt['path']).parent.parent
        self.artifacts = self.job_dir / 'artifacts/tasks' / self.attempt['task_id']
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.draft = self.artifacts / 'draft.json'

    def save(self, result=None, raw=None):
        self.draft.write_bytes(raw if raw is not None else canonical(
            result if result is not None else self.f.draft_result(self.attempt)))

    def check(self, *, installed=False, ok=True, extra=None):
        payload = dict(brief_file=self.attempt['path'], brief_sha256=self.attempt['sha256'],
                       result_file=str(self.draft))
        payload.update(extra or {})
        source = self.f.package if installed else fixtures.ROOT
        # Write the command input before taking the read-only observation.
        input_file = self.f.box.payload(payload)
        before = tree_digest(self.f.box.state)
        names = sorted(str(p.relative_to(self.f.box.state)) for p in self.f.box.state.rglob('*'))
        proc = self.f.box.run([sys.executable, source / 'shared/planning_review_cli.py',
                              'check-draft', '--input', input_file], check=False)
        self.assertEqual(proc.returncode, 0 if ok else 2, proc.stdout + proc.stderr)
        self.assertEqual(tree_digest(self.f.box.state), before)
        self.assertEqual(sorted(str(p.relative_to(self.f.box.state)) for p in self.f.box.state.rglob('*')), names)
        return json.loads(proc.stdout) if proc.stdout else {'errors': [proc.stderr]}

    def test_public_source_and_relocated_install_are_non_accepting_and_read_only(self):
        self.save()
        brief = json.loads(Path(self.attempt['path']).read_text())
        offered = brief['resources']['draft_check']
        self.assertEqual(offered['command'], 'check-draft')
        self.assertEqual(offered['maximum_correction_cycles'], 1)
        self.assertTrue(offered['requires_declared_procedural_reads'])
        self.assertEqual(digest(Path(offered['helper']['path']).read_bytes()), offered['helper']['sha256'])
        self.assertFalse(offered['acceptance'])
        moved = self.f.package.parent / 'relocated-draft-package'
        import shutil
        shutil.copytree(self.f.package, moved)
        for installed in (False, True):
            if installed:
                self.f.package = moved
            out = self.check(installed=installed)
            self.assertTrue(out['valid'])
            self.assertFalse(out['acceptance'])
            self.assertIn('host_identity_options_and_fresh_execution', out['deferred_checks'])
        with patch.object(planning, 'pinned_store', side_effect=AssertionError('must not open live state')):
            self.assertTrue(planning.check_draft(self.attempt['path'], self.attempt['sha256'], self.draft)['valid'])

    def test_invalid_drafts_match_strict_contract_without_charging(self):
        baseline = self.f.draft_result(self.attempt)
        cases = [(b'not JSON', 'invalid JSON'),
                 (b'{"schema_version":1,"schema_version":1}', 'duplicate'),
                 (b' ' * 32769, 'oversize')]
        for field in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256'):
            bad = dict(baseline, **{field: '0' * 64 if field == 'effective_brief_sha256' else 'wrong'})
            cases.append((canonical(bad), 'correlation'))
        for edit, expected in (
            (lambda r: r.update(commands=[{'argv': 'not-an-array'}]), 'argv'),
            (lambda r: r['planning_review'].update(coverage=[]), 'coverage'),
            (lambda r: r.update(planning_review=['not-an-object']), 'object'),
            (lambda r: r.update(requirements=[]), 'coverage'),
            (lambda r: r['requirements'][0].update(status='failed'), 'contradicts'),
            (lambda r: r['planning_review'].update(responses=[{'finding_key': 'anthropic:missing',
                'status': 'open', 'evidence': 'fixture'}]), 'unknown retained'),
            (lambda r: r.update(findings=[dict(self.f.finding(), severity='minor', smallest_correction='')]), 'smallest correction'),
        ):
            result = deepcopy(baseline)
            edit(result)
            cases.append((canonical(result), expected))
        for raw, error in cases:
            with self.subTest(error=error, raw=raw[:60]):
                self.save(raw=raw)
                out = self.check(ok=False)
                self.assertIn(error, str(out['errors']))

    def test_valid_adverse_draft_is_not_approval_and_malformed_return_keeps_major(self):
        major = self.f.finding()
        result = self.f.draft_result(self.attempt, findings=[major], verdict='adverse')
        self.save(result)
        self.assertTrue(self.check()['valid'])
        self.save(dict(result, review_verdict='approve'))
        self.assertIn('adverse verdict', str(self.check(ok=False)['errors']))
        out = self.f.result(self.attempt, findings=[major], verdict='adverse',
                           edit=lambda r: r.update(commands=[{'argv': 'malformed'}]))
        self.assertEqual(out['outcome'], 'incomplete')
        receipt = self.f.cli('validate', {'reference': self.f.finish(accepted=False)}, ok=False)
        self.assertTrue(receipt)
        state = json.loads(Path(self.f.created['subject_file']).read_text())
        self.assertEqual(state['rounds_used'], 1)
        self.assertEqual(state['findings']['anthropic:F1']['finding'], major)
        self.assertEqual(state['findings']['anthropic:F1']['status'], 'open')

    def test_actual_out_of_scope_read_is_not_filtered_and_ingest_still_refuses(self):
        actual = str(self.f.write('outside.py', 'OUTSIDE = True\n'))
        result = self.f.draft_result(self.attempt)
        result['planning_review']['inspected_paths'].append(actual)
        self.save(result)
        self.assertIn('unexpected inspected path', str(self.check(ok=False)['errors']))
        self.assertIn(actual, json.loads(self.draft.read_text())['planning_review']['inspected_paths'])
        out = self.f.result(self.attempt, edit=lambda r: r['planning_review']['inspected_paths'].append(actual))
        self.assertEqual(out['outcome'], 'incomplete')

    def test_passing_draft_cannot_clear_identity_or_changed_input_failures(self):
        self.save()
        self.assertTrue(self.check()['valid'])
        out = self.f.result(self.attempt, identity=False)
        self.assertEqual(out['outcome'], 'incomplete')
        self.assertIn('identity', out['error'])
        self.f.source.write_text('VALUE = 2\n')
        self.assertIn('drift', str(self.check(ok=False)['errors']))

    def test_brief_hash_draft_subtree_and_symlinks_fail_closed(self):
        self.save()
        self.assertIn('hash differs', str(self.check(ok=False, extra={'brief_sha256': '0' * 64})['errors']))
        foreign = self.f.write('foreign-draft.json', self.draft.read_text())
        self.assertIn('escapes assigned', str(self.check(ok=False, extra={'result_file': str(foreign)})['errors']))
        self.draft.unlink()
        self.draft.symlink_to(foreign)
        self.check(ok=False)

    def test_document_only_or_wrong_role_brief_cannot_use_planning_checker(self):
        self.save()
        original = json.loads(Path(self.attempt['path']).read_text())
        for change in ({'document': {'path': 'fixture-document'}}, {'role': 'worker'}):
            brief = dict(original, **change)
            brief.pop('effective_brief_sha256')
            brief['effective_brief_sha256'] = digest(canonical(brief))
            path = Path(self.attempt['path']).parent / 'unsupported-brief.json'
            raw = canonical(brief)
            path.write_bytes(raw)
            out = self.check(ok=False, extra={'brief_file': str(path), 'brief_sha256': digest(raw)})
            self.assertIn('never a document-only/cold-read', str(out['errors']))

    def test_custom_provider_alias_uses_frozen_lineage_for_new_finding_responses(self):
        f = fixtures.PlanningReviewTests()
        f.setUp()
        f.selection_data = json.loads(json.dumps(f.selection_data).replace('fixture-review', 'custom-review').replace('claude-fixture', 'opus'))
        next(p for p in f.selection_data['capabilities']['providers']
             if p['providerInstanceId'] == 'custom-review')['driverKind'] = 'claudeAgent'
        f.create(installed=True)
        self.f, self.attempt = f, f.attempt()
        self.job_dir = Path(self.attempt['path']).parent.parent
        self.artifacts = self.job_dir / 'artifacts/tasks' / self.attempt['task_id']
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.draft = self.artifacts / 'draft.json'
        response = {'finding_key': 'anthropic:F1', 'status': 'open', 'evidence': 'fixture:new-minor-note'}
        edit = lambda r: r['planning_review'].update(responses=[response])
        self.save(f.draft_result(self.attempt, findings=[f.finding('minor')], edit=edit))
        self.assertTrue(self.check(installed=True)['valid'])
        self.assertEqual(f.result(self.attempt, findings=[f.finding('minor')], edit=edit)['outcome'], 'approved')

    def test_artifact_envelope_and_evidence_are_limited_to_assigned_task(self):
        result = self.f.draft_result(self.attempt)
        artifact = self.artifacts / 'full.json'
        raw = canonical(result)
        artifact.write_bytes(raw)
        envelope = {'schema_version': 1, 'correlation': {k: result[k] for k in
            ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256')},
            'artifact': {'path': str(artifact.relative_to(self.job_dir)), 'sha256': digest(raw),
                         'finding_count': 0, 'finding_ids': []}}
        self.save(envelope)
        self.assertTrue(self.check(installed=True)['valid'])
        envelope['artifact']['path'] = 'artifacts/tasks/foreign/full.json'
        self.save(envelope)
        self.assertIn('declared task subtree', str(self.check(ok=False)['errors']))


    def test_carry_provenance_legacy_recovery_and_negative_guards(self):
        f = self.f
        f.result(self.attempt, findings=[f.finding()], verdict='adverse')
        f.finish(accepted=False)
        source = f.write('rebuttal.txt', 'The caller already handles fixture recovery.')
        f.cli('disposition', {'finding_key': 'anthropic:F1', 'status': 'rejected',
            'evidence': {'reason': 'Caller handles recovery', 'source': str(source)}})
        f.cli('begin', {'requested_rereview': True})
        response = {'finding_key': 'anthropic:F1', 'status': 'rebuttal-agreed', 'evidence': 'fixture:agreed-recovery'}
        f.result(f.attempt(), edit=lambda r: r['planning_review'].update(responses=[response]))
        f.finish()
        original = json.loads(Path(f.created['subject_file']).read_text())
        clearing = deepcopy(original['findings']['anthropic:F1']['clearing'])
        job = {'planning': {'snapshot': f.snapshot}}
        assessment = f.assessment([response])
        for legacy in (False, True):
            state = deepcopy(original)
            if legacy:
                state['findings']['anthropic:F1']['clearing'].pop('content_sha256')
            previous = deepcopy(state['findings']['anthropic:F1']['clearing'])
            planning._responses(state, job, assessment, 'fresh-carry', 'anthropic', True, 'cross-lineage')
            self.assertEqual(state['findings']['anthropic:F1']['clearing'], previous)
        for severity in ('minor', 'note'):
            state = deepcopy(original)
            row = state['findings']['anthropic:F1']
            row['finding']['severity'] = severity
            row.pop('clearing')
            planning._responses(state, job, assessment, 'fresh-carry', 'anthropic', True, 'cross-lineage')
            self.assertEqual(state['findings']['anthropic:F1']['clearing'], clearing)
        for mutation, family, execution in (
            (lambda s, j: None, 'google', 'fresh-carry'),
            (lambda s, j: s['findings']['anthropic:F1'].update(lineage='unknown'), 'unknown', 'fresh-carry'),
            (lambda s, j: None, 'anthropic', clearing['execution_id']),
            (lambda s, j: j['planning']['snapshot'].update(content_sha256='0' * 64), 'anthropic', 'fresh-carry'),
            (lambda s, j: s['findings']['anthropic:F1'].update(status='open'), 'anthropic', 'fresh-carry'),
            (lambda s, j: s['findings']['anthropic:F1'].pop('clearing'), 'anthropic', 'fresh-carry'),
            (lambda s, j: s.update(rounds=[]) or s['findings']['anthropic:F1']['clearing'].pop('content_sha256'),
             'anthropic', 'fresh-carry'),
        ):
            state, current_job = deepcopy(original), deepcopy(job)
            mutation(state, current_job)
            before = deepcopy(state)
            with self.assertRaises(ValueError):
                planning._responses(state, current_job, assessment, execution, family, True, 'cross-lineage')
            self.assertEqual(state, before)


if __name__ == '__main__':
    unittest.main()
