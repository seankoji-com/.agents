#!/usr/bin/env python3
"""Focus-group lifecycle: model pilots, host-backed ingestion, reconciliation, resume and journey slots.

T3 owns dispatch, status and cancellation. The coordinator records each host observation and each
complete result through the shared job helper (`job_cli.py task-observation` and `job_cli.py result`);
these commands read that recorded job state once, together with the study records beside it, decide, and
return what the coordinator may do next. Nothing here calls a model, a browser, T3 or GitHub, waits,
loops, polls or schedules work; a host notification is the only wake.

Exit codes: 0 the operation succeeded, 1 a refusal or hold (nothing was dispatched or charged), 2 invalid
input or unsafe state. Every run prints one JSON object.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study as fg  # noqa: E402
from study import (JobError, Study, StudyError, _regular, canonical, digest, invalid, load_json,  # noqa: E402
                   refuse, safe_id, sha, strict_load, text)
from core.jobs import _record_identity, _unsettled  # noqa: E402  (the shared job's own identity and liveness rules)
from shared.job_acceptance import identity_exception_binding  # noqa: E402

evidence = fg.evidence_module()

TERMINAL = ('completed', 'failed', 'cancelled', 'interrupted')
BUSY = ('working', 'waiting_for_children')
TRANSPORT_LIMIT = 32768             # the shared worker-result transport limit
RETAIN_LIMIT = 16 * 1024 * 1024     # complete raw outputs up to this size are retained before any check
JOB_LIMIT = 16 * 1024 * 1024
# Why a participant execution produced no accepted evidence. None of these is product friction.
CATEGORIES = {
    'oversize_transport': 'session', 'not_ingested_by_job': 'session', 'conflicting_duplicate': 'session',
    'malformed_result': 'session', 'participant_not_ready': 'session', 'payload_missing': 'session',
    'payload_ambiguous': 'session', 'wrong_slot': 'session', 'forged_completion': 'session',
    'execution_unobserved': 'lifecycle', 'execution_not_settled': 'lifecycle', 'provider_failure': 'provider',
    'stale_observation': 'lifecycle',
}
IDENTITY_INSTRUCTION = ('Accept observed model {observed} for focus-group cell {cell} {stage} request {request} '
                        '(requested {requested})')
CONTRADICTION_INSTRUCTION = ('Accept contradictory host identity for focus-group cell {cell} {stage} request {request} '
                             '(requested {requested}; readings {readings}; resolved {resolved}; now {current})')


# ----------------------------------------------------------------------------- shared reads


def load_job(study):
    """The generic job beside the study, read once without locking or writing; None before `job_cli create`."""
    path = study.job_dir / 'job.json'
    if not path.exists():
        return None
    try:
        return strict_load(_regular(path, max_bytes=JOB_LIMIT))
    except (OSError, JobError, ValueError) as exc:
        invalid('unsafe_state', f'job.json is unreadable: {exc}')


def owned_requests(task):
    """Every request a job task has held: current, original, retired and those its handles name."""
    out = {task.get('request_id'), task.get('original_request_id'), *task.get('retired_request_ids', [])}
    out |= {h.get('request_id') for h in task.get('handles', []) + task.get('followups', [])}
    return out - {None}


def task_for_request(job, request_id):
    return next((t for t in (job or {}).get('tasks', []) if request_id in owned_requests(t)), None)


def task_cell(study, job, task, briefs=None):
    """The study cell a participant job task serves. job-spec records it on the slot; a slot added later by
    plan revision carries only its contract, so the brief this helper built for exactly that task and document
    names its cell. A slot whose target differs from that cell's is not this study's participant slot."""
    if task.get('worker_id') != 'focus-group/participant' or task.get('stage_id') not in ('first-impression', 'journey'):
        return None
    if task.get('focus_group'):
        return task['focus_group']
    rows = evidence.records(study, 'briefs') if briefs is None else briefs
    row = next((r for r in rows if (r['task_id'], r['stage'], r['document']) ==
                (task['task_id'], task['stage_id'], task.get('document'))), None)
    if row is None:
        return None
    cell = next((c for c in fg.cells(study.plan(row['revision'])['plan']) if c['cell_id'] == row['cell_id']), None)
    if cell is None or cell['target'] != task.get('target'):
        return None
    return {'cell_id': cell['cell_id'], 'persona_id': cell['persona_id'], 'pilot': cell['pilot']}


def served_slots(study, job):
    """(cell_id, stage) -> the job task declared for that participant slot."""
    briefs = evidence.records(study, 'briefs')
    out = {}
    for task in (job or {}).get('tasks', []):
        meta = task_cell(study, job, task, briefs)
        if meta:
            out.setdefault((meta['cell_id'], task['stage_id']), task)
    return out


def task_for_slot(study, job, cell_id, stage):
    return served_slots(study, job).get((cell_id, stage))


def slot_task_ids(study, job, plan):
    """(cell_id, stage) -> task ID for every participant slot of `plan`: the declared task serving it, else
    `fi-NN`/`jr-NN`, suffixed with the cell's hash when another cell's task already holds that ID."""
    served = served_slots(study, job)
    declared = {t['task_id'] for t in job['tasks']}
    ids = {}
    for n, cell in enumerate(fg.cells(plan), 1):
        for stage in fg.stages_for(plan['mode']):
            task = served.get((cell['cell_id'], stage))
            base = f"{'fi' if stage == 'first-impression' else 'jr'}-{n:02d}"
            ids[(cell['cell_id'], stage)] = (task['task_id'] if task else base if base not in declared
                                             else f"{base}-{sha(cell['cell_id'])[:8]}")
    return ids


def handle_for(task, request_id):
    rows = [h for h in task.get('handles', []) + task.get('followups', []) if h.get('request_id') == request_id]
    return rows[-1] if rows else None


def conflicts_for(task, request_id):
    """Every other host task returned for this request that the shared job retained as a conflict (refused
    as a handle, never proven not to run), with its shared terminal reconciliation, None until recorded."""
    out = {}
    for row in (task or {}).get('host_conflicts', []):
        if row.get('request_id') == request_id and row.get('host_task_id'):
            seen = out.setdefault(row['host_task_id'], {'host_task_id': row['host_task_id'], 'reconciled': None})
            seen['reconciled'] = seen['reconciled'] or row.get('reconciled')
    return [out[k] for k in sorted(out)]


def prepared(study, task, request_id):
    """Whether the job store holds an immutable brief prepared for this request (the only thing a dispatch
    can carry), now or before a retry replaced it."""
    if (task.get('brief') or {}).get('request_id') == request_id:
        return True
    name = f"{task['task_id']}-{digest(request_id.encode())}.json"
    return (study.job_dir / 'briefs' / name).exists() or (study.job_dir / 'briefs' / 'followup' / name).exists()


def settled(handle):
    return (handle is not None and handle.get('status') in TERMINAL and handle.get('has_pending_child_runs') is False
            and handle.get('work_state') not in BUSY)


def effective_record(study, revision, cell_id, stage, accepted):
    """The result filling a participant slot in `revision`: its own accepted record, else the entry its
    written, revalidated carry mapping carries. None when the slot is unfilled."""
    native = [r for r in accepted if (r['revision'], r['cell_id'], r['stage']) == (revision, cell_id, stage)]
    if native:
        return native[0], 'native'
    mapping = fg.recorded_carry(study, revision)
    by_sha = {r['record_sha256']: r for r in accepted}
    for entry in (mapping or {}).get('entries', []):
        if entry['status'] == 'carried' and (entry['cell_id'], entry['stage']) == (cell_id, stage):
            return by_sha[entry['record_sha256']], 'carry'
    return None, None


_UNREAD = object()


def model_of(observed):
    return {k: (observed or {}).get(k) for k in ('providerInstanceId', 'model')}


def current_identity(study, record, job=_UNREAD):
    """The identity of an accepted record's exact admitted request now. The record keeps the identity it was
    accepted with as history; the job handle of that same request (found through retries and revisions) is
    re-read under the shared sticky rules, so a later host source naming another model makes it `mismatched`.
    Nothing here ever upgrades an accepted identity, and without a recorded handle the record is all there is."""
    job = load_job(study) if job is _UNREAD else job
    recorded = record.get('identity', 'unreported')
    task = task_for_request(job, record['request_id'])
    handle = handle_for(task, record['request_id']) if task else None
    if handle is None:
        return {'state': recorded, 'observed': record.get('observed'), 'source': 'accepted record'}
    shared = handle.get('observed_identity') or {}
    observed = model_of(shared)
    state = 'mismatched' if shared.get('status') == 'mismatched' and recorded in ('verified', 'unreported') else recorded
    return {'state': state, 'observed': observed if any(observed.values()) else None,
            'source': 'job handle observed_identity of request ' + record['request_id']}


def recorded_states(task, handle):
    """The shared observed identity of one owned host task after each recorded observation of it, oldest
    first, then as the handle holds it now. The task's dispatch history is replayed cumulatively through the
    shared `_record_identity`, exactly as the handle accumulated it, so each state keeps which source reported
    which provider and model and what the shared rules resolved from them at that point. The handle keeps
    one row per source, so a later reading can replace an earlier one there; these states keep both."""
    host = handle.get('task_id', handle.get('host_task_id'))
    scratch = {'task_id': host, 'request_id': handle.get('request_id'), 'target': handle.get('target')}
    states = []
    for event in task.get('dispatch_history', []):
        if event.get('request_id') == handle.get('request_id') and event.get('host_task_id') == host:
            _record_identity({'blockers': []}, {'task_id': task['task_id'], 'target': task.get('target')}, scratch,
                             copy.deepcopy(event))
            states.append(copy.deepcopy(scratch['observed_identity']))
    return states + [handle.get('observed_identity') or {}]


def pair_text(pair):
    return '/'.join(pair.get(k) or 'unreported' for k in ('providerInstanceId', 'model'))


def normalized_pairs(pairs, complete_extra=()):
    """Distinct provider/model associations, sorted. A partial one (a missing field) is kept unless a complete
    association, here or in `complete_extra`, already names its reported field: it then adds nothing."""
    pairs = [model_of(p) for p in pairs if any(model_of(p).values())]
    complete = [p for p in [*pairs, *map(model_of, complete_extra)] if all(p.values())]
    out = []
    for pair in pairs:
        subsumed = not all(pair.values()) and any(all(pair[k] in (None, c[k]) for k in pair) for c in complete)
        if not subsumed and pair not in out:
            out.append(pair)
    return sorted(out, key=lambda p: (p['providerInstanceId'] or '', p['model'] or ''))


def identity_evidence(study, record, job=_UNREAD):
    """The complete recorded identity evidence of an accepted record's exact request, kept apart from its
    requested target. `readings` are the distinct per-source rows the shared handle held over time; the
    shared canonical resolution (the status provider, then the status, receipt or configuration model) gives
    `canonical` now and `resolutions` over time. Nothing here pairs a provider and a model that no source or
    canonical resolution paired.

    `observed` is set only when the canonical resolution now is complete and every reading agrees with it:
    a `wrong-model` discrepancy. Two or more different complete associations are `contradictory`: the owner
    can accept them only through an instruction naming every association and resolution, with nothing
    observed. Anything else is a hold, with the missing canonical fields shown, and the target never fills a
    gap. `discrepancy_sha256` binds an owner decision to the request, host task, shared status, associations
    and resolutions: a repeated or equivalent reading keeps it; a new association, or a changed resolution
    (such as another status provider), changes it."""
    job = load_job(study) if job is _UNREAD else job
    requested = fg.identity_request(record['bindings']['requested_target'])
    task = task_for_request(job, record['request_id'])
    handle = handle_for(task, record['request_id']) if task else None
    if handle is None:
        given = record.get('observed') or {}
        states = [{'status': record.get('identity', 'unreported'), 'providerInstanceId': given.get('providerInstanceId'),
                   'model': given.get('model'),
                   'sources': {f"accepted record ({given.get('source')})": model_of(given)} if any(model_of(given).values())
                   else {}}]
        host = None
    else:
        states = recorded_states(task, handle)
        host = handle.get('task_id', handle.get('host_task_id'))
    status = states[-1].get('status', 'unreported')
    current_sources = states[-1].get('sources') or {}
    canonical = model_of(states[-1])
    readings = []
    for state in states:
        for source, value in sorted((state.get('sources') or {}).items()):
            row = {'source': source, **model_of(value)}
            if any(model_of(value).values()) and row not in readings:
                readings.append(row)
    resolved = [model_of(s) for s in states if any(model_of(s).values())]
    resolutions = normalized_pairs(resolved)
    associations = normalized_pairs(readings, complete_extra=resolutions)
    providers = sorted({p['providerInstanceId'] for p in associations + resolutions if p['providerInstanceId']})
    models = sorted({p['model'] for p in associations + resolutions if p['model']})
    complete = normalized_pairs([p for p in associations + resolutions if all(p.values())])
    missing = [k for k, v in canonical.items() if v is None]
    observed, hold, kind = None, None, None
    if not missing and providers == [canonical['providerInstanceId']] and models == [canonical['model']]:
        if canonical == model_of(requested):
            hold = 'the shared identity rules did not verify this execution, and no reading names another model'
        else:
            observed, kind = dict(canonical), 'wrong-model'
    elif len(complete) > 1:
        kind = 'contradictory'
    elif not complete:
        hold = 'the host reported no complete provider and model for this execution'
    else:
        hold = ('the shared canonical rules resolve no complete identity that every reading agrees with '
                f"(missing {', '.join(missing) or 'nothing'}); one complete reading is not a contradiction to accept")
    core = {'record_sha256': record['record_sha256'], 'request_id': record['request_id'], 'host_task_id': host,
            'requested': requested, 'shared_status': status, 'associations': associations,
            'resolutions': resolutions, 'canonical': canonical}
    out = dict(core, current_sources=current_sources, readings=readings, reported_providers=providers,
               reported_models=models, missing=missing, observed=observed, kind=kind, hold=hold,
               hold_code=None if not hold else 'identity_unreported' if missing or not complete
               else 'identity_indefinite', discrepancy_sha256=sha(core))
    out['instruction'] = None if hold else identity_instruction(record, out)
    return out


def identity_instruction(record, found):
    """The exact owner instruction that accepts this evidence and nothing else: the one observed model beside
    the request, or for contradictory readings every association and canonical resolution the host reported."""
    common = {'cell': record['cell_id'], 'stage': record['stage'], 'request': record['request_id'],
              'requested': pair_text(found['requested'])}
    if found['kind'] == 'wrong-model':
        return IDENTITY_INSTRUCTION.format(observed=pair_text(found['observed']), **common)
    return CONTRADICTION_INSTRUCTION.format(readings=', '.join(map(pair_text, found['associations'])),
                                            resolved=', '.join(map(pair_text, found['resolutions'])) or 'nothing',
                                            current=pair_text(found['canonical']), **common)


def identity_decision(study, evidence_row):
    """The owner decision recorded for exactly this discrepancy evidence, or None."""
    body = study.read(f"identity/{evidence_row['record_sha256']}.{evidence_row['discrepancy_sha256'][:16]}.json")
    if (body is None or body.get('discrepancy_sha256') != evidence_row['discrepancy_sha256']
            or body.get('statement') != evidence_row['instruction']):
        return None
    return body


def identity_state(study, record, job=_UNREAD):
    """`verified`; `owner-accepted-discrepancy` when the owner explicitly accepted exactly the discrepancy
    evidence the record's request shows now; otherwise the current state (mismatched, ambiguous, unreported),
    which never counts as verified. Pilots, progress, resume, coverage, carry and the shared usable-record
    resolver all read it here."""
    job = load_job(study) if job is _UNREAD else job
    now = current_identity(study, record, job)
    if now['state'] == 'verified':
        return 'verified'
    found = identity_evidence(study, record, job)
    if not found['hold'] and identity_decision(study, found) is not None:
        return 'owner-accepted-discrepancy'
    return now['state']


USABLE_IDENTITY = ('verified', 'owner-accepted-discrepancy')


def identity_problem(study, record, job=_UNREAD):
    """(state, detail) when the record's exact request has no usable identity now, else None."""
    state = identity_state(study, record, job)
    if state in USABLE_IDENTITY:
        return None
    return state, (f"the host-observed identity of request {record['request_id']} is {state}: neither verified "
                   'against the request nor accepted by the owner for the discrepancy it shows now')


