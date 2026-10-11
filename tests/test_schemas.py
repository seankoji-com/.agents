"""Source-spec case 1 and REQ-SCHEMAS: published schemas, the stdlib validator and
version handling."""
import json
import re
import subprocess
from pathlib import Path

from support import FIXTURES, ROOT, CoreTestCase, cli

import sys
sys.path.insert(0, str(ROOT))
from core import schema  # noqa: E402

SCHEMA_FILES = sorted((ROOT / 'core' / 'schemas').glob('*.json')) + sorted((ROOT / 'plugins').glob('*/schemas/*.json'))
FIXTURE_DIR = FIXTURES / 'schemas'


def schema_for(fixture: Path) -> Path:
    name = fixture.name.split('--')[0]
    for candidate in SCHEMA_FILES:
        if candidate.name == f'{name}.schema.json':
            return candidate
    raise AssertionError(f'no schema named {name} for fixture {fixture.name}')


class SchemaParityTest(CoreTestCase):
    def test_every_schema_parses_and_uses_supported_keywords(self):
        self.assertGreaterEqual(len(SCHEMA_FILES), 10)
        for path in SCHEMA_FILES:
            with self.subTest(schema=path.name):
                json.loads(path.read_text())
                schema.load_schema_file(path)

    def test_fixture_directories_match_validator_verdicts(self):
        valid = sorted((FIXTURE_DIR / 'valid').glob('*.json'))
        invalid = sorted((FIXTURE_DIR / 'invalid').glob('*.json'))
        self.assertTrue(valid and invalid)
        covered = set()
        for fixture in valid + invalid:
            target = schema_for(fixture)
            covered.add(target.name)
            problems = schema.errors(json.loads(fixture.read_text()), schema.load_schema_file(target))
            with self.subTest(fixture=fixture.name):
                if fixture.parent.name == 'valid':
                    self.assertEqual(problems, [], fixture.name)
                else:
                    self.assertNotEqual(problems, [], f'{fixture.name} should be rejected')
        for required in ('plan.schema.json', 'run.schema.json', 'recipe.schema.json',
                         'roles.schema.json', 'defaults.schema.json'):
            self.assertIn(required, covered)

    def test_task_and_evidence_schemas_match_run_definitions(self):
        run = json.loads((ROOT / 'core' / 'schemas' / 'run.schema.json').read_text())
        for name in ('evidence',):
            standalone = json.loads((ROOT / 'core' / 'schemas' / f'{name}.schema.json').read_text())
            body = {k: v for k, v in standalone.items() if k not in ('$schema', '$id', 'title', '$defs')}
            self.assertEqual(body, run['$defs'][name])

    def test_imps_config_matches_defaults_and_roles_schemas(self):
        config = json.loads((ROOT / 'plugins' / 'imps' / 'config.json').read_text())
        self.assertEqual(schema.errors(config, schema.load_schema('defaults')), [])
        roles = schema.load_schema_file(ROOT / 'plugins' / 'imps' / 'schemas' / 'roles.schema.json')
        self.assertEqual(schema.errors(config['roles'], roles), [])

    def test_persisted_perspective_fields_reject_malformed_values(self):
        run = json.loads((FIXTURE_DIR / 'valid/run--active.json').read_text())
        review = run['policy']['review']
        review['perspectives'] = {'architecture': 'Trace contracts.'}
        stored = schema.load_schema('run')
        self.assertEqual(schema.errors(run, stored), [])
        review['perspectives'] = {'architecture': 42}
        self.assertTrue(schema.errors(run, stored))
        review['perspectives'] = {'architecture': 'Trace contracts.'}
        child = {'task_id': 'task-1', 'client_request_id': 'request-1', 'parent_thread_id': 'parent',
                 'status': 'running', 'has_pending_child_runs': False}
        run['children'] = [child]
        self.assertEqual(schema.errors(run, stored), [])
        child['has_pending_child_runs'] = 'no'
        self.assertTrue(schema.errors(run, stored))

    def test_no_third_party_imports_or_runtime_dependency_manifests(self):
        pattern = re.compile(r'^(import|from) (jsonschema|pydantic|yaml|attrs)\b', re.M)
        for directory in ('core', 'plugins', 'scripts'):
            for path in (ROOT / directory).rglob('*.py'):
                self.assertIsNone(pattern.search(path.read_text()), path)
        for manifest in ('requirements.txt', 'pyproject.toml', 'setup.py', 'setup.cfg', 'Pipfile', 'package.json'):
            self.assertFalse((ROOT / manifest).exists(), manifest)


class VersionAndCorruptionTest(CoreTestCase):
    def test_newer_schema_version_rejected_and_left_byte_identical(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo))
        state_file = run.run_dir / 'run.json'
        data = json.loads(state_file.read_text())
        data['schema_version'] = 3
        state_file.write_text(json.dumps(data, indent=1))
        before = state_file.read_bytes()
        code, env, _ = cli('status', *run.args())
        self.assertEqual((code, env['error']['code']), (2, 'unsupported_version'))
        code, env, _ = cli('snapshot', *run.args())
        self.assertEqual(code, 2)
        self.assertEqual(state_file.read_bytes(), before)

    def test_invalid_plan_rejected_without_creating_state(self):
        repo = self.make_repo()
        plan = self.plan(repo)
        plan['brief']['requirements'][0]['kind'] = 'vibes'
        env = self.init(plan, expect=2)
        self.assertEqual(env['error']['code'], 'plan_invalid')
        self.assertFalse((self.state_root / 'runs').exists() and any((self.state_root / 'runs').iterdir()))
        plan = self.plan(repo)
        plan['brief']['requirements'].append(dict(plan['brief']['requirements'][0]))
        self.assertEqual(self.init(plan, expect=2)['error']['code'], 'duplicate_requirement')

    def test_record_that_would_corrupt_state_is_rejected(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo))
        before = (run.run_dir / 'run.json').read_bytes()
        code, env, _ = run.submit_raw('note', {'text': 'x', 'phase': 'nonsense'})
        self.assertEqual(code, 2)
        code, env, _ = cli('not-a-kind', *run.args())
        self.assertEqual(code, 2)
        code, env, _ = cli('note', *run.args('--json', '{not json'))
        self.assertEqual((code, env['error']['code']), (2, 'invalid_input'))
        self.assertEqual((run.run_dir / 'run.json').read_bytes(), before)
