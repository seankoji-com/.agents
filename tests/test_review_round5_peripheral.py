"""Round-5 PR review findings outside the run engine: artifact writes, recipe
evidence containment, the installer, the conformance grader and the schemas."""
import importlib.util
import json
import os
import py_compile
from pathlib import Path
from types import SimpleNamespace

from support import ROOT, CoreTestCase
import test_install

import sys
sys.path.insert(0, str(ROOT))
from core import blockers, recipe, schema  # noqa: E402
from core.errors import InvalidInput  # noqa: E402
from core.fsutil import sha256_bytes, sha256_file, write_artifact  # noqa: E402

_spec = importlib.util.spec_from_file_location('conformance_script', ROOT / 'scripts' / 'conformance.py')
conformance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conformance)


class ArtifactWriteTest(CoreTestCase):
    def test_existing_target_must_be_a_matching_regular_file(self):
        run_dir = self.tmp / 'run'
        run_dir.mkdir()
        data = b'payload'
        target = run_dir / 'artifacts' / 'host' / f'{sha256_bytes(data)[:12]}-cap.json'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'stale')
        entry = write_artifact(run_dir, 'host', 'cap.json', data)
        self.assertEqual(target.read_bytes(), data)
        self.assertEqual(sha256_file(run_dir / entry['path']), entry['sha256'])

        outside = self.tmp / 'outside.txt'
        outside.write_text('not yours')
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaises(InvalidInput) as caught:
            write_artifact(run_dir, 'host', 'cap.json', data)
        self.assertEqual(caught.exception.code, 'path_escape')
        self.assertEqual(outside.read_text(), 'not yours')


class RecipeEvidenceContainmentTest(CoreTestCase):
    def verified(self, directory, evidence_path):
        doc = directory / 'features' / 'f-x.md'
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text('# F-X\n')
        return {'schema_version': 1, 'project': 'x', 'status': 'verified', 'prerequisites': ['python3'],
                'launch': {'argv': ['python3', 'app.py'], 'ready': {'kind': 'file', 'path': 'ready', 'timeout_seconds': 5}},
                'doctor': [{'argv': ['python3', '--version']}], 'cleanup': [{'argv': ['true']}],
                'evidence': {'dir': 'evidence', 'expected': ['x']},
                'features': [{'id': 'F-X', 'name': 'x', 'doc': 'features/f-x.md',
                              'steps': [{'kind': 'command', 'argv': ['true']}],
                              'expect': [{'kind': 'exit_code', 'step': 1, 'equals': 0}]}],
                'verified_run': {'evidence': [{'path': evidence_path, 'sha256': sha256_file(self.secret)}]}}

    def test_evidence_outside_the_recipe_directory_is_rejected(self):
        directory = self.tmp / 'recipe'
        directory.mkdir()
        self.secret = self.tmp / 'secret.txt'
        self.secret.write_text('outside')
        (directory / 'link.txt').symlink_to(self.secret)
        for path in ('../secret.txt', str(self.secret), 'link.txt'):
            with self.subTest(path=path):
                found = recipe.problems(self.verified(directory, path), directory)
                self.assertTrue(any('escapes the recipe directory' in item for item in found), found)


class RecipeSchemaCouplingTest(CoreTestCase):
    def test_step_and_expect_fields_follow_kind(self):
        step, expect = schema.load_schema('recipe')['$defs']['step'], schema.load_schema('recipe')['$defs']['expect']
        root = schema.load_schema('recipe')
        self.assertEqual(schema.errors({'kind': 'http', 'method': 'GET', 'url': 'http://x'}, step, root), [])
        self.assertTrue(schema.errors({'kind': 'http', 'method': 'GET'}, step, root))
        self.assertTrue(schema.errors({'kind': 'command'}, step, root))
        self.assertEqual(schema.errors({'kind': 'json_equals', 'step': 1, 'path': 'ok', 'equals': True}, expect, root), [])
        for bad in ({'kind': 'json_equals', 'step': 1, 'equals': True}, {'kind': 'status', 'step': 1},
                    {'kind': 'contains', 'step': 1}, {'kind': 'exit_code'}):
            with self.subTest(expect=bad):
                self.assertTrue(schema.errors(bad, expect, root))


class StateSchemaShapeTest(CoreTestCase):
    def test_run_and_report_declare_review_and_check_shapes(self):
        run = json.loads((ROOT / 'tests' / 'fixtures' / 'schemas' / 'valid' / 'run--verifying.json').read_text())
        self.assertEqual(schema.errors(run, schema.load_schema('run')), [])
        bad = dict(run, reviews=[{'round': 1, 'verdict': 'maybe'}])
        self.assertTrue(schema.errors(bad, schema.load_schema('run')))
        bad = dict(run, policy=dict(run['policy'], review={'required': 'yes'}))
        self.assertTrue(schema.errors(bad, schema.load_schema('run')))
        report = schema.load_schema('report')
        self.assertTrue(any('review' in e for e in schema.errors({'review': {'required': True}}, report)))
        self.assertTrue(any('checks[0]' in e for e in schema.errors({'checks': [{'name': 'x'}]}, report)))

    def test_roles_schema_accepts_what_the_runtime_accepts(self):
        roles = schema.load_schema_file(ROOT / 'plugins' / 'imps' / 'schemas' / 'roles.schema.json')
        custom = {'tester': {'chain': [{'select': 'same_provider', 'of_role': 'tester', 'exclude_roles': ['docs']}]}}
        self.assertEqual(schema.errors(custom, roles), [])
        self.assertEqual(schema.errors({'schema_version': 1, 'roles': custom}, schema.load_schema('defaults')), [])