# ----------------------------------------------------------------------------- pilots


def pilot_of(plan, cell):
    key = fg.target_key(cell['target'])
    return next(c for c in fg.cells(plan) if c['pilot'] and fg.target_key(c['target']) == key)


def session_failures(study, request_ids):
    out = []
    for request_id in sorted(request_ids):
        out += [row for row in session_log(study, request_id) if row['outcome'] == 'refused']
    return out


def pilot_state(study, plan, revision, pilot, stage, accepted, ledger, job=_UNREAD):
    """Gate state of one model's pilot for one stage. `passed` needs the pilot's own (or carried) result,
    usable now, with verified or owner-accepted identity now; for a journey it must also hold hands-on goals."""
    base = {'model': dict(pilot['target']),
            'pilot_cell': pilot['cell_id'], 'stage': stage}
    record, via = effective_record(study, revision, pilot['cell_id'], stage, accepted)
    if record is not None:
        # The record's own identity is reported as such below; any other problem (including a journey's first
        # impression whose identity is unusable now) fails the pilot under its own code.
        problems = [p for p in evidence.record_problems(study, record, accepted) if p['code'] != 'identity_unverified']
        ident = identity_state(study, record, job)
        if problems:
            return dict(base, state='failed', via=via, reasons=[p['code'] for p in problems])
        if ident not in ('verified', 'owner-accepted-discrepancy'):
            return dict(base, state='failed', via=via, reasons=[f'identity {ident}'])
        if stage == 'journey':
            row = evidence.journey_record(study, record['record_sha256'])
            if not row['goals']:
                return dict(base, state='unavailable', via=via, reasons=sorted({g['reason'] for g in row['gaps']}))
            return dict(base, state='passed', via=via, identity=ident, evidence_class=row['evidence_class'])
        frozen = evidence.frozen_first(study, record['record_sha256'])
        return dict(base, state='passed', via=via, identity=ident, image_delivery=frozen['image_delivery'])
    slot = f"{pilot['cell_id']}:{stage}"
    mine = {rid: row for rid, row in ledger['requests'].items() if row['slot'] == slot and row['revision'] == revision}
    if any(row['state'] in ('open', 'cancel-requested') for row in mine.values()):
        return dict(base, state='running', requests=sorted(mine))
    if stage == 'journey':
        binding = evidence.latest_binding(study, revision, pilot['cell_id'])
        if binding is not None and binding['state'] != 'verified':
            return dict(base, state='unavailable', reasons=[p['code'] for p in binding['problems']])
    failures = session_failures(study, mine)
    if failures:
        return dict(base, state='failed', reasons=sorted({f['code'] for f in failures}), requests=sorted(mine))
    return dict(base, state='pending', requests=sorted(mine))


