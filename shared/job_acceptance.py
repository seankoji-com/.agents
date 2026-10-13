"""Current acceptance from immutable adapters, bound inputs and dependency chains."""
from __future__ import annotations

import hashlib
import subprocess
import os, selectors, signal, time
from core.jobs.results import parse_result
from pathlib import Path

from core.jobs.store import JobError, _regular, _retain, canonical, digest, strict_load, _authorize
from shared.job_coordinator import verify_all_pins
from shared.error_codes import code_of
from core.jobs import _owner_current, _live_handles, _open_dispatch, _uningested

class AcceptanceError(ValueError):
    pass

ADAPTERS = {
    'imps': 'validate_stage.py',
    'ape': 'validate_report.py',
    'babysitter': 'validate_pr.py',
    'elephant-goldfish': 'validate_document.py',
    'agent-tuneup': 'validate_audit.py',
}

def _caller(job, caller):
    try:
        _authorize(job, caller, 'acceptance')
    except JobError as exc:
        raise AcceptanceError(str(exc)) from exc

def _semantic_binding(job, stage):
    contract = {key: job.get(key) for key in (
        'installation_id', 'workflow', 'objective', 'requirements', 'authorization',
        'constraints', 'snapshot', 'dependencies', 'pins', 'policy')}
    contract['dependencies'] = sorted(job['dependencies'], key=lambda row: row['key'])
    contract['stage'] = {key: value for key, value in stage.items()
                         if key not in ('status', 'attempts', 'acceptance', 'acceptance_history', 'acceptance_runs', 'validated_cycle', 'cycle')}
    for key in ('depends_on', 'requirements'):
        contract['stage'][key] = sorted(stage.get(key, []))
    contract['predecessors'] = [
        {'id': other['id'], 'acceptance': other.get('acceptance'), 'outputs': other.get('outputs', [])}
        for other in job['stages'] if other['id'] in stage.get('depends_on', [])]
    if 'criteria' in contract['stage']:
        contract['stage']['criteria'] = sorted(contract['stage']['criteria'], key=canonical)
    contract['slots'] = [task for task in job['tasks'] if task['stage_id'] == stage['id']]
    return digest(canonical(contract))

def _stage(job, stage_id):
    found = next((stage for stage in job['stages'] if stage['id'] == stage_id), None)
    if found is None:
        raise AcceptanceError('unknown stage')
    return found

def _pending(job, stage):
    for task in job['tasks']:
        if task['stage_id'] != stage['id']:
            continue
        if task.get('status') in ('running', 'awaiting-followup'):
            return True
        # Same rule as core: terminal, no pending child runs and work_state result_available.
        if _live_handles(task) or _open_dispatch(task) or _uningested(task):
            return True
    current = {task['task_id'] for task in job['tasks']}
    if any(b.get('kind') == 'conflicting-host-handle' and not b.get('reconciled') and b.get('task_id') not in current for b in job.get('blockers', [])):
        return True
    return bool(job.get('approval_waits'))

def _unchanged(store, generation, stage_ids):
    """Reread after validators: same generation, valid pins, no live work, intact local chain."""
    job = verify_all_pins(store)
    if digest(canonical(job)) != generation:
        raise AcceptanceError('job changed during validator execution')
    for stage_id in stage_ids:
        stage = _stage(job, stage_id)
        if _pending(job, stage):
            raise AcceptanceError('owned tasks or approval waits became live during validator execution')
        _ready_slots(store, job, stage)
        checked = validate_stage(store, stage_id, run_validator=False)
        if not checked.get('accepted'):
            raise AcceptanceError('acceptance chain changed during validator execution: ' + checked.get('reason', stage_id))
    return job

