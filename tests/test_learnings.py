"""Stage 4: private storage, maintenance and installed helper failure paths."""
import concurrent.futures
import contextlib
import errno
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
from learning_store import (Store, Unavailable, canonical_remote, decode, probe_write, project_identity,
                            state_root)

OLD = '0.1.0+g' + 'a' * 12
NEW = '0.2.0+g' + 'b' * 12
CONTENT = '0.2.0+content.' + 'c' * 12


def write_worker(args):
    project, env, number = args
    return Store(project, 'imps', OLD, env).operate('write', {
        'entry': {'id': 'lesson-' + str(number), 'summary': 'Keep the task handle',
                  'failure': 'A lost handle prevented cancellation'}})


@contextlib.contextmanager
def lock_open_faults(codes):
    """Inject only the observed lock-open error, leaving fixture filesystem I/O real."""
    real_open = os.open
    errors = iter(codes)
    calls = []

    def open_file(name, flags, mode=0o777, *, dir_fd=None):
        if name == 'imps.md.lock':
            calls.append((name, flags, mode, dir_fd))
            code = next(errors, None)
            if code is not None:
                raise OSError(code, os.strerror(code), name)
        return real_open(name, flags, mode, dir_fd=dir_fd)

    with mock.patch('learning_store.os.open', side_effect=open_file):
        yield calls