def pilot_hold(study, plan, revision, cell, stage, accepted=None, ledger=None, job=_UNREAD):
    """The hold on starting a non-pilot cell's work for one stage now, or None once its model's pilot has
    passed that stage. The pilot can stop passing after a request was admitted, so this is checked before
    every start of new work, including the same-ID dispatch of an open request; work the host already
    started is never held by it."""
    if cell['pilot']:
        return None
    state = pilot_state(study, plan, revision, pilot_of(plan, cell), stage,
                        study.accepted() if accepted is None else accepted,
                        study.ledger() if ledger is None else ledger, job)
    if state['state'] == 'passed':
        return None
    return {'code': {'failed': 'pilot_failed', 'unavailable': 'journey_unavailable'}.get(state['state'], 'pilot_pending'),
            'pilot': state}


def pilot_gate(study, plan, revision, cell, stage, data=None):
    """Refuse a non-pilot cell until its model's pilot has passed this stage. The caller holds the lock."""
    hold = pilot_hold(study, plan, revision, cell, stage)
    if hold:
        refuse(hold['code'], f"this model's {stage} pilot has not passed ({hold['pilot']['state']}); its other {stage} "
                             'cells wait for it. Other models and other stages are not affected',
               dict(data or {}, pilot=hold['pilot']))


def host_started(job, request_id):
    """Whether the job records a host task for this request: an accepted handle or a retained conflicting one."""
    task = task_for_request(job, request_id)
    return task is not None and (handle_for(task, request_id) is not None or bool(conflicts_for(task, request_id)))


def request_hold(study, plan, revision, ledger, job, entry):
    """The pilot hold on starting one participant request of the current revision, or None."""
    stage = entry.get('stage')
    if entry['revision'] != revision or stage not in ('first-impression', 'journey'):
        return None
    cell_id = entry['slot'][:-len(stage) - 1]
    cell = next((c for c in fg.cells(plan) if c['cell_id'] == cell_id), None)
    return None if cell is None else pilot_hold(study, plan, revision, cell, stage, None, ledger, job)


def require_journey_brief(study, plan, revision, cell):
    """A journey is admitted only once its own generator brief exists and is still current."""
    rows = evidence.brief_records(study, revision, cell['cell_id'], 'journey')
    if not rows:
        refuse('journey_brief_missing', "build this journey's brief (evidence.py brief) before admitting it; an "
                                        'unbriefable journey is never charged')
    last = None
    for row in rows:
        last = evidence.verify_brief_document(study, plan, revision, {'task_id': row['task_id'], 'cell_id': cell['cell_id'],
                                                                      'stage': 'journey'}, row['document'])
        if last is None:
            return row
    refuse(last[0], f'no current journey brief for this cell: {last[1]}')


def op_pilots(args):
    """Read-only pilot gates of the current revision, per model and stage."""
    study = Study(args.state_root, args.study)
    current = study.require()
    plan = study.plan(current['revision'])['plan']
    accepted, ledger, job = study.accepted(), study.ledger(), load_job(study)
    rows = [pilot_state(study, plan, current['revision'], cell, stage, accepted, ledger, job)
            for cell in fg.cells(plan) if cell['pilot'] for stage in fg.stages_for(plan['mode'])]
    return 0, {'revision': current['revision'], 'pilots': rows,
               'note': 'A pilot is a normal matrix cell. Each stage gates only its own stage for that model.'}


# ----------------------------------------------------------------------------- identity


def op_accept_identity(args):
    """Record the owner's explicit acceptance of one recorded identity discrepancy, with both identities
    visible. It never changes the accepted record and never makes it `verified` (carry still refuses it)."""
    study = Study(args.state_root, args.study)
    study.require()
    request = load_json(args.input, 'identity decision')
    keys = {'record_sha256', 'message_ref', 'statement', 'source', 'source_sha256'}
    if not isinstance(request, dict) or set(request) != keys:
        invalid('invalid_identity_decision', f'identity decision needs exactly {sorted(keys)}')
    record = next((r for r in study.accepted() if r['record_sha256'] == request['record_sha256']), None)
    if record is None:
        refuse('record_unknown', 'no accepted participant record has this hash')
    # The discrepancy its own request shows now, which may be later than the one it was accepted with, with
    # every reading recorded for that execution: a decision covers exactly this evidence and nothing later.
    job = load_job(study)
    now = current_identity(study, record, job)
    if now['state'] == 'verified':
        refuse('identity_verified', 'this record has no identity discrepancy to accept')
    found = identity_evidence(study, record, job)
    if found['hold']:
        refuse(found['hold_code'], f"no observed execution identity to accept: {found['hold']}. It stays a visible hold; the "
                     'requested target is never taken as what ran', {'evidence': found})
    requested = record['bindings']['requested_target']
    # The only instruction that accepts this evidence names what the host reported, all of it when the readings
    # contradict each other; one naming the request as observed, or a subset, is refused with this one shown.
    expected = found['instruction']
    source = Path(text(request['source'], 'source'))
    if not source.is_absolute() or source.resolve().is_relative_to(study.job_dir.resolve()):
        invalid('invalid_identity_decision', 'the owner source must be an absolute file outside the job directory')
    try:
        raw = _regular(source)
    except (OSError, JobError) as exc:
        invalid('invalid_identity_decision', f'owner source is unreadable: {exc}')
    if digest(raw) != request['source_sha256'] or request['statement'] not in raw.decode('utf-8', 'replace'):
        invalid('invalid_identity_decision', 'statement must occur verbatim in the source with the recorded SHA-256')
    try:
        fg.affirmative(text(request['statement'], 'statement'), raw, expected)
    except StudyError as exc:
        exc.data = dict(exc.data or {}, evidence=found)
        raise
    body = {'schema_version': 1, 'record_sha256': record['record_sha256'], 'cell_id': record['cell_id'],
            'stage': record['stage'], 'recorded_identity': record['identity'], 'current_identity': now['state'],
            'identity_source': now['source'], 'requested': fg.identity_request(requested),
            'observed': found['observed'], 'discrepancy': {k: found[k] for k in (
                'kind', 'request_id', 'host_task_id', 'shared_status', 'associations', 'resolutions', 'canonical',
                'missing', 'readings', 'current_sources')}, 'discrepancy_sha256': found['discrepancy_sha256'],
            'message_ref': text(request['message_ref'], 'message_ref'), 'statement': request['statement'],
            'source': str(source), 'source_sha256': request['source_sha256']}
    body['decision_sha256'] = sha(body)
    # Keyed by the evidence hash: a later reading with a new association or another canonical resolution
    # changes the hash and the instruction, so neither this decision nor its quote covers it. An equivalent
    # reading from another source keeps the hash, so the exact same owner authority returns the recorded
    # decision as it is; its incidental readings are history, never rewritten.
    authority = ('message_ref', 'statement', 'source', 'source_sha256')
    with study.locked():
        kept = identity_decision(study, found)
        if kept is not None and all(kept.get(k) == body[k] for k in authority):
            body = kept
        else:
            study.retain(f"identity/{record['record_sha256']}.{found['discrepancy_sha256'][:16]}.json", body,
                         'a different identity decision is recorded')
    out = {'identity': 'owner-accepted-discrepancy', 'decision': body, 'verified': False}
    task = task_for_request(job, record['request_id'])
    handle = handle_for(task, record['request_id']) if task else None
    if handle is not None and (handle.get('observed_identity') or {}).get('status') == 'mismatched':
        # The same owner authority, recorded in the shared job, lets stage acceptance take exactly this mismatched
        # execution as unverified evidence. The handle, its sticky blocker and every reading stay as they are; any
        # later reading changes the binding, so this decision then covers nothing. An equivalent reading re-emits
        # the same authority for the current binding under its own ID; the earlier job decision stays as history.
        binding = identity_exception_binding(task, handle)
        decision = {'id': f"fg-identity-{body['decision_sha256'][:16]}-{sha(binding)[:16]}",
                    'quote': request['statement'], 'source': str(source), 'source_sha256': request['source_sha256'],
                    'scope': f"identity-exception:task:{task['task_id']}", 'binding': binding,
                    'reason': f"owner-accepted identity discrepancy {found['discrepancy_sha256'][:16]} "
                              f"of request {record['request_id']}; not verified"}
        out['decision_input'] = {
            'caller': {'actor': 'coordinator', 'installation_id': job['installation_id'], 'workflow': job['workflow'],
                       'package_digest': job['pins']['focus-group']['package_digest']},
            'decision': decision}
        exact = ('id', 'quote', 'source', 'source_sha256', 'scope', 'binding')
        out['decision_recorded'] = any(all(d.get(k) == decision[k] for k in exact) for d in job.get('decisions', []))
    return 0, out


