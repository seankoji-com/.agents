"""REQ-PURITY, REQ-T3-SURFACE, REQ-NO-PATHS, REQ-ENTRY and REQ-CLI: static
contracts over the tracked tree plus the CLI envelope and exit codes."""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

from support import source_entry

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
                self.assertFalse(word in lowered, f'{path.relative_to(ROOT)} contains {word!r}')

    def test_core_imports_only_stdlib_and_itself(self):
        allowed = set(sys.stdlib_module_names) | {'core'}
        for path, text in text_files('core'):
            if path.suffix != '.py':
                continue
            for node in ast.walk(ast.parse(text, str(path))):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    modules = [node.module]
                else:
                    continue
                for module in modules:
                    self.assertIn(module.split('.')[0], allowed | {'__future__'}, f'{path.name}:{node.lineno}: {module}')


class SurfaceTest(CoreTestCase):
    def test_no_undocumented_t3_tools(self):
        for path, text in text_files('core', 'plugins', 'scripts', 'skills'):
            for banned in ('acp-mcp-call',):
                self.assertNotIn(banned, text, path)

    def test_pr_linking_uses_discovered_host_tools(self):
        text = (ROOT / 'shared' / 't3-runtime.md').read_text()
        self.assertIn('`link_pull_request`', text)
        self.assertIn('when exposed', text)

    def test_approvals_go_through_the_native_question_picker(self):
        text = (ROOT / 'shared' / 't3-runtime.md').read_text()
        self.assertIn("host's native question picker", text)
        self.assertIn('`AskUserQuestion`', text)
        self.assertIn('Never bury an approval in a prose status', text)
        self.assertIn('silence is not approval', text)
        for entry in sorted([*(ROOT / 'plugins').glob('*/entry.md'), *(ROOT/'skills').glob('*/SKILL.md')]):
            if entry.parent.name == 'unslop':
                continue  # Independently owned single-file prose has no T3 runtime.
            self.assertIn('shared/t3-runtime.md', entry.read_text(), entry.parent.name)

    def test_top_level_thread_tools_appear_only_as_prohibitions(self):
        for path, text in [*text_files('plugins'), *text_files('shared')]:
            if path == ROOT / 'plugins/bug-report/playbooks/report.md':
                # Issue #84 explicitly requests an ordinary reporting conversation.
                # Other plugin/worker uses remain prohibited by the shared contract.
                self.assertIn('`scratch:true`', text)
                self.assertIn('No child delegation', text)
                self.assertNotIn('create_threads', text)
                continue
            for line in text.splitlines():
                if 'create_threads' in line or 't3_thread_launch' in line:
                    self.assertRegex(line.lower(), r'never|prohibited', f'{path}: {line}')

    def test_pr_monitoring_yields_to_host_and_has_handoff_cleanup(self):
        text = (ROOT / 'shared' / 't3-runtime.md').read_text()
        self.assertIn('`watch_pull_request` and yield', text)
        self.assertIn('`unwatch_pull_request`', text)
        self.assertIn('Do not start a polling loop', text)

    def test_adapter_pins_version_doc_and_preview_discovery(self):
        adapter = (PLUGIN / 'references' / 't3-adapter.md').read_text()
        self.assertRegex(adapter, r'0\.0\.46-nightly\.\d{8}\.\d{4}')
        self.assertIn('docs/orchestration-v2/orchestrator-mcp-server.md', adapter)
        self.assertIn('by description', adapter)
        self.assertIn('`unavailable`', adapter.split('## Preview toolkit')[1])


COORDINATORS = ('imps', 'ape', 'elephant-goldfish', 'babysitter', 'agent-tuneup', 'focus-group')
COORDINATION = ROOT / 'shared' / 'job-coordination.md'
# Approval channels that bypass the picker: "reply yes", "type approve", "approve in chat".
PROSE_APPROVAL = re.compile(r'(?i)\b(?:reply|respond|answer|type)\b[^.\n]{0,20}\b(?:yes|approved?|approves)\b'
                            r'|\bapprov\w* (?:in|via|by) (?:chat|prose|a reply)\b')


