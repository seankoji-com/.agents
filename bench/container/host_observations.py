#!/usr/bin/env python3
"""Export parent tool results from the pinned isolated T3 store.

This is an observation adapter for the pinned benchmark runtime, not a task
scheduler. The coordinator copies the snapshot outside the worker's mounts.
Unknown storage layouts or missing results remain unverified.
"""
import hashlib
import json
import shlex
import sqlite3
from pathlib import Path

MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024 * 1024


def read_snapshot(path, parent_thread_id):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError('host observation snapshot is not a bounded regular file')
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        records, runs, requests, threads = [], [], [], []
        query = ('SELECT payload_json FROM orchestration_v2_projection_turn_items '
                 "WHERE thread_id=? AND type='dynamic_tool' ORDER BY ordinal")
        for (raw,) in connection.execute(query, (parent_thread_id,)):
            if len(raw.encode('utf-8')) > MAX_RECORD_BYTES:
                raise ValueError('host tool observation exceeds the finite record bound')
            row = json.loads(raw)
            if not isinstance(row, dict) or row.get('threadId') != parent_thread_id:
                raise ValueError('host tool observation has a foreign parent')
            if row.get('status') != 'completed':
                continue
            if row.get('toolName') not in {'t3-code.delegate_task', 't3-code.task_status'}:
                continue
            if not isinstance(row.get('input'), dict) or not isinstance(row.get('output'), dict):
                raise ValueError('host tool observation has no complete structured result')
            records.append(row)
        # Include visible grandchildren too. Immediate-child checks alone do
        # not reconcile unexpected work owned below an accepted child.
        subagents, commands, file_changes = [], [], []
        frontier, seen = [parent_thread_id], set()
        while frontier:
            owner = frontier.pop()
            if owner in seen:
                continue
            seen.add(owner)
            for table, output in (('runs', runs), ('runtime_requests', requests), ('threads', threads)):
                for (raw,) in connection.execute('SELECT payload_json FROM orchestration_v2_projection_' + table + ' WHERE thread_id=?', (owner,)):
                    if len(raw.encode('utf-8')) > MAX_RECORD_BYTES:
                        raise ValueError('host lifecycle observation exceeds finite record bound')
                    row = json.loads(raw)
                    if not isinstance(row, dict) or row.get('id' if table == 'threads' else 'threadId') != owner:
                        raise ValueError('host lifecycle observation has a foreign parent')
                    output.append(row)
            # Command executions and file changes recorded by T3 in its coordinator-only
            # store, for every thread including the parent, so each is bound to its actor.
            # Command output and file contents are omitted.
            for item_type, output, keys in (
                    ('command_execution', commands, ('id', 'threadId', 'status', 'exitCode', 'input')),
                    ('file_change', file_changes, ('id', 'threadId', 'status'))):
                for (raw,) in connection.execute(
                        'SELECT payload_json FROM orchestration_v2_projection_turn_items '
                        'WHERE thread_id=? AND type=? ORDER BY ordinal', (owner, item_type)):
                    if len(raw.encode('utf-8')) > MAX_RECORD_BYTES:
                        raise ValueError('host action observation exceeds the finite record bound')
                    row = json.loads(raw)
                    if not isinstance(row, dict) or row.get('threadId') != owner:
                        raise ValueError('host action observation has a foreign thread')
                    output.append({key: row.get(key) for key in keys})
            if len(seen) > 100:
                raise ValueError('host descendant observation exceeds the finite tree bound')
            children = connection.execute(
                'SELECT payload_json FROM orchestration_v2_projection_subagents WHERE thread_id=?',
                (owner,)).fetchall()
            for (raw,) in children:
                if len(raw.encode('utf-8')) > MAX_RECORD_BYTES:
                    raise ValueError('host subagent observation exceeds the finite record bound')
                row = json.loads(raw)
                if not isinstance(row, dict) or row.get('threadId') != owner:
                    raise ValueError('host subagent observation has a foreign parent')
                subagents.append(row)
                child_thread = row.get('childThreadId')
                if isinstance(child_thread, str):
                    frontier.append(child_thread)
    except sqlite3.Error as exc:
        raise ValueError('pinned T3 host observation storage is unavailable: ' + type(exc).__name__) from None
    finally:
        connection.close()
    return {'schema_version': 1, 'parent_thread_id': parent_thread_id,
            'snapshot_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'tool_records': records, 'subagents': subagents, 'runs': runs, 'runtime_requests': requests, 'threads': threads,
            'commands': commands, 'file_changes': file_changes}


