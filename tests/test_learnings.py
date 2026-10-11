"""Stage 4: private storage, maintenance and installed helper failure paths."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
from learning_store import Store, Unavailable, canonical_remote, decode, project_identity, state_root

OLD = '0.1.0+g' + 'a' * 12
NEW = '0.2.0+g' + 'b' * 12
CONTENT = '0.2.0+content.' + 'c' * 12


def write_worker(args):
    project, env, number = args
    return Store(project, 'imps', OLD, env).operate('write', {
        'entry': {'id': 'lesson-' + str(number), 'summary': 'Keep the task handle',
                  'failure': 'A lost handle prevented cancellation'}})


class LearningsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.env = dict(os.environ, HOME=str(self.base / 'home'), XDG_STATE_HOME=str(self.base / 'state'),
                        XDG_CONFIG_HOME=str(self.base / 'config'))
        self.store = Store(self.project, 'imps', OLD, self.env)

    def write(self, entry_id='lesson', upstream=None):
        entry = {'id': entry_id, 'summary': 'Keep task handles', 'failure': 'A lost task handle prevented cancellation'}
        if upstream:
            entry['upstream'] = upstream
        result = self.store.operate('write', {'entry': entry})
        self.assertEqual(result['status'], 'available', result)
        return result

    def git(self, *args, cwd=None):
        result = subprocess.run(['git', *args], cwd=cwd or self.project, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_remote_identity_across_worktrees_transports_and_credentials(self):
        self.git('init', '-q')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'base')
        self.git('remote', 'add', 'zebra', 'https://elsewhere.invalid/z/repo.git')
        self.git('remote', 'add', 'origin', 'git@EXAMPLE.invalid:group/repo.git')
        other = self.base / 'other'
        self.git('worktree', 'add', '-qb', 'other', str(other))
        first = Store(self.project, 'imps', OLD, self.env)
        second = Store(other, 'imps', OLD, self.env)
        self.assertEqual(first.folder, second.folder)
        self.git('remote', 'set-url', 'origin', 'https://user:password@example.invalid/group/repo.git')
        third = Store(self.project, 'imps', OLD, self.env)
        self.assertEqual(first.folder, third.folder)
        result = third.operate('write', {'entry': {'id': 'safe', 'summary': 'One lesson', 'failure': 'Observed failure'}})
        text = Path(result['path']).read_text()
        self.assertNotIn('password', text)
        self.assertNotIn(first.key, text)
        self.git('remote', 'remove', 'origin')
        self.git('remote', 'add', 'alpha', 'ssh://who@example.invalid/group/first.git')
        self.assertEqual(project_identity(self.project)[1], 'example.invalid/group/first')

    def test_non_git_and_git_missing_are_optional(self):
        key, label = project_identity(self.project)
        with mock.patch('learning_store.subprocess.run', side_effect=FileNotFoundError):
            self.assertEqual(project_identity(self.project), (key, label))
        self.assertNotEqual(key, project_identity(self.base)[0])
        self.assertEqual(canonical_remote('ssh://user@EXAMPLE.invalid/group/repo.git'),
                         canonical_remote('https://example.invalid/group/repo'))

    def test_roots_are_absolute_outside_project_and_fallback_is_xdg(self):
        for root in ('relative', str(self.project / 'state')):
            with self.assertRaises(Unavailable):
                state_root(self.project, dict(self.env, XDG_STATE_HOME=root))
        self.assertEqual(state_root(self.project, {'HOME': str(self.base / 'home')}),
                         self.base / 'home/.local/state')

    def test_read_only_load_never_creates_or_prunes(self):
        result = self.store.operate()
        self.assertEqual(result['data']['entries'], [])
        self.assertFalse(self.store.root.exists())
        self.write()
        before = {p: p.read_bytes() for p in self.store.folder.iterdir()}
        result = Store(self.project, 'imps', NEW, self.env).operate()
        self.assertTrue(result['pending_maintenance'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.store.folder.iterdir()})

    def test_versioned_format_authorship_and_plugin_isolation(self):
        loaded = self.write()
        self.assertEqual(stat.S_IMODE(Path(loaded['path']).stat().st_mode), 0o600)
        self.assertEqual(decode(Path(loaded['path']).read_bytes())[1]['format_version'], 1)
        self.store = Store(self.project, 'imps', NEW, self.env)
        pending = self.store.operate('write', {'entry': {'id': 'lesson', 'summary': 'Changed', 'failure': 'Observed'}})
        self.assertEqual(pending['status'], 'unavailable')
        maintained = self.store.operate('maintain', {'expected': loaded['revision']})
        self.assertEqual(maintained['status'], 'available')
        updated = self.write()['data']['entries'][0]
        self.assertEqual(updated['authored_version'], OLD)
        self.assertEqual(updated['last_validated_version'], NEW)
        self.assertEqual(Store(self.project, 'ape', NEW, self.env).operate()['data']['entries'], [])

    def test_git_failure_does_not_silently_select_another_identity(self):
        probe = subprocess.CompletedProcess([], 128, stdout='', stderr='unsafe ownership')
        with mock.patch('learning_store.subprocess.run', return_value=probe):
            with self.assertRaises(Unavailable):
                project_identity(self.project)

    def test_concurrent_writers_do_not_lose_entries(self):
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write_worker, [(str(self.project), self.env, n) for n in range(24)]))
        self.assertTrue(all(r['status'] == 'available' for r in results))
        self.assertEqual(len(self.store.operate()['data']['entries']), 24)

    def test_symlink_and_hardlink_artifacts_and_parent_are_refused(self):
        loaded = self.write()
        path = Path(loaded['path'])
        outside = self.base / 'outside'
        outside.write_text('untouched')
        path.unlink()
        path.symlink_to(outside)
        result = self.store.operate('write', {'entry': {'id': 'other', 'summary': 'Safe', 'failure': 'Failed'}})
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(outside.read_text(), 'untouched')
        path.unlink()
        os.link(outside, path)
        self.assertEqual(self.store.operate()['status'], 'unavailable')
        path.unlink()
        shutil.rmtree(self.store.folder)
        self.store.folder.symlink_to(self.base, target_is_directory=True)
        self.assertEqual(self.store.operate()['status'], 'unavailable')
        self.assertFalse((self.base / 'imps.md').exists())

    def test_maintenance_fixture_prunes_only_completed_released_issue(self):
        for number, name in enumerate(('completed', 'duplicate', 'rejected', 'reopened', 'unreleased', 'unknown'), 1):
            self.write(name, 'seankoji-com/t3-plugins#' + str(number))
        loaded = self.store.operate()
        new = Store(self.project, 'imps', NEW, self.env)
        states = []
        for entry in loaded['data']['entries']:
            state = {'upstream': entry['upstream'], 'state': 'closed', 'state_reason': entry['id'],
                     'closing_commit': 'd' * 40, 'compare_base': 'd' * 40,
                     'compare_head': 'b' * 12, 'compare_status': 'ahead'}
            if entry['id'] in ('unreleased', 'unknown'):
                state['state_reason'] = 'completed'
                state['compare_status'] = 'behind' if entry['id'] == 'unreleased' else None
            if entry['id'] == 'reopened':
                state.update(state='open', state_reason='completed')
            states.append(state)
        result = new.operate('maintain', {'expected': loaded['revision'], 'states': states})
        self.assertEqual(result['status'], 'available', result)
        self.assertEqual({e['id'] for e in result['data']['entries']},
                         {'duplicate', 'rejected', 'reopened', 'unreleased', 'unknown'})
        backup = new.folder / ('imps.md.pre-' + OLD)
        self.assertEqual(decode(backup.read_bytes())[1], loaded['data'])
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(result['data']['maintained_version'], NEW)
        self.assertTrue(all(e['authored_version'] == OLD and e['last_validated_version'] == NEW
                            for e in result['data']['entries']))

    def test_content_install_skips_upstream_without_gh_and_judgement_can_amend(self):
        loaded = self.write(upstream='seankoji-com/t3-plugins#42')
        new = Store(self.project, 'imps', CONTENT, self.env)
        with mock.patch('learning_store.subprocess.run', side_effect=AssertionError('no gh')):
            result = new.operate('maintain', {'expected': loaded['revision'], 'states': [
                {'upstream': 'seankoji-com/t3-plugins#42', 'state': 'closed', 'state_reason': 'completed',
                 'closing_commit': 'd' * 40, 'compare_base': 'd' * 40, 'compare_head': 'b' * 12,
                 'compare_status': 'ahead'}], 'amend': [{'id': 'lesson', 'summary': 'Keep every handle'}]})
        self.assertIn('skipped', result['upstream_check'])
        self.assertEqual(result['data']['entries'][0]['summary'], 'Keep every handle')
        self.assertEqual(result['data']['entries'][0]['authored_version'], OLD)

    def test_stale_judgement_and_failures_leave_active_file_unchanged(self):
        loaded = self.write()
        active = Path(loaded['path'])
        original = active.read_bytes()
        new = Store(self.project, 'imps', NEW, self.env)
        proposal = {'expected': loaded['revision'], 'remove': ['lesson']}
        with mock.patch('learning_store.os.replace', side_effect=OSError('rename failed')):
            result = new.operate('maintain', proposal)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['proposed_learning'], proposal)
        self.assertEqual(active.read_bytes(), original)
        # Also fail after the owned backup was successfully written.
        from learning_store import atomic_file
        def fail_active(fd, name, data):
            if name == 'imps.md':
                raise OSError('active write failed')
            return atomic_file(fd, name, data)
        with mock.patch('learning_store.atomic_file', side_effect=fail_active):
            self.assertEqual(new.operate('maintain', proposal)['status'], 'unavailable')
        self.assertEqual(active.read_bytes(), original)
        self.write('concurrent')
        self.assertEqual(new.operate('maintain', proposal)['status'], 'unavailable')
        for function in ('read_file', 'encode'):
            with mock.patch('learning_store.' + function, side_effect=OSError('I/O failed')):
                self.assertEqual(self.store.operate('write', {'entry': {'id': 'extra'}})['status'], 'unavailable')

    def test_upstream_compare_endpoints_are_bound(self):
        loaded = self.write(upstream='seankoji-com/t3-plugins#42')
        new = Store(self.project, 'imps', NEW, self.env)
        state = {'upstream': 'seankoji-com/t3-plugins#42', 'state': 'closed', 'state_reason': 'completed',
                 'closing_commit': 'd' * 40, 'compare_base': 'e' * 40, 'compare_head': 'b' * 12,
                 'compare_status': 'ahead'}
        result = new.operate('maintain', {'expected': loaded['revision'], 'states': [state]})
        self.assertEqual(len(result['data']['entries']), 1)

    def test_every_installed_plugin_loads_maintains_writes_and_handles_unavailable(self):
        prefix = self.base / 'prefix'
        for plugin in ('imps', 'babysitter', 'elephant-goldfish', 'ape', 'agent-tuneup'):
            installed = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', plugin,
                                        '--prefix', str(prefix)], env=self.env, capture_output=True, text=True)
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            package = prefix / plugin / 'current'
            helper = package / 'shared/learnings.py'
            entry = (package / 'entry.md').read_text()
            self.assertIn('PKG/shared/learnings.md', entry)
            self.assertIn('PKG/shared/delegation.md', entry)
            def run(operation, proposal=None, env=None):
                argv = [sys.executable, str(helper), operation, '--project', str(self.project)]
                if proposal is not None:
                    input_path = self.base / 'input.json'
                    input_path.write_text(json.dumps(proposal))
                    argv.extend(['--input', str(input_path)])
                output = subprocess.run(argv, env=env or self.env, cwd=self.base, capture_output=True, text=True)
                self.assertEqual(output.returncode, 0, output.stderr)
                return json.loads(output.stdout)
            self.assertEqual(run('load')['data']['entries'], [])
            previous = Store(self.project, plugin, OLD, self.env).operate('write', {
                'entry': {'id': 'old', 'summary': 'Old lesson', 'failure': 'Observed failure'}})
            loaded = run('load')
            self.assertTrue(loaded['pending_maintenance'])
            maintained = run('maintain', {'expected': loaded['revision'], 'remove': ['old']})
            self.assertEqual(maintained['data']['entries'], [])
            written = run('write', {'entry': {'id': 'new', 'summary': 'New lesson', 'failure': 'Another observed failure'}})
            self.assertEqual(written['status'], 'available')
            proposal = {'entry': {'id': 'blocked', 'summary': 'Proposed', 'failure': 'Write failed'}}
            unavailable = run('write', proposal, dict(self.env, XDG_STATE_HOME=str(self.project / 'state')))
            self.assertEqual(unavailable['status'], 'unavailable')
            self.assertEqual(unavailable['proposed_learning'], proposal)
            self.assertFalse((self.project / 'state').exists())


if __name__ == '__main__':
    unittest.main()
