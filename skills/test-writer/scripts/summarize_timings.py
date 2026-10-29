#!/usr/bin/env python3
"""Summarize JSON [{"seconds": 12, "outcome": "failed"}, ...].

Each row is a runner attempt. Include failures/retries, not just final passes.
Use the same declared duration boundary/environment; record provenance separately.
Summed runner seconds are NOT elapsed wall time. No commands are executed.
"""
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

OUTCOMES = {'passed', 'failed', 'cancelled', 'timed_out', 'unknown'}


def summarize(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('expected nonempty attempts list')
    durations, outcomes = [], Counter()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('attempt must be an object')
        seconds, outcome = row.get('seconds'), row.get('outcome')
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or seconds < 0):
            raise ValueError('seconds must be finite and nonnegative')
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            raise ValueError('missing/invalid outcome')
        durations.append(seconds)
        outcomes[outcome] += 1
    durations.sort()
    total = math.fsum(durations)
    if not math.isfinite(total):
        raise ValueError('total overflow')
    return {'attempts': len(rows), 'outcomes': dict(sorted(outcomes.items())),
            'runner_seconds': total, 'p50_seconds': durations[math.ceil(len(rows) * .50) - 1],
            'p95_seconds': durations[math.ceil(len(rows) * .95) - 1],
            'method': 'nearest rank; all attempts; wall latency unknown'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    try:
        result = summarize(json.loads(args.file.read_text(encoding='utf-8')))
    except (OSError, ValueError, OverflowError, RecursionError):
        parser.exit(2, 'Invalid timing observations; see --help.\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    if sys.version_info < (3, 10):
        sys.exit('Python 3.10+ required')
    main()