SHELLS = {'bash', 'sh', 'zsh', 'dash'}
TERMINAL_RUN_STATUSES = frozenset({'completed', 'failed', 'interrupted', 'cancelled'})


def command_tokens(text):
    """Tokenize a recorded command, unwrapping exactly one `<shell> -c|-lc '<cmd>'` layer."""
    try:
        tokens = shlex.split(text)
        if len(tokens) == 3 and Path(tokens[0]).name in SHELLS and tokens[1] in {'-c', '-lc'}:
            tokens = shlex.split(tokens[2])
    except ValueError:
        return None
    return tokens


def declared_child_thread(observations, task_id):
    """The app child thread the parent dispatched for one declared task, or None.

    Every app-owned subagent row for the task must be owned by the parent, and
    the rows and the parent's task_status must name one child thread.
    """
    parent = observations.get('parent_thread_id')
    if not isinstance(task_id, str) or not task_id:
        return None
    rows = [row for row in observations.get('subagents', []) if row.get('id') == task_id]
    if not rows or any(row.get('threadId') != parent or row.get('origin') == 'provider_native'
                       for row in rows):
        return None
    try:
        status = CapturedTaskClient(observations).results.get(task_id)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    child = projected_child_thread(observations, task_id, status)
    return child if child != parent else None


def helper_invocation_observed(observations, command, primary_task_id):
    """Exactly one T3-recorded execution of the pinned helper, made by the primary child.

    The primary task resolves to its host-projected child thread. The helper run
    there must have succeeded, and a run in any other thread (parent, boundary
    reader, native probe, follow-up or unknown) fails the check.
    """
    primary = declared_child_thread(observations, primary_task_id)
    expected = shlex.split(command)
    matches = [row for row in observations.get('commands', [])
               if isinstance(row.get('input'), str) and command_tokens(row['input']) == expected]
    return (primary is not None and len(matches) == 1 and matches[0].get('threadId') == primary
            and matches[0].get('status') == 'completed' and matches[0].get('exitCode') == 0)


def file_changes_bound_to_primary(observations, primary_task_id):
    """Every T3-recorded file change was made by the primary child thread.

    Only the primary may write; a recorded file change by any other actor fails,
    whatever its status. Shell-command writes are not attributable this way.
    """
    primary = declared_child_thread(observations, primary_task_id)
    changes = observations.get('file_changes')
    return (primary is not None and isinstance(changes, list)
            and all(isinstance(row, dict) and row.get('threadId') == primary for row in changes))


CANARY_ROLE_MARKER_PREFIX = 'ISSUE28_CANARY_ROLE='
SUMMARY_BOUNDARY_KEYS = ('32767', '32768', '32769')