def write_worker_after_lock_open_miss(args):
    with lock_open_faults([errno.ENOENT]) as calls:
        result = write_worker(args)
    return result, len(calls)


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

    def test_pre_198_lessons_stay_shared_in_place_until_moved(self):
        self.write('legacy', upstream='seankoji-com/t3-plugins#28')
        legacy = self.store.root / 't3-plugins/learnings' / self.store.key
        legacy.parent.mkdir(parents=True)
        self.store.folder.rename(legacy)
        loaded = Store(self.project, 'imps', OLD, self.env).operate()
        self.assertEqual([e['id'] for e in loaded['data']['entries']], ['legacy'])
        self.assertEqual(Path(loaded['path']).parent, legacy)
        written = self.write('new')
        self.assertEqual(Path(written['path']).parent, legacy)
        self.assertFalse(self.store.folder.exists())
        # An old job writing in between is seen by the next new-runtime load: no fork.
        old_job = Store(self.project, 'imps', OLD, self.env)
        old_job.folder = legacy
        self.assertEqual(old_job.operate('write', {'entry': {'id': 'late-old-job', 'summary': 'Old runtime',
                                                             'failure': 'Written at the old location'}})['status'],
                         'available')
        ids = sorted(e['id'] for e in Store(self.project, 'imps', OLD, self.env).operate()['data']['entries'])
        self.assertEqual(ids, ['late-old-job', 'legacy', 'new'])
        # Old runtimes validate with the pre-#198 pattern, so the shared file must keep passing it.
        before = (legacy / 'imps.md').read_bytes()
        refused = self.store.operate('write', {'entry': {'id': 'renamed', 'summary': 'New reference',
                                                         'failure': 'Cited the renamed repository',
                                                         'upstream': 'seankoji-com/.agents#7'}})
        self.assertEqual(refused['status'], 'unavailable')
        self.assertIn('seankoji-com/t3-plugins#N', refused['reason'])
        self.assertEqual((legacy / 'imps.md').read_bytes(), before)
        _, data = decode((legacy / 'imps.md').read_bytes())
        base_pattern = r'seankoji-com/t3-plugins#[1-9]\d*'  # a76f51c shared/learning_store.py validate_entry
        self.assertTrue(all(re.fullmatch(base_pattern, e['upstream']) for e in data['entries'] if e.get('upstream')))
        # Once moved, the current location wins and the old file is no longer used.
        legacy.rename(self.store.folder)
        self.assertEqual(Path(self.write('moved')['path']).parent, self.store.folder)

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
        with mock.patch('learning_store.subprocess.run', return_value=probe) as run:
            with self.assertRaises(Unavailable):
                project_identity(self.project)
            self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')
        not_git = subprocess.CompletedProcess([], 128, stdout='', stderr='fatal: not a git repository')
        with mock.patch('learning_store.subprocess.run', return_value=not_git) as run:
            self.assertEqual(project_identity(self.project)[1], self.project.name)
            self.assertTrue(all(call.kwargs['env']['LC_ALL'] == 'C' for call in run.call_args_list))

    def test_concurrent_writers_do_not_lose_entries(self):
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write_worker, [(str(self.project), self.env, n) for n in range(24)]))
        self.assertTrue(all(r['status'] == 'available' for r in results),
                        [r for r in results if r['status'] != 'available'])
        self.assertEqual(len(self.store.operate()['data']['entries']), 24)

    def test_transient_lock_open_enoent_retries_without_replaying_write(self):
        lock = self.store.folder / 'imps.md.lock'
        for entry_id in ('first', 'second'):
            with self.subTest(entry_id=entry_id):
                identity = lock.stat() if lock.exists() else None
                with lock_open_faults([errno.ENOENT]) as calls, mock.patch.object(
                        self.store, '_operate', wraps=self.store._operate) as operation:
                    self.write(entry_id)
                operation.assert_called_once()
                self.assertEqual(len(calls), 3 if identity is not None else 2)
                self.assertEqual(calls[0], calls[1])
                self.assertEqual(calls[0][1], os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK)
                self.assertEqual(calls[0][2], 0o600)
                self.assertIsNotNone(calls[0][3])
                if identity is not None:
                    self.assertEqual(calls[2][1], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                    self.assertEqual(calls[2][3], calls[0][3])
                    self.assertEqual((lock.stat().st_dev, lock.stat().st_ino),
                                     (identity.st_dev, identity.st_ino))
        self.assertEqual({e['id'] for e in self.store.operate()['data']['entries']}, {'first', 'second'})

    def test_existing_lock_reopen_enoent_is_bounded_and_preserves_inode(self):
        self.write('first')
        lock = self.store.folder / 'imps.md.lock'
        identity = lock.stat()
        with lock_open_faults([errno.EEXIST, errno.ENOENT]) as calls, mock.patch.object(
                self.store, '_operate', wraps=self.store._operate) as operation:
            self.write('second')
        operation.assert_called_once()
        self.assertEqual(len(calls), 4)
        self.assertEqual([bool(call[1] & os.O_EXCL) for call in calls], [True, False, True, False])
        self.assertEqual(len({call[3] for call in calls}), 1)
        self.assertEqual((lock.stat().st_dev, lock.stat().st_ino), (identity.st_dev, identity.st_ino))
        self.assertEqual({e['id'] for e in self.store.operate()['data']['entries']}, {'first', 'second'})
        before = {p.name: p.read_bytes() for p in self.store.folder.iterdir()}
        with lock_open_faults([errno.EEXIST, errno.ENOENT] * 4) as calls, mock.patch(
                'learning_store.atomic_file', side_effect=AssertionError('must not write')):
            result = self.store.operate('write', {'entry': {'id': 'lost'}})
        self.assertEqual(result['status'], 'unavailable', result)
        self.assertEqual(len(calls), 6)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.store.folder.iterdir()})
        self.assertEqual(lock.stat().st_ino, identity.st_ino)

    def test_persistent_lock_open_enoent_fails_closed(self):
        loaded = self.write()
        before = {p.name: p.read_bytes() for p in self.store.folder.iterdir()}
        proposal = {'entry': {'id': 'lost', 'summary': 'Keep handles', 'failure': 'Lost handle'}}
        with lock_open_faults([errno.ENOENT] * 8) as calls, mock.patch(
                'learning_store.atomic_file', side_effect=AssertionError('must not write')):
            result = self.store.operate('write', proposal)
        self.assertEqual(result['status'], 'unavailable', result)
        self.assertEqual(result['proposed_learning'], proposal)
        self.assertIn('imps.md.lock', result['reason'])
        self.assertEqual(len(calls), 3)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.store.folder.iterdir()})
        self.assertEqual(self.store.operate()['revision'], loaded['revision'])

    def test_other_lock_open_errors_are_not_retried(self):
        self.write()
        before = {p.name: p.read_bytes() for p in self.store.folder.iterdir()}
        for code in (errno.EACCES, errno.EPERM, errno.EROFS, errno.EIO, errno.ELOOP):
            for prefix in ([], [errno.ENOENT]):
                with self.subTest(errno=errno.errorcode[code], prefix=prefix), lock_open_faults(
                        prefix + [code] * 8) as calls:
                    result = self.store.operate('write', {'entry': {'id': 'lost'}})
                    self.assertEqual(result['status'], 'unavailable', result)
                    self.assertEqual(len(calls), len(prefix) + 1)
                    if code in (errno.EACCES, errno.EPERM, errno.EROFS):
                        self.assertIn('sandbox or filesystem permissions deny', result['reason'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.store.folder.iterdir()})

    def test_lock_open_retry_still_refuses_symlinks_and_hardlinks(self):
        loaded = self.write()
        active = Path(loaded['path']).read_bytes()
        lock = self.store.folder / 'imps.md.lock'
        outside = self.base / 'outside'
        outside.write_bytes(b'untouched')
        outside.chmod(0o644)
        for link in ('symlink', 'hardlink'):
            with self.subTest(link=link):
                lock.unlink()
                if link == 'symlink':
                    lock.symlink_to(outside)
                else:
                    os.link(outside, lock)
                with lock_open_faults([errno.ENOENT]) as calls:
                    result = self.store.operate('write', {'entry': {'id': 'lost'}})
                self.assertEqual(result['status'], 'unavailable', result)
                self.assertEqual(len(calls), 3)
                self.assertEqual(Path(loaded['path']).read_bytes(), active)
                self.assertEqual(outside.read_bytes(), b'untouched')
                self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o644)

    def test_lock_open_retry_stays_anchored_after_directory_rename(self):
        from learning_store import directory, locked
        self.write()
        lock = self.store.folder / 'imps.md.lock'
        identity = lock.stat()
        moved = self.store.folder.with_name('moved')
        real_open = os.open
        calls = []

        def rename_before_open(name, flags, mode=0o777, *, dir_fd=None):
            if name == 'imps.md.lock':
                calls.append(dir_fd)
                if len(calls) == 1:
                    self.store.folder.rename(moved)
                    self.store.folder.mkdir()
                    raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
            return real_open(name, flags, mode, dir_fd=dir_fd)

        with directory(self.store.folder) as fd, mock.patch(
                'learning_store.os.open', side_effect=rename_before_open):
            with locked(fd, 'imps.md.lock', True):
                self.assertEqual(calls, [fd, fd, fd])
                self.assertEqual(list(self.store.folder.iterdir()), [])
                info = (moved / 'imps.md.lock').stat()
                self.assertEqual((info.st_dev, info.st_ino), (identity.st_dev, identity.st_ino))

    def test_read_only_missing_lock_is_not_retried_or_created(self):
        self.store.folder.mkdir(parents=True)
        with lock_open_faults([errno.ENOENT]) as calls:
            result = self.store.operate()
        self.assertEqual(result['data']['entries'], [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        self.assertEqual(list(self.store.folder.iterdir()), [])
        self.write()
        lock = self.store.folder / 'imps.md.lock'
        lock.unlink()
        with lock_open_faults([errno.ENOENT]) as calls:
            self.assertEqual(self.store.operate()['status'], 'unavailable')
        self.assertEqual(len(calls), 1)
        self.assertFalse(lock.exists())

    def test_concurrent_writers_retain_every_entry_after_lock_open_misses(self):
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write_worker_after_lock_open_miss,
                                    [(str(self.project), self.env, n) for n in range(24)]))
        for result, attempts in results:
            self.assertEqual(result['status'], 'available', result)
            self.assertIn(attempts, (2, 3))
        self.assertEqual({e['id'] for e in self.store.operate()['data']['entries']},
                         {'lesson-' + str(n) for n in range(24)})

    def test_first_writer_losing_lock_creation_preserves_both_entries(self):
        real_open = os.open
        raced = False
        winner_inode = None

        def competing_open(name, flags, *args, **kwargs):
            nonlocal raced, winner_inode
            if name == 'imps.md.lock' and flags & os.O_CREAT and not raced:
                raced = True
                self.write('winner')
                winner_inode = (self.store.folder / name).stat().st_ino
                # Model the macOS ENOENT race on the exclusive O_CREAT open too.
                error = FileNotFoundError
                code = errno.ENOENT
                raise error(code, os.strerror(code), name)
            return real_open(name, flags, *args, **kwargs)

        with mock.patch('learning_store.os.open', side_effect=competing_open):
            self.write('loser')
        self.assertTrue(raced)
        self.assertEqual({e['id'] for e in self.store.operate()['data']['entries']}, {'winner', 'loser'})
        lock = self.store.folder / 'imps.md.lock'
        self.assertEqual(lock.stat().st_ino, winner_inode)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

    def test_lock_reopen_enoent_retries_exclusive_creation(self):
        real_open = os.open
        exclusive_seen = False
        reopen_missed = False
        winner_done = False
        exclusive_flags = []
        reopen_flags = []

        def competing_open(name, flags, *args, **kwargs):
            nonlocal exclusive_seen, reopen_missed, winner_done
            if name == 'imps.md.lock':
                if flags & os.O_EXCL:
                    exclusive_flags.append(flags)
                    if not exclusive_seen:
                        exclusive_seen = True
                        self.write('winner')
                        winner_done = True
                        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), name)
                elif winner_done:
                    reopen_flags.append(flags)
                    if not reopen_missed:
                        reopen_missed = True
                        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
            return real_open(name, flags, *args, **kwargs)

        with mock.patch('learning_store.os.open', side_effect=competing_open):
            self.write('loser')
        self.assertTrue(reopen_missed)
        self.assertGreaterEqual(len(exclusive_flags), 2)
        self.assertTrue(all(flags & os.O_EXCL for flags in exclusive_flags))
        self.assertGreaterEqual(len(reopen_flags), 2)
        self.assertTrue(all(not flags & os.O_EXCL for flags in reopen_flags))
        self.assertEqual({e['id'] for e in self.store.operate()['data']['entries']}, {'winner', 'loser'})

    def test_unsafe_lock_files_are_refused_without_changing_target(self):
        self.write()
        lock = self.store.folder / 'imps.md.lock'
        outside = self.base / 'outside-lock'
        outside.write_text('untouched')
        outside.chmod(0o640)
        for kind in ('symlink', 'hardlink', 'fifo'):
            with self.subTest(kind=kind):
                lock.unlink()
                if kind == 'symlink':
                    lock.symlink_to(outside)
                elif kind == 'hardlink':
                    os.link(outside, lock)
                elif kind == 'fifo' and not hasattr(os, 'mkfifo'):
                    continue
                else:
                    os.mkfifo(lock)
                self.assertEqual(self.store.operate()['status'], 'unavailable')
                result = self.store.operate('write', {
                    'entry': {'id': 'unsafe', 'summary': 'Keep locks safe', 'failure': 'Unsafe lock'}})
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(outside.read_text(), 'untouched')
                self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o640)

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
            self.write(name, 'seankoji-com/.agents#' + str(number))
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
        loaded = self.write(upstream='seankoji-com/.agents#42')
        new = Store(self.project, 'imps', CONTENT, self.env)
        with mock.patch('learning_store.subprocess.run', side_effect=AssertionError('no gh')):
            result = new.operate('maintain', {'expected': loaded['revision'], 'states': [
                {'upstream': 'seankoji-com/.agents#42', 'state': 'closed', 'state_reason': 'completed',
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
        loaded = self.write(upstream='seankoji-com/.agents#42')
        new = Store(self.project, 'imps', NEW, self.env)
        state = {'upstream': 'seankoji-com/.agents#42', 'state': 'closed', 'state_reason': 'completed',
                 'closing_commit': 'd' * 40, 'compare_base': 'e' * 40, 'compare_head': 'b' * 12,
                 'compare_status': 'ahead'}
        result = new.operate('maintain', {'expected': loaded['revision'], 'states': [state]})
        self.assertEqual(len(result['data']['entries']), 1)

    def test_every_installed_plugin_loads_maintains_writes_and_handles_unavailable(self):
        prefix = self.base / 'prefix'
        for plugin in ('imps', 'babysitter', 'elephant-goldfish', 'ape', 'agent-tuneup', 'ralph'):
            installed = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', plugin,
                                        '--prefix', str(prefix)], env=self.env, capture_output=True, text=True, timeout=30)
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
                output = subprocess.run(argv, env=env or self.env, cwd=self.base, capture_output=True, text=True, timeout=30)
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



class SandboxDenialTest(unittest.TestCase):
    """A sandbox or filesystem that refuses the learnings subtree gets a named cause and both remedies."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.env = dict(os.environ, HOME=str(self.base / 'home'), XDG_STATE_HOME=str(self.base / 'state'))
        self.subtree = str(self.base / 'state/agents/jobs/learnings')
        self.store = Store(self.project, 'imps', OLD, self.env)
        self.proposal = {'entry': {'id': 'lesson', 'summary': 'Keep task handles',
                                   'failure': 'A lost task handle prevented cancellation'}}

    def assert_remedies(self, reason, action='writes under'):
        self.assertIn(f'the sandbox or filesystem permissions deny {action} {self.subtree}', reason)
        self.assertIn(f'allow writes to {self.subtree} and {self.subtree}/** in the sandbox', reason)
        self.assertIn('sandbox.filesystem.allowWrite', reason)
        self.assertIn('agents permissions', reason)
        self.assertIn('fix the ownership, permissions or read-only mount', reason)
        # Nothing below the learnings root: no identity hash, plugin file or temporary name.
        for private in (self.store.key, 'imps.md', '.learning-', '.probe-', 'Errno'):
            self.assertNotIn(private, reason)

    def assert_denied(self, result):
        self.assertEqual(result['status'], 'unavailable', result)
        self.assertEqual(result['proposed_learning'], self.proposal)
        self.assert_remedies(result['reason'])

    def make_root(self):
        Path(self.subtree).mkdir(parents=True)
        return Path(self.subtree)

    def test_symlink_loop_in_the_state_root_is_unavailable_not_a_crash(self):
        loop = self.base / 'loop'
        os.symlink(loop, loop)
        env = dict(self.env, XDG_STATE_HOME=str(loop))
        for project in (None, self.project):
            with self.subTest(project=project):
                probe = probe_write(project, env)
                self.assertEqual(probe['status'], 'unavailable', probe)
        # Store refuses it too: Unavailable where resolve() raises (Python < 3.13), or the
        # no-symlink walk's OSError, which the learnings helper turns into an unavailable receipt.
        with self.assertRaises((Unavailable, OSError)):
            Store(self.project, 'imps', OLD, env)
        with mock.patch.object(Path, 'resolve', side_effect=RuntimeError('Symlink loop')):
            self.assertEqual(probe_write(self.project, self.env)['status'], 'unavailable')

    def test_simulated_erofs_eacces_and_eperm_name_the_grant(self):
        for code, target in ((errno.EROFS, 'learning_store.os.mkdir'), (errno.EACCES, 'learning_store.atomic_file'),
                             (errno.EPERM, 'learning_store.atomic_file')):
            with self.subTest(errno=errno.errorcode[code]), mock.patch(
                    target, side_effect=OSError(code, os.strerror(code), 'learnings')):
                self.assert_denied(self.store.operate('write', self.proposal))
        with mock.patch('learning_store.atomic_file', side_effect=OSError(errno.ENOSPC, 'No space left')):
            self.assertIn('No space left', self.store.operate('write', self.proposal)['reason'])

    def test_state_root_traversal_denial_is_classified_for_store_helper_and_probe(self):
        real_open = os.open

        def refuse_state(name, *args, **kwargs):
            if name == 'state' and kwargs.get('dir_fd') is not None:
                raise OSError(errno.EACCES, 'Permission denied', name)
            return real_open(name, *args, **kwargs)

        (self.base / 'state').mkdir()
        package = self.base / 'package'
        package.mkdir()
        (package / 'install-manifest.json').write_text(json.dumps({'plugin': 'imps', 'version': OLD}))
        import contextlib, io, learnings
        with mock.patch('learning_store.os.open', side_effect=refuse_state):
            with self.assertRaises(Unavailable) as raised:
                Store(self.project, 'imps', OLD, self.env)
            self.assert_remedies(str(raised.exception), 'access to')
            output = io.StringIO()
            with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(output):
                learnings.main(['write', '--project', str(self.project), '--package', str(package)])
            helper = json.loads(output.getvalue())
            probe = probe_write(self.project, self.env)
        self.assertEqual(helper['status'], 'unavailable')
        self.assert_remedies(helper['reason'], 'access to')
        self.assertEqual(probe['status'], 'denied', probe)
        self.assert_remedies(probe['reason'], 'access to')

    @unittest.skipIf(os.geteuid() == 0, 'root ignores directory permissions')
    def test_real_read_only_learnings_root_is_reported_and_probe_leaves_nothing(self):
        root = self.make_root()
        root.chmod(0o500)
        self.addCleanup(root.chmod, 0o700)
        self.assert_denied(self.store.operate('write', self.proposal))
        probe = probe_write(self.project, self.env)
        self.assertEqual(probe['status'], 'denied', probe)
        self.assert_remedies(probe['reason'])
        self.assertEqual(list(root.iterdir()), [])

    def test_probe_creates_no_directories_when_the_root_is_absent(self):
        with mock.patch('learning_store.os.mkdir') as mkdir, mock.patch('learning_store.os.rmdir') as rmdir:
            probe = probe_write(self.project, self.env)
        mkdir.assert_not_called()
        rmdir.assert_not_called()
        self.assertEqual(probe['status'], 'absent', probe)
        self.assertEqual((probe['root'], probe['ancestor']), (self.subtree, str(self.base)))
        self.assertIs(probe['ancestor_writable'], True)
        self.assertIn('advisory', probe['reason'])
        self.assertEqual(list(self.base.iterdir()), [self.project])

    def test_probe_writes_and_removes_one_file_in_an_existing_root(self):
        result = self.store.operate('write', self.proposal)
        self.assertEqual(result['status'], 'available', result)
        folder = Path(result['path']).parent
        before = sorted(p.name for p in folder.iterdir())
        with mock.patch('learning_store.os.mkdir') as mkdir, mock.patch('learning_store.os.rmdir') as rmdir:
            self.assertEqual(probe_write(self.project, self.env), {'status': 'writable', 'root': self.subtree})
        mkdir.assert_not_called()
        rmdir.assert_not_called()
        self.assertEqual(sorted(p.name for p in folder.iterdir()), before)
        self.assertEqual(sorted(p.name for p in Path(self.subtree).iterdir()), [folder.name])

    def test_probe_refuses_a_symlinked_root_and_touches_nothing_outside(self):
        outside = self.base / 'outside'
        (outside / 'kept').mkdir(parents=True)
        Path(self.subtree).parent.mkdir(parents=True)
        Path(self.subtree).symlink_to(outside)
        with mock.patch('learning_store.os.rmdir') as rmdir:
            probe = probe_write(self.project, self.env)
        rmdir.assert_not_called()
        self.assertEqual(probe['status'], 'unavailable', probe)
        self.assertEqual([p.name for p in outside.iterdir()], ['kept'])

    def test_probe_reports_a_file_it_could_not_remove(self):
        root = self.make_root()
        real_unlink = os.unlink

        def refuse_probe(name, *args, **kwargs):
            if str(name).startswith('.probe-'):
                raise OSError(errno.EACCES, 'Permission denied', name)
            return real_unlink(name, *args, **kwargs)

        with mock.patch('learning_store.os.unlink', side_effect=refuse_probe):
            probe = probe_write(self.project, self.env)
        self.assertEqual(probe['status'], 'probe_left', probe)
        self.assertEqual([p.name for p in root.iterdir()], [probe['probe']])
        self.assertIn(probe['probe'] + ' in the learnings root', probe['reason'])
        self.assertIn('left behind', probe['reason'])

    def test_probe_reports_simulated_create_denial(self):
        root = self.make_root()
        real_open = os.open

        def refuse_probe(name, *args, **kwargs):
            if str(name).startswith('.probe-'):
                raise OSError(errno.EROFS, 'Read-only file system', name)
            return real_open(name, *args, **kwargs)

        with mock.patch('learning_store.os.open', side_effect=refuse_probe):
            probe = probe_write(self.project, self.env)
        self.assertEqual(probe['status'], 'denied', probe)
        self.assert_remedies(probe['reason'])
        self.assertEqual(list(root.iterdir()), [])

    def test_probe_refuses_the_same_roots_as_store(self):
        cases = {'project-contained': str(self.project / 'state'), 'relative': 'relative/state'}
        for label, root in cases.items():
            with self.subTest(root=label):
                env = dict(self.env, XDG_STATE_HOME=root)
                with self.assertRaises(Unavailable) as raised:
                    Store(self.project, 'imps', OLD, env)
                self.assertEqual(probe_write(self.project, env), {'status': 'unavailable', 'reason': str(raised.exception)})
        self.assertEqual(list(self.project.iterdir()), [])

    def test_docs_name_both_causes_and_remedies(self):
        text = ' '.join((ROOT / 'docs/troubleshooting.md').read_text().split())
        self.assertIn('the sandbox or filesystem permissions deny', text)
        self.assertIn('read-only mount', text)
        self.assertIn('agents permissions', text)


if __name__ == '__main__':
    unittest.main()
