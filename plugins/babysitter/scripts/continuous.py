#!/usr/bin/env python3
"""Deterministic continuous-coordination state for babysitter (issue #94).

The helper keeps the coordinator's sweep state between turns: the authorised scope,
the host schedule that wakes it, queue age, last meaningful progress, the next
action/check deadline, admitted PRs and ownership. It makes no network, host,
model or clock calls. The coordinator supplies every observation and every
timestamp, so the same inputs always produce the same decisions and tests can move
a fake clock while a CI job stays queued.

Commands::

    start           create the state file and record the continuous-mode contract
    schedule-plan   the structured host schedule request (idempotent by key)
    schedule-record record the host's actual schedule ID and next run
    scheduler       record scheduler availability/authorisation for later wakes
    observe         reconcile one discovery snapshot (the core decision)
    dispatch        record a dispatch handle for a coordinator action
    fixer-done      clear the in-flight fixer guard after an ingested result
    resolve         close a known PR only from an explicit targeted host read
    cancel          stop this run; no further actions are produced
    resume          expose installed/policy version gaps and migrate explicitly
    status          compact read of the persisted state
    version         source and installed policy identity

No live verification is implied: only a recorded host schedule plus observed wakes
prove scheduled coverage. Without them the state reports its event-only gap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 1
POLICY_VERSION = 'continuous-1'
DEFAULT_CADENCE_SECONDS = 600
DEFAULT_QUEUE_THRESHOLD_SECONDS = 900
DEFAULT_STALL_THRESHOLD_SECONDS = 1800
DISCOVERY_RETRY_LIMIT = 3
MAX_STATE_BYTES = 4 * 1024 * 1024

PENDING_STATUSES = {'QUEUED', 'REQUESTED', 'WAITING', 'PENDING', 'IN_PROGRESS'}
RUNNING_STATUSES = {'IN_PROGRESS'}
PASSING_CONCLUSIONS = {'SUCCESS', 'NEUTRAL', 'SKIPPED'}
FAILING_CONCLUSIONS = {'FAILURE', 'CANCELLED', 'TIMED_OUT', 'STALE', 'ACTION_REQUIRED', 'ERROR'}

# Blockers that genuinely need a person. Everything routine in the playbook must
# resolve without a new question.
HUMAN_BLOCKERS = {
    'missing-authorization',
    'ownership-transfer',
    'material-product-choice',
    'missing-access',
    'protected-branch-decision',
}


class ContinuousError(Exception):
    """Invalid input or an unsafe state transition. Nothing is written."""


# ---------------------------------------------------------------------------
# small deterministic utilities


def now_iso(moment):
    if moment.tzinfo is None:
        raise ContinuousError('timestamps must carry an explicit timezone')
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def parse_time(value, field='timestamp'):
    if not isinstance(value, str) or not value.strip():
        raise ContinuousError(f'{field} must be an RFC 3339 string')
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContinuousError(f'{field} is not an RFC 3339 timestamp: {value!r}') from exc
    if parsed.tzinfo is None:
        raise ContinuousError(f'{field} must include an offset: {value!r}')
    return parsed.astimezone(timezone.utc)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def positive_int(value, field):
    if type(value) is not int or value < 1:
        raise ContinuousError(f'{field} must be a positive integer')
    return value


def require(condition, message):
    if not condition:
        raise ContinuousError(message)


def load_json(path):
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContinuousError(f'cannot read {path}: {exc.strerror or exc}') from exc
    if len(raw) > MAX_STATE_BYTES:
        raise ContinuousError(f'{path} exceeds the {MAX_STATE_BYTES}-byte state limit')
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContinuousError(f'{path} is not valid UTF-8 JSON: {exc}') from exc


def save_json(path, value):
    """Atomic replace, so an interrupted wake never leaves half a roster."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8') + b'\n'
    require(len(payload) <= MAX_STATE_BYTES, 'state exceeds the size limit')
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def state_path(path):
    return Path(path).expanduser().resolve()


def read_state(path):
    state = load_json(state_path(path))
    require(state.get('schema_version') == SCHEMA_VERSION, 'unsupported continuous state schema')
    require(state.get('policy_version') == POLICY_VERSION,
            f"state policy {state.get('policy_version')!r} differs from {POLICY_VERSION!r}; run resume")
    return state


def audit(state, now, kind, **fields):
    entry = {'at': now.isoformat().replace('+00:00', 'Z'), 'kind': kind}
    entry.update({key: value for key, value in fields.items() if value is not None})
    state.setdefault('audit', []).append(entry)
    state['audit'] = state['audit'][-200:]


def source_identity(script=__file__):
    package = Path(script).resolve().parents[1]
    meta = load_json(package / 'plugin.json')
    return {'plugin': meta.get('name'), 'version': meta.get('version'),
            'policy_version': policy_identity(meta), 'package_dir': str(package)}


def policy_identity(meta):
    continuous = meta.get('continuous') if isinstance(meta, dict) else None
    return (continuous or {}).get('policy_version') or POLICY_VERSION


# ---------------------------------------------------------------------------
# scope and observations


def scope_matches(scope, raw):
    kind = scope['kind']
    repo = str(raw.get('repo') or '')
    number = raw.get('number')
    if not re.fullmatch(r'[^/\s]+/[^/\s]+', repo) or type(number) is not int:
        return False
    if kind == 'repo':
        return repo.lower() == scope['value'].lower()
    if kind == 'org':
        return repo.split('/', 1)[0].lower() == scope['value'].lower()
    if kind == 'pr':
        return f'{repo}#{number}'.lower() == scope['value'].lower()
    return False


def pr_key(repo, number):
    return f'https://github.com/{repo}/pull/{number}'


def excluded(scope, raw):
    url = str(raw.get('url') or '')
    key = f"{raw.get('repo')}#{raw.get('number')}".lower()
    for value in scope.get('exclusions', []):
        if str(value).lower() in (url.lower(), key):
            return True
    if raw.get('excluded') is True:
        return True
    if raw.get('draft') is True and not scope.get('include_drafts', False):
        return True
    if raw.get('fork') is True and not scope.get('include_forks', False):
        return True
    return False


