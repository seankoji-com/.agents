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
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}  # a global hooksPath or gpgsign must not break fixtures


def source_entry(plugin):
    """Canonical source body; old fixture/retired packages retain their layout."""
    canonical = ROOT/'skills'/Path(plugin).name/'SKILL.md'
    return canonical if canonical.is_file() else Path(plugin)/'entry.md'


def skill_manifest(path):
    sys.path.insert(0,str(ROOT/'scripts'))
    from manifest_data import load
    return load(path)


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


class Run:
    """Exercise the public evidence API without simulating a dispatcher."""

    def __init__(self, test, state_root, run_id, parent=PARENT):
        self.test, self.state_root, self.run_id, self.parent = test, Path(state_root), run_id, parent

    def args(self, *extra):
        return ['--state-root', self.state_root, '--run-id', self.run_id, '--plugin-dir', PLUGIN, *extra]

    @property
    def run_dir(self):
        return self.state_root / 'runs' / self.run_id

    @property
    def state(self):
        return json.loads((self.run_dir / 'run.json').read_text())

    def status(self):
        code, env, _ = cli('status', *self.args())
        self.test.assertEqual(code, 0, env)
        return env['data']

    def binding(self):
        code, env, _ = cli('snapshot', *self.args())
        self.test.assertEqual(code, 0, env)
        return env['data']

    def submit_raw(self, kind, payload):
        return cli(kind, *self.args('--json', json.dumps(payload)))

    def submit(self, kind, payload, expect=0):
        code, env, _ = self.submit_raw(kind, payload)
        self.test.assertEqual(code, expect, env)
        return env.get('data', env.get('error'))

    def evidence(self, requirement_id, path, kind='command', status='passed', **extra):
        return self.submit('evidence', dict(requirement_id=requirement_id, status=status, kind=kind,
                                         explanation='observed result', artifacts=[str(path)],
                                         binding=self.binding(), **extra))

    def child(self, task_id='task-1', status='completed', pending=False, **extra):
        return self.submit('child', dict(task_id=task_id, client_request_id='request-' + task_id,
                                       parent_thread_id=self.parent, status=status,
                                       has_pending_child_runs=pending, **extra))

    def scratch(self, name, text):
        path = self.run_dir / 'scratch' / name
        path.write_text(text)
        return path

    def validate(self):
        code, env, _ = cli('validate', *self.args())
        self.test.assertEqual(code, 0, env)
        return env['data']


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        # Resolved: on macOS TMPDIR is under /var, a symlink to /private/var, and the core records real paths.
        self.tmp = Path(tempfile.mkdtemp(prefix='t3p-test-')).resolve()
        self.state_root = self.tmp / 'state'
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_repo(self, fixture='bugfix-cli', name='repo'):
        repo, counter = self.tmp / name, 1
        while repo.exists():
            counter += 1
            repo = self.tmp / f'{name}{counter}'
        shutil.copytree(FIXTURES / fixture, repo, ignore=shutil.ignore_patterns('__pycache__', '.claude', '.mcp.json'))
        git(repo, 'init', '-q', '-b', 'main')
        # Checks run Python inside the fixture. GIT_CONFIG_GLOBAL hides the developer's
        # global excludes, so ignore bytecode here rather than rely on them (CI also
        # sets PYTHONDONTWRITEBYTECODE).
        (repo / '.git' / 'info' / 'exclude').write_text('__pycache__/\n')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-q', '-m', 'fixture')
        return repo

    def plan(self, repo, **overrides):
        plan = {
            'schema_version': 2,
            'brief': {'text': 'wordstat count is wrong for multi-line files',
                      'requirements': [{'id': 'REQ-MULTILINE', 'text': 'count splits on any whitespace', 'kind': 'command'}],
                      'constraints': ['Do not change the CLI usage text.']},
            'repo': {'worktree': str(repo), 'base_ref': 'HEAD'},
            'authorization': {'endstate': 'local', 'local': ['edit', 'commit'], 'evidence': 'test'},
            'host': {'parent_thread_id': PARENT, 'provider_instance_id': 'claudeAgent', 'model': 'claude-opus-5-5'},
            'policy': {'checks': [{'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
                                   'cwd': str(repo)}],
                       'review': {'required': False, 'role': 'reviewer'},
},
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

    def run_check(self, run, check=None):
        check = check or run.state['policy']['checks'][0]
        binding = run.binding()
        cwd = Path(check.get('cwd') or run.state['repo']['worktree'])
        if not cwd.is_absolute():
            cwd = Path(run.state['repo']['worktree']) / cwd
        result = subprocess.run(check['argv'], cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
        log = run.scratch(check['name'] + '.log', result.stdout + result.stderr)
        return run.submit('check', {'name': check['name'], 'argv': check['argv'], 'cwd': str(cwd),
                                    'exit_code': result.returncode, 'log': str(log), 'binding': binding})
