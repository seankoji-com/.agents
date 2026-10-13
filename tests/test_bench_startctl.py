"""Offline tests for the Stage 6 quality-start runner (no Docker, network or model calls)."""
import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = ROOT / 'bench' / 'container'
V2 = ROOT / 'bench' / 'v2'
sys.path.insert(0, str(V2 / 'tools'))
sys.path.insert(0, str(V2 / 'checks'))
sys.path.insert(0, str(CONTAINER))
import attempt_record  # noqa: E402
import benchctl  # noqa: E402
import driver  # noqa: E402
import host_observations  # noqa: E402
import negative_start  # noqa: E402
import observations_to_context as o2c  # noqa: E402
import packages  # noqa: E402
import startctl  # noqa: E402
import workflow_contract  # noqa: E402

LUNA = {'providerInstanceId': 'codex', 'model': 'gpt-0-luna',
        'options': {'reasoningEffort': 'low', 'serviceTier': 'default'}}
HAIKU = {'providerInstanceId': 'claudeAgent', 'model': 'claude-haiku-0', 'options': {'thinking': False}}
CATALOG = {'providers': [
    {'providerInstanceId': 'codex', 'canRunChildTask': True, 'models': [{'id': 'gpt-0-luna', 'options': [
        {'id': 'reasoningEffort', 'options': [{'id': 'low'}]}, {'id': 'serviceTier', 'options': [{'id': 'default'}]}]}]},
    {'providerInstanceId': 'claudeAgent', 'canRunChildTask': True, 'models': [{'id': 'claude-haiku-0', 'options': [
        {'id': 'thinking', 'type': 'boolean'}]}]}]}
FROZEN = {'codex': LUNA, 'claudeAgent': HAIKU}


def writable(root):
    """Restore write bits so a temporary directory holding a read-only arm can be removed."""
    for path in [Path(root), *Path(root).rglob('*')]:
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o700)


def fake_arm(out, arm='baseline'):
    """A minimal read-only package arm with a valid identity."""
    prefix = out / 'prefix'
    plugins = {}
    for plugin in startctl.PLUGIN_OF.values():
        name = plugin[0]
        if name in plugins:
            continue
        version_dir = prefix / name / '1.0.0'
        version_dir.mkdir(parents=True)
        (version_dir / 'entry.md').write_text(f'# {name}\n', encoding='utf-8')
        manifest = {'version': '1.0.0', 'files': [{'path': 'entry.md'}]}
        raw = json.dumps(manifest).encode()
        (version_dir / 'install-manifest.json').write_bytes(raw)
        plugins[name] = {'version': '1.0.0', 'version_dir': str(version_dir), 'entry': str(version_dir / 'entry.md'),
                         'install_manifest_sha256': hashlib.sha256(raw).hexdigest()}
    identity = {'schema_version': 1, 'arm': arm, 'prefix': str(prefix), 'agents_root': None, 'plugins': plugins,
                'package_digests': {p: r['install_manifest_sha256'] for p, r in plugins.items()},
                'bundle_digests': {'baseline-identity-no-agent-bundles': 'b' * 64},
                'prefix_tree_sha256': packages.tree_digest(prefix)}
    packages.make_read_only(prefix)
    (out / packages.IDENTITY).write_text(json.dumps(identity), encoding='utf-8')
    return identity


class PackageArmTest(unittest.TestCase):
    def git_clean(self):
        result = subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--', *packages.CLEAN_PATHS],
                                capture_output=True, text=True)
        return result.returncode == 0 and not result.stdout.strip()

    @unittest.skipUnless(subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e',
                                         json.loads(packages.BASELINE.read_text())['base_commit'] + '^{commit}'],
                                        capture_output=True).returncode == 0, 'baseline commit not in this clone')
    def test_baseline_arm_reproduces_recorded_identity_and_detects_tampering(self):
        baseline = json.loads(packages.BASELINE.read_text())
        with tempfile.TemporaryDirectory() as temp:
            try:
                identity = packages.build_arm('baseline', Path(temp) / 'baseline')
                for row in baseline['plugins']:
                    record = identity['plugins'][row['name']]
                    self.assertEqual(record['version'], row['installed_version'])
                    self.assertEqual(record['install_manifest_sha256'], row['install_manifest_sha256'])
                    self.assertEqual(record['package_content_sha256'], row['package_content_sha256'])
                    self.assertNotIn('/current/', record['entry'])  # version directories only
                    self.assertTrue(Path(record['entry']).is_file())
                path = Path(temp) / 'baseline' / packages.IDENTITY
                self.assertTrue(packages.verify_identity(path)['verified'])
                entry = Path(identity['plugins']['imps']['entry'])
                entry.chmod(0o644)
                entry.write_text(entry.read_text() + 'tampered\n')
                result = packages.verify_identity(path)
                self.assertFalse(result['verified'])
                self.assertIn('prefix tree changed', result['problems'])
                self.assertIn('package tree is writable', result['problems'])
                with self.assertRaisesRegex(packages.PackageError, 'already exists'):
                    packages.build_arm('baseline', Path(temp) / 'baseline')
            finally:
                writable(temp)

    def test_rebuilt_arm_installs_bundles_and_mounts_at_its_own_path(self):
        if not self.git_clean():
            self.skipTest('rebuilt source paths have uncommitted changes')
        with tempfile.TemporaryDirectory() as temp:
            try:
                identity = packages.build_arm('rebuilt', Path(temp) / 'rebuilt')
                self.assertEqual(set(identity['package_digests']), {r['name'] for r in json.loads(packages.BASELINE.read_text())['plugins']})
                self.assertTrue(identity['bundle_digests'])
                view = packages.container_view(identity)
                out = str(Path(temp) / 'rebuilt')
                self.assertEqual(view['mounts'], [(out, out, False)])
                self.assertEqual(view['env']['T3_PLUGINS_AGENTS_ROOT'], identity['agents_root'])
                self.assertTrue(packages.verify_identity(Path(out) / packages.IDENTITY)['verified'])
            finally:
                writable(temp)

    def test_output_path_and_arm_are_checked_before_any_install(self):
        calls = []
        for bad in (Path('relative/out'), Path('/tmp/has:colon'), Path('/tmp/has,comma')):
            with self.subTest(path=str(bad)), self.assertRaises(packages.PackageError):
                packages.build_arm('baseline', bad, run=lambda *a, **k: calls.append(a))
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(packages.PackageError):
            packages.build_arm('other', Path(temp) / 'x', run=lambda *a, **k: calls.append(a))
        self.assertEqual(calls, [])

    def test_dirty_rebuilt_source_is_refused(self):
        def run(argv, **_kwargs):
            out = ' M plugins/imps/entry.md\n' if 'status' in argv else 'abc\n'
            return SimpleNamespace(returncode=0, stdout=out, stderr='')
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(packages.PackageError, 'uncommitted'):
            packages.build_arm('rebuilt', Path(temp) / 'r', run=run)

    def test_installer_runs_with_isolated_home_and_no_owner_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'arm'
            with patch.dict(os.environ, {'T3_PLUGINS_PREFIX': '/owner/prefix', 'HOME': '/owner'}):
                env = packages._isolated_env(out)
            self.assertNotIn('T3_PLUGINS_PREFIX', env)
            self.assertTrue(env['HOME'].startswith(str(out)))
            self.assertTrue(env['XDG_STATE_HOME'].startswith(str(out)))


class FakeClient:
    def __init__(self, statuses=(), clock=None):
        self.statuses = list(statuses)
        self.calls = []
        self.clock = clock

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        if name == 't3_thread_read':
            return {'structuredContent': settled_read()}
        if self.clock is not None:
            self.clock.now += arguments.get('timeoutMs', 0) / 1000
        status = self.statuses.pop(0) if self.statuses else 'completed'
        return {'structuredContent': {'status': status}}


def settled_read(runs=((1, 'completed'),), pending=0, items=(), active_run=None):
    """Live T3 thread-read shape: the thread row, recentRuns (newest first) and run-tagged items."""
    rows = [{'runId': f'run:{ordinal}', 'ordinal': ordinal, 'status': status,
             'providerInstanceId': 'codex', 'model': 'gpt-0-luna'}
            for ordinal, status in sorted(runs, reverse=True)]
    latest = rows[0]
    thread_status = latest['status'] if latest['status'] in driver.ACTIVE_THREAD_STATUSES else 'idle'
    return {'thread': {'threadId': 't1', 'status': thread_status, 'latestRunId': latest['runId'],
                       'activeRunId': active_run, 'runCount': latest['ordinal'],
                       'pendingRequestCount': pending, 'providerInstanceId': 'codex',
                       'model': 'gpt-0-luna', 'settled': False},
            'recentRuns': rows, 'items': list(items), 'nextPosition': len(items), 'hasMore': False}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


