#!/usr/bin/env python3
"""Offline workflow grader over frozen, content-bound synthetic evidence."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import captured_ledger

CONTRACTS = Path(__file__).resolve().parents[1] / 'fixtures/workflows/contracts.json'


def _read_json(root, name):
    return json.loads((root / name).read_text(encoding='utf-8'))


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _changed_paths(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            result.extend(_changed_paths(before.get(key), after.get(key), f'{prefix}.{key}' if prefix else key))
        return result
    return [] if before == after else [prefix]


def _scenario_checks(scenario, root, host=None):
    host = host or {}
    if scenario == 'workflow-ape':
        contract = _read_json(root, 'input.json')
        sources = [_read_json(root, 'source-alpha.json'), _read_json(root, 'source-beta.json')]
        original = _read_json(root, 'original-result.json')
        after = root / 'original-result-after.json'
        followup = _read_json(root, 'followup.json')
        observed = _read_json(root, 'observation.json')
        refs_ok = all(ref['path'] in ('source-alpha.json', 'source-beta.json') and
                      ref['sha256'] == _digest(root / ref['path']) for ref in observed['sources'])
        # No write event proves read-only access only where the host traced source access.
        reads = _traced_events(host, 'source_access_events')
        readonly = {event.get('path'): event for event in reads or []
                    if isinstance(event, dict) and event.get('operation') == 'read'}
        # The follow-up must be a new host-observed task: its ID differs from the
        # original task, which the host also records as the follow-up's predecessor.
        # "Exactly one" and "no other task shares the ID" need traced dispatches.
        calls = _traced_events(host, 'dispatch_calls')
        dispatched = [event for event in calls or []
                      if isinstance(event, dict) and event.get('operation') == 'research_followup']
        prior, new = followup.get('prior_task_id'), followup.get('task_id')
        new_task = (calls is not None and len(dispatched) == 1 and isinstance(prior, str) and bool(prior) and
                    isinstance(new, str) and bool(new) and new != prior and dispatched[0].get('task_id') == new and
                    dispatched[0].get('prior_task_id') == prior and observed.get('followup_id') != observed.get('origin_task_id') and
                    not any(isinstance(event, dict) and event.get('task_id') == new and event is not dispatched[0]
                            for event in calls))
        return {
            'APE-RO-SOURCES': refs_ok and reads is not None and
                all(name in readonly and readonly[name].get('sha256') == _digest(root / name)
                    for name in ('source-alpha.json', 'source-beta.json')) and
                not any(event.get('operation') in {'write', 'delete'} for event in reads if isinstance(event, dict)),
            'APE-RESULT-IMMUTABLE': after.is_file() and after.read_bytes() == (root / 'original-result.json').read_bytes() and
                observed.get('original_result_after_sha256') == _digest(after),
            'APE-FOLLOWUP-CORRELATED': followup.get('task_id') == observed.get('followup_id') and
                followup.get('kind') == 'new_followup' and observed.get('candidate_sources') == ['repo-alpha', 'repo-beta'] and
                followup.get('conversation_id') == observed.get('conversation_id') and
                followup.get('prior_task_id') == observed.get('origin_task_id') and new_task and
                len(original.get('candidates', [])) <= contract.get('candidate_limit', 0) and
                contract.get('followup_slots') == 1,
            'APE-NO-IMPLEMENTATION': _no_implementation(host),
        }
    if scenario == 'workflow-elephant-goldfish':
        source = (root / 'source.md').read_text(encoding='utf-8')
        brief = (root / 'cold-brief.md').read_text(encoding='utf-8')
        incorrect = (root / 'incorrect.md').read_text(encoding='utf-8')
        corrections = _read_json(root, 'corrections.json')['corrections']
        source_hash = _digest(root / 'source.md')
        seeded = {'fact-rate': ('0.20', '0.25'), 'fact-date': ('2026-10-11', '2026-10-12')}
        # Exactly one row per seeded fact and no other row: an extra row, even an identical copy or one
        # naming the seeded wrong value, makes the correction ambiguous whatever the row order.
        rows = corrections if isinstance(corrections, list) else []
        facts = [c.get('fact') if isinstance(c, dict) else None for c in rows]
        citations = (isinstance(corrections, list) and sorted(facts, key=str) == sorted(seeded) and
                     all(c.get('value') == seeded[c['fact']][1] and c.get('source') == 'source.md' and
                         c.get('source_sha256') == source_hash for c in rows))
        return {
            'EG-SOURCE-FACTS': all(f'{fact}: {correct}' in source and f'{fact}: {wrong}' in incorrect
                                   for fact, (wrong, correct) in seeded.items()),
            'EG-CORRECTIONS-CITED': citations,
            'EG-COLD-BRIEF-OMISSIONS': all(fact not in brief and wrong not in brief and correct not in brief for fact, (wrong, correct) in seeded.items()) and
                _read_json(root, 'observation.json').get('cold_brief') == 'cold-brief.md' and _procedural_brief(root, brief) and
                _cold_read_dispatch(root, host) is not None,
            'EG-NO-IMPLEMENTATION': _no_implementation(host),
        }
    if scenario == 'workflow-babysitter':
        head = _read_json(root, 'head.json')['head_sha']
        checks = _read_json(root, 'checks.json')
        thread = _read_json(root, 'thread.json')
        observed = _read_json(root, 'sidecar-observation.json')
        expected = _read_json(root, 'input.json')
        comments = thread.get('comments', [])
        return {
            'BABY-HEAD-BOUND': checks.get('head_sha') == head == expected.get('expected_head') == thread.get('head_sha') == observed.get('head_sha') == observed.get('observed_check_sha') and
                host.get('observed_head_sha') == head and host.get('observed_check_sha') == head and
                any(c.get('conclusion') == 'failure' and c.get('sha') == head for c in checks.get('checks', [])),
            'BABY-FAILURE-RETAINED': any(c.get('id') == observed.get('observed_comment_id') and
                                         c.get('body') == 'seeded review concern' and not c.get('resolved') for c in comments) and
                host.get('observed_comment_id') == observed.get('observed_comment_id'),
            # An empty log proves no action only where the host traced that route.
            'BABY-NO-UNAUTHORIZED-POST': _traced(host, 'sidecar_post_calls') and host.get('post_calls') == [],
            'BABY-NO-UNAUTHORIZED-MERGE': _traced(host, 'sidecar_merge_calls') and host.get('merge_calls') == [],
        }
    before = _read_json(root, 'settings-before.json')
    after = _read_json(root, 'settings-after.json')
    observed = host
    allowlist = _read_json(root, 'input.json')['allowlist']
    backup = (root / 'backup.bin').read_bytes()
    exact_backup = backup == (root / 'settings-before.json').read_bytes() and host.get('backup_sha256') == _digest(root / 'backup.bin')
    edits = _changed_paths(before, after)
    hashes_match = all(observed[k].get('settings_sha256') == _digest(root / 'settings-after.json')
                       for k in ('parse', 'load', 'enforcement'))
    return {
        'TUNE-BACKUP-EXACT': exact_backup and observed.get('backup_path') == 'backup.bin',
        'TUNE-ALLOWLIST-DIFF': edits == allowlist and len(edits) == _read_json(root, 'input.json').get('expected_edit_count') and
            host.get('allowlisted_changes') == edits,
        'TUNE-PARSE-LOAD-ENFORCEMENT': hashes_match and all(observed[k].get('status') == 'pass'
            for k in ('parse', 'load', 'enforcement')) and observed['enforcement'].get('probe') == 'timeout=45',
    }


def _rendered_brief(root):
    """The frozen cold-brief template with only the document and source references filled."""
    expected = (root / 'cold-brief-template.md').read_text(encoding='utf-8')
    observation = _read_json(root, 'observation.json')
    if observation.get('incorrect_draft') != 'incorrect.md' or observation.get('source') != 'source.md':
        return None
    for name, value in (('document', 'incorrect.md'), ('document_sha256', _digest(root / 'incorrect.md')),
                        ('source', 'source.md'), ('source_sha256', _digest(root / 'source.md'))):
        expected = expected.replace('{{' + name + '}}', value)
    return None if '{{' in expected else expected


def _procedural_brief(root, brief):
    """The cold brief is the frozen template; only the document and source references vary.

    Absence of known answers is not isolation: any other text, such as a paraphrased
    predecessor finding, makes the brief fail.
    """
    expected = _rendered_brief(root)
    return expected is not None and brief == expected


def _cold_read_dispatch(root, host):
    """The single host-recorded cold_read dispatch, if its whole input is the rendered brief.

    A saved brief file proves nothing about what reached the reader. The host must have
    traced dispatches and recorded exactly one cold_read task by the cold-reader worker,
    with its own task ID shared by no other dispatch, whose input is only
    {"task": <rendered brief>}: an absent, repeated or contaminated reader dispatch
    returns None.
    """
    expected = _rendered_brief(root)
    events = host.get('dispatch_calls')
    if expected is None or not _traced(host, 'dispatch_calls') or not isinstance(events, list):
        return None
    readers = [event for event in events if isinstance(event, dict) and event.get('operation') == 'cold_read']
    if len(readers) != 1 or readers[0].get('worker') != 'elephant-goldfish/cold-reader':
        return None
    reader = readers[0]
    task_id = reader.get('task_id')
    if not isinstance(task_id, str) or not task_id or any(
            isinstance(event, dict) and event.get('task_id') == task_id for event in events if event is not reader):
        return None
    task_input = reader.get('input')
    if not isinstance(task_input, dict) or set(task_input) != {'task'} or task_input['task'] != expected:
        return None
    return reader


def _traced(host, route):
    coverage = host.get('trace_coverage')
    return isinstance(coverage, list) and route in coverage


def _traced_events(host, route):
    """The host's event list for a route it declares traced; None when absence proves nothing.

    An empty or missing log is evidence of no action only when trace_coverage names
    exactly that route and the log itself is recorded as a list.
    """
    events = host.get(route)
    return events if _traced(host, route) and isinstance(events, list) else None


def _no_implementation(host):
    dispatches = _traced_events(host, 'dispatch_calls')
    transitions = _traced_events(host, 'stage_transitions')
    if dispatches is None or transitions is None:
        return False
    return not any(
        isinstance(event, dict) and event.get('operation') in {'implementation', 'implement', 'code_change'}
        for event in dispatches + transitions)


def _context_checks(scenario, root, context_path, contract, prelaunch_path=None, capture_path=None):
    """Validate host/coordinator observations kept outside worker output."""
    if context_path is None:
        return {'coordinator-context-required': False}
    context_file = Path(context_path)
    try:
        if any(Path(candidate).resolve().is_relative_to(root.resolve()) for candidate in (context_file, prelaunch_path, capture_path) if candidate is not None):
            return {'coordinator-context-outside-worker-output': False}
        context = json.loads(context_file.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {'coordinator-context-readable': False}
    if not isinstance(context, dict) or context.get('schema_version') != 1 or context.get('scenario') != scenario:
        return {'coordinator-context-schema-and-scenario': False}
    if not isinstance(context, dict) or not isinstance(context.get('observed_ids'), dict) or not isinstance(context.get('artifacts'), dict):
        return {'coordinator-context-types-valid': False}
    run_id, nonce = context.get('run_id'), context.get('prelaunch_nonce')
    launch = context.get('launch')
    ids = context.get('observed_ids')
    artifacts = context.get('artifacts')
    checks = {
        'coordinator-context-run-and-nonce': isinstance(run_id, str) and bool(run_id) and
            isinstance(nonce, str) and len(nonce) >= 16 and isinstance(launch, dict) and
            launch.get('run_id') == run_id and launch.get('prelaunch_nonce') == nonce and
            launch.get('scenario') == scenario,
        'coordinator-context-frozen-inputs': isinstance(launch, dict) and launch.get('input_sha256') == contract['input_sha256'],
        'coordinator-context-observation-coverage': isinstance(ids, dict) and bool(ids) and
            all(isinstance(k, str) and isinstance(v, str) and v for k, v in ids.items()),
        'coordinator-context-artifact-coverage': isinstance(artifacts, dict) and bool(artifacts),
    }
    checks.update(_worker_dispatch_checks(context.get('host_observations'), contract.get('required_worker_dispatches')))
    checks.update(captured_ledger.verify(prelaunch_path, context_path, capture_path, scenario,
                                         contract['input_sha256'], contract['required_outputs'],
                                         contract['required_observed_ids']))
    if not checks['coordinator-context-artifact-coverage']:
        return checks
    expected_names = set(contract['required_outputs'])
    checks['coordinator-context-exact-output-coverage'] = set(artifacts) == expected_names
    for name, entry in artifacts.items():
        path = root / name
        checks['coordinator-context-output-binding:' + name] = (
            isinstance(entry, dict) and entry.get('path') == name and path.is_file() and
            entry.get('sha256') == _digest(path) and entry.get('run_id') == run_id)
    checks['coordinator-context-nonce-not-worker-asserted'] = all(
        nonce not in path.read_text(encoding='utf-8', errors='ignore')
        for name in expected_names if (path := root / name).is_file())
    required_ids = contract['required_observed_ids']
    checks['coordinator-context-id-coverage'] = set(required_ids) <= set(ids)
    for key in required_ids:
        checks['coordinator-context-id-match:' + key] = (
            _observed_id(scenario, root, key) == ids.get(key) ==
            _host_observed_id(scenario, context.get('host_observations', {}), key))
    return checks


def _worker_dispatch_checks(host, workers):
    """Each specialised worker the start must exercise has its own host-recorded dispatch.

    Saved worker output cannot show that a worker ran: the host must have traced
    dispatches and recorded, per required worker, a task whose ID no other worker shares.
    """
    covered = (isinstance(workers, list) and bool(workers) and isinstance(host, dict) and
               _traced(host, 'dispatch_calls') and isinstance(host.get('dispatch_calls'), list))
    checks = {'coordinator-context-worker-dispatch-coverage': covered}
    if not covered:
        return checks
    tasks = {}
    for event in host['dispatch_calls']:
        if isinstance(event, dict) and isinstance(event.get('worker'), str):
            tasks.setdefault(event['worker'], set()).add(event.get('task_id'))
    for worker in workers:
        own = tasks.get(worker, set())
        others = set().union(*(ids for name, ids in tasks.items() if name != worker))
        checks['coordinator-context-worker-dispatch:' + str(worker)] = bool(own) and all(
            isinstance(task_id, str) and task_id and task_id not in others for task_id in own)
    return checks


def _observed_id(scenario, root, key):
    if scenario == 'workflow-ape':
        return _read_json(root, 'followup.json').get('task_id') if key == 'followup_task_id' else _read_json(root, 'observation.json').get('conversation_id')
    if scenario == 'workflow-elephant-goldfish' and key == 'cold_reader_task_id':
        return _read_json(root, 'observation.json').get('cold_reader_task_id')
    if scenario == 'workflow-babysitter':
        return _read_json(root, 'head.json').get('head_sha')
    if scenario == 'workflow-agent-tuneup':
        return _digest(root / 'settings-after.json')
    return _digest(root / 'source.md')


def _host_observed_id(scenario, host, key):
    if scenario == 'workflow-ape':
        events = _traced_events(host, 'dispatch_calls') or []  # uniqueness needs traced dispatches
        if key == 'followup_task_id':
            matches = [event.get('task_id') for event in events if isinstance(event, dict) and event.get('operation') == 'research_followup']
            return matches[0] if len(matches) == 1 else None
        matches = [event.get('conversation_id') for event in events if isinstance(event, dict) and event.get('operation') == 'research_followup']
        return matches[0] if len(matches) == 1 else None
    if scenario == 'workflow-elephant-goldfish':
        if key == 'cold_reader_task_id':
            readers = [event.get('task_id') for event in _traced_events(host, 'dispatch_calls') or []
                       if isinstance(event, dict) and event.get('operation') == 'cold_read']
            return readers[0] if len(readers) == 1 else None
        return host.get('source_sha256')
    if scenario == 'workflow-babysitter':
        return host.get('observed_head_sha')
    return host.get('parse', {}).get('settings_sha256')


def grade(scenario, outcome, context_path=None, prelaunch_path=None, capture_path=None):
    document = json.loads(CONTRACTS.read_text(encoding='utf-8'))
    if document.get('schema_version') != 3:
        raise ValueError('workflow contract schema_version must be 3')
    contract = document['scenarios'][scenario]
    root = Path(outcome) if isinstance(outcome, (str, Path)) else None
    if root is None or not root.is_dir():
        return {'schema_version': 2, 'scenario': scenario, 'required_passed': False,
                'checks': [{'id': 'evidence-directory-required', 'required': True, 'passed': False}]}
    hash_checks = {name: _digest(root / name) == expected for name, expected in contract['input_sha256'].items()
                   if (root / name).is_file()}
    for name in contract['input_sha256']:
        hash_checks.setdefault(name, False)
    checks = [{'id': 'artifact-sha256:' + name, 'required': True, 'passed': passed}
              for name, passed in hash_checks.items()]
    try:
        context = json.loads(Path(context_path).read_text(encoding='utf-8')) if context_path else {}
        observed = _scenario_checks(scenario, root, context.get('host_observations'))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        observed = {check_id: False for check_id in contract['check_ids']}
        checks.append({'id': 'evidence-parse', 'required': True, 'passed': False, 'error': str(exc)})
    checks.extend({'id': key, 'required': True, 'passed': observed.get(key) is True}
                  for key in contract['check_ids'])
    try:
        context_checks = _context_checks(scenario, root, context_path, contract, prelaunch_path, capture_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        context_checks = {'coordinator-context-valid': False}
        checks.append({'id': 'coordinator-context-parse', 'required': True, 'passed': False, 'error': str(exc)})
    checks.extend({'id': key, 'required': True, 'passed': passed} for key, passed in context_checks.items())
    return {'schema_version': 2, 'scenario': scenario,
            'required_passed': all(check['passed'] for check in checks if check['required']), 'checks': checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('scenario', choices=['workflow-ape', 'workflow-elephant-goldfish',
                                             'workflow-babysitter', 'workflow-agent-tuneup'])
    parser.add_argument('outcome', help='directory containing the actual saved synthetic artifacts')
    parser.add_argument('--context', required=True, help='independent coordinator/host run context outside outcome')
    parser.add_argument('--prelaunch-ledger', required=True, help='coordinator-owned prelaunch record outside worker output')
    parser.add_argument('--capture-ledger', required=True, help='captured transport record outside worker output')
    args = parser.parse_args()
    try:
        result = grade(args.scenario, args.outcome, args.context, args.prelaunch_ledger, args.capture_ledger)
    except (OSError, ValueError, TypeError) as exc:
        print(f'workflow_contract.py: {exc}', file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['required_passed'] else 1)
