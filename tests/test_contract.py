"""REQ-PURITY, REQ-T3-SURFACE, REQ-NO-PATHS, REQ-ENTRY and REQ-CLI: static
contracts over the tracked tree plus the CLI envelope and exit codes."""
import json
import re
import subprocess
import sys
from pathlib import Path

from support import CLI, PLUGIN, ROOT, CoreTestCase, cli

FORBIDDEN_CORE_WORDS = ('implementer', 'reviewer', 'researcher', 'bug-fix', 'bugfix', 'playbook')


def tracked(*roots):
    out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', *roots],
                         capture_output=True, text=True, check=True).stdout.split('\n')
    return [ROOT / line for line in out if line and (ROOT / line).is_file()]


def text_files(*roots):
    for path in tracked(*roots):
        try:
            yield path, path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue


class PurityTest(CoreTestCase):
    def test_core_has_no_plugin_imports_or_vocabulary(self):
        files = list(text_files('core'))
        self.assertGreater(len(files), 15)
        for path, text in files:
            self.assertIsNone(re.search(r'^\s*(from|import)\s+plugins\b', text, re.M), path)
            lowered = text.lower()
            for word in FORBIDDEN_CORE_WORDS:
                self.assertNotIn(word, lowered, f'{path.relative_to(ROOT)} contains {word!r}')

    def test_core_imports_only_stdlib_and_itself(self):
        allowed = set(sys.stdlib_module_names) | {'core'}
        for path, text in text_files('core'):
            if path.suffix != '.py':
                continue
            for match in re.finditer(r'^(?:from\s+([A-Za-z_]\w*)[\w.]*\s+import\b|import\s+([A-Za-z_]\w*))', text, re.M):
                module = match.group(1) or match.group(2)
                self.assertIn(module, allowed | {'__future__'}, f'{path.name}: {match.group(0)}')


class SurfaceTest(CoreTestCase):
    def test_no_undocumented_t3_tools(self):
        for path, text in text_files('core', 'plugins', 'scripts'):
            for banned in ('acp-mcp-call', 'preview_status', 'preview_open'):
                self.assertNotIn(banned, text, path)

    def test_link_pull_request_only_as_thread_update_action(self):
        for path, text in text_files('core', 'plugins', 'scripts', 'README.md'):
            for line in text.splitlines():
                if 'link_pull_request' in line:
                    self.assertIn('t3_thread_update', line, f'{path}: {line}')

    def test_top_level_thread_tools_appear_only_as_prohibitions(self):
        for path, text in text_files('plugins'):
            for line in text.splitlines():
                if 'create_threads' in line or 't3_thread_launch' in line:
                    self.assertRegex(line.lower(), r'never|prohibited', f'{path}: {line}')

    def test_no_pr_watcher_tool_instructions(self):
        for path, text in text_files('core', 'plugins', 'scripts'):
            for banned in ('watch_pull_request', 'unwatch_pull_request'):
                self.assertNotIn(banned, text, path)
            for line in text.splitlines():
                if re.search(r'pr[- ]watcher', line, re.I):
                    self.assertRegex(line.lower(), r'no pr-watcher|never|not', f'{path}: {line}')

    def test_adapter_pins_version_doc_and_preview_discovery(self):
        adapter = (PLUGIN / 'references' / 't3-adapter.md').read_text()
        self.assertRegex(adapter, r'0\.0\.46-nightly\.\d{8}\.\d{4}')
        self.assertIn('docs/orchestration-v2/orchestrator-mcp-server.md', adapter)
        self.assertIn('by description', adapter)
        self.assertIn('`unavailable`', adapter.split('## Preview toolkit')[1])


class NoMachinePathsTest(CoreTestCase):
    def test_no_developer_home_paths_in_tracked_files(self):
        pattern = re.compile('/' + 'Users/|/' + 'home/')
        for path, text in text_files():
            if path.relative_to(ROOT).parts[0] in ('thinking', '.git'):
                continue
            self.assertIsNone(pattern.search(text), f'{path.relative_to(ROOT)} contains a machine path')