# ----------------------------------------------------------------------------- ingestion


def session_log(study, request_id):
    folder = study.dir / 'sessions' / safe_id(request_id, 'request_id')
    rows = []
    if folder.is_dir():
        for n, path in enumerate(sorted(folder.glob('*.json'))):
            row = study.read(f'sessions/{request_id}/{path.name}')
            body = {k: v for k, v in row.items() if k != 'entry_sha256'}
            if (path.name != f'{n:04d}.json' or row.get('entry_sha256') != sha(body) or row.get('sequence') != n
                    or row.get('previous_sha256') != (rows[-1]['entry_sha256'] if rows else None)):
                invalid('unsafe_state', f'session log {request_id}/{path.name} breaks its append-only order')
            rows.append(row)
    return rows


def log_session(study, request_id, entry):
    """Append one ingestion outcome; an exact repeat of any earlier outcome is not appended again, so a
    redelivered response is idempotent whatever arrived in between."""
    with study.locked():
        rows = session_log(study, request_id)
        for row in rows:
            if {k: v for k, v in row.items() if k not in ('sequence', 'previous_sha256', 'entry_sha256')} == entry:
                return row
        row = dict(entry, sequence=len(rows), previous_sha256=rows[-1]['entry_sha256'] if rows else None)
        row['entry_sha256'] = sha(row)
        study.retain(f'sessions/{request_id}/{len(rows):04d}.json', row, 'session log changed concurrently')
        return row


def payload_artifact(study, task_id, result):
    """The one participant payload a worker result cites: `artifacts/tasks/<task-id>/payload.json`."""
    scope = study.job_dir / 'artifacts' / 'tasks' / task_id
    rows = []
    for item in result.get('artifacts', []):
        path = Path(item['path'])
        path = path if path.is_absolute() else study.job_dir / path
        if path.name == 'payload.json' and '..' not in path.parts and path.parent == scope:
            rows.append(dict(item, path=str(path)))
    if not rows:
        refuse('payload_missing', f'the worker result cites no artifacts/tasks/{task_id}/payload.json')
    if len(rows) > 1:
        refuse('payload_ambiguous', 'the worker result cites more than one participant payload')
    return rows[0]


def observed_from(handle, target, index):
    """Identity from the job handle's recorded host sources, under the shared canonical rules: the shared
    status `mismatched` is never softened, and `unreported` is never upgraded. Target values never fill a gap."""
    shared = (handle or {}).get('observed_identity') or {}
    provider, model = shared.get('providerInstanceId'), shared.get('model')
    observed = None
    if provider or model:
        observed = {'providerInstanceId': provider, 'model': model,
                    'source': 'job handle observed_identity: ' + ','.join(sorted(shared.get('sources', {})))}
    verdict = fg.identity_verdict(target, observed, index)
    if shared.get('status') == 'mismatched' and verdict['state'] == 'verified':
        verdict = dict(verdict, state='mismatched', reason='a recorded host source reported another provider or model')
    if shared.get('status') != 'verified' and verdict['state'] == 'verified':
        verdict = dict(verdict, state='unreported', reason='the shared identity rules did not verify this execution')
    return observed, verdict


def judge(study, request, raw, catalog):
    """Map one complete, shared-parser-ingested worker result to the participant acceptance boundary."""
    if len(raw) > TRANSPORT_LIMIT:
        refuse('oversize_transport', f'the transport exceeds the {TRANSPORT_LIMIT}-byte result limit; it is retained, '
                                     'never truncated or accepted')
    job = load_job(study)
    if job is None:
        invalid('job_missing', 'create the generic job (job-spec, job_cli.py create) before ingesting results')
    task = next((t for t in job['tasks'] if t['task_id'] == request['task_id']), None)
    meta = task_cell(study, job, task) if task else None
    if task is None or not meta:
        refuse('wrong_slot', 'the task is not a participant slot of this study job')
    if request['request_id'] not in owned_requests(task):
        refuse('wrong_slot', 'the request is not owned by this task')
    stage = task['stage_id']
    admitted = study.ledger()['requests'].get(request['request_id'])
    if admitted is None or admitted['slot'] != f"{meta['cell_id']}:{stage}":
        refuse('forged_completion', 'no admission of this study matches this request, cell and stage')
    rows = [x for x in task.get('execution_history', []) if x.get('request_id') == request['request_id']]
    if not rows:
        refuse('not_ingested_by_job', 'the shared parser has no recorded result for this request; submit the complete '
                                      'transport with job_cli.py result first')
    execution = rows[0]
    if (execution.get('completion_id') != request['completion_id']
            or (execution.get('transport_ref') or {}).get('transport_sha256') != digest(raw)):
        refuse('conflicting_duplicate', 'another response for this request was already ingested; this one is retained '
                                        'and never accepted', {'ingested_completion_id': execution.get('completion_id')})
    if execution.get('malformed') or execution.get('quarantined'):
        refuse('malformed_result', f"the shared parser refused the complete transport: {execution.get('reason')}",
               {'job_reason': execution.get('reason'), 'transport': execution.get('transport_ref')})
    result = execution['result']
    handle = handle_for(task, request['request_id'])
    if handle is None:
        refuse('execution_unobserved', 'no owned host handle is recorded for this request')
    if not settled(handle):
        refuse('execution_not_settled', 'the owned host task is not terminal without pending runs',
               {k: handle.get(k) for k in ('status', 'work_state', 'has_pending_child_runs')})
    others = [c['host_task_id'] for c in conflicts_for(task, request['request_id']) if c['reconciled'] is None]
    if others:
        refuse('execution_not_settled', 'another host task returned for this request is retained unreconciled; it may '
                                        'still be running', {'conflicting_hosts': others})
    if result['status'] != 'ready-for-acceptance':
        refuse('participant_not_ready', f"the participant returned {result['status']}; this is a session outcome, not "
                                        'product friction', {'status': result['status'], 'gaps': result['gaps']})
    plan = study.plan(admitted['revision'])['plan']
    cell = next(c for c in fg.cells(plan) if c['cell_id'] == meta['cell_id'])
    item = payload_artifact(study, task['task_id'], result)
    observed, verdict = observed_from(handle, cell['target'], catalog['index'])
    record = {'revision': admitted['revision'], 'cell_id': cell['cell_id'], 'stage': stage, 'task_id': task['task_id'],
              'request_id': request['request_id'], 'result': {'path': item['path'], 'sha256': item['sha256']},
              'observed': observed, 'predecessors': [], 'context': request.get('context')}
    data, problem = study.artifact_bytes({'task_id': task['task_id'], 'result': record['result']})
    if problem:
        refuse(problem[0], problem[1])
    if len(data) != item['bytes']:
        refuse('hash_mismatch', 'the payload byte count differs from the worker result')
    if stage == 'journey':
        record['predecessors'] = [s['result_sha256'] for s in
                                  fg.effective_first(study, admitted['revision'], cell['cell_id'], study.accepted())]
    for key in ('image_delivery', 'material_inspection'):
        if key in request:
            record[key] = request[key]
    return record, verdict


def op_ingest(args):
    """Ingest one participant execution through the shared parser's recorded verdict. The complete raw
    transport is retained first, whatever follows; every outcome is appended to that request's session log."""
    study = Study(args.state_root, args.study)
    study.require()
    request = load_json(args.input, 'ingestion request')
    keys, optional = {'task_id', 'request_id', 'completion_id', 'transport'}, {'image_delivery', 'material_inspection',
                                                                               'context'}
    if not isinstance(request, dict) or not keys <= set(request) or set(request) - keys - optional:
        invalid('invalid_ingestion', f'ingestion needs {sorted(keys)} and optional {sorted(optional)}')
    safe_id(request['task_id'], 'task_id')
    safe_id(request['request_id'], 'request_id')
    text(request['completion_id'], 'completion_id')
    now = fg.utc_now(args.now)
    try:
        raw = _regular(Path(text(request['transport'], 'transport')), max_bytes=RETAIN_LIMIT)
    except (OSError, JobError) as exc:
        invalid('transport_unreadable', f'the transport is not a readable regular file of at most {RETAIN_LIMIT} bytes: '
                                        f'{exc}')
    raw_rel = f'sessions/raw/{digest(raw)}.bin'
    with study.locked():
        try:
            fg._retain(study.dir / raw_rel, raw, 'raw transport changed')
        except JobError as exc:
            invalid('immutable_record', str(exc))
    entry = {'request_id': request['request_id'], 'task_id': request['task_id'], 'completion_id': request['completion_id'],
             'transport_sha256': digest(raw), 'transport_bytes': len(raw), 'raw': raw_rel}
    try:
        # The catalog is checked only after the raw bytes are retained, so a delayed completion offered with an
        # aged observation is kept and logged (never accepted) and can be ingested again with a fresh one.
        catalog = fg.fresh_catalog(args.capabilities, now)
        record, verdict = judge(study, request, raw, catalog)
        code, data = fg.accept_participant(study, record, verdict)
    except StudyError as exc:
        if exc.exit_code == 1:
            log_session(study, request['request_id'], dict(entry, outcome='refused', code=exc.code,
                                                            category=CATEGORIES.get(exc.code, 'evidence'),
                                                            detail=str(exc)))
            exc.data = dict(exc.data or {}, category=CATEGORIES.get(exc.code, 'evidence'), raw_retained=raw_rel,
                            product_friction=False)
        raise
    identity = data.get('identity') or next(r['identity'] for r in study.accepted()
                                             if r['record_sha256'] == data['record_sha256'])
    log_session(study, request['request_id'], dict(entry, outcome='accepted', record_sha256=data['record_sha256'],
                                                    identity=identity))
    return code, dict(data, raw_retained=raw_rel)