def _check_slots(store, job, stage, task_ids=None, require_reviews=True):
    if not any(t['stage_id'] == stage['id'] for t in job['tasks']) and stage.get('execution_mode') != 'direct':
        raise AcceptanceError('zero-worker stage requires explicit direct execution mode')
    for task in job['tasks']:
        if task['stage_id'] != stage['id'] or task_ids is not None and task['task_id'] not in task_ids:
            continue
        if task.get('inputs_stale'):
            raise AcceptanceError('task inputs changed while its owned handle remained live; charged repair required')
        owned = task.get('handles', []) + task.get('followups', [])
        if task.get('blocked_reason') or task.get('uncertain_calls') and not any(h.get('request_id') == task['request_id'] for h in owned):
            raise AcceptanceError('uncertain_dispatch: uncertain dispatch lacks an authoritative host observation for the current request')
        if _open_dispatch(task):
            raise AcceptanceError(_open_dispatch(task))
        if any(b.get('kind') == 'conflicting-host-handle' and b.get('task_id') == task['task_id'] and not b.get('reconciled') for b in job.get('blockers', [])):
            raise AcceptanceError('a conflicting host handle remains unreconciled in job blockers')
        if _live_handles(task):
            raise AcceptanceError('every owned host handle must be terminal with work_state result_available and no pending runs')
        if _uningested(task):
            raise AcceptanceError('an unread terminal result is still an open obligation; ingest it before acceptance')
        if task.get('status') != 'awaiting-acceptance':
            raise AcceptanceError('declared task slot lacks a current ready result: ' + task['task_id'])
        for disposition in task.get('finding_dispositions', []):
            reference = disposition.get('evidence')
            if reference is not None:
                if not isinstance(reference, dict) or Path(reference.get('path', '')).parent != store.path / 'dispositions':
                    raise AcceptanceError('disposition evidence must be a frozen coordinator reference')
                content = _regular(Path(reference['path']), max_bytes=job['policy']['max_artifact_bytes'])
                if digest(content) != reference.get('sha256') or len(content) != reference.get('bytes'):
                    raise AcceptanceError('disposition evidence changed')
            if disposition.get('finding', {}).get('severity') in ('blocker', 'major') and (disposition.get('disposition') not in ('fixed', 'rejected') or not disposition.get('evidence')):
                raise AcceptanceError('unresolved retained blocker or major finding')
        brief = task.get('brief', {})
        raw = _regular(Path(brief['path']), max_bytes=job['policy']['max_artifact_bytes'])
        if digest(raw) != brief['sha256']:
            raise AcceptanceError('immutable brief bytes changed')
        assigned = strict_load(raw)
        effective = assigned.pop('effective_brief_sha256')
        if digest(canonical(assigned)) != effective or effective != brief['effective_brief_sha256']:
            raise AcceptanceError('brief content correlation changed')
        expected = {key: brief[key] for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256')}
        expected.update(role=assigned.get('role', 'worker'), revision=brief.get('revision'), binding=brief.get('snapshot'), task_id=task['task_id'], requirements=[r['id'] for r in assigned['requirements']], owner_waivers=[d for d in job['decisions'] if d.get('scope') == 'waiver:' + task['task_id'] and _owner_current(d, job['policy']['max_artifact_bytes'])], waivable_requirements=job['policy'].get('waivable_requirements', []))
        if brief['request_id'] != task['request_id'] or brief.get('revision') != (None if task.get('context_policy') == 'document-only' else stage.get('revision')):
            raise AcceptanceError('ready result belongs to a superseded request or revision')
        reference = task['result_ref']
        transport = Path(reference['transport_path'])
        if transport != store.path / 'results' / (task['request_id'] + '.json'):
            raise AcceptanceError('result transport is outside its immutable request path')
        transport_raw = _regular(transport, max_bytes=32768)
        parsed = parse_result(transport_raw, expected, store.path if task.get('write_scope', {}).get('mode') == 'worker-evidence' else None, job['policy']['max_artifact_bytes'])
        if digest(transport_raw) != reference['transport_sha256'] or parsed['sha256'] != reference['sha256'] or parsed['result']['status'] != 'ready-for-acceptance':
            raise AcceptanceError('current ready result bytes differ')
        verdict = parsed['result']['review_verdict']
        if verdict in ('adverse', 'unavailable') or task.get('role') == 'review' and verdict != 'approve':
            raise AcceptanceError('required current review approval is absent or adverse')
        execution = next((h for h in task.get('execution_history', []) if h.get('request_id') == task['request_id']), None)
        if not execution or execution.get('result') != parsed['result'] or execution.get('sha256') != parsed['sha256']:
            raise AcceptanceError('ready result was not ingested for this execution')
        for finding in parsed['result']['findings']:
            disposition = next((d for d in task.get('finding_dispositions', []) if d.get('finding_id') == finding['id'] and d.get('finding') == finding), {})
            if finding['severity'] in ('blocker', 'major') and (disposition.get('disposition') not in ('fixed', 'rejected') or not disposition.get('evidence')):
                raise AcceptanceError('unresolved blocker or major finding')
        for artifact in parsed['result']['artifacts']:
            rel = Path(artifact['path'])
            if rel.as_posix() != artifact['path'] or rel.is_absolute() or rel.parts[:3] != ('artifacts', 'tasks', task['task_id']) or '..' in rel.parts:
                raise AcceptanceError('result evidence escapes its task subtree')
            content = _regular(store.path / rel, max_bytes=job['policy']['max_artifact_bytes'])
            if digest(content) != artifact['sha256'] or len(content) != artifact['bytes']:
                raise AcceptanceError('worker evidence changed after ingestion')
    if require_reviews:
        for task in (t for t in job['tasks'] if t['stage_id'] == stage['id']):
            if task.get('role') == 'review':
                assigned = strict_load(_regular(Path(task['brief']['path']), max_bytes=job['policy']['max_artifact_bytes']))
                if assigned.get('review_inputs') != review_inputs(store, job, task):
                    raise AcceptanceError('review approval is not bound to the current reviewed executions')
                if 'reviewed_documents' in task:
                    review_handle(task)  # the reviewer's own completed owned host execution
            if task.get('review_required'):
                reviewers = task.get('review_task_ids', [])
                if not reviewers:
                    raise AcceptanceError('required_review_unavailable: required independent review task IDs are absent')
                for task_id in reviewers:
                    reviewer = next((t for t in job['tasks'] if t['task_id'] == task_id), {})
                    if reviewer.get('role') != 'review' or reviewer.get('stage_id') != stage['id'] or task['task_id'] not in reviewer.get('reviewed_task_ids', []):
                        raise AcceptanceError('required review must name a distinct declared review slot')
                    original, peer = review_handle(task), review_handle(reviewer)
                    if task_id == task['task_id'] or task['request_id'] == reviewer.get('request_id') or task['logical_slot_id'] == reviewer.get('logical_slot_id') or original['task_id'] == peer['task_id'] or original['child_thread_id'] == peer['child_thread_id']:
                        raise AcceptanceError('required review execution is not independent')
                    independent_lineage(task, reviewer, original, peer)


def _lineage(task, handle=None):
    """Return the recorded (provider, model, lineage) of a declared slot or host handle."""
    if handle is None:
        target = task.get('target')
    else:
        chain = task.get('handles', []) + task.get('followups', [])
        for _ in range(len(chain) + 1):
            if handle is None or 'target' in handle:
                break
            handle = next((h for h in chain if h.get('task_id') == handle.get('parent_task_id')), None)
        target = (handle or {}).get('target')
    if not isinstance(target, dict) or any(not isinstance(target.get(key), str) or not target[key] for key in ('providerInstanceId', 'model', 'lineage')):
        raise AcceptanceError('required_review_unavailable: review lineage is unknown; independent review is unverified')
    return target['providerInstanceId'], target['model'], target['lineage']


def independent_lineage(worker, reviewer, worker_handle=None, reviewer_handle=None):
    """Refuse a required review on the worker's target or model lineage."""
    original, peer = _lineage(worker, worker_handle), _lineage(reviewer, reviewer_handle)
    if original[:2] == peer[:2] or original[2] == peer[2]:
        raise AcceptanceError('required review must use a different model target and a known different lineage')


def review_handle(task):
    handles = [h for h in task.get('handles', []) + task.get('followups', []) if h.get('request_id') == task.get('request_id')]
    if len(handles) != 1 or handles[0].get('status') != 'completed' or handles[0].get('work_state') != 'result_available' or handles[0].get('has_pending_child_runs') is not False or not handles[0].get('task_id') or not handles[0].get('child_thread_id'):
        raise AcceptanceError('required_review_unavailable: independent review requires a completed owned host execution')
    return handles[0]


def reviewed_document_bytes(store, job, path):
    """Read a declared document subject: absolute, no traversal or symlinks, outside job state."""
    path = Path(path) if isinstance(path, str) and path else None
    if path is None or not path.is_absolute() or '..' in path.parts:
        raise AcceptanceError('reviewed document path must be absolute without parent traversal')
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise AcceptanceError('reviewed document path crosses a symlink')
    if Path(os.path.realpath(path)).is_relative_to(Path(os.path.realpath(store.path))):
        raise AcceptanceError('reviewed document cannot be job state or worker evidence')
    try:
        return _regular(path, max_bytes=job['policy']['max_artifact_bytes'])
    except (OSError, JobError) as exc:
        raise AcceptanceError('reviewed document must be a readable regular file') from exc


def _document_inputs(store, job, reviewer):
    """Bind a document-subject review to the current bytes; a changed document is stale."""
    documents = reviewer['reviewed_documents']
    if not isinstance(documents, list) or not documents or any(
            not isinstance(d, dict) or set(d) != {'path', 'sha256'} for d in documents):
        raise AcceptanceError('reviewed_documents must be a non-empty list of {path, sha256}')
    if len({d['path'] for d in documents}) != len(documents):
        raise AcceptanceError('reviewed documents must be distinct')
    if reviewer.get('context_policy') == 'document-only' and documents != [reviewer.get('document')]:
        raise AcceptanceError('a document-only review names exactly its supplied document')
    for document in documents:
        if digest(reviewed_document_bytes(store, job, document['path'])) != document['sha256']:
            raise AcceptanceError('reviewed document bytes differ from the declared SHA-256; the review is stale')
    return {'documents': [dict(d) for d in documents]}


def review_inputs(store, job, reviewer):
    """Bind exactly one subject form: worker task IDs or declared documents."""
    if reviewer.get('role') != 'review' or ('reviewed_task_ids' in reviewer) == ('reviewed_documents' in reviewer):
        raise AcceptanceError('a review slot needs exactly one subject form: reviewed_task_ids or reviewed_documents')
    if 'reviewed_documents' in reviewer:
        return _document_inputs(store, job, reviewer)
    ids = reviewer.get('reviewed_task_ids', [])
    if not ids or len(set(ids)) != len(ids) or reviewer['task_id'] in ids:
        raise AcceptanceError('review subjects must be explicit distinct worker task IDs')
    stage = _stage(job, reviewer['stage_id'])
    inputs = {}
    for task_id in ids:
        subject = next((t for t in job['tasks'] if t['task_id'] == task_id), {})
        if subject.get('role', 'worker') != 'worker' or subject.get('stage_id') != reviewer['stage_id']:
            raise AcceptanceError('review subject is outside its stage or is another review')
        _check_slots(store, job, stage, {task_id}, require_reviews=False)
        review_handle(subject)
        inputs[task_id] = {k: subject[k] for k in ('request_id', 'brief', 'result_ref')}
    return inputs


def _ready_slots(store, job, stage):
    try:
        _check_slots(store, job, stage)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        code = code_of(exc)  # keep a stable contract code visible through the wrapper
        raise AcceptanceError((code + ': ' if code else '') + 'current task evidence is invalid: ' + str(exc)) from exc


def _bounded_run(argv, cwd, limits):
    timeout = limits.get('timeout_seconds', 30)
    maximum = limits.get('max_output_bytes', 1048576)
    if type(timeout) not in (int, float) or not 0 < timeout <= 30 or type(maximum) is not int or not 0 < maximum <= 1048576:
        raise AcceptanceError('validator helper limits exceed the pinned finite ceiling')
    proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    output = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    for stream in output:
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise AcceptanceError('validator helper timeout')
            for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    output[key.fileobj].extend(chunk)
                    if sum(len(value) for value in output.values()) > maximum:
                        raise AcceptanceError('validator helper output limit exceeded')
        try:
            proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise AcceptanceError('validator helper timeout after output closed') from exc
        return subprocess.CompletedProcess(argv, proc.returncode, bytes(output[proc.stdout]), bytes(output[proc.stderr]))
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
        selector.close()
        for stream in output:
            stream.close()


def _adapter(job, stage, argv, input_file):
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv):
        raise AcceptanceError('validator argv must be a nonempty string array')
    dep = next((dep for dep in job['dependencies'] if dep['key'] == stage.get('validator_dependency')), None)
    if dep is None or dep['plugin'] not in ADAPTERS:
        raise AcceptanceError('undeclared authoritative validator dependency')
    pin = job['pins'][dep['key']]
    program = Path(pin['package_dir']) / 'scripts' / ADAPTERS[dep['plugin']]
    if argv[0] != str(program):
        raise AcceptanceError('validator must be the exact adapter in the stored pinned package')
    program_raw = _regular(program)
    inp = Path(input_file)
    reference = stage.get('observation_ref', {})
    if not inp.is_absolute() or str(inp) != reference.get('path') or inp.parent != Path(reference.get('root', '')) or inp.parent.name != 'observations' or inp.parent.parent.name != job['job_id']:
        raise AcceptanceError('validator input is not the published coordinator observation')
    raw = _regular(inp, max_bytes=job['policy']['max_artifact_bytes'])
    if digest(raw) != reference.get('sha256') or len(raw) != reference.get('bytes'):
        raise AcceptanceError('published coordinator observation bytes changed')
    data = strict_load(raw)
    contract = stage.get('validator_contract', {})
    if dep['plugin'] == 'ape':
        criteria = stage.get('criteria', [])
        if not criteria or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or 'status' in row or row.get('kind') not in ('source-provenance', 'finding-source-coverage') for row in criteria):
            raise AcceptanceError('ape stage criteria must declare checks, never result statuses')
        if not isinstance(data.get('criteria'), list) or sorted(data['criteria'],key=canonical) != sorted(criteria,key=canonical) or not contract.get('sources') or data.get('sources') != contract['sources']:
            raise AcceptanceError('report source pins or criteria differ from the declared stage')
        # The validator checks coverage of what the report declares; bind that declaration to the stage.
        synthesis = bool(stage.get('depends_on'))
        operations = {'ape/study': {'study'}, 'ape/forage': {'forage-synthesis' if synthesis else 'forage-research'}}
        if job['workflow'] in operations and data.get('operation') not in operations[job['workflow']]:
            raise AcceptanceError('ape report operation differs from the job workflow and stage')
        declared = data.get('requirements')
        if not isinstance(declared, list) or any(not isinstance(row, dict) for row in declared) or sorted(map(str, (row.get('id') for row in declared))) != sorted(stage.get('requirements', [])):
            raise AcceptanceError('ape report requirements differ from the stage assignment')
        if data.get('operation') == 'forage-synthesis':
            outputs = sorted(path for sid in stage['depends_on'] for path in _stage(job, sid).get('outputs', []))
            consumed = data.get('consumed_reports')
            if not isinstance(consumed, list) or any(not isinstance(row, dict) for row in consumed) or sorted(map(str, (row.get('path') for row in consumed))) != outputs:
                raise AcceptanceError('ape synthesis must consume exactly the accepted dependency outputs')
    if dep['plugin'] in ('babysitter', 'agent-tuneup'):
        required = ({'pr', 'head_sha', 'required_contexts', 'allow_empty_required_contexts', 'optional_contexts', 'authorized_endstate'} if dep['plugin'] == 'babysitter' else {'criteria'})
        if not required <= set(contract) or any(data.get(key) != value for key, value in contract.items()):
            raise AcceptanceError('workflow criteria differ from the complete declared stage contract')
    # Bind the inputs the executable actually consumes, rather than a decoy file.
    args = argv[1:]
    if len(args) % 2 or len(set(args[::2])) != len(args[::2]):
        raise AcceptanceError('validator options must be unique flag/value pairs')
    flags = dict(zip(args[::2], args[1::2]))
    extra = {}
    if dep['plugin'] in ('ape', 'babysitter', 'agent-tuneup'):
        if flags != {'--input': str(inp)}:
            raise AcceptanceError('validator input differs from the pre-check input')
    elif dep['plugin'] == 'imps':
        descriptor = strict_load(raw)
        if not isinstance(descriptor, dict):
            raise AcceptanceError('imps input must describe its exact gate invocation')
        permitted = {'--state-root', '--run-id', '--final-plan'}
        if set(flags) - permitted or '--state-root' not in flags or not Path(flags['--state-root']).is_absolute():
            raise AcceptanceError('unsupported imps gate invocation')
        for key, value in flags.items():
            if descriptor.get(key[2:].replace('-', '_')) != value:
                raise AcceptanceError('imps gate invocation is not bound to the input descriptor')
        if '--final-plan' in flags:
            plan = Path(flags['--final-plan'])
            if not plan.is_absolute():
                raise AcceptanceError('final-plan path must be absolute')
            plan_raw = _regular(plan, max_bytes=job['policy']['max_artifact_bytes'])
            if strict_load(plan_raw).get('state_root') != flags['--state-root']:
                raise AcceptanceError('final-plan state root differs from bound invocation')
            final_plan = strict_load(plan_raw)
            declared = contract.get('final_plan')
            if not isinstance(declared, dict) or any(final_plan.get(key) != value for key, value in declared.items()) or not {'required_stages', 'stages'} <= set(declared):
                raise AcceptanceError('final-plan gate identities/coverage differ from the declared stage')
            # Declared gate rows need distinct valid IDs, or a repeated ID could hide a second gate.
            # Exact required/declared coverage is enforced by the final gate before it runs any stage gate.
            rows, required_ids = final_plan.get('stages'), final_plan.get('required_stages')
            ids = [row.get('id') for row in rows] if isinstance(rows, list) and all(isinstance(row, dict) for row in rows) else None
            if ids is None or not isinstance(required_ids, list) or not required_ids or any(
                    not isinstance(sid, str) or not sid for sid in ids + required_ids) or len(set(ids)) != len(ids) \
                    or len(set(required_ids)) != len(required_ids):
                raise AcceptanceError('final-plan stage identities must be unique non-empty strings')
            extra[str(plan)] = digest(plan_raw)
        elif '--run-id' not in flags or contract.get('state_root') != flags['--state-root'] or contract.get('run_id') != flags['--run-id']:
            raise AcceptanceError('imps stage requires a run id')
    else:
        if set(flags) - {'--root', '--slug', '--mode', '--input'} or '--slug' not in flags:
            raise AcceptanceError('unsupported document validator invocation')
        if '--root' not in flags or not Path(flags['--root']).is_absolute():
            raise AcceptanceError('document root must be absolute')
        if contract.get('root') != flags['--root'] or contract.get('slug') != flags['--slug'] or contract.get('mode') != flags.get('--mode', 'handoff'):
            raise AcceptanceError('document invocation differs from declared root/slug/mode')
        mode = flags.get('--mode', 'handoff')
        if mode == 'handoff':
            descriptor = strict_load(raw)
            if not isinstance(descriptor, dict) or any(
                descriptor.get(key[2:].replace('-', '_')) != value for key, value in flags.items()):
                raise AcceptanceError('handoff inputs are not bound to the descriptor')
        elif mode in ('factual', 'cold-read'):
            required = {'root', 'slug', 'mode', 'document_path', 'document_sha256'}
            if not required <= set(contract) or not Path(contract['document_path']).is_absolute() or any(data.get(key) != value for key, value in contract.items() if key not in ('root', 'slug', 'mode')):
                raise AcceptanceError('document criteria differ from the complete declared stage contract')
            if flags.get('--input') != str(inp):
                raise AcceptanceError('observation input differs from the pre-check input')
        else:
            raise AcceptanceError('unsupported document validator mode')
    if dep['plugin'] == 'ape':
        for source in contract['sources']:
            path = Path(source['path'])
            if not path.is_absolute() or Path(os.path.realpath(path)).is_relative_to(Path(os.path.realpath(inp.parent.parent / 'artifacts'))):
                raise AcceptanceError('source pin is relative or worker-writable')
            content = _regular(path, max_bytes=job['policy']['max_artifact_bytes'])
            if digest(content) != source['sha256']:
                raise AcceptanceError('pinned research source changed')
            extra[str(path)] = digest(content)
    if dep['plugin'] == 'agent-tuneup' and data.get('changes'):
        references = {change.get('authorization_ref') for change in data['changes']}
        recorded = [d for d in job['decisions'] if d.get('id') in references]
        if len(recorded) != len(references) or data.get('authorization_records') != recorded or not all(_owner_current(d, job['policy']['max_artifact_bytes']) for d in recorded):
            raise AcceptanceError('settings authorization is not the adopted immutable owner record')
        for change in data['changes']:
            owner = next(d for d in recorded if d['id'] == change['authorization_ref'])
            if owner['scope'] != 'settings-change:' + str(change.get('id', '')):
                raise AcceptanceError('owner authorization is for another settings change')
            for key in ('backup_path', 'before_path'):
                path = Path(change[key])
                if not path.is_absolute() or Path(os.path.realpath(path)).is_relative_to(Path(os.path.realpath(inp.parent.parent))):
                    raise AcceptanceError('settings backup evidence must be outside worker/job state')
                extra[str(path)] = digest(_regular(path, max_bytes=job['policy']['max_artifact_bytes']))
    expected = {'babysitter': ['exact-head-required-checks'], 'agent-tuneup': ['audit-criteria'],
                'elephant-goldfish': ['workflow-observation']}.get(dep['plugin'])
    if dep['plugin'] == 'ape':
        expected = [row['id'] for row in stage['criteria']]
    elif dep['plugin'] == 'imps':
        if '--final-plan' in flags:
            expected = ['imps-stage-' + sid for sid in final_plan['required_stages']]
        else:
            run_path = Path(flags['--state-root']) / 'runs' / flags['--run-id'] / 'run.json'
            run_raw = _regular(run_path, max_bytes=job['policy']['max_artifact_bytes'])
            run = strict_load(run_raw)
            expected = [row['id'] for row in run['brief']['requirements']] + ['pre-check-binding']
            extra[str(run_path)] = digest(run_raw)
    if not expected or len(set(expected)) != len(expected):
        raise AcceptanceError('authoritative validator criterion identities are missing or duplicated')
    return program, pin, {'input_sha256': digest(raw), 'extra_inputs': extra,
                          'validator_sha256': digest(program_raw), 'expected_outcome_ids': sorted(expected)}

