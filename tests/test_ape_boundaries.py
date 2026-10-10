"""Research helpers reject unsafe targets before cloning or deleting anything."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/ape/scripts'


class ResearchBoundaryTest(unittest.TestCase):
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