# ----------------------------------------------------------------------------- reconciliation


def classify_handle(study, job, task, request_id):
    """One request's lifecycle state from its recorded handle, never from a claimed status or summary."""
    if task is None:
        return {'state': 'admitted-not-prepared', 'settled': False}
    handle = handle_for(task, request_id)
    waits = {w.get('wait_id') for w in job.get('approval_waits', [])}
    question = [e.get('wait_id') for e in task.get('dispatch_history', [])
                if e.get('kind') == 'approval-wait' and e.get('wait_id') in waits
                and e.get('request_id', task['request_id']) == request_id]
    if handle is None:
        if task.get('blocked_reason') == 'uncertain_dispatch' and task['request_id'] == request_id:
            return {'state': 'dispatch-blocked', 'settled': False, 'task_id': task['task_id'],
                    'note': 'uncertain dispatch exhausted its two same-ID retries; reconcile with the host'}
        if task.get('uncertain_calls') and task['request_id'] == request_id:
            return {'state': 'dispatch-uncertain', 'settled': False, 'task_id': task['task_id'],
                    'note': 'response lost: retry delegate_task with the same clientRequestId; nothing is charged'}
        return {'state': 'prepared-not-dispatched' if prepared(study, task, request_id) else 'admitted-not-prepared',
                'settled': False, 'task_id': task['task_id']}
    host = handle.get('task_id', handle.get('host_task_id'))
    row = {'task_id': task['task_id'], 'host_task_id': host, 'host_settled': settled(handle),
           'host': {k: handle.get(k) for k in ('status', 'work_state', 'has_pending_child_runs')},
           'identity': (handle.get('observed_identity') or {}).get('status', 'unreported')}
    seen_terminal = any(e.get('host_task_id') == host and e.get('status') in TERMINAL
                        for e in task.get('reconciliation', []) + task.get('dispatch_history', []))
    if handle.get('status') not in TERMINAL:
        if seen_terminal:
            return dict(row, state='conflicting-observations', settled=False,
                        note='a terminal observation was recorded earlier; record a fresh task_status reconciliation')
        if question:
            return dict(row, state='pending-question', settled=False, waits=question)
        return dict(row, state='waiting-for-children' if handle.get('work_state') == 'waiting_for_children'
                    else 'running', settled=False)
    if handle.get('has_pending_child_runs') is not False or handle.get('work_state') in BUSY:
        return dict(row, state='pending-descendants', settled=False,
                    note='terminal parent with pending or nested runs is not quiescent')
    if question:
        return dict(row, state='pending-question', settled=False, waits=question)
    ingested = any(x.get('request_id') == request_id for x in task.get('execution_history', []))
    if handle.get('status') in ('failed', 'interrupted') or handle.get('work_state') != 'result_available':
        return dict(row, state='provider-failure', settled=True, ingested=ingested,
                    note='the host task failed or stopped: a provider or host outcome, not product friction')
    return dict(row, state='terminal-confirmed', settled=True, ingested=ingested)


def classify(study, job, task, request_id):
    """The request's state over every host task owned for it: its accepted handle and each conflicting host
    task the shared job retained for the same request. A conflict settles only through the shared job's own
    terminal reconciliation of that host task (`task-observation` kind `reconciled`)."""
    view = classify_handle(study, job, task, request_id)
    conflicts = conflicts_for(task, request_id)
    if not conflicts:
        return view
    view = dict(view, conflicting_hosts=conflicts)
    if view.get('settled') and any(c['reconciled'] is None for c in conflicts):
        view.update(state='conflicting-host', settled=False,
                    note='another host task returned for this request is retained by the job without a terminal '
                         'reconciliation; it may still be running')
    return view


NO_DISPATCH = ('prepared-not-dispatched', 'dispatch-uncertain', 'dispatch-blocked')
REDISCOVER = ('Ask the host for the task started with this clientRequestId. If it exists, record it with job_cli.py '
              'task-observation kind accepted and the same request ID (before job_cli.py cancel), then cancel it. If '
              'the host cannot resolve it, cancellation stays unconfirmed with this request named. Never dispatch it '
              'again.')
HELD = ('Do not dispatch this request while its pilot hold lasts. A prepared request may already have started (a lost '
        'response): ask the host for the task started with this clientRequestId, and if it exists record it with '
        'job_cli.py task-observation kind accepted and the same request ID; it is then reconciled and ingested as usual. '
        'The request keeps its ID, charge and reservation; once the pilot passes again it is offered for dispatch '
        'with the same ID, uncharged.')
FULL = ('Do not dispatch this request while other owned work fills the approved concurrency limit. A prepared request '
        'may already have started (a lost response): ask the host for the task started with this clientRequestId, and '
        'if it exists record it with job_cli.py task-observation kind accepted and the same request ID; it is then '
        'reconciled and ingested as usual. The request keeps its ID, charge and reservation; once owned work settles '
        'it is offered for dispatch with the same ID, uncharged.')


def reconcile_view(study, plan, ledger, job, now):
    """Pure: the state of every admitted request over all its owned host tasks, and the bounded actions for
    this wake. A request the ledger closed earlier is judged again from the current recorded view."""
    expired = now is not None and now >= fg.parse_time(plan['limits']['deadline'], 'deadline')
    stop = ledger['cancel_requested'] or expired
    rows = []
    actions = {'task_cancel': [], 'task_status': [], 'ingest': [], 'dispatch_same_request': [], 'rediscover': [],
               'launch_held': []}
    revision = None
    starts = []
    for request_id, entry in sorted(ledger['requests'].items()):
        task = task_for_request(job, request_id)
        view = classify(study, job, task, request_id) if job is not None else {'state': 'no-job', 'settled': False}
        row = dict(view, request_id=request_id, slot=entry['slot'], ledger_state=entry['state'], revision=entry['revision'])
        if view.get('settled') and not view.get('ingested') and view['host']['work_state'] == 'result_available':
            # The host holds a result: submit its complete transport with job_cli.py result, then ingest.
            actions['ingest'].append({'task_id': view['task_id'], 'request_id': request_id})
        # Owned host tasks that still need a reading, or a cancel while stopping: the accepted handle unless it
        # settled, and every conflicting host task without its own terminal reconciliation.
        primary = view.get('host_task_id') and not view.get('settled') and view['state'] != 'conflicting-host'
        hosts = [view['host_task_id']] if primary else []
        hosts += [c['host_task_id'] for c in view.get('conflicting_hosts', []) if c['reconciled'] is None]
        unconfirmed = view['state'] in NO_DISPATCH
        if entry['state'] == 'terminal':
            quiet = (view.get('settled') or view['state'] in ('no-job', 'admitted-not-prepared')
                     or unconfirmed and entry.get('terminal_kind') != 'never-prepared')
            if quiet:
                rows.append(row)
                continue
            row['note'] = 'closed earlier; a later reading disagrees, so the study is not quiescent'
            row['quiescent'] = False
            # Its closure, charge and history stay; while stopping, every owned host task is cancelled again.
            cancel = stop
        else:
            if view.get('settled'):
                row['closes'] = True
            elif stop and job is not None and view['state'] == 'admitted-not-prepared':
                # No immutable brief and no host handle exist for this request, so under the job contract
                # nothing was dispatched. It closes, charge kept; a brief or handle recorded later reopens it.
                row['closes'] = 'never-prepared'
            cancel = stop or entry['state'] == 'cancel-requested'
            if (job is not None and not hosts and not view.get('host_task_id') and not stop and entry['state'] == 'open'
                    and view['state'] in NO_DISPATCH + ('admitted-not-prepared',)):
                # Admission charged and reserved this request; it is not a standing permission to start it. The
                # same-ID dispatch is offered only while the request may start now.
                revision = revision or study.require()['revision']
                hold = request_hold(study, plan, revision, ledger, job, entry)
                if hold:
                    row['launch_hold'] = hold
                    actions['launch_held'].append({'task_id': view.get('task_id'), 'request_id': request_id,
                                                   'clientRequestId': request_id, 'state': view['state'],
                                                   'code': hold['code'], 'next': HELD})
                else:
                    starts.append(row)  # judged against concurrency once every row is built
        for host in hosts:
            actions['task_cancel' if cancel else 'task_status'].append({'host_task_id': host, 'request_id': request_id})
        if not hosts and unconfirmed and cancel:
            # A brief was prepared but no host task is recorded: a crash or a lost response may have started it.
            actions['rediscover'].append({'task_id': view['task_id'], 'request_id': request_id,
                                          'clientRequestId': request_id, 'state': view['state'], 'next': REDISCOVER})
        rows.append(row)
    unresolved = [r['request_id'] for r in rows if not (r['ledger_state'] == 'terminal' or r.get('closes'))
                  or r.get('quiescent') is False]
    result = {'requests': rows, 'actions': actions, 'deadline_expired': expired, 'unresolved': unresolved,
              'quiescent': not unresolved}
    if starts:
        # A host task of a request closed earlier can reopen after this one was admitted, so the reservation
        # admission took is not a standing permission either: the same-ID start needs free capacity now.
        occupied = occupied_work(result)
        for row in starts:
            hold = capacity_hold(occupied, plan['limits']['max_concurrency'], row['request_id'])
            if hold:
                row['launch_hold'] = hold
                actions['launch_held'].append({'task_id': row.get('task_id'), 'request_id': row['request_id'],
                                               'clientRequestId': row['request_id'], 'state': row['state'],
                                               'code': hold['code'], 'next': FULL})
            elif row['state'] in NO_DISPATCH and row['state'] != 'dispatch-blocked':
                actions['dispatch_same_request'].append({'task_id': row['task_id'], 'request_id': row['request_id']})
        actions['launch_held'].sort(key=lambda a: a['request_id'])
    return result