def _authoritative(raw, stage, expected_ids):
    try:
        result = strict_load(raw)
    except (JobError, ValueError):
        return False, {'validator-output': {'status': 'failed', 'reason': 'invalid full JSON'}}
    if not isinstance(result, dict):
        return False, {}
    outcomes = result.get('requirement_outcomes')
    ok = result.get('accepted') is True and isinstance(outcomes, dict) and bool(outcomes)
    ok = ok and set(outcomes or {}) == set(expected_ids)
    ok = ok and all(isinstance(row, dict) and row.get('status') == 'passed' and row.get('evidence')
                    for row in (outcomes or {}).values())
    return bool(ok), outcomes if isinstance(outcomes, dict) else {}

def _invoke(job, stage, argv, input_file, binding):
    program, pin, fresh = _adapter(job, stage, argv, input_file)
    if any(binding.get(key) != value for key, value in fresh.items()):
        raise AcceptanceError('validator program or actual input changed before execution')
    proc = _bounded_run(argv, Path(pin['package_dir']), stage.get('validator_limits', {}))
    _, _, after = _adapter(job, stage, argv, input_file)
    if fresh != after:
        raise AcceptanceError('validator program or actual input changed during execution')
    ok, outcomes = _authoritative(proc.stdout, stage, fresh['expected_outcome_ids'])
    return proc, ok and proc.returncode == 0, outcomes

