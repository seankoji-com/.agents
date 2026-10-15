#!/usr/bin/env python3
"""Read-only local readiness and recorded identity report for elephant-goldfish."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PKG = Path(__file__).resolve().parent.parent
BASE = next((p for p in (PKG, PKG.parent.parent) if (p / 'shared' / 'identity_reporting.py').is_file()), PKG)
sys.path.insert(0, str(BASE))
from shared.identity_reporting import recorded_identity_reporting


def check(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return {'ok': result.returncode == 0, 'output': (result.stdout or result.stderr).strip(),
                'exit_code': result.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'ok': False, 'output': f'{type(exc).__name__}: {exc}', 'exit_code': None}


def doctor(jobs_state_root=None):
    checks = {
        'python': {'ok': sys.version_info[:2] >= (3, 10), 'version': '.'.join(map(str, sys.version_info[:3])),
                   'required': '3.10+'},
        'thinking_state': check([sys.executable, '-B', str(PKG / 'scripts' / 'thinking_state.py'), '--help']),
        'installed_bundle': check(['t3-plugins', 'agents', 'list', 'elephant-goldfish']),
    }
    from core.store import env_state_root
    root = Path(jobs_state_root).expanduser().absolute() if jobs_state_root else env_state_root('imps').parent / 'jobs'
    failed = [name for name, value in checks.items() if not value['ok']]
    return {'plugin': 'elephant-goldfish', 'checks': checks, 'failed': failed,
            'identity_reporting': recorded_identity_reporting(root)}


def main(argv=None):
    envelope = {'schema_version': 1, 'ok': False, 'op': 'doctor', 'run_id': None}
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--jobs-state-root', help=argparse.SUPPRESS)
        data = doctor(parser.parse_args(argv).jobs_state_root)
    except (OSError, ValueError, KeyError) as exc:
        code, output = 5, {**envelope, 'error': {'code': 'doctor_failed', 'message': f'{type(exc).__name__}: {exc}'}}
    else:
        code = 0 if not data['failed'] else 5
        output = ({**envelope, 'ok': True, 'data': data} if code == 0 else
                  {**envelope, 'error': {'code': 'doctor_failed', 'message': 'failed checks: ' + ', '.join(data['failed']),
                                         'details': data}})
    print(json.dumps(output))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