def occupied_work(view):
    """Occupied concurrency from the current recorded-host view: one unit per distinct unresolved owned host
    task (an unsettled accepted handle, or a retained conflicting one without its own terminal reconciliation),
    and one reservation per open or unresolved request with no recorded host task, since it may launch or may
    already have launched. A settled handle never counts, and one host task counts once however often it
    was observed."""
    units, requests = {}, set()
    for row in view['requests']:
        hosts = [row['host_task_id']] if row.get('host_task_id') and not row.get('host_settled') else []
        hosts += [c['host_task_id'] for c in row.get('conflicting_hosts', []) if c['reconciled'] is None]
        live = (row['ledger_state'] in ('open', 'cancel-requested') and not row.get('closes')
                or row['request_id'] in view['unresolved'])
        if hosts:
            for host in hosts:
                units.setdefault(('host', host), row['request_id'])
        elif live and not row.get('host_task_id'):
            units[('reservation', row['request_id'])] = row['request_id']
        else:
            continue
        requests.add(row['request_id'])
    work = [{'kind': kind, 'host_task_id': key if kind == 'host' else None, 'request_id': rid}
            for (kind, key), rid in sorted(units.items())]
    return {'count': len(work), 'work': work, 'requests': sorted(requests)}


def capacity_hold(occupied, limit, request_id):
    """Pure: the concurrency hold on the same-ID start of an open request with no recorded host task, or None.
    Starting it uses its own reservation, so that one unit is left out once; every other unit counts."""
    own = {'kind': 'reservation', 'host_task_id': None, 'request_id': request_id}
    others = [w for w in occupied['work'] if w != own]
    if len(others) < limit:
        return None
    return {'code': 'concurrency_limit', 'max_concurrency': limit, 'occupied_count': len(others),
            'occupied': sorted({w['request_id'] for w in others}), 'occupied_work': others,
            'excluded': own if len(others) < len(occupied['work']) else None}


def reconcile(study, now):
    """Apply one bounded reconciliation pass under the caller's lock: confirmed terminal requests close (freeing
    concurrency, never refunding), and past the deadline or after cancel every open request becomes
    cancel-requested. Repeating it with the same recorded state changes nothing."""
    current = study.require()
    plan = study.plan(current['revision'])['plan']
    ledger = study.ledger()
    job = load_job(study)
    view = reconcile_view(study, plan, ledger, job, now)
    changed = False
    if view['deadline_expired'] and not ledger['deadline_expired']:
        ledger['deadline_expired'] = changed = True
    for row in view['requests']:
        entry = ledger['requests'][row['request_id']]
        if row.get('closes') == 'never-prepared':
            entry.update(state='terminal', terminal_status='never-dispatched', terminal_kind='never-prepared',
                         terminal_source='job store: no immutable brief or host handle for this request')
            changed = True
        elif row.get('closes'):
            entry.update(state='terminal', terminal_status=row['host']['status'], terminal_source='job handle',
                         terminal_work_state=row['host']['work_state'], terminal_kind=row['state'])
            changed = True
        elif entry['state'] == 'open' and (ledger['cancel_requested'] or view['deadline_expired']):
            entry['state'] = 'cancel-requested'
            changed = True
    if changed:
        study.write('ledger.json', ledger)
    return reconcile_view(study, plan, ledger, job, now)


def cancellation_confirmed(ledger, view):
    """Cancellation is confirmed only by the current recorded-host view, never by `cancel_requested` or a
    request the ledger closed earlier: every owned request must be quiescent now."""
    return ledger['cancel_requested'] and view['quiescent']


def op_reconcile(args):
    study = Study(args.state_root, args.study)
    now = fg.utc_now(args.now)
    with study.locked():
        view = reconcile(study, now)
        ledger = study.ledger()
    return 0, dict(view, cancel_requested=ledger['cancel_requested'],
                   cancellation_confirmed=cancellation_confirmed(ledger, view),
                   complete=False if view['unresolved'] else None, dispatched=0,
                   next='yield: end the turn; the next T3 completion notification wakes the coordinator')


# ----------------------------------------------------------------------------- resume


def slot_view(study, plan, revision, cell, stage, accepted, ledger, job, now, catalog, view=None):
    task = task_for_slot(study, job, cell['cell_id'], stage)
    record, via = effective_record(study, revision, cell['cell_id'], stage, accepted)
    row = {'slot': f"{cell['cell_id']}:{stage}", 'task_id': task['task_id'] if task else None, 'pilot': cell['pilot']}
    if record is not None:
        problems = evidence.record_problems(study, record, accepted)
        return dict(row, state='accepted' if not problems else 'accepted-unusable', via=via,
                    identity=identity_state(study, record, job), record_sha256=record['record_sha256'],
                    problems=[p['code'] for p in problems])
    live = [rid for rid, r in ledger['requests'].items()
            if r['slot'] == row['slot'] and r['revision'] == revision and r['state'] in ('open', 'cancel-requested')]
    if live:
        unstarted = [rid for rid in live if ledger['requests'][rid]['state'] == 'open' and not host_started(job, rid)]
        hold = pilot_hold(study, plan, revision, cell, stage, accepted, ledger, job) if unstarted else None
        if hold and job is not None and len(unstarted) == len(live):
            # Admitted while the pilot passed, never started, and the pilot no longer passes: held, not in flight.
            return dict(row, state='held', code=hold['code'], pilot=hold['pilot'], requests=sorted(live),
                        next=HELD)
        full = {r['request_id']: r['launch_hold'] for r in (view or {}).get('requests', [])
                if r['request_id'] in unstarted and r.get('launch_hold', {}).get('code') == 'concurrency_limit'}
        if full and job is not None and len(full) == len(live):
            # Admitted while capacity was free, never started, and other owned work fills it now.
            hold = full[min(full)]
            return dict(row, state='held', code=hold['code'], capacity=hold, requests=sorted(live), next=FULL)
        return dict(row, state='in-flight', requests=sorted(live), next='not dispatched again')
    if task is None:
        return dict(row, state='slot-undeclared', next='add the slot with journey-slots once its brief exists'
                    if stage == 'journey' else 'declare the slot in the job')
    request_id = task['request_id']
    # A request already admitted, or one whose brief was prepared under a contract a plan revision has since
    # replaced, needs the job's charged retry and a new request ID.
    retry = request_id in ledger['requests'] or bool(prepared(study, task, request_id)
                                                     and (task.get('inputs_stale') or task.get('status') == 'stale'))
    probe = f"{task['task_id']}-resume-probe" if retry else request_id
    target = dict(cell['target'])
    attempt = {'revision': revision, 'request_id': probe, 'stage': stage, 'cell_id': cell['cell_id'], 'target': target,
               'material_classes': sorted(fg.required_classes(stage, plan['mode'])), 'purpose': 'resume'}
    try:
        _, out = fg.admission(study, attempt, now, catalog, charge=False)
    except StudyError as exc:
        if exc.exit_code != 1:
            raise
        held = dict(row, state='held', code=exc.code, reason=str(exc))
        if exc.code in ('job_revision_stale', 'job_slot_stale', 'job_slot_missing'):
            held['next'] = 'lifecycle.py job-revision, then job_cli.py decision and plan-revision'
        return held
    if retry:
        return dict(row, state='dispatchable', pool=out['pool'],
                    next='charged retry: job_cli.py retry, then admit the new request ID it records')
    return dict(row, state='dispatchable', pool=out['pool'], request_id=request_id,
                next='admit this request ID, then prepare and dispatch it')