def normalise_check(row):
    require(isinstance(row, dict) and isinstance(row.get('name'), str) and row['name'],
            'each check needs a name')
    status = str(row.get('status') or '').upper()
    conclusion = str(row.get('conclusion') or '').upper() or None
    created = row.get('created_at') or row.get('createdAt')
    started = row.get('started_at') or row.get('startedAt')
    return {
        'name': row['name'],
        'status': status,
        'conclusion': conclusion,
        'created_at': created,
        'started_at': started,
        'head_sha': row.get('head_sha') or row.get('head_oid'),
    }


def check_is_pending(check):
    if check['conclusion'] in PASSING_CONCLUSIONS or check['conclusion'] in FAILING_CONCLUSIONS:
        return False
    # A queued job has no conclusion yet; a completed one with no conclusion is
    # unknown, not silently green.
    return check['status'] in PENDING_STATUSES or check['status'] not in ('COMPLETED', '')


def check_age_seconds(check, now):
    """Age of the oldest trustworthy clock for a pending job.

    A queued job has no runner, so ``started_at`` is null and creation time is the
    only honest start. A cancelled/rhyming API value never invents age.
    """
    for field in ('created_at', 'started_at'):
        value = check.get(field)
        if value:
            created = parse_time(value, field)
            return max(0, int((now - created).total_seconds()))
    return 0


def check_diagnosis(check):
    if check['status'] in RUNNING_STATUSES:
        return 'running-tests'
    if check['status'] == 'QUEUED' or check['status'] in ('REQUESTED', 'WAITING', 'PENDING'):
        return 'waiting-for-runner'
    if check['conclusion'] is None:
        return 'unknown-check-state'
    return 'finished'


def normalise_threads(raw):
    value = raw.get('unresolved_threads', 0)
    if type(value) is not int or value < 0:
        raise ContinuousError('unresolved_threads must be a non-negative integer')
    return value


def progress_signature(raw, checks, queue):
    """What actually changed for this PR. A repeated identical read is not progress."""
    return digest({
        'head': raw.get('head_sha'),
        'checks': sorted((c['name'], c['status'], c['conclusion']) for c in checks),
        'threads': normalise_threads(raw),
        'review': raw.get('review_decision'),
        'changes_requested': sorted(raw.get('changes_requested_by') or []),
        'merge_state': raw.get('merge_state_status') or raw.get('mergeable'),
        'state': str(raw.get('state') or 'OPEN').upper(),
        'queue': [(q['name'], q['status'], q.get('created_at')) for q in queue],
    })


def owner_state(raw):
    owner = raw.get('owner') or {}
    if not isinstance(owner, dict):
        raise ContinuousError('owner must be an object')
    return {
        'thread_id': owner.get('thread_id'),
        'status': owner.get('status') or 'none',
        'continuation': owner.get('continuation'),
        'fixer_in_flight': bool(owner.get('fixer_in_flight', False)),
    }


def owned_elsewhere(pr, self_thread):
    owner = pr.get('owner') or {}
    thread = owner.get('thread_id')
    if owner.get('status') not in ('active', 'parked'):
        return False
    if not thread or thread == self_thread:
        return False
    # A parked thread still owns the PR while its latest state maintains it. A
    # terminal turn alone (continuation 'handed-back' or none) releases it.
    if owner.get('status') == 'parked' and owner.get('continuation') not in ('maintainer-live', 'in-flight'):
        return False
    return True


# ---------------------------------------------------------------------------
# decisions


def queue_summary(checks, now, threshold):
    pending = [c for c in checks if check_is_pending(c)]
    rows = []
    for check in pending:
        age = check_age_seconds(check, now)
        rows.append({
            'name': check['name'],
            'status': check['status'] or 'UNKNOWN',
            'diagnosis': check_diagnosis(check),
            'age_seconds': age,
            'created_at': check.get('created_at'),
            'started_at': check.get('started_at'),
            'head_sha': check.get('head_sha'),
            'over_threshold': age >= threshold,
        })
    oldest = max(rows, key=lambda row: row['age_seconds'], default=None)
    return {
        'pending': rows,
        'oldest': oldest,
        'over_threshold': bool(oldest and oldest['over_threshold']),
        'failing': [c['name'] for c in checks if c['conclusion'] in FAILING_CONCLUSIONS],
    }


def deadline(now, seconds):
    return now_iso(now + timedelta(seconds=seconds))