def raw_equal(left, right):
    """Structural equality that never coerces booleans to integers or vice versa."""
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(raw_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(raw_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def frozen_assignment(role):
    """The exact frozen literal (app `task` or native `prompt`) a role must be dispatched with."""
    return role.get('prompt') if role.get('dispatch') == 'native' else role.get('task')


def frozen_protocol_is_valid(protocol):
    """A finite role authority: schema 1, one frozen target, unique roles and markers.

    The protocol declares, per role, whether the host dispatches it as an app child
    or a provider-native child, the exact frozen marker line, the exact frozen scope
    tokens, and the complete frozen assignment literal (app `task` or native `prompt`)
    that carries the marker line and every scope token. Unknown or duplicate roles, or
    a template whose marker/tokens do not match its declaration, fail closed.
    """
    if not isinstance(protocol, dict) or protocol.get('schema_version') != 1:
        return False
    target, roles = protocol.get('target'), protocol.get('roles')
    if (not isinstance(protocol.get('provider'), str) or not protocol['provider']
            or not isinstance(target, dict)
            or not isinstance(target.get('providerInstanceId'), str) or not target['providerInstanceId']
            or not isinstance(target.get('model'), str) or not target['model']
            or not isinstance(target.get('options'), dict)
            or not isinstance(roles, list) or not roles):
        return False
    names, markers = set(), set()
    for role in roles:
        if (not isinstance(role, dict) or not isinstance(role.get('role'), str) or not role['role']
                or role.get('dispatch') not in {'app', 'native'}
                or not isinstance(role.get('marker'), str)
                or not role['marker'].startswith(CANARY_ROLE_MARKER_PREFIX)
                or not isinstance(role.get('required'), list)
                or any(not isinstance(token, str) or not token for token in role['required'])):
            return False
        template = frozen_assignment(role)
        if not isinstance(template, str) or not template:
            return False
        if role['marker'] not in {line.strip() for line in template.splitlines()} or \
                any(token not in template for token in role['required']):
            return False
        names.add(role['role'])
        markers.add(role['marker'])
    return len(names) == len(roles) and len(markers) == len(roles)


def role_dispatch_matches(launch_input, role, target):
    """Exact frozen-literal match for one captured dispatch input.

    The captured target must equal the frozen target with identical raw types (a
    boolean is never an integer), and the captured ``task`` must equal the complete
    frozen assignment literal byte for byte. This rejects a task that merely quotes the
    marker or a scope token, or that adds contradictory, extra or reformatted text.
    """
    if not isinstance(launch_input, dict) or not raw_equal(launch_input.get('target'), target):
        return False
    task = launch_input.get('task')
    return isinstance(task, str) and task == role.get('task')


def captured_role_assignments(observations, protocol):
    """Bind every frozen canary role to the accepted handle its host capture names.

    The independent authority is what the host recorded at dispatch time: the parent's
    captured `delegate_task` input (exact task text and frozen target) and the captured
    provider-native subagent row. The final model report, thread ownership alone, a
    worker-written receipt and natural-language similarity are never used to classify
    a role, and missing, duplicated or conflicting assignments fail closed.
    """
    if not frozen_protocol_is_valid(protocol):
        return {'ok': False, 'assignments': {}, 'problems': ['frozen canary role protocol is malformed']}
    target = protocol['target']
    native_names = {role['role'] for role in protocol['roles'] if role['dispatch'] == 'native'}
    problems, accepted = [], []
    for row in observations.get('tool_records', []):
        if not isinstance(row, dict) or row.get('toolName') != 't3-code.delegate_task':
            continue
        output = row.get('output')
        task_id = output.get('taskId') if isinstance(output, dict) else None
        launch_input = row.get('input')
        # A captured continuation carries the continued child thread; it is not a fresh
        # finite-role dispatch, so it never classifies as one.
        followup = isinstance(launch_input, dict) and launch_input.get('childThreadId') is not None
        if isinstance(task_id, str) and task_id and not followup:
            accepted.append((task_id, launch_input))
    assignments = {}
    for role in protocol['roles']:
        name = role['role']
        if role['dispatch'] == 'native':
            matches = [row for row in observations.get('subagents', [])
                       if isinstance(row, dict) and row.get('origin') == 'provider_native'
                       and row.get('prompt') == role.get('prompt')]  # missing projection fails closed
            if len(matches) == 1 and isinstance(matches[0].get('id'), str) and matches[0]['id']:
                assignments[name] = matches[0]['id']
            else:
                problems.append(f'{name}: {len(matches)} captured provider-native rows carry this role')
            continue
        matches = [task_id for task_id, launch_input in accepted
                   if role_dispatch_matches(launch_input, role, target)]
        if len(matches) == 1:
            assignments[name] = matches[0]
        else:
            problems.append(f'{name}: {len(matches)} accepted dispatch inputs carry this role')
    for task_id, launch_input in accepted:
        carrying = [role['role'] for role in protocol['roles'] if role['dispatch'] == 'app'
                    and role_dispatch_matches(launch_input, role, target)]
        if len(carrying) > 1:
            problems.append(f'{task_id} carries multiple frozen roles')
    app = [task_id for name, task_id in assignments.items() if name not in native_names]
    if len(app) != len(set(app)):
        problems.append('two frozen roles resolved to the same accepted task')
    return {'ok': not problems and len(assignments) == len(protocol['roles']),
            'assignments': assignments, 'problems': problems}


def reported_role_bindings(observations, protocol, canary_result):
    """Every finite-role field in the final report must equal the captured dispatch assignment.

    This covers the reported primary, each summary-boundary ID and the tracked
    follow-up identity, so a reordered or self-relabelled report fails even when its
    unordered set of owned task IDs is unchanged.
    """
    assignment = captured_role_assignments(observations, protocol)
    assignments = assignment['assignments']
    problems = list(assignment['problems'])
    if not isinstance(canary_result, dict):
        return {'ok': False, 'assignments': assignments,
                'problems': problems + ['canary result is not an object']}
    if canary_result.get('primary_task_id') != assignments.get('primary'):
        problems.append('reported primary does not match the captured primary dispatch')
    boundaries = canary_result.get('summary_boundary_task_ids')
    if not isinstance(boundaries, dict) or set(boundaries) != set(SUMMARY_BOUNDARY_KEYS):
        problems.append('reported summary boundary IDs are missing or malformed')
    else:
        for key in SUMMARY_BOUNDARY_KEYS:
            if boundaries.get(key) != assignments.get('summary-' + key):
                problems.append(f'reported summary binding for {key} does not match the captured dispatch')
    followup = canary_result.get('tracked_followup')
    if isinstance(followup, dict):
        original, new = followup.get('original_task_id'), followup.get('new_task_id')
        if original is not None and original != assignments.get('primary'):
            problems.append('tracked follow-up original task is not the captured primary assignment')
        if new is not None and new in set(assignments.values()):
            problems.append('tracked follow-up new task repeats a captured role assignment')
    return {'ok': not problems and bool(assignments), 'assignments': assignments, 'problems': problems}


class CapturedTaskClient:
    """Replay only actual task_status results emitted by the authenticated parent."""
    def __init__(self, observations):
        self.results = {}
        self.records = observations['tool_records']
        for row in observations['tool_records']:
            if row['toolName'] != 't3-code.task_status':
                continue
            task_id = row['input'].get('taskId')
            output = row['output']
            if not isinstance(task_id, str) or output.get('taskId') != task_id:
                raise ValueError('captured task status identity mismatch')
            self.results[task_id] = output

    def call(self, name, arguments):
        if name != 'task_status' or arguments.get('taskId') not in self.results:
            raise RuntimeError('authenticated parent task_status observation is unavailable')
        return {'structuredContent': self.results[arguments['taskId']]}

    def followup_observation(self, original_id, new_id):
        statuses = [(i, r['output']) for i, r in enumerate(self.records)
                    if r.get('toolName') == 't3-code.task_status' and r.get('input', {}).get('taskId') == original_id
                    and r.get('output', {}).get('taskId') == original_id]
        launches = [(i, r) for i, r in enumerate(self.records) if r.get('toolName') == 't3-code.delegate_task'
                    and r.get('output', {}).get('taskId') == new_id] if new_id else []
        if new_id:
            if len(launches) != 1:
                return None
            index, launch = launches[0]
            before = [out for i, out in statuses if i < index]
            after = [out for i, out in statuses if i > index]
            if not before or not after or launch['input'].get('childThreadId') != before[-1].get('childThreadId'):
                return None
            originals = [r for r in self.records if r.get('toolName') == 't3-code.delegate_task' and r.get('output', {}).get('taskId') == original_id]
            if not originals or not raw_equal(launch['input'].get('target'), originals[0]['input'].get('target')):
                return None
            return {'before': before[-1], 'after': after[-1], 'launch': launch}
        # Immutable before/after can be observed without a follow-up. A policy
        # refusal itself needs separate authoritative policy evidence.
        return {'before': statuses[0][1], 'after': statuses[-1][1], 'launch': None} if len(statuses) >= 2 else None


def verify_owned_tasks(observations, task_ids, target, native_probe=False, expected_input_sha256=None):
    accepted = {}
    for row in observations['tool_records']:
        if row['toolName'] == 't3-code.delegate_task':
            output = row['output']
            accepted[output.get('taskId')] = row
    client = CapturedTaskClient(observations)
    declared = set(task_ids)
    native = [row for row in observations['subagents'] if row.get('origin') == 'provider_native']
    visible = {row.get('id') for row in observations['subagents'] if row.get('origin') != 'provider_native'}
    if not native_probe:
        visible |= {row.get('id') for row in native}
    checks = {'all_declared_tasks_accepted': declared <= set(accepted),
              'no_unexpected_visible_children': visible == declared,
              'exact_targets': True, 'projected_child_selection': True,
              'projected_child_runs_terminal': True,
              'terminal_no_pending': True, 'all_children_successful': True}
    checks['task_ids_valid'] = bool(declared) and all(isinstance(value, str) and value for value in declared)
    for task_id in declared:
        launch = accepted.get(task_id)
        status = client.results.get(task_id)
        checks['exact_targets'] &= bool(launch and raw_equal(launch['input'].get('target'), target)
                                      and status and status.get('model') == target['model']
                                      and status.get('providerInstanceId') == target['providerInstanceId'])
        # The delegate_task input is what the parent asked for; T3's projection
        # of the child thread and its runs is what the host actually selected.
        checks['projected_child_selection'] &= projected_child_selection_matches(
            observations, task_id, status, target)
        # A cached terminal task_status does not override the current projection:
        # the child thread needs projected runs, one completed, none still active.
        checks['projected_child_runs_terminal'] &= projected_child_runs_terminal(
            observations, task_id, status)
        checks['terminal_no_pending'] &= bool(
            status and status.get('status') in {'completed', 'failed', 'cancelled', 'interrupted'}
            and status.get('workState') == 'result_available'
            and status.get('hasPendingChildRuns') is False)
        checks['all_children_successful'] &= bool(status and status.get('status') == 'completed')
    # No observed descendant thread may still have an active projected run.
    checks['no_active_descendant_run'] = all(
        row.get('status') in TERMINAL_RUN_STATUSES for row in observations.get('runs', [])
        if row.get('threadId') != observations['parent_thread_id'])
    pending = [r for r in observations.get('runtime_requests', []) if r.get('status') not in {'resolved', 'cancelled', 'failed'}]
    native_checks = {'exactly_one_native_probe': len(native) == 1,
                     'native_identity_and_target': False, 'native_terminal': False,
                     'native_thread_selection': False, 'native_runs_terminal_if_projected': False,
                     'native_hash_result': False, 'no_pending_approval': not pending}
    # Pinned T3 projects one thread but no run rows for provider-native
    # children, so zero runs is recorded explicitly rather than claimed as run evidence.
    native_runs_projected = None
    if native_probe and len(native) == 1:
        child = native[0]
        native_checks['native_identity_and_target'] = bool(
            child.get('threadId') == observations['parent_thread_id']
            and 'ISSUE28_NATIVE_PROBE' in child.get('prompt', '')
            and child.get('providerInstanceId') == target['providerInstanceId']
            and child.get('model') == target['model'] and child.get('childThreadId'))
        native_checks['native_hash_result'] = bool(expected_input_sha256 and isinstance(child.get('result'), str) and child['result'] == expected_input_sha256)
        native_checks['native_terminal'] = child.get('status') == 'completed' and bool(child.get('completedAt'))
        child_runs = [r for r in observations.get('runs', []) if r.get('threadId') == child.get('childThreadId')]
        child_threads = [r for r in observations.get('threads', []) if r.get('id') == child.get('childThreadId')]
        native_checks['native_thread_selection'] = bool(child_threads) and all(
            selection_matches(r.get('modelSelection'), target) for r in child_threads)
        native_checks['native_runs_terminal_if_projected'] = all(
            r.get('status') == 'completed' and selection_matches(r.get('modelSelection'), target) for r in child_runs)
        native_runs_projected = len(child_runs) if child_runs else 'none'
    native_verified = native_probe and all(native_checks.values())
    native_checks['native_runs_projected'] = native_runs_projected
    return {'verified': all(checks.values()), 'checks': checks, 'pending_approvals': pending,
            'native_probe_checks': native_checks, 'native_child_visibility_verified': native_verified,
            'native_child_visibility': 'observed finite native probe' if native_verified else
            'unverified: native target, lifecycle or visibility evidence is incomplete'}


def projected_child_thread(observations, task_id, status):
    """The single app-owned child thread named by the subagent rows and task status, or None."""
    rows = [row for row in observations.get('subagents', [])
            if row.get('id') == task_id and row.get('origin') != 'provider_native']
    children = {row.get('childThreadId') for row in rows}
    if isinstance(status, dict) and status.get('childThreadId') is not None:
        children.add(status.get('childThreadId'))
    if len(children) != 1:
        return None
    child = children.pop()
    return child if isinstance(child, str) and child else None


def projected_child_selection_matches(observations, task_id, status, target):
    """One app-owned child thread whose projected thread and runs carry the frozen selection."""
    child = projected_child_thread(observations, task_id, status)
    if child is None:
        return False
    threads = [row for row in observations.get('threads', []) if row.get('id') == child]
    runs = [row for row in observations.get('runs', []) if row.get('threadId') == child]
    return (bool(threads) and all(selection_matches(row.get('modelSelection'), target) for row in threads)
            and all(selection_matches(row.get('modelSelection'), target) for row in runs))


def projected_child_runs_terminal(observations, task_id, status):
    """App-owned children always have projected runs: one completed, none outside the terminal set."""
    child = projected_child_thread(observations, task_id, status)
    runs = [row for row in observations.get('runs', []) if child is not None and row.get('threadId') == child]
    return (bool(runs) and any(row.get('status') == 'completed' for row in runs)
            and all(row.get('status') in TERMINAL_RUN_STATUSES for row in runs))


def selection_matches(selection, target):
    """Validate the pinned host's option-row schema without aliases or duplicates."""
    if not isinstance(selection, dict) or selection.get('instanceId') != target['providerInstanceId'] or selection.get('model') != target['model']:
        return False
    options = selection.get('options')
    if not isinstance(options, list) or any(not isinstance(row, dict) or set(row) != {'id', 'value'} or not isinstance(row['id'], str) for row in options):
        return False
    values = {row['id']: row['value'] for row in options}
    return len(values) == len(options) and values == target['options'] and all(type(values[k]) is type(v) for k, v in target['options'].items())