def cli_surface(script: Path) -> tuple:
    """(subcommand choices, option flags) declared by a CLI's argparse calls, read from its source."""
    choices, flags = set(), set()
    for node in ast.walk(ast.parse(script.read_text(), str(script))):
        if not (isinstance(node, ast.Call) and getattr(node.func, 'attr', None) in ('add_argument', 'add_parser')):
            continue
        names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        flags |= {n for n in names if n.startswith('--')}
        if node.func.attr == 'add_parser':
            choices |= set(names)
        for keyword in node.keywords:
            if keyword.arg == 'choices' and isinstance(keyword.value, (ast.List, ast.Tuple)):
                choices |= {e.value for e in keyword.value.elts if isinstance(e, ast.Constant)}
    return choices, flags


def plugin_instructions(plugin: str):
    base = ROOT / 'plugins' / plugin
    yield source_entry(base)
    for folder in ('playbooks', 'references'):
        yield from sorted((base / folder).glob('**/*.md'))


def installer_module():
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        import install
    finally:
        sys.path.remove(str(ROOT / 'scripts'))
    return install


class ApprovalPickerTest(CoreTestCase):
    """REQ-APPROVAL-PICKER: every coordinator routes owner decisions through the native picker."""

    def test_each_coordinator_entry_routes_owner_decisions_through_the_installed_picker_contract(self):
        install = installer_module()
        runtime = (ROOT / 'shared' / 't3-runtime.md').read_text()
        for phrase in ("host's native question picker", 'recommended option first', 'silence is not approval'):
            self.assertIn(phrase, ' '.join(runtime.split()))
        for plugin in COORDINATORS:
            with self.subTest(plugin=plugin):
                entry = (source_entry(ROOT / 'plugins' / plugin)).read_text()
                self.assertIn('`PKG/shared/t3-runtime.md`', entry)
                # The installed package carries the same contract the entry points at.
                mapping = install.source_files(ROOT, plugin)
                self.assertEqual(mapping['shared/t3-runtime.md'].read_text(), runtime)
                self.assertIn('shared/job-coordination.md', mapping)
                for name in re.findall(r'`PKG/(shared/[\w./-]+)`', entry):
                    self.assertIn(name, mapping, f'{plugin} entry names {name}, absent from its package')
                for path in plugin_instructions(plugin):
                    match = PROSE_APPROVAL.search(path.read_text())
                    self.assertIsNone(match, f'{path.relative_to(ROOT)} asks for approval outside the picker: '
                                             f'{match and match.group(0)!r}')

    def test_each_coordinator_entry_adopts_the_job_coordination_protocol(self):
        for plugin in COORDINATORS:
            with self.subTest(plugin=plugin):
                entry = (source_entry(ROOT / 'plugins' / plugin)).read_text()
                self.assertIn('`PKG/shared/job-coordination.md`', entry)
                self.assertIn('`PKG/shared/t3-runtime.md`', entry)

    def test_protocol_sends_every_owner_decision_to_the_picker_and_records_it(self):
        text = COORDINATION.read_text()
        section = ' '.join(text.split('## 9. Approvals and owner decisions')[1].split())
        self.assertIn('native question picker', section)
        self.assertIn('`PKG/shared/t3-runtime.md`', section)
        self.assertIn('recommended option first', section)
        self.assertIn('Silence is not approval', section)
        self.assertIsNone(PROSE_APPROVAL.search(text))

    def test_documented_approval_wait_blocks_acceptance_until_resolved_and_decision_is_source_bound(self):
        from core.jobs import decision, record_dispatch
        from core.jobs.store import JobError, Store, digest
        from shared.job_acceptance import _pending
        job = {'schema_version': 1, 'job_id': 'job-1', 'installation_id': 'install-1', 'workflow': 'imps/run',
               'owner': 'coordinator', 'objective': 'x', 'requirements': {'R1': 'keep evidence'},
               'authorization': {'actions': ['edit']}, 'constraints': ['no network'],
               'dependencies': [{'key': 'imps', 'plugin': 'imps'}], 'pins': {'imps': {'package_digest': 'c' * 64}},
               'result_contract': {'schema_version': 1}, 'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
               'stages': [{'id': 's0', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                           'attempts': {'primary': 0, 'support': 0, 'review': 0, 'final': 0}, 'acceptance': None}],
               'tasks': [{'task_id': 't0', 'stage_id': 's0', 'logical_slot_id': 'primary', 'request_id': 'req0',
                          'worker_id': 'imps/stage-executor', 'dependency_key': 'imps', 'status': 'pending', 'attempt': 0,
                          'handles': [], 'followups': [], 'dispatch_retries': 0, 'dispatch_history': []}],
               'decisions': [], 'history': [], 'metrics': {}}
        store = Store(self.state_root, 'job-1')
        store.create(job)
        caller = {'actor': 'coordinator', 'installation_id': 'install-1', 'workflow': 'imps/run', 'package_digest': 'c' * 64}
        stage = lambda: store.load()['stages'][0]
        self.assertFalse(_pending(store.load(), stage()))
        record_dispatch(store, caller, 't0', {'kind': 'approval-wait', 'request_id': 'req0', 'wait_id': 'w1'})
        self.assertTrue(_pending(store.load(), stage()), 'an open picker question must block acceptance')
        self.assertEqual([w['wait_id'] for w in store.overview(persist=False)['approval_waits']], ['w1'],
                         'the overview checklist must show the open picker question')
        # The picker answer is saved outside the job directory and bound by quote and hash.
        source = self.tmp / 'owner-answer.txt'
        source.write_text('Approve plan revision rev-1\n')
        record = {'id': 'owner-1', 'quote': 'Approve plan revision rev-1', 'source': str(source),
                  'source_sha256': digest(source.read_bytes()), 'scope': 'plan:rev-1'}
        with self.assertRaises(JobError):
            decision(store, caller, dict(record, quote='Approve everything'))
        inside = store.path / 'answer.txt'
        inside.write_bytes(source.read_bytes())
        with self.assertRaises(JobError):
            decision(store, caller, dict(record, source=str(inside)))
        decision(store, caller, record)
        record_dispatch(store, caller, 't0', {'kind': 'approval-resolved', 'request_id': 'req0', 'wait_id': 'w1'})
        state = store.load()
        self.assertEqual([d['id'] for d in state['decisions']], ['owner-1'])
        self.assertFalse(_pending(state, stage()))
        self.assertEqual(store.overview(state, persist=False)['approval_waits'], [])