def op_resume(args):
    """Reconcile recorded tasks and source bindings first, then list only unfilled valid slots inside the
    remaining limits. It admits, charges and dispatches nothing."""
    study = Study(args.state_root, args.study)
    now = fg.utc_now(args.now)
    catalog = fg.fresh_catalog(args.capabilities, now)
    with study.locked():
        reconciled = reconcile(study, now)
        current = study.require()
        revision = current['revision']
        plan = study.plan(revision)['plan']
        blockers = []
        try:
            fg.preflight(study, now, catalog)
        except StudyError as exc:
            if exc.exit_code != 1:
                raise
            blockers.append({'code': exc.code, 'reason': str(exc), 'data': exc.data})
        ledger, accepted, job = study.ledger(), study.accepted(), load_job(study)
        slots = []
        for cell in fg.cells(plan):
            for stage in fg.stages_for(plan['mode']):
                if blockers:
                    record, via = effective_record(study, revision, cell['cell_id'], stage, accepted) \
                        if blockers[0]['code'] != 'carry_invalid' else (None, None)
                    slots.append({'slot': f"{cell['cell_id']}:{stage}", 'state': 'accepted' if record else 'held',
                                  'code': None if record else blockers[0]['code']})
                    continue
                slots.append(slot_view(study, plan, revision, cell, stage, accepted, ledger, job, now, catalog,
                                       reconciled))
        roles = []
        for role in ('analysis', 'review'):
            slot = f'{role}:{role}'
            mine = {rid: r for rid, r in ledger['requests'].items() if r['slot'] == slot and r['revision'] == revision}
            live = sorted(rid for rid, r in mine.items() if r['state'] in ('open', 'cancel-requested'))
            roles.append({'slot': slot, 'state': 'in-flight' if live else 'executed' if mine else 'pending',
                          'requests': sorted(mine), 'acceptance': 'decided by the study validator, not by resume'})
    unresolved = sorted(set(reconciled['unresolved']) | {r for s in roles for r in s['requests'] if s['state'] == 'in-flight'})
    capture = all(s['state'] == 'accepted' for s in slots if s['slot'].endswith(':first-impression'))
    return 0, {'revision': revision, 'reconciliation': reconciled, 'blockers': blockers, 'slots': slots,
               'later_stages': roles, 'charged': ledger['charged'], 'charged_tasks': sum(ledger['charged'].values()),
               'unresolved_owned_work': unresolved, 'capture_scope_filled': capture,
               'combined_scope_complete': False if plan['mode'] == 'capture-only' else None,
               'complete': False, 'dispatched': 0,
               'note': 'Completion is decided by the study validator; resume never claims it, and never while owned '
                       'work is unresolved.'}


# ----------------------------------------------------------------------------- journey slots


def op_journey_slots(args):
    """Inputs for the supported generic route that adds journey slots after `job-spec --defer-journeys`: one
    owner decision whose quote and source are the approval of this exact study revision, and one job plan
    revision adding only undeclared journey slots with their current generated briefs. Existing slots,
    accepted results, counters and briefs are untouched; the shared helper records both."""
    study = Study(args.state_root, args.study)
    current = study.require()
    revision = current['revision']
    plan = study.plan(revision)['plan']
    job = load_job(study)
    if job is None:
        invalid('job_missing', 'create the job first')
    if plan['mode'] != 'combined':
        refuse('outside_matrix', 'a capture-only revision declares no journeys')
    if job_revision_problem(job, revision):
        refuse('stale_revision', "the job was built for another study revision; a revision's journeys join only its "
                                 'own job. Run lifecycle.py job-revision first')
    approval = fg.approval_state(study.approvals(revision), revision, fg.ceiling(plan, study.ledger()))
    if approval['state'] != 'approved':
        refuse('unapproved_revision', 'journey slots are added only under an approval in force for this revision')
    documents = load_json(args.documents, 'journey briefs')
    if not isinstance(documents, dict):
        invalid('invalid_documents', 'documents map journey task IDs to {path, sha256}')
    declared = {t['task_id'] for t in job['tasks']}
    by_cell = {c['cell_id']: c for c in fg.cells(plan)}
    order = {task_id: by_cell[cell_id] for (cell_id, stage), task_id in slot_task_ids(study, job, plan).items()
             if stage == 'journey'}
    added = []
    for task_id, document in sorted(documents.items()):
        cell = order.get(task_id)
        if cell is None:
            invalid('invalid_documents', f'{task_id} is not a journey task of this revision')
        if task_id in declared:
            continue
        if not (isinstance(document, dict) and set(document) == {'path', 'sha256'}):
            invalid('invalid_documents', f'{task_id} needs a document {{path, sha256}}')
        problem = evidence.verify_brief_document(study, plan, revision, {'task_id': task_id, 'cell_id': cell['cell_id'],
                                                                         'stage': 'journey'}, document)
        if problem:
            refuse(problem[0], f'{task_id}: {problem[1]}')
        added.append(new_slot(task_id, 'journey', cell['target'], document, plan))
    if not added:
        return 0, {'added': [], 'note': 'every briefed journey slot is already declared', 'dispatched': 0}
    last, inputs = owner_inputs(study, job, revision, 'journeys', {'tasks': job['tasks'] + added})
    return 0, dict(**inputs, added=[t['task_id'] for t in added], approval_record_sha256=last['record_sha256'],
                   dispatched=0, note='Record decision_input with job_cli.py decision, then plan_revision_input with '
                                      'job_cli.py plan-revision. The study budget and every existing slot are unchanged.')


# ----------------------------------------------------------------------------- job revision


def job_revision_problem(job, revision):
    """None when the generic job's stage contracts and authority name this study revision; otherwise what
    still names an earlier one. Updating only the study plan never updates the job's preparation."""
    if job is None:
        return None
    stale = sorted(s['id'] for s in job['stages'] if s.get('revision') != revision
                   or (s.get('validator_contract') or {}).get('study_revision') != revision)
    authority = (job.get('authorization') or {}).get('study_revision')
    if not stale and authority == revision:
        return None
    return {'stages': stale, 'job_authorization_revision': authority, 'study_revision': revision,
            'next': 'lifecycle.py job-revision, then job_cli.py decision and plan-revision'}


def slot_contract_problem(study, job, revision, plan, stage, cell=None):
    """(code, reason) when the job slot that would run this admission does not carry the current revision's
    target and generated brief; None otherwise or before a job exists. The caller holds the lock."""
    if job is None:
        return None
    if cell is None:  # analysis or review
        task = next((t for t in job['tasks'] if t['task_id'] == stage), None)
        if task is not None and task.get('target') != plan[stage]:
            return 'job_slot_stale', f'the job {stage} slot still names an earlier target'
        if task is not None and stage == 'analysis':
            # The analyst runs only on this revision's frozen inputs, still equal to the accepted evidence (FG-4).
            return fg.report_module().analysis_slot_problem(study, job, revision, task)
        if task is not None and stage == 'review':
            # A bound review runs only on the current render of the current synthesis (FG-4).
            return fg.report_module().review_slot_problem(study, job, revision, task)
        return None
    task = task_for_slot(study, job, cell['cell_id'], stage)
    if task is None:
        return 'job_slot_missing', f"the job declares no {stage} slot for this cell; nothing could run this admission"
    current = any((r['task_id'], r['document']) == (task['task_id'], task.get('document'))
                  for r in evidence.brief_records(study, revision, cell['cell_id'], stage))
    if (task.get('target') != cell['target'] or not current
            or task.get('context_files') != evidence.material_context_files(plan)):
        return 'job_slot_stale', (f"job slot {task['task_id']} still carries an earlier revision's brief or target; "
                                  'it is held until lifecycle.py job-revision records the current one')
    return None


def new_slot(task_id, stage, target, document, plan):
    return {'task_id': task_id, 'stage_id': stage, 'logical_slot_id': task_id, 'request_id': f'{task_id}-r0',
            'worker_id': 'focus-group/participant', 'dependency_key': 'focus-group', 'target': target,
            'write_scope': {'mode': 'worker-evidence', 'path': f'artifacts/tasks/{task_id}'},
            'context_policy': 'document-only', 'document': document,
            'context_files': evidence.material_context_files(plan), 'max_followups': 0}


def owner_inputs(study, job, revision, kind, new_plan):
    """The owner decision and plan revision that record `new_plan` in the shared job. The decision quotes the
    owner's approval of this exact study revision; nothing here asks the owner again."""
    record = fg.planning_gate(study, revision, run=True)
    plan = study.plan(revision)['plan']
    for task in new_plan.get('tasks', []):
        if not _unsettled(job, task) and not task.get('selection_binding'):
            task['selection_binding'] = fg.planning_module().task_binding(plan, record, task)
    # The generic revision route retains producing choices for already executing slots.
    selected = record['selection']
    if selected['selection_sha256'] != job.get('model_selection_sha256'):
        new_plan.update(model_selection=selected, model_selection_sha256=selected['selection_sha256'],
                        invocation_id=record['invocation_id'], scope_id=record['scope_id'])
    stages = new_plan.setdefault('stages', copy.deepcopy(job['stages']))
    for stage in stages:
        stage.setdefault('resources', {}).update(focus_group_plan=fg.planning_module().descriptor(study, revision),
                                                focus_group_admission=record)
    last = study.approvals(revision)[-1]
    tag = sha({'revision': revision, 'kind': kind, 'plan': new_plan})[:16]
    revision_id = decision_id = f'fg-{kind}-{tag}'
    caller = {'actor': 'coordinator', 'installation_id': job['installation_id'], 'workflow': job['workflow'],
              'package_digest': job['pins']['focus-group']['package_digest']}
    decision = {'id': decision_id, 'quote': last['statement'], 'source': last['source'],
                'source_sha256': last['source_sha256'], 'scope': f'plan:{revision_id}',
                'reason': f'{kind} of approved focus-group revision {revision[:12]}'}
    return last, {'decision_input': {'caller': caller, 'decision': decision},
                  'plan_revision_input': {'caller': caller, 'revision': {'id': revision_id, 'owner_decision_id': decision_id},
                                          'new_plan': new_plan}}