def _descendants(stages, stage_id):
    found = {stage_id}
    while True:
        expanded = found | {stage['id'] for stage in stages if set(stage.get('depends_on', [])) & found}
        if expanded == found:
            return [stage for stage in stages if stage['id'] in found and stage['id'] != stage_id]
        found = expanded

def _stale(job, stage_id):
    for stage in [_stage(job, stage_id), *_descendants(job['stages'], stage_id)]:
        if stage.get('acceptance'):
            stage.setdefault('acceptance_history', []).append(stage['acceptance'])
        stage['acceptance'] = None
        stage['status'] = 'stale'
        for task in job['tasks']:
            if task['stage_id'] == stage['id']:
                task['inputs_stale'] = True  # fresh preparation or a charged retry clears it
                if task.get('status') != 'running' and not task.get('uncertain_calls'):
                    task['status'] = 'stale'

def accept_stage(store, caller, stage_id, validator_argv, input_file, expected_revision=None):
    job = verify_all_pins(store, caller)
    stage = _stage(job, stage_id)
    _caller(job, caller)
    if expected_revision != stage.get('revision'):
        raise AcceptanceError('acceptance revision differs from the declared stage revision')
    _ready_slots(store, job, stage)
    if _pending(job, stage):
        raise AcceptanceError('owned tasks or approval waits remain unreconciled')
    for dependency in stage.get('depends_on', []):
        if not validate_stage(store, dependency).get('accepted'):
            raise AcceptanceError('dependency_stale: stage dependency lacks current authoritative acceptance')
    program, pin, actual = _adapter(job, stage, validator_argv, input_file)
    binding = {**actual, 'revision': expected_revision,
               'semantic_sha256': _semantic_binding(job, stage), 'pin_sha256': digest(canonical(pin))}
    generation = digest(canonical(job))
    def reserve(state):
        current = _stage(state, stage_id)
        if digest(canonical(state)) != generation:
            raise AcceptanceError('job changed during preparation; capture a fresh pre-check binding')
        cycle = current.get('cycle', 0)
        if current.get('validated_cycle') == cycle:
            if cycle >= state['policy']['max_repair_cycles']:
                raise AcceptanceError('attempt_budget_exhausted: shared stage pass budget exhausted')
            cycle += 1
            current['cycle'] = cycle
            # Standalone validation can advance only a stage without worker slots;
            # stages with slots need fresh worker execution in the next pass.
            if any(task['stage_id'] == stage_id for task in state['tasks']):
                raise AcceptanceError('next acceptance pass requires charged worker repair')
        current['validated_cycle'] = cycle
        current['acceptance_runs'] = current.get('acceptance_runs', 0) + 1
        current['status'] = 'running'
        return current['acceptance_runs'] - 1, digest(canonical(state))
    sequence, reserved_generation = store.transact(caller, reserve, 'acceptance')
    try:
        proc, accepted, outcomes = _invoke(job, stage, validator_argv, input_file, binding)
        verify_all_pins(store)
        receipt = {'schema_version': 1, 'job_id': job['job_id'], 'stage_id': stage_id,
                   'validator': str(program), 'package_digest': pin['package_digest'], 'binding': binding,
                   'validator_argv': validator_argv, 'input_file': str(Path(input_file).absolute()),
                   'exit_code': proc.returncode, 'stdout_sha256': digest(proc.stdout),
                   'stderr_sha256': digest(proc.stderr), 'outcomes': outcomes, 'accepted': accepted}
    except (OSError, ValueError, JobError, subprocess.SubprocessError) as exc:
        receipt = {'schema_version': 1, 'job_id': job['job_id'], 'stage_id': stage_id,
                   'validator': str(program), 'package_digest': pin['package_digest'], 'binding': binding,
                   'validator_argv': validator_argv, 'input_file': str(Path(input_file).absolute()),
                   'accepted': False, 'outcomes': {}, 'error': str(exc)}
    if digest(canonical(store.load())) != reserved_generation:
        receipt['accepted'] = False
        receipt['error'] = 'job changed during validator execution'
    receipt['validator_sha256'] = binding['validator_sha256']
    receipt.setdefault('exit_code', None)
    receipt['receipt_sha256'] = digest(canonical(receipt))
    path = store.path / 'acceptance' / (stage_id + '-' + str(sequence) + '-' + receipt['receipt_sha256'] + '.json')
    _retain(path, canonical(receipt), 'acceptance receipt is immutable')
    drift = []
    def commit(state):
        current = _stage(state, stage_id)
        changed = digest(canonical(state)) != reserved_generation
        if receipt['accepted']:
            try:
                _ready_slots(store, state, current)
                # The commit-time adapter reading must be the reserved binding, not merely readable:
                # inputs the validator saw are not current if run, plan or source bytes moved since.
                now_program, now_pin, now_actual = _adapter(state, current, validator_argv, input_file)
                if now_program != program or digest(canonical(now_pin)) != binding['pin_sha256'] or \
                        any(binding.get(key) != value for key, value in now_actual.items()):
                    drift.append('validator program, pin or actual input changed before acceptance commit')
                    changed = True
            except (ValueError, OSError, KeyError, TypeError):
                changed = True
        current.setdefault('acceptance_history', []).append({'path': str(path), 'sha256': receipt['receipt_sha256']})
        if changed or _semantic_binding(state, current) != binding['semantic_sha256']:
            _stale(state, stage_id)
            return False
        if receipt['accepted']:
            current['acceptance'] = {'path': str(path), 'sha256': receipt['receipt_sha256'], 'binding': binding}
            current['status'] = 'accepted-at-snapshot'
        else:
            _stale(state, stage_id)
            current['status'] = 'failed'
    committed = store.transact(caller, commit, 'acceptance')
    if committed is False and receipt['accepted']:
        raise AcceptanceError(drift[0] if drift else 'acceptance commit lost its reserved state generation or evidence')
    return receipt

