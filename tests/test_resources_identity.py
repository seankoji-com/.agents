"""Worktree cleanup must refuse replacements even when inodes are reused."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import engine, resources


class WorktreeIdentityTest(unittest.TestCase):
    def test_failed_identity_capture_never_authorizes_cleanup(self):
        for error in (FileNotFoundError, PermissionError):
            with self.subTest(error=error), \
                    patch.object(resources, '_git', return_value='/fixture/admin'), \
                    patch.object(resources.os, 'lstat', side_effect=error):
                recorded = resources.worktree_identity('/fixture/tree')
                self.assertIsNone(recorded)
            item = {'id': 'R-fixture', 'kind': 'worktree', 'path': '/fixture/tree',
                    'identity': recorded, 'cleanup_argv': ['git', 'worktree', 'remove', '/fixture/tree']}
            # The path is present again, but capture never established ownership.
            with patch.object(resources, '_exists', return_value=True):
                action = engine.cleanup_action(item)
                self.assertEqual(action['args']['identity'], 'replaced')
                self.assertIsNone(action['args']['argv'])
                self.assertFalse(resources.live(item))
                del item['identity']
                self.assertIsNone(engine.cleanup_action(item)['args']['argv'])

    def test_reused_inodes_do_not_authorize_cleanup(self):
        with patch.object(resources, '_git', return_value='/fixture/admin'), \
                patch.object(resources.os, 'stat', return_value=SimpleNamespace(st_ino=10)), \
                patch.object(resources.os, 'lstat') as lstat, \
                patch.object(resources, '_exists', return_value=True):
            lstat.return_value = SimpleNamespace(st_ino=20, st_dev=1, st_ctime_ns=100)
            original = resources.worktree_identity('/fixture/tree')
            item = {'kind': 'worktree', 'path': '/fixture/tree', 'identity': original}
            self.assertEqual(resources.identity(item), 'live')
            # Both inodes and the path are reused, but the pointer file is new.
            lstat.return_value = SimpleNamespace(st_ino=20, st_dev=1, st_ctime_ns=200)
            self.assertEqual(resources.identity(item), 'replaced')
            self.assertFalse(resources.live(item))

    def test_legacy_inode_only_identity_is_not_cleanup_authority(self):
        with patch.object(resources, '_exists', return_value=True), \
                patch.object(resources, 'worktree_identity', return_value={
                    'gitdir': '/fixture/admin', 'gitdir_inode': 10,
                    'dotgit_inode': 20, 'dotgit_device': 1, 'dotgit_ctime_ns': 100}):
            item = {'kind': 'worktree', 'path': '/fixture/tree', 'identity': {
                'gitdir': '/fixture/admin', 'gitdir_inode': 10, 'dotgit_inode': 20}}
            self.assertEqual(resources.identity(item), 'replaced')
