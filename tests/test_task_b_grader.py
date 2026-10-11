"""The behaviour grader's inode simulation preserves real filesystem evidence."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('task_b_grader', Path(__file__).resolve().parents[1] / 'bench/checks/task_b.py')
grader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grader)


class InodeSimulationTest(unittest.TestCase):
    def test_only_inode_changes_and_nanoseconds_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'real'
            path.write_text('real bytes')
            os.utime(path, ns=(1700000000123456789, 1700000000987654321))
            real = path.stat()
            wrapped = grader.inode_wrapper(os.stat, {str(path): real.st_ino + 1})(path)
            self.assertEqual(wrapped.st_ino, real.st_ino + 1)
            self.assertEqual(wrapped[1], real.st_ino + 1)
            for name in dir(real):
                if name.startswith('st_') and name != 'st_ino':
                    self.assertEqual(getattr(wrapped, name), getattr(real, name), name)
            self.assertEqual(tuple(wrapped)[2:], tuple(real)[2:])
            self.assertEqual(path.read_text(), 'real bytes')
            self.assertEqual(grader.inode_wrapper(os.stat, {})(path), path.stat())
            with path.open() as handle:
                self.assertEqual(grader.inode_wrapper(os.stat, {str(path): 0})(handle.fileno()), os.fstat(handle.fileno()))

    def test_symlinks_keep_real_lstat_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'link'
            path.symlink_to('missing')
            real = path.lstat()
            result = grader.inode_wrapper(os.lstat, {str(path): 42})(path)
            self.assertEqual(result.st_ino, 42)
            self.assertEqual(result.st_mode, real.st_mode)
            self.assertEqual(result.st_ctime_ns, real.st_ctime_ns)


if __name__ == '__main__':
    unittest.main()