def validate_stage(store, stage_id, _seen=None, run_validator=True):
    try:
        job = verify_all_pins(store)
        generation = digest(canonical(job))  # read-only reservation; rechecked after validators
        stage = _stage(job, stage_id)
        _ready_slots(store, job, stage)
        seen = set() if _seen is None else set(_seen)
        if stage_id in seen:
            raise AcceptanceError('cyclic acceptance dependency')
        seen.add(stage_id)
        if stage.get('status') != 'accepted-at-snapshot' or not stage.get('acceptance') or _pending(job, stage):
            raise AcceptanceError('stage lacks a current receipt or still owns live work')
        for dependency in stage.get('depends_on', []):
            if not validate_stage(store, dependency, seen, run_validator=run_validator).get('accepted'):
                raise AcceptanceError('dependency_stale: predecessor acceptance is stale: ' + dependency)
        reference = stage['acceptance']
        path = Path(reference['path']).absolute()
        if path.parent != store.path / 'acceptance' or path.is_symlink():
            raise AcceptanceError('receipt path is outside the declared acceptance subtree')
        receipt = strict_load(_regular(path, max_bytes=job['policy']['max_artifact_bytes']))
        expected = receipt.pop('receipt_sha256')
        if digest(canonical(receipt)) != expected or expected != reference['sha256']:
            raise AcceptanceError('receipt bytes changed')
        if receipt.get('schema_version') != 1 or receipt.get('job_id') != job['job_id'] or receipt.get('stage_id') != stage_id:
            raise AcceptanceError('receipt correlation changed')
        binding = receipt['binding']
        if binding != reference.get('binding') or binding.get('revision') != stage.get('revision'):
            raise AcceptanceError('receipt revision or binding changed')
        if binding.get('semantic_sha256') != _semantic_binding(job, stage):
            raise AcceptanceError('job contract or consumed output changed')
        program, pin, actual = _adapter(job, stage, receipt['validator_argv'], receipt['input_file'])
        if receipt.get('validator') != str(program) or receipt.get('package_digest') != pin['package_digest']:
            raise AcceptanceError('receipt adapter or package changed')
        if binding.get('pin_sha256') != digest(canonical(pin)):
            raise AcceptanceError('receipt dependency pin changed')
        if any(binding.get(key) != value for key, value in actual.items()):
            raise AcceptanceError('current local inputs differ from receipt')
        if not run_validator:
            if not receipt.get('accepted'):
                raise AcceptanceError('receipt did not accept the stage')
            receipt['receipt_sha256'] = expected
            return {'accepted': True, 'receipt': receipt, 'validation': 'local-receipt-only'}
        proc, accepted, outcomes = _invoke(job, stage, receipt['validator_argv'], receipt['input_file'], binding)
        if not receipt.get('accepted') or not accepted or digest(proc.stdout) != receipt['stdout_sha256'] or outcomes != receipt['outcomes']:
            raise AcceptanceError('current authoritative validator differs from receipt')
        _unchanged(store, generation, [stage_id])
        receipt['receipt_sha256'] = expected
        return {'accepted': True, 'receipt': receipt}
    except (OSError, ValueError, KeyError, TypeError, JobError, StopIteration, subprocess.SubprocessError) as exc:
        return {'accepted': False, 'reason': str(exc), 'stage_id': stage_id}

