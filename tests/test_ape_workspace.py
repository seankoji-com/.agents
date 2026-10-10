"""The actual initializer allocates empty report directories without deleting research."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/ape/scripts/init-workspace.sh'


class WorkspaceTest(unittest.TestCase):
    def test_each_run_has_an_empty_report_directory_and_preserves_previous_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            env = {**os.environ, 'HOME': directory}
            def initialize():
                result = subprocess.run(['bash', str(SCRIPT)], cwd=project, env=env,
                                        capture_output=True, text=True, check=True, timeout=5)
                fingerprint = Path(next(line.split('=', 1)[1] for line in result.stdout.splitlines() if line.startswith('fingerprint=')))
                self.assertEqual(fingerprint, root / 'tmp/repo-research/project/fingerprint.md')
                return Path(next(line.split('=', 1)[1] for line in result.stdout.splitlines()
                                 if line.startswith('reports=')))
            first = initialize()
            old = first / 'org__repo.md'
            old.write_text('previous expedition')
            second = initialize()
            self.assertNotEqual(first, second)
            self.assertEqual(list(second.iterdir()), [])
            self.assertEqual(old.read_text(), 'previous expedition')
            workspace = first.parent.parent
            (workspace / 'repos').mkdir()
            (workspace / 'repos/clone.txt').write_text('clone')
            subprocess.run(['bash', str(SCRIPT.with_name('clean-ape-workspace.sh')),
                            str(workspace), '--confirm'], env=env,
                           capture_output=True, text=True, check=True, timeout=5)
            self.assertFalse((workspace / 'repos').exists())
            self.assertEqual(old.read_text(), 'previous expedition')
            self.assertTrue(second.is_dir())
            subprocess.run(['bash', str(SCRIPT.with_name('clean-ape-workspace.sh')),
                            str(workspace), '--all', '--confirm'], env=env,
                           capture_output=True, text=True, check=True, timeout=5)
            self.assertFalse(workspace.exists())

    def test_study_and_forage_share_fingerprint_from_project_subdirectories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, project = root / 'source', root / 'project'
            env = {**os.environ, 'HOME': directory, 'GIT_CONFIG_NOSYSTEM': '1',
                   'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0'}
            def git(*args):
                return subprocess.run(['git', *map(str, args)], env=env,
                                      capture_output=True, text=True, check=True, timeout=10)
            git('init', source)
            (source / 'README.md').write_text('fixture source')
            git('-C', source, 'add', 'README.md')
            git('-C', source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture')
            git('init', project)
            git('-C', project, 'remote', 'add', 'origin', 'https://github.com/owner/project.git')
            nested = project / 'nested'
            nested.mkdir()
            env.update({'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': f'url.{source.as_uri()}.insteadOf',
                        'GIT_CONFIG_VALUE_0': 'https://github.com/example/source'})
            def helper(name, *args):
                result = subprocess.run(['bash', str(SCRIPT.with_name(name)), *args], cwd=nested, env=env,
                                        capture_output=True, text=True, check=True, timeout=15)
                return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            forage = helper('init-workspace.sh')
            fingerprint = Path(forage['fingerprint'])
            fingerprint.write_text('reviewed fingerprint')
            study = helper('study-repo.sh', 'https://github.com/example/source')
            self.assertEqual(Path(study['fingerprint_path']), fingerprint)
            self.assertEqual(study['fingerprint_fresh'], 'true')
            self.assertEqual(fingerprint.read_text(), 'reviewed fingerprint')
            self.assertTrue((Path(study['repo_path']) / 'README.md').is_file())
