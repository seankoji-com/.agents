"""Publishing and receiver safety using local remotes, never models or GitHub."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('maintain', ROOT / 'scripts/maintain.py')
maintain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintain)


class Maintenance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'author'
        self.remote = self.base / 'remote.git'
        environment = patch.dict(os.environ, {
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
            'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.call(['git', 'init', '-q', '--bare', '--initial-branch=main', str(self.remote)])
        self.call(['git', 'clone', '-q', str(self.remote), str(self.root)])
        (self.root / 'scripts').mkdir()
        (self.root / 'tests').mkdir()
        shutil.copyfile(ROOT / 'scripts/maintain.py', self.root / 'scripts/maintain.py')
        (self.root / 'scripts/check_library.py').write_text(
            'from pathlib import Path\nraise SystemExit(int(Path("fail-check").exists()))\n')
        (self.root / 'tests/test_fixture.py').write_text(
            'import unittest\nclass Fixture(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
        (self.root / '.gitignore').write_text('.maintain.json\n__pycache__/\n')
        (self.root / 'edit.txt').write_text('before\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Initial')
        self.git('push', '-q', 'origin', 'main')
        self.initial = self.git('rev-parse', 'HEAD')
        self.settings = {'message_command': [sys.executable, '-c',
                         'import sys; assert "diff --git" in sys.stdin.read(); print("Update fixture")'],
                         'hosts': []}
        self.save_config()

    def call(self, argv, cwd=None, **kwargs):
        result = subprocess.run(argv, cwd=cwd or self.base, capture_output=True, text=True, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def git(self, *args):
        return self.call(['git', *args], cwd=self.root)

    def save_config(self):
        (self.root / '.maintain.json').write_text(json.dumps(self.settings))

    def command(self, name, expected=0):
        # The copied script selects its own checkout even from a foreign cwd.
        result = subprocess.run([sys.executable, '-B', str(self.root / 'scripts/maintain.py'), name],
                                cwd=self.base, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def edit(self):
        (self.root / 'edit.txt').write_text('after\n')

    def receiver(self):
        root = self.base / 'receiver with spaces'
        self.call(['git', 'clone', '-q', str(self.remote), str(root)])
        return root

    def receive(self, root, expected, code=0, refresh=False, env=None):
        result = subprocess.run([sys.executable, '-c', maintain.RECEIVE, str(root), expected, str(self.remote),
                                 str(refresh).lower()], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_publish_relocated_includes_new_deleted_files_and_hook(self):
        self.command('install-hook')
        self.call(['bash', '-n', str(self.root / '.git/hooks/pre-commit')])
        self.command('install-hook', 1)
        (self.root / 'edit.txt').unlink()
        (self.root / 'new.txt').write_text('new\n')
        self.command('publish')
        head = self.git('rev-parse', 'HEAD')
        self.assertNotEqual(head, self.initial)
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'Update fixture')
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.git('ls-remote', 'origin', 'refs/heads/main').split()[0], head)
        self.assertFalse((self.root / 'edit.txt').exists())
        self.assertEqual(self.git('show', 'HEAD:new.txt'), 'new')

    def test_failed_validation_and_ai_do_not_commit_or_push(self):
        self.edit()
        (self.root / 'fail-check').touch()
        self.command('publish', 1)
        self.assertEqual(self.git('diff', '--cached'), '')
        (self.root / 'fail-check').unlink()
        self.settings['message_command'] = [sys.executable, '-c', 'raise SystemExit(1)']
        self.save_config()
        self.command('publish', 1)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.initial)
        self.assertEqual(self.git('ls-remote', 'origin', 'refs/heads/main').split()[0], self.initial)

    def test_ai_edit_is_detected(self):
        self.edit()
        self.settings['message_command'] = [sys.executable, '-c',
            'from pathlib import Path; Path("edit.txt").write_text("unexpected"); print("Message")']
        self.save_config()
        self.assertIn('changed during message generation', self.command('publish', 1))
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.initial)

    def test_check_side_effect_stops_before_staging(self):
        self.edit()
        (self.root / 'scripts/check_library.py').write_text(
            'from pathlib import Path\nPath("edit.txt").write_text("changed during checks")\n')
        self.assertIn('changed during checks', self.command('publish', 1))
        self.assertEqual(self.git('diff', '--cached'), '')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.initial)

    def test_rejected_push_retains_commit_and_can_retry_without_ai(self):
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        self.edit()
        self.command('publish', 1)
        committed = self.git('rev-parse', 'HEAD')
        self.assertNotEqual(committed, self.initial)
        self.assertEqual(self.git('ls-remote', 'origin', 'refs/heads/main').split()[0], self.initial)
        hook.unlink()
        self.settings['message_command'] = [sys.executable, '-c', 'raise SystemExit(1)']
        self.save_config()
        self.command('publish')
        self.assertEqual(self.git('rev-parse', 'HEAD'), committed)

    def test_receiver_updates_exact_commit_and_rejects_dirty_wrong_origin_or_ahead(self):
        receiver = self.receiver()
        self.edit()
        self.command('publish')
        head = self.git('rev-parse', 'HEAD')
        (receiver / 'local.txt').touch()
        self.assertIn('local edits', self.receive(receiver, head, 1))
        (receiver / 'local.txt').unlink()
        self.receive(receiver, head)
        self.assertEqual(self.call(['git', 'rev-parse', 'HEAD'], cwd=receiver), head)
        self.call(['git', 'remote', 'set-url', 'origin', str(self.base / 'other.git')], cwd=receiver)
        self.assertIn('origin differs', self.receive(receiver, head, 1))
        self.call(['git', 'remote', 'set-url', 'origin', str(self.remote)], cwd=receiver)
        self.call(['git', 'commit', '--allow-empty', '-qm', 'Local only'], cwd=receiver)
        ahead = self.call(['git', 'rev-parse', 'HEAD'], cwd=receiver)
        self.assertIn('ahead', self.receive(receiver, head, 1))
        self.assertEqual(self.call(['git', 'rev-parse', 'HEAD'], cwd=receiver), ahead)

    def test_sync_attempts_other_hosts_after_failure_and_quotes_paths(self):
        self.settings['hosts'] = [{'ssh': 'fixture-one', 'path': '/srv/synthetic checkout'},
                                  {'ssh': 'fixture-two', 'path': '/srv/other;literal'}]
        original = maintain.run
        calls = []
        def fake(root, argv, **kwargs):
            if argv[0] == 'ssh':
                calls.append(argv)
                if len(calls) == 1:
                    raise subprocess.CalledProcessError(1, argv)
                return b''
            return original(root, argv, **kwargs)
        with patch.object(maintain, 'run', side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(maintain.MaintenanceError, 'fixture-one'):
                maintain.sync(self.root, self.settings)
        self.assertEqual(len(calls), 2)
        self.assertIn("'/srv/other;literal'", calls[1][-1])

    def test_behind_branch_and_partial_staging_refused(self):
        receiver = self.receiver()
        self.call(['git', 'commit', '--allow-empty', '-qm', 'Remote change'], cwd=receiver)
        self.call(['git', 'push', '-q', 'origin', 'main'], cwd=receiver)
        self.edit()
        self.command('publish', 1)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.initial)
        self.command('hook', 1)

    def test_hook_refuses_untracked_inputs_and_preserves_custom_hooks(self):
        (self.root / 'new.txt').touch()
        self.command('hook', 1)
        self.git('config', 'core.hooksPath', 'custom-hooks')
        self.assertIn('custom hooksPath', self.command('install-hook', 1))
        self.assertFalse((self.root / 'custom-hooks').exists())
        with contextlib.redirect_stdout(io.StringIO()):
            maintain.install_hook(self.root, forwarded=True)
        self.assertTrue((self.root / '.git/hooks/pre-commit').is_file())
        self.assertEqual(self.git('config', '--get', 'core.hooksPath'), 'custom-hooks')

    def test_default_codex_runs_outside_checkout_without_live_model(self):
        tools = self.base / 'tools'
        tools.mkdir()
        command = tools / 'codex'
        command.write_text('#!' + sys.executable + '\nimport pathlib, sys\n'
                           'assert not (pathlib.Path.cwd() / "scripts/maintain.py").exists()\n'
                           'assert "diff --git" in sys.stdin.read()\n'
                           'print("Synthetic prompt echo", file=sys.stderr)\nprint("Default CLI message")\n')
        command.chmod(0o755)
        self.settings['message_command'] = []
        self.save_config()
        self.edit()
        with patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}):
            output = self.command('publish')
        self.assertNotIn('Synthetic prompt echo', output)
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'Default CLI message')

    def test_receiver_refreshes_native_discovery_through_dotfiles(self):
        home = self.base / 'synthetic home'
        home.mkdir()
        receiver = home / '.agents'
        self.call(['git', 'clone', '-q', str(self.remote), str(receiver)])
        registrar = home / '.dotfiles/scripts/t3-workflow-skills.py'
        registrar.parent.mkdir(parents=True)
        registrar.write_text('from pathlib import Path\nimport sys\n'
                             'with (Path.home()/"actions").open("a") as out: out.write(sys.argv[1]+"\\n")\n')
        self.receive(receiver, self.initial, refresh=True, env=dict(os.environ, HOME=str(home)))
        self.assertEqual((home / 'actions').read_text().splitlines(), ['install', 'check'])


if __name__ == '__main__':
    unittest.main()
