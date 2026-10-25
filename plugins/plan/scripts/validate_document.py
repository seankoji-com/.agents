#!/usr/bin/env python3
"""Validate source-plan readiness and deterministic handoff provenance."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='plans')
    parser.add_argument('--slug', required=True)
    parser.add_argument('--mode', choices=('plan-review', 'handoff'), default='handoff')
    args = parser.parse_args(argv)
    scripts = Path(__file__).resolve().parent
    required = 'discovery,spec,plan_review' + (',handoff' if args.mode == 'handoff' else '')
    checks = [[sys.executable, str(scripts / 'plan_state.py'), '--root', args.root,
               'gate', args.slug, '--require', required]]
    if args.mode == 'handoff':
        checks.append([sys.executable, str(scripts / 'render_handoff.py'), args.slug,
                       '--root', args.root, '--check'])
    evidence = []
    for command in checks:
        result = subprocess.run(command, capture_output=True, text=True)
        evidence.append({'argv': command, 'exit_code': result.returncode,
                         'output': result.stdout[-2000:]})
    accepted = all(row['exit_code'] == 0 for row in evidence)
    print(json.dumps({'accepted': accepted, 'mode': args.mode,
                      'requirement_outcomes': {'workflow-observation': {
                          'status': 'passed' if accepted else 'unverified',
                          'evidence': evidence}}}, sort_keys=True))
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
