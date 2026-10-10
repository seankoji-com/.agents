"""Shared test helpers: run the core CLI, build fixture repositories and script
T3 orchestration responses. No network, credentials or model calls."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / 'core' / 'cli.py'
PLUGIN = ROOT / 'plugins' / 'imps'
FIXTURES = ROOT / 'tests' / 'fixtures'
PARENT = 'thread-parent-0001'
TIMEOUT = 120  # seconds; a hung child process fails the test instead of the suite

GIT_ENV = {'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
           'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
           'GIT_CONFIG_NOSYSTEM': '1'}


def git(cwd, *args, check=True):
    env = dict(os.environ, **GIT_ENV)
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, check=check, env=env,
                          timeout=TIMEOUT)


def native(argv, check=False):
    """Run an argv returned by next, as a native foreground tool would."""
    return subprocess.run(argv, capture_output=True, text=True, check=check, env=dict(os.environ, **GIT_ENV),
                          timeout=TIMEOUT)


def cli(*args, stdin=None, env=None):
    """Run the core CLI; return (exit_code, envelope, stderr)."""
    merged = dict(os.environ, **(env or {}))
    merged.pop('T3_PARENT_THREAD_ID', None)
    result = subprocess.run([sys.executable, str(CLI), *map(str, args)], input=stdin, capture_output=True,
                            text=True, env=merged, timeout=TIMEOUT)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f'expected one JSON line on stdout, got {result.stdout!r} / {result.stderr!r}'
    return result.returncode, json.loads(lines[0]), result.stderr


def capabilities(**overrides):
    data = json.loads((FIXTURES / 't3' / 'capabilities.json').read_text())
    data = copy.deepcopy(data)
    data.update(overrides)
    return data


class FakeT3:
    """Scripted T3 orchestration. Dispatch is idempotent on clientRequestId, like T3."""

    def __init__(self):
        self.tasks = {}
        self.calls = []
        self.scripts = {}

    def script(self, client_request_id, *responses):
        self.scripts[client_request_id] = list(responses)

    def call(self, host_call):
        tool, arguments = host_call['tool'], host_call['arguments']
        self.calls.append((tool, copy.deepcopy(arguments)))
        if tool == 'delegate_task':
            request = arguments['clientRequestId']
            task_id = 'task:' + request
            if task_id not in self.tasks:
                self.tasks[task_id] = {'request': request, 'arguments': arguments, 'queue': list(self.scripts.get(request, [])),
                                       'state': {'status': 'running', 'workState': 'working', 'summary': None}}
            return self._response(task_id)
        if tool == 'task_status':
            task = self.tasks[arguments['taskId']]
            if task['queue']:
                task['state'] = task['queue'].pop(0)
            return self._response(arguments['taskId'])
        if tool == 'task_cancel':
            task = self.tasks[arguments['taskId']]
            return {'taskId': arguments['taskId'], 'status': task.get('cancel_reply', 'cancel_requested')}
        raise AssertionError(f'unexpected tool {tool}')

    def _response(self, task_id):
        state = self.tasks[task_id]['state']
        return {'taskId': task_id, 'childThreadId': 'child:' + task_id, 'status': state['status'],
                'workState': state['workState'], 'hasPendingChildRuns': state.get('hasPendingChildRuns', False),
                'summary': state.get('summary'), 'waitTimedOut': state.get('waitTimedOut', False)}

    def dispatches(self):
        return [args for tool, args in self.calls if tool == 'delegate_task']


def done(summary):
    return {'status': 'completed', 'workState': 'result_available', 'summary': summary}


def result_block(task_id, **fields):
    body = {'schema_version': 1, 'task_id': task_id, 'status': 'done', 'changed_files': [], 'commit': None,
            'requirements': [], 'verification': [], 'findings': [], 'blockers': []}
    body.update(fields)
    return 'Work finished.\n\n```json t3-result\n' + json.dumps(body, indent=2) + '\n```'


class Run:
    """Drives one run through the CLI the way an agent following entry.md would."""

    def __init__(self, test, state_root, run_id, parent=PARENT):
        self.test, self.state_root, self.run_id, self.parent = test, Path(state_root), run_id, parent
        self.token = None

    def args(self, *extra):
        return ['--state-root', self.state_root, '--run-id', self.run_id, '--plugin-dir', PLUGIN, *extra]

    def status(self):
        code, env, _ = cli('status', *self.args())
        self.test.assertEqual(code, 0, env)
        return env['data']

    @property
    def generation(self):
        return self.status()['generation']

    @property
    def state(self):
        return json.loads((self.state_root / 'runs' / self.run_id / 'run.json').read_text())

    @property
    def run_dir(self):
        return self.state_root / 'runs' / self.run_id

    def claim(self):
        code, env, _ = cli('claim', *self.args('--parent-thread-id', self.parent))
        self.test.assertEqual(code, 0, env)
        self.token = env['data']['token']
        return env

    def release(self):
        code, env, _ = cli('release', *self.args('--token', self.token))
        self.test.assertEqual(code, 0, env)
        self.token = None

    def next(self, parent=None):
        code, env, _ = cli('next', *self.args('--parent-thread-id', parent or self.parent))
        self.test.assertEqual(code, 0, env)
        return env['data']

    def snapshot_token(self):
        code, env, _ = cli('validate', *self.args())
        snap = env['data']['binding']['snapshot']
        return f'{snap["head"]}:{snap["content_hash"]}'

    def record_raw(self, kind, payload, parent=None, token=None, generation=None):
        if kind in ('check', 'acceptance') and 'snapshot' not in payload:
            # An agent echoes the snapshot token from the next action that asked for the evidence.
            payload = dict(payload, snapshot=self.snapshot_token())
        return cli('record', *self.args('--kind', kind, '--token', token or self.token or '',
                                        '--expect-generation', generation if generation is not None else self.generation,
                                        '--parent-thread-id', parent or self.parent, '--json', json.dumps(payload)))

    def record(self, kind, payload, expect=0, **kwargs):
        code, env, _ = self.record_raw(kind, payload, **kwargs)
        self.test.assertEqual(code, expect, env)
        return env.get('data', env.get('error'))

    def scratch(self, name, text):
        path = self.run_dir / 'scratch' / name
        path.write_text(text)
        return path

    def only(self, wanted):
        data = self.next()
        actions = [a for a in data['actions'] if a['action'] == wanted]
        self.test.assertTrue(actions, f'expected {wanted}, got {[a["action"] for a in data["actions"]]} '
                                      f'blocked={data.get("blocked")}')
        return actions[0]


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='t3p-test-'))
        self.state_root = self.tmp / 'state'
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_repo(self, fixture='bugfix-cli', name='repo'):
        repo, counter = self.tmp / name, 1
        while repo.exists():
            counter += 1
            repo = self.tmp / f'{name}{counter}'
        shutil.copytree(FIXTURES / fixture, repo, ignore=shutil.ignore_patterns('__pycache__', '.claude', '.mcp.json'))
        git(repo, 'init', '-q', '-b', 'main')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-q', '-m', 'fixture')
        return repo

    def plan(self, repo, **overrides):
        plan = {
            'schema_version': 1,
            'brief': {'text': 'wordstat count is wrong for multi-line files',
                      'requirements': [{'id': 'REQ-MULTILINE', 'text': 'count splits on any whitespace', 'kind': 'command'}],
                      'constraints': ['Do not change the CLI usage text.']},
            'repo': {'worktree': str(repo), 'base_ref': 'HEAD'},
            'authorization': {'endstate': 'local', 'local': ['edit', 'commit'], 'evidence': 'test'},
            'host': {'parent_thread_id': PARENT, 'provider_instance_id': 'claudeAgent', 'model': 'claude-opus-5-5'},
            'policy': {'checks': [{'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
                                   'cwd': str(repo)}],
                       'review': {'required': False, 'role': 'reviewer'},
                       'worktree_root': str(self.tmp / 'worktrees')},
        }
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(plan.get(key), dict):
                plan[key] = dict(plan[key], **value)
            else:
                plan[key] = value
        return plan

    def init(self, plan, expect=0):
        code, env, _ = cli('init', '--state-root', self.state_root, '--plugin-dir', PLUGIN, '--json', json.dumps(plan))
        self.assertEqual(code, expect, env)
        if code:
            return env
        run = Run(self, self.state_root, env['run_id'])
        return run

    def write(self, name, text):
        path = self.tmp / name
        path.write_text(text)
        return path

    def run_check(self, run, action):
        """Execute a planned check the way a native foreground tool would."""
        args = action['args']
        result = subprocess.run(args['argv'], cwd=args['cwd'], capture_output=True, text=True, timeout=TIMEOUT)
        log = Path(args['log_path'])
        log.write_text(result.stdout + result.stderr)
        return run.record('check', {'name': args['name'], 'argv': args['argv'], 'cwd': args['cwd'],
                                    'exit_code': result.returncode, 'log': str(log), 'snapshot': args['snapshot']})
