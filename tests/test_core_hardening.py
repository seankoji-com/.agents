"""Surviving artifact, recipe, snapshot and installer regressions."""
import importlib.util
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from support import ROOT, CoreTestCase, cli, git, native
import test_install
sys.path.insert(0, str(ROOT))
from core import fsutil, recipe, schema, snapshot
from core.errors import InvalidInput
from core.fsutil import sha256_bytes, sha256_file, write_artifact


class ArtifactNameTest(unittest.TestCase):
    def test_traversal_in_name_stays_inside_the_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp)
            run_dir = state_root / 'runs' / 'r1'
            run_dir.mkdir(parents=True)
            receipt = fsutil.write_artifact(run_dir, 'results', '../../../escaped-r1-raw.txt', b'x')
            written = run_dir / receipt['path']
            self.assertTrue(written.is_file())
            self.assertTrue(written.resolve().is_relative_to((run_dir / 'artifacts' / 'results').resolve()))
            self.assertEqual(list(state_root.glob('escaped*')), [])
            self.assertNotIn('/', receipt['path'].split('artifacts/results/', 1)[1])

    def test_stem_is_one_safe_component(self):
        self.assertNotIn('/', fsutil.artifact_stem('../../x'))
        self.assertFalse(fsutil.artifact_stem('../../x').startswith('.'))
        self.assertFalse(fsutil.artifact_stem('..').startswith('.'))
        self.assertEqual(fsutil.artifact_stem(''), 'artifact')
        self.assertLessEqual(len(fsutil.artifact_stem('a' * 500)), 80)


class PorcelainRenameTest(unittest.TestCase):
    def test_worktree_column_rename_skips_its_source(self):
        # porcelain v1 -z: ` R` (renamed in the work tree, after `git add -N`) is
        # followed by the source path, exactly like an index rename.
        from unittest import mock
        out = b' R new.txt\0old.txt\0 C copy.txt\0orig.txt\0?? other.txt\0'
        fake = mock.Mock(returncode=0, stdout=out, stderr=b'')
        with mock.patch.object(snapshot.subprocess, 'run', return_value=fake):
            entries = list(snapshot._porcelain(Path('.')))
        self.assertEqual(entries, [(' R', 'new.txt'), (' C', 'copy.txt'), ('??', 'other.txt')])

    def test_rename_source_is_skipped_not_hashed_as_a_path(self):
        import os
        import subprocess
        env = {**os.environ, 'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
               'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                subprocess.run(['git', '-C', tmp, *args], check=True, capture_output=True, env=env)

            git('init', '-q')
            (root / 'old.txt').write_text('same content\n')
            git('add', 'old.txt')
            git('commit', '-q', '-m', 'one')
            git('mv', 'old.txt', 'new.txt')
            (root / 'other.txt').write_text('untracked\n')
            paths = sorted(path for _, path in snapshot._porcelain(root))
        self.assertEqual(paths, ['new.txt', 'other.txt'])