class JobCoordinationTest(CoreTestCase):
    """shared/job-coordination.md names only real helper commands and keeps cheap operations direct."""
    JOB_CLI = ROOT / 'shared' / 'job_cli.py'
    ACCEPT_CLI = ROOT / 'shared' / 'job_acceptance_cli.py'

    def documented(self):
        text = COORDINATION.read_text()
        named = re.findall(r'\b(job_cli|job_acceptance_cli)\.py"?\s+`?([a-z][a-z-]*)', text)
        return text, named

    def test_protocol_names_only_real_subcommands_and_flags(self):
        text, named = self.documented()
        job_choices, job_flags = cli_surface(self.JOB_CLI)
        accept_choices, accept_flags = cli_surface(self.ACCEPT_CLI)
        _, catalog_flags = cli_surface(ROOT / 'scripts' / 'catalog.py')
        catalog_help = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'catalog.py'), '--help'],
                                      capture_output=True, text=True, check=True, timeout=60).stdout
        catalog_choices = set(re.search(r'\{([a-z,-]+)\}', catalog_help).group(1).split(','))
        self.assertIn('task-observation', job_choices)
        self.assertEqual(accept_choices, {'accept-stage', 'validate', 'validate-final'})
        choices = {'job_cli': job_choices, 'job_acceptance_cli': accept_choices}
        self.assertGreaterEqual(len(named), 12)
        for helper, command in named:
            self.assertIn(command, choices[helper], f'{helper}.py {command} is not a real subcommand')
        # Every job_cli subcommand is covered, so the protocol cannot silently drop one.
        tokens = set(re.findall(r'`([a-z][a-z-]*)`', text)) | {c for h, c in named if h == 'job_cli'}
        self.assertEqual(job_choices - tokens, set())
        for command in re.findall(r'`agents (?:--job \S+ )?([a-z]+)', text):
            self.assertIn(command, catalog_choices)
        for flag in set(re.findall(r'(?<![\w-])--[a-z][a-z-]*', text)):
            self.assertIn(flag, job_flags | accept_flags | catalog_flags, f'{flag} is not a real helper option')
        self.assertLess(len(text.split()), 1500)

    def test_documented_subcommands_reach_the_helpers_instead_of_failing_argparse(self):
        import contextlib
        import io
        from shared import job_acceptance_cli, job_cli
        _, named = self.documented()
        missing = self.tmp / 'missing-input.json'
        for helper, command in sorted(set(named)):
            module = job_cli if helper == 'job_cli' else job_acceptance_cli
            argv = [command, '--state-root', str(self.state_root), '--job', 'probe-job', '--input', str(missing)]
            if command == 'create':
                argv += ['--prefix', str(self.tmp / 'prefix'), '--agents-root', str(self.tmp / 'agents')]
            with self.subTest(helper=helper, command=command), contextlib.redirect_stderr(io.StringIO()) as err, \
                    contextlib.redirect_stdout(io.StringIO()):
                try:
                    code = module.main(argv)
                except SystemExit as exc:  # argparse rejected the documented command line
                    self.fail(f'{helper}.py {command}: usage error {exc.code}: {err.getvalue()[-200:]}')
                self.assertEqual(code, 2, 'a job that does not exist is refused as invalid state, not accepted')
            self.assertFalse((self.state_root / 'probe-job' / 'job.json').exists())

    def test_cheap_operations_stay_direct_and_status_reads_without_mutating(self):
        text = COORDINATION.read_text()
        cheap = text.split('## 1. Cheap operations stay direct')[1].split('##')[0]
        for word in ('`doctor`', '`status`', 'directly', 'Never create a job or launch a worker'):
            self.assertIn(word, cheap)
        for plugin in COORDINATORS:
            for line in (source_entry(ROOT / 'plugins' / plugin)).read_text().splitlines():
                if re.search(r'\*\*doctor\b|`doctor`|^- doctor\b', line):
                    self.assertNotRegex(line, r'delegate_task|job_cli\.py|dispatch', f'{plugin}: {line}')
        # job_cli status/overview render through Store.overview(persist=False): no state write.
        from core.jobs.store import Store
        store = Store(self.state_root, 'job-1')
        store.create({'schema_version': 1, 'job_id': 'job-1', 'installation_id': 'i', 'workflow': 'ape/forage',
                      'owner': 'coordinator', 'objective': 'x', 'requirements': {'R1': 'x'},
                      'authorization': {'actions': []}, 'constraints': [], 'dependencies': [{'key': 'ape', 'plugin': 'ape'}],
                      'pins': {'ape': {'package_digest': 'c' * 64}}, 'result_contract': {'schema_version': 1},
                      'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
                      'stages': [{'id': 's0', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                                  'attempts': {'primary': 0, 'support': 0, 'review': 0, 'final': 0}, 'acceptance': None}],
                      'tasks': [], 'decisions': [], 'history': [], 'metrics': {}})
        before = store.file.read_bytes()
        view = store.overview(persist=False)
        self.assertEqual(view['current_stage'], 's0')
        self.assertEqual(store.file.read_bytes(), before)

    def test_installed_package_ships_the_protocol_beside_the_runtime_contract(self):
        home = self.tmp / 'home'
        home.mkdir()
        env = {k: v for k, v in __import__('os').environ.items() if not k.startswith(('AGENTS_', 'XDG_'))}
        env['HOME'] = str(home)
        cli = [sys.executable, str(ROOT / 'scripts' / 'catalog.py'), '--prefix', str(self.tmp / 'prefix'),
               '--agents-root', str(self.tmp / 'agents')]
        subprocess.run(cli + ['install', 'babysitter'], check=True, capture_output=True, env=env, timeout=120)
        entry = Path(subprocess.run(cli + ['path', 'babysitter'], check=True, capture_output=True, text=True, env=env,
                                    timeout=60).stdout.strip())
        package = entry.parent
        self.assertTrue(package.is_relative_to(self.tmp))
        installed = package / 'shared' / 'job-coordination.md'
        self.assertEqual(installed.read_bytes(), COORDINATION.read_bytes())
        self.assertIn('`PKG/shared/job-coordination.md`', (package / 'shared' / 't3-runtime.md').read_text())
        self.assertIn('`PKG/shared/job-coordination.md`', (package / 'shared' / 'delegation.md').read_text())
        for name in re.findall(r'`PKG/(shared/[\w./-]+)`', installed.read_text()):
            self.assertTrue((package / name).is_file(), f'protocol names {name}, absent from the installed package')
        for helper in ('job_cli.py', 'job_acceptance_cli.py'):
            self.assertTrue((package / 'shared' / helper).is_file())
        self.assertFalse(any(home.rglob('*')), 'install wrote into HOME despite explicit roots')


