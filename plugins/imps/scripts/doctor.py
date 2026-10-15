#!/usr/bin/env python3
"""Local readiness for `$t3-imps doctor`, printed as one core-style JSON envelope.

Checks Python 3.10+, Git, the state root and the learnings load status. The only
write is one temporary file inside an existing state root, removed straight away; an
absent root gets no write at all. T3 capabilities are the agent's check: this process
cannot call T3 tools. Exit 0 when the required checks pass, 2 for invalid arguments,
5 when one fails."""
import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PKG = Path(__file__).resolve().parent.parent
# core/ and shared/ sit beside this package when installed, two levels up in a source checkout.
BASE = next((p for p in (PKG, PKG.parent.parent) if (p / 'core' / 'store.py').is_file()), PKG)
sys.path.insert(0, str(BASE))
MIN_PYTHON = (3, 10)
# init needs only search permission on the way down, so the walk must not ask for more.
# O_PATH (Linux) opens a directory without read permission; elsewhere O_RDONLY is the
# closest portable flag and an unreadable directory is reported as refused.
WALK = getattr(os, 'O_PATH', os.O_RDONLY) | os.O_DIRECTORY


def open_directory(path):
    """Open an absolute directory one component at a time, refusing a symlink at any of them."""
    fd = os.open('/', WALK)
    for part in Path(path).parts[1:]:
        try:
            child = os.open(part, WALK | os.O_NOFOLLOW, dir_fd=fd)
        finally:
            os.close(fd)
        fd = child
    return fd


def nearest_ancestor(root):
    """For a root with a missing component: (nearest existing ancestor, None), or (None, a dangling symlink)."""
    ancestor = Path(root.anchor)
    for prefix in [*reversed(root.parents[:-1]), root]:
        if not os.path.lexists(prefix):
            return ancestor, None
        if not os.path.exists(prefix):
            return None, prefix
        ancestor = prefix
    return ancestor, None


def refused(result, exc):
    return {**result, 'status': 'refused', 'ok': False, 'reason': f'{type(exc).__name__}: {exc}'}


def probe_state_root(root):
    """Create and remove one empty file inside the resolved root, and only when the root exists."""
    result = {'path': str(root)}
    try:
        resolved = Path(os.path.realpath(root, strict=True))
    except FileNotFoundError:
        ancestor, dangling = nearest_ancestor(root)
        if dangling:
            return {**result, 'status': 'refused', 'ok': False, 'reason': f'dangling symlink: {dangling}'}
        # Doctor writes nothing outside the state root, so this is os.access's guess, not a probe.
        return {**result, 'status': 'absent', 'ok': True, 'note': 'created on first run; nothing written',
                'advisory': {'nearest_existing_ancestor': str(ancestor),
                             'access_w_ok': os.access(ancestor, os.W_OK)}}
    except OSError as exc:
        return refused(result, exc)
    result['resolved'] = str(resolved)
    try:
        fd = open_directory(resolved)
    except OSError as exc:
        return refused(result, exc)
    name = f'.doctor-probe-{os.getpid()}-{secrets.token_hex(4)}'
    try:
        try:
            os.close(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd))
        except OSError as exc:
            return {**result, 'status': 'not_writable', 'ok': False, 'reason': f'{type(exc).__name__}: {exc.strerror}'}
        try:
            os.unlink(name, dir_fd=fd)
        except OSError as exc:
            return {**result, 'status': 'probe_left', 'ok': False, 'leftover': str(resolved / name),
                    'reason': f'{type(exc).__name__}: {exc.strerror}'}
    finally:
        os.close(fd)
    return {**result, 'status': 'writable', 'ok': True}