class EntryTest(CoreTestCase):
    def test_word_budgets(self):
        entry = len((PLUGIN / 'entry.md').read_text().split())
        bugfix = len((PLUGIN / 'playbooks' / 'bug-fix.md').read_text().split())
        self.assertLess(entry, 1500)
        self.assertLessEqual(entry + bugfix, 3000)

    def test_entry_supports_operations_and_names_every_loadable_file(self):
        text = (PLUGIN / 'entry.md').read_text()
        for op in ('doctor', 'run <task>', 'resume <run-id>', 'status <run-id>', 'cancel <run-id>', 'verification-init'):
            self.assertIn(f'**{op}.**', text)
        named = set(re.findall(r'`PKG/([\w./-]+)`', text))
        for name in named:
            self.assertTrue((PLUGIN / name).exists() or (ROOT / name).exists(), name)
        for folder in ('playbooks', 'references'):
            for path in (PLUGIN / folder).glob('*.md'):
                self.assertIn(f'{folder}/{path.name}', named, f'entry.md never names {folder}/{path.name}')
        self.assertNotRegex(text, r'~/\.local/share|/' + 'Users/|/' + 'home/', 'core is located relative to PKG')
        self.assertIn('PKG/core/cli.py', text)


class CliContractTest(CoreTestCase):
    def assertEnvelope(self, env, ok):
        self.assertEqual(env['schema_version'], 1)
        self.assertIs(env['ok'], ok)
        self.assertIn('run_id', env)
        if ok:
            self.assertIn('data', env)
            self.assertNotIn('error', env)
        else:
            self.assertEqual(set(env['error']), {'code', 'message', 'details'})

    def test_every_op_returns_one_envelope_and_each_exit_code_occurs(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo))
        seen = {}
        cases = [
            ('status', [*run.args()], 0),
            ('validate', [*run.args()], 0),
            ('next', [*run.args()], 0),
            ('report', [*run.args()], 0),
            ('claim', [*run.args()], 0),
            ('claim', [*run.args()], 3),
            ('record', [*run.args('--kind', 'nonsense', '--json', '{}', '--token', 'x', '--expect-generation', '1')], 2),
            ('recover', [*run.args('--token', 'x')], 4),
            ('init', ['--state-root', repo / 'wordstat.py', '--plugin-dir', PLUGIN, '--json', json.dumps(self.plan(repo))], 5),
            ('status', ['--state-root', self.state_root, '--plugin-dir', PLUGIN, '--run-id', 'not-an-id'], 2),
        ]
        for op, args, expected in cases:
            result = subprocess.run([sys.executable, str(CLI), op, *map(str, args)], capture_output=True, text=True)
            lines = result.stdout.splitlines()
            self.assertEqual(len(lines), 1, (op, result.stdout))
            env = json.loads(lines[0])
            self.assertEqual(result.returncode, expected, (op, env))
            self.assertEnvelope(env, expected == 0)
            if expected:
                self.assertTrue(result.stderr.strip(), 'diagnostics go to stderr')
            seen.setdefault(expected, op)
        token = run.status()['owner']['token']
        code, env, _ = cli('release', *run.args('--token', token))
        self.assertEnvelope(env, True)
        self.assertEqual(set(seen), {0, 2, 3, 4, 5})

    def test_usage_errors_are_json_too(self):
        result = subprocess.run([sys.executable, str(CLI), 'frobnicate'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'usage')


class MappingTest(CoreTestCase):
    def test_every_mapped_test_id_exists(self):
        import unittest
        text = (ROOT / 'tests' / 'README.md').read_text()
        table = text.split('## Source-spec §14 cases')[1].split('## Rubric')[0]
        cases = {}
        for line in table.splitlines():
            match = re.match(r'^\| (\d+) \|', line)
            if match:
                cases[int(match.group(1))] = re.findall(r'`(test_\w+\.\w+\.test_\w+)`', line)
        self.assertEqual(sorted(cases), list(range(1, 17)))
        loader = unittest.TestLoader()
        for case, ids in cases.items():
            self.assertTrue(ids, f'case {case} has no test')
            for test_id in ids:
                suite = loader.loadTestsFromName(test_id)
                self.assertEqual(suite.countTestCases(), 1, test_id)
