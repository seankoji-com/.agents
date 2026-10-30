"""Exercise personal publishing with local Git remotes and fake Codex/SSH."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Maintenance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.remote = self.base / 'author', self.base / 'remote.git'
        tools = self.base / 'tools'
        tools.mkdir()
        environment = patch.dict(os.environ, {
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
            'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
            'PATH': str(tools) + os.pathsep + os.environ['PATH'], 'FIXTURE': str(self.base),
            'TMPDIR': str(self.base),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.call(self.base, 'git', 'init', '-q', '--bare', '--initial-branch=main', str(self.remote))
        self.call(self.base, 'git', 'clone', '-q', str(self.remote), str(self.root))
        (self.root / 'scripts').mkdir()
        (self.root / 'tests').mkdir()
        shutil.copyfile(ROOT / 'scripts/maintain.py', self.root / 'scripts/maintain.py')
        (self.root / 'scripts/check_library.py').write_text(
            'from pathlib import Path\nraise SystemExit(int(Path("fail-check").exists()))\n')
        (self.root / 'tests/test_fixture.py').write_text(
            'import unittest\nclass Fixture(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
        self.call(self.root, 'git', 'add', '.')
        self.call(self.root, 'git', 'commit', '-qm', 'Initial')
        self.call(self.root, 'git', 'push', '-q', 'origin', 'main')
        self.initial = self.call(self.root, 'git', 'rev-parse', 'HEAD')
        for host in ('wsl', 'mint'):
            home = self.base / host
            self.call(self.base, 'git', 'clone', '-q', str(self.remote), str(home / '.agents'))
            registrar = home / '.dotfiles/scripts/t3-workflow-skills.py'
            registrar.parent.mkdir(parents=True)
            registrar.write_text('from pathlib import Path\nimport sys\n'
                                 'with (Path.home()/"actions").open("a") as out: out.write(sys.argv[1]+"\\n")\n')
        for name, body in {
            'codex': 'assert "diff --git" in sys.stdin.read()\n'
                     'with (Path(os.environ["FIXTURE"])/"messages").open("a") as out: out.write("message\\n")\n'
                     'print("Update fixture")\n',
            'ssh': 'home=Path(os.environ["FIXTURE"])/sys.argv[-2]\n'
                   'shell=os.environ.get("FIXTURE_SSH_SHELL", "bash")\n'
                   'shell_args=[shell, "-f", "-c"] if Path(shell).name=="zsh" else [shell, "-c"]\n'
                   'sys.exit(subprocess.call(shell_args+[sys.argv[-1]], env=dict(os.environ, HOME=str(home))))\n',
        }.items():
            command = tools / name
            command.write_text('#!' + sys.executable + '\nimport os, sys, subprocess\nfrom pathlib import Path\n' + body)
            command.chmod(0o755)

    def call(self, cwd, *args, expected=0):
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return (result.stdout + result.stderr).strip()

    def publish(self, expected=0):
        return self.call(self.base, sys.executable, '-B', str(self.root / 'scripts/maintain.py'), expected=expected)

    def log(self, output):
        path = Path(next(line[5:] for line in output.splitlines() if line.startswith('Log: ')))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        return path.read_text()

    def test_rejected_push_retries_without_another_commit_then_updates_both_hosts(self):
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        (self.root / 'new.txt').write_text('edit\n')
        output = self.publish(expected=1)
        self.assertIn('FAIL Push main (exit 1)', output)
        self.assertIn('Log: ', output)
        self.assertIn('git push origin HEAD:refs/heads/main', self.log(output))
        head = self.call(self.root, 'git', 'rev-parse', 'HEAD')
        self.assertNotEqual(head, self.initial)
        self.assertEqual(self.call(self.base, 'git', '--git-dir', str(self.remote), 'rev-parse', 'main'), self.initial)
        hook.unlink()
        self.publish()
        self.assertEqual(self.call(self.root, 'git', 'rev-parse', 'HEAD'), head)
        self.assertEqual((self.base / 'messages').read_text(), 'message\n')
        for host in ('wsl', 'mint'):
            self.assertEqual(self.call(self.base / host / '.agents', 'git', 'rev-parse', 'HEAD'), head)
            self.assertEqual((self.base / host / 'actions').read_text(), 'install\ncheck\n')

    def test_failed_validation_does_not_commit_or_generate_a_message(self):
        (self.root / 'fail-check').touch()
        output = self.publish(expected=1)
        self.assertIn('FAIL Validate local changes (exit 1)', output)
        self.assertIn('Command:', output)
        self.assertEqual(self.call(self.root, 'git', 'rev-parse', 'HEAD'), self.initial)
        self.assertFalse((self.base / 'messages').exists())

    def test_dirty_receiver_is_preserved_and_other_host_still_updates(self):
        dirty = self.base / 'wsl/.agents/local.txt'
        dirty.write_text('local work')
        (self.root / 'new.txt').touch()
        output = self.publish(expected=1)
        self.assertIn('Host updates failed: wsl', output)
        self.assertIn('Published ', output)
        self.assertIn('Receiver has local edits; left untouched', output)
        self.assertIn('OK Update mint', output)
        self.assertIn('FAILED [preflight]', self.log(output))
        self.assertEqual(dirty.read_text(), 'local work')
        self.assertEqual(self.call(dirty.parent, 'git', 'rev-parse', 'HEAD'), self.initial)
        self.assertEqual(self.call(self.base / 'mint/.agents', 'git', 'rev-parse', 'HEAD'),
                         self.call(self.root, 'git', 'rev-parse', 'HEAD'))

    def test_noisy_commands_are_logged_in_full_and_panel_stays_compact(self):
        (self.root / 'scripts/check_library.py').write_text(
            'import sys\nprint("NOISY_STDOUT\\n"*200); print("NOISY_STDERR", file=sys.stderr)\n')
        output = self.publish()
        self.assertNotIn('NOISY_', output)
        self.assertNotIn('Ran 1 test', output)
        self.assertLess(len(output.splitlines()), 30)
        log = self.log(output)
        self.assertGreaterEqual(log.count('NOISY_STDOUT'), 600)  # Author plus both receivers.
        self.assertIn('NOISY_STDERR', log)
        self.assertIn('Ran 1 test', log)
        self.assertIn('Update fixture', log)  # Captured Codex output.
        self.assertIn('Deployment complete.', output)

    def test_discovery_failure_reports_source_success_and_continues_other_host(self):
        registrar = self.base / 'wsl/.dotfiles/scripts/t3-workflow-skills.py'
        registrar.write_text('import sys\nsys.exit("Existing cutover receipt blocks discovery")\n')
        (self.root / 'new.txt').touch()
        output = self.publish(expected=1)
        self.assertIn('FAIL Update wsl', output)
        self.assertIn('discovery refresh; source updated and tests passed', output)
        self.assertIn('Existing cutover receipt blocks discovery', self.log(output))
        self.assertIn('OK Update mint', output)
        self.assertEqual(self.call(self.base / 'wsl/.agents', 'git', 'rev-parse', 'HEAD'),
                         self.call(self.root, 'git', 'rev-parse', 'HEAD'))

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is not installed')
    def test_zsh_receivers_succeed_and_label_discovery_failure(self):
        with patch.dict(os.environ, {'FIXTURE_SSH_SHELL': shutil.which('zsh')}):
            (self.root / 'new.txt').touch()
            self.assertIn('Deployment complete.', self.publish())
            registrar = self.base / 'wsl/.dotfiles/scripts/t3-workflow-skills.py'
            registrar.write_text('import sys\nsys.exit("Synthetic discovery failure")\n')
            output = self.call(self.base, sys.executable, '-B',
                               str(self.root / 'scripts/maintain.py'), 'sync', expected=1)
            self.assertIn('discovery refresh; source updated and tests passed', output)
            self.assertIn('OK Update mint', output)
            self.assertNotIn('read-only variable', self.log(output))

    def test_ssh_timeout_names_host_and_reason_without_script_noise(self):
        script = self.root / 'scripts/maintain.py'
        script.write_text(script.read_text().replace('timeout=300', 'timeout=0.05'))
        (self.base / 'tools/ssh').write_text(
            '#!' + sys.executable + '\nimport time\ntime.sleep(5)\n')
        output = self.publish(expected=1)
        self.assertRegex(output, r'FAIL Update wsl \(timed out after [0-9.]+s\)')
        self.assertIn('Command: ssh wsl', output)
        self.assertRegex(output, r'FAIL Update mint \(timed out after [0-9.]+s\)')
        self.assertRegex(self.log(output), r'Timed out after [0-9.]+s')
        self.assertNotIn('step=preflight', output)

    def test_detached_head_failure_has_command_and_diagnostic(self):
        self.call(self.root, 'git', 'checkout', '--detach', '-q')
        output = self.publish(expected=1)
        self.assertIn('git symbolic-ref --short HEAD', output)
        self.assertIn('not a symbolic ref', output)
        self.assertNotIn('See the failed stage', output)


if __name__ == '__main__':
    unittest.main()