def op_job_revision(args):
    """Inputs for the supported generic route that moves the job's preparation to the current approved study
    revision: stage contracts, authority, policy and every participant slot's target and generated brief.
    Settled slots take the brief supplied for them; a slot with unsettled host work keeps its contract (held)
    until it settles. Requests, handles, execution history, charges and immutable briefs are never rewritten;
    the shared plan revision stales the stages it changes, so an executed slot runs again only after a
    charged job_cli.py retry and a new admission. Read-only: it records nothing itself."""
    study = Study(args.state_root, args.study)
    current = study.require()
    revision = current['revision']
    plan = study.plan(revision)['plan']
    job = load_job(study)
    if job is None:
        invalid('job_missing', 'create the job first')
    ledger, accepted = study.ledger(), study.accepted()
    if fg.approval_state(study.approvals(revision), revision, fg.ceiling(plan, ledger))['state'] != 'approved':
        refuse('unapproved_revision', 'the job follows only a study revision with an approval in force')
    documents = load_json(args.documents, 'participant briefs') if args.documents else {}
    if not isinstance(documents, dict):
        invalid('invalid_documents', 'documents map participant task IDs to {path, sha256}')
    ids = slot_task_ids(study, job, plan)
    cell_of = {c['cell_id']: c for c in fg.cells(plan)}
    slot_of = {task_id: (cell_of[cell_id], stage) for (cell_id, stage), task_id in ids.items()}
    unknown = sorted(set(documents) - set(slot_of))
    if unknown:
        invalid('invalid_documents', f'{unknown} are not participant slots of this revision; use the task IDs listed '
                                     'by job-revision without --documents')
    tasks = copy.deepcopy(job['tasks'])
    index = {t['task_id']: t for t in tasks}
    slots = []
    for task_id, (cell, stage) in sorted(slot_of.items(), key=lambda kv: kv[0]):
        task, document = index.get(task_id), documents.get(task_id)
        row = {'slot': f"{cell['cell_id']}:{stage}", 'task_id': task_id}
        if document is not None:
            if not (isinstance(document, dict) and set(document) == {'path', 'sha256'}):
                invalid('invalid_documents', f'{task_id} needs a document {{path, sha256}}')
            problem = evidence.verify_brief_document(study, plan, revision, {'task_id': task_id, 'cell_id': cell['cell_id'],
                                                                             'stage': stage}, document)
            if problem:
                refuse(problem[0], f'{task_id}: {problem[1]}')
        filled = effective_record(study, revision, cell['cell_id'], stage, accepted)[0] is not None
        stale = slot_contract_problem(study, job, revision, plan, stage, cell) if task is not None else ('missing',)
        if task is not None and stale and _unsettled(job, job_task(job, task_id)):
            row.update(state='held-live', reason=_unsettled(job, job_task(job, task_id)))
        elif document is not None and (task is None or task.get('document') != document or stale):
            if task is None:
                tasks.append(new_slot(task_id, stage, cell['target'], document, plan))
                row['state'] = 'added'
            else:
                task.update(target=cell['target'], document=document, context_files=evidence.material_context_files(plan))
                row['state'] = 'updated'
        elif task is not None and not stale:
            row['state'] = 'current'
        else:
            row['state'] = 'filled' if filled else 'needs-brief'
            if not filled:
                row['next'] = f'evidence.py brief for task {task_id}, then job-revision with --documents'
        slots.append(row)
    for kind in ('analysis', 'review'):
        task = index.get(kind)
        if task is not None and task.get('target') != plan[kind]:
            if _unsettled(job, job_task(job, kind)):
                slots.append({'slot': f'{kind}:{kind}', 'task_id': kind, 'state': 'held-live'})
            else:
                task['target'] = plan[kind]
                slots.append({'slot': f'{kind}:{kind}', 'task_id': kind, 'state': 'updated'})
    requirements, wanted = fg.job_contract(plan, revision)
    stages = copy.deepcopy(job['stages'])
    for spec in wanted:
        stage = next((s for s in stages if s['id'] == spec['id']), None)
        if stage is None:
            stages.insert(len(stages) - 2, dict(spec, status='pending'))
        else:
            stage.update({k: spec[k] for k in ('revision', 'validator_contract', 'depends_on', 'requirements')})
    for stage in stages:  # a stage outside this revision's mode stays declared, on this revision's contract
        stage['revision'] = revision
        stage['validator_contract'] = dict(stage.get('validator_contract') or {}, study_revision=revision)
    new_plan = {'tasks': tasks, 'stages': stages, 'requirements': {**job['requirements'], **requirements},
                'authorization': dict(job['authorization'], study_revision=revision, sharing=plan['sharing']),
                'policy': dict(job['policy'], max_repair_cycles=plan['limits']['max_attempts_per_slot'] - 1,
                               max_live_workers=plan['limits']['max_concurrency'])}
    out = {'revision': revision, 'slots': slots, 'dispatched': 0,
           'job_revision': job_revision_problem(job, revision)}
    if all(new_plan[key] == job.get(key) for key in new_plan):
        return 0, dict(out, changed=False, note='the job already prepares this revision for every supplied brief')
    last, inputs = owner_inputs(study, job, revision, 'revision', new_plan)
    return 0, dict(out, **inputs, changed=True, approval_record_sha256=last['record_sha256'],
                   note='Record decision_input with job_cli.py decision, then plan_revision_input with job_cli.py '
                        'plan-revision. Requests, handles, accepted results, charges and earlier briefs are unchanged; '
                        'held slots join a later job-revision once they settle.')


def job_task(job, task_id):
    return next(t for t in job['tasks'] if t['task_id'] == task_id)


# ----------------------------------------------------------------------------- progress


def op_progress(args):
    """Read-only lifecycle summary: pilots, identity, session failures and unresolved owned work."""
    study = Study(args.state_root, args.study)
    current = study.require()
    revision = current['revision']
    plan = study.plan(revision)['plan']
    ledger, accepted, job = study.ledger(), study.accepted(), load_job(study)
    view = reconcile_view(study, plan, ledger, job, None)
    cells = []
    for cell in fg.cells(plan):
        row = {'cell_id': cell['cell_id'], 'pilot': cell['pilot'], 'requested': cell['target']}
        for stage in fg.stages_for(plan['mode']):
            record, via = effective_record(study, revision, cell['cell_id'], stage, accepted)
            if record is None:
                row[stage] = {'state': 'unfilled'}
                continue
            ident, now = identity_state(study, record, job), current_identity(study, record, job)
            problems = evidence.record_problems(study, record, accepted)
            # The identity its request shows now, beside the immutable identity it was accepted with.
            row[stage] = {'state': 'unusable' if problems else 'accepted', 'problems': [p['code'] for p in problems],
                          'via': via, 'identity': ident, 'observed': now['observed'],
                          'accepted_identity': record.get('identity'), 'accepted_observed': record.get('observed'),
                          'verified_coverage': ident == 'verified'}
            if ident != 'verified':
                # Everything the owner must see before deciding: every recorded reading, the hold when there is no
                # observed identity to accept, and the exact instruction a decision on this evidence must be.
                row[stage]['identity_evidence'] = identity_evidence(study, record, job)
        cells.append(row)
    failures = session_failures(study, ledger['requests'])
    pilots = [pilot_state(study, plan, revision, c, s, accepted, ledger, job)
              for c in fg.cells(plan) if c['pilot'] for s in fg.stages_for(plan['mode'])]
    return 0, {'revision': revision, 'cells': cells, 'pilots': pilots,
               'session_failures': [{k: f[k] for k in ('request_id', 'code', 'category', 'detail')} for f in failures],
               'unresolved_owned_work': view['unresolved'], 'quiescent': view['quiescent'],
               'cancel_requested': ledger['cancel_requested'], 'complete': False,
               'note': 'Session, provider and capability failures are not product friction. Only verified identity '
                       'counts as verified coverage.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('pilots', 'accept-identity', 'ingest', 'reconcile', 'resume', 'journey-slots', 'job-revision',
                 'progress'):
        command = sub.add_parser(name)
        command.add_argument('--state-root', required=True)
        command.add_argument('--study', required=True)
        if name in ('accept-identity', 'ingest'):
            command.add_argument('--input', required=True)
        if name in ('ingest', 'reconcile', 'resume'):
            command.add_argument('--now')
        if name in ('ingest', 'resume'):
            command.add_argument('--capabilities', required=True)
        if name == 'journey-slots':
            command.add_argument('--documents', required=True)
        if name == 'job-revision':
            command.add_argument('--documents')
    args = parser.parse_args(argv)
    handler = {'pilots': op_pilots, 'accept-identity': op_accept_identity, 'ingest': op_ingest,
               'reconcile': op_reconcile, 'resume': op_resume, 'journey-slots': op_journey_slots,
               'job-revision': op_job_revision, 'progress': op_progress}[args.command]
    try:
        code, data = handler(args)
        print(json.dumps({'ok': code == 0, 'op': args.command, 'data': data}, sort_keys=True))
        return code
    except StudyError as exc:
        print(json.dumps({'ok': False, 'op': args.command, 'error': {'code': exc.code, 'message': str(exc)},
                          'data': exc.data}, sort_keys=True))
        return exc.exit_code
    except JobError as exc:
        print(json.dumps({'ok': False, 'op': args.command, 'error': {'code': 'unsafe_state', 'message': str(exc)}}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
