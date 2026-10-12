"""Issue #28 keep/change/remove map: every current surface has exactly one recorded fate.

Fails when an operation, test module, test class, helper or instruction file, schema,
CLI subcommand, manifest field or persisted format is missing from
migration/rebuild/compat-map.json, or when an entry names a file that no longer exists
without a `remove` disposition. Later stages update the map; they do not relax this test. Stages that run in parallel
append to their own shard, compat-map.d/stage-<n>.json, holding "added" entries and
"removed" records ({path, stage, reason}), so they never edit the same file.
"""
import ast
import copy
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / 'migration' / 'rebuild' / 'compat-map.json'
SHARDS = ROOT / 'migration' / 'rebuild' / 'compat-map.d'
ISSUE = ROOT / 'migration' / 'rebuild' / 'issue-28.md'
WORKERS = {'imps/stage-executor', 'imps/investigator', 'imps/auditor', 'imps/reviewer', 'ape/source-researcher',
           'ape/synthesizer', 'elephant-goldfish/factual-checker', 'elephant-goldfish/cold-reader',
           'babysitter/pr-maintainer', 'babysitter/pr-reviewer', 'agent-tuneup/config-researcher',
           'agent-tuneup/config-verifier'}
# Persisted formats named by the issue; a later stage may add more, never drop these.
FORMATS = {'imps-run-state', 'learnings-store', 'install-manifest', 'skill-adapter-marker', 'ape-workspace-marker',
           'thinking-state', 'routing-config'}
COVERED_ROOTS = ('plugins', 'shared', 'core', 'scripts', 'bin', 'packaging')
SKIP_PARTS = {'__pycache__', '.pytest_cache'}
SKIP_SUFFIXES = ('.pyc', '.pyo')
SKIP_NAMES = {'.DS_Store', 'Thumbs.db'}


def test_classes(path: Path) -> set:
    """TestCase classes with test methods, directly or inherited from a class in the same module."""
    nodes = {n.name: n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef)}
    found, changed = set(), True
    while changed:
        changed = False
        for name, node in nodes.items():
            if name in found:
                continue
            direct = any(isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name.startswith('test')
                         for f in node.body)
            inherited = any(isinstance(b, ast.Name) and b.id in found for b in node.bases)
            if direct or inherited:
                found.add(name)
                changed = True
    return found


def subcommands(script: Path) -> set:
    """The first `{a,b,c}` choice list in a CLI's --help: its subcommands."""
    out = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True, cwd=ROOT,
                         timeout=60)
    match = re.search(r'\{([a-z0-9,-]+)\}', out.stdout)
    if out.returncode != 0 or not match:
        raise AssertionError(f'{script} --help did not list subcommands: {out.stderr[-300:]}')
    return set(match.group(1).split(','))


def issue_operations() -> dict:
    if not ISSUE.is_file():
        return {}
    table, inside = {}, False
    for line in ISSUE.read_text().splitlines():
        if line.strip() == '| Plugin | Operations |':
            inside = True
            continue
        if inside and not line.startswith('|'):
            break
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if inside and len(cells) == 2 and not set(cells[0]) <= {'-'}:
            table[cells[0]] = [op.strip() for op in cells[1].split(',')]
    return table


def merged(data: dict, shards: list) -> dict:
    """The main map with each stage shard's additions and removals applied."""
    data = copy.deepcopy(data)
    for shard in shards:
        data.setdefault('added', []).extend(shard.get('added', []))
        for removal in shard.get('removed', []):
            hits = [e for section in ('helpers', 'instructions', 'schemas', 'tests', 'added')
                    for e in data.get(section, []) if e.get('path') == removal.get('path')]
            if not hits:
                data.setdefault('shard_errors', []).append(f'removal of unmapped path {removal.get("path")}')
            for entry in hits:
                entry.update(disposition='remove', stage=removal.get('stage'), reason=removal.get('reason'))
    return data


def load(root: Path = ROOT) -> dict:
    shards = [json.loads(path.read_text()) for path in sorted((root / 'migration/rebuild/compat-map.d').glob('*.json'))]
    return merged(json.loads((root / 'migration/rebuild/compat-map.json').read_text()), shards)


