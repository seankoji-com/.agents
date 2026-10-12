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


class LauncherTest(CoreTestCase):
    """seankoji: one launcher, whatever the package layout."""

    def test_launcher_runs_the_core_installed_and_from_source(self):
        home = self.tmp / 'home'
        source = self.tmp / 'src'
        for part in ('core', 'plugins', 'scripts', 'shared'):
            shutil.copytree(ROOT / part, source / part, ignore=shutil.ignore_patterns('__pycache__'))
        env = {key: value for key, value in os.environ.items()
               if key not in ('T3_PLUGINS_PREFIX', 'T3_PLUGINS_STATE_ROOT', 'XDG_STATE_HOME')}
        env['HOME'] = str(home)
        installed = subprocess.run([sys.executable, str(source / 'scripts' / 'install.py')], capture_output=True,
                                   text=True, env=env)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        prefix = home / '.local' / 'share' / 't3-plugins'
        for launcher in (prefix / 'imps' / 'current' / 'cli.py', ROOT / 'plugins' / 'imps' / 'cli.py'):
            result = subprocess.run([sys.executable, str(launcher), 'status', '--state-root', str(self.tmp / 's'),
                                     '--run-id', 'bad'], capture_output=True, text=True, env=env)
            envelope = json.loads(result.stdout)
            self.assertEqual((result.returncode, envelope['op'], envelope['error']['code']), (2, 'status', 'run_id'), launcher)


class Round6Test(CoreTestCase):
    def test_recipe_stamp_refuses_evidence_outside_the_run_directory(self):
        recipe_path = self.tmp / 'r' / 'recipe.json'
        recipe_path.parent.mkdir()
        recipe_path.write_text(json.dumps({'features': [{'id': 'F-X'}]}))
        outside = self.write('secret.txt', 'x')
        state = {'phase': 'completed', 'run_id': 'r1', 'acceptance': [{
            'requirement_id': 'REQ-X', 'status': 'passed', 'kind': 'runtime',
            'artifacts': [{'path': '../secret.txt', 'sha256': __import__('hashlib').sha256(b'x').hexdigest()}]}]}
        run_dir = self.tmp / 'run'
        run_dir.mkdir()
        with self.assertRaises(Exception) as caught:
            recipe.stamp(recipe_path, state, run_dir, 'F-X', 'REQ-X')
        self.assertEqual(caught.exception.code, 'path_escape')
        self.assertFalse((recipe_path.parent / 'evidence').exists())

    def test_uninstall_keeps_current_for_a_version_kept_for_local_edits(self):
        home = self.tmp / 'home'
        source = self.tmp / 'src'
        for part in ('core', 'plugins', 'scripts', 'shared'):
            shutil.copytree(ROOT / part, source / part, ignore=shutil.ignore_patterns('__pycache__'))
        env = {key: value for key, value in os.environ.items()
               if key not in ('T3_PLUGINS_PREFIX', 'T3_PLUGINS_STATE_ROOT', 'XDG_STATE_HOME')}
        env['HOME'] = str(home)
        installer = [sys.executable, str(source / 'scripts' / 'install.py')]
        self.assertEqual(subprocess.run(installer, capture_output=True, env=env).returncode, 0)
        current = home / '.local' / 'share' / 't3-plugins' / 'imps' / 'current'
        (current / 'entry.md').write_text((current / 'entry.md').read_text() + '\nlocal note\n')
        out = subprocess.run(installer + ['--uninstall'], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(current.is_symlink() and (current / 'entry.md').is_file(), 'the kept version stays active')

    def test_launcher_without_a_core_explains_itself(self):
        lonely = self.tmp / 'lonely'
        lonely.mkdir()
        shutil.copy(ROOT / 'plugins' / 'imps' / 'cli.py', lonely / 'cli.py')
        result = subprocess.run([sys.executable, str(lonely / 'cli.py'), 'status'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no usable core/cli.py', result.stderr)
