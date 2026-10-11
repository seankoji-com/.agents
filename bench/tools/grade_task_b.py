#!/usr/bin/env python3
"""Apply the private Task B grader bundle to a finished run and report the result.

The bundle is the test file the upstream fix added. It lives in the private results
directory, never in this repository; only its sha256 is committed here. The script
refuses a bundle whose hash differs, clones the run's committed `HEAD` into a
temporary directory, adds the hidden test, and runs it. The run's workspace is not
modified. With --full it also runs the workspace's whole suite, for information.

Usage: python3 bench/tools/grade_task_b.py WORKSPACE BUNDLE [--full] [--json]
Exit status: 0 when the hidden tests pass, 1 when they fail, 2 on a bad bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BUNDLE_SHA256 = '19f12fe6d38ff0991c2f7000d3cb819d51f8ae58cb4f7122ba81610333d2465c'
TEST_PATH = 'tests/test_resources_identity.py'


def run(argv, cwd) -> dict:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=1800)
    return {'argv': argv, 'exit_code': result.returncode, 'tail': (result.stdout + result.stderr)[-4000:]}


def grade(workspace: Path, bundle: Path, full: bool) -> dict:
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if digest != BUNDLE_SHA256:
        return {'ok': False, 'error': f'bundle sha256 {digest} != {BUNDLE_SHA256}'}
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=workspace, capture_output=True, text=True,
                          check=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / 'tree'
        subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(workspace), str(tree)], check=True,
                       capture_output=True)
        target = tree / TEST_PATH
        replaced = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bundle.read_bytes())
        hidden = run([sys.executable, '-m', 'unittest', '-v', 'tests.test_resources_identity'], tree)
        report = {'ok': hidden['exit_code'] == 0, 'head': head, 'bundle_sha256': digest,
                  'replaced_existing_file': replaced, 'hidden': hidden}
        if full:
            report['full_suite'] = run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], tree)
        return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('workspace', type=Path)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    report = grade(args.workspace.resolve(), args.bundle.resolve(), args.full)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(report.get('error') or f"hidden tests {'passed' if report['ok'] else 'failed'} at {report['head']}")
    if 'error' in report:
        return 2
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