def reconcile_pr(pr, state, now, discovery_complete):
    """Return (action, queue, blocked, progress) for one admitted open PR."""
    threshold = state['policy']['queue_threshold_seconds']
    stall = state['policy']['stall_threshold_seconds']
    cadence = state['policy']['cadence_seconds']
    observation = pr['observation']
    checks = observation.get('checks', [])
    queue = queue_summary(checks, now, threshold)
    raw_state = str(observation.get('state') or 'OPEN').upper()
    head = observation.get('head_sha')
    required = set(observation.get('required_contexts') or [])
    blocking_failing = [name for name in queue['failing'] if not required or name in required]
    progress = progress_signature(observation, checks, queue['pending'])

    if raw_state == 'MERGED':
        pr['state'] = 'merged'
        return ({'pr': pr['url'], 'kind': 'merged', 'reason': 'host observed a merge'},
                queue, None, progress)
    if raw_state == 'CLOSED':
        pr['state'] = 'closed'
        return ({'pr': pr['url'], 'kind': 'closed', 'reason': 'host observed a close without merge'},
                queue, None, progress)

    if pr.get('discovery_gap'):
        return ({'pr': pr['url'], 'kind': 'reconcile-discovery',
                 'reason': 'the current discovery snapshot omitted this known open PR',
                 'next_check_at': deadline(now, cadence)},
                queue, {'kind': 'discovery-omission', 'detail': pr['discovery_gap']}, progress)

    if not discovery_complete:
        return ({'pr': pr['url'], 'kind': 'retry-discovery',
                 'reason': 'discovery was partial; no completion claim is possible',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'discovery-incomplete', 'detail': state['discovery']['gaps']}, progress)

    if owned_elsewhere(pr, state.get('thread_id')):
        return ({'pr': pr['url'], 'kind': 'owned-elsewhere',
                 'reason': 'active ownership elsewhere; this run performs no writes',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'owned-elsewhere', 'owner': pr['owner'].get('thread_id')}, progress)

    stale = [row for row in queue['pending']
             if row.get('head_sha') and head and row['head_sha'] != head]
    if stale:
        detail = ', '.join(row['name'] for row in stale)
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': f'checks belong to a previous head: {detail}',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'stale-head-checks', 'detail': detail}, progress)

    fixer = pr.get('fixer') or {}
    if fixer.get('in_flight'):
        started = fixer.get('started_at') or pr.get('last_meaningful_progress_at')
        age = int((now - parse_time(started, 'fixer.started_at')).total_seconds()) if started else 0
        return ({'pr': pr['url'], 'kind': 'wait-fixer',
                 'reason': f"fixer {fixer.get('request_id')} is in flight",
                 'next_check_at': deadline(now, min(cadence, max(60, stall - age)))},
                queue, {'kind': 'fixer-in-flight', 'detail': fixer.get('request_id')}, progress)

    human = observation.get('human_blocker') or {}
    if human.get('kind') in HUMAN_BLOCKERS:
        return ({'pr': pr['url'], 'kind': 'needs-human',
                 'reason': human.get('detail') or human['kind'],
                 'next_check_at': deadline(now, cadence)},
                queue, {'kind': human['kind'], 'detail': human.get('detail')}, progress)
    # A non-human-only blocker supplied by the caller is still a concrete state.
    if human and human.get('kind'):
        return ({'pr': pr['url'], 'kind': 'blocked',
                 'reason': human.get('detail') or human['kind'],
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': human['kind'], 'detail': human.get('detail')}, progress)

    if queue['over_threshold']:
        oldest = queue['oldest']
        detail = (f"{oldest['name']} has been {oldest['diagnosis']} for "
                  f"{oldest['age_seconds']}s (threshold {threshold}s)")
        return ({'pr': pr['url'], 'kind': 'diagnose-queue',
                 'reason': detail, 'next_check_at': deadline(now, cadence)},
                queue, {'kind': oldest['diagnosis'], 'detail': detail, 'check': oldest['name']}, progress)

    if blocking_failing or observation.get('unresolved_threads', 0) > 0 or \
            str(observation.get('mergeable') or '').upper() == 'CONFLICTING':
        fingerprint = digest({'head': head, 'blockers': blocking_failing,
                              'threads': observation.get('unresolved_threads', 0),
                              'conflict': str(observation.get('mergeable') or '').upper()})
        request_key = f"{pr['number']}-maintain-{fingerprint[:12]}"
        existing = next((row for row in pr.get('dispatches', []) if row['request_id'] == request_key), None)
        if existing:
            return ({'pr': pr['url'], 'kind': 'wait-fixer',
                     'reason': f"repair already dispatched as {request_key}",
                     'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'fixer-in-flight', 'detail': request_key}, progress)
        reason = ('failing checks ' + ', '.join(blocking_failing)) if blocking_failing else (
            f"{observation.get('unresolved_threads')} unresolved thread(s)" if
            observation.get('unresolved_threads', 0) else 'merge conflict')
        return ({'pr': pr['url'], 'kind': 'dispatch-fixer', 'request_id': request_key,
                 'reason': reason, 'next_check_at': deadline(now, cadence)},
                queue, None, progress)

    checks_state = str(observation.get('checks_state') or '').upper()
    merge_state = str(observation.get('merge_state_status') or '').upper()
    if observation.get('checks_complete', True) and observation.get('required_contexts'):
        observed = {c['name'] for c in checks}
        missing = sorted(set(observation['required_contexts']) - observed)
        if missing:
            return ({'pr': pr['url'], 'kind': 'wait-checks',
                     'reason': 'required contexts missing from this head: ' + ', '.join(missing),
                     'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'missing-contexts', 'detail': missing}, progress)
    review = str(observation.get('review_decision') or '').upper()
    changes = observation.get('changes_requested_by') or []
    if review == 'CHANGES_REQUESTED' or changes:
        return ({'pr': pr['url'], 'kind': 'wait-review',
                 'reason': 'a review requests changes; request re-review after any fix',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'requested-changes', 'detail': changes}, progress)
    if checks_state in ('SUCCESS', 'EXPECTED') and merge_state in ('BLOCKED', 'UNSTABLE', 'UNKNOWN') \
            and not blocking_failing and not queue['pending']:
        return ({'pr': pr['url'], 'kind': 'diagnose-gate',
                 'reason': f'checks report {checks_state} but the aggregate gate is {merge_state}',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'stuck-aggregate-gate', 'detail': merge_state}, progress)

    if not re.fullmatch(r'[0-9a-f]{40}', str(head or '')):
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': 'no exact current head was observed; no merge is possible',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'missing-head', 'detail': 'head_sha is absent or not a full commit'}, progress)

    if observation.get('checks_complete', True):
        checks_ok = checks_state in ('SUCCESS', 'EXPECTED')
    else:
        # A partial reader line lists only pending and failing contexts. GitHub's
        # aggregate state already encodes the required-check result.
        checks_ok = merge_state in ('CLEAN', 'HAS_HOOKS', 'UNSTABLE')
    if str(observation.get('mergeable') or '').upper() == 'MERGEABLE' and \
            merge_state in ('CLEAN', 'HAS_HOOKS', 'UNSTABLE', '') and not queue['pending'] and \
            not blocking_failing and observation.get('unresolved_threads', 0) == 0 and checks_ok:
        if any(row.get('kind') == 'merge' for row in pr.get('dispatches', [])):
            return ({'pr': pr['url'], 'kind': 'merge-pending',
                     'reason': 'a merge was already requested for this head; observe before retrying',
                     'next_check_at': deadline(now, cadence)}, queue, None, progress)
        return ({'pr': pr['url'], 'kind': 'merge',
                 'reason': 'GitHub reports every gate green at this head',
                 'next_check_at': deadline(now, cadence)}, queue, None, progress)

    last = parse_time(pr.get('last_meaningful_progress_at') or pr['admitted_at'], 'last progress')
    stalled = (now - last).total_seconds() >= stall
    if stalled:
        detail = f'no meaningful progress for {int((now - last).total_seconds())}s'
        return ({'pr': pr['url'], 'kind': 'diagnose-stall', 'reason': detail,
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'stalled-work', 'detail': detail}, progress)

    if queue['pending']:
        oldest = queue['oldest']
        remaining = max(0, threshold - oldest['age_seconds'])
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': f"{oldest['name']} is {oldest['diagnosis']} ({oldest['age_seconds']}s)",
                 'next_check_at': deadline(now, min(cadence, max(30, remaining)))},
                queue, {'kind': oldest['diagnosis'], 'detail': oldest['name']}, progress)

    # Everything GitHub needs is not visible yet: a concrete wait, never "all done".
    return ({'pr': pr['url'], 'kind': 'unknown-state',
             'reason': 'no green gate and no named blocker in this observation',
             'next_check_at': deadline(now, cadence)}, queue,
            {'kind': 'unclassified', 'detail': 'refresh required'}, progress)


# ---------------------------------------------------------------------------
# commands


def cmd_start(args):
    now = parse_time(args.now, '--now')
    scope_kind = args.scope_kind
    require(scope_kind in ('org', 'repo', 'pr'), '--scope-kind must be org, repo or pr')
    value = args.scope_value.strip()
    require(bool(value), '--scope-value is required')
    cadence = positive_int(args.cadence_seconds, '--cadence-seconds')
    queue_threshold = positive_int(args.queue_threshold_seconds, '--queue-threshold-seconds')
    stall = positive_int(args.stall_threshold_seconds, '--stall-threshold-seconds')
    require(queue_threshold >= 60, 'queue threshold must allow at least one sweep')
    mode = args.scheduler
    authorization = {'state': 'unavailable', 'source': None, 'sha256': None}
    if mode == 'scheduled':
        require(args.authorization_source, 'scheduled mode requires --authorization-source')
        source = Path(args.authorization_source).expanduser()
        require(source.is_file(), f'authorization source does not exist: {source}')
        authorization = {'state': 'authorized', 'source': str(source),
                         'sha256': sha256_file(source)}
    state = {
        'schema_version': SCHEMA_VERSION,
        'policy_version': POLICY_VERSION,
        'created_at': now_iso(now),
        'updated_at': now_iso(now),
        'thread_id': args.thread_id,
        'scope': {
            'kind': scope_kind, 'value': value,
            'include_drafts': bool(args.include_drafts),
            'include_forks': bool(args.include_forks),
            'exclusions': list(args.exclude),
        },
        'policy': {
            'cadence_seconds': cadence,
            'queue_threshold_seconds': queue_threshold,
            'stall_threshold_seconds': stall,
        },
        'scheduler': {
            'mode': mode,
            'authorization': authorization,
            'schedule_id': None,
            'next_run_at': None,
            'recorded_at': None,
            'stop': None,
            'gap': (None if mode == 'scheduled' else
                    'event-only: no idle discovery, queue-age diagnosis or stalled-work wake'),
        },
        'package': {'pinned_version': args.package_version},
        'prs': {},
        'events': {},
        'discovery': {'attempts': 0, 'last_attempt_at': None, 'last_complete_at': None,
                      'gaps': [], 'complete': None},
        'cancelled': None,
        'migration': None,
        'audit': [],
    }
    audit(state, now, 'start', scheduler=mode, scope=f'{scope_kind}:{value}')
    save_json(state_path(args.state), state)
    return {'status': 'started', 'state': str(state_path(args.state)),
            'policy_version': POLICY_VERSION, 'scheduler': state['scheduler'],
            'policy': state['policy'], 'scope': state['scope']}


def schedule_request(state):
    scope = state['scope']
    key = f"babysitter-{scope['kind']}-{scope['value'].replace('/', '-')}-{POLICY_VERSION}"
    prompt = (f"Continue the authorised babysitter {scope['kind']} sweep for {scope['value']}. "
              "Refresh discovery, diagnose queue age and stalled work, admit new matching PRs, "
              "and continue only actions already authorised by the owner's request. "
              "Report concrete blockers, the next action and the next wake.")
    return {
        'key': key,
        'clientRequestId': key,
        'tool': 'schedule_task',
        'arguments': {
            'schedule': {'type': 'interval', 'everyMs': state['policy']['cadence_seconds'] * 1000},
            'bindToCurrentThread': True,
            'prompt': prompt,
            'title': f"babysitter {scope['kind']} {scope['value']} continuous sweep",
            'clientRequestId': key,
        },
    }


def cmd_schedule_plan(args):
    state = read_state(args.state)
    request = schedule_request(state)
    if state['scheduler'].get('schedule_id'):
        return {'status': 'already-scheduled', 'schedule_id': state['scheduler']['schedule_id'],
                'next_run_at': state['scheduler'].get('next_run_at'),
                'stop': state['scheduler'].get('stop'), 'request': request,
                'instruction': 'do not create a second schedule'}
    if state['scheduler']['mode'] != 'scheduled':
        return {'status': 'event-only', 'request': None,
                'gap': state['scheduler']['gap'],
                'instruction': 'schedule only with explicit owner authorization'}
    return {'status': 'plan', 'request': request,
            'stop_after_create': {'tool': 'delete_scheduled_task',
                                  'arguments': {'scheduledTaskId': '<returned schedule id>'}}}


def cmd_schedule_record(args):
    state = read_state(args.state)
    now = parse_time(args.now, '--now')
    require(state['scheduler']['mode'] == 'scheduled',
            'event-only runs cannot record a host schedule; obtain scheduler authorization first')
    require(bool(args.schedule_id), '--schedule-id is required')
    require(bool(args.next_run_at), '--next-run-at is required')
    next_run = parse_time(args.next_run_at, '--next-run-at')
    require(next_run > now, '--next-run-at must be after the recording time')
    current = state['scheduler'].get('schedule_id')
    if current and current != args.schedule_id:
        raise ContinuousError(
            f"a different schedule ({current}) already owns this scope; "
            "stop it before creating another")
    request = schedule_request(state)
    state['scheduler'].update({
        'schedule_id': args.schedule_id,
        'next_run_at': now_iso(next_run),
        'recorded_at': now_iso(now),
        'stop': {'tool': 'delete_scheduled_task',
                 'arguments': {'scheduledTaskId': args.schedule_id}},
        'gap': None,
    })
    state['scheduler']['request_key'] = request['key']
    duplicate = current == args.schedule_id
    audit(state, now, 'schedule', schedule_id=args.schedule_id, duplicate=duplicate)
    save_json(state_path(args.state), state)
    return {'status': 'already-recorded' if duplicate else 'recorded',
            'duplicate': duplicate, 'schedule_id': args.schedule_id,
            'next_run_at': state['scheduler']['next_run_at'],
            'stop': state['scheduler']['stop']}


def cmd_scheduler(args):
    state = read_state(args.state)
    now = parse_time(args.now, '--now')
    available = args.available == 'yes'
    authorized = args.authorized == 'yes'
    if available and authorized:
        require(state['scheduler']['authorization'].get('source') and
                state['scheduler']['authorization'].get('sha256'),
                'scheduler authorization needs a recorded owner source')
        state['scheduler']['mode'] = 'scheduled'
        state['scheduler']['authorization'] = {
            'state': 'authorized', 'source': state['scheduler']['authorization'].get('source'),
            'sha256': state['scheduler']['authorization'].get('sha256')}
        state['scheduler']['gap'] = None
        outcome = 'scheduled'
    else:
        state['scheduler']['mode'] = 'event-only'
        state['scheduler']['authorization'] = {
            'state': 'unavailable' if not available else 'unauthorized',
            'source': state['scheduler']['authorization'].get('source'),
            'sha256': state['scheduler']['authorization'].get('sha256')}
        state['scheduler']['gap'] = ('scheduler unavailable' if not available else
                                     'scheduler not authorized by the owner') + \
            '; no idle discovery, queue-age diagnosis or stalled-work wake'
        outcome = 'event-only'
    state['scheduler']['recorded_at'] = now_iso(now)
    audit(state, now, 'scheduler', mode=outcome)
    save_json(state_path(args.state), state)
    return {'status': outcome, 'scheduler': state['scheduler'],
            'coverage': ('scheduled' if outcome == 'scheduled' else 'event-only'),
            'gap': state['scheduler']['gap']}


def normalise_pr(raw, now):
    repo = raw.get('repo')
    number = raw.get('number')
    require(isinstance(repo, str) and re.fullmatch(r'[^/\s]+/[^/\s]+', repo),
            'each PR needs a repo as owner/name')
    require(type(number) is int and number > 0, 'each PR needs a positive number')
    url = str(raw.get('url') or pr_key(repo, number))
    if raw.get('checks') is not None:
        check_rows = raw['checks']
        checks_complete = True
    else:
        # A list-prs.sh line carries pending_checks and a failing-name list. Accept it
        # directly so the coordinator does not have to reinterpret the reader.
        check_rows = list(raw.get('pending_checks') or [])
        check_rows += [{'name': name, 'status': 'COMPLETED', 'conclusion': 'FAILURE'}
                       for name in raw.get('failing') or []]
        checks_complete = False
    checks = [normalise_check(c) for c in check_rows]
    default_check_head = raw.get('checks_head_sha')
    if default_check_head:
        for check in checks:
            if not check['head_sha']:
                check['head_sha'] = default_check_head
    observation = {
        'state': str(raw.get('state') or 'OPEN').upper(),
        'head_sha': raw.get('head_sha') or raw.get('head_oid'),
        'checks': checks,
        'checks_complete': checks_complete,
        'checks_state': raw.get('checks_state'),
        'required_contexts': list(raw.get('required_contexts') or []),
        'unresolved_threads': normalise_threads(raw),
        'review_decision': raw.get('review_decision'),
        'changes_requested_by': list(raw.get('changes_requested_by') or []),
        'mergeable': raw.get('mergeable'),
        'merge_state_status': raw.get('merge_state_status'),
        'draft': bool(raw.get('draft')),
        'fork': bool(raw.get('fork')),
        'human_blocker': raw.get('human_blocker'),
        'fixer_in_flight': bool((raw.get('owner') or {}).get('fixer_in_flight')),
    }
    return {'url': url, 'repo': repo, 'number': number, 'title': raw.get('title'),
            'observation': observation, 'owner': owner_state(raw)}


def reconcile_observation(state, observation, now, wake_id, wake_kind):
    """Apply one discovery snapshot. Returns the public decision object."""
    require(isinstance(observation, dict), 'observation input must be an object')
    require(isinstance(observation.get('prs'), list), 'observation needs a prs list')
    gaps = observation.get('gaps') or []
    require(isinstance(gaps, list) and all(isinstance(gap, dict) for gap in gaps),
            'observation gaps must be objects')
    if observation.get('complete') is not True and not gaps:
        gaps = [{'kind': 'incomplete', 'detail': 'observation did not assert complete discovery'}]
    complete = observation.get('complete') is True and not gaps
    raw_rows = [normalise_pr(raw, now) for raw in observation['prs']]
    require(len({row['url'] for row in raw_rows}) == len(raw_rows),
            'observation lists the same PR more than once')
    wake_kind = wake_kind or 'manual'
    wake_id = wake_id or digest({'at': now_iso(now), 'prs': [row['url'] for row in raw_rows],
                                 'gaps': gaps, 'kind': wake_kind})[:16]
    event_key = digest({'wake': wake_id, 'kind': wake_kind, 'observation': observation})
    if event_key in state['events']:
        return {'status': 'duplicate', 'wake': {'id': wake_id, 'kind': wake_kind, 'duplicate': True},
                'actions': [], 'admitted': [], 'human_questions': [],
                'coverage': ('scheduled' if state['scheduler']['mode'] == 'scheduled' else 'event-only'),
                'message': 'this wake and observation were already reconciled; no new work was created'}

    admitted, actions, questions, queue_rows = [], [], [], []
    seen_urls = set()
    progressed = False
    for row in raw_rows:
        seen_urls.add(row['url'])
        if not scope_matches(state['scope'], {'repo': row['repo'], 'number': row['number']}):
            continue
        if excluded(state['scope'], {'url': row['url'], 'repo': row['repo'],
                                     'number': row['number'], 'draft': row['observation']['draft'],
                                     'fork': row['observation']['fork']}):
            continue
        pr = state['prs'].get(row['url'])
        is_new = pr is None
        if is_new:
            pr = {
                'url': row['url'], 'repo': row['repo'], 'number': row['number'],
                'title': row['title'], 'state': 'open',
                'admitted_at': now_iso(now), 'first_seen_at': now_iso(now),
                'last_seen_at': now_iso(now), 'last_meaningful_progress_at': now_iso(now),
                'observation': row['observation'], 'owner': row['owner'],
                'dispatches': [], 'fixer': {'in_flight': False, 'request_id': None,
                                            'started_at': None},
                'discovery_gap': None,
            }
            state['prs'][row['url']] = pr
            admitted.append({'url': row['url'], 'repo': row['repo'], 'number': row['number'],
                             'reason': 'matched the authorised continuing scope'})
            progressed = True
        else:
            pr['last_seen_at'] = now_iso(now)
            pr['title'] = row['title'] or pr.get('title')
            pr['owner'] = row['owner']
            pr['observation'] = row['observation']
            pr['discovery_gap'] = None
        queue = queue_summary(pr['observation']['checks'], now, state['policy']['queue_threshold_seconds'])
        signature = progress_signature(pr['observation'], pr['observation']['checks'], queue['pending'])
        if pr.get('progress_signature') != signature:
            pr['progress_signature'] = signature
            if not is_new:
                pr['last_meaningful_progress_at'] = now_iso(now)
                progressed = True
        # A fixer in flight is discovered from the observation (host handle state).
        # Only an ingested result/local fixer-done clears the guard; a PR event
        # alone must not let a merge race a running writer.
        if row['observation'].get('fixer_in_flight') and not pr['fixer'].get('in_flight'):
            pr['fixer'] = {'in_flight': True, 'request_id': None,
                           'started_at': pr['last_meaningful_progress_at']}

    # Omissions never close a known-open PR. Only explicit host state does.
    omitted = []
    for url, pr in state['prs'].items():
        if pr.get('state') != 'open' or url in seen_urls:
            continue
        pr['discovery_gap'] = 'omitted from a partial or temporary discovery snapshot'
        omitted.append(url)

    for url, pr in state['prs'].items():
        if pr.get('state') != 'open':
            continue
        action, queue, blocked, signature = reconcile_pr(pr, state, now, complete)
        if blocked:
            action = {**action, 'blocked': blocked}
        pr['next_action'] = action
        pr['blocked'] = blocked
        pr['queue'] = queue
        if action['kind'] == 'needs-human':
            question = {'pr': url, 'kind': blocked['kind'],
                        'question': (pr['observation'].get('human_blocker') or {}).get('question'),
                        'recommended': (pr['observation'].get('human_blocker') or {}).get('recommended')}
            questions.append(question)
        actions.append(action)
        if queue.get('oldest'):
            queue_rows.append({'pr': url, **queue['oldest']})

    state['discovery'].update({
        'last_attempt_at': now_iso(now),
        'gaps': gaps,
        'complete': complete,
        'omitted': omitted,
    })
    if complete:
        state['discovery']['last_complete_at'] = now_iso(now)
        state['discovery']['attempts'] = 0
    else:
        state['discovery']['attempts'] = int(state['discovery'].get('attempts', 0)) + 1
        if state['discovery']['attempts'] >= DISCOVERY_RETRY_LIMIT:
            actions.append({'kind': 'discovery-blocked', 'reason':
                            f"discovery incomplete after {state['discovery']['attempts']} attempts",
                            'next_check_at': deadline(now, state['policy']['cadence_seconds']),
                            'blocked': {'kind': 'discovery-incomplete', 'detail': gaps}})
    state['events'][event_key] = now_iso(now)
    if len(state['events']) > 500:
        state['events'] = dict(list(state['events'].items())[-500:])
    state['updated_at'] = now_iso(now)
    audit(state, now, 'observe', wake=wake_id, wake_kind=wake_kind,
          admitted=len(admitted), actions=len(actions), progress=progressed)
    next_wake = deadline(now, state['policy']['cadence_seconds'])
    if state['scheduler'].get('next_run_at') and \
            parse_time(state['scheduler']['next_run_at']) > now:
        next_wake = state['scheduler']['next_run_at']
    return {
        'status': 'cancelled' if state.get('cancelled') else 'ok',
        'wake': {'id': wake_id, 'kind': wake_kind, 'duplicate': False},
        'admitted': admitted,
        'actions': actions,
        'queue': queue_rows,
        'discovery': {'complete': complete, 'gaps': gaps, 'omitted': omitted,
                      'attempts': state['discovery']['attempts']},
        'scheduler': {'mode': state['scheduler']['mode'],
                      'schedule_id': state['scheduler'].get('schedule_id'),
                      'next_run_at': state['scheduler'].get('next_run_at'),
                      'stop': state['scheduler'].get('stop'),
                      'gap': state['scheduler'].get('gap')},
        'coverage': ('scheduled' if state['scheduler']['mode'] == 'scheduled' else 'event-only'),
        'human_questions': questions,
        'progress': {'meaningful': progressed},
        'next_wake_at': next_wake,
        'policy_version': state['policy_version'],
    }


def cmd_observe(args):
    path = state_path(args.state)
    state = read_state(path)
    now = parse_time(args.now, '--now')
    if state.get('cancelled'):
        return {'status': 'cancelled', 'actions': [], 'admitted': [], 'human_questions': [],
                'cancelled': state['cancelled'],
                'message': 'this run was cancelled; resume explicitly to continue'}
    observation = load_json(args.observation)
    result = reconcile_observation(state, observation, now, args.wake_id, args.wake_kind)
    if result['status'] != 'duplicate':
        save_json(path, state)
    return result


def cmd_dispatch(args):
    path = state_path(args.state)
    state = read_state(path)
    now = parse_time(args.now, '--now')
    pr = state['prs'].get(args.pr)
    require(pr is not None, f'unknown PR: {args.pr}')
    require(bool(args.request_id), '--request-id is required')
    require(args.kind in ('fixer', 'merge', 'resolution'),
            'dispatch kind must be fixer, merge or resolution')
    existing = next((row for row in pr['dispatches'] if row['request_id'] == args.request_id), None)
    if existing:
        return {'status': 'duplicate', 'request_id': args.request_id,
                'host_task_id': existing.get('host_task_id'), 'dispatch': existing}
    if args.kind == 'fixer':
        row = {'request_id': args.request_id, 'host_task_id': args.host_task_id,
               'kind': 'fixer', 'created_at': now_iso(now)}
        pr['dispatches'].append(row)
        pr['fixer'] = {'in_flight': True, 'request_id': args.request_id,
                       'started_at': now_iso(now)}
        audit(state, now, 'dispatch', pr=args.pr, request_id=args.request_id,
              host_task_id=args.host_task_id)
        save_json(path, state)
        return {'status': 'recorded', 'dispatch': row, 'fixer': pr['fixer']}
    row = {'request_id': args.request_id, 'kind': args.kind, 'created_at': now_iso(now)}
    pr['dispatches'].append(row)
    audit(state, now, 'dispatch', pr=args.pr, request_id=args.request_id,
          dispatch_kind=args.kind)
    save_json(path, state)
    return {'status': 'recorded', 'dispatch': row}


def cmd_resolve(args):
    """Close a known PR only from an explicit targeted host read, never from omission."""
    path = state_path(args.state)
    state = read_state(path)
    now = parse_time(args.now, '--now')
    pr = state['prs'].get(args.pr)
    require(pr is not None, f'unknown PR: {args.pr}')
    require(args.state_value in ('merged', 'closed'), '--state must be merged or closed')
    if args.state_value == 'merged':
        require(bool(args.head), 'merged resolution needs the observed merge head')
    pr['state'] = args.state_value
    pr['resolved_at'] = now_iso(now)
    pr['resolved_head'] = args.head
    pr['fixer'] = {'in_flight': False, 'request_id': None, 'started_at': None}
    pr['next_action'] = {'pr': args.pr, 'kind': args.state_value,
                         'reason': 'explicit targeted host observation'}
    audit(state, now, 'resolve', pr=args.pr, resolved=args.state_value, head=args.head)
    save_json(path, state)
    return {'status': 'resolved', 'pr': args.pr, 'state': args.state_value,
            'head': args.head}


def cmd_fixer_done(args):
    path = state_path(args.state)
    state = read_state(path)
    now = parse_time(args.now, '--now')
    pr = state['prs'].get(args.pr)
    require(pr is not None, f'unknown PR: {args.pr}')
    pr['fixer'] = {'in_flight': False, 'request_id': None, 'started_at': None}
    pr['last_meaningful_progress_at'] = now_iso(now)
    audit(state, now, 'fixer-done', pr=args.pr)
    save_json(path, state)
    return {'status': 'cleared', 'pr': args.pr}


def cmd_cancel(args):
    path = state_path(args.state)
    state = read_state(path)
    now = parse_time(args.now, '--now')
    state['cancelled'] = {'at': now_iso(now), 'reason': args.reason}
    audit(state, now, 'cancel', reason=args.reason)
    save_json(path, state)
    return {'status': 'cancelled', 'cancelled': state['cancelled'],
            'scheduler_stop': state['scheduler'].get('stop'),
            'instruction': 'stop the owned host schedule; no further actions will be produced'}


def cmd_resume(args):
    path = state_path(args.state)
    state = load_json(path)
    require(state.get('schema_version') == SCHEMA_VERSION, 'unsupported continuous state schema')
    now = parse_time(args.now, '--now')
    installed = source_identity(args.script)
    gaps = []
    if state.get('policy_version') != installed['policy_version']:
        gaps.append({'kind': 'policy-version',
                     'state': state.get('policy_version'), 'installed': installed['policy_version']})
    pinned = (state.get('package') or {}).get('pinned_version')
    if args.package_version and pinned and args.package_version != pinned:
        gaps.append({'kind': 'package-version',
                     'state_pinned': pinned, 'installed_running': args.package_version})
    if args.package_version and installed['version'] and \
            args.package_version.split('+', 1)[0] != installed['version']:
        gaps.append({'kind': 'installed-drift',
                     'installed_running': args.package_version,
                     'installed_on_disk': installed['version']})
    if state.get('cancelled') and not args.resume_cancelled and not gaps:
        return {'status': 'cancelled', 'cancelled': state['cancelled'],
                'gaps': gaps, 'changed': False,
                'instruction': 'resume a cancelled run only with --resume-cancelled'}
    if gaps and not args.accept_migration:
        return {'status': 'migration-required', 'gaps': gaps, 'changed': False,
                'installed': installed,
                'instruction': 'preserve the pinned brief and state; pass --accept-migration '
                               'with an owner decision after the supported package upgrade'}
    require(not gaps or args.owner_decision_id,
            'accepting a policy/package migration requires --owner-decision-id')
    changed = False
    if gaps:
        if state.get('migration') is None:
            state['migration'] = {'at': now_iso(now), 'from': state.get('policy_version'),
                                  'to': installed['policy_version'],
                                  'owner_decision_id': args.owner_decision_id,
                                  'gaps': gaps}
        state['policy_version'] = installed['policy_version']
        changed = True
    if state.get('cancelled') and args.resume_cancelled:
        state['cancelled'] = None
        changed = True
    if args.package_version:
        state.setdefault('package', {})['pinned_version'] = args.package_version
    state['updated_at'] = now_iso(now)
    audit(state, now, 'resume', gaps=gaps, changed=changed)
    save_json(path, state)
    return {'status': 'resumed', 'changed': changed, 'gaps': gaps,
            'policy_version': state['policy_version'], 'installed': installed,
            'migration': state.get('migration')}


def cmd_status(args):
    state = read_state(args.state)
    open_prs = [url for url, pr in state['prs'].items() if pr.get('state') == 'open']
    return {
        'status': 'cancelled' if state.get('cancelled') else 'active',
        'policy_version': state['policy_version'],
        'scope': state['scope'],
        'policy': state['policy'],
        'scheduler': state['scheduler'],
        'coverage': ('scheduled' if state['scheduler']['mode'] == 'scheduled' else 'event-only'),
        'open_prs': open_prs,
        'prs': {url: {'next_action': pr.get('next_action'), 'blocked': pr.get('blocked'),
                      'queue': pr.get('queue', {}).get('oldest'),
                      'last_meaningful_progress_at': pr.get('last_meaningful_progress_at'),
                      'owner': pr.get('owner'), 'fixer': pr.get('fixer')}
                for url, pr in state['prs'].items()},
        'discovery': state['discovery'],
        'cancelled': state.get('cancelled'),
    }


def cmd_version(args):
    identity = source_identity(args.script)
    return {'status': 'ok', **identity}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--script', default=__file__, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='command', required=True)

    def state_arg(command):
        command.add_argument('--state', required=True)

    start = sub.add_parser('start')
    state_arg(start)
    start.add_argument('--now', required=True)
    start.add_argument('--scope-kind', required=True)
    start.add_argument('--scope-value', required=True)
    start.add_argument('--thread-id')
    start.add_argument('--cadence-seconds', type=int, default=DEFAULT_CADENCE_SECONDS)
    start.add_argument('--queue-threshold-seconds', type=int, default=DEFAULT_QUEUE_THRESHOLD_SECONDS)
    start.add_argument('--stall-threshold-seconds', type=int, default=DEFAULT_STALL_THRESHOLD_SECONDS)
    start.add_argument('--scheduler', choices=('scheduled', 'event-only'), default='event-only')
    start.add_argument('--authorization-source')
    start.add_argument('--package-version')
    start.add_argument('--include-drafts', action='store_true')
    start.add_argument('--include-forks', action='store_true')
    start.add_argument('--exclude', action='append', default=[])
    start.set_defaults(func=cmd_start)

    plan = sub.add_parser('schedule-plan')
    state_arg(plan)
    plan.set_defaults(func=cmd_schedule_plan)

    record = sub.add_parser('schedule-record')
    state_arg(record)
    record.add_argument('--now', required=True)
    record.add_argument('--schedule-id', required=True)
    record.add_argument('--next-run-at', required=True)
    record.set_defaults(func=cmd_schedule_record)

    scheduler = sub.add_parser('scheduler')
    state_arg(scheduler)
    scheduler.add_argument('--now', required=True)
    scheduler.add_argument('--available', choices=('yes', 'no'), required=True)
    scheduler.add_argument('--authorized', choices=('yes', 'no'), required=True)
    scheduler.set_defaults(func=cmd_scheduler)

    observe = sub.add_parser('observe')
    state_arg(observe)
    observe.add_argument('--now', required=True)
    observe.add_argument('--observation', required=True)
    observe.add_argument('--wake-id')
    observe.add_argument('--wake-kind', choices=('schedule', 'event', 'manual', 'resume'), default='manual')
    observe.set_defaults(func=cmd_observe)

    dispatch = sub.add_parser('dispatch')
    state_arg(dispatch)
    dispatch.add_argument('--now', required=True)
    dispatch.add_argument('--pr', required=True)
    dispatch.add_argument('--request-id', required=True)
    dispatch.add_argument('--kind', choices=('fixer', 'merge', 'resolution'), required=True)
    dispatch.add_argument('--host-task-id')
    dispatch.set_defaults(func=cmd_dispatch)

    done = sub.add_parser('fixer-done')
    state_arg(done)
    done.add_argument('--now', required=True)
    done.add_argument('--pr', required=True)
    done.set_defaults(func=cmd_fixer_done)

    resolve = sub.add_parser('resolve')
    state_arg(resolve)
    resolve.add_argument('--now', required=True)
    resolve.add_argument('--pr', required=True)
    resolve.add_argument('--resolution', dest='state_value', required=True,
                         choices=('merged', 'closed'))
    resolve.add_argument('--head')
    resolve.set_defaults(func=cmd_resolve)

    cancel = sub.add_parser('cancel')
    state_arg(cancel)
    cancel.add_argument('--now', required=True)
    cancel.add_argument('--reason', required=True)
    cancel.set_defaults(func=cmd_cancel)

    resume = sub.add_parser('resume')
    state_arg(resume)
    resume.add_argument('--now', required=True)
    resume.add_argument('--package-version')
    resume.add_argument('--accept-migration', action='store_true')
    resume.add_argument('--owner-decision-id')
    resume.add_argument('--resume-cancelled', action='store_true')
    resume.set_defaults(func=cmd_resume)

    status = sub.add_parser('status')
    state_arg(status)
    status.set_defaults(func=cmd_status)

    version = sub.add_parser('version')
    version.set_defaults(func=cmd_version)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except ContinuousError as exc:
        print(f'continuous_error: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
