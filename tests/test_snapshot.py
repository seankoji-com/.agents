"""Snapshot guarantees retained from the prior evidence gate regressions."""
import os
from support import CoreTestCase, git
from core import snapshot


class SnapshotTest(CoreTestCase):
    def test_changed_since_tracks_index_content_and_preserves_existing_staged_work(self):
        repo = self.make_repo()
        source = repo / 'wordstat.py'
        original = source.read_bytes()
        baseline = snapshot.baseline(repo)
        source.write_text('first staged content\n')
        git(repo, 'add', 'wordstat.py')
        source.write_bytes(original)
        self.assertEqual(snapshot.changed_since(repo, baseline), {'wordstat.py'})
        existing = snapshot.baseline(repo)
        self.assertEqual(snapshot.changed_since(repo, existing), set())
        source.write_text('second staged content\n')
        git(repo, 'add', 'wordstat.py')
        source.write_bytes(original)
        self.assertEqual(snapshot.changed_since(repo, existing), {'wordstat.py'})
        # Previously saved baselines conservatively report staged candidates.
        legacy = dict(existing)
        legacy.pop('index')
        self.assertEqual(snapshot.changed_since(repo, legacy), {'wordstat.py'})

    def test_changed_since_tracks_staged_add_delete_and_mode_changes(self):
        repo = self.make_repo()
        baseline = snapshot.baseline(repo)
        source = repo / 'wordstat.py'
        original = source.read_bytes()
        git(repo, 'rm', '--cached', 'wordstat.py')
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(snapshot.changed_since(repo, baseline), {'wordstat.py'})
        git(repo, 'add', 'wordstat.py')
        git(repo, 'update-index', '--chmod=+x', 'wordstat.py')
        self.assertEqual(snapshot.changed_since(repo, baseline), {'wordstat.py'})
        git(repo, 'update-index', '--chmod=-x', 'wordstat.py')
        added = repo / 'new staged.txt'
        added.write_text('staged addition\n')
        git(repo, 'add', added.name)
        added.unlink()
        self.assertEqual(snapshot.changed_since(repo, baseline), {added.name})

    def test_executable_bit_change_invalidates_even_with_same_porcelain(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, policy={'checks': [], 'review': {'required': False}}))
        (repo/'wordstat.py').write_text('already dirty\n')
        os.chmod(repo/'wordstat.py', 0o755)
        run.evidence('REQ-MULTILINE', run.scratch('proof', 'ok'))
        self.assertTrue(run.validate()['ready'])
        porcelain = git(repo, 'status', '--porcelain').stdout
        os.chmod(repo/'wordstat.py', 0o644)
        self.assertEqual(git(repo, 'status', '--porcelain').stdout, porcelain)
        self.assertEqual(run.validate()['status'], 'stale')

    def test_staged_bytes_change_invalidates_with_same_working_bytes(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, policy={'checks': [], 'review': {'required': False}}))
        source = repo/'wordstat.py'
        source.write_text('first\n')
        git(repo,'add','wordstat.py')
        source.write_text('working\n')
        run.evidence('REQ-MULTILINE',run.scratch('proof','ok'))
        self.assertTrue(run.validate()['ready'])
        source.write_text('second\n')
        git(repo,'add','wordstat.py')
        source.write_text('working\n')
        self.assertEqual(run.validate()['status'],'stale')

    def test_dirty_submodule_content_invalidates_with_same_porcelain(self):
        repo = self.make_repo()
        sub = self.tmp/'subsrc'
        sub.mkdir()
        (sub/'lib.py').write_text('X = 1\n')
        git(sub,'init','-q','-b','main')
        git(sub,'add','-A')
        git(sub,'commit','-qm','lib')
        git(repo,'-c','protocol.file.allow=always','submodule','add','-q',str(sub),'dep')
        git(repo,'commit','-qm','add dep')
        run=self.init(self.plan(repo,policy={'checks': [], 'review': {'required': False}}))
        (repo/'dep/lib.py').write_text('X = 2\n')
        run.evidence('REQ-MULTILINE',run.scratch('proof','ok'))
        self.assertTrue(run.validate()['ready'])
        porcelain=git(repo,'status','--porcelain').stdout
        (repo/'dep/lib.py').write_text('X = 3\n')
        self.assertEqual(git(repo,'status','--porcelain').stdout,porcelain)
        self.assertEqual(run.validate()['status'],'stale')

    def test_tracked_symlink_into_exclusion_and_symlink_loop_are_hashed(self):
        repo=self.make_repo()
        goal=repo/'goal.md'
        goal.write_text('goal\n')
        before=snapshot.take(repo,[goal])
        (repo/'wordstat.py').unlink()
        (repo/'wordstat.py').symlink_to(goal)
        self.assertNotEqual(snapshot.token(snapshot.take(repo,[goal])),snapshot.token(before))
        (repo/'loop').symlink_to(repo/'loop')
        snapshot.take(repo,[goal])

    def test_symlink_target_change_invalidates(self):
        repo=self.make_repo()
        link=repo/'link'
        link.symlink_to('wordstat.py')
        before=snapshot.take(repo)
        link.unlink()
        link.symlink_to('notes.txt')
        self.assertFalse(snapshot.same(before,snapshot.take(repo)))
