"""Research helpers reject unsafe targets before cloning or deleting anything."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/ape/scripts'


class ResearchBoundaryTest(unittest.TestCase):
    def test_cleanup_refuses_unmarked_or_copied_marker_inside_allowed_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'tmp/repo-research/unrelated'
            workspace.mkdir(parents=True)
            keep = workspace / 'keep.txt'
            keep.write_text('unrelated research')
            env = {**os.environ, 'HOME': tmp}
            for marker in (None, {'schema_version': 1, 'owner': 't3-plugins/ape', 'workspace': str(workspace.parent / 'other')}):
                if marker:
                    (workspace / '.ape-workspace.json').write_text(json.dumps(marker))
                result = subprocess.run(['bash', str(SCRIPTS / 'clean-ape-workspace.sh'), str(workspace), '--all', '--confirm'],
                                        env=env, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(keep.read_text(), 'unrelated research')

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