def _topological(stages):
    by_id = {stage['id']: stage for stage in stages}
    seen, ordered = set(), []
    def visit(stage):
        if stage['id'] in seen:
            return
        for dependency in stage.get('depends_on', []):
            visit(by_id[dependency])
        seen.add(stage['id'])
        ordered.append(stage)
    for stage in stages:
        visit(stage)
    return ordered

def validate_final(store, caller, argv_by_stage, input_by_stage):
    job = verify_all_pins(store, caller)
    _caller(job, caller)
    generation = digest(canonical(job))
    coverage = {r for stage in job['stages'] for r in stage['requirements']} == set(job['requirements'])
    def reserve(state):
        if digest(canonical(state)) != generation:
            raise AcceptanceError('job changed during final preparation; retry against the current job')
        runs = state.get('final_passes', 0)
        if runs >= 1 + state['policy']['max_repair_cycles']:
            raise AcceptanceError('attempt_budget_exhausted: integrated final pass budget exhausted')
        state['final_passes'] = runs + 1
        if not coverage:
            state['history'].append({'kind': 'final-failure', 'reason': 'stage coverage differs from complete job requirements', 'final_pass': runs + 1})
        return runs + 1, digest(canonical(state))
    final_pass, reserved = store.transact(caller, reserve, 'acceptance')
    if not coverage:
        return {'accepted': False, 'reason': 'stage coverage differs from complete job requirements', 'receipts': []}
    results = []
    for stage in _topological(job['stages']):
        # Recheck the existing chain, then run the explicitly declared integrated
        # validator at current inputs. This never manufactures earlier acceptance.
        checked = validate_stage(store, stage['id'])
        if checked.get('accepted'):
            try:
                _, pin, actual = _adapter(job, stage, argv_by_stage[stage['id']], input_by_stage[stage['id']])
                proc, accepted, outcomes = _invoke(job, stage, argv_by_stage[stage['id']],
                    input_by_stage[stage['id']], actual)
                checked = {'accepted': accepted, 'stage_id': stage['id'], 'outcomes': outcomes}
            except (OSError, ValueError, KeyError, JobError) as exc:
                checked = {'accepted': False, 'stage_id': stage['id'], 'reason': str(exc)}
        results.append(checked)
        if not checked.get('accepted'):
            def reopen(state):
                current = _stage(state, stage['id'])
                _stale(state, stage['id'])
                state['history'].append({'kind': 'final-failure', 'stage_id': stage['id'], 'evidence': checked})
                current['status'] = 'blocked' if current.get('cycle', 0) >= state['policy']['max_repair_cycles'] else 'failed'
            store.transact(caller, reopen, 'acceptance')
            return {'accepted': False, 'stage_id': stage['id'], 'receipts': results}
    try:
        # The reserved generation must survive every validator: no observation,
        # plan revision, approval wait or pin change may land during the pass.
        current = _unchanged(store, reserved, [stage['id'] for stage in job['stages']])
        if {r for stage in current['stages'] for r in stage['requirements']} != set(current['requirements']):
            raise AcceptanceError('stage coverage differs from complete job requirements')
    except (OSError, ValueError, KeyError, TypeError, JobError, StopIteration) as exc:
        reason = str(exc)
        def record(state):
            state['history'].append({'kind': 'final-failure', 'reason': reason, 'final_pass': final_pass})
        try:
            store.transact(caller, record, 'acceptance')
        except JobError:
            pass  # a cancelled/discarded job refuses history writes; the result still fails closed
        return {'accepted': False, 'reason': reason, 'receipts': results}
    return {'accepted': True, 'receipts': results}
