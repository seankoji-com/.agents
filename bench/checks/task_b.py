#!/usr/bin/env python3
"""Grade cleanup behaviour on real, CLI-recorded worktrees, independent of fix design.

Only st_ino is overridden after replacement. Every other stat attribute, owner
file, git pointer and git command remains real. Each target runs in a separate
Python process so its core imports cannot contaminate another target's grade.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from contextlib import ExitStack


class InodeStat:
    """Forward the real stat result, including nanoseconds, changing only its inode."""

    def __init__(self, real, inode):
        self.real, self.st_ino = real, inode

    def __getattr__(self, name):
        return getattr(self.real, name)

    def __getitem__(self, index):
        return tuple(self)[index]

    def __iter__(self):
        values = list(self.real)
        values[1] = self.st_ino
        return iter(values)

    def __len__(self):
        return len(self.real)


def inode_wrapper(real, numbers):
    def wrapped(path, *args, **kwargs):
        found = real(path, *args, **kwargs)
        key = os.path.abspath(os.fsdecode(path)) if isinstance(path, (str, bytes, os.PathLike)) else None
        return InodeStat(found, numbers[key]) if key in numbers else found
    return wrapped


def inode_snapshot(roots):
    """Capture every existing path, without relying on the target identity schema."""
    found = {}
    for root in roots:
        paths = [root, *root.rglob('*')] if root.is_dir() else [root]
        for path in paths:
            stat = path.lstat()
            found[str(path)] = stat.st_ino
    return found


class ReusedInodes:
    """Override by real device/inode, so descriptors and extra paths are covered."""

    def __init__(self, before=None):
        self.mapping = {}
        self.hits = 0
        self.paths = 0
        self.real_lstat = os.lstat
        if before is not None:
            self.populate(before)

    def populate(self, before):
        mapping = {}
        for path, inode in before.items():
            try:
                current = self.real_lstat(path)
            except FileNotFoundError:
                continue  # Missing owner files stay missing.
            key = (current.st_dev, current.st_ino)
            if key in mapping and mapping[key] != inode:
                raise RuntimeError('ambiguous hardlink inode mapping')
            mapping[key] = inode
            self.paths += 1
        self.mapping = mapping

    def convert(self, stat):
        key = (stat.st_dev, stat.st_ino)
        if key in self.mapping:
            self.hits += 1
            return InodeStat(stat, self.mapping[key])
        return stat

    def wrap(self, real):
        def wrapped(*args, **kwargs):
            return self.convert(real(*args, **kwargs))
        return wrapped

    def wrap_scandir(self, real):
        owner = self
        class Entry:
            def __init__(self, entry): self.entry = entry
            def __getattr__(self, name): return getattr(self.entry, name)
            def __fspath__(self): return os.fspath(self.entry)
            def inode(self): return owner.convert(self.entry.stat(follow_symlinks=False)).st_ino
            def stat(self, *, follow_symlinks=True):
                return owner.convert(self.entry.stat(follow_symlinks=follow_symlinks))
        class Iterator:
            def __init__(self, iterator): self.iterator = iterator
            def __iter__(self): return self
            def __next__(self): return Entry(next(self.iterator))
            def __enter__(self): self.iterator.__enter__(); return self
            def __exit__(self, *args): return self.iterator.__exit__(*args)
            def close(self): return self.iterator.close()
        def wrapped(*args, **kwargs): return Iterator(real(*args, **kwargs))
        return wrapped

    def patches(self):
        stack = ExitStack()
        # Python 3.10 pathlib keeps bound accessor functions. Capture and patch
        # them separately, before os.stat itself is replaced.
        accessor = getattr(Path, '_accessor', None)
        if accessor is not None:
            for name in ('stat', 'lstat'):
                if hasattr(accessor, name):
                    stack.enter_context(patch.object(accessor, name, self.wrap(getattr(accessor, name))))
            if hasattr(accessor, 'scandir'):
                stack.enter_context(patch.object(accessor, 'scandir', self.wrap_scandir(accessor.scandir)))
        stack.enter_context(patch.multiple(os, stat=self.wrap(os.stat), lstat=self.wrap(os.lstat),
                                          fstat=self.wrap(os.fstat), scandir=self.wrap_scandir(os.scandir)))
        native = sys.modules[os.name]
        stack.enter_context(patch.multiple(native, stat=self.wrap(native.stat), lstat=self.wrap(native.lstat),
                                          fstat=self.wrap(native.fstat), scandir=self.wrap_scandir(native.scandir)))
        return stack


def command(argv, cwd, env):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                          check=True, timeout=120).stdout.strip()


def probe(tree: Path) -> dict:
    simulation = ReusedInodes()
    # Imported aliases and default arguments must bind the same mutable wrapper.
    with simulation.patches():
        return patched_probe(tree, simulation)


def patched_probe(tree: Path, simulation: ReusedInodes) -> dict:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(tree))
    from core import engine

    with tempfile.TemporaryDirectory(prefix='task-b-behaviour-') as tmp:
        root = Path(tmp).resolve()
        home = root / 'home'
        home.mkdir()
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                   XDG_STATE_HOME=str(home / 'state'), PYTHONDONTWRITEBYTECODE='1',
                   GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                   GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'T3_PARENT_THREAD_ID'):
            env.pop(key, None)
        repo = root / 'repo'
        repo.mkdir()
        def git(*args):
            return command(['git', *args], repo, env)
        git('init', '-q', '-b', 'main')
        (repo / 'file.txt').write_text('real worktree content\n')
        git('add', 'file.txt')
        git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
        plan = {'schema_version': 1,
                'brief': {'text': 'Check worktree cleanup ownership',
                          'requirements': [{'id': 'REQ-CLEANUP', 'text': 'Preserve unrelated worktrees', 'kind': 'command'}]},
                'repo': {'worktree': str(repo), 'base_ref': 'HEAD'},
                'authorization': {'endstate': 'local', 'evidence': 'behaviour grader'},
                'execution': {'mode': 'delegated', 'isolation': 'parallel'},
                'host': {'parent_thread_id': 'grader-parent'},
                'tasks': [{'id': 'fix', 'purpose': 'Check cleanup', 'files': ['file.txt']}],
                'policy': {'checks': [], 'review': {'required': False}, 'worktree_root': str(root / 'worktrees')}}
        run_id, token, generation = None, None, None
        def cli(op, payload=None, kind=None):
            nonlocal run_id, token, generation
            argv = [sys.executable, str(tree / 'core/cli.py'), op, '--state-root', str(root / 'state'),
                    '--plugin-dir', str(tree / 'plugins/imps'), '--parent-thread-id', 'grader-parent']
            if run_id: argv += ['--run-id', run_id]
            if payload is not None:
                file = root / 'input.json'
                file.write_text(json.dumps(payload))
                argv += ['--input', str(file)]
            if kind:
                argv += ['--kind', kind, '--token', token, '--expect-generation', str(generation)]
            data = json.loads(command(argv, tree, env))
            if not data['ok']: raise RuntimeError(data)
            run_id = data.get('run_id') or run_id
            generation = data['data'].get('generation', generation)
            return data['data']
        cli('init', plan)
        token = cli('claim')['token']
        caps = json.loads((tree / 'tests/fixtures/t3/capabilities.json').read_text())
        cli('record', {'response': caps}, 'capabilities')
        cli('record', {'to': 'executing'}, 'transition')
        action = next(a for a in cli('next')['actions'] if a['action'] == 'create_worktree')
        args = action['args']
        command(args['argv'], repo, env)
        cli('record', {'action_id': action['id'], 'kind': 'worktree', 'name': args['name'],
                       'path': args['path'], 'branch': args['branch'], 'task_id': 'fix'}, 'resource')
        state = json.loads((root / 'state/runs' / run_id / 'run.json').read_text())
        item = next(r for r in state['resources'] if r['kind'] == 'worktree')
        gitdir = Path(command(['git', '-C', item['path'], 'rev-parse', '--absolute-git-dir'], repo, env))
        # Git removes the containing .git/worktrees directory with its last
        # worktree. Include all repository metadata and the worktree root too.
        numbers = inode_snapshot([Path(item['path']).parent, repo / '.git'])
        untouched = engine.cleanup_action(item)['args']
        positive = untouched['argv'] is not None
        git('worktree', 'remove', item['path'])
        git('worktree', 'add', '-q', item['path'], item['branch'])
        before = {p: simulation.real_lstat(p) for p in numbers if Path(p).exists() or Path(p).is_symlink()}
        simulation.populate(numbers)
        fields_real = True
        # Explicitly prove that all original path inode numbers match, while the
        # timestamp and device fields remain those of the replacement.
        for p, real in before.items():
            found = os.lstat(p)
            if found.st_ino != numbers[p]:
                raise RuntimeError('inode simulation did not apply')
            for field in ('st_dev', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns'):
                fields_real = fields_real and getattr(found, field) == getattr(real, field)
        if not fields_real:
            raise RuntimeError('simulation changed non-inode stat fields')
        simulation.hits = 0
        replaced = engine.cleanup_action(item)['args']
        negative = replaced['argv'] is None
        if (Path(item['path']) / 'file.txt').read_text() != 'real worktree content\n':
            raise RuntimeError('replacement file bytes changed')
        return {'ok': positive and negative, 'untouched_offered': positive,
                'replacement_refused': negative, 'replacement_identity': replaced['identity'],
                'simulated_path_count': simulation.paths, 'cleanup_inode_reads': simulation.hits,
                'other_stat_fields_real': fields_real,
                'resource_recorded_via_cli': True}


def grade(tree: Path) -> dict:
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(tree), '--probe'],
                            capture_output=True, text=True, timeout=300)
    if result.returncode and not result.stdout.strip():
        return {'ok': False, 'error': result.stderr[-4000:], 'exit_code': result.returncode}
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tree', type=Path)
    parser.add_argument('--probe', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    report = probe(args.tree.resolve()) if args.probe else grade(args.tree.resolve())
    report['grader_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
