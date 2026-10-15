"""`cli.py doctor` (scripts/doctor.py): one envelope of local readiness facts, and no files left behind."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / 'plugins' / 'imps' / 'cli.py'
CHECKS = {'python', 'git', 'state_root', 'learnings'}
SPEC = importlib.util.spec_from_file_location('imps_doctor', ROOT / 'plugins' / 'imps' / 'scripts' / 'doctor.py')
DOCTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCTOR)


def tree(path):
    """Every path under `path` with its content digest, so any created or changed file shows."""
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'dir'
            for p in sorted(Path(path).rglob('*'))}


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: (os.chmod(self.tmp, 0o700), shutil.rmtree(self.tmp, ignore_errors=True)))
        self.project = self.tmp / 'project'
        self.project.mkdir()
        self.env = dict(os.environ, HOME=str(self.tmp / 'home'), XDG_STATE_HOME=str(self.tmp / 'xdg'))
        self.env.pop('T3_PLUGINS_STATE_ROOT', None)

    def doctor(self, *args, cli=WRAPPER, env=None):
        result = subprocess.run([sys.executable, str(cli), 'doctor', '--repo', str(self.project), *map(str, args)],
                                capture_output=True, text=True, env=env or self.env, cwd=self.tmp, timeout=120)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, result.stdout + result.stderr)
        return result.returncode, json.loads(lines[0])

    def test_writable_root_passes_in_one_envelope(self):
        root = self.tmp / 'state' / 'imps'
        code, out = self.doctor('--state-root', root)
        self.assertEqual(code, 0, out)
        self.assertEqual(set(out), {'schema_version', 'ok', 'op', 'run_id', 'data'})
        self.assertEqual((out['schema_version'], out['ok'], out['op'], out['run_id']), (1, True, 'doctor', None))
        data = out['data']
        self.assertEqual(set(data['checks']), CHECKS)
        self.assertEqual(data['failed'], [])
        self.assertEqual(data['agent_checks'], ['orchestrator_capabilities'])
        self.assertEqual(data['identity_reporting'], {'source': 'recorded host observations only', 'launches_nothing': True})
        self.assertEqual(data['plugin'], 'imps')
        self.assertTrue(data['checks']['python']['ok'])
        self.assertEqual(data['checks']['python']['required'], '3.10+')
        self.assertTrue(data['checks']['git']['version'].startswith('git version'))
        self.assertEqual(data['checks']['state_root']['status'], 'absent')
        self.assertIn(data['checks']['learnings']['status'], ('available', 'unavailable'))

    def test_absent_root_passes_and_writes_nothing_anywhere(self):
        root = self.tmp / 'state' / 'imps'
        before, stamp = tree(self.tmp), os.stat(self.tmp).st_mtime_ns
        code, out = self.doctor('--state-root', root)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['data']['checks']['state_root'], {
            'path': str(root), 'status': 'absent', 'ok': True, 'note': 'created on first run; nothing written',
            'advisory': {'nearest_existing_ancestor': str(self.tmp), 'access_w_ok': True}})
        # A create-then-unlink in the ancestor leaves no file but still moves its mtime.
        self.assertEqual((tree(self.tmp), os.stat(self.tmp).st_mtime_ns), (before, stamp))

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores directory permissions')
    def test_absent_root_under_a_read_only_ancestor_passes_with_an_advisory(self):
        parent = self.tmp / 'locked'
        parent.mkdir()
        parent.chmod(0o500)
        self.addCleanup(parent.chmod, 0o700)
        code, out = self.doctor('--state-root', parent / 'imps')
        self.assertEqual(code, 0, out)
        state = out['data']['checks']['state_root']
        self.assertEqual(state['status'], 'absent')
        self.assertEqual(state['advisory'], {'nearest_existing_ancestor': str(parent), 'access_w_ok': False})

    def test_dangling_symlink_root_fails_instead_of_counting_as_absent(self):
        root = self.tmp / 'state'
        root.symlink_to(self.tmp / 'nowhere')
        before = tree(self.tmp)
        for target in (root, root / 'imps'):
            code, out = self.doctor('--state-root', target)
            self.assertEqual(code, 5, out)
            state = out['error']['details']['checks']['state_root']
            self.assertEqual((state['status'], state['reason']), ('refused', f'dangling symlink: {root}'))
        self.assertFalse(os.path.lexists(self.tmp / 'nowhere'))
        self.assertEqual(tree(self.tmp), before)

    def test_symlinked_root_probes_its_resolved_directory(self):
        real = self.tmp / 'real'
        real.mkdir()
        (self.tmp / 'link').symlink_to(real)
        code, out = self.doctor('--state-root', self.tmp / 'link')
        self.assertEqual(code, 0, out)
        state = out['data']['checks']['state_root']
        self.assertEqual((state['status'], state['resolved']), ('writable', os.path.realpath(real)))
        self.assertEqual(list(real.iterdir()), [])

    def test_creates_no_files(self):
        root = self.tmp / 'state'
        root.mkdir()
        before = tree(self.tmp)
        code, out = self.doctor('--state-root', root)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['data']['checks']['state_root']['status'], 'writable')
        self.assertEqual(out['data']['checks']['state_root']['resolved'], os.path.realpath(root))
        self.assertEqual(tree(self.tmp), before)
        code, _ = self.doctor()  # the default XDG root does not exist yet and is not created
        self.assertEqual(code, 0)
        self.assertEqual(tree(self.tmp), before)

    def test_default_root_is_the_xdg_state_directory(self):
        code, out = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertEqual(out['data']['checks']['state_root']['path'], str(self.tmp / 'xdg' / 't3-plugins' / 'imps'))

    def test_root_under_a_file_fails_with_exit_5(self):
        blocker = self.tmp / 'blocker'
        blocker.write_text('not a directory\n')
        before = tree(self.tmp)
        code, out = self.doctor('--state-root', blocker / 'state')
        self.assertEqual(code, 5)
        self.assertEqual(set(out), {'schema_version', 'ok', 'op', 'run_id', 'error'})
        self.assertFalse(out['ok'])
        self.assertEqual(out['error']['code'], 'doctor_failed')
        details = out['error']['details']
        self.assertEqual(details['failed'], ['state_root'])
        self.assertEqual(set(details['checks']), CHECKS)
        self.assertFalse(details['checks']['state_root']['ok'])
        self.assertIn('NotADirectoryError', details['checks']['state_root']['reason'])
        self.assertTrue(details['checks']['python']['ok'])
        self.assertEqual(tree(self.tmp), before)

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores directory permissions')
    def test_read_only_root_fails_with_exit_5(self):
        root = self.tmp / 'readonly'
        root.mkdir()
        root.chmod(0o500)
        self.addCleanup(root.chmod, 0o700)
        code, out = self.doctor('--state-root', root)
        self.assertEqual(code, 5)
        self.assertEqual(out['error']['details']['failed'], ['state_root'])
        state = out['error']['details']['checks']['state_root']
        self.assertEqual(state['status'], 'not_writable')
        self.assertIn('PermissionError', state['reason'])
        self.assertEqual(list(root.iterdir()), [])

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores directory permissions')
    @unittest.skipUnless(hasattr(os, 'O_PATH'), 'searching without read permission needs O_PATH')
    def test_search_only_permissions_pass_like_init(self):
        # init needs only search (x) on ancestors and write+search on the root, never read.
        ancestor = self.tmp / 'search-only'
        root = ancestor / 'imps'
        root.mkdir(parents=True)
        root.chmod(0o300)
        ancestor.chmod(0o100)
        self.addCleanup(lambda: (ancestor.chmod(0o700), root.chmod(0o700)))
        code, out = self.doctor('--state-root', root)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['data']['checks']['state_root']['status'], 'writable')
        ancestor.chmod(0o700)
        root.chmod(0o700)
        self.assertEqual(list(root.iterdir()), [])

    def test_invalid_arguments_exit_2_in_an_envelope(self):
        code, out = self.doctor('--no-such-flag')
        self.assertEqual(code, 2)
        self.assertEqual((out['ok'], out['op'], out['error']['code']), (False, 'doctor', 'usage'))

    def test_missing_git_fails_with_exit_5(self):
        empty = self.tmp / 'empty-path'
        empty.mkdir()
        code, out = self.doctor('--state-root', self.tmp / 'state', env=dict(self.env, PATH=str(empty)))
        self.assertEqual(code, 5)
        self.assertEqual(out['error']['details']['failed'], ['git'])
        self.assertFalse(out['error']['details']['checks']['git']['ok'])


class ProbeRaceTest(unittest.TestCase):
    """The probe is created and removed through one directory descriptor, not by pathname."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'state'
        self.root.mkdir()

    def probe_with_unlink_hook(self, hook):
        unlink = os.unlink

        def hooked(name, *args, **kwargs):
            if os.path.basename(name).startswith('.doctor-probe-'):
                hook()
            return unlink(name, *args, **kwargs)
        with mock.patch.object(DOCTOR.os, 'unlink', hooked):
            return DOCTOR.probe_state_root(self.root)

    def test_root_renamed_between_create_and_unlink_keeps_no_probe(self):
        moved = self.tmp / 'moved'
        state = self.probe_with_unlink_hook(lambda: self.root.rename(moved))
        self.assertEqual(list(moved.iterdir()), [])
        self.assertEqual(state['status'], 'writable', state)

    def test_root_replaced_between_create_and_unlink_keeps_no_probe(self):
        moved = self.tmp / 'moved'
        state = self.probe_with_unlink_hook(lambda: (self.root.rename(moved), self.root.mkdir()))
        self.assertEqual((list(moved.iterdir()), list(self.root.iterdir())), ([], []))
        self.assertEqual(state['status'], 'writable', state)

    def test_failed_unlink_names_the_leftover_and_fails(self):
        def refuse(name, *args, **kwargs):
            raise PermissionError(1, 'Operation not permitted')
        with mock.patch.object(DOCTOR.os, 'unlink', refuse):
            state = DOCTOR.probe_state_root(self.root)
        self.assertFalse(state['ok'])
        self.assertEqual(state['status'], 'probe_left')
        leftover = [p.name for p in self.root.iterdir()]
        self.assertEqual(len(leftover), 1)
        self.assertEqual(state['leftover'], str(self.root / leftover[0]))

    def test_root_swapped_for_a_symlink_after_resolving_is_refused(self):
        real = self.tmp / 'elsewhere'
        real.mkdir()
        resolve = os.path.realpath

        def swap(path, **kwargs):
            resolved = resolve(path, **kwargs)
            self.root.rmdir()
            self.root.symlink_to(real)
            return resolved
        with mock.patch.object(DOCTOR.os.path, 'realpath', swap):
            state = DOCTOR.probe_state_root(self.root)
        self.assertEqual(state['status'], 'refused', state)
        self.assertEqual(list(real.iterdir()), [])


