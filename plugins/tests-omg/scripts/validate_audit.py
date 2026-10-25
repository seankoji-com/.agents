#!/usr/bin/env python3
"""Validate one exact saved local advisory; independent review is a shared job gate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import audit
from render import render

FIELDS = {'state_root', 'run_id', 'audit_sha256', 'input_sha256',
          'snapshot_sha256', 'head_sha'}
OUTCOMES = ('audit-report-integrity', 'audit-source-current', 'audit-scope-complete')


def inspect_report(descriptor):
    if not isinstance(descriptor, dict) or set(descriptor) != FIELDS:
        raise ValueError('exact audit descriptor fields required')
    if not isinstance(descriptor['state_root'], str) or not Path(descriptor['state_root']).is_absolute():
        raise ValueError('absolute private audit state root required')
    root = audit.state_root(descriptor['state_root'], create=False)
    folder, manifest, saved = audit.verify(root, descriptor['run_id'])
    expected = {'audit_sha256': manifest['hashes']['audit.json'],
                'input_sha256': manifest['hashes']['input.json'],
                'snapshot_sha256': saved['snapshot']['sha256'],
                'head_sha': saved['snapshot']['head_sha']}
    if any(descriptor[k] != v for k, v in expected.items()):
        raise ValueError('audit descriptor differs from saved report binding')
    data = audit.load(folder / 'input.json')
    if data != saved['input']:
        raise ValueError('saved audit and input disagree')
    audit.authorize_input(data, saved['scope'].get('run_checks', False))
    if manifest['generator_version'] != audit.GENERATOR or audit.digest(render(saved).encode()) != manifest['hashes']['report.html']:
        raise ValueError('pinned deterministic report rendering differs')
    refs = data.get('references', [])
    now = datetime.now(timezone.utc)
    if any(r.get('available') is False or (r.get('expires_at') and
           audit.expiry(r['expires_at']) <= now) for r in refs):
        raise ValueError('audit diagnostics unavailable or expired')
    if audit.expired_exceptions(data):
        raise ValueError('audit compensating exception expired')
    index = audit.load(root / 'index.json')
    rows = [r for r in index['runs'] if r['run_id'] == descriptor['run_id']]
    if len(rows) != 1 or rows[0].get('superseded_by'):
        raise ValueError('audit index identity missing, duplicated or superseded')
    source = manifest.get('source_locator')
    if not source or saved['scope'].get('kind') != 'repository':
        raise ValueError('local repository source locator required; organization review is unavailable')
    audit.state_root(descriptor['state_root'], repo=source, create=False)
    current = audit.snapshot_saved(source, saved['snapshot'])
    if (current['limitations'] or current['sha256'] != descriptor['snapshot_sha256'] or
            current['head_sha'] != descriptor['head_sha'] or
            not saved['analysis'].get('evidence_current') or
            audit.evidence_rejections(data, current)):
        raise ValueError('audit source is stale, incomplete or rejected')
    findings = saved['analysis']['findings']
    if (saved['completion'] != 'complete' or saved['analysis']['sample'].get('omitted') or
            sorted(f['id'] for f in findings) != [f'TEST-{n:02}' for n in range(1, 13)]):
        raise ValueError('audit scope or twelve-finding coverage incomplete')
    return {'run_id': descriptor['run_id'], 'snapshot_sha256': current['sha256'],
            'validation_verdict': saved['analysis']['validation_verdict'],
            'claim': 'Current complete advisory only; repository validation and independent review are separate.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect_report(audit.load(args.input))
        accepted, status = True, 'passed'
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        # Exception text can embed private absolute state and host paths. The
        # validator's JSON is a public evidence boundary, so expose only a stable
        # failure code and keep diagnostic details out of the receipt.
        accepted, status, result = False, 'unverified', {
            'code': 'audit_validation_failed',
            'message': 'saved audit evidence is unavailable or invalid'}
    print(json.dumps({'accepted': accepted, 'requirement_outcomes': {
        key: {'status': status, 'evidence': result} for key in OUTCOMES}}, sort_keys=True))
    return 0 if accepted else 1


if __name__ == '__main__':
    sys.exit(main())
