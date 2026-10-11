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

    def test_descriptors_scandir_and_pathlib_share_the_same_inode_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'index'
            path.write_text('before')
            before = grader.inode_snapshot([root])
            # Keeping the old inode alive forces a different real inode for the replacement.
            path.rename(root / 'old-index')
            path.write_text('after')
            simulation = grader.ReusedInodes(before)
            with path.open() as handle, simulation.patches():
                self.assertEqual(os.fstat(handle.fileno()).st_ino, before[str(path)])
                self.assertEqual(os.stat(handle.fileno()).st_ino, before[str(path)])
                self.assertEqual(path.stat().st_ino, before[str(path)])
                with os.scandir(root) as entries:
                    entry = next(e for e in entries if e.name == 'index')
                    self.assertEqual(entry.inode(), before[str(path)])
                    self.assertEqual(entry.stat().st_ino, before[str(path)])
                    self.assertEqual(entry.stat().st_size, len('after'))


class BehaviourProbeTest(unittest.TestCase):
    """Minimal old CLI seam, real Git resources, several independent fix designs."""

    def tree(self, root, read, extra='', guard='current == recorded'):
        (root / 'core').mkdir()
        (root / 'core/__init__.py').write_text('')
        (root / 'tests/fixtures/t3').mkdir(parents=True)
        (root / 'tests/fixtures/t3/capabilities.json').write_text('{}')
        (root / 'core/resources.py').write_text(
            'import os, subprocess\nfrom pathlib import Path\n'
            'def capture(path):\n'
            '    gitdir = subprocess.check_output(["git", "-C", str(path), "rev-parse", "--absolute-git-dir"], text=True).strip()\n'
            f'    return {{"renamed_inode": {read}, {extra}}}\n')
        (root / 'core/engine.py').write_text(
            'from .resources import capture\n'
            'def cleanup_action(item):\n'
            '    current, recorded = capture(item["path"]), item["identity"]\n'
            f'    return {{"args": {{"argv": item["cleanup_argv"] if {guard} else None, "identity": "arbitrary-label"}}}}\n')
        (root / 'core/cli.py').write_text('''import sys, json, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.resources import capture
p = argparse.ArgumentParser()
p.add_argument('op')
for name in ('state-root','plugin-dir','parent-thread-id','run-id','input','kind','token','expect-generation'):
    p.add_argument('--'+name)
a = p.parse_args()
root = Path(a.state_root)/'runs'/'fixture'; root.mkdir(parents=True, exist_ok=True)
file = root/'run.json'
state = json.loads(file.read_text()) if file.exists() else {}
payload = json.loads(Path(a.input).read_text()) if a.input else {}
data = {'generation': 1}
if a.op == 'init': state['plan'] = payload
elif a.op == 'claim': data['token'] = 'fixture-token'
elif a.op == 'next':
    plan = state['plan']; path = str(Path(plan['policy']['worktree_root'])/'owned')
    data['actions'] = [{'action':'create_worktree','id':'fixture','args':{'argv':['git','-C',plan['repo']['worktree'],'worktree','add','-q','-b','owned',path], 'path':path,'branch':'owned','name':'owned'}}]
elif a.op == 'record' and a.kind == 'resource':
    state['resources'] = [dict(payload, identity=capture(payload['path']), cleanup_argv=['git','-C',state['plan']['repo']['worktree'],'worktree','remove',payload['path']])]
file.write_text(json.dumps(state))
print(json.dumps({'ok':True,'run_id':'fixture','data':data}))
''')
        return root

    def test_inode_only_mutants_and_refuse_everything_fail(self):
        designs = [
            ('path', 'os.stat(gitdir).st_ino', '', 'current == recorded'),
            ('fd_stat', 'os.stat(os.open(gitdir, os.O_RDONLY)).st_ino', '', 'current == recorded'),
            ('fstat', 'os.fstat(os.open(gitdir, os.O_RDONLY)).st_ino', '', 'current == recorded'),
            ('extra_inode', 'os.stat(gitdir).st_ino', '"third_inode": os.stat(Path(gitdir)/"index").st_ino', 'current == recorded'),
            ('scandir', 'next(e for e in os.scandir(gitdir) if e.name == "index").inode()', '', 'current == recorded'),
            ('pathlib', 'Path(gitdir).stat().st_ino', '', 'current == recorded'),
            ('refuse_all', 'os.stat(gitdir).st_ino', '', 'False'),
        ]
        for name, read, extra, guard in designs:
            with self.subTest(design=name), tempfile.TemporaryDirectory() as tmp:
                report = grader.grade(self.tree(Path(tmp), read, extra, guard))
                self.assertNotIn('error', report, report)
                self.assertFalse(report['ok'], report)
                if name != 'refuse_all':
                    self.assertTrue(report['untouched_offered'])
                    self.assertFalse(report['replacement_refused'])

    def test_real_timestamp_fix_passes_with_renamed_identity_and_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = grader.grade(self.tree(Path(tmp), 'os.stat(gitdir).st_ino',
                                            '"ctime": os.lstat(Path(path)/".git").st_ctime_ns'))
            self.assertNotIn('error', report, report)
            self.assertTrue(report['ok'], report)


if __name__ == '__main__':
    unittest.main()
