#!/usr/bin/env python3
"""Validate exact-head PR state from content-bound coordinator host observations."""
import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.validator_observations import read_object, observation, emit

PASSING = ('success', 'neutral', 'skipped')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    args = parser.parse_args()
    try:
        data, sha = read_object(args.input)
        if not re.fullmatch(r'[0-9a-f]{40}', str(data.get('head_sha', ''))):
            raise ValueError('PR head must be an exact commit SHA')
        required = data['required_contexts']
        checks = data['required_checks']
        if not required and data.get('allow_empty_required_contexts') is not True:
            raise ValueError('empty required contexts need explicit stage permission')
        threads = data['review_threads']
        if not isinstance(required, list) or len(set(required)) != len(required) or any(not isinstance(x, str) or not x for x in required):
            raise ValueError('required check contexts must be an explicit unique list')
        if not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks):
            raise ValueError('check observations must be complete objects')
        optional = data.get('optional_contexts', [])
        if not isinstance(optional, list) or any(not isinstance(name, str) or not name for name in optional) or set(optional) & set(required):
            raise ValueError('optional check policy must be an explicit disjoint list')
        if any(c.get('context') not in set(required) | set(optional) for c in checks):
            raise ValueError('observed check is neither required nor explicitly optional')
        by_name = {c.get('context'): c for c in checks}
        if len(by_name) != len(checks) or not set(required) <= set(by_name):
            raise ValueError('required check coverage is missing or duplicated')
        # GitHub treats a neutral or skipped required check as passing; merge-pr.sh agrees.
        if any(by_name[name].get('conclusion') not in PASSING or by_name[name].get('head_sha') != data['head_sha'] for name in required):
            raise ValueError('required checks failed or refer to a different head')
        if not isinstance(threads, list) or any(not isinstance(t, dict) or t.get('resolved') is not True or t.get('head_sha') != data['head_sha'] for t in threads):
            raise ValueError('unresolved or stale review threads remain')
        # An empty or first-page list proves nothing: bind distinct host thread IDs to GitHub's own total.
        count = data['review_thread_count']
        ids = [t.get('id') for t in threads]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('review threads need distinct host thread IDs')
        if type(count) is not int or count != len(ids):
            raise ValueError('review thread list is incomplete: review_thread_count must equal the observed threads')
        end = data['authorized_endstate']
        if not isinstance(end, dict) or end.get('requested') not in ('mergeable', 'merged', 'open') or end.get('observed') != end['requested'] or not end.get('authorization_ref'):
            raise ValueError('requested and observed authorized endstate differ')
        snapshots = [observation(row, 'pr-state') for row in data['host_observations']]
        fields = ('pr', 'head_sha', 'required_contexts', 'required_checks', 'review_threads', 'review_thread_count', 'authorized_endstate', 'allow_empty_required_contexts', 'optional_contexts')
        if not snapshots or not all(snapshots[-1].get(key) == data.get(key) for key in fields):
            raise ValueError('host observation does not bind the complete current PR state')
        if len(snapshots) > 1 and (any(type(row.get('sequence')) is not int for row in data['host_observations']) or any(left['sequence'] >= right['sequence'] for left, right in zip(data['host_observations'], data['host_observations'][1:]))):
            raise ValueError('host observations need strictly increasing coordinator sequence numbers')
        if not required and snapshots[-1].get('allow_empty_required_contexts') is not True:
            raise ValueError('latest host policy must confirm empty required contexts')
        result = emit(True, 'exact-head-required-checks', {'input': args.input, 'sha256': sha})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = emit(False, 'exact-head-required-checks', {'reason': str(exc)})
    print(json.dumps(result, sort_keys=True))
    return 0 if result['accepted'] else 1

if __name__ == '__main__':
    sys.exit(main())