def learnings(project):
    """Advisory: the helper's own load receipt, summarised. Never fails doctor."""
    try:
        # -B: doctor must not leave bytecode caches in the installed package.
        loaded = subprocess.run([sys.executable, '-B', str(BASE / 'shared' / 'learnings.py'), 'load',
                                 '--project', str(project), '--package', str(PKG)],
                                capture_output=True, text=True, timeout=60)
        receipt = json.loads(loaded.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        receipt = {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}'}
    if receipt.get('status') == 'available':
        return {'status': 'available', 'entries': len(receipt['data']['entries']),
                'pending_maintenance': receipt['pending_maintenance']}
    return {'status': receipt.get('status'), 'reason': receipt.get('reason')}


def recorded_identity_reporting(jobs_state_root):
    """Summarise identity observations in saved jobs without consulting the host."""
    unreported = set()
    known_providers = set()
    observed_providers = set()
    root = Path(jobs_state_root)
    try:
        job_files = sorted(root.glob('*/job.json'))
    except OSError:
        job_files = []
    for path in job_files:
        try:
            if path.stat().st_size > 16 * 1024 * 1024:
                continue
            job = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError):
            continue
        if not isinstance(job, dict):
            continue
        tasks = list(job.get('tasks', []))
        for historic in job.get('history', []):
            if isinstance(historic, dict):
                tasks.extend(historic.get('tasks', []))
        for task in tasks:
            if not isinstance(task, dict):
                continue
            target = task.get('target')
            if isinstance(target, dict) and isinstance(target.get('providerInstanceId'), str):
                known_providers.add(target['providerInstanceId'])
            records = []
            for key in ('handles', 'followups', 'execution_history', 'dispatch_history', 'host_conflicts'):
                records.extend(task.get(key, []))
            for record in records:
                if not isinstance(record, dict):
                    continue
                observed = record.get('observed_identity')
                if not isinstance(observed, dict):
                    continue
                provider = observed.get('providerInstanceId')
                if not isinstance(provider, str) or not provider:
                    continue
                observed_providers.add(provider)
                if observed.get('status') == 'unreported' and not observed.get('model'):
                    unreported.add(provider)
    return {
        'source': 'recorded host observations only',
        'providers_with_unreported_model': sorted(unreported),
        'identity_reporting_unverified': sorted(known_providers - observed_providers),
        'launches_nothing': True,
    }


def doctor(state_root, project, jobs_state_root=None):
    from core.store import env_state_root
    meta = json.loads((PKG / 'plugin.json').read_text())
    version = meta['version']
    if (PKG / 'install-manifest.json').is_file():
        version = json.loads((PKG / 'install-manifest.json').read_text())['version']
    root = Path(state_root).expanduser().absolute() if state_root else env_state_root(meta['name'])
    jobs_root = Path(jobs_state_root).expanduser().absolute() if jobs_state_root else env_state_root('imps').parent / 'jobs'
    checks = {'python': {'ok': sys.version_info[:2] >= MIN_PYTHON, 'version': '.'.join(map(str, sys.version_info[:3])),
                         'required': '.'.join(map(str, MIN_PYTHON)) + '+'}}
    try:
        git = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=10)
        checks['git'] = ({'ok': True, 'version': git.stdout.strip()} if git.returncode == 0
                         else {'ok': False, 'reason': git.stderr.strip() or f'exit {git.returncode}'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks['git'] = {'ok': False, 'reason': f'{type(exc).__name__}: {exc}'}
    checks['state_root'] = probe_state_root(root)
    checks['learnings'] = learnings(project)
    failed = [name for name in ('python', 'git', 'state_root') if not checks[name]['ok']]
    return {'plugin': meta['name'], 'version': version, 'project': str(project), 'checks': checks,
            'failed': failed, 'identity_reporting': recorded_identity_reporting(jobs_root),
            'agent_checks': ['orchestrator_capabilities']}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cli.py doctor', description=__doc__.split('\n')[0])
    parser.add_argument('--state-root')
    parser.add_argument('--jobs-state-root', help=argparse.SUPPRESS)
    parser.add_argument('--repo', default='.', help='project whose learnings to load (default: cwd)')
    envelope = {'schema_version': 1, 'ok': False, 'op': 'doctor', 'run_id': None}
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        error, code = {'code': 'usage', 'message': 'invalid arguments; see --help on stderr', 'details': {}}, 2
    else:
        try:
            data = doctor(args.state_root, Path(args.repo).absolute(), args.jobs_state_root)
        except (OSError, ValueError, KeyError) as exc:
            error, code = {'code': 'io_error', 'message': f'{type(exc).__name__}: {exc}', 'details': {}}, 5
        else:
            if not data['failed']:
                print(json.dumps({**envelope, 'ok': True, 'data': data}))
                return 0
            error = {'code': 'doctor_failed', 'message': 'failed checks: ' + ', '.join(data['failed']),
                     'details': data}
            code = 5
    print(json.dumps({**envelope, 'error': error}))
    print(f"{error['code']}: {error['message']}", file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