TOOLS = [{'name': 't3_thread_wait', 'inputSchema': {'type': 'object', 'properties': {
             'threadId': {'type': 'string'}, 'timeoutMs': {'type': 'integer'}}, 'required': ['threadId']}},
         {'name': 't3_thread_interrupt', 'inputSchema': {'type': 'object', 'properties': {
             'threadId': {'type': 'string'}}, 'required': ['threadId']}},
         {'name': 't3_thread_send', 'inputSchema': {'type': 'object', 'properties': {
             'threadId': {'type': 'string'}, 'message': {'type': 'string'},
             'modelSelection': {'type': 'object', 'properties': {'instanceId': {}, 'model': {}, 'options': {}}}},
             'required': ['threadId', 'message']}},
         {'name': 't3_thread_read', 'inputSchema': {'type': 'object', 'properties': {
             'threadId': {'type': 'string'}, 'view': {'type': 'string', 'enum': ['messages', 'activity']},
             'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
             'maxCharsPerItem': {'type': 'integer', 'minimum': 1, 'maximum': 50000},
             'runLimit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
             'afterPosition': {'type': 'integer', 'minimum': 0}, 'itemId': {'type': 'string'},
             'textOffset': {'type': 'integer', 'minimum': 0}},
             'required': ['threadId'], 'additionalProperties': False}}]


class DriverResumeTest(unittest.TestCase):
    def test_wait_is_bounded_by_the_deadline_and_stops_on_terminal_status(self):
        clock = Clock()
        client = FakeClient(['running'] * 10, clock)
        result, late = driver.wait_for_thread(client, TOOLS, 't1', 2000, clock=clock, sleep=lambda _s: None)
        self.assertTrue(late)
        self.assertEqual([c[1]['timeoutMs'] for c in client.calls], [900000, 900000, 200000])
        clock = Clock()
        client = FakeClient(['running', 'completed'], clock)
        result, late = driver.wait_for_thread(client, TOOLS, 't1', 9000, clock=clock, sleep=lambda _s: None)
        self.assertFalse(late)
        self.assertEqual(result['status'], 'completed')
        with self.assertRaises(RuntimeError):
            driver.wait_for_thread(client, TOOLS, 't1', 0)

    def test_interrupt_sends_only_the_thread_id(self):
        client = FakeClient()
        driver.interrupt_thread(client, TOOLS, 'thread-1')
        self.assertEqual(client.calls, [('t3_thread_interrupt', {'threadId': 'thread-1'})])

    def test_resume_keeps_the_frozen_target_and_validates_role_resume(self):
        client = FakeClient()
        driver.resume_thread(client, TOOLS, CATALOG, FROZEN, 'codex', 'thread-1', 'resume')
        name, arguments = client.calls[0]
        self.assertEqual(name, 't3_thread_send')
        self.assertEqual(arguments['message'], 'resume')
        self.assertEqual(arguments['modelSelection']['model'], 'gpt-0-luna')
        self.assertEqual(arguments['modelSelection']['options'], LUNA['options'])
        premium = copy.deepcopy(FROZEN)
        premium['codex'] = dict(LUNA, model='gpt-0-sol')
        client = FakeClient()
        with self.assertRaises(ValueError):
            driver.resume_thread(client, TOOLS, CATALOG, premium, 'codex', 'thread-1', 'resume')
        self.assertEqual(client.calls, [])  # a forbidden target sends nothing

    def test_resume_blocks_when_the_live_schema_needs_an_unknown_field(self):
        tools = copy.deepcopy(TOOLS)
        tools[2]['inputSchema']['required'].append('turnPolicy')
        tools[2]['inputSchema']['properties']['turnPolicy'] = {'type': 'string'}
        client = FakeClient()
        with self.assertRaisesRegex(RuntimeError, 'unsupported required'):
            driver.resume_thread(client, tools, CATALOG, FROZEN, 'codex', 'thread-1', 'resume')
        self.assertEqual(client.calls, [])


def message(position, kind, run, text):
    return {'position': position, 'itemId': f'item-{position}', 'runId': f'run:{run}',
            'type': kind, 'status': 'completed', 'text': text, 'textTruncated': False}


PROMPT = 'canary prompt'
INTERIM = '{"interim": "parent progress note"}'
FINAL = '{"final": "report from run 2"}'
QUEUED = {'wait': {'status': 'completed', 'runId': 'run:1'},
          'read': settled_read(((1, 'completed'), (2, 'queued')), items=[
              message(0, 'user_message', 1, PROMPT), message(1, 'assistant_message', 1, INTERIM)])}
RUNNING = {'wait': {'status': 'running', 'runId': 'run:2'},
           'read': settled_read(((1, 'completed'), (2, 'running')), active_run='run:2', items=QUEUED['read']['items'])}
DONE = {'wait': {'status': 'completed', 'runId': 'run:2'},
        'read': settled_read(((1, 'completed'), (2, 'completed')), items=QUEUED['read']['items'] + [
            message(2, 'assistant_message', 2, FINAL)])}


class SettlingThread:
    """Fake MCP thread: each wait advances one scripted state; reads return the current one.

    Mirrors the live defect: t3_thread_wait reported run 1 completed while T3 had
    already queued run 2 on the same thread.
    """

    def __init__(self, states, clock):
        self.states = list(states)
        self.index = -1
        self.clock = clock
        self.calls = []

    def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name == 't3_thread_wait':
            self.index = min(self.index + 1, len(self.states) - 1)
            result = dict(self.states[self.index]['wait'])
            # A wait on a terminal run returns at once; an active one returns when the
            # next scripted state arrives (30 s later) or at the end of its slice.
            self.clock.now += (min(30, arguments['timeoutMs'] / 1000)
                               if result['status'] in driver.ACTIVE_THREAD_STATUSES else 1)
            return {'structuredContent': result}
        state = self.states[max(self.index, 0)]
        return {'structuredContent': copy.deepcopy(state['read'])}