class NoMachinePathsTest(CoreTestCase):
    def test_no_developer_home_paths_in_tracked_files(self):
        # Per-user temporary directories too: a sandbox's /tmp/<tool>-<uid> or macOS /var/folders.
        pattern = re.compile('/' + 'Users/|/' + 'home/|/tmp/[A-Za-z0-9._-]+-[0-9]+/|/var/' + 'folders/')
        for path, text in text_files():
            # The archived imps-t3 brief quotes this very grep pattern in its rubric.
            rel = path.relative_to(ROOT)
            if rel.parts[0] == '.git' or rel.parts[:3] == ('docs', 'design', 'imps-t3'):
                continue
            self.assertIsNone(pattern.search(text), f'{path.relative_to(ROOT)} contains a machine path')


class EntryTest(CoreTestCase):
    def test_word_budgets(self):
        entry = len((source_entry(PLUGIN)).read_text().split())
        bugfix = len((PLUGIN / 'playbooks' / 'bug-fix.md').read_text().split())
        self.assertLessEqual(entry, 800)
        self.assertLessEqual(entry + bugfix, 3000)

    def test_entry_supports_operations_and_names_every_loadable_file(self):
        text = (source_entry(PLUGIN)).read_text()
        for op in ('doctor', 'run <task>', 'resume <run-id>', 'status <run-id>', 'cancel <run-id>', 'verification-init'):
            self.assertIn(f'**{op}.**', text)
        named = set(re.findall(r'`PKG/([\w./-]+)`', text))
        for name in named:
            self.assertTrue((PLUGIN / name).exists() or (ROOT / name).exists(), name)
        for folder in ('playbooks', 'references'):
            for path in (PLUGIN / folder).glob('*.md'):
                self.assertIn(f'{folder}/{path.name}', named, f'entry.md never names {folder}/{path.name}')
        self.assertNotRegex(text, r'~/\.local/share|/' + 'Users/|/' + 'home/', 'core is located relative to PKG')
        self.assertIn('PKG/cli.py', text)


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
            ('snapshot', [*run.args()], 0),
            ('report', [*run.args()], 0),
            ('note', [*run.args('--json', '{"text":"ok"}')], 0),
            ('note', [*run.args('--json', '{"text":"x","ready":true}')], 2),
            ('waive', [*run.args('--json', '{"target":"review","reason":"x","decided_by":"owner","operator_quote":"skip"}')], 0),
            ('policy', [*run.args('--json', '{"policy":{"checks":[]}}')], 4),
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
        import contextlib
        import io
        from unittest import mock
        from core import cli as module, store
        output = io.StringIO()
        with mock.patch.object(store, 'new_run_id', return_value=run.run_id), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = module.main(['init', '--state-root', str(self.state_root), '--plugin-dir', str(PLUGIN),
                                '--json', json.dumps(self.plan(repo))])
        self.assertEqual(code, 3)
        self.assertEnvelope(json.loads(output.getvalue()), False)
        self.assertEqual(set(seen), {0, 2, 4, 5})

    def test_usage_errors_are_json_too(self):
        result = subprocess.run([sys.executable, str(CLI), 'frobnicate'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'usage')


class MappingTest(CoreTestCase):
    def test_every_mapped_test_id_exists(self):
        import unittest
        text = (ROOT / 'tests' / 'README.md').read_text()
        table = text.split('## Current evidence gate')[1]
        ids = re.findall(r'`(test_\w+\.\w+\.test_\w+)`', table)
        self.assertGreaterEqual(len(ids), 7)
        loader = unittest.TestLoader()
        for test_id in ids:
            suite = loader.loadTestsFromName(test_id)
            self.assertEqual(suite.countTestCases(), 1, test_id)
            self.assertEqual(loader.errors, [], test_id)

    def test_operations_and_removed_instruction_api(self):
        meta = json.loads((PLUGIN/'plugin.json').read_text())
        self.assertEqual(meta['operations'], ['doctor','run','resume','status','cancel','verification-init',
                                              'blast-radius','audit','issues','prs','checklist','discussion'])
        for path, text in text_files('plugins'):
            for banned in ('--expect-generation', 'claim --', 'record --kind'):
                self.assertNotIn(banned, text, path)
            self.assertNotRegex(text, r'(?i)(?:next[^\n]{0,35}loop|loop[^\n]{0,35}`next`)', path)

    def test_core_size_remains_within_stage_three_budget(self):
        count = sum(len(path.read_text().splitlines()) for path in (ROOT/'core').rglob('*.py'))
        # 2156 is the issue-28 budget; master's #34 later added 26 lines to core/snapshot.py.
        self.assertLessEqual(count, 2156 + 26)
        self.assertFalse((ROOT/'core/engine.py').exists())
