#!/usr/bin/env python3
"""Offline negative-start grader over frozen job and coordinator artifacts."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import captured_ledger

CONTRACTS = Path(__file__).resolve().parents[1] / 'fixtures/workflows/contracts.json'


def _json(root, name):
    return json.loads((root / name).read_text(encoding='utf-8'))


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _traced(host, *routes):
    """An empty log proves no action only where trace_coverage is a list naming each route."""
    coverage = host.get('trace_coverage')
    return isinstance(coverage, list) and all(route in coverage for route in routes)


def _checks(kind, root, host=None):
    host = host or {}
    if kind == 'negative-missing-delegation':
        scope = _json(root, 'scope.json')
        receipts = _json(root, 'direct-stage-receipts.json')
        markers = _json(root, 'fallback-markers.json')
        observed = _json(root, 'coordinator-observation.json')
        scope_hash = _hash(root / 'scope.json')
        budgets_hash = hashlib.sha256(json.dumps(scope['budgets'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        gates_hash = hashlib.sha256(json.dumps(scope['gates'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        counters_hash = hashlib.sha256(json.dumps(scope['counters'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        stages = [f's{i}' for i in range(1, 6)]
        return {
            'N1-ALL-FIVE-DIRECT-STAGES': [r.get('stage') for r in receipts] == stages and
                all(r.get('status') == 'completed_direct' and r.get('receipt_id') and
                    r.get('job_id') == observed.get('job_id') for r in receipts) and
                observed.get('direct_stage_ids') == stages,
            'N2-VALID-FALLBACK-MARKERS': [m.get('stage') for m in markers] == stages and
                all(m.get('schema_version') == 1 and m.get('reason') == 'delegation_unavailable' and
                    m.get('job_id') == observed.get('job_id') for m in markers),
            'N3-SCOPE-BUDGET-GATES-PRESERVED': all(r.get('scope_id') == scope.get('scope_id') and
                r.get('scope_sha256') == scope_hash and r.get('budgets_sha256') == budgets_hash and
                r.get('gates_sha256') == gates_hash and r.get('counters_sha256') == counters_hash for r in receipts),
            'N4-ZERO-WORKER-DISPATCH': _traced(host, 'dispatch_calls', 'task_handles') and
                host.get('observed_handles') == [] and host.get('dispatch_calls') == [],
        }
    job = _json(root, 'job.json')
    observation = _json(root, 'reviewer-observation.json')
    return {
        'N5-BLOCKED-REVIEW-UNAVAILABLE': job.get('status') == 'blocked' and
            'required_review_unavailable' in job.get('blocker_codes', []) and
            observation.get('required_review_status') == 'unavailable' and
            observation.get('job_id') == job.get('job_id'),
        'N6-NO-ACCEPTED-STAGES': job.get('accepted_stages') == [] and job.get('stage_receipts') == [],
        'N7-NO-FINAL-READINESS': job.get('final_readiness_receipt') is None and job.get('current_readiness') is None,
        'N8-ZERO-REVIEWER-DISPATCH': _traced(host, 'dispatch_calls', 'task_handles') and
            host.get('reviewer_handles') == [] and host.get('dispatch_calls') == [],
    }


def grade(kind, outcome, context_path=None, prelaunch_path=None, capture_path=None):
    document = json.loads(CONTRACTS.read_text(encoding='utf-8'))
    if document.get('schema_version') != 3:
        raise ValueError('workflow contract schema_version must be 3')
    contracts = document['negative_scenarios']
    contract = contracts[kind]
    root = Path(outcome) if isinstance(outcome, (str, Path)) else None
    if root is None or not root.is_dir():
        return {'schema_version': 2, 'outcome': kind, 'required_passed': False,
                'checks': [{'id': 'evidence-directory-required', 'required': True, 'passed': False}]}
    checks = []
    for name, expected in contract['input_sha256'].items():
        actual = _hash(root / name) if (root / name).is_file() else None
        checks.append({'id': 'artifact-sha256:' + name, 'required': True, 'passed': actual == expected})
    try:
        context = json.loads(Path(context_path).read_text(encoding='utf-8')) if context_path else {}
        observed = _checks(kind, root, context.get('host_observations'))
        checks.extend({'id': key, 'required': True, 'passed': observed.get(key) is True}
                      for key in contract['check_ids'])
        checks.extend({'id': key, 'required': True, 'passed': value}
                      for key, value in _context_checks(kind, root, context_path, contract, prelaunch_path, capture_path).items())
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        checks.append({'id': 'evidence-parse', 'required': True, 'passed': False, 'error': str(exc)})
        checks.extend({'id': key, 'required': True, 'passed': False}
                      for key in contract['check_ids'])
    return {'schema_version': 2, 'outcome': kind,
            'required_passed': all(check['passed'] for check in checks if check['required']), 'checks': checks}


def _context_checks(kind, root, context_path, contract, prelaunch_path=None, capture_path=None):
    if context_path is None:
        return {'coordinator-context-required': False}
    path = Path(context_path)
    try:
        if any(Path(candidate).resolve().is_relative_to(root.resolve()) for candidate in (path, prelaunch_path, capture_path) if candidate is not None):
            return {'coordinator-context-outside-worker-output': False}
        context = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {'coordinator-context-readable': False}
    if not isinstance(context, dict) or not isinstance(context.get('observed_ids'), dict) or not isinstance(context.get('artifacts'), dict):
        return {'coordinator-context-types-valid': False}
    run_id, nonce = context.get('run_id'), context.get('prelaunch_nonce')
    launch = context.get('launch')
    ids, artifacts = context.get('observed_ids'), context.get('artifacts')
    checks = {
        'coordinator-context-schema-and-scenario': context.get('schema_version') == 1 and context.get('scenario') == kind,
        'coordinator-context-run-and-nonce': isinstance(run_id, str) and bool(run_id) and isinstance(nonce, str) and len(nonce) >= 16 and
            isinstance(launch, dict) and launch.get('run_id') == run_id and launch.get('prelaunch_nonce') == nonce and launch.get('scenario') == kind,
        'coordinator-context-frozen-inputs': isinstance(launch, dict) and launch.get('input_sha256') == contract['input_sha256'],
        'coordinator-context-observation-coverage': isinstance(ids, dict) and bool(ids),
        'coordinator-context-exact-output-coverage': isinstance(artifacts, dict) and set(artifacts) == set(contract['required_outputs']),
    }
    checks.update(captured_ledger.verify(prelaunch_path, context_path, capture_path, kind,
                                         contract['input_sha256'], contract['required_outputs'],
                                         contract['required_observed_ids']))
    if not isinstance(artifacts, dict):
        return checks
    for name in contract['required_outputs']:
        entry = artifacts.get(name, {})
        target = root / name
        checks['coordinator-context-output-binding:' + name] = (
            isinstance(entry, dict) and entry.get('path') == name and target.is_file() and
            entry.get('sha256') == _hash(target) and entry.get('run_id') == run_id)
    checks['coordinator-context-nonce-not-worker-asserted'] = all(
        nonce not in target.read_text(encoding='utf-8', errors='ignore')
        for name in contract['required_outputs'] if (target := root / name).is_file())
    checks['coordinator-context-id-coverage'] = set(contract['required_observed_ids']) <= set(ids or {})
    for key in contract['required_observed_ids']:
        checks['coordinator-context-id-match:' + key] = ids.get(key) == _observed_id(kind, root, key) == _host_observed_id(kind, context.get('host_observations', {}), key)
    return checks


def _observed_id(kind, root, key):
    if kind == 'negative-missing-delegation':
        if key == 'job_id':
            return _json(root, 'coordinator-observation.json').get('job_id')
        return ','.join(r.get('receipt_id', '') for r in _json(root, 'direct-stage-receipts.json'))
    if key == 'job_id':
        return _json(root, 'job.json').get('job_id')
    return _json(root, 'reviewer-observation.json').get('required_review_status')


def _host_observed_id(kind, host, key):
    if kind == 'negative-missing-delegation':
        if key == 'job_id':
            return host.get('job_id')
        return ','.join(host.get('receipt_ids', []))
    if key == 'job_id':
        return host.get('job_id')
    return host.get('required_review_status')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['negative-missing-delegation', 'negative-unavailable-required-review'])
    parser.add_argument('record', help='directory containing saved synthetic artifacts')
    parser.add_argument('--context', required=True, help='independent coordinator/host run context outside record')
    parser.add_argument('--prelaunch-ledger', required=True, help='coordinator-owned prelaunch record outside worker output')
    parser.add_argument('--capture-ledger', required=True, help='captured transport record outside worker output')
    args = parser.parse_args()
    try:
        result = grade(args.kind, args.record, args.context, args.prelaunch_ledger, args.capture_ledger)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f'negative_start.py: {exc}', file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['required_passed'] else 1)