class ThreadSettlementTest(unittest.TestCase):
    def wait_and_read(self, states, deadline=600):
        clock = Clock()
        client = SettlingThread(states, clock)

        def sleep(seconds):
            clock.now += seconds
        with tempfile.TemporaryDirectory() as temp:
            report = driver.wait_and_read(client, TOOLS, 't1', deadline, PROMPT, Path(temp),
                                          clock=clock, sleep=sleep)
        return report, client

    def test_completed_run_with_a_queued_run_is_not_settled(self):
        settled, run_id, reasons = driver.thread_settlement(QUEUED['wait'], QUEUED['read'])
        self.assertFalse(settled)
        self.assertIsNone(run_id)
        self.assertIn('run 2 is queued', reasons)
        clock = Clock()
        result, late = driver.wait_for_thread(SettlingThread([QUEUED], clock), TOOLS, 't1', 30,
                                              clock=clock, sleep=lambda s: setattr(clock, 'now', clock.now + s))
        self.assertTrue(late)
        self.assertEqual(result['status'], 'not settled')
        self.assertIs(result['settled'], False)

    def test_settles_when_run_two_completes_and_reads_the_report_from_run_two(self):
        report, client = self.wait_and_read([QUEUED, RUNNING, DONE])
        self.assertIs(report['settled'], True)
        self.assertEqual(report['status'], 'completed')
        self.assertFalse(report['timed_out'])
        self.assertEqual(report['latest_run_id'], 'run:2')
        self.assertEqual(report['canary_result'], {'final': 'report from run 2'})
        self.assertIs(report['final_message_retrieval_exact'], True)
        self.assertTrue(report['original_message_exact'])
        self.assertEqual([c[0] for c in client.calls].count('t3_thread_wait'), 3)
        snapshots = [c[1] for c in client.calls if c[0] == 't3_thread_read' and c[1].get('limit') == 1]
        self.assertTrue(snapshots and all(c['runLimit'] == 50 for c in snapshots))

    def test_run_scoped_final_text_ignores_the_interim_message(self):
        self.assertEqual(driver.final_assistant_text(DONE['read'], 'run:2'), FINAL)
        self.assertIsNone(driver.final_assistant_text(QUEUED['read'], 'run:2'))
        self.assertEqual(driver.final_assistant_text(QUEUED['read'], 'run:1'), INTERIM)

    def test_pending_child_runs_or_requests_are_not_settled(self):
        children = {'wait': dict(DONE['wait'], hasPendingChildRuns=True), 'read': DONE['read']}
        settled, _run, reasons = driver.thread_settlement(children['wait'], children['read'])
        self.assertFalse(settled)
        self.assertIn('child runs are pending', reasons)
        waiting = {'wait': dict(DONE['wait'], workState='waiting_for_children'), 'read': DONE['read']}
        self.assertFalse(driver.thread_settlement(waiting['wait'], waiting['read'])[0])
        requests = {'wait': DONE['wait'], 'read': copy.deepcopy(DONE['read'])}
        requests['read']['thread']['pendingRequestCount'] = 1
        self.assertFalse(driver.thread_settlement(requests['wait'], requests['read'])[0])
        pointer = copy.deepcopy(DONE['read'])
        pointer['thread']['activeRunId'] = 'run:2'  # names a listed terminal run
        self.assertTrue(driver.thread_settlement(DONE['wait'], pointer)[0])
        pointer['thread']['activeRunId'] = 'run:3'  # names a run the read does not list
        self.assertFalse(driver.thread_settlement(DONE['wait'], pointer)[0])
        missing = copy.deepcopy(DONE['read'])
        del missing['recentRuns']
        self.assertFalse(driver.thread_settlement(DONE['wait'], missing)[0])
        report, _client = self.wait_and_read([children], deadline=60)
        self.assertIs(report['settled'], False)
        self.assertEqual(report['status'], 'not settled')
        self.assertIsNone(report['canary_result'])

    def test_deadline_while_queued_reports_not_settled_without_reading_interim_output(self):
        report, client = self.wait_and_read([QUEUED], deadline=60)
        self.assertIs(report['settled'], False)
        self.assertTrue(report['timed_out'])
        self.assertEqual(report['status'], 'not settled')
        self.assertNotEqual(report['status'], 'completed')
        self.assertIsNone(report['canary_result'])
        self.assertIsNone(report['final_message_utf8_bytes'])
        self.assertIs(report['final_message_retrieval_exact'], False)
        self.assertIn('run 2 is queued', report['unsettled_reasons'])
        # The poll is bounded: an idle-returning wait does not spin once per second.
        self.assertLessEqual([c[0] for c in client.calls].count('t3_thread_wait'), 7)

    def test_a_run_queued_after_settlement_makes_the_read_interim(self):
        class LateQueue(SettlingThread):
            def call(self, name, arguments):
                if name == 't3_thread_read' and arguments.get('limit') != 1:
                    return {'structuredContent': copy.deepcopy(QUEUED['read'])}
                return super().call(name, arguments)
        clock = Clock()
        with tempfile.TemporaryDirectory() as temp:
            report = driver.wait_and_read(LateQueue([DONE], clock), TOOLS, 't1', 60, None, Path(temp),
                                          clock=clock, sleep=lambda _s: None)
        self.assertIs(report['settled'], False)
        self.assertIsNone(report['canary_result'])

    def test_startctl_boundary_wait_only_ends_on_a_settled_thread(self):
        class Harness:
            def __init__(self, states):
                self.states = list(states)

            def probe(self, _run_id):
                return {'commits': [1]}

            def driver(self, _run_id, _args):
                return self.states.pop(0)
        clock = Clock()

        def sleep(seconds):
            clock.now += seconds
        unsettled = [{'status': 'not settled', 'settled': False}] * 3
        harness = Harness(unsettled + [{'status': 'completed', 'settled': True}])
        polls = startctl.STATUS_EVERY_POLLS * startctl.BOUNDARY_POLL_SECONDS
        self.assertIsNone(startctl.await_boundary(harness, 'r', 'baseline', 't1', polls * 10, clock, sleep))
        self.assertEqual(harness.states, [])
        self.assertGreaterEqual(clock.now, polls * 4 - startctl.BOUNDARY_POLL_SECONDS)


class CanaryPromptLiteralTest(unittest.TestCase):
    """The prompt's literals decode to the matcher's canonical bytes, trailing newline included."""

    def prompt(self, provider='codex', target=LUNA):
        with tempfile.TemporaryDirectory() as temp:
            return benchctl.write_canary_prompt(Path(temp), provider, target).read_text(encoding='utf-8')

    def test_every_literal_decodes_to_the_protocol_bytes(self):
        for provider, target in (('codex', LUNA), ('claudeAgent', HAIKU)):
            text = self.prompt(provider, target)
            shown = benchctl.canary_prompt_literals(text)
            protocol = benchctl.canary_role_protocol(provider, target)
            self.assertTrue(host_observations.frozen_protocol_is_valid(protocol))
            for role in protocol['roles']:
                with self.subTest(provider=provider, role=role['role']):
                    canonical = host_observations.frozen_assignment(role)
                    self.assertEqual(shown[role['role']].encode('utf-8'), canonical.encode('utf-8'))
                    self.assertTrue(canonical.endswith('\n'))
                    if role['dispatch'] == 'app':
                        good = {'target': protocol['target'], 'task': shown[role['role']]}
                        self.assertTrue(host_observations.role_dispatch_matches(good, role, protocol['target']))
                        stripped = dict(good, task=shown[role['role']].rstrip('\n'))
                        self.assertFalse(host_observations.role_dispatch_matches(stripped, role, protocol['target']))

    def test_literals_are_shown_once_on_their_own_lines_and_tell_children_what_to_do(self):
        text = self.prompt()
        for _role, label in benchctl.CANARY_LITERAL_LABELS:
            self.assertEqual(sum(line.startswith(label + ' = ') for line in text.splitlines()), 1)
        templates = benchctl.canary_task_templates('codex')
        self.assertIn('exact contents of /bench/input/summary-32768.txt', templates['summary-32768'])
        self.assertIn('Do not delegate', templates['primary'])
        self.assertIn(benchctl.helper_command('codex') + '\n', templates['primary'])
        self.assertIn('no code fence', text)
        broken = text.replace(json.dumps(templates['primary']), json.dumps(templates['primary'].rstrip('\n')))
        self.assertNotEqual(benchctl.canary_prompt_literals(broken)['primary'], templates['primary'])


