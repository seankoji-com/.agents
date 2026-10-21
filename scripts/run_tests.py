#!/usr/bin/env python3
"""Run the unittest suite one module per process, several at a time.

The suite is mostly integration tests: each one drives the core CLI and git in
temporary repositories, so it spends its time waiting on child processes. Every test
owns its temporary directories, which makes modules safe to run side by side.
``python3 -m unittest discover -s tests`` runs the same tests one module after another.

Two checks are stricter than unittest's: a module that collects no tests fails (a
test file that runs nothing is a mistake, and unittest before 3.12 exits 0 on it),
and a module that runs past --timeout seconds is stopped and fails.

Usage: python3 scripts/run_tests.py [-j N] [--timeout S] [pattern ...]
       python3 scripts/run_tests.py --shard-index I --shard-count N [pattern ...]
Patterns filter module file names (``test_review*``). Exit status is 1 if any
module fails, with that module's full output printed. Zero-based shards partition
the selected ordered modules: run every index in range(N) for the complete suite.
Sharding changes neither test discovery within a module nor its failure deadline.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / 'tests'
DURATIONS = ROOT / 'scripts' / 'test_durations.json'
RAN = re.compile(r'^Ran (\d+) tests? in ', re.MULTILINE)


def duration_hints() -> dict[str, float]:
    """Optional measured seconds affect ordering only; unusable hints fall back to size."""
    try:
        data = json.loads(DURATIONS.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: seconds for name, seconds in data.items()
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
            and 0 < seconds < math.inf}


def modules(patterns: list[str]) -> list[Path]:
    hints = duration_hints()
    found = sorted(TESTS.glob('test_*.py'),
                   key=lambda p: (-hints.get(p.name, 0), -p.stat().st_size, p.name))
    if patterns:
        found = [p for p in found if any(fnmatch.fnmatch(p.name, pat if pat.endswith('.py') else pat + '*.py')
                                         for pat in patterns)]
    return found


def run(module: Path, timeout: float) -> tuple[Path, int, str, float, int]:
    started = time.monotonic()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    try:
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(TESTS), '-t', str(TESTS),
                                 '-p', module.name], cwd=ROOT, capture_output=True, text=True, env=env,
                                timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        partial = ''.join(part.decode(errors='replace') if isinstance(part, bytes) else (part or '')
                          for part in (exc.stdout, exc.stderr))
        return module, -1, f'{partial}\nstopped after {timeout:g}s (--timeout)', time.monotonic() - started, 0
    output = result.stdout + result.stderr
    ran = RAN.search(output)
    return module, result.returncode, output, time.monotonic() - started, int(ran.group(1)) if ran else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('-j', '--jobs', type=int, default=os.cpu_count() or 2,
                        help='modules to run at once (default: CPU count)')
    parser.add_argument('--timeout', type=float, default=600,
                        help='seconds before a module is stopped and counted as failed (default: 600)')
    parser.add_argument('--shard-index', type=int, default=0,
                        help='zero-based shard to run (default: 0)')
    parser.add_argument('--shard-count', type=int, default=1,
                        help='number of disjoint module shards (default: 1, the complete suite)')
    parser.add_argument('patterns', nargs='*', help='module file name patterns, e.g. test_review*')
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error('--jobs must be at least 1')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error('--shard-count must be positive and 0 <= --shard-index < --shard-count')
    selected = modules(args.patterns)
    if not selected:
        parser.error(f'no test modules match {args.patterns}')
    selected = selected[args.shard_index::args.shard_count]
    if not selected:
        parser.error('selected shard contains no test modules')

    started = time.monotonic()
    failed, total = [], 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for future in as_completed([pool.submit(run, m, args.timeout) for m in selected]):
            module, code, output, elapsed, ran = future.result()
            total += ran
            mark = 'ok' if code == 0 and ran else 'FAIL'
            print(f'{mark:4} {module.stem:45} {ran:4} tests {elapsed:6.1f}s', flush=True)
            if mark == 'FAIL':
                failed.append((module, output))

    for module, output in failed:
        print(f'\n===== {module.stem} =====\n{output}', file=sys.stderr)
    print(f'\n{total} tests in {len(selected)} modules, {time.monotonic() - started:.1f}s wall; '
          f'{len(failed)} module(s) failed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