def problems(data: dict, root: Path = ROOT) -> list:
    """Every way the map fails to account for the tree. Empty means complete."""
    errors = list(data.get('shard_errors', []))
    dispositions = set(data.get('dispositions', []))
    if dispositions != {'keep', 'change', 'remove'}:
        errors.append('dispositions must be exactly keep/change/remove')
    known = set(data.get('requirements', [])) | set(data.get('guarantees', {}))

    def entry_ok(where, entry, stages=range(2, 6)):
        if entry.get('disposition') not in dispositions:
            errors.append(f'{where}: bad disposition {entry.get("disposition")!r}')
        if type(entry.get('stage')) is not int or entry['stage'] not in stages:
            errors.append(f'{where}: stage must be one of {list(stages)}')
        if not isinstance(entry.get('reason'), str) or not entry['reason'].strip():
            errors.append(f'{where}: missing reason')

    def path_ok(where, rel, disposition):
        if not isinstance(rel, str) or rel.startswith('/') or '..' in Path(rel).parts:
            errors.append(f'{where}: path must be repository-relative: {rel!r}')
        elif not (root / rel).exists() and disposition != 'remove':
            errors.append(f'{where}: {rel} no longer exists but is not marked remove')

    # Operations: manifests, issue table and map agree.
    manifest_ops = {}
    for manifest in sorted((root / 'plugins').glob('*/plugin.json')):
        meta = json.loads(manifest.read_text())
        manifest_ops[meta['name']] = meta.get('operations', [])
    mapped_ops = {}
    for op in data.get('operations', []):
        where = f'operation {op.get("id")}'
        entry_ok(where, op)
        if op.get('id') != f'{op.get("plugin")}:{op.get("operation")}':
            errors.append(f'{where}: id must be plugin:operation')
        if op.get('id') in mapped_ops:
            errors.append(f'{where}: duplicate')
        mapped_ops[op.get('id')] = op
        for rel in op.get('files', []):
            path_ok(where, rel, op.get('disposition'))
        for worker in op.get('workers', []):
            if worker not in WORKERS:
                errors.append(f'{where}: unknown worker {worker}')
        for item in op.get('guarantees', []):
            if item not in known:
                errors.append(f'{where}: unknown guarantee {item}')
    required_ops = {f'{p}:{o}' for p, ops in manifest_ops.items() for o in ops}
    required_ops |= {f'{p}:{o}' for p, ops in issue_operations().items() for o in ops}
    for missing in sorted(required_ops - set(mapped_ops)):
        errors.append(f'operation {missing} is not mapped')
    for extra in sorted(set(mapped_ops) - required_ops):
        if mapped_ops[extra].get('disposition') != 'remove':
            errors.append(f'operation {extra} no longer exists but is not marked remove')
    used = {w for op in data.get('operations', []) for w in op.get('workers', [])}
    for worker in sorted(WORKERS - used):
        errors.append(f'worker {worker} is not assigned to any operation')

    # Files: helpers, instructions, schemas and added entries account for every shipped/tooling file.
    mapped_paths = {}
    for section in ('helpers', 'instructions', 'schemas'):
        for entry in data.get(section, []):
            where = f'{section} {entry.get("path")}'
            entry_ok(where, entry)
            path_ok(where, entry.get('path'), entry.get('disposition'))
            if entry.get('path') in mapped_paths:
                errors.append(f'{where}: duplicate')
            mapped_paths[entry.get('path')] = entry
    for entry in data.get('added', []):
        where = f'added {entry.get("path")}'
        if type(entry.get('stage')) is not int or not 1 <= entry['stage'] <= 6:
            errors.append(f'{where}: stage must be 1-6')
        if not isinstance(entry.get('reason'), str) or not entry['reason'].strip():
            errors.append(f'{where}: missing reason')
        path_ok(where, entry.get('path'), entry.get('disposition'))
        if entry.get('path') in mapped_paths:
            errors.append(f'{where}: duplicate')
        mapped_paths[entry.get('path')] = entry
        for item in entry.get('coverage', []):
            if item not in known:
                errors.append(f'{where}: unknown coverage {item}')
    for top in COVERED_ROOTS:
        for path in sorted((root / top).rglob('*')):
            rel = path.relative_to(root)
            if (not path.is_file() or SKIP_PARTS & set(rel.parts) or path.name in SKIP_NAMES
                    or path.name.endswith(SKIP_SUFFIXES)):
                continue
            if rel.match('plugins/*/plugin.json'):
                continue  # covered field by field in manifest_fields
            if rel.as_posix() not in mapped_paths:
                errors.append(f'file {rel.as_posix()} is not mapped')
    for schema in [*(root / 'core/schemas').glob('*.json'), *(root / 'plugins').glob('*/schemas/*.json')]:
        rel = schema.relative_to(root).as_posix()
        if rel not in {e.get('path') for e in data.get('schemas', [])} and rel not in {
                e.get('path') for e in data.get('added', [])}:
            errors.append(f'schema {rel} is not in schemas or added')

    # CLI subcommands.
    cli_ids = {}
    for entry in data.get('cli_subcommands', []):
        where = f'cli {entry.get("id")}'
        entry_ok(where, entry)
        path_ok(where, entry.get('path'), entry.get('disposition'))
        cli_ids[entry.get('id')] = entry
    sys.path.insert(0, str(root))
    try:
        from core.cli import OPS
    finally:
        sys.path.remove(str(root))
    required_cli = {f'core:{op}' for op in OPS}
    required_cli |= {f't3-plugins:{name}' for name in subcommands(root / 'scripts' / 'catalog.py')}
    required_cli |= {f'thinking_state:{name}' for name in
                     subcommands(root / 'plugins/elephant-goldfish/scripts/thinking_state.py')}
    for missing in sorted(required_cli - set(cli_ids)):
        errors.append(f'cli subcommand {missing} is not mapped')

    # Manifest fields, including nested origin keys.
    fields = set()
    for manifest in (root / 'plugins').glob('*/plugin.json'):
        for key, value in json.loads(manifest.read_text()).items():
            fields.add(key)
            if isinstance(value, dict):
                fields |= {f'{key}.{sub}' for sub in value}
    mapped_fields = set()
    for entry in data.get('manifest_fields', []):
        entry_ok(f'manifest field {entry.get("id")}', entry)
        if entry.get('id', '').startswith('plugin.json:'):
            mapped_fields.add(entry.get('field'))
    for missing in sorted(fields - mapped_fields):
        errors.append(f'manifest field {missing} is not mapped')

    # Persisted formats.
    format_ids = set()
    for entry in data.get('persisted_formats', []):
        where = f'format {entry.get("id")}'
        entry_ok(where, entry)
        format_ids.add(entry.get('id'))
        for rel in entry.get('paths', []):
            path_ok(where, rel, entry.get('disposition'))
    for missing in sorted(FORMATS - format_ids):
        errors.append(f'persisted format {missing} is not mapped')

    # Tests: every module and class, with surviving coverage.
    mapped_tests = {}
    for entry in data.get('tests', []):
        where = f'test {entry.get("path")}'
        entry_ok(where, entry)
        path_ok(where, entry.get('path'), entry.get('disposition'))
        mapped_tests[entry.get('path')] = entry
        selectors = set()
        for assertion in entry.get('assertions', []):
            selectors.add(assertion.get('selector'))
            if not assertion.get('coverage'):
                errors.append(f'{where}: {assertion.get("selector")} has no coverage')
            for item in assertion.get('coverage', []):
                if item not in known:
                    errors.append(f'{where}: unknown coverage {item}')
        path = root / entry.get('path', '')
        if path.is_file():
            module = path.stem
            for cls in sorted(test_classes(path)):
                if f'{module}.{cls}' not in selectors:
                    errors.append(f'{where}: class {cls} has no assertion mapping')
        elif entry.get('disposition') == 'remove' and not entry.get('assertions'):
            errors.append(f'{where}: removed module must keep its assertion-to-coverage map')
    added_paths = {e.get('path') for e in data.get('added', [])}
    for module in sorted((root / 'tests').glob('test_*.py')):
        rel = module.relative_to(root).as_posix()
        if rel not in mapped_tests and rel not in added_paths:
            errors.append(f'test module {rel} is not mapped')
    return errors


class CompatMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load()

    def test_map_accounts_for_the_current_tree(self):
        self.assertEqual(problems(self.data), [])

    def test_every_requirement_id_in_the_issue_is_known(self):
        if not ISSUE.is_file():
            self.skipTest('issue source not present')
        ids = set(re.findall(r'^\| (REQ-[A-Z]+) \|', ISSUE.read_text(), re.M))
        self.assertGreaterEqual(len(ids), 15)
        self.assertLessEqual(ids, set(self.data['requirements']))

    def test_missing_operation_is_reported(self):
        data = copy.deepcopy(self.data)
        data['operations'] = [op for op in data['operations'] if op['id'] != 'babysitter:org']
        self.assertIn('operation babysitter:org is not mapped', problems(data))

    def test_vanished_file_needs_remove(self):
        data = copy.deepcopy(self.data)
        data['helpers'].append({'path': 'scripts/no_such_helper.py', 'disposition': 'keep', 'stage': 2,
                                'reason': 'synthetic'})
        found = problems(data)
        self.assertIn('helpers scripts/no_such_helper.py: scripts/no_such_helper.py no longer exists but is not '
                      'marked remove', found)
        data['helpers'][-1]['disposition'] = 'remove'
        self.assertEqual(problems(data), [])

    def test_unmapped_test_class_helper_and_schema_are_reported(self):
        data = copy.deepcopy(self.data)
        install = next(t for t in data['tests'] if t['path'] == 'tests/test_install.py')
        install['assertions'] = []
        data['helpers'] = [h for h in data['helpers'] if h['path'] != 'scripts/install.py']
        data['schemas'] = [s for s in data['schemas'] if s['path'] != 'core/schemas/run.schema.json']
        found = problems(data)
        self.assertIn('test tests/test_install.py: class InstallTest has no assertion mapping', found)
        self.assertIn('file scripts/install.py is not mapped', found)
        self.assertIn('schema core/schemas/run.schema.json is not in schemas or added', found)

    def test_bad_disposition_stage_and_coverage_are_reported(self):
        data = copy.deepcopy(self.data)
        data['operations'][0]['disposition'] = 'maybe'
        data['operations'][1]['stage'] = 7
        data['tests'][0]['assertions'][0]['coverage'] = ['REQ-NOPE']
        found = '\n'.join(problems(data))
        self.assertIn("bad disposition 'maybe'", found)
        self.assertIn('stage must be one of', found)
        self.assertIn('unknown coverage REQ-NOPE', found)

    def test_stage_shard_adds_and_removes_without_editing_the_main_map(self):
        shard = {'schema_version': 1, 'stage': 2,
                 'added': [{'path': 'scripts/not_written_yet.py', 'stage': 2, 'reason': 'synthetic'}],
                 'removed': [{'path': 'scripts/run_imps.py', 'stage': 2, 'reason': 'synthetic'}]}
        data = merged(self.data, [shard])
        launcher = next(h for h in data['helpers'] if h['path'] == 'scripts/run_imps.py')
        self.assertEqual(launcher['disposition'], 'remove')
        self.assertIn('added scripts/not_written_yet.py: scripts/not_written_yet.py no longer exists but is not '
                      'marked remove', problems(data))
        bogus = merged(self.data, [{'removed': [{'path': 'scripts/never.py', 'stage': 2, 'reason': 'x'}]}])
        self.assertIn('removal of unmapped path scripts/never.py', problems(bogus))

    def test_removed_module_keeps_its_assertion_map(self):
        data = copy.deepcopy(self.data)
        data['tests'].append({'path': 'tests/test_gone.py', 'disposition': 'remove', 'stage': 3,
                              'reason': 'synthetic', 'assertions': []})
        self.assertIn('test tests/test_gone.py: removed module must keep its assertion-to-coverage map',
                      problems(data))


if __name__ == '__main__':
    unittest.main()
