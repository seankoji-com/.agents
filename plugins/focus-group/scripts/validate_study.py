#!/usr/bin/env python3
"""Pinned focus-group study validator: one stage verdict from a published coordinator observation.

The shared acceptance helper runs this exact program from the stored pinned package with
`--input <job>/observations/<stage>-<sha>.json`. It reads that frozen observation, the shared job
receipts and the study records, and prints `{accepted, requirement_outcomes}` keyed by the stage's
requirement IDs. Worker completion, a summary saying done or a self-approval never passes it. It
checks provenance, coverage, counts and declared contracts, not the truth of arbitrary prose.
Exit 0 accepted, 1 rejected or unverified, 2 invalid invocation.
"""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never write caches into the pinned package
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--input', required=True)
    args = parser.parse_args(argv)
    try:
        import report
        result = report.validate_observation(args.input)
    except Exception as exc:  # any unreadable or unsafe state is a rejection, never an acceptance
        result = {'accepted': False, 'requirement_outcomes': {}, 'error': f'{type(exc).__name__}: {exc}'}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('accepted') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
