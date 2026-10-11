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


class InstallerFindingsTest(test_install.InstallTest):
    def test_install_lifecycle(self):
        pass  # covered by test_install.InstallTest

    def test_new_version_and_rollback(self):
        pass  # covered by test_install.InstallTest

    def test_12_manifest_paths_cannot_escape_the_version_directory(self):
        first = self.installer()['data']
        victim = self.home / '.local' / 'state' / 't3-plugins' / 'imps' / 'runs' / 'evidence.log'
        victim.parent.mkdir(parents=True)
        victim.write_text('run evidence')
        manifest_path = Path(first['version_dir']) / 'install-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        import hashlib
        manifest['files'].append({'path': str(victim), 'sha256': hashlib.sha256(b'run evidence').hexdigest(), 'mode': 420})
        manifest_path.write_text(json.dumps(manifest))
        out = self.installer('--uninstall', expect=2)
        self.assertEqual(out['error']['code'], 'manifest_path_escape')
        self.assertEqual(victim.read_text(), 'run evidence')

    def test_13_modified_files_stay_owned_after_uninstall(self):
        first = self.installer()['data']
        entry = Path(first['version_dir']) / 'entry.md'
        entry.write_text('my edits\n')
        out = self.installer('--uninstall')['data']
        self.assertEqual(out['kept_modified'], [str(entry)])
        self.assertEqual(entry.read_text(), 'my edits\n')
        refused = self.installer(expect=4)
        self.assertEqual(refused['error']['code'], 'locally_modified')
        self.assertEqual(entry.read_text(), 'my edits\n')


class Round2InstallerTest(test_install.InstallTest):
    def test_install_lifecycle(self):
        pass  # covered by test_install.InstallTest

    def test_new_version_and_rollback(self):
        pass  # covered by test_install.InstallTest

    def test_f_symlinked_version_directory_is_refused(self):
        first = self.installer()['data']
        version_dir = Path(first['version_dir'])
        elsewhere = self.tmp / 'elsewhere'
        shutil.move(str(version_dir), elsewhere)
        os.symlink(elsewhere, version_dir)
        out = self.installer('--uninstall', expect=2)
        self.assertEqual(out['error']['code'], 'manifest_path_escape')
        self.assertTrue((elsewhere / 'entry.md').is_file(), 'nothing outside the prefix was deleted')


class Round3InstallerTest(test_install.InstallTest):
    def test_install_lifecycle(self):
        pass  # covered by test_install.InstallTest

    def test_new_version_and_rollback(self):
        pass  # covered by test_install.InstallTest

    def test_8_uninstall_version_cannot_traverse(self):
        self.installer()
        victim_dir = self.prefix / 'victim'
        victim_dir.mkdir(parents=True)
        (victim_dir / 'keep.txt').write_text('outside the plugin root')
        out = self.installer('--uninstall', '--version', '../victim', expect=2)
        self.assertEqual(out['error']['code'], 'unknown_version')
        self.assertTrue((victim_dir / 'keep.txt').is_file())

    def test_10_uninstall_keeps_unowned_bytecode(self):
        first = self.installer()['data']
        mine = Path(first['version_dir']) / 'unrelated' / '__pycache__' / 'user-data.cpython-314.pyc'
        mine.parent.mkdir(parents=True)
        mine.write_bytes(b'not ours')
        self.installer('--uninstall')
        self.assertTrue(mine.is_file())
