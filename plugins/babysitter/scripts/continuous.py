#!/usr/bin/env python3
"""Deterministic continuous-coordination state for babysitter (issue #94).

The helper keeps the coordinator's sweep state between turns: the authorised scope,
the host schedule that wakes it, queue age, last meaningful progress, the next
action/check deadline, admitted PRs and ownership. It makes no network, host,
model or clock calls. The coordinator supplies every observation and every
timestamp, so the same inputs always produce the same decisions and tests can move
a fake clock while a CI job stays queued.

Commands::

    start           create state exclusively and record the continuous-mode contract
    schedule-plan   the structured host schedule request (idempotent by key)
    schedule-record record or refresh the host's schedule ID and next run
    schedule-stop   record a verified stopped schedule before re-arming
    scheduler       record scheduler availability/authorisation for later wakes
    observe         reconcile one discovery snapshot (the core decision)
    dispatch        reserve a fixer, merge or resolution action before host execution
    receipt         record a dispatch outcome; stale replays change nothing
    fixer-done      accepted fixer result shorthand for receipt --status succeeded
    resolve         close a known PR only from an explicit targeted host read
    cancel          stop this run; no further actions are produced
    resume          expose installed/policy version gaps and migrate explicitly
    preflight       expose an older pinned job's continuous-coverage gap, read-only
    status          compact read of the persisted state
    version         source and installed policy identity

No live verification is implied: only a recorded host schedule plus observed wakes
prove scheduled coverage. Without them the state reports its event-only gap.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # POSIX hosts only; the plugin already requires bash and gh.
    import fcntl
except ImportError:  # pragma: no cover - documented as an explicit failure below
    fcntl = None

SCHEMA_VERSION = 1
POLICY_VERSION = 'continuous-1'
DEFAULT_CADENCE_SECONDS = 600
DEFAULT_QUEUE_THRESHOLD_SECONDS = 900
DEFAULT_STALL_THRESHOLD_SECONDS = 1800
DISCOVERY_RETRY_LIMIT = 3
MAX_REPAIR_ATTEMPTS = 3
MAX_MERGE_ATTEMPTS = 3
MAX_REVIEW_ATTEMPTS = 2
MAX_STATE_BYTES = 4 * 1024 * 1024

PENDING_STATUSES = {'QUEUED', 'REQUESTED', 'WAITING', 'PENDING', 'IN_PROGRESS'}
RUNNING_STATUSES = {'IN_PROGRESS'}
PASSING_CONCLUSIONS = {'SUCCESS', 'NEUTRAL', 'SKIPPED'}
FAILING_CONCLUSIONS = {'FAILURE', 'CANCELLED', 'TIMED_OUT', 'STALE', 'ACTION_REQUIRED', 'ERROR',
                       'STARTUP_FAILURE'}
TERMINAL_DISPATCH = {'succeeded', 'failed', 'rejected', 'cancelled', 'superseded', 'no-change'}
OPEN_DISPATCH = {'reserved', 'uncertain', 'pending', 'armed'}
# A reservation is written before any host side effect, so an in-flight launch and a
# live writer are indistinguishable to a competing command. Only the dispatch kind's
# own terminal statuses may release a writer guard; 'armed' is a merge-only state.
FIXER_RECEIPT_STATUSES = {'succeeded', 'failed', 'rejected', 'cancelled', 'superseded',
                          'no-change'}
MERGE_RECEIPT_STATUSES = {'armed', 'succeeded', 'failed', 'rejected', 'cancelled',
                          'superseded'}
RESOLUTION_RECEIPT_STATUSES = {'succeeded', 'failed', 'rejected', 'cancelled',
                               'superseded', 'no-change'}
KIND_RECEIPT_STATUSES = {
    'fixer': FIXER_RECEIPT_STATUSES,
    'merge': MERGE_RECEIPT_STATUSES,
    'resolution': RESOLUTION_RECEIPT_STATUSES,
    'update-branch': RESOLUTION_RECEIPT_STATUSES.copy(),
}
for _statuses in KIND_RECEIPT_STATUSES.values():
    _statuses.add('uncertain')
OWNER_LIVE_STATUSES = {'active', 'running', 'starting', 'queued', 'waiting', 'preparing'}
OWNER_RELEASED = {'handed-back', 'released', 'none', 'stopped', 'cancelled'}

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


def save_json_exclusive(path, value):
    """Create a new state file. An existing run is never silently replaced."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8') + b'\n'
    require(len(payload) <= MAX_STATE_BYTES, 'state exceeds the size limit')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ContinuousError(
            f'{path} already exists; resume that run or choose a new state path') from exc
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def state_path(path):
    return Path(path).expanduser().resolve()


