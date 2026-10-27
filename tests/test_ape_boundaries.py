"""Research helpers reject unsafe targets before cloning or deleting anything."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/ape/scripts'


class ResearchBoundaryTest(unittest.TestCase):
    def test_clone_requires_owned_workspace_and_regular_repos_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {**os.environ, 'HOME': tmp}
            tools = root / 'bin'
            tools.mkdir()
            (tools / 'git').write_text('#!/bin/sh\nprintf "called" >> "$HOME/git-called"\n')
            (tools / 'git').chmod(0o755)
            env['PATH'] = f'{tools}:{env["PATH"]}'
            owned = root / 'tmp/repo-research/owned'
            outside = root / 'outside'
            unmarked = root / 'tmp/repo-research/unmarked'
            unmarked.mkdir(parents=True)
            def clone(path):
                return subprocess.run(['bash', str(SCRIPTS / 'clone-candidates.sh'), str(path),
                                       'https://github.com/example/project', 'project', '0'],
                                      env=env, capture_output=True, text=True, timeout=5)
            for path in (outside, unmarked):
                self.assertNotEqual(clone(path).returncode, 0)
                self.assertFalse((path / 'repos').exists())
            subprocess.run(['python3', str(SCRIPTS / 'workspace.py'), 'init', str(owned)],
                           env=env, check=True, capture_output=True, timeout=5)
            outside.mkdir()
            (owned / 'repos').symlink_to(outside, target_is_directory=True)
            self.assertNotEqual(clone(owned).returncode, 0)
            self.assertFalse((root / 'git-called').exists())
            (owned / 'repos').unlink()
            self.assertEqual(clone(owned).returncode, 0)
            self.assertEqual((root / 'git-called').read_text(), 'called')

    def test_cleanup_rejects_unknown_flags_and_extra_paths_before_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args in ([tmp, '--al', '--confirm'], [tmp, tmp, '--all', '--confirm']):
                result = subprocess.run(['bash', str(SCRIPTS / 'clean-ape-workspace.sh'), *args],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertTrue(Path(tmp).is_dir())

    def test_triage_marks_failures_and_continues_and_readme_is_fail_soft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gh = root / 'gh'
            gh.write_text('#!/bin/sh\nif [ "$1" = api ]; then [ "$3" = "Accept: application/vnd.github.raw" ] || exit 9; cat "$HOME/readme.txt"; exit 0; fi\nif [ "$3" = bad/repo ]; then echo "not found" >&2; exit 1; fi\necho "{}"\n')
            gh.chmod(0o755)
            env = {**os.environ, 'HOME': tmp, 'PATH': f'{root}:{os.environ["PATH"]}'}
            def run(script, *args):
                return subprocess.run(['bash', str(SCRIPTS / script), *args], env=env,
                                      capture_output=True, text=True, timeout=5)
            self.assertEqual(run('triage-repos.sh').returncode, 2)
            result = run('triage-repos.sh', 'bad/repo', 'good/repo')
            self.assertEqual(result.returncode, 1)
            self.assertIn('=== bad/repo === (FAILED)', result.stdout)
            self.assertIn('=== good/repo ===\n{}', result.stdout)
            (root / 'readme.txt').write_text('line\n' * 100000)
            result = run('readme-peek.sh', 'good/repo')
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.splitlines(), ['line'] * 40)
            (root / 'readme.txt').unlink()
            self.assertEqual(run('readme-peek.sh', 'good/repo').returncode, 0)

    def test_cleanup_refuses_unmarked_or_copied_marker_inside_allowed_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'tmp/repo-research/unrelated'
            workspace.mkdir(parents=True)
            keep = workspace / 'keep.txt'
            keep.write_text('unrelated research')
            env = {**os.environ, 'HOME': tmp}
            for marker in (None, {'schema_version': 1, 'owner': 'agents/ape', 'workspace': str(workspace.parent / 'other')}):
                if marker:
                    (workspace / '.ape-workspace.json').write_text(json.dumps(marker))
                result = subprocess.run(['bash', str(SCRIPTS / 'clean-ape-workspace.sh'), str(workspace), '--all', '--confirm'],
                                        env=env, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(keep.read_text(), 'unrelated research')

    def test_pre_198_workspace_marker_still_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve() / 'tmp/repo-research/old'
            workspace.mkdir(parents=True)
            marker = {'schema_version': 1, 'owner': 't3-plugins/ape', 'workspace': str(workspace)}
            (workspace / '.ape-workspace.json').write_text(json.dumps(marker))
            result = subprocess.run([sys.executable, str(SCRIPTS / 'workspace.py'), 'validate', str(workspace)],
                                    env={**os.environ, 'HOME': str(Path(tmp).resolve())},
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((workspace / '.ape-workspace.json').read_text()), marker)

    def test_initializer_does_not_adopt_unmarked_workspaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'
            project.mkdir()
            workspace = Path(tmp) / 'tmp/repo-research/project'
            workspace.mkdir(parents=True)
            result = subprocess.run(['bash', str(SCRIPTS / 'init-workspace.sh')], cwd=project,
                                    env={**os.environ, 'HOME': tmp}, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(workspace.iterdir()), [])

    def test_dot_clone_names_fail_before_any_workspace_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'absent'
            for name in ('.', '..'):
                result = subprocess.run(['bash', str(SCRIPTS / 'clone-candidates.sh'), str(workspace),
                                         'https://github.com/example/project', name, '0'],
                                        capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(workspace.exists())

    def test_study_rejects_non_github_and_traversal_urls(self):
        for url in ('file:///tmp/project', 'https://github.com/a/b/tree/main/../secret',
                    'https://github.com/a/b?token=fixture', 'https://github.com/a/b/tree/-option'):
            result = subprocess.run(['bash', str(SCRIPTS / 'study-repo.sh'), url], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0, url)
            self.assertIn('study-repo:', result.stderr)

    def test_clone_batch_validates_every_candidate_before_creating_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'not-created'
            result = subprocess.run(['bash', str(SCRIPTS / 'clone-candidates.sh'), str(workspace),
                                     'https://github.com/example/project', 'valid', '0',
                                     'file:///tmp/unsafe', 'invalid', '0'], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(workspace.exists())

    def test_cleanup_refuses_an_unowned_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'keep.txt'
            marker.write_text('keep')
            result = subprocess.run(['bash', str(SCRIPTS / 'clean-ape-workspace.sh'), tmp, '--all', '--confirm'],
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), 'keep')