class InstalledDoctorTest(unittest.TestCase):
    def test_installed_cli_runs_doctor_from_its_own_layout(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        source = tmp / 'src'
        for part in ('core', 'plugins', 'scripts', 'shared'):
            shutil.copytree(ROOT / part, source / part, ignore=shutil.ignore_patterns('__pycache__'))
        home = tmp / 'home'
        home.mkdir()
        env = dict(os.environ, HOME=str(home))
        for name in ('T3_PLUGINS_PREFIX', 'T3_PLUGINS_STATE_ROOT', 'XDG_STATE_HOME', 'T3_PLUGINS_AGENTS_ROOT'):
            env.pop(name, None)
        installed = subprocess.run([sys.executable, str(source / 'scripts' / 'install.py')], capture_output=True,
                                   text=True, env=env, timeout=120)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        shutil.rmtree(source)  # the installed copy must not reach back into its source checkout
        version = json.loads(installed.stdout)['data']['version']
        cli = home / '.local' / 'share' / 't3-plugins' / 'imps' / 'current' / 'cli.py'
        project = tmp / 'project'
        project.mkdir()
        before = tree(home)
        result = subprocess.run([sys.executable, str(cli), 'doctor', '--repo', str(project)], capture_output=True,
                                text=True, env=env, cwd=tmp, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['data']['version'], version)
        self.assertEqual(out['data']['checks']['state_root']['path'],
                         str(home / '.local' / 'state' / 't3-plugins' / 'imps'))
        # An installed package has a manifest, so the learnings helper gets past it to the store.
        self.assertNotIn('install-manifest.json', str(out['data']['checks']['learnings'].get('reason')))
        self.assertEqual(tree(home), before)


if __name__ == '__main__':
    unittest.main()