class BudgetBlockerTest(CoreTestCase):
    def blocker(self, seconds):
        ctx = SimpleNamespace(cli_path=Path('/pkg/core/cli.py'), state_root=Path('/state'), parent_thread_id=None)
        state = {'run_id': 'r1', 'budget': {'seconds': seconds, 'spent_seconds': seconds}, 'policy': {'repair_limit': 2},
                 'host': {}, 'blockers': [], 'plugin': {'entry': '/pkg/entry.md'}}
        return blockers.make(ctx, state, 'budget_exhausted', 'spent', (), 'now')

    def test_raise_budget_suggestion_stays_within_the_ceiling(self):
        argv = self.blocker(14400)['resume']['argv']
        self.assertEqual(argv[argv.index('--value') + 1], '18000')
        argv = self.blocker(84000)['resume']['argv']
        self.assertEqual(argv[argv.index('--value') + 1], '86400')

    def test_no_impossible_raise_at_the_ceiling(self):
        item = self.blocker(86400)
        self.assertEqual(item['resume']['decision'], 'none')
        self.assertIn('report', item['resume']['argv'])
        self.assertNotIn('unblock', item['resume']['argv'])
        self.assertIsNone(item['resume']['then'])
        self.assertIn('86400', item['meaning'])


class ConformanceGraderTest(CoreTestCase):
    def test_pending_task_round_without_request_id_fails_the_check(self):
        state = {'tasks': [{'id': 'survey', 'status': 'accepted',
                            'rounds': [{'task_id': 't1', 'purpose': 'initial'},
                                       {'task_id': 't2', 'purpose': 'correction', 'client_request_id': 'c2'}]}],
                 'events': [{'kind': 'record:capabilities'}] * 2}
        verdict = conformance.grade('pending-task', state, {'reviews': []})
        checks = {item['name']: item['passed'] for item in verdict['checks']}
        self.assertFalse(checks['every round has its own clientRequestId'])
        self.assertTrue(checks['exactly one initial dispatch'])
        self.assertFalse(verdict['passed'])

    def test_sanitise_replaces_home_only_at_path_boundaries(self):
        original = conformance.HOME
        conformance.HOME = '/srv/u'
        try:
            self.assertEqual(conformance.sanitise('"/srv/u/x" /srv/u'), '"~/x" ~')
            for text in ('/srv/user2/x', '/data/srv/u/x', '/xsrv/u'):
                self.assertEqual(conformance.sanitise(text), text)
        finally:
            conformance.HOME = original

    def test_sanitise_replaces_a_per_user_temp_dir_but_not_shared_tmp(self):
        original = conformance.HOME, conformance.TEMP
        conformance.HOME, conformance.TEMP = '/srv/u', '/srv/u/scratch/s1'
        try:
            self.assertEqual(conformance.sanitise('--state-root /srv/u/scratch/s1/b1/state /srv/u/x'),
                             '--state-root $TMPDIR/b1/state ~/x')
            self.assertEqual(conformance.sanitise('/srv/u/scratch/s10/x'), '~/scratch/s10/x')
            conformance.TEMP = '/tmp'
            self.assertEqual(conformance.sanitise('/tmp/fixture'), '/tmp/fixture')
        finally:
            conformance.HOME, conformance.TEMP = original


class Round5InstallerTest(test_install.InstallTest):
    def test_install_lifecycle(self):
        pass  # covered by test_install.InstallTest

    def test_new_version_and_rollback(self):
        pass  # covered by test_install.InstallTest

    def test_activate_refuses_paths_outside_the_plugin_dir(self):
        first = self.installer()['data']
        victim = self.prefix / 'victim'
        victim.mkdir(parents=True)
        (victim / 'install-manifest.json').write_text(json.dumps({'files': []}))
        current = self.prefix / 'imps' / 'current'
        for value in ('../victim', str(victim), '.'):
            with self.subTest(value=value):
                out = self.installer('--activate', value, expect=2)
                self.assertEqual(out['error']['code'], 'unknown_version')
                self.assertEqual(os.readlink(current), first['version'])

    def test_corrupt_manifest_is_a_structured_error(self):
        version_dir = Path(self.installer()['data']['version_dir'])
        (version_dir / 'install-manifest.json').write_text('{not json')
        for args in ((), ('--uninstall',)):
            with self.subTest(args=args):
                out = self.installer(*args, expect=2)
                self.assertEqual(out['error']['code'], 'manifest_corrupt')
        out = self.installer('--activate', version_dir.name, expect=2)
        self.assertEqual(out['error']['code'], 'unknown_version', 'a corrupt snapshot is not activatable')
        self.installer('--force')
        self.assertIsInstance(json.loads((version_dir / 'install-manifest.json').read_text())['files'], list)
        self.installer('--uninstall')
        self.assertFalse(version_dir.exists())

    def test_uninstall_with_kept_file_still_removes_bytecode_of_deleted_modules(self):
        version_dir = Path(self.installer()['data']['version_dir'])
        module = version_dir / 'core' / 'fsutil.py'
        py_compile.compile(str(module), cfile=str(version_dir / 'core' / '__pycache__' / 'fsutil.cpython-310.pyc'))
        (version_dir / 'entry.md').write_text('edited by hand\n')
        out = self.installer('--uninstall')['data']
        self.assertEqual(len(out['kept_modified']), 1)
        self.assertFalse(module.exists())
        self.assertFalse((version_dir / 'core' / '__pycache__').exists(), 'stale bytecode of a removed module')
        self.assertEqual((version_dir / 'entry.md').read_text(), 'edited by hand\n')
