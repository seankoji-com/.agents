"""Behavior through source and installed thinking CLIs and real planning receipts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from tests.upfront_fixtures import approved_selection
from tests.thinking_plan_review_fixtures import ThinkingPlanFixture
from tests.test_rebuild_installed import ROOT, tree_digest


class ThinkingPlanReviewCommands:
    installed = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='thinking-plan-review-')
        self.addCleanup(self.temp.cleanup)
        self.fixture = ThinkingPlanFixture(Path(self.temp.name) / 'fixture')
        package = self.fixture.install()
        self.scripts = (package if self.installed else ROOT / 'plugins/elephant-goldfish') / 'scripts'
        self.root = self.fixture.box.private / 'thinking'
        self.topic = self.root / 'topic'
        self.cap = self.fixture.box.payload({'inheritedProviderInstanceId': 'fixture-work',
            'inheritedModel': 'gpt-fixture', 'parentThreadId': 'fixture-source-author',
            'providers': [{'providerInstanceId': 'fixture-work', 'driverKind': 'codex',
                           'models': [{'id': 'gpt-fixture'}]}]})
        self.state('init', '--output-type', 'implementation')
        (self.topic / 'discovery.md').write_text('# Discovery\nKeep the fixture read-only; describe recovery.\n')
        (self.topic / 'spec.md').write_text('# Acceptance\n[REQ-SAFE] No writes; recovery is observable.\n')
        self.accept()
        # Record every source author before the review, including attachments.
        for doc in ('discovery.md', 'spec.md'):
            self.state('author', doc, '--capabilities', self.cap)
        self.templates = self.fixture.box.private / 'templates'
        shutil.copytree(package / 'templates', self.templates)
        self.attachment = self.fixture.box.private / 'implementation-plan.md'
        self.attachment.write_text('Read the fixture and report recovery without executing writes.\n')
        from shared.document_authors import append_author, locked_author_records
        with locked_author_records(self.attachment.parent) as (records, save):
            save(append_author(records, self.attachment.read_bytes(), json.loads(self.cap.read_text()),
                               document_path=self.attachment))

    def run_script(self, name, args=(), ok=True):
        proc = self.fixture.box.run([sys.executable, self.scripts / name, '--root', self.root, *args], check=False)
        self.assertEqual(proc.returncode, 0 if ok else 1, proc.stdout + proc.stderr)
        return proc

    def state(self, command, *args, ok=True):
        return self.fixture.command(self.scripts, self.root, 'topic', command, *map(str, args), ok=ok)

    def accept(self):
        return self.state('review', '--decision', 'accepted', '--scope', 'finalise-brief',
            '--discovery-sha256', hashlib.sha256((self.topic / 'discovery.md').read_bytes()).hexdigest(),
            '--evidence-ref', 'fixture:owner-discovery', '--operator-statement', 'I accept this exact discovery.')

    def approve(self, **kwargs):
        return self.fixture.approve(self.scripts, self.root, 'topic', template_dir=self.templates,
                                    attachments=[self.attachment], **kwargs)

    def render(self, *args, ok=True):
        return self.run_script('render_handoff.py', ['topic', '--capabilities', self.cap,
            '--template-dir', self.templates, *args], ok=ok)

    def validate(self, mode, ok=True):
        proc = self.run_script('validate_document.py', ['--slug', 'topic', '--mode', mode], ok=ok)
        self.assertEqual(json.loads(proc.stdout)['accepted'], ok)

    def assert_blocked(self):
        for data in (self.state('resolve'), json.loads(self.run_script('thinking_state.py', ['list']).stdout)['topics'][0]):
            self.assertEqual(data['next_phase'], 'plan_review', data)
            self.assertFalse(data['plan_review']['ready'])
            self.assertFalse(data['execution_authorized'])
        self.state('gate', '--require', 'discovery,spec,plan_review', ok=False)
        self.render(ok=False)
        self.render('--stdout', ok=False)
        self.validate('plan-review', ok=False)
        self.validate('handoff', ok=False)

    def test_predraft_admission_missing_tampered_wrong_scope_and_retroactive_selection_refused(self):
        from tests.thinking_plan_review_fixtures import init_selection_args
        def init(slug, extras=()):
            return self.fixture.box.run([sys.executable, self.scripts / 'thinking_state.py',
                '--root', self.root, 'init', slug, '--output-type', 'implementation', *extras], check=False)
        self.assertEqual(init('missing').returncode, 1)
        self.assertFalse((self.root / 'missing').exists())
        args = init_selection_args(self.fixture.box.private, 'new')
        wrong = list(args); wrong[-1] = 'fixture:request:wrong'
        self.assertEqual(init('new', wrong).returncode, 1)
        path = Path(args[1]); original = path.read_bytes()
        data = json.loads(original); data['source']['answer'] = 'Changed answer'
        path.write_text(json.dumps(data)); self.assertEqual(init('new', args).returncode, 1)
        path.write_bytes(original)
        drafted = self.root / 'new'; drafted.mkdir(); (drafted / 'discovery.md').write_text('Already drafted.')
        self.assertEqual(init('new', args).returncode, 1)
        meta = self.topic / 'meta.json'; original_meta = meta.read_bytes()
        data = json.loads(original_meta); data.pop('model_admission'); meta.write_text(json.dumps(data))
        self.state('author', 'spec.md', '--capabilities', self.cap, ok=False)
        self.state('resolve')  # Legacy/status remains readable.
        meta.write_bytes(original_meta)
        self.fixture.prepare(self.scripts, self.root, 'topic')
        self.fixture.begin()
        payload = {'job_id': 'wrong-selection', 'installation_id': self.fixture.manifest['installation_id'],
                   'plugin': 'elephant-goldfish', 'project_id': self.fixture.selection['project_id'],
                   'owner': 'fixture-owner', 'invocation_id': self.fixture.selection['invocation_id'],
                   'scope_id': self.fixture.snapshot['logical_output_id'], 'snapshot': self.fixture.snapshot}
        from shared import model_selection as models
        changed = deepcopy(self.fixture.snapshot['thinking_admission']['selection'])
        # A genuinely sealed different selection still cannot replace the producing answer.
        changed.pop('selection_sha256'); changed['source']['answer'] = 'Choose again after drafting.'
        changed['source']['sha256'] = models.digest(changed['source']['answer'])
        payload['selection'] = approved_selection(changed)
        self.fixture.cli('create', payload, ok=False)

    def test_positive_delegated_and_direct_receipts_reach_all_public_paths(self):
        for direct in (False, True):
            with self.subTest(direct=direct):
                if direct:
                    self.setUp()
                self.assertEqual(self.state('resolve')['next_phase'], 'plan_review')
                accepted = self.approve(direct=direct)
                self.assertTrue(accepted['ready'])
                self.assertEqual(accepted['modes'], ['self-review'] if direct else ['cross-lineage'])
                self.state('gate', '--require', 'discovery,spec,plan_review')
                self.validate('plan-review')  # Source review precedes handoff existence.
                self.render()
                self.render('--check')
                self.validate('handoff')
                first = self.state('resolve')
                self.assertEqual(first['next_phase'], 'delivery')
                self.assertFalse(first['endpoint_complete'])
                self.assertFalse(first['execution_authorized'])
                manifest = json.loads((self.topic / 'handoff.manifest.json').read_text())
                self.assertEqual(manifest['schema'], 3)
                self.assertEqual(manifest['plan_review']['reference'], self.fixture.reference)
                before = self.fixture.box.state_of(self.fixture.job_id)
                self.render()  # Rerender changes output time, never the source subject/budget.
                self.state('resolve')
                self.assertEqual(before, self.fixture.box.state_of(self.fixture.job_id))
                self.assertNotIn('handoff.md', [Path(r['path']).name for r in self.fixture.snapshot['documents']])
                for doc in ('discovery.md', 'spec.md'):
                    self.assertIn((self.topic / doc).read_bytes(), (self.topic / 'handoff.md').read_bytes())

    def test_missing_malformed_boolean_and_tampered_receipts_cannot_pass(self):
        self.assert_blocked()
        self.approve()
        self.render()
        meta_path = self.topic / 'meta.json'
        original = json.loads(meta_path.read_text())
        for reference in (None, True, {'accepted': True}, {'path': '/missing', 'sha256': '0'*64, 'bytes': 0}):
            with self.subTest(reference=reference):
                meta = deepcopy(original)
                meta['plan_review']['reference'] = reference
                meta_path.write_text(json.dumps(meta))
                self.assert_blocked()
        meta_path.write_text(json.dumps(original))
        receipt_path = Path(self.fixture.reference['path'])
        original_receipt = receipt_path.read_bytes()
        receipt_path.write_bytes(original_receipt + b' ')
        self.assert_blocked()
        receipt_path.write_bytes(original_receipt)
        receipt_path.unlink()
        self.assert_blocked()

    def test_each_source_attachment_request_decision_template_and_relevant_byte_change_stales(self):
        self.approve()
        self.render()
        paths = [self.topic / 'spec.md', self.attachment,
                 Path(self.fixture.inputs['requests'][0]['path']), Path(self.fixture.inputs['decisions'][0]['path']),
                 self.templates / 'handoff.implementation.md', Path(self.fixture.inputs['evidence_paths'][0])]
        for path in paths:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b'\nchanged reviewed bytes\n')
                self.assert_blocked()
                path.write_bytes(original)
                self.assertTrue(self.state('resolve')['plan_review']['ready'])
        # A tracked, dirty source is bound just as an untracked one is.
        repo = self.fixture.inputs['repository_root']
        self.fixture.box.run(['git', '-C', repo, 'add', 'source.py'])
        self.fixture.box.run(['git', '-C', repo, '-c', 'user.email=fixture@example.invalid', '-c', 'user.name=Fixture',
                              'commit', '-qm', 'track fixture'])
        self.assertTrue(self.state('resolve')['plan_review']['ready'])
        Path(self.fixture.inputs['evidence_paths'][0]).write_text('VALUE = 99\n')
        self.assert_blocked()

    def test_owner_acceptance_and_decisions_are_separate_and_unchanged_resume_reuses_review(self):
        self.approve()
        self.render()
        owner = self.state('resolve')['meta']['review']
        for _ in range(2):
            self.assertTrue(self.state('resolve')['plan_review']['ready'])
        self.assertEqual(owner, self.state('resolve')['meta']['review'])
        path = self.topic / 'meta.json'
        original = json.loads(path.read_text())
        changed = deepcopy(original)
        changed['review']['operator_statement'] = 'A different scoped owner decision.'
        path.write_text(json.dumps(changed))
        self.assert_blocked()
        path.write_text(json.dumps(original))
        (self.topic / 'discovery.md').write_text('Changed discovery needs owner acceptance.\n')
        self.assertEqual(self.state('resolve')['next_phase'], 'discovery_review')
        self.assertFalse(self.state('resolve')['plan_review']['ready'])
        self.accept()
        self.assertEqual(self.state('resolve')['next_phase'], 'plan_review')

    def test_unrelated_head_moves_and_metadata_do_not_force_review_or_grant_execution(self):
        self.approve()
        self.render()
        repo = self.fixture.inputs['repository_root']
        Path(repo, 'unrelated.txt').write_text('Unrelated change.\n')
        self.fixture.box.run(['git', '-C', repo, 'add', 'unrelated.txt'])
        self.fixture.box.run(['git', '-C', repo, '-c', 'user.email=fixture@example.invalid', '-c', 'user.name=Fixture',
                              'commit', '-qm', 'unrelated fixture'])
        result = self.state('resolve')
        self.assertTrue(result['plan_review']['ready'])
        self.assertTrue(result['plan_review']['head_observation']['changed'])
        self.state('set', 'execution_request.source=fixture:explicit-user-transition',
                   'execution_request.scope=fixture-only')
        result = self.state('resolve')
        self.assertTrue(result['has_execution_request'])
        self.assertFalse(result['execution_authorized'])
        self.validate('handoff')

    def test_real_job_result_and_snapshot_tampering_invalidate_consumers(self):
        self.approve()
        self.render()
        job = self.fixture.box.jobs / self.fixture.job_id / 'job.json'
        original = job.read_bytes()
        data = json.loads(original)
        data['model_selection']['review_panel'][0]['target']['options'] = {}
        job.write_text(json.dumps(data))
        self.assert_blocked()
        job.write_bytes(original)
        snapshot = self.topic / 'plan-review.snapshot.json'
        snapshot.write_bytes(snapshot.read_bytes() + b' ')
        self.assert_blocked()

    def test_legacy_complete_is_labelled_without_mutation_and_cannot_rerender_unreviewed(self):
        self.approve()
        self.render()
        # Reconstruct the prior format as a fixture, not by changing frozen plans.
        path = self.topic / 'meta.json'
        meta = json.loads(path.read_text())
        for key in ('plan_review', 'plan_review_policy', 'plan_review_inputs', 'model_admission'):
            meta.pop(key, None)
        path.write_text(json.dumps(meta))
        manifest_path = self.topic / 'handoff.manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['schema'] = 2
        for key in ('plan_review', 'template', 'rubric'):
            manifest.pop(key)
        manifest_path.write_text(json.dumps(manifest))
        before = tree_digest(self.topic)
        state = self.state('resolve')
        self.assertEqual(state['next_phase'], 'complete')
        self.assertEqual(state['plan_review']['status'], 'legacy-unreviewed')
        self.assertFalse(state['plan_review']['ready'])
        self.assertEqual(self.state('gate', '--require', 'discovery,spec,handoff')['gate'], 'legacy-unreviewed')
        self.render('--check')
        self.render(ok=False)
        self.validate('handoff', ok=False)
        self.assertEqual(before, tree_digest(self.topic))
        (self.topic / 'spec.md').write_text('[REQ-SAFE] Changed historical plan.\n')
        self.assert_blocked()

    def test_drafts_and_metadata_shortcuts_do_not_satisfy_plan_review(self):
        for pair in ('plan_review=true', 'plan_review.reference={"accepted":true}', 'plan_review_policy=0'):
            self.state('set', pair, ok=False)
        (self.topic / 'spec.md').write_text('<!-- thinking:draft -->\nDRAFT. Non-executable.\n[REQ-SAFE] Pending.\n')
        self.state('gate', '--require', 'discovery,spec', '--draft')
        self.render('--draft')
        self.render(ok=False)
        self.assertFalse((self.topic / 'handoff.md').exists())
        self.assertFalse(self.state('resolve')['execution_authorized'])

    def test_plan_review_document_mode_is_consumed_by_real_parent_acceptance(self):
        self.approve()
        box, package = self.fixture.box, self.fixture.package
        contract = {'root': str(self.root), 'slug': 'topic', 'mode': 'plan-review'}
        parent_id = 'parent-source-review'
        box.create(package, {'schema_version': 1, 'job_id': parent_id,
            'installation_id': self.fixture.manifest['installation_id'], 'workflow': 'elephant-goldfish/thinking',
            'owner': 'fixture-owner', 'requirements': {'REQ-PLAN': 'Consume an actual source-plan receipt'},
            'authorization': {'actions': ['read']}, 'constraints': ['offline fixture'],
            'dependencies': [{'key': 'eg', 'plugin': 'elephant-goldfish'}], 'pins': {},
            'stages': [{'id': 'plan-review', 'depends_on': [], 'requirements': ['REQ-PLAN'],
                'status': 'pending', 'execution_mode': 'direct', 'validator_dependency': 'eg',
                'validator_contract': contract}], 'tasks': [], 'decisions': [], 'history': [],
            'metrics': {}, 'result_contract': {'schema_version': 1}})
        caller = box.caller(self.fixture.manifest, 'elephant-goldfish/thinking')
        descriptor = box.publish(package, parent_id, caller, 'plan-review', contract)
        payload = {'caller': caller, 'stage_id': 'plan-review', 'input_file': descriptor,
            'validator_argv': [str(package / 'scripts/validate_document.py'),
                               '--root', str(self.root), '--slug', 'topic', '--mode', 'plan-review']}
        proc = box.accept(package, 'accept-stage', parent_id, payload)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        # A prior accepted flag cannot replace re-reading the now-missing receipt.
        Path(self.fixture.reference['path']).unlink()
        proc = box.accept(package, 'accept-stage', parent_id, payload)
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_handoff_and_receipt_are_refused_as_their_own_review_inputs(self):
        self.approve()
        self.render()
        before = (self.topic / 'meta.json').read_bytes()
        for path in (self.topic / 'handoff.md', Path(self.fixture.reference['path'])):
            with self.subTest(path=path.name):
                inputs = dict(self.fixture.inputs, attachments=[str(path)])
                result = self.state('plan-review', '--input', self.fixture.box.payload(inputs), ok=False)
                self.assertIn('circular', result['error'])
                self.assertEqual(before, (self.topic / 'meta.json').read_bytes())
        self.assertTrue(self.state('resolve')['plan_review']['ready'])


class TestThinkingPlanReviewSource(ThinkingPlanReviewCommands, unittest.TestCase):
    pass


class TestThinkingPlanReviewInstalled(ThinkingPlanReviewCommands, unittest.TestCase):
    installed = True