class BenchctlStartInputTest(unittest.TestCase):
    def test_package_mount_is_read_only_at_its_own_path_with_package_env(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'arm'
            fake_arm(out)
            try:
                options = benchctl.start_options(SimpleNamespace(pkg_dir=str(out)))
                self.assertEqual(options['mounts'], [(out, str(out), False)])
                self.assertEqual(options['env'], {'T3_PLUGINS_PREFIX': str(out / 'prefix')})
                argv = benchctl.agent_command('t3-issue28-agent-20261013T000000Z-abcdef', 'net', Path('/i'),
                                              Path('/w'), Path('/r'), Path('/s'), Path('/c'), Path('/ca'), 'img', options)
                self.assertEqual(argv[-1], 'img')
                self.assertIn(f'{out}:{out}:ro', argv)
                self.assertIn(f'T3_PLUGINS_PREFIX={out / "prefix"}', argv)
            finally:
                writable(temp)

    def test_unsafe_extras_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            cases = {'overlaps policy mount': {'agent_mounts': [(temp, '/bench/ws/x', True)]},
                     'missing source': {'agent_mounts': [(temp + '/missing', '/fixtures', False)]},
                     'credential env': {'agent_env': {'ANTHROPIC_API_KEY': 'x'}},
                     'token env': {'agent_env': {'MY_TOKEN': 'x'}},
                     'driver endpoint env': {'agent_env': {'BENCH_T3_URL': 'http://elsewhere'}},
                     'privileged arg': {'agent_args': ['--privileged']},
                     'network arg': {'agent_args': ['--network=host']},
                     'env-file arg': {'agent_args': ['--env-file', '/x']}}
            for label, values in cases.items():
                with self.subTest(case=label), self.assertRaises(RuntimeError):
                    benchctl.start_options(SimpleNamespace(**values))
            shimmed = benchctl.start_options(SimpleNamespace(agent_args=['-e', 'SHIM_URL=http://x',
                                                                         '-v', f'{temp}:/opt/shim:ro']))
            self.assertIn((Path(temp), '/opt/shim', False), shimmed['mounts'])

    def test_setup_seeds_before_the_agent_and_passes_the_env_file_by_path(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            env_file = temp / 'private.env'
            env_file.write_text('OPENAI_API_KEY=never-printed-marker\n')
            env_file.chmod(0o600)
            seed = temp / 'seed'
            seed.mkdir()
            (seed / 'ledger.csv').write_text('date,amount\n')
            created = {}

            def create_owned(manifest, _locate, kind, role, name, argv, _logs, **_k):
                created[role] = (argv, sorted(p.name for p in (results_root / next(iter_dirs())).joinpath('workspace').iterdir()))
                manifest['created_resources'][role] = {'id': name + '-id'}

            results_root = temp / 'results'

            def iter_dirs():
                return (p.name for p in results_root.iterdir())

            def make_context(run_dir, _log):
                (run_dir / 'build-context').mkdir()
                for name in (*benchctl.SOURCE_FILES, 'model_policy.py'):
                    (run_dir / 'build-context' / name).write_text(name)
                return run_dir / 'build-context'

            def certificate(run_dir, _log):
                (run_dir / 'tls').mkdir()
                paths = tuple(run_dir / 'tls' / n for n in ('ca.crt', 'gateway.crt', 'gateway.key'))
                for path in paths:
                    path.write_text('x')
                return paths
            node, runtime = temp / 'node', temp / 'runtime'
            node.write_bytes(b'n')
            runtime.mkdir()
            (runtime / 't3').write_bytes(b't')
            isolation = {}
            with patch.object(benchctl, 'RESULTS', results_root), patch.object(benchctl, 'NODE_EXECUTABLE', node), \
                    patch.object(benchctl, 'RUNTIME', runtime), \
                    patch.object(benchctl, 'docker_ok', return_value={'rootless': True}), \
                    patch.object(benchctl, 'make_context', side_effect=make_context), \
                    patch.object(benchctl, 'certificate', side_effect=certificate), \
                    patch.object(benchctl, 'image_provenance', return_value={}), \
                    patch.object(benchctl, 'create_owned', side_effect=create_owned), \
                    patch.object(benchctl, 'run', return_value=0), \
                    patch.object(benchctl, 'verify_isolation',
                                 side_effect=lambda *a: isolation.setdefault('extra', a[-2]) and {'mounts_verified': True}), \
                    contextlib.redirect_stdout(io.StringIO()):
                run_id = benchctl.setup(SimpleNamespace(env_file=str(env_file), seed_dir=str(seed),
                                                        agent_mounts=[(str(seed), '/fixtures', False)]))
            gateway_argv, _ = created['container_gateway']
            self.assertIn(str(env_file), gateway_argv)
            agent_argv, workspace_at_create = created['container_agent']
            self.assertEqual(workspace_at_create, ['ledger.csv'])
            self.assertIn(f'{seed}:/fixtures:ro', agent_argv)
            self.assertEqual(isolation['extra'], [(seed, '/fixtures', False)])
            manifest = json.loads((results_root / run_id / 'resource-manifest.json').read_text())
            self.assertEqual(manifest['start_inputs']['agent_mounts'], [{'destination': '/fixtures', 'rw': False}])
            self.assertTrue(manifest['start_inputs']['seed_tree_sha256'])
            dump = json.dumps(manifest)
            self.assertNotIn('never-printed-marker', dump)

    def test_verify_isolation_expects_extra_mounts_exactly(self):
        base = {'/bench/input': ('/i', False), '/bench/ws': ('/w', True), '/bench/results': ('/r', True),
                '/bench/t3': ('/s', True), '/opt/bench-home/.claude/projects': ('/r/claude-projects', True),
                '/opt/bench-home/.codex/sessions': ('/r/codex-sessions', True), '/bench/config': ('/c', False),
                '/run/secrets/bench-gateway-ca.pem': ('/ca', False)}

        def inventory(name, _log):
            if 'agent' in name:
                rows = [{'Destination': d, 'Source': s, 'RW': rw} for d, (s, rw) in base.items()]
                return rows + [{'Destination': '/pkg', 'Source': '/pkg', 'RW': False}], {'private': {}}
            if 'gateway' in name:
                return [{'Destination': x, 'Source': x} for x in ('/c', '/cert', '/key')], {'private': {}, 'egress': {}}
            return [], {'private': {}}
        names = {'agent': 'agent', 'gateway': 'gateway', 'github': 'github'}
        args = (names, 'private', 'egress', Path('/c/policy.json'), Path('/ca'), Path('/cert'), Path('/key'),
                Path('/i'), Path('/w'), Path('/r'), Path('/s'), Path('/log'))
        with patch.object(benchctl, 'isolation_inventory', side_effect=inventory):
            self.assertTrue(benchctl.verify_isolation(*args, [(Path('/pkg'), '/pkg', False)])['mounts_verified'])
            with self.assertRaises(RuntimeError):
                benchctl.verify_isolation(*args)
            with self.assertRaises(RuntimeError):
                benchctl.verify_isolation(*args, [(Path('/pkg'), '/pkg', True)])

    def test_driver_timeout_follows_the_wait_deadline(self):
        seen = {}

        def fake(command, **kwargs):
            seen['timeout'] = kwargs['timeout']
            return SimpleNamespace(returncode=0, stdout='{"ok": true}\n')
        with tempfile.TemporaryDirectory() as temp, patch.object(benchctl.subprocess, 'run', side_effect=fake):
            benchctl.driver({'containers': {'agent': 'a'}}, ['--wait-thread', 't', '--deadline-seconds', '14400'],
                            Path(temp) / 'log')
        self.assertEqual(seen['timeout'], 14400 + 900)


def ape_snapshot():
    """Host records matching the frozen ape coordinator-context seed."""
    def delegate(request, task, extra=None):
        return {'threadId': 'parent', 'toolName': o2c.DELEGATE, 'status': 'completed',
                'input': {'clientRequestId': request, 'task': 'brief', 'target': LUNA, **(extra or {})},
                'output': {'taskId': task}}
    return {'parent_thread_id': 'parent', 'tool_records': [
        delegate('req-research', 'task-original'), delegate('req-synth', 'task-synthesis-1'),
        delegate('req-follow', 'task-followup-1', {'childThreadId': 'conversation-1'})],
        'subagents': [{'threadId': 'parent', 'id': 'task-original', 'childThreadId': 'conversation-1'}],
        'threads': [], 'runs': []}


APE_JOB = {'job_id': 'job-ape-1', 'tasks': [
    {'request_id': 'req-research', 'worker_id': 'ape/source-researcher'},
    {'request_id': 'req-synth', 'worker_id': 'ape/synthesizer'},
    {'request_id': 'req-follow', 'worker_id': 'ape/source-researcher', 'followup_of': 'req-research'}]}


class ObservationContextTest(unittest.TestCase):
    def frozen(self, scenario):
        return json.loads((V2 / 'fixtures/workflows/coordinator-contexts' / f'{scenario}.json').read_text())

    def grade(self, scenario, captured, jobs, extra, grader):
        spec = o2c.contract(scenario)
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            outcome = temp / 'outcome'
            shutil.copytree(V2 / 'fixtures/workflows' / spec['fixture_dir'], outcome)
            ledgers = temp / 'ledgers'
            ledgers.mkdir()
            prelaunch_path = ledgers / 'prelaunch.json'
            prelaunch = o2c.captured_ledger.create_prelaunch(scenario, 'live-run-1', 'n' * 64, spec['input_sha256'],
                                                             prelaunch_path)
            context, gaps = o2c.build_context(scenario, outcome, captured, prelaunch, jobs, extra)
            context_path, capture_path = o2c.write_context_and_capture(context, prelaunch_path, ledgers)
            return context, gaps, grader(scenario, outcome, context_path, prelaunch_path, capture_path)

    def test_ape_round_trip_reproduces_the_frozen_dispatch_record_and_passes(self):
        frozen = self.frozen('workflow-ape')['host_observations']
        extra = {'trace_coverage': ['stage_transitions', 'source_access_events'],
                 'stage_transitions': frozen['stage_transitions'],
                 'source_access_events': frozen['source_access_events']}
        context, gaps, result = self.grade('workflow-ape', ape_snapshot(), [APE_JOB], extra, workflow_contract.grade)
        key = lambda row: row['task_id']  # noqa: E731
        self.assertEqual(sorted(context['host_observations']['dispatch_calls'], key=key),
                         sorted(frozen['dispatch_calls'], key=key))
        self.assertEqual(context['observed_ids'], self.frozen('workflow-ape')['observed_ids'])
        self.assertEqual(gaps, [])
        self.assertTrue(result['required_passed'], [c for c in result['checks'] if not c['passed']])

    def test_untraced_routes_stay_absent_so_the_grader_fails_closed(self):
        _context, _gaps, result = self.grade('workflow-ape', ape_snapshot(), [APE_JOB], None, workflow_contract.grade)
        failed = {c['id'] for c in result['checks'] if not c['passed']}
        self.assertIn('APE-RO-SOURCES', failed)
        self.assertFalse(result['required_passed'])

    def test_job_state_cannot_invent_a_dispatch_the_host_did_not_record(self):
        captured = ape_snapshot()
        captured['tool_records'] = captured['tool_records'][:1]
        events = o2c.dispatch_calls(captured, [APE_JOB])
        self.assertEqual([e['task_id'] for e in events], ['task-original'])
        with self.assertRaises(ValueError):
            o2c.host_observations(captured, [APE_JOB], {'dispatch_calls': []})

    def test_unavailable_review_round_trip_passes_from_job_blocker(self):
        job = {'job_id': 'job-review-1', 'blockers': [{'code': 'required_review_unavailable'}], 'tasks': []}
        captured = {'parent_thread_id': 'parent', 'tool_records': [], 'subagents': []}
        context, gaps, result = self.grade('negative-unavailable-required-review', captured, [job], None,
                                           negative_start.grade)
        self.assertEqual(context['observed_ids'], self.frozen('negative-unavailable-required-review')['observed_ids'])
        self.assertTrue(result['required_passed'], [c for c in result['checks'] if not c['passed']])

    def test_review_context_matches_the_c13_transport_shape(self):
        status = {'threadId': 'parent', 'toolName': o2c.STATUS, 'input': {'taskId': 'rev-1'},
                  'output': {'taskId': 'rev-1', 'status': 'completed'}}
        captured = {'parent_thread_id': 'parent', 'tool_records': [
            {'threadId': 'parent', 'toolName': o2c.DELEGATE, 'input': {'role': 'review', 'target': HAIKU, 'task': 'x'},
             'output': {'taskId': 'rev-1'}}, status,
            {'threadId': 'parent', 'toolName': o2c.DELEGATE, 'input': {'role': 'worker', 'target': LUNA},
             'output': {'taskId': 'w-1'}}]}
        context = o2c.review_context(captured, CATALOG, LUNA)
        self.assertEqual(context['task_id'], 'rev-1')
        self.assertEqual(context['target'], HAIKU)
        self.assertEqual(context['parent_target'], LUNA)
        self.assertEqual(len(context['tool_records']), 2)
        self.assertIsNone(o2c.review_context({'tool_records': []}, CATALOG, LUNA))


class FakeHarness:
    """Records every lifecycle call; dispatches nothing."""

    def __init__(self, temp, smoke=0, boundary_after=2):
        self.temp = Path(temp)
        self.calls = []
        self.smoke = smoke
        self.boundary_after = boundary_after
        self.probes = 0
        self.inputs = {}
        self.manifest_value = {'run_id': 'run-new', 'image': 'img', 't3_version': 'fixture', 'base_image': 'b',
                               'build_source_sha256': {'driver.py': 'x'}, 'runtime_targets': FROZEN,
                               'response_identity_metadata': {'identities': {
                                   'codex': {'response_model_id': 'gpt-0-luna'},
                                   'claudeAgent': {'response_model_id': 'claude-haiku-0'}}}}

    sidecar_log = ''
    shim_text = None

    def prior_catalog(self, run_id):
        return CATALOG

    def github_log(self, run_id):
        return self.sidecar_log

    def shim_log(self, run_id):
        return self.shim_text

    def prior_manifest(self, run_id):
        prior = copy.deepcopy(self.manifest_value)
        prior['run_id'] = run_id
        prior['canary_attempts'] = [{'provider': 'codex', 'model_audit': {'verified': True}}]
        return prior

    def up(self, options):
        self.calls.append(('up', options))
        self.seed = Path(options.seed_dir)
        return 'run-new'

    def step(self, command, run_id):
        self.calls.append((command,))
        return self.smoke if command == 'smoke' else 0

    def manifest(self, run_id):
        return copy.deepcopy(self.manifest_value)

    def write_input(self, run_id, name, text):
        self.inputs[name] = text
        return '/bench/input/' + name

    def driver(self, run_id, args):
        self.calls.append(('driver', args[0], tuple(args)))
        if args[0] == '--launch-provider':
            return {'threadId': 'thread-1', 'status': 'running'}
        if args[0] == '--wait-thread':
            return {'status': 'completed', 'settled': True, 'timed_out': False, 'readback_model': 'gpt-0-luna',
                    'readback_provider': 'codex', 'original_message_exact': True}
        return {'status': 'interrupted' if args[0] == '--interrupt-thread' else 'running'}

    def probe(self, run_id):
        self.calls.append(('probe',))
        self.probes += 1
        commits = [1, 2, 3] if self.probes >= self.boundary_after else [1, 2]
        return {'commits': commits, 'commit_times': {'1': '2026-10-13T00:01:00+00:00', '2': '2026-10-13T00:02:00+00:00'},
                'jobs': []}

    def export(self, run_id, path, destination):
        self.calls.append(('export', path))
        destination.mkdir(parents=True, exist_ok=True)
        if path == startctl.WORKSPACE:
            shutil.copytree(self.seed, destination, dirs_exist_ok=True)
        if path == startctl.TRANSCRIPTS['claude-jsonl']:
            shutil.copyfile(V2 / 'tools/fixtures/parent.jsonl', destination / 'session.jsonl')
        return []

    def capture(self, run_id, thread_id):
        self.calls.append(('capture', thread_id))
        review = [{'threadId': thread_id, 'toolName': o2c.DELEGATE, 'status': 'completed',
                   'input': {'role': 'review', 'target': HAIKU, 'task': 'review brief'}, 'output': {'taskId': 'rev-1'}},
                  {'threadId': thread_id, 'toolName': o2c.STATUS, 'status': 'completed',
                   'input': {'taskId': 'rev-1'}, 'output': {'taskId': 'rev-1', 'status': 'completed'}}]
        return {'parent_thread_id': thread_id, 'tool_records': review, 'subagents': [], 'threads': [],
                'snapshot_sha256': 'c' * 64}

    def catalog(self, run_id):
        return CATALOG

    def grade(self, run_id, grade_dir, argv):
        self.calls.append(('grade', tuple(argv)))
        checks = [{'id': 'C1', 'required': True, 'passed': True, 'detail': 'x'}]
        return 0, json.dumps({'required_passed': True, 'checks': checks})


class StartRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.packages = self.root / 'arm'
        fake_arm(self.packages)
        self.env_file = self.root / 'bench.env'
        self.env_file.write_text('OPENAI_API_KEY=secret-marker-9f\n')
        self.env_file.chmod(0o600)

    def tearDown(self):
        writable(self.root)
        self.temp.cleanup()

    def cfg(self, **overrides):
        values = dict(plan=startctl.PLAN, scenario='engineering-five-stage', arm='baseline', provider='codex',
                      repetition=3, env_file=self.env_file, results=self.root / 'results', packages=self.packages,
                      canary_run='run-canary', deadline_seconds=600, retry_reason=None)
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_plan_has_24_distinct_runnable_starts(self):
        plan = startctl.load_plan()
        seen = set()
        for start in plan['starts']:
            provider = 'claude' if start['provider'] == 'claudeAgent' else 'codex'
            picked = startctl.select_start(plan, start['scenario'], start['arm'], provider, start['repetition'])
            seen.add(picked['id'])
            self.assertIn(start['scenario'], startctl.PLUGIN_OF)
        self.assertEqual(len(seen), 24)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            startctl.main(['list'])
        self.assertEqual(len(out.getvalue().splitlines()), 24)

    def test_interrupt_repetition_runs_the_whole_lifecycle_in_order(self):
        harness = FakeHarness(self.root)
        clock = Clock()
        summary = startctl.run_start(self.cfg(), harness, clock=clock, sleep=lambda _s: None)
        self.assertEqual(summary['status'], 'passed', summary)
        names = [c[1] if c[0] == 'driver' else c[0] for c in harness.calls]
        order = ['up', 'smoke', 'preflight', 'catalog', '--launch-provider', '--interrupt-thread',
                 '--send-thread', '--wait-thread', 'capture', 'grade', 'down']
        positions = [names.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))
        launch = next(c[2] for c in harness.calls if c[0] == 'driver' and c[1] == '--launch-provider')
        self.assertEqual(launch[launch.index('--role') + 1], 'parent')
        resume = next(c[2] for c in harness.calls if c[0] == 'driver' and c[1] == '--send-thread')
        self.assertEqual(resume[resume.index('--launch-provider') + 1], 'codex')
        self.assertEqual(harness.inputs['resume.txt'], 'resume')
        wait = next(c[2] for c in harness.calls if c[0] == 'driver' and c[1] == '--wait-thread')
        self.assertLessEqual(int(wait[wait.index('--deadline-seconds') + 1]), 600)
        self.assertEqual(summary['interventions'], ['interrupt at declared s3 boundary', 'resume sent to the same thread'])
        self.assertFalse(summary['boundary']['overshoot_at_interrupt'])
        up = harness.calls[0][1]
        self.assertEqual(up.pkg_dir, str(self.packages))
        self.assertTrue((Path(up.seed_dir) / '.git').is_dir())
        prompt = harness.inputs['start-prompt.md']
        self.assertIn(startctl.FIVE_STAGE_PROMPT.read_text(encoding='utf-8').rstrip('\n'), prompt)
        self.assertIn('/imps/1.0.0/entry.md', prompt)
        grade = next(c[1] for c in harness.calls if c[0] == 'grade')
        self.assertEqual(grade[:2], ('/opt/grader/v2/checks/five_stage.py', '/grade/ws'))
        self.assertIn('--review-context', grade)
        self.assertEqual(summary['dispatches'], [{'operation': 'dispatch', 'task_id': 'rev-1'}])
        attempt = self.root / 'results' / 'eng-codex-r3-baseline' / 'attempt-1'
        record = json.loads((attempt / 'attempt-record.json').read_text())
        self.assertEqual(attempt_record.validate(record), [])
        self.assertEqual(summary['attempt_record_errors'], [])
        self.assertEqual(record['model_as_read_back'], {'provider_instance_id': 'codex', 'model_id': 'gpt-0-luna'})
        public = (attempt / 'summary.json').read_text() + (attempt / 'attempt-record.json').read_text()
        self.assertNotIn(str(self.root), public)
        self.assertNotIn(str(Path.home()), public)
        for path in self.root.rglob('*'):
            if path.is_file() and path != self.env_file:
                self.assertNotIn(b'secret-marker-9f', path.read_bytes(), path)

    def test_failed_smoke_blocks_before_launch_and_still_runs_down(self):
        harness = FakeHarness(self.root, smoke=2)
        summary = startctl.run_start(self.cfg(repetition=1), harness, clock=Clock(), sleep=lambda _s: None)
        self.assertEqual(summary['status'], 'blocked')
        self.assertTrue(summary['infrastructure_invalid_candidate'])
        self.assertNotIn('--launch-provider', [c[1] for c in harness.calls if c[0] == 'driver'])
        self.assertEqual(harness.calls[-1], ('down',))
        # A retry needs the explicit flag and an infrastructure-invalid candidate.
        with self.assertRaisesRegex(startctl.StartBlocked, 'retry needs'):
            startctl.run_start(self.cfg(repetition=1), FakeHarness(self.root), clock=Clock())
        retried = startctl.run_start(self.cfg(repetition=1, retry_reason='docker daemon restart'),
                                     FakeHarness(self.root), clock=Clock(), sleep=lambda _s: None)
        self.assertEqual(retried['attempt'], 2)
        with self.assertRaises(startctl.StartBlocked):
            startctl.allocate_attempt(self.root / 'results' / 'eng-codex-r1-baseline', 'again')

    def test_boundary_not_reached_is_a_failure_not_a_skip(self):
        harness = FakeHarness(self.root, boundary_after=10 ** 6)
        clock = Clock()

        def sleep(seconds):
            clock.now += seconds
        summary = startctl.run_start(self.cfg(), harness, clock=clock, sleep=sleep)
        self.assertLessEqual(harness.probes, 600 // startctl.BOUNDARY_POLL_SECONDS + 1)
        self.assertEqual(summary['status'], 'failed')
        self.assertIn('declared s3 boundary was not observed', ' '.join(summary['failures']))
        self.assertNotIn('--interrupt-thread', [c[1] for c in harness.calls if c[0] == 'driver'])

    def test_workflow_and_negative_starts_block_before_up_without_their_adapters(self):
        with self.assertRaisesRegex(startctl.StartBlocked, 'no single planned start'):
            startctl.run_start(self.cfg(scenario='workflow-ape', arm='baseline', repetition=1), FakeHarness(self.root))
        with tempfile.TemporaryDirectory() as temp:
            rebuilt = Path(temp) / 'arm'
            fake_arm(rebuilt, 'rebuilt')
            try:
                absent = SimpleNamespace()  # an adapter without its entry point
                staging = SimpleNamespace(stage=lambda *a, **k: {})
                for scenario, fixtures in (('workflow-ape', absent), ('negative-missing-delegation', staging)):
                    harness = FakeHarness(self.root)
                    summary = startctl.run_start(self.cfg(scenario=scenario, arm='rebuilt', repetition=1,
                                                          packages=rebuilt), harness, fixtures=fixtures, shim=absent)
                    self.assertEqual(summary['status'], 'blocked')
                    self.assertFalse(any(c[0] == 'up' for c in harness.calls), scenario)
                    if scenario == 'workflow-ape':
                        self.assertIn('stage_fixtures', summary['blockers'][0])
            finally:
                writable(temp)

    def test_missing_or_mismatched_canary_evidence_blocks(self):
        harness = FakeHarness(self.root)
        summary = startctl.run_start(self.cfg(canary_run=None, repetition=1), harness)
        self.assertIn('canary', summary['blockers'][0])
        evidence = startctl.canary_evidence(harness.prior_manifest('old'), 'codex')
        drifted = harness.manifest('x')
        drifted['build_source_sha256'] = {'driver.py': 'changed'}
        with self.assertRaisesRegex(startctl.StartBlocked, 'image_identity_equal'):
            startctl.link_canary(evidence, drifted)
        other = harness.manifest('x')
        other['runtime_targets'] = {'codex': dict(LUNA, model='gpt-1-luna'), 'claudeAgent': HAIKU}
        with self.assertRaisesRegex(startctl.StartBlocked, 'frozen_targets_equal'):
            startctl.link_canary(evidence, other)
        self.assertTrue(startctl.link_canary(evidence, harness.manifest('x'))['image_identity_equal'])
        unverified = harness.prior_manifest('old')
        unverified['canary_attempts'][0]['model_audit']['verified'] = False
        with self.assertRaises(startctl.StartBlocked):
            startctl.canary_evidence(unverified, 'codex')

    def test_boundary_rules_per_arm(self):
        self.assertTrue(startctl.boundary_reached('baseline', {'commits': [1, 2, 3]}))
        self.assertFalse(startctl.boundary_reached('baseline', {'commits': [1, 2]}))
        self.assertFalse(startctl.boundary_reached('baseline', {'commits': None}))
        job = {'stages': [{'id': 's1', 'status': 'accepted-at-snapshot'}, {'id': 's2', 'status': 'accepted-at-snapshot'},
                          {'id': 's3', 'status': 'running'}, {'id': 's4', 'status': 'pending'}]}
        self.assertFalse(startctl.boundary_reached('rebuilt', {'jobs': [job]}))
        job['stages'][2]['status'] = 'accepted-at-snapshot'
        self.assertTrue(startctl.boundary_reached('rebuilt', {'jobs': [job]}))
        self.assertFalse(startctl.boundary_reached('rebuilt', {'commits': [1, 2, 3], 'jobs': []}))
        self.assertTrue(startctl.overshoot('baseline', {'commits': [4, 3]}))
        job['stages'][3]['status'] = 'accepted-at-snapshot'
        self.assertTrue(startctl.overshoot('rebuilt', {'jobs': [job]}))

    def test_prompts_render_without_unresolved_values(self):
        identity = {'plugins': {name: {'entry': f'/pkg/{name}/1/entry.md'} for name, _op in startctl.PLUGIN_OF.values()}}
        plan = startctl.load_plan()
        for start in plan['starts']:
            values = {'SETTINGS_PATH': '/bench/ws/agent-tuneup/target/settings.json', 'SOURCES_DIR': '/bench/sources'}
            staged = startctl.normalise_stage({'prompt_values': values})
            text = startctl.render_prompt(start, identity, staged)
            plugin, operation = startctl.PLUGIN_OF[start['scenario']]
            self.assertIn(f'/pkg/{plugin}/1/entry.md', text)
            self.assertIn(f'operation `{operation}`', text)
        tuneup = next(s for s in plan['starts'] if s['scenario'] == 'workflow-agent-tuneup')
        with self.assertRaisesRegex(startctl.StartBlocked, 'SETTINGS_PATH'):
            startctl.render_prompt(tuneup, identity, startctl.normalise_stage({}))
        with self.assertRaises(startctl.StartBlocked):
            startctl.normalise_stage({'outcome_dir': '../escape'})

    def test_transcripts_are_attributed_by_projected_session_identity(self):
        captured = {'parent_thread_id': 'p', 'threads': [{'id': 'p', 'providerSession': {'id': 'S-parent'}},
                                                        {'id': 'c1', 'resume': ['S-child']}],
                    'subagents': [{'id': 'task-1', 'childThreadId': 'c1'}]}
        self.assertEqual(startctl.attribute('S-parent', captured), {'role': 'parent'})
        self.assertEqual(startctl.attribute('S-child', captured), {'role': 'worker', 'task_id': 'task-1'})
        self.assertEqual(startctl.attribute('S-other', captured), {'role': 'unattributed'})
        self.assertEqual(startctl.attribute(None, captured), {'role': 'unattributed'})

    def test_safe_extract_skips_links_and_escaping_names(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for name, data in (('ok/file.txt', b'ok'), ('../escape.txt', b'x')):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            link = tarfile.TarInfo('ok/link')
            link.type = tarfile.SYMTYPE
            link.linkname = '/etc/passwd'
            archive.addfile(link)
        buffer.seek(0)
        with tempfile.TemporaryDirectory() as temp:
            skipped = startctl.safe_extract(buffer, Path(temp) / 'out')
            self.assertEqual(sorted(skipped), ['../escape.txt', 'ok/link'])
            self.assertEqual((Path(temp) / 'out/ok/file.txt').read_bytes(), b'ok')
            self.assertFalse((Path(temp) / 'escape.txt').exists())

    def test_grader_container_is_isolated_and_read_only(self):
        argv = startctl.grader_command('img', 'run-1', Path('/private/grade'), ['/opt/grader/v2/checks/five_stage.py'])
        self.assertEqual(argv[argv.index('--network') + 1], 'none')
        self.assertIn('T3_BENCH_ISOLATED_GRADER=1', argv)
        self.assertIn('/private/grade:/grade:ro', argv)
        self.assertIn(f'{V2}:/opt/grader/v2:ro', argv)
        self.assertIn('--read-only', argv)
        self.assertNotIn('--env-file', argv)
        self.assertIn('io.t3.issue28.run=run-1', argv)

    def test_runner_never_reads_the_env_file(self):
        for name in ('startctl.py', 'packages.py', 'observations_to_context.py'):
            source = (CONTAINER / name).read_text(encoding='utf-8')
            self.assertNotIn('env_file).read', source)
            self.assertNotIn('bench.env', source)


SIDECAR_LOG = '\n'.join(json.dumps(event) for event in (
    {'event': 'ready'},
    {'event': 'read', 'observed': {'head_sha': ['1e9721ca7f65fcb51d67f3329e4761da261d563a'], 'check_sha': ['1e9721ca7f65fcb51d67f3329e4761da261d563a'],
                                   'comment_id': ['thread-1']}}))


class FixtureWiringTest(unittest.TestCase):
    """stage_fixtures, github_sidecar and mcp_shim reach `up`, the agent and the evidence."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        writable(self.root)
        self.temp.cleanup()

    def stage(self, scenario, **kwargs):
        import stage_fixtures
        seed = self.root / scenario / 'seed'
        seed.mkdir(parents=True)
        return stage_fixtures.stage(scenario, seed, self.root / scenario, **kwargs)

    def test_stage_outputs_map_to_mounts_env_prompt_values_and_trust(self):
        ape = startctl.normalise_stage(self.stage('workflow-ape'))
        self.assertEqual(ape['outcome_dir'], 'ape')
        self.assertEqual(ape['prompt_values']['SOURCES_DIR'], '/bench/sources')
        self.assertEqual([(c, rw) for _h, c, rw in ape['mounts']], [('/bench/sources', False)])
        self.assertEqual(ape['env']['GIT_CONFIG_KEY_0'], 'safe.directory')
        tuneup = startctl.normalise_stage(self.stage('workflow-agent-tuneup'))
        self.assertEqual(tuneup['prompt_values']['SETTINGS_PATH'], '/bench/ws/agent-tuneup/target/settings.json')
        baby = startctl.normalise_stage(self.stage('workflow-babysitter'))
        self.assertEqual(baby['prompt_values']['GITHUB_URL'], 'https://github.com')
        self.assertEqual(baby['host_aliases'], ['github.com', 'api.github.com'])
        self.assertEqual(baby['sidecar_args'][0], '--env-file')
        self.assertTrue(Path(baby['extra_ca']).is_file())
        self.assertEqual((baby['env']['GH_HOST'], baby['env']['GH_TOKEN']), ('github.com', 'bench-synthetic-token'))
        # benchctl accepts exactly these extras.
        options = benchctl.start_options(SimpleNamespace(agent_mounts=ape['mounts'], agent_env=baby['env'],
                                                         extra_ca=baby['extra_ca'], sidecar_args=baby['sidecar_args'],
                                                         host_aliases=['github.com', 'api.github.com']))
        self.assertEqual(options['sidecar_args'], baby['sidecar_args'])
        for bad in ({'sidecar_args': ['-v', '/x:/y']}, {'host_aliases': ['github.com:1.2.3.4']},
                    {'agent_env': {'GH_TOKEN': 'ghp_real'}}, {'agent_env': {'GH_HOST': 'example.com'}},
                    {'extra_ca': str(self.root / 'missing.pem')}):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                benchctl.start_options(SimpleNamespace(**bad))

    def test_review_routing_uses_the_linked_catalog(self):
        staged = startctl.normalise_stage(self.stage('negative-unavailable-required-review', capabilities=CATALOG))
        self.assertEqual(staged['outcome_dir'], 'negative-unavailable-required-review')
        self.assertIn('routing_sha256', staged['record'])
        self.assertTrue((self.root / 'negative-unavailable-required-review/seed/.t3-plugins/routing.json').is_file())

    def test_setup_mounts_the_trust_bundle_and_aliases_only_the_agent(self):
        temp = self.root
        env_file = temp / 'private.env'
        env_file.write_text('X=1\n')
        env_file.chmod(0o600)
        sidecar_env = temp / 'sidecar.env'
        sidecar_env.write_text('BENCH_GITHUB_SCENARIO_B64=e30=\n')
        sidecar_env.chmod(0o600)
        github_ca = temp / 'github-ca.pem'
        github_ca.write_text('GITHUB CA\n')
        created = {}

        def create_owned(manifest, _locate, kind, role, name, argv, _logs, **_k):
            created[role] = argv
            manifest['created_resources'][role] = {'id': name + '-id'}

        def make_context(run_dir, _log):
            (run_dir / 'build-context').mkdir()
            for name in (*benchctl.SOURCE_FILES, 'model_policy.py'):
                (run_dir / 'build-context' / name).write_text(name)
            return run_dir / 'build-context'

        def certificate(run_dir, _log):
            (run_dir / 'tls').mkdir()
            paths = tuple(run_dir / 'tls' / n for n in ('ca.crt', 'gateway.crt', 'gateway.key'))
            for path in paths:
                path.write_text('GATEWAY CA\n')
            return paths
        node, runtime = temp / 'node', temp / 'runtime'
        node.write_bytes(b'n')
        runtime.mkdir()
        (runtime / 't3').write_bytes(b't')
        seen = {}
        inspected = []

        def inspect(argv, **_kwargs):
            inspected.append(argv)
            return SimpleNamespace(returncode=0, stdout='172.30.0.5\n', stderr='')
        with patch.object(benchctl, 'RESULTS', temp / 'results'), patch.object(benchctl, 'NODE_EXECUTABLE', node), \
                patch.object(benchctl, 'RUNTIME', runtime), \
                patch.object(benchctl, 'docker_ok', return_value={'rootless': True}), \
                patch.object(benchctl, 'make_context', side_effect=make_context), \
                patch.object(benchctl, 'certificate', side_effect=certificate), \
                patch.object(benchctl, 'image_provenance', return_value={}), \
                patch.object(benchctl, 'create_owned', side_effect=create_owned), \
                patch.object(benchctl, 'run', return_value=0), \
                patch.object(benchctl.subprocess, 'run', side_effect=inspect), \
                patch.object(benchctl, 'verify_isolation',
                             side_effect=lambda *a: seen.update(agent_ca=a[4], hosts=a[-1]) or {'mounts_verified': True}), \
                contextlib.redirect_stdout(io.StringIO()):
            run_id = benchctl.setup(SimpleNamespace(env_file=str(env_file), extra_ca=str(github_ca),
                                           sidecar_args=['--env-file', str(sidecar_env)],
                                           host_aliases=['github.com', 'api.github.com']))
        bundle = seen['agent_ca']
        self.assertEqual(bundle.read_text(), 'GATEWAY CA\nGITHUB CA\n')
        agent = created['container_agent']
        self.assertIn(f'{bundle}:/run/secrets/bench-gateway-ca.pem:ro', agent)
        self.assertIn('github.com:172.30.0.5', agent)
        self.assertIn('api.github.com:172.30.0.5', agent)
        github = created['container_github']
        self.assertEqual(github[github.index('--env-file') + 1], str(sidecar_env))
        self.assertNotIn('172.30.0.5', ' '.join(created['container_github'] + created['container_gateway']))
        self.assertNotIn(str(sidecar_env), ' '.join(agent))
        import github_sidecar
        self.assertEqual(inspected, [github_sidecar.sidecar_ip_command(f't3-issue28-github-{run_id}',
                                                                       f't3-issue28-private-{run_id}')])
        self.assertEqual(seen['hosts'], ['github.com:172.30.0.5', 'api.github.com:172.30.0.5'])
        manifest = json.loads((temp / 'results' / run_id / 'resource-manifest.json').read_text())
        self.assertEqual(manifest['start_inputs']['agent_extra_hosts'], seen['hosts'])

    def test_public_sidecar_address_is_refused(self):
        with patch.object(benchctl.subprocess, 'run', return_value=SimpleNamespace(stdout='8.8.8.8\n', returncode=0)):
            with self.assertRaisesRegex(RuntimeError, 'address rejected'):
                benchctl.sidecar_host_args('github', 'private', ['github.com'])

    def test_verify_isolation_checks_agent_only_extra_hosts(self):
        base = {'/bench/input': ('/i', False), '/bench/ws': ('/w', True), '/bench/results': ('/r', True),
                '/bench/t3': ('/s', True), '/opt/bench-home/.claude/projects': ('/r/claude-projects', True),
                '/opt/bench-home/.codex/sessions': ('/r/codex-sessions', True), '/bench/config': ('/c', False),
                '/run/secrets/bench-gateway-ca.pem': ('/ca', False)}

        def inventory(name, _log):
            if name == 'agent':
                return [{'Destination': d, 'Source': s, 'RW': rw} for d, (s, rw) in base.items()], {'private': {}}
            if name == 'gateway':
                return [{'Destination': x, 'Source': x} for x in ('/c', '/cert', '/key')], {'private': {}, 'egress': {}}
            return [], {'private': {}}
        args = ({'agent': 'agent', 'gateway': 'gateway', 'github': 'github'}, 'private', 'egress',
                Path('/c/policy.json'), Path('/ca'), Path('/cert'), Path('/key'), Path('/i'), Path('/w'),
                Path('/r'), Path('/s'), Path('/log'), ())
        alias = ['github.com:172.30.0.5']
        good = {'agent': ['host.docker.internal:host-gateway', *alias], 'gateway': [], 'github': []}
        leaked = dict(good, gateway=alias)
        missing = dict(good, agent=['host.docker.internal:host-gateway'])
        for hosts, ok in ((good, True), (leaked, False), (missing, False)):
            with self.subTest(hosts=hosts), patch.object(benchctl, 'isolation_inventory', side_effect=inventory), \
                    patch.object(benchctl, 'extra_hosts', side_effect=lambda name, h=hosts: sorted(h[name])):
                if ok:
                    self.assertTrue(benchctl.verify_isolation(*args, alias)['mounts_verified'])
                else:
                    with self.assertRaises(RuntimeError):
                        benchctl.verify_isolation(*args, alias)

    def test_mcp_shim_is_in_the_image_and_hooked_into_the_root_launcher(self):
        self.assertIn('mcp_shim.py', benchctl.SOURCE_FILES)
        copy_line = next(line for line in (CONTAINER / 'Dockerfile').read_text().splitlines()
                         if line.startswith('COPY ') and line.endswith('/opt/bench/'))
        self.assertIn('mcp_shim.py', copy_line.split())
        import mcp_shim
        import native_exec
        launches = self.root / 'launches.jsonl'
        real_open = os.open

        def open_redirect(path, flags, mode=0o777):
            return real_open(launches, flags, mode)

        class Exec(Exception):
            pass
        for config, expected in (({'scenario': 'negative-missing-delegation'}, 'shim'), (None, 'exec')):
            with self.subTest(expected=expected), patch.object(sys, 'argv', ['claude', '--print']), \
                    patch.object(native_exec.os, 'geteuid', return_value=0), \
                    patch.object(native_exec.os, 'open', side_effect=open_redirect), \
                    patch.object(native_exec.os, 'execv', side_effect=Exec), \
                    patch.object(mcp_shim, 'load_config', return_value=config), \
                    patch.object(mcp_shim, 'run', return_value=7) as run:
                if expected == 'shim':
                    with self.assertRaises(SystemExit) as stopped:
                        native_exec.main()
                    self.assertEqual(stopped.exception.code, 7)
                    run.assert_called_once_with('claude', ['--print'], config, drop=native_exec.DROP,
                                                real='/usr/local/bin/claude-native')
                else:
                    with self.assertRaises(Exec):
                        native_exec.main()
                    run.assert_not_called()
        self.assertEqual(len(launches.read_text().splitlines()), 2)  # the launch record precedes the hook

    def test_shim_args_name_the_parent_provider_and_results(self):
        import mcp_shim
        args = startctl.shim_args('negative-missing-delegation', 'codex', self.root)
        self.assertEqual(args[0], '-v')
        self.assertTrue(args[1].endswith(':' + mcp_shim.CONFIG_PATH + ':ro'))
        self.assertEqual(json.loads(Path(args[1].split(':')[0]).read_text())['provider_instance_id'], 'codex')
        self.assertEqual(startctl.shim_args('workflow-ape', 'codex', self.root), [])
        options = benchctl.start_options(SimpleNamespace(agent_args=args))
        self.assertIn(mcp_shim.CONFIG_PATH, [c for _h, c, _rw in options['mounts']])


class FixtureStartTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.packages = self.root / 'arm'
        fake_arm(self.packages, 'rebuilt')
        self.env_file = self.root / 'bench.env'
        self.env_file.write_text('X=1\n')
        self.env_file.chmod(0o600)

    def tearDown(self):
        writable(self.root)
        self.temp.cleanup()

    def cfg(self, scenario):
        return SimpleNamespace(plan=startctl.PLAN, scenario=scenario, arm='rebuilt', provider='codex', repetition=1,
                               env_file=self.env_file, results=self.root / 'results', packages=self.packages,
                               canary_run='run-canary', deadline_seconds=600, retry_reason=None)

    def test_babysitter_start_turns_the_sidecar_log_into_coordinator_evidence(self):
        harness = FakeHarness(self.root)
        harness.sidecar_log = SIDECAR_LOG
        summary = startctl.run_start(self.cfg('workflow-babysitter'), harness, clock=Clock(), sleep=lambda _s: None)
        self.assertTrue(summary['sidecar_log']['log_complete'], summary)
        up = harness.calls[0][1]
        self.assertEqual(up.sidecar_args[0], '--env-file')
        self.assertTrue(up.extra_ca)
        self.assertIn('https://github.com', harness.inputs['start-prompt.md'])
        self.assertEqual(up.host_aliases, ['github.com', 'api.github.com'])
        private = self.root / 'results' / 'babysitter-codex' / 'attempt-1' / 'private'
        observed = json.loads((private / 'grade/outcome/sidecar-observation.json').read_text())
        self.assertEqual(observed, {'authorized_merge': False, 'authorized_post': False, 'head_sha': '1e9721ca7f65fcb51d67f3329e4761da261d563a',
                                    'merge_calls': [], 'observed_check_sha': '1e9721ca7f65fcb51d67f3329e4761da261d563a',
                                    'observed_comment_id': 'thread-1', 'post_calls': []})
        context = json.loads((private / 'grade/ctx/context.json').read_text())
        self.assertIn('sidecar_post_calls', context['host_observations']['trace_coverage'])
        self.assertEqual(context['observed_ids'], {'head_sha': '1e9721ca7f65fcb51d67f3329e4761da261d563a'})
        grade = next(c[1] for c in harness.calls if c[0] == 'grade')
        self.assertEqual(grade[:3], ('/opt/grader/v2/checks/workflow_contract.py', 'workflow-babysitter', '/grade/outcome'))

    def test_missing_delegation_needs_a_verified_shim_log(self):
        harness = FakeHarness(self.root)
        summary = startctl.run_start(self.cfg('negative-missing-delegation'), harness, clock=Clock(),
                                     sleep=lambda _s: None)
        up = harness.calls[0][1]
        self.assertTrue(any(arg.endswith('/run/bench-shim/mcp-shim.json:ro') for arg in up.agent_args))
        self.assertFalse(summary['mcp_shim_audit']['verified'])
        self.assertTrue(summary['infrastructure_invalid_candidate'])
        self.assertEqual(summary['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
