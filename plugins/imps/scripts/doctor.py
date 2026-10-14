#!/usr/bin/env python3
"""Local readiness for `$t3-imps doctor`, printed as one core-style JSON envelope.

Checks Python 3.10+, Git, state-root writability (a probe file, removed before
returning) and the learnings load status. Changes nothing else. T3 capabilities
are the agent's check: this process cannot call T3 tools. Exit 0 when the
required checks pass, 2 for invalid arguments, 5 when one fails."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
PKG = Path(__file__).resolve().parent.parent
# core/ and shared/ sit beside this package when installed, two levels up in a source checkout.
BASE = next((p for p in (PKG, PKG.parent.parent) if (p / 'core' / 'store.py').is_file()), PKG)
sys.path.insert(0, str(BASE))
MIN_PYTHON = (3, 10)


def probe_writable(root):
    """Create and remove one file where `init` would first write: the root, or its nearest existing ancestor."""
    target = root
    while not target.exists() and target != target.parent:
        target = target.parent
    result = {'path': str(root), 'exists': root.is_dir(), 'probed': str(target)}
    try:
        handle, name = tempfile.mkstemp(prefix='.doctor-probe-', dir=target)
        try:
            os.write(handle, b'probe\n')
        finally:
            os.close(handle)
            os.unlink(name)
    except OSError as exc:
        return {**result, 'ok': False, 'reason': f'{type(exc).__name__}: {exc.strerror or exc}'}
    return {**result, 'ok': True}


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


def doctor(state_root, project):
    from core.store import env_state_root
    meta = json.loads((PKG / 'plugin.json').read_text())
    version = meta['version']
    if (PKG / 'install-manifest.json').is_file():
        version = json.loads((PKG / 'install-manifest.json').read_text())['version']
    root = Path(state_root).expanduser().absolute() if state_root else env_state_root(meta['name'])
    checks = {'python': {'ok': sys.version_info[:2] >= MIN_PYTHON, 'version': '.'.join(map(str, sys.version_info[:3])),
                         'required': '.'.join(map(str, MIN_PYTHON)) + '+'}}
    try:
        git = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=10)
        checks['git'] = ({'ok': True, 'version': git.stdout.strip()} if git.returncode == 0
                         else {'ok': False, 'reason': git.stderr.strip() or f'exit {git.returncode}'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks['git'] = {'ok': False, 'reason': f'{type(exc).__name__}: {exc}'}
    checks['state_root'] = probe_writable(root)
    checks['learnings'] = learnings(project)
    failed = [name for name in ('python', 'git', 'state_root') if not checks[name]['ok']]
    return {'plugin': meta['name'], 'version': version, 'project': str(project), 'checks': checks,
            'failed': failed, 'agent_checks': ['orchestrator_capabilities']}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cli.py doctor', description=__doc__.split('\n')[0])
    parser.add_argument('--state-root')
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
            data = doctor(args.state_root, Path(args.repo).absolute())
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
