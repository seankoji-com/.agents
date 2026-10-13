#!/usr/bin/env python3
"""Derive report provenance checks from actual pinned source bytes."""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.validator_observations import read_object
from core.jobs.store import _regular


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    args = parser.parse_args()
    try:
        data, report_sha = read_object(args.input)
        sources, findings, criteria = data['sources'], data['findings'], data['criteria']
        if not isinstance(sources, list) or not 0 < len(sources) <= 5 or not isinstance(findings, list) or not isinstance(criteria, list) or not criteria:
            raise ValueError('report must declare finite source and criterion coverage')
        source_bytes = {}
        for source in sources:
            if not isinstance(source, dict) or not source.get('id') or not source.get('url') or not source.get('revision') or not Path(source.get('path', '')).is_absolute() or source['id'] in source_bytes:
                raise ValueError('source pin identity/path is missing or duplicated')
            raw = _regular(Path(source['path']), max_bytes=16 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != source.get('sha256'):
                raise ValueError('actual source bytes differ from source pin')
            source_bytes[source['id']] = raw.decode('utf-8')
        for finding in findings:
            if not isinstance(finding, dict) or finding.get('source_id') not in source_bytes or not isinstance(finding.get('quote'), str) or not finding['quote'] or finding['quote'] not in source_bytes[finding['source_id']]:
                raise ValueError('finding is not supported by its actual source bytes')
        outcomes = {}
        for criterion in criteria:
            if not isinstance(criterion, dict) or 'status' in criterion or not criterion.get('id') or criterion['id'] in outcomes:
                raise ValueError('criteria declare checks; result statuses cannot be supplied')
            kind = criterion.get('kind')
            if kind not in ('source-provenance', 'finding-source-coverage'):
                raise ValueError('unsupported provenance criterion')
            minimum = criterion.get('minimum_findings', 0)
            if type(minimum) is not int or minimum < 0:
                raise ValueError('minimum finding coverage must be a nonnegative integer')
            passed = kind == 'source-provenance' or len(findings) >= minimum
            outcomes[criterion['id']] = {'status': 'passed' if passed else 'failed',
                                         'evidence': {'input': args.input, 'sha256': report_sha,
                                                      'source_sha256': {row['id']: row['sha256'] for row in sources},
                                                      'finding_count': len(findings), 'check': kind}}
        accepted = all(row['status'] == 'passed' for row in outcomes.values())
        result = {'accepted': accepted, 'requirement_outcomes': outcomes}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {'accepted': False, 'requirement_outcomes': {'report-provenance': {
            'status': 'failed', 'evidence': {'reason': str(exc)}}}}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['accepted'] else 1


if __name__ == '__main__':
    sys.exit(main())