@contextlib.contextmanager
def locked_state(path, *, create=False):
    """Exclusive transaction over the complete read-modify-write of one run state.

    Atomic replacement protects a reader from a half-written file. It does not stop
    two coordinators from reading the same roster and overwriting each other, so the
    lock covers the whole command. Commands save explicitly; the lock is released
    however the command exits.
    """
    require(fcntl is not None, 'continuous state locking requires a POSIX host with fcntl')
    path = state_path(path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.exists():
        raise ContinuousError(f'no continuous state at {path}; run start first')
    lock_path = path.with_name(path.name + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if create:
            yield None
        else:
            yield read_state(path)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def package_digest(package_dir):
    """Stable digest of the installed package contents.

    Resume compares this with the snapshot recorded at start, so a swapped running
    package is detected even when the caller passes no --package-version.
    """
    package = Path(package_dir)
    rows = []
    for path in sorted(package.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        rel = str(path.relative_to(package))
        if any(part.startswith('.') for part in Path(rel).parts):
            continue
        if rel.split(os.sep)[0] in ('__pycache__', 'dist', 'site') or rel.endswith('.pyc'):
            continue
        if rel.endswith('.lock') or rel.endswith('.json.tmp'):
            continue
        rows.append([rel, sha256_file(path)])
    return hashlib.sha256(canonical(rows)).hexdigest()


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
    manifest_path = package / 'install-manifest.json'
    if manifest_path.exists():
        job_contracts(package)
        from shared.worker_registry import package_digest as manifest_digest, verify_package_files
        try:
            manifest = load_json(manifest_path)
            fingerprint = manifest_digest(manifest)
            require(manifest.get('package_digest') == fingerprint,
                    'installed package manifest digest differs from its file list')
            verify_package_files(package, manifest)
        except (ValueError, OSError) as exc:
            raise ContinuousError(f'installed package integrity failure: {exc}') from exc
        version = manifest['version']
    else:
        fingerprint, version = package_digest(package), meta.get('version')
    return {'plugin': meta.get('name'), 'version': meta.get('version'),
            'installed_version': version,
            'policy_version': policy_identity(meta), 'package_dir': str(package),
            'digest': fingerprint}


def job_contracts(package=None):
    """Load the shipped job APIs, from the package or this source checkout."""
    package = Path(package or Path(__file__).resolve().parents[1])
    for root in (package, *package.parents):
        if (root / 'shared' / 'job_coordinator.py').is_file():
            sys.path.insert(0, str(root))
            return
    raise ContinuousError('supported job APIs are unavailable in this package')


def verified_job(path):
    job_contracts()
    from shared.job_coordinator import pinned_store, verify_all_pins
    directory = Path(path).expanduser().resolve()
    if directory.name == 'job.json':
        directory = directory.parent
    try:
        store = pinned_store(directory.parent, directory.name)
        return store, verify_all_pins(store)
    except (ValueError, OSError) as exc:
        raise ContinuousError(f'job evidence is invalid: {exc}') from exc


def accepted_fixer_result(args, state, row):
    """Bind the retained transport to an ingested execution and terminal owned handle."""
    require(bool(args.result), 'a terminal fixer receipt needs --result <ingested result>')
    transport = Path(args.result).expanduser().resolve()
    job_path = getattr(args, 'job', None)
    if not job_path and transport.parent.name == 'results':
        job_path = transport.parent.parent
    require(bool(job_path), 'successful fixer evidence needs the accepted job --job <job-dir>')
    store, job = verified_job(job_path)
    require(not state.get('job_id') or state['job_id'] == job['job_id'],
            'result belongs to a different pinned job')
    require(transport == store.path / 'results' / (args.request_id + '.json'),
            'result is not the job-retained transport for this request')
    for task in job['tasks']:
        execution = next((item for item in task.get('execution_history', [])
                          if item.get('request_id') == args.request_id
                          and item.get('accepted_execution') is True
                          and (not item.get('malformed') or args.status == 'failed')), None)
        if not execution:
            continue
        handle = next((item for item in task.get('handles', []) + task.get('followups', [])
                       if item.get('request_id') == args.request_id
                       and item.get('task_id', item.get('host_task_id')) == row.get('host_task_id')
                       and any(event.get('request_id') == args.request_id
                               and event.get('host_task_id') == row.get('host_task_id')
                               and event.get('completion_id') == execution.get('completion_id')
                               for event in job.get('notifications', []))
                       and item.get('status') in ('completed', 'failed', 'cancelled', 'interrupted')
                       and item.get('work_state') == 'result_available'
                       and item.get('has_pending_child_runs') is False), None)
        require(handle is not None, 'result has no matching terminal owned host handle')
        require(args.host_task_id == row.get('host_task_id'),
                'fixer receipt must name its matching host handle')
        reference = execution.get('transport_ref') or {}
        require(reference.get('transport_path') == str(transport)
                and reference.get('transport_sha256') == sha256_file(transport),
                'accepted result transport bytes or reference changed')
        result = execution.get('result') or {}
        require(execution.get('malformed') or (
                result.get('request_id') == args.request_id and result.get('job_id') == job['job_id']),
                'accepted result correlation differs from this request')
        if args.status in ('succeeded', 'no-change'):
            require(result.get('status') == 'ready-for-acceptance',
                    'successful fixer receipt requires an accepted ready result')
        return sha256_file(transport)
    raise ContinuousError('no matching accepted job-result execution was ingested')


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
    """Age of the oldest trustworthy clock for a pending job, or None.

    A queued Actions job has no runner, so ``started_at`` is null and the creation
    clock from the Actions job API is the only honest start. When no clock is known
    the caller reports unknown age instead of treating the observation time as zero.
    """
    for field in ('created_at', 'started_at'):
        value = check.get(field)
        if value:
            created = parse_time(value, field)
            return max(0, int((now - created).total_seconds()))
    return None


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
    """What actually changed for this PR. A repeated identical read is not progress.

    Both collections are sorted by their own identity, so the same queued checks in a
    different API order do not reset the progress clock.
    """
    return digest({
        'head': raw.get('head_sha'),
        'checks': sorted((c['name'], c['status'], c['conclusion'],
                          c.get('created_at'), c.get('started_at'), c.get('head_sha'))
                         for c in checks),
        'threads': normalise_threads(raw),
        'review': raw.get('review_decision'),
        'review_threads_complete': raw.get('review_threads_complete'),
        'changes_requested': sorted(raw.get('changes_requested_by') or []),
        'merge_state': raw.get('merge_state_status') or raw.get('mergeable'),
        'state': str(raw.get('state') or 'OPEN').upper(),
        'queue': sorted((q['name'], q['status'], q.get('created_at'), q.get('started_at'))
                        for q in queue),
    })


def owner_state(raw):
    """Record ownership only when the snapshot actually carries ownership evidence.

    A missing owner key is unavailable evidence, not a release and not a new 'none'
    owner. A missing continuation field is unavailable evidence too: only an explicit
    continuation value releases or preserves a live maintainer. Keeping the previous
    confirmed owner is the conservative choice; only an explicit handoff releases it.
    """
    owner = raw.get('owner')
    if not isinstance(owner, dict) or not any(owner.get(k) for k in
                                               ('thread_id', 'status', 'continuation')):
        return None
    status = str(owner.get('status') or 'none').lower()
    return {
        'thread_id': owner.get('thread_id'),
        'status': status,
        'continuation': owner.get('continuation'),
        'continuation_known': isinstance(owner.get('continuation'), str)
                              and bool(owner['continuation']),
        'fixer_in_flight': bool(owner.get('fixer_in_flight', False)),
        'host_task_id': (owner.get('host_task_id') or owner.get('task_id')
                         or owner.get('fixer_request_id')),
    }


def merge_owner(previous, observed):
    """Fold one ownership snapshot into the stored owner without inventing a release.

    A partial update that omits the continuation field for the same thread keeps the
    last confirmed continuation. A different thread is new evidence and replaces it.
    """
    previous = previous or {}
    owner = dict(observed)
    if not owner.get('thread_id'):
        owner['thread_id'] = previous.get('thread_id')
    same_thread = owner.get('thread_id') == previous.get('thread_id')
    if same_thread and not owner.get('continuation_known'):
        if owner.get('status') in OWNER_LIVE_STATUSES \
                and previous.get('continuation') in OWNER_RELEASED:
            owner['continuation'] = None
            owner['continuation_known'] = False
        else:
            owner['continuation'] = previous.get('continuation')
            owner['continuation_known'] = previous.get('continuation_known', False)
    if same_thread and owner.get('status') == 'none' and previous.get('status') not in (
            None, 'none'):
        owner['status'] = previous.get('status')
    if same_thread and not owner.get('host_task_id'):
        owner['host_task_id'] = previous.get('host_task_id')
    return owner


def owned_elsewhere(pr, self_thread):
    """Keep another maintainer's ownership until an explicit handoff or release.

    Missing or unfamiliar continuation evidence cannot establish release, even when
    the host reports a parked or terminal turn. Historical links can be released by
    a fresh, explicit handoff observation.
    """
    owner = pr.get('owner') or {}
    thread = owner.get('thread_id')
    if not thread or thread == self_thread:
        return False
    return owner.get('continuation') not in OWNER_RELEASED


def required_contexts(observation):
    """Complete configured required-check names, or None when unknown.

    Only a snapshot that can enumerate the configured set (for example a full read
    with branch-protection evidence) may claim completeness. A reader that lists
    ``isRequired`` on the contexts it saw knows only an observed subset.
    """
    value = observation.get('required_contexts')
    known = observation.get('required_contexts_known')
    if known is False or value is None:
        return None
    if not isinstance(value, list):
        raise ContinuousError('required_contexts must be a list or null')
    return [str(name) for name in value]


def observed_required_contexts(observation):
    """Required names among the observed contexts; an explicitly partial subset."""
    value = observation.get('required_contexts_observed')
    if value is None:
        if observation.get('required_contexts_known') is not False:
            return None
        value = observation.get('required_contexts')
    if not isinstance(value, list):
        return None
    return [str(name) for name in value]


def stale_evidence(observation, checks):
    """Check names whose evidence belongs to a head other than the current one.

    Provenance is checked for finished and pending checks alike: a SUCCESS from an
    older head must never authorise a landing.
    """
    head = observation.get('head_sha')
    fallback = observation.get('checks_head_sha')
    stale = set()
    if fallback and head and fallback != head:
        stale.add('(checks_header)')
    for check in checks:
        evidence = check.get('head_sha') or None
        if evidence and head and evidence != head:
            stale.add(check['name'])
    return sorted(stale)


def blocking_failures(observation, failing):
    """Failing checks that actually block landing, or every failing check when unknown.

    GitHub's ``StatusCheckRollup.state`` is a ``StatusState`` and has no ``UNSTABLE``
    value; optional-failure evidence comes from ``mergeStateStatus`` instead. A
    single-PR reader can bind ``isRequired`` on the contexts it saw, which safely
    identifies present required checks, while a complete configured set is unknown.
    """
    required = required_contexts(observation)
    if required is not None:
        return [name for name in failing if name in required]
    observed = observed_required_contexts(observation)
    if observed is not None:
        optional = observation.get('optional_contexts_observed')
        if optional is not None:
            return [name for name in failing if name not in optional]
        return [name for name in failing if name in observed]
    merge_state = str(observation.get('merge_state_status') or '').upper()
    if merge_state == 'UNSTABLE':
        return []
    return list(failing)


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
            'age_known': age is not None,
            'created_at': check.get('created_at'),
            'started_at': check.get('started_at'),
            'head_sha': check.get('head_sha'),
            'over_threshold': bool(age is not None and age >= threshold),
        })
    known = [row for row in rows if row['age_known']]
    oldest = max(known, key=lambda row: row['age_seconds'], default=None)
    return {
        'pending': rows,
        'oldest': oldest,
        'over_threshold': bool(oldest and oldest['over_threshold']),
        'unknown_clock': [row['name'] for row in rows if not row['age_known']],
        'failing': [c['name'] for c in checks if c['conclusion'] in FAILING_CONCLUSIONS],
    }


def deadline(now, seconds):
    return now_iso(now + timedelta(seconds=seconds))


def stall_diagnosis(pr, policy, now, clock_detail, clock_gaps):
    last = parse_time(pr.get('last_meaningful_progress_at') or pr['admitted_at'], 'last progress')
    elapsed = int((now - last).total_seconds())
    if elapsed < policy['stall_threshold_seconds']:
        return None
    detail = f'no meaningful progress for {elapsed}s'
    if clock_detail:
        detail += '; queue age is unknown for ' + clock_detail
    return ({'pr': pr['url'], 'kind': 'diagnose-stall', 'reason': detail,
             'next_check_at': deadline(now, policy['cadence_seconds'])},
            {'kind': 'stalled-work', 'detail': detail, 'queue_clock_gaps': clock_gaps})


def dispatch_status(row):
    return str(row.get('status') or 'pending')


def update_helper_receipt(pr, row, result):
    """Classify the synchronous update-only helper, bound to its target and head.

    A nonzero exit alone never proves rejection after a PUT may have been sent.
    Unknown output, including a lost process response, therefore keeps the lock.
    """
    result = result if isinstance(result, dict) else {}
    if result.get('request_id') != row.get('request_id'):
        return 'uncertain', 'unknown'
    target = re.escape(f"{pr['repo']}#{pr['number']}")
    head = re.escape(str(row.get('head') or ''))
    output = str(result.get('stdout') or '').strip()
    updated = re.fullmatch(
        rf'UPDATED {target} previous_head={head} head=([0-9a-f]{{40}}) refresh_gates=required',
        output)
    if result.get('returncode') == 0 and updated and updated[1] != row.get('head'):
        return 'succeeded', 'updated'
    if result.get('returncode') == 0 and re.fullmatch(
            rf'MERGED {target} via preexisting', output):
        return 'no-change', 'merged'
    no_put = re.fullmatch(
        rf'BLOCKED {target} reason=(closed|not_behind|conflict|expected_head_mismatch) '
        r'blockers=\S+ (?:changes_requested_by=\S+ )?detail=.+ '
        r'automerge=(?:unavailable|preexisting)', output)
    if result.get('returncode') == 4 and no_put:
        outcome = no_put[1]
        if outcome == 'expected_head_mismatch' and not re.search(
                rf' is not the expected head {head}; ', output):
            return 'uncertain', 'unknown'
        # A later no-PUT refusal cannot retract an earlier unconfirmed PUT. A
        # terminal PR read can settle a completed synchronous helper separately.
        if outcome != 'closed' and row.get('update_outcome') in ('accepted', 'unknown'):
            return 'uncertain', row['update_outcome']
        return 'no-change', outcome
    blocked = re.fullmatch(
        rf'BLOCKED {target} reason=(update_pending|update_rejected) blockers=\S+ '
        rf'(?:changes_requested_by=\S+ )?detail=update_head={head} '
        r'update_outcome=(accepted|unknown|rejected) [^\n]+ automerge=(?:unavailable|preexisting)', output)
    if result.get('returncode') == 4 and blocked:
        reason, outcome = blocked.groups()
        if reason == 'update_rejected' and outcome == 'rejected':
            return 'rejected', outcome
        if reason == 'update_pending' and outcome in ('accepted', 'unknown'):
            return 'uncertain', outcome
    return 'uncertain', 'unknown'


def record_terminal_pr(pr, resolution, head, now):
    """Close the PR lifecycle without claiming that a live host writer stopped."""
    pr.update(state=resolution, resolved_head=head, excluded=None)
    pr.setdefault('resolved_at', now_iso(now))
    pr['observation']['state'] = resolution.upper()
    pr.pop('branch_update', None)
    for row in pr.get('dispatches', []):
        if (row['kind'] == 'update-branch' and dispatch_status(row) in OPEN_DISPATCH
                and not row.get('host_task_id') and row.get('result_digest')
                and row.get('update_outcome')):
            # Only a completed synchronous helper can be settled by a PR read.
            # An unknown launch or attached task still needs its host receipt.
            row.update(status='superseded', completed_at=now_iso(now),
                       observed_state=resolution, observed_head=head)


def live_merge_dispatch(pr):
    return next((row for row in pr.get('dispatches', [])
                 if row.get('kind') == 'merge' and dispatch_status(row) in OPEN_DISPATCH), None)


def live_dispatch(pr, kind):
    return next((row for row in pr.get('dispatches', [])
                 if row.get('kind') == kind and dispatch_status(row) in OPEN_DISPATCH), None)


def pending_write(pr, state, now):
    """Keep coordinator writes visible until their matching terminal receipts."""
    dispatches = [dict(row) for row in pr.get('dispatches', [])
                  if row.get('kind') in ('resolution', 'update-branch')
                  and dispatch_status(row) in OPEN_DISPATCH]
    for kind in ('resolution', 'update-branch'):
        row = live_dispatch(pr, kind)
        if row:
            status = dispatch_status(row)
            identity = {key: row.get(key) for key in ('request_id', 'host_task_id', 'head')}
            return ({'pr': pr['url'], 'kind': f'{kind}-pending', **identity,
                     'dispatch_status': status, 'dispatches': dispatches,
                     'reason': f"{kind} {row['request_id']} is {status}; reconcile its host receipt",
                     'next_check_at': deadline(now, state['policy']['cadence_seconds'])},
                    {'kind': f'{kind}-in-flight', **identity, 'dispatch_status': status})
    return None


def merge_attempts(pr, head):
    return [row for row in pr.get('dispatches', [])
            if row.get('kind') == 'merge' and row.get('head') == head]


def settlement_attempts(pr, prefix):
    return [row for row in pr.get('dispatches', []) if row.get('request_id', '').startswith(prefix)]


def mark_stale_merges(pr, head):
    """Record head drift without releasing a possibly live landing operation.

    A head change proves nothing about host termination. Reservations, uncertain
    launches, pending handles and armed requests all keep their exclusion until a
    terminal receipt settles the original attempt.
    """
    for row in pr.get('dispatches', []):
        if row.get('kind') == 'merge' and row.get('head') != head \
                and dispatch_status(row) in OPEN_DISPATCH:
            row['stale_at_head'] = head


def reconcile_pr(pr, state, now, discovery):
    """Return (action, queue, blocked, progress) for one admitted open PR.

    The decision order keeps independently repairable work ahead of a queued-job
    diagnosis: a failed required check, a conflict or an unresolved thread is acted on
    even when some other job has been queued past the threshold.
    """
    threshold = state['policy']['queue_threshold_seconds']
    stall = state['policy']['stall_threshold_seconds']
    cadence = state['policy']['cadence_seconds']
    observation = pr['observation']
    checks = observation.get('checks', [])
    queue = queue_summary(checks, now, threshold)
    queue['queue_clock_gaps'] = observation.get('queue_clock_gaps', [])
    unknown_clock_detail = ', '.join(queue['unknown_clock'])
    if queue['queue_clock_gaps']:
        unknown_clock_detail += '; clock gaps: ' + '; '.join(
            f"{gap['name']}: {gap['reason']}" for gap in queue['queue_clock_gaps'])
    raw_state = str(observation.get('state') or 'OPEN').upper()
    head = observation.get('head_sha')
    required = required_contexts(observation)
    failing = blocking_failures(observation, queue['failing'])
    threads = observation.get('unresolved_threads', 0)
    merge_state = str(observation.get('merge_state_status') or 'UNKNOWN').upper()
    conflict = (str(observation.get('mergeable') or '').upper() == 'CONFLICTING'
                or merge_state == 'DIRTY')
    review = str(observation.get('review_decision') or '').upper()
    changes = [name for name in observation.get('changes_requested_by') or [] if name]
    progress = progress_signature(observation, checks, queue['pending'])
    stalled = stall_diagnosis(pr, state['policy'], now,
                             unknown_clock_detail if queue['unknown_clock'] else '',
                             queue['queue_clock_gaps'])
    threads_complete = observation.get('review_threads_complete') is True

    if raw_state in ('MERGED', 'CLOSED'):
        record_terminal_pr(pr, raw_state.lower(), head, now)
    pending = pending_write(pr, state, now)
    if pending:
        return pending[0], queue, pending[1], progress

    if raw_state == 'MERGED':
        pr['state'] = 'merged'
        return ({'pr': pr['url'], 'kind': 'merged', 'reason': 'host observed a merge'},
                queue, None, progress)
    if raw_state == 'CLOSED':
        pr['state'] = 'closed'
        return ({'pr': pr['url'], 'kind': 'closed', 'reason': 'host observed a close without merge'},
                queue, None, progress)

    if pr.get('discovery_gap'):
        gap = discovery.get('gaps') or [{'kind': 'omission',
                                         'detail': pr['discovery_gap']}]
        return ({'pr': pr['url'], 'kind': 'reconcile-discovery',
                 'reason': 'the current discovery snapshot omitted this known open PR',
                 'next_check_at': deadline(now, cadence)},
                queue, {'kind': 'discovery-omission', 'detail': gap}, progress)

    if owned_elsewhere(pr, state.get('thread_id')):
        return ({'pr': pr['url'], 'kind': 'owned-elsewhere',
                 'reason': 'active ownership elsewhere; this run performs no writes',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'owned-elsewhere', 'owner': (pr.get('owner') or {}).get('thread_id')},
                progress)

    stale = stale_evidence(observation, checks)
    if stale:
        detail = ', '.join(stale)
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': f'check evidence belongs to a previous head: {detail}',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'stale-head-checks', 'detail': detail,
                 'current_head': head}, progress)

    fixer = pr.get('fixer') or {}
    if fixer.get('in_flight'):
        started = fixer.get('started_at') or pr.get('last_meaningful_progress_at')
        age = int((now - parse_time(started, 'fixer.started_at')).total_seconds()) if started else 0
        return ({'pr': pr['url'], 'kind': 'wait-fixer',
                 'reason': f"fixer {fixer.get('request_id')} is in flight",
                 'request_id': fixer.get('request_id'),
                 'next_check_at': deadline(now, min(cadence, max(60, stall - age)))},
                queue, {'kind': 'fixer-in-flight', 'detail': fixer.get('request_id')}, progress)

    merge = live_merge_dispatch(pr)
    if merge:
        return ({'pr': pr['url'], 'kind': 'merge-pending',
                 'reason': f"merge {merge['request_id']} is {dispatch_status(merge)}; "
                           'reconcile its host receipt before another write',
                 'request_id': merge['request_id'], 'head': merge.get('head'),
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'merge-in-flight', 'host_task_id': merge.get('host_task_id'),
                 'head': merge.get('head'), 'current_head': head}, progress)

    human = observation.get('human_blocker') or {}
    if human.get('kind') in HUMAN_BLOCKERS:
        return ({'pr': pr['url'], 'kind': 'needs-human',
                 'reason': human.get('detail') or human['kind'],
                 'next_check_at': deadline(now, cadence)},
                queue, {'kind': human['kind'], 'detail': human.get('detail')}, progress)
    if human and human.get('kind'):
        return ({'pr': pr['url'], 'kind': 'blocked',
                 'reason': human.get('detail') or human['kind'],
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': human['kind'], 'detail': human.get('detail')}, progress)

    # Independently repairable work comes before queue diagnosis, so a queued job
    # never starves a failed check, an unresolved thread or a conflict on this PR.
    if conflict or failing or threads > 0:
        fingerprint = digest({
            'head': head, 'failing': sorted(failing), 'threads': threads,
            'conflict': conflict,
            'review': review, 'changes': sorted(changes),
        })[:12]
        prefix = f"{pr['number']}-maintain-{fingerprint}"
        attempts = settlement_attempts(pr, prefix)
        live = next((row for row in attempts if dispatch_status(row) in OPEN_DISPATCH), None)
        if live:
            return ({'pr': pr['url'], 'kind': 'wait-fixer',
                     'reason': f"repair already dispatched as {live['request_id']}",
                     'request_id': live['request_id'],
                     'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'fixer-in-flight', 'detail': live['request_id']}, progress)
        if len(attempts) >= MAX_REPAIR_ATTEMPTS:
            detail = f'repair attempts exhausted at this head ({len(attempts)})'
            return ({'pr': pr['url'], 'kind': 'blocked',
                     'reason': detail, 'next_check_at': deadline(now, cadence)},
                    queue, {'kind': 'repair-exhausted', 'detail': detail,
                            'attempts': len(attempts)}, progress)
        reason = ('merge conflict' if conflict else
                  ('failing required checks ' + ', '.join(sorted(failing)) if failing else
                   f'{threads} unresolved thread(s)'))
        request_id = f'{prefix}-a{len(attempts) + 1}'
        return ({'pr': pr['url'], 'kind': 'dispatch-fixer', 'request_id': request_id,
                 'head': head, 'reason': reason,
                 'attempt': len(attempts) + 1,
                 'next_check_at': deadline(now, cadence)},
                queue, None, progress)

    if review == 'CHANGES_REQUESTED' or changes:
        prefix = f"{pr['number']}-review-{(head or 'unknown')[:12]}"
        attempts = settlement_attempts(pr, prefix)
        live = next((row for row in attempts if dispatch_status(row) in OPEN_DISPATCH), None)
        if live:
            return ({'pr': pr['url'], 'kind': 'wait-fixer',
                     'reason': f"review triage dispatched as {live['request_id']}",
                     'request_id': live['request_id'],
                     'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'review-triage', 'detail': live['request_id']}, progress)
        resolved = next((row for row in attempts
                         if dispatch_status(row) in ('succeeded', 'no-change')), None)
        if resolved or len(attempts) >= MAX_REVIEW_ATTEMPTS:
            detail = ('review triage completed; waiting for re-review' if resolved else
                      'review triage attempts exhausted; waiting for re-review')
            return ({'pr': pr['url'], 'kind': 'wait-review',
                     'reason': detail, 'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'requested-changes', 'detail': changes,
                     'triage': dispatch_status(resolved) if resolved else 'exhausted'}, progress)
        request_id = f'{prefix}-a{len(attempts) + 1}'
        return ({'pr': pr['url'], 'kind': 'dispatch-fixer', 'request_id': request_id,
                 'head': head,
                 'reason': 'inspect and repair the requested changes before re-review',
                 'attempt': len(attempts) + 1,
                 'review_triage': True,
                 'next_check_at': deadline(now, cadence)}, queue, None, progress)

    if queue['over_threshold']:
        oldest = queue['oldest']
        detail = (f"{oldest['name']} has been {oldest['diagnosis']} for "
                  f"{oldest['age_seconds']}s (threshold {threshold}s)")
        return ({'pr': pr['url'], 'kind': 'diagnose-queue',
                 'reason': detail, 'next_check_at': deadline(now, cadence)},
                queue, {'kind': oldest['diagnosis'], 'detail': detail,
                        'check': oldest['name'], 'age_seconds': oldest['age_seconds']}, progress)

    if queue['pending'] and queue['unknown_clock']:
        if stalled:
            return stalled[0], queue, stalled[1], progress
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': f'queue age is unknown for: {unknown_clock_detail}',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'queue-age-unknown', 'detail': unknown_clock_detail,
                 'queue_clock_gaps': queue['queue_clock_gaps']}, progress)

    if observation.get('checks_complete') is False:
        source = observation.get('checks_source')
        detail = ('the check-context read is incomplete; fetch the remaining pages'
                  if source == 'full' else
                  'the reader snapshot is missing check contexts beyond its context page; '
                  're-read this PR with a paginated or targeted context read')
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': detail, 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'incomplete-checks', 'detail': detail,
                 'continuation': f"re-read {pr['repo']}#{pr['number']} contexts"}, progress)

    if observation.get('checks_source') == 'full' and required is not None:
        observed = {c['name'] for c in checks}
        missing = sorted(set(required) - observed)
        if missing:
            return ({'pr': pr['url'], 'kind': 'wait-checks',
                     'reason': 'required contexts missing from this head: ' + ', '.join(missing),
                     'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'missing-contexts', 'detail': missing}, progress)

    if not threads_complete:
        detail = ('the review-thread read is incomplete'
                  if observation.get('review_threads_complete') is False else
                  'no complete review-thread read was supplied')
        return ({'pr': pr['url'], 'kind': 'wait-threads',
                 'reason': detail + '; read the remaining conversations before landing',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'incomplete-threads', 'detail': detail}, progress)

    checks_state = str(observation.get('checks_state') or '').upper()
    if review == 'REVIEW_REQUIRED':
        return ({'pr': pr['url'], 'kind': 'wait-review',
                 'reason': 'GitHub requires an approving review',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'review-required', 'detail': review}, progress)
    if merge_state == 'HAS_HOOKS':
        return ({'pr': pr['url'], 'kind': 'diagnose-gate',
                 'reason': 'GitHub reports HAS_HOOKS; reconcile hooks before landing',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'has-hooks', 'detail': merge_state}, progress)
    if ((checks_state == 'SUCCESS' and merge_state in ('BLOCKED', 'UNKNOWN'))
        or (queue['failing'] and not failing and merge_state in ('BLOCKED', 'UNKNOWN'))) \
            and not failing and not queue['pending']:
        return ({'pr': pr['url'], 'kind': 'diagnose-gate',
                 'reason': f'checks report {checks_state} but the aggregate gate is {merge_state}',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'stuck-aggregate-gate', 'detail': merge_state}, progress)

    if not re.fullmatch(r'[0-9a-f]{40}', str(head or '')):
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': 'no exact current head was observed; no merge is possible',
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'missing-head', 'detail': 'head_sha is absent or not a full commit'}, progress)

    checks_ok = checks_state == 'SUCCESS'
    if merge_state == 'UNSTABLE':
        # Match merge-pr.sh: UNSTABLE needs at least one observed required context,
        # a complete context page and every required context green. Search-reader
        # rows without isRequired evidence need a targeted read before landing.
        required_seen = observed_required_contexts(observation)
        if required_seen is None and observation.get('checks_source') == 'full':
            required_seen = required
        checks_ok = (bool(required_seen) and observation.get('checks_complete') is True
                     and (required is None or set(required).issubset(required_seen)))
        if checks_ok and observation.get('checks_source') == 'full':
            by_name = {c['name']: c for c in checks}
            checks_ok = all(name in by_name and by_name[name]['conclusion'] in PASSING_CONCLUSIONS
                            for name in required_seen)
        elif checks_ok:
            checks_ok = not any(c['name'] in required_seen and c['conclusion'] not in PASSING_CONCLUSIONS
                                for c in checks)
        if not checks_ok:
            return ({'pr': pr['url'], 'kind': 'wait-checks',
                     'reason': 'UNSTABLE requires a targeted read verifying every required context green',
                     'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'unverified-required-checks', 'detail': merge_state}, progress)
    mergeable = str(observation.get('mergeable') or '').upper() == 'MERGEABLE'
    update = pr.get('branch_update')
    if update and (update.get('refresh_required')
                   or (head == update['head'] and update.get('outcome', 'updated') == 'updated')):
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': 'branch update completed; refresh the new head and its gates before landing',
                 'request_id': update['request_id'], 'head': head,
                 'next_check_at': deadline(now, cadence)}, queue,
                {'kind': 'branch-update-refresh', 'head': head}, progress)
    if mergeable and merge_state == 'BEHIND' and checks_ok \
            and not queue['pending'] and not failing and threads == 0:
        attempts = [row for row in pr['dispatches']
                    if row['kind'] == 'update-branch' and row.get('head') == head]
        if len(attempts) >= MAX_MERGE_ATTEMPTS:
            detail = 'branch update attempts exhausted at this head'
            return ({'pr': pr['url'], 'kind': 'blocked', 'reason': detail,
                     'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'branch-update-rejected', 'detail': detail}, progress)
        return ({'pr': pr['url'], 'kind': 'update-branch', 'head': head,
                 'request_id': f"{pr['number']}-update-{head[:12]}-a{len(attempts) + 1}",
                 'reason': 'branch is behind its base; update before refreshing landing gates',
                 'next_check_at': deadline(now, cadence)}, queue, None, progress)
    if mergeable and merge_state in ('CLEAN', 'UNSTABLE') \
            and not queue['pending'] and not failing and threads == 0 and checks_ok:
        head_attempts = merge_attempts(pr, head)
        rejected = [row for row in head_attempts
                    if dispatch_status(row) in ('rejected', 'failed', 'cancelled')]
        if len(rejected) >= MAX_MERGE_ATTEMPTS:
            detail = f'merge rejected {len(rejected)} times at this head'
            return ({'pr': pr['url'], 'kind': 'blocked', 'reason': detail,
                     'next_check_at': deadline(now, cadence)}, queue,
                    {'kind': 'merge-rejected', 'detail': detail}, progress)
        request_id = f"{pr['number']}-merge-{head[:12]}-a{len(head_attempts) + 1}"
        return ({'pr': pr['url'], 'kind': 'merge', 'request_id': request_id, 'head': head,
                 'reason': 'GitHub reports every gate green at this head',
                 'next_check_at': deadline(now, cadence)}, queue, None, progress)

    if stalled:
        return stalled[0], queue, stalled[1], progress

    if queue['pending']:
        oldest = queue['oldest']
        remaining = max(0, threshold - oldest['age_seconds'])
        return ({'pr': pr['url'], 'kind': 'wait-checks',
                 'reason': f"{oldest['name']} is {oldest['diagnosis']} ({oldest['age_seconds']}s)",
                 'next_check_at': deadline(now, min(cadence, max(30, remaining)))},
                queue, {'kind': oldest['diagnosis'], 'detail': oldest['name']}, progress)

    return ({'pr': pr['url'], 'kind': 'wait-checks' if not checks_ok else 'diagnose-gate',
             'reason': f'landing blocked: mergeable={observation.get("mergeable")} '
                       f'merge_state={merge_state} rollup={checks_state or "NONE"}',
             'next_check_at': deadline(now, cadence)}, queue,
            {'kind': 'checks-not-successful' if not checks_ok else 'not-clean',
             'detail': checks_state if not checks_ok else merge_state}, progress)


def scheduler_report(state, now):
    """Separate authorization, recorded schedule existence and observed delivery.

    A stored receipt stops being a confirmed upcoming wake the moment the run is no
    longer in scheduled mode. It is preserved as history (``historical_next_run_at``)
    instead of being republished as ``next_wake_at``.
    """
    scheduler = state['scheduler']
    mode = scheduler.get('mode')
    schedule_id = scheduler.get('schedule_id')
    stored_next = scheduler.get('next_run_at')
    stopped = scheduler.get('stopped') or {}
    report = {
        'mode': mode,
        'schedule_id': schedule_id,
        'next_run_at': stored_next,
        'historical_next_run_at': None,
        'stop': scheduler.get('stop'),
        'gap': None,
        'coverage': None,
        'overdue': False,
        'awaiting_receipt': bool(scheduler.get('awaiting_receipt')),
        'last_wake_at': scheduler.get('last_wake_at'),
        'last_wake_kind': scheduler.get('last_wake_kind'),
    }
    if mode != 'scheduled':
        report.update({
            'coverage': ('stop-unverified' if schedule_id and not stopped.get('verified')
                         else 'event-only'),
            'next_run_at': None,
            'historical_next_run_at': stored_next,
            'gap': scheduler.get('gap') or (
                'event-only: no idle discovery, queue-age diagnosis or stalled-work wake'),
        })
        return report
    report['overdue'] = bool(stored_next and parse_time(stored_next, 'next_run_at') < now)
    if stopped and stopped.get('verified') is not True:
        report['coverage'] = 'stop-unverified'
        report['gap'] = scheduler.get('gap') or (
            'stop requested but not verified; verify the schedule is absent before re-arming')
    elif stopped.get('verified') is True and not schedule_id:
        report['coverage'] = 'stopped'
        report['gap'] = ('host schedule stopped and verified; no wake will arrive until re-armed')
        report['next_run_at'] = None
        report['historical_next_run_at'] = stored_next
        report['overdue'] = False
    elif schedule_id:
        report['coverage'] = 'scheduled'
        report['gap'] = None
    else:
        report['coverage'] = 'scheduled-unverified'
        report['gap'] = scheduler.get('gap') or (
            'scheduler authorized but no host schedule receipt is recorded')
    return report


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
        report = scheduler_report(state, now)
        return {'status': 'duplicate', 'wake': {'id': wake_id, 'kind': wake_kind, 'duplicate': True},
                'actions': [], 'admitted': [], 'excluded': [], 'human_questions': [],
                'coverage': report['coverage'], 'scheduler': report,
                'next_wake_at': report['next_run_at'],
                'message': 'this wake and observation were already reconciled; no new work was created'}

    admitted, actions, questions, queue_rows, excluded_rows = [], [], [], [], []
    seen_urls = set()
    progressed = False
    for row in raw_rows:
        if not scope_matches(state['scope'], {'repo': row['repo'], 'number': row['number']}):
            continue
        seen_urls.add(row['url'])
        is_excluded = excluded(state['scope'], {'url': row['url'], 'repo': row['repo'],
                                                'number': row['number'],
                                                'draft': row['observation']['draft'],
                                                'fork': row['observation']['fork']})
        pr = state['prs'].get(row['url'])
        is_new = pr is None
        if is_new:
            if is_excluded:
                continue
            pr = {
                'url': row['url'], 'repo': row['repo'], 'number': row['number'],
                'title': row['title'], 'state': 'open',
                'admitted_at': now_iso(now), 'first_seen_at': now_iso(now),
                'last_seen_at': now_iso(now), 'last_meaningful_progress_at': now_iso(now),
                'observation': row['observation'], 'owner': row['owner'],
                'dispatches': [], 'fixer': {'in_flight': False, 'request_id': None,
                                            'started_at': None},
                'discovery_gap': None, 'excluded': None, 'reopens': [],
            }
            state['prs'][row['url']] = pr
            admitted.append({'url': row['url'], 'repo': row['repo'], 'number': row['number'],
                             'reason': 'matched the authorised continuing scope'})
            progressed = True
        else:
            pr['last_seen_at'] = now_iso(now)
            pr['title'] = row['title'] or pr.get('title')
            if row['owner'] is not None:
                pr['owner'] = merge_owner(pr.get('owner'), row['owner'])
            pr['observation'] = row['observation']
            pr['discovery_gap'] = None
            if is_excluded:
                pr['state'] = 'excluded'
                pr['excluded'] = 'draft, fork or explicit exclusion no longer matches the scope'
                # An excluded row keeps its history but may not publish a stale action.
                pr['next_action'] = None
                pr['blocked'] = None
                pr['queue'] = None
                pr['excluded_at'] = now_iso(now)
                excluded_rows.append({'pr': row['url'], 'reason': pr['excluded']})
                continue
            if pr['state'] == 'excluded':
                pr['state'] = 'open'
                pr['excluded'] = None
                pr.pop('excluded_at', None)
            if pr['state'] == 'closed' and row['observation']['state'] == 'OPEN':
                pr['state'] = 'open'
                pr['reopened_at'] = now_iso(now)
                pr['reopens'] = (pr.get('reopens') or []) + [now_iso(now)]
                pr.pop('resolved_at', None)
                pr.pop('resolved_head', None)
            if pr['state'] == 'merged':
                continue
            if pr['state'] != 'open':
                continue
        for dispatch in pr['dispatches']:
            if (dispatch['kind'] == 'update-branch'
                    and dispatch_status(dispatch) == 'uncertain'
                    and dispatch.get('update_outcome') in ('accepted', 'unknown')
                    and not dispatch.get('host_task_id')
                    and re.fullmatch(r'[0-9a-f]{40}', str(row['observation'].get('head_sha') or ''))
                    and row['observation']['head_sha'] != dispatch['head']):
                # This is a completed synchronous helper with an unresolved PUT,
                # not a possibly live asynchronous host task. A later head read
                # settles the write; checks still need provenance at that head.
                dispatch.update(status='succeeded', completed_at=now_iso(now),
                                observed_head=row['observation']['head_sha'])
                pr['branch_update'] = {'request_id': dispatch['request_id'],
                                       'head': dispatch['head'], 'refresh_required': False}
                audit(state, now, 'update-head-observed', pr=pr['url'],
                      request_id=dispatch['request_id'], head=dispatch['observed_head'])
        update = pr.get('branch_update')
        if update and (row['observation'].get('head_sha') != update['head']
                       or update.get('outcome', 'updated') != 'updated'):
            # Only a new observation after the terminal update receipt can refresh
            # landing gates. A green snapshot read while the update ran is stale.
            update['refresh_required'] = False
        queue = queue_summary(pr['observation']['checks'], now,
                              state['policy']['queue_threshold_seconds'])
        signature = progress_signature(pr['observation'], pr['observation']['checks'],
                                       queue['pending'])
        if pr.get('progress_signature') != signature:
            pr['progress_signature'] = signature
            if not is_new:
                pr['last_meaningful_progress_at'] = now_iso(now)
                progressed = True
        # A fixer in flight is discovered from the observation (host handle state).
        # Its observed handle is retained so only a matching ingested completion can
        # clear the guard; a PR event alone must not let a merge race a running writer.
        if row['observation'].get('fixer_in_flight') and not pr['fixer'].get('in_flight'):
            owner = pr.get('owner') or {}
            pr['fixer'] = {'in_flight': True, 'request_id': None,
                           'started_at': pr['last_meaningful_progress_at'],
                           'host_task_id': owner.get('host_task_id'),
                           'owner_thread_id': owner.get('thread_id')}
        elif row['observation'].get('fixer_in_flight') and pr['fixer'].get('in_flight') \
                and pr['fixer'].get('request_id') is None:
            guard = pr['fixer']
            owner = pr.get('owner') or {}
            # Missing identity may be filled only for the same observed writer.
            if guard.get('owner_thread_id') == owner.get('thread_id') \
                    and not guard.get('host_task_id'):
                guard['host_task_id'] = owner.get('host_task_id')

    # Omissions never close a known-open PR. Only explicit host state does.
    omitted = []
    for url, pr in state['prs'].items():
        if pr.get('state') != 'open' or url in seen_urls:
            continue
        pr['discovery_gap'] = 'omitted from a partial or temporary discovery snapshot'
        omitted.append(url)

    discovery = {'complete': complete, 'gaps': gaps}
    for url, pr in state['prs'].items():
        terminal_read = (url in seen_urls
                         and pr['observation']['state'] in ('MERGED', 'CLOSED'))
        if pr.get('state') != 'open' and not pending_write(pr, state, now) and not terminal_read:
            continue
        mark_stale_merges(pr, pr['observation'].get('head_sha'))
        action, queue, blocked, signature = reconcile_pr(pr, state, now, discovery)
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
        # A scope-wide coverage gap stays visible without suppressing an independent
        # PR whose own targeted evidence and gates are complete.
        if state['discovery']['attempts'] >= DISCOVERY_RETRY_LIMIT:
            actions.append({'kind': 'discovery-blocked', 'reason':
                            f"discovery incomplete after {state['discovery']['attempts']} attempts",
                            'next_check_at': deadline(now, state['policy']['cadence_seconds']),
                            'blocked': {'kind': 'discovery-incomplete', 'detail': gaps}})

    scheduler = state['scheduler']
    if wake_kind == 'schedule':
        scheduler['last_wake_at'] = now_iso(now)
        scheduler['last_wake_id'] = wake_id
        scheduler['last_wake_kind'] = wake_kind
        if scheduler.get('next_run_at') and \
                parse_time(scheduler['next_run_at'], 'next_run_at') <= now:
            # The host delivered the recorded run. The next wake time comes from the
            # next host receipt, not from adding the cadence locally.
            scheduler['next_run_at'] = None
            scheduler['awaiting_receipt'] = True

    state['events'][event_key] = now_iso(now)
    if len(state['events']) > 500:
        state['events'] = dict(list(state['events'].items())[-500:])
    state['updated_at'] = now_iso(now)
    audit(state, now, 'observe', wake=wake_id, wake_kind=wake_kind,
          admitted=len(admitted), actions=len(actions), progress=progressed,
          complete=complete)
    report = scheduler_report(state, now)
    return {
        'status': 'cancelled' if state.get('cancelled') else 'ok',
        'wake': {'id': wake_id, 'kind': wake_kind, 'duplicate': False},
        'admitted': admitted,
        'excluded': excluded_rows,
        'actions': actions,
        'queue': queue_rows,
        'discovery': {'complete': complete, 'gaps': gaps, 'omitted': omitted,
                      'attempts': state['discovery']['attempts']},
        'scheduler': report,
        'coverage': report['coverage'],
        'human_questions': questions,
        'progress': {'meaningful': progressed},
        'next_wake_at': report['next_run_at'],
        'policy_version': state['policy_version'],
    }


# ---------------------------------------------------------------------------
# commands


def cmd_start(args):
    path = state_path(args.state)
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
    identity = source_identity(args.script)
    pinned = args.package_version or identity['installed_version']
    job_path = getattr(args, 'job', None)
    job_id = getattr(args, 'job_id', None)
    if job_path:
        store, job = verified_job(job_path)
        require(not job_id or job_id == job['job_id'], '--job-id differs from the pinned job')
        require(any(pin['package_digest'] == identity['digest']
                    and Path(pin['package_dir']).resolve() == Path(identity['package_dir']).resolve()
                    for pin in job['pins'].values()), 'this helper is not the job-pinned package')
        job_id, job_path = job['job_id'], str(store.file)
    scope = {
        'kind': scope_kind, 'value': value,
        'include_drafts': bool(args.include_drafts),
        'include_forks': bool(args.include_forks),
        'exclusions': list(args.exclude),
    }
    run_id = uuid.uuid4().hex
    state = {
        'schema_version': SCHEMA_VERSION,
        'policy_version': POLICY_VERSION,
        'run_id': run_id,
        'job_id': job_id,
        'job': job_path,
        'job_state_sha256': getattr(args, 'job_state_sha256', None),
        'created_at': now_iso(now),
        'updated_at': now_iso(now),
        'thread_id': args.thread_id,
        'scope': scope,
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
            'generation': 1,
            'history': [],
            'stopped': None,
            'awaiting_receipt': False,
            'last_wake_at': None,
            'last_wake_id': None,
            'last_wake_kind': None,
            'gap': (None if mode == 'scheduled' else
                    'event-only: no idle discovery, queue-age diagnosis or stalled-work wake'),
        },
        'package': {'pinned_version': pinned,
                    'installed_version': identity['version'],
                    'installed_digest': identity['digest'],
                    'helper': str(Path(args.script).resolve())},
        'prs': {},
        'events': {},
        'discovery': {'attempts': 0, 'last_attempt_at': None, 'last_complete_at': None,
                      'gaps': [], 'complete': None},
        'cancelled': None,
        'migration': None,
        'audit': [],
    }
    if mode == 'scheduled':
        state['scheduler']['gap'] = 'scheduler authorized; no host schedule receipt recorded yet'
    audit(state, now, 'start', scheduler=mode, scope=f'{scope_kind}:{value}', run_id=run_id)
    # Creation is exclusive: an existing run is resumed (or migrated) explicitly,
    # never replaced along with its roster, dispatches and writer guard.
    with locked_state(path, create=True):
        if path.exists():
            raise ContinuousError(
                f'{path} already exists; run resume for that run or choose a new state path')
        save_json_exclusive(path, state)
    return {'status': 'started', 'state': str(path), 'run_id': run_id,
            'policy_version': POLICY_VERSION, 'scheduler': state['scheduler'],
            'policy': state['policy'], 'scope': state['scope'],
            'package': {key: state['package'][key]
                        for key in ('pinned_version', 'installed_version', 'installed_digest')}}


def schedule_request(state, state_file):
    scope = state['scope']
    generation = state['scheduler'].get('generation', 1)
    # The durable run identity is part of the key: two runs for the same scope in the
    # same thread must never share host idempotency, prompt or stop ownership.
    key = (f"babysitter-{scope['kind']}-{scope['value'].replace('/', '-')}"
           f"-{POLICY_VERSION}-{state.get('run_id') or 'norun'}-g{generation}")
    package = state.get('package') or {}
    prompt = (
        f"Continue the authorised babysitter {scope['kind']} sweep for {scope['value']} "
        f"(run {state.get('run_id')}, policy {state.get('policy_version')}, "
        f"package {package.get('pinned_version')}). Resume the pinned package with its "
        f"continuous helper and --state {state_file}: refresh discovery, reconcile the whole "
        "scope, diagnose queue age and stalled work, admit new matching PRs, reconcile "
        "dispatch receipts, and continue only actions already authorised by the owner's "
        "request. Report concrete blockers, the next action and the next wake. Do not "
        "create a second schedule; this scheduled wake is the continuation.")
    return {
        'key': key,
        'clientRequestId': key,
        'tool': 'schedule_task',
        'arguments': {
            'schedule': {'type': 'interval', 'everyMs': state['policy']['cadence_seconds'] * 1000},
            'bindToCurrentThread': bool(state.get('thread_id')),
            'prompt': prompt,
            'title': f"babysitter {scope['kind']} {scope['value']} continuous sweep",
            'clientRequestId': key,
        },
    }


def cmd_schedule_plan(args):
    path = state_path(args.state)
    with locked_state(path) as state:
        if state.get('cancelled'):
            return {'status': 'cancelled', 'request': None, 'cancelled': state['cancelled'],
                    'instruction': 'resume the run explicitly before planning scheduled work'}
        scheduler = state['scheduler']
        stopped = scheduler.get('stopped') or {}
        request = schedule_request(state, path)
        if stopped and stopped.get('verified') is not True:
            return {'status': 'stop-unverified', 'request': None,
                    'gap': 'the previous host schedule is not verified stopped; '
                           'verify it before re-arming',
                    'stop': scheduler.get('stop')}
        if scheduler.get('schedule_id') and not stopped.get('verified'):
            return {'status': 'already-scheduled', 'schedule_id': scheduler['schedule_id'],
                    'next_run_at': scheduler.get('next_run_at'),
                    'stop': scheduler.get('stop'), 'request': request,
                    'instruction': 'do not create a second schedule'}
        if scheduler['mode'] != 'scheduled':
            return {'status': 'event-only', 'request': None,
                    'gap': scheduler.get('gap'),
                    'instruction': 'schedule only with explicit owner authorization'}
        return {'status': 'plan', 'request': request,
                'generation': scheduler.get('generation', 1),
                'stop_after_create': {'tool': 'delete_scheduled_task',
                                      'arguments': {'scheduledTaskId': '<returned schedule id>'}}}


def cmd_schedule_record(args):
    path = state_path(args.state)
    with locked_state(path) as state:
        if state.get('cancelled'):
            raise ContinuousError('this run is cancelled; resume it before recording a schedule')
        now = parse_time(args.now, '--now')
        require(state['scheduler']['mode'] == 'scheduled',
                'event-only runs cannot record a host schedule; obtain scheduler authorization first')
        require(bool(args.schedule_id), '--schedule-id is required')
        require(bool(args.next_run_at), '--next-run-at is required')
        next_run = parse_time(args.next_run_at, '--next-run-at')
        require(next_run > now, '--next-run-at must be after the recording time')
        scheduler = state['scheduler']
        stopped = scheduler.get('stopped') or {}
        if stopped and stopped.get('verified') is not True:
            raise ContinuousError('verify the previous schedule is stopped before recording a replacement')
        current = scheduler.get('schedule_id')
        if current and current != args.schedule_id:
            raise ContinuousError(
                f"a different schedule ({current}) already owns this scope; "
                "stop it before creating another")
        request = schedule_request(state, path)
        scheduler.update({
            'schedule_id': args.schedule_id,
            'next_run_at': now_iso(next_run),
            'recorded_at': now_iso(now),
            'stop': {'tool': 'delete_scheduled_task',
                     'arguments': {'scheduledTaskId': args.schedule_id}},
            'gap': None,
            'awaiting_receipt': False,
        })
        scheduler['request_key'] = request['key']
        if stopped.get('verified'):
            scheduler['stopped'] = None
        duplicate = current == args.schedule_id
        audit(state, now, 'schedule', schedule_id=args.schedule_id, duplicate=duplicate)
        save_json(path, state)
        return {'status': 'already-recorded' if duplicate else 'recorded',
                'duplicate': duplicate, 'schedule_id': args.schedule_id,
                'next_run_at': scheduler['next_run_at'],
                'stop': scheduler['stop']}


def cmd_schedule_stop(args):
    path = state_path(args.state)
    with locked_state(path) as state:
        now = parse_time(args.now, '--now')
        scheduler = state['scheduler']
        current = scheduler.get('schedule_id')
        require(bool(args.schedule_id), '--schedule-id is required')
        require(current == args.schedule_id,
                f'schedule {args.schedule_id} is not the active schedule'
                + (f' ({current})' if current else ''))
        verified = args.verified == 'yes'
        entry = {'schedule_id': args.schedule_id, 'at': now_iso(now),
                 'verified': verified, 'stop': scheduler.get('stop')}
        scheduler.setdefault('history', []).append(entry)
        scheduler['stopped'] = entry
        scheduler['next_run_at'] = None
        scheduler['awaiting_receipt'] = False
        if verified:
            scheduler['schedule_id'] = None
            scheduler['stop'] = None
            scheduler['gap'] = 'host schedule stopped and verified; no wake will arrive until re-armed'
            scheduler['generation'] = int(scheduler.get('generation', 1)) + 1
        else:
            scheduler['gap'] = ('stop requested but not verified; verify the schedule is absent '
                                'or disabled before re-arming')
        audit(state, now, 'schedule-stop', schedule_id=args.schedule_id, verified=verified)
        save_json(path, state)
        return {'status': 'stopped' if verified else 'stop-unverified',
                'schedule_id': args.schedule_id, 'verified': verified,
                'stop': entry.get('stop'), 'gap': scheduler['gap']}


def cmd_scheduler(args):
    path = state_path(args.state)
    with locked_state(path) as state:
        if state.get('cancelled'):
            raise ContinuousError('this run is cancelled; resume it before changing scheduler coverage')
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
            state['scheduler']['gap'] = state['scheduler'].get('gap') or (
                'scheduler authorized; no host schedule receipt recorded yet')
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
            if state['scheduler'].get('schedule_id'):
                state['scheduler']['stopped'] = {
                    'schedule_id': state['scheduler']['schedule_id'],
                    'at': now_iso(now), 'verified': False,
                    'stop': state['scheduler'].get('stop')}
                state['scheduler']['gap'] += '; owned host schedule stop is unverified'
        state['scheduler']['recorded_at'] = now_iso(now)
        audit(state, now, 'scheduler', mode=outcome)
        save_json(path, state)
        report = scheduler_report(state, now)
        return {'status': outcome, 'scheduler': report,
                'coverage': report['coverage'], 'gap': report['gap'],
                'scheduler_stop': state['scheduler'].get('stop')}


def normalise_pr(raw, now):
    repo = raw.get('repo')
    number = raw.get('number')
    require(isinstance(repo, str) and re.fullmatch(r'[^/\s]+/[^/\s]+', repo),
            'each PR needs a repo as owner/name')
    require(type(number) is int and number > 0, 'each PR needs a positive number')
    url = str(raw.get('url') or pr_key(repo, number))
    if raw.get('checks') is not None:
        check_rows = raw['checks']
        checks_complete = raw.get('checks_complete', True) is not False
        checks_source = 'full'
    else:
        # A list-prs.sh line carries pending_checks and a failing-name list. Accept it
        # directly so the coordinator does not have to reinterpret the reader.
        check_rows = list(raw.get('pending_checks') or [])
        check_rows += [{'name': name, 'status': 'COMPLETED', 'conclusion': 'FAILURE'}
                       for name in raw.get('failing') or []]
        checks_complete = raw.get('checks_complete') is True
        checks_source = 'reader'
    checks = [normalise_check(c) for c in check_rows]
    clock_gaps = raw.get('queue_clock_gaps') or []
    require(isinstance(clock_gaps, list) and all(
        isinstance(gap, dict) and isinstance(gap.get('name'), str) and gap['name']
        and isinstance(gap.get('reason'), str) and gap['reason'] for gap in clock_gaps),
        'queue_clock_gaps must list check names and reasons')
    default_check_head = raw.get('checks_head_sha')
    if not default_check_head and raw.get('head_oid'):
        default_check_head = raw.get('head_oid')
    if default_check_head:
        for check in checks:
            if not check['head_sha']:
                check['head_sha'] = default_check_head
    observation = {
        'state': str(raw.get('state') or 'OPEN').upper(),
        'head_sha': raw.get('head_sha') or raw.get('head_oid'),
        'checks': checks,
        'checks_complete': checks_complete,
        'checks_source': checks_source,
        'queue_clock_gaps': [dict(gap) for gap in clock_gaps],
        'checks_state': raw.get('checks_state'),
        'checks_head_sha': raw.get('checks_head_sha'),
        'required_contexts': raw.get('required_contexts'),
        'required_contexts_known': raw.get('required_contexts_known',
                                           raw.get('required_contexts') is not None),
        'required_contexts_observed': raw.get('required_contexts_observed'),
        'optional_contexts_observed': raw.get('optional_contexts_observed'),
        'unresolved_threads': normalise_threads(raw),
        'review_decision': raw.get('review_decision'),
        'review_threads_complete': raw.get('review_threads_complete'),
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


def cmd_observe(args):
    path = state_path(args.state)
    with locked_state(path) as state:
        now = parse_time(args.now, '--now')
        if state.get('cancelled'):
            return {'status': 'cancelled', 'actions': [], 'admitted': [], 'human_questions': [],
                    'cancelled': state['cancelled'],
                    'message': 'this run was cancelled; resume explicitly to continue'}
        if args.wake_kind == 'schedule' and (
                state['scheduler']['mode'] != 'scheduled'
                or state['scheduler']['authorization']['state'] != 'authorized'
                or state['scheduler'].get('stopped')):
            report = scheduler_report(state, now)
            return {'status': 'scheduled-continuation-blocked', 'actions': [],
                    'admitted': [], 'human_questions': [], 'scheduler': report,
                    'coverage': report['coverage'], 'next_wake_at': None,
                    'scheduler_stop': state['scheduler'].get('stop')}
        observation = load_json(args.observation)
        result = reconcile_observation(state, observation, now, args.wake_id, args.wake_kind)
        if result['status'] != 'duplicate':
            state['last_observation_wake_kind'] = args.wake_kind
            save_json(path, state)
        return result


def cmd_dispatch(args):
    """Reserve, then record, one dispatch.

    A coordinator that is about to perform a host side effect must call this with
    ``--reserve`` first: the row, the writer guard and the merge exclusion exist before
    the host launches anything. The returned host handle is attached afterwards with a
    second call naming the same request ID. An uncertain launch keeps its reservation
    until host reconciliation establishes a handle or confirms refusal.
    """
    path = state_path(args.state)
    with locked_state(path) as state:
        if state.get('cancelled'):
            raise ContinuousError('this run is cancelled; resume it before dispatching new work')
        now = parse_time(args.now, '--now')
        pr = state['prs'].get(args.pr)
        require(pr is not None, f'unknown PR: {args.pr}')
        require(bool(args.request_id), '--request-id is required')
        require(args.kind in KIND_RECEIPT_STATUSES,
                'dispatch kind must be fixer, merge, update-branch or resolution')
        reserve = bool(getattr(args, 'reserve', False))
        existing = next((row for row in pr['dispatches'] if row['request_id'] == args.request_id), None)
        if existing:
            require(existing['kind'] == args.kind,
                    f"request {args.request_id} is a {existing['kind']} dispatch, not {args.kind}")
            if (not reserve and args.host_task_id and not existing.get('host_task_id')
                    and dispatch_status(existing) in ('reserved', 'uncertain')):
                existing['host_task_id'] = args.host_task_id
                existing['status'] = 'pending'
                existing['attached_at'] = now_iso(now)
                if existing['kind'] == 'fixer' and pr.get('fixer'):
                    pr['fixer']['host_task_id'] = args.host_task_id
                audit(state, now, 'dispatch-attach', pr=args.pr,
                      request_id=args.request_id, host_task_id=args.host_task_id)
                save_json(path, state)
                return {'status': 'recorded', 'attached': True, 'dispatch': existing,
                        'host_task_id': args.host_task_id}
            if reserve and dispatch_status(existing) in ('reserved', 'uncertain'):
                return {'status': 'already-reserved', 'request_id': args.request_id,
                        'dispatch': existing}
            return {'status': 'duplicate', 'request_id': args.request_id,
                    'host_task_id': existing.get('host_task_id'), 'dispatch': existing}
        if reserve and args.host_task_id:
            raise ContinuousError(
                'reserve before the host side effect; attach --host-task-id afterwards')
        require(pr.get('state') == 'open' and not pr.get('excluded'),
                'this PR is no longer eligible: lifecycle or scope exclusion changed')
        observation = pr.get('observation') or {}
        require(scope_matches(state['scope'], pr) and not excluded(
            state['scope'], {**pr, **observation}), 'this PR is outside the authorized scope')
        require(not owned_elsewhere(pr, state.get('thread_id')),
                'this PR is owned elsewhere; explicit handoff is required')
        require(not pr.get('discovery_gap'), 'refresh this omitted PR before reserving writes')
        require(not (state.get('last_observation_wake_kind') == 'schedule' and (
            state['scheduler']['mode'] != 'scheduled' or state['scheduler'].get('stopped'))),
            'scheduled continuation is no longer authorized; reconcile the owned stop')
        if args.head:
            require(args.head == observation.get('head_sha'),
                    'dispatch head differs from the current observed head')
        fixer = pr.get('fixer') or {}
        merge = live_merge_dispatch(pr)
        resolution = next((item for item in pr['dispatches']
                           if item['kind'] == 'resolution'
                           and dispatch_status(item) in OPEN_DISPATCH), None)
        if resolution:
            raise ContinuousError(
                f"resolution {resolution['request_id']} is pending; another write may not race it")
        update = live_dispatch(pr, 'update-branch')
        if update:
            raise ContinuousError(
                f"update-branch {update['request_id']} is pending; another write may not race it")
        if args.kind == 'resolution' and merge:
            raise ContinuousError(
                f"merge {merge['request_id']} is pending; resolution may not race it")
        if args.kind == 'fixer':
            if fixer.get('in_flight'):
                raise ContinuousError(
                    f"fixer {fixer.get('request_id')} is already in flight for {args.pr}")
            if merge:
                raise ContinuousError(
                    f"merge {merge['request_id']} is pending for {args.pr}; a fixer may not race it")
            row = {'request_id': args.request_id, 'host_task_id': args.host_task_id,
                   'kind': 'fixer', 'head': args.head or (pr.get('observation') or {}).get('head_sha'),
                   'status': 'reserved' if reserve else 'pending',
                   'attempt': int(args.attempt or 1),
                   'review_triage': bool(args.review_triage),
                   'created_at': now_iso(now)}
            pr['dispatches'].append(row)
            pr['fixer'] = {'in_flight': True, 'request_id': args.request_id,
                           'started_at': now_iso(now),
                           'host_task_id': args.host_task_id}
            audit(state, now, 'dispatch-reserve' if reserve else 'dispatch', pr=args.pr,
                  request_id=args.request_id, host_task_id=args.host_task_id)
            save_json(path, state)
            return {'status': 'recorded', 'dispatch': row, 'fixer': pr['fixer']}
        if args.kind in ('merge', 'update-branch'):
            require(bool(args.head), 'a merge dispatch must name the exact head')
            require(re.fullmatch(r'[0-9a-f]{40}', args.head) is not None,
                    'a merge dispatch needs the full 40-character head')
            current = (pr.get('observation') or {}).get('head_sha')
            require(not current or args.head == current,
                    f'merge head {args.head} is not the observed head {current}')
            if fixer.get('in_flight'):
                raise ContinuousError(
                    f"fixer {fixer.get('request_id')} is in flight for {args.pr}; "
                    "a merge may not race a live writer")
            if merge:
                raise ContinuousError(
                    f"merge {merge['request_id']} is already pending for {args.pr}")
            # A retained green action is insufficient: a later observation may have
            # found a red check or incomplete gate at the same head. Reconcile under
            # the reservation lock before recording any landing operation.
            action, _, _, _ = reconcile_pr(pr, state, now, state['discovery'])
            require(action['kind'] == args.kind,
                    f"{args.kind} gates are not satisfied; current action is {action['kind']}: "
                    f"{action['reason']}")
        if args.kind == 'resolution':
            if fixer.get('in_flight'):
                raise ContinuousError(
                    f"fixer {fixer.get('request_id')} is in flight for {args.pr}; "
                    "resolve threads only after its result is ingested")
        row = {'request_id': args.request_id, 'kind': args.kind,
               'head': args.head or (pr.get('observation') or {}).get('head_sha'),
               'status': 'reserved' if reserve else 'pending',
               'attempt': int(args.attempt or 1),
               'created_at': now_iso(now),
               'host_task_id': args.host_task_id}
        pr['dispatches'].append(row)
        audit(state, now, 'dispatch-reserve' if reserve else 'dispatch', pr=args.pr,
              request_id=args.request_id, dispatch_kind=args.kind)
        save_json(path, state)
        return {'status': 'recorded', 'dispatch': row}


def cmd_receipt(args):
    """Record the outcome of one dispatch.

    A completion applies only to the request it names. A stale replay is reported and
    changes nothing, including the progress clock.
    """
    path = state_path(args.state)
    with locked_state(path) as state:
        now = parse_time(args.now, '--now')
        pr = state['prs'].get(args.pr)
        require(pr is not None, f'unknown PR: {args.pr}')
        require(bool(args.request_id), '--request-id is required')
        row = next((item for item in pr['dispatches']
                    if item['request_id'] == args.request_id), None)
        guard = pr.get('fixer') or {}
        if row is None and getattr(args, 'kind', None) == 'fixer' and guard.get('in_flight') \
                and guard.get('request_id') is None:
            # The guard was adopted from a host observation before this helper saw the
            # dispatch. Only the writer's observed handle may close it: an arbitrary
            # historical request ID is not evidence about this writer.
            observed_handle = guard.get('host_task_id')
            require(bool(observed_handle),
                    'the adopted writer has no recorded host handle; re-observe it with '
                    'owner.host_task_id before recording a completion')
            require(args.host_task_id == observed_handle,
                    f'receipt handle {args.host_task_id!r} does not match the adopted '
                    f'writer handle {observed_handle!r}')
            row = {'request_id': args.request_id, 'kind': 'fixer',
                   'head': (pr.get('observation') or {}).get('head_sha'),
                   'host_task_id': observed_handle,
                   'status': 'pending', 'attempt': 1, 'created_at': now_iso(now)}
            pr['dispatches'].append(row)
        require(row is not None, f'unknown dispatch: {args.request_id}')
        require(not getattr(args, 'kind', None) or args.kind == row['kind'],
                'receipt kind differs from the recorded dispatch kind')
        allowed = KIND_RECEIPT_STATUSES[row['kind']]
        require(args.status in allowed,
                f"{row['kind']} receipts accept {', '.join(sorted(allowed))}; "
                f"{args.status!r} is not a terminal outcome for that kind")
        if dispatch_status(row) in TERMINAL_DISPATCH and dispatch_status(row) == args.status:
            return {'status': 'duplicate', 'changed': False, 'request_id': args.request_id,
                    'dispatch': row}
        if row['kind'] == 'update-branch' and dispatch_status(row) in TERMINAL_DISPATCH:
            return {'status': 'stale', 'changed': False, 'request_id': args.request_id,
                    'dispatch': row}
        if args.head and row.get('head') and args.head != row['head']:
            raise ContinuousError(
                f"receipt head {args.head} differs from dispatch head {row['head']}")
        if row['kind'] in ('merge', 'resolution', 'update-branch') and args.status in TERMINAL_DISPATCH \
                and row.get('host_task_id'):
            require(args.host_task_id == row['host_task_id'],
                    f"a terminal {row['kind']} receipt must name the recorded host handle")
        if args.host_task_id and row.get('host_task_id') and \
                args.host_task_id != row['host_task_id']:
            raise ContinuousError(
                f"receipt handle {args.host_task_id} differs from dispatch handle "
                f"{row['host_task_id']}")
        result_digest = None
        if args.result:
            result_path = Path(args.result).expanduser()
            require(result_path.is_file(), f'result file does not exist: {result_path}')
            result_digest = sha256_file(result_path)
        if row['kind'] == 'update-branch':
            if args.result:
                result = load_json(result_path)
                require(isinstance(result, dict), 'update helper result must be a JSON object')
                status, outcome = update_helper_receipt(pr, row, result)
                require(args.status == status,
                        f'update helper outcome is {outcome}; record --status {status}')
                row['update_outcome'] = outcome
            elif args.status != 'uncertain':
                # An explicit host launch refusal precedes any PUT. Once a helper
                # has reported an accepted/unknown PUT, only its evidence or a new
                # head can settle it, even if the surrounding host task terminates.
                current_head = (pr.get('observation') or {}).get('head_sha')
                require((args.status == 'rejected' and not row.get('host_task_id')
                         and not row.get('update_outcome')) or (
                    row.get('host_task_id') and current_head != row.get('head')
                    and re.fullmatch(r'[0-9a-f]{40}', str(current_head or ''))),
                        'a synchronous update requires --result with a matching helper '
                        'outcome; an unconfirmed PUT stays uncertain until a new head '
                        'observation or confirmed rejection')
        if row['kind'] == 'fixer' and args.status in TERMINAL_DISPATCH:
            # Only a confirmed refusal before a handle exists needs no execution.
            if not (args.status == 'rejected' and not row.get('host_task_id')
                    and guard.get('request_id') == args.request_id):
                result_digest = accepted_fixer_result(args, state, row)
        stale = False
        if row['kind'] == 'fixer' and guard.get('in_flight'):
            if guard.get('request_id') is not None:
                stale = guard['request_id'] != args.request_id
            else:
                # An adopted guard is identified only by the handle observed with it.
                handle = row.get('host_task_id') or args.host_task_id
                stale = not (guard.get('host_task_id') and
                             handle == guard['host_task_id'])
        row['status'] = args.status
        if row['kind'] == 'update-branch' and args.status == 'succeeded':
            pr['branch_update'] = {'request_id': row['request_id'], 'head': row['head'],
                                   'refresh_required': True}
        if row['kind'] == 'update-branch' and args.status == 'no-change':
            outcome = row['update_outcome']
            if outcome in ('merged', 'closed'):
                record_terminal_pr(pr, outcome, row['head'], now)
            else:
                pr['branch_update'] = {'request_id': row['request_id'], 'head': row['head'],
                                       'outcome': outcome, 'refresh_required': True}
        if args.status in TERMINAL_DISPATCH:
            row['completed_at'] = now_iso(now)
        else:
            row['armed_at'] = now_iso(now)
        if result_digest:
            row['result_digest'] = result_digest
        if args.reason:
            row['note'] = str(args.reason)[:500]
        if row['kind'] == 'fixer' and not stale and args.status in TERMINAL_DISPATCH:
            # Only a verified terminal outcome releases the writer guard. 'armed' is a
            # merge state and proves nothing about a fixer's completion.
            pr['fixer'] = {'in_flight': False, 'request_id': None, 'started_at': None}
            if args.status in ('succeeded', 'no-change') and result_digest:
                # An ingested, verified result is real progress; a replay is not.
                pr['last_meaningful_progress_at'] = now_iso(now)
        audit(state, now, 'receipt', pr=args.pr, request_id=args.request_id,
              status=args.status, stale=stale)
        if row['kind'] in ('resolution', 'update-branch'):
            pending = pending_write(pr, state, now)
            if state.get('cancelled') and not pending:
                pr.update(next_action=None, blocked=None, queue=None)
            elif pr.get('state') in ('open', 'merged', 'closed') or pending:
                action, queue, blocked, _ = reconcile_pr(pr, state, now, state['discovery'])
                pr.update(next_action={**action, **({'blocked': blocked} if blocked else {})},
                          queue=queue, blocked=blocked)
            elif pr.get('state') == 'excluded':
                pr.update(next_action=None, blocked=None, queue=None)
        save_json(path, state)
        return {'status': 'stale' if stale else 'recorded',
                'changed': not stale and args.status in TERMINAL_DISPATCH,
                'request_id': args.request_id, 'dispatch': row,
                'fixer': pr.get('fixer')}


def cmd_resolve(args):
    """Close a known PR only from an explicit targeted host read, never from omission."""
    path = state_path(args.state)
    with locked_state(path) as state:
        now = parse_time(args.now, '--now')
        pr = state['prs'].get(args.pr)
        require(pr is not None, f'unknown PR: {args.pr}')
        require(args.state_value in ('merged', 'closed'), '--state must be merged or closed')
        require(bool(args.head), 'resolution needs the explicitly observed head')
        current = (pr.get('observation') or {}).get('head_sha')
        if current and args.head != current:
            raise ContinuousError(
                f'resolution head {args.head} differs from the observed head {current}')
        record_terminal_pr(pr, args.state_value, args.head, now)
        action, queue, blocked, _ = reconcile_pr(pr, state, now, state['discovery'])
        pr.update(next_action={**action, **({'blocked': blocked} if blocked else {})},
                  queue=queue, blocked=blocked)
        audit(state, now, 'resolve', pr=args.pr, resolved=args.state_value, head=args.head)
        save_json(path, state)
        return {'status': 'resolved', 'pr': args.pr, 'state': args.state_value,
                'head': args.head}


def cmd_cancel(args):
    path = state_path(args.state)
    with locked_state(path) as state:
        now = parse_time(args.now, '--now')
        state['cancelled'] = {'at': now_iso(now), 'reason': args.reason}
        audit(state, now, 'cancel', reason=args.reason)
        save_json(path, state)
        return {'status': 'cancelled', 'cancelled': state['cancelled'],
                'scheduler_stop': state['scheduler'].get('stop'),
                'instruction': 'stop the owned host schedule; no further actions will be produced'}


def validate_upgrade_receipt(receipt_path, state, owner_decision, installed, job_path):
    """Validate the supported ``job_cli.py upgrade-package`` receipt.

    A migration may not replace the pinned identity on the strength of a version flag
    alone. The receipt must come from the upgrade operation and bind the target package
    (and, when known, the pinned job and its previous state) to this decision.
    """
    receipt_path = Path(receipt_path).expanduser()
    require(receipt_path.is_file(), f'upgrade receipt does not exist: {receipt_path}')
    receipt = load_json(receipt_path)
    require(isinstance(receipt, dict), 'the upgrade receipt must be a JSON object')
    require(receipt.get('package_digest') == installed['digest'],
            'the upgrade receipt does not name the running package digest; '
            'run job_cli.py upgrade-package for this installed package')
    require(bool(receipt.get('package_dir')),
            'the upgrade receipt must name its package directory')
    require(Path(receipt['package_dir']).resolve() == Path(installed['package_dir']).resolve(),
            'the upgrade receipt package directory is not the running package')
    job_id = state.get('job_id')
    if job_id:
        require(receipt.get('job_id') == job_id,
                f"the upgrade receipt job {receipt.get('job_id')!r} is not the pinned job "
                f"{job_id!r}")
    require(bool(job_path), 'migration requires --job <pinned-job-dir> to verify the upgrade')
    store, job = verified_job(job_path)
    require(job['job_id'] == receipt.get('job_id'), 'upgrade receipt is not for this job')
    require(job['workflow'].startswith('babysitter/'), 'upgrade job is not a babysitter job')
    previous = receipt.get('previous_state')
    require(isinstance(previous, dict) and bool(previous.get('sha256'))
            and bool(previous.get('path')), 'upgrade receipt needs retained previous-state evidence')
    require(Path(previous['path']).resolve() == store.path / 'migrations' / (
        previous['sha256'] + '-job.json'), 'upgrade previous-state path is not retained by this job')
    from core.jobs import _owner_current
    from core.jobs.store import _regular, MAX_STATE_BYTES as JOB_MAX_BYTES, strict_load
    try:
        old_raw = _regular(Path(previous['path']), max_bytes=JOB_MAX_BYTES)
        require(hashlib.sha256(old_raw).hexdigest() == previous['sha256']
                and len(old_raw) == previous.get('bytes'), 'retained previous job bytes changed')
        old = strict_load(old_raw)
        require(old.get('job_id') == job['job_id'], 'retained previous state belongs to another job')
        if state.get('job_state_sha256'):
            require(previous['sha256'] == state['job_state_sha256'],
                    'the upgrade receipt previous state does not match this run')
        revision = next((item for item in job.get('plan_revisions', [])
                         if item.get('revision', {}).get('previous_state') == previous
                         and item.get('revision', {}).get('new_package_digest') == installed['digest']
                         and item.get('decision_id') == owner_decision
                         and item.get('revision', {}).get('owner_decision_id') == owner_decision), None)
        require(revision is not None, 'no matching supported job upgrade and owner decision recorded')
        decision = next((item for item in job['decisions']
                         if item.get('id') == owner_decision
                         and item.get('scope') == 'plan:' + revision['revision']['id']), None)
        require(decision is not None and _owner_current(decision, job['policy']['max_artifact_bytes']),
                'the upgrade owner decision evidence is unavailable or changed')
        keys = revision['adopted_dependencies']
        matching = [key for key in keys if key in job['pins'] and key in old['pins']
                    and job['pins'][key]['package_digest'] == installed['digest']
                    and Path(job['pins'][key]['package_dir']).resolve()
                    == Path(installed['package_dir']).resolve()]
        require(len(matching) == 1, 'job pin does not name the running upgraded package')
        old_pin = old['pins'][matching[0]]
        from shared.job_coordinator import verify_job_pins
        verify_job_pins(old)
        old_manifest = load_json(Path(old_pin['package_dir']) / 'install-manifest.json')
        package = state.get('package') or {}
        if package.get('pinned_version'):
            # Earlier continuous-1 defaulted to the plugin's base version. The
            # verified retained pin, not that abbreviated string, establishes identity.
            require(package['pinned_version'] in (old_manifest['version'],
                    old_manifest['version'].split('+', 1)[0]),
                    'retained old package version does not match this continuous run')
        if package.get('installed_digest'):
            # Earlier helpers hashed installed files plus metadata. Accept that
            # legacy fingerprint only after the old package passes manifest checks.
            require(package['installed_digest'] in (old_pin['package_digest'],
                    package_digest(Path(old_pin['package_dir']))),
                    'retained old package digest does not match this continuous run')
    except (ValueError, OSError, KeyError) as exc:
        raise ContinuousError(f'upgrade evidence is invalid: {exc}') from exc
    return {'path': str(receipt_path), 'sha256': sha256_file(receipt_path),
            'job_id': receipt.get('job_id'), 'package_digest': receipt.get('package_digest'),
            'owner_decision_id': owner_decision, 'job': str(store.file),
            'previous_state': previous}


def cmd_resume(args):
    path = state_path(args.state)
    require(fcntl is not None, 'continuous state locking requires a POSIX host with fcntl')
    require(path.exists(), f'no continuous state at {path}')
    lock_path = path.with_name(path.name + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        state = load_json(path)
        require(state.get('schema_version') == SCHEMA_VERSION,
                'unsupported continuous state schema')
        now = parse_time(args.now, '--now')
        installed = source_identity(args.script)
        gaps = []
        if state.get('policy_version') != installed['policy_version']:
            gaps.append({'kind': 'policy-version',
                         'state': state.get('policy_version'),
                         'installed': installed['policy_version']})
        package = state.get('package') or {}
        pinned = package.get('pinned_version')
        if args.package_version and pinned and args.package_version != pinned:
            gaps.append({'kind': 'package-version',
                         'state_pinned': pinned, 'installed_running': args.package_version})
        if not package.get('installed_digest'):
            # A state written before the fingerprint existed cannot prove which
            # package produced it. Surface that instead of silently claiming identity.
            gaps.append({'kind': 'missing-package-identity',
                         'state_pinned': pinned,
                         'detail': 'the state predates the installed-package fingerprint; '
                                   'its package identity is unverified'})
        elif package['installed_digest'] != installed['digest']:
            gaps.append({'kind': 'installed-drift',
                         'state_installed': package.get('installed_version'),
                         'installed_on_disk': installed['version'],
                         'state_digest': package.get('installed_digest'),
                         'installed_digest': installed['digest']})
        if args.package_version and installed['version'] and \
                args.package_version.split('+', 1)[0] != installed['version']:
            gaps.append({'kind': 'installed-drift',
                         'installed_running': args.package_version,
                         'installed_on_disk': installed['version'],
                         'detail': 'this helper is not the pinned package; preserve the brief '
                                   'and use the supported job package upgrade first'})
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
        if gaps and not getattr(args, 'upgrade_receipt', None):
            raise ContinuousError(
                'policy/package drift on this run needs the supported upgrade receipt: run '
                'job_cli.py upgrade-package, then pass --upgrade-receipt <output.json> '
                'with --accept-migration and --owner-decision-id')
        if gaps and args.package_version and installed['version'] and \
                args.package_version.split('+', 1)[0] != installed['version']:
            raise ContinuousError(
                'the running helper is not the pinned package; complete job_cli.py '
                'upgrade-package before accepting the migration')
        upgrade_receipt = None
        if getattr(args, 'upgrade_receipt', None):
            upgrade_receipt = validate_upgrade_receipt(
                args.upgrade_receipt, state, args.owner_decision_id, installed,
                getattr(args, 'job', None) or state.get('job'))
        changed = False
        if gaps:
            if state.get('migration') is None:
                state['migration'] = {'at': now_iso(now), 'from': state.get('policy_version'),
                                      'to': installed['policy_version'],
                                      'owner_decision_id': args.owner_decision_id,
                                      'upgrade_receipt': upgrade_receipt,
                                      'gaps': gaps}
            state['policy_version'] = installed['policy_version']
            package['installed_version'] = installed['version']
            package['installed_digest'] = installed['digest']
            package['pinned_version'] = args.package_version or installed['installed_version']
            package['helper'] = str(Path(args.script).resolve())
            state['package'] = package
            if upgrade_receipt:
                state['job_id'] = upgrade_receipt['job_id']
                state['job'] = upgrade_receipt['job']
                state['job_state_sha256'] = upgrade_receipt['previous_state']['sha256']
            changed = True
        if state.get('cancelled') and args.resume_cancelled:
            state['cancelled'] = None
            changed = True
        if args.package_version and not gaps:
            state.setdefault('package', {})['pinned_version'] = args.package_version
        state['updated_at'] = now_iso(now)
        audit(state, now, 'resume', gaps=gaps, changed=changed)
        save_json(path, state)
        status = 'resumed' if not (state.get('cancelled') and not args.resume_cancelled) else 'cancelled'
        return {'status': status, 'changed': changed, 'gaps': gaps,
                'policy_version': state['policy_version'], 'installed': installed,
                'migration': state.get('migration'),
                'cancelled': state.get('cancelled')}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def cmd_preflight(args):
    """Expose an older pinned job's continuous-coverage gap without changing it.

    A job pinned to a package from before continuous mode has neither this helper nor
    continuous state. This read-only preflight names that gap and the supported
    upgrade path; it never swaps the package, rewrites the brief or invents state.
    """
    now = parse_time(args.now, '--now')
    job_path = Path(args.job).expanduser()
    if job_path.is_dir():
        job_path = job_path / 'job.json'
    require(job_path.is_file(), f'job file does not exist: {job_path}')
    job = load_json(job_path)
    pins = job.get('pins') if isinstance(job.get('pins'), dict) else {}
    key = args.pin
    if key is None:
        key = 'babysitter' if 'babysitter' in pins else next(iter(pins), None)
    pin = pins.get(key) if key else None
    version = None
    package_dir = None
    if isinstance(pin, dict):
        version = pin.get('version') or pin.get('package_version') or pin.get('installed_version')
        package_dir = pin.get('package_dir')
        if package_dir and (Path(package_dir) / 'install-manifest.json').is_file():
            version = load_json(Path(package_dir) / 'install-manifest.json').get('version')
    helper = (Path(package_dir) / 'scripts' / 'continuous.py') if package_dir else None
    has_helper = bool(helper and helper.is_file())
    state_present = bool(args.state) and Path(args.state).expanduser().exists()
    gaps = []
    if not has_helper:
        gaps.append({'kind': 'pinned-package-without-continuous',
                     'pinned_version': version,
                     'detail': 'the pinned package predates continuous mode and has no '
                               'scripts/continuous.py'})
    if state_present:
        state = load_json(args.state)
        if state.get('policy_version') != policy_identity(load_json(
                Path(args.script).resolve().parents[1] / 'plugin.json')):
            gaps.append({'kind': 'policy-version', 'state': state.get('policy_version')})
    return {
        'status': 'legacy-job' if gaps else 'ready',
        'checked_at': now_iso(now),
        'job': str(job_path),
        'pin': key,
        'pinned_version': version,
        'pinned_package_has_helper': has_helper,
        'state_present': state_present,
        'gaps': gaps,
        'changed': False,
        'instruction': ('preserve the pinned brief, evidence and package; upgrade the job '
                        'through job_cli.py upgrade-package, then start continuous state '
                        'with the upgraded package. Do not swap the package silently.'),
    }


def cmd_status(args):
    path = state_path(args.state)
    with locked_state(path) as state:
        now = (parse_time(args.now, '--now') if getattr(args, 'now', None)
               else datetime.now(timezone.utc))
        report = scheduler_report(state, now)
        open_prs = [url for url, pr in state['prs'].items() if pr.get('state') == 'open']
        excluded = {url: pr.get('excluded') for url, pr in state['prs'].items()
                    if pr.get('state') == 'excluded'}
        return {
            'status': 'cancelled' if state.get('cancelled') else 'active',
            'run_id': state.get('run_id'),
            'policy_version': state['policy_version'],
            'scope': state['scope'],
            'policy': state['policy'],
            'scheduler': report,
            'coverage': report['coverage'],
            'open_prs': open_prs,
            'excluded': excluded,
            'prs': {url: {'state': pr.get('state'),
                          'blocked': pr.get('blocked'),
                          'queue': (pr.get('queue') or {}).get('oldest'),
                          'last_meaningful_progress_at': pr.get('last_meaningful_progress_at'),
                          'owner': pr.get('owner'), 'fixer': pr.get('fixer'),
                          'dispatches': pr.get('dispatches', []),
                          'next_action': (pending_write(pr, state, now) or
                                          (pr.get('next_action'),))[0]}
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
    start.add_argument('--job-id')
    start.add_argument('--job', help='job directory whose installed package is pinned')
    start.add_argument('--job-state-sha256')
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

    stop = sub.add_parser('schedule-stop')
    state_arg(stop)
    stop.add_argument('--now', required=True)
    stop.add_argument('--schedule-id', required=True)
    stop.add_argument('--verified', choices=('yes', 'no'), required=True)
    stop.set_defaults(func=cmd_schedule_stop)

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
    dispatch.add_argument('--kind', choices=tuple(KIND_RECEIPT_STATUSES), required=True)
    dispatch.add_argument('--host-task-id')
    dispatch.add_argument('--head')
    dispatch.add_argument('--attempt', type=int)
    dispatch.add_argument('--review-triage', action='store_true')
    dispatch.add_argument('--reserve', action='store_true',
                          help='record the action before any host side effect')
    dispatch.set_defaults(func=cmd_dispatch)

    receipt = sub.add_parser('receipt')
    state_arg(receipt)
    receipt.add_argument('--now', required=True)
    receipt.add_argument('--pr', required=True)
    receipt.add_argument('--request-id', required=True)
    receipt.add_argument('--status', required=True,
                         choices=('succeeded', 'failed', 'rejected', 'cancelled',
                                  'superseded', 'armed', 'no-change', 'uncertain'))
    receipt.add_argument('--head')
    receipt.add_argument('--result')
    receipt.add_argument('--job', help='job directory containing the accepted execution')
    receipt.add_argument('--host-task-id')
    receipt.add_argument('--reason')
    receipt.add_argument('--kind', choices=tuple(KIND_RECEIPT_STATUSES))
    receipt.set_defaults(func=cmd_receipt)

    done = sub.add_parser('fixer-done')
    state_arg(done)
    done.add_argument('--now', required=True)
    done.add_argument('--pr', required=True)
    done.add_argument('--request-id', required=True)
    done.add_argument('--result', required=True)
    done.add_argument('--job', help='job directory containing the accepted execution')
    done.add_argument('--head')
    done.add_argument('--host-task-id')
    done.add_argument('--reason')
    done.set_defaults(func=cmd_receipt, status='succeeded', kind='fixer')

    resolve = sub.add_parser('resolve')
    state_arg(resolve)
    resolve.add_argument('--now', required=True)
    resolve.add_argument('--pr', required=True)
    resolve.add_argument('--resolution', dest='state_value', required=True,
                         choices=('merged', 'closed'))
    resolve.add_argument('--head', required=True)
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
    resume.add_argument('--upgrade-receipt')
    resume.add_argument('--job', help='pinned job whose supported package upgrade is verified')
    resume.set_defaults(func=cmd_resume)

    preflight = sub.add_parser('preflight')
    preflight.add_argument('--job', required=True)
    preflight.add_argument('--pin')
    preflight.add_argument('--state')
    preflight.add_argument('--now', required=True)
    preflight.set_defaults(func=cmd_preflight)

    status = sub.add_parser('status')
    state_arg(status)
    status.add_argument('--now')
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
