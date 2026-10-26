"""Planning-only acceptance over pinned jobs and durable, locked review subjects.

No dispatch, scheduler or model client. Host/owner observations are transcribed
local evidence, not authenticated attestations. Existing specialised gates do not
call this module and cannot be converted into this contract.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import os
from pathlib import Path
import re

from core.jobs import create_job, prepare, record_dispatch, record_result, _unsettled
from core.jobs.results import parse_result, ResultError
from core.jobs.store import (Store, JobError, canonical, digest, strict_load, _regular,
                             _atomic, _retain, _authorize)
from shared import model_selection as models
from shared.job_coordination import freeze_provider_limits, require_admission, observed_now
from shared.job_coordinator import (verified_pins, verify_job_pins, pinned_store,
                                    verify_all_pins, verify_pinned_dependency)
from shared.lineage import lineage
from shared.worker_registry import locked, registry_root, record_job_root, job_agents_roots


class PlanningError(JobError):
    pass


def need(value, message):
    if not value:
        raise PlanningError(message)


def seal(value):
    value = deepcopy(value)
    value.pop('sha256', None)
    return dict(value, sha256=digest(canonical(value)))


def unseal(value):
    need(isinstance(value, dict) and value == seal(value), 'planning record digest mismatch')
    return value


def component(value):
    need(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value)
         and value not in ('.', '..'), 'unsafe review subject ID')
    return value


def supported(value, name):
    from core.schema import errors, load_schema_file
    problems = errors(value, load_schema_file(Path(__file__).parent / 'agents' / (name + '.schema.json')))
    need(not problems, 'invalid ' + name + ' contract: ' + '; '.join(problems[:3]))
    return value


def logical_output_id(request_reference, output_name):
    need(bool(request_reference) and bool(output_name), 'request reference and named output required')
    return digest(canonical([request_reference, output_name]))


def subject_root(project_id, environ=None):
    env = os.environ if environ is None else environ
    base = env.get('XDG_STATE_HOME')
    root = Path(base) if base and Path(base).is_absolute() else Path(env.get('HOME') or Path.home()) / '.local/state'
    return root / 't3-plugins/review-subjects' / component(project_id)


class Subject:
    """Reuse the job store's no-symlink, private-directory and process lock rules."""
    def __init__(self, project_id, output_id, environ=None):
        self.store = Store(subject_root(project_id, environ), component(output_id))
        self.file = self.store.path / 'review.json'

    @contextmanager
    def transaction(self):
        fd = self.store.locked()
        try:
            state = supported(unseal(strict_load(_regular(self.file))), 'planning-subject') if self.file.exists() else None
            yield state
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def save(self, state):
        _atomic(self.file, canonical(supported(seal(state), 'planning-subject')))


def file_descriptor(path):
    p = Path(path)
    need(p.is_absolute() and '..' not in p.parts, 'input path must be absolute without traversal')
    raw = _regular(p)
    return {'path': str(p), 'sha256': digest(raw), 'bytes': len(raw)}


def current_file(row):
    need(file_descriptor(row['path']) == {k: row[k] for k in ('path', 'sha256', 'bytes')},
         'reviewed input drift: ' + row['path'])


def capture(data):
    """Freeze request/decision bytes, source plan, rubric/template and pre-read paths.

    Clauses are contiguous UTF-8 text character ranges, covering every character
    of each request/decision. Each maps to a requirement or explicit non-goal.
    evidence_paths is the authorised pre-review read set, including optional reads.
    """
    out = deepcopy(data)
    out.pop('sha256', None)
    need(out.get('output_name') and out.get('output_type') and out.get('requirements'), 'named output/type and requirements required')
    for field in ('requests', 'decisions'):
        need(isinstance(out.get(field), list) and (field != 'requests' or out[field]), field + ' input list required')
        for row in out[field]:
            need(row.get('reference'), 'verbatim source needs actual message reference')
            desc = file_descriptor(row['path'])
            if row.get('sha256'):
                need(row['sha256'] == desc['sha256'], 'source digest differs')
            row.update(desc)
            text = _regular(Path(row['path'])).decode('utf-8')
            clauses = row.get('clauses', [])
            end = 0
            for clause in clauses:
                need(clause.get('start') == end and type(clause.get('end')) is int and
                     end < clause['end'] <= len(text), 'omitted/overlapping request clauses')
                end = clause['end']
                need((clause.get('requirement') in out['requirements']) != bool(clause.get('non_goal')),
                     'every clause maps to a requirement or explicit non-goal')
            need(end == len(text) and bool(text), 'omitted request clauses')
    for field in ('documents', 'rubrics', 'templates', 'evidence_paths'):
        need(isinstance(out.get(field), list) and (field not in ('documents', 'rubrics') or out[field]), field + ' paths required')
        out[field] = [dict(file_descriptor(p['path'] if isinstance(p, dict) else p),
                           data_class=p.get('data_class', 'repository') if isinstance(p, dict) else 'repository')
                      for p in out[field]]
        need(len({p['path'] for p in out[field]}) == len(out[field]), 'duplicate input paths')
    need(set(out.get('declared_paths', [])) <= {p['path'] for p in out['evidence_paths']}, 'declared evidence lacks pre-review bytes')
    need(isinstance(out.get('authors'), list) and out['authors'], 'all actual authors required')
    # Authorship labels must be derived from identities, never provider-name comparison.
    for author in out['authors']:
        if author.get('unknown'):
            need(author.get('lineage') == 'unknown', 'unrecorded author cannot claim known lineage')
            continue
        provider, model = models.key(author)
        family = lineage(author.get('driver_kind', provider), model)
        need(author.get('lineage') == family, 'author lineage disagrees with identity')
    out['logical_output_id'] = logical_output_id(out['requests'][0]['reference'], out['output_name'])
    out['content_sha256'] = digest(canonical(out['documents']))
    if out.get('repository_root'):
        from core.snapshot import toplevel, git
        root = toplevel(out['repository_root'])
        out['repository_root'] = str(root)
        out['repository_head'] = git(root, 'rev-parse', '--verify', '-q', 'HEAD', check=False).strip() or None
    return seal(out)


def head_observation(snapshot):
    """Report unrelated HEAD movement without making it a content dependency."""
    reviewed = snapshot.get('repository_head')
    current = None
    if snapshot.get('repository_root'):
        from core.snapshot import git
        current = git(snapshot['repository_root'], 'rev-parse', '--verify', '-q', 'HEAD', check=False).strip() or None
    return {'reviewed_head': reviewed, 'observed_head': current,
            'changed': current != reviewed if current is not None else None}


def check_snapshot(snapshot, inspected=()):
    unseal(snapshot)
    for field in ('requests', 'decisions', 'documents', 'rubrics', 'templates'):
        for row in snapshot[field]:
            current_file(row)
    paths = set(snapshot['declared_paths']) | set(inspected)
    index = {row['path']: row for row in snapshot['evidence_paths']}
    need(paths <= set(index), 'unexpected inspected path lacks authorised pre-review snapshot')
    for path in paths:
        current_file(index[path])
    return {p: index[p] for p in sorted(paths)}


def _freeze_inputs(subject, snapshot):
    for field in ('requests', 'decisions', 'documents', 'rubrics', 'templates', 'evidence_paths'):
        for row in snapshot[field]:
            raw = _regular(Path(row['path']))
            need(digest(raw) == row['sha256'] and len(raw) == row['bytes'], 'input changed while freezing review snapshot')
            _retain(subject.store.path / 'inputs' / row['sha256'], raw, 'frozen planning input differs')


def manifest_policy(job):
    """Policy is read only from the verified immutable workflow package."""
    verify_job_pins(job)
    key = job['planning']['dependency_key']
    pin = job['pins'][key]
    # Source entry points may operate on an installed pin only when the executing
    # acceptance implementation and its contracts are those pinned bytes.
    runtime = Path(__file__).resolve().parents[1]
    for rel in ('shared/planning_review.py', 'shared/model_selection.py', 'shared/lineage.py',
                'core/jobs/__init__.py', 'core/jobs/results.py', 'core/jobs/store.py', 'core/schema.py',
                'shared/agents/planning-policy.schema.json', 'shared/agents/planning-direct.schema.json',
                'shared/agents/planning-assessment.schema.json', 'shared/agents/planning-subject.schema.json',
                'shared/agents/planning-job.schema.json', 'shared/agents/job.schema.json',
                'shared/agents/worker-result.schema.json'):
        need(_regular(runtime / rel) == _regular(Path(pin['package_dir']) / rel),
             'planning validator runtime differs from pinned package; use its stored helper: ' + rel)
    meta = strict_load(_regular(Path(pin['package_dir']) / 'plugin.json'))
    policy = meta.get('planning_review')
    from core.schema import errors, load_schema_file
    schema = load_schema_file(Path(__file__).parent / 'agents/planning-policy.schema.json')
    need(not errors(policy, schema), 'pinned workflow has no supported planning purpose policy')
    need(job['workflow'] == meta['name'] + '/planning-review' and
         job['planning']['purpose'] == 'planning-review' and
         job['planning']['output_type'] in policy['output_types'], 'planning purpose/output type not permitted by pinned manifest')
    need(job['planning']['policy_sha256'] == digest(canonical(policy)), 'pinned planning policy differs')
    need(len(job['stages']) == 1 and job['stages'][0]['id'] == 'planning', 'separate planning job must have one planning stage')
    need(not job.get('history'), 'existing job cannot migrate into planning fallback')
    need(not job['policy'].get('author_independence') and not job.get('decisions'), 'stronger gates and waivers cannot be relabelled')
    for row in job['tasks']:
        need(row['worker_id'] == policy['worker_id'] and row.get('role') == 'review' and
             not any(row.get(k) for k in ('review_required', 'independent_of_author', 'reviewed_task_ids', 'context_policy')),
             'stronger review slot cannot migrate to planning policy')
    return policy


def caller_for(job):
    return {'actor': 'coordinator', 'workflow': job['workflow'], 'installation_id': job['installation_id'],
            'package_digest': job['pins'][job['planning']['dependency_key']]['package_digest']}


def snapshot_data_classes(snapshot, explicit):
    """Keep declared job scope and derive confidentiality from current inputs."""
    need(isinstance(explicit, list) and all(isinstance(c, str) and c for c in explicit),
         'explicit data classes must be nonempty strings')
    classes = set(explicit)
    for field in ('requests', 'decisions', 'documents', 'rubrics', 'templates', 'evidence_paths'):
        for row in snapshot[field]:
            value = row.get('data_class', 'topic')
            need(isinstance(value, str) and value, 'snapshot data class must be a nonempty string')
            classes.add(value)
    return sorted(classes)


def create(data, state_root, prefix, agents_root, environ=None):
    """Create a NEW separate pinned job. Callers cannot supply stages/purpose/policy."""
    need(not set(data) & {'stages', 'tasks', 'policy', 'purpose', 'history'}, 'cannot relabel or import existing stronger slots')
    snapshot = data['snapshot']
    check_snapshot(snapshot)
    selected = models.validate(data['selection'])
    need(selected['project_id'] == data['project_id'], 'selection belongs to another project')
    models.gate(selected, invocation_id=data['invocation_id'], scope_id=data['scope_id'])
    need(selected['scope_id'] == snapshot['logical_output_id'], 'selection is not bound to this stable request/output scope')
    if snapshot.get('thinking_admission'):
        admission = unseal(snapshot['thinking_admission'])
        need(admission['scope_id'] == snapshot['logical_output_id'] and
             admission['selection_sha256'] == selected['selection_sha256'],
             'thinking planning selection differs from predraft admission')
    for author in snapshot['authors']:
        if not author.get('unknown'):
            need(_identity_lineage(selected, author) == author['lineage'], 'author identity disagrees with frozen host provider lineage')
    explicit_classes = sorted(set(data.get('data_classes', ['repository', 'topic'])))
    classes = snapshot_data_classes(snapshot, explicit_classes)
    subject = Subject(data['project_id'], snapshot['logical_output_id'], environ)
    with subject.transaction() as state:
        if state:
            need(state['request_reference'] == snapshot['requests'][0]['reference'] and state['output_name'] == snapshot['output_name'], 'subject scope mismatch')
            need(state['active_job'] is None, 'another unfinished job owns this output')
            need(state['rounds_used'] < state['round_limit'], 'substantive review budget exhausted')
            need(state['requirements'] == snapshot['requirements'], 'new jobs cannot weaken retained requirements')
        else:
            state = {'schema_version': 1, 'project_id': data['project_id'], 'logical_output_id': snapshot['logical_output_id'],
                     'request_reference': snapshot['requests'][0]['reference'], 'output_name': snapshot['output_name'],
                     'round_limit': 5, 'rounds_used': 0, 'technical_used': 0, 'active_job': None,
                     'requirements': snapshot['requirements'],
                     'sharing_revocations': [],
                     'jobs': [], 'revisions': {}, 'rounds': [], 'findings': {}, 'decisions': [], 'receipts': []}
        job = {'schema_version': 1, 'job_id': component(data['job_id']), 'installation_id': data['installation_id'],
               'workflow': data['plugin'] + '/planning-review', 'owner': data['owner'],
               'objective': 'Review the exact planning output against the original request.',
               'requirements': snapshot['requirements'], 'authorization': {'actions': ['read']},
               'constraints': ['Read-only critique. No children, implementation, owner decisions or scope expansion.'],
               'dependencies': [{'key': 'workflow', 'plugin': data['plugin']}], 'stages': [
                   {'id': 'planning', 'depends_on': [], 'requirements': list(snapshot['requirements']), 'status': 'pending',
                    'resources': {'planning_snapshot': snapshot, 'prior_findings': state['findings']}, 'revision': snapshot['sha256']}],
               'pins': {}, 'policy': {'max_repair_cycles': 0, 'max_artifact_bytes': 16*1024*1024, 'identity': 'observed'},
               'tasks': [], 'decisions': [], 'history': [], 'metrics': {}, 'result_contract': {'schema_version': 1},
               'model_selection': selected, 'model_selection_sha256': selected['selection_sha256'],
               'invocation_id': data['invocation_id'], 'scope_id': data['scope_id'],
               'planning': {'purpose': 'planning-review', 'dependency_key': 'workflow', 'output_type': snapshot['output_type'],
                            'subject_file': str(subject.file), 'snapshot': snapshot, 'passes': [], 'attempts': [], 'round': None,
                            'sharing_revocations': deepcopy(state['sharing_revocations']),
                            'attempts_per_candidate': 2, 'explicit_data_classes': explicit_classes,
                            'data_classes': classes}}
        with locked(registry_root(agents_root)):
            pins = verified_pins(job, state_root, prefix, agents_root)
            freeze_provider_limits(job, pins)
            job['pins'] = pins
            meta = strict_load(_regular(Path(pins['workflow']['package_dir']) / 'plugin.json'))
            job['planning']['policy_sha256'] = digest(canonical(meta.get('planning_review')))
            policy = manifest_policy(job)
            # A finite full chain for each content round. No generic repair limit is used as content budget.
            chain_size = sum(1 + len([r for r in selected['review_replacements'] if r.get('slot_id') == s['slot_id'] and r.get('execution') != 'self-review'])
                             for s in selected['review_panel'] if s['required'])
            need(chain_size > 0, 'planning review needs an applicable selected panel')
            state.setdefault('technical_limit', 2 * chain_size * state['round_limit'])
            job['planning']['technical_limit'] = state['technical_limit']
            job['policy']['max_repair_cycles'] = job['planning']['technical_limit']
            record_job_root(job_agents_roots(pins), state_root, job['job_id'])
            created = create_job(job, state_root, pins)
        store = pinned_store(state_root, job['job_id'])
        ref = {'job_id': job['job_id'], 'state_root': str(store.root)}
        need(ref not in state['jobs'], 'job identity already retained')
        state['jobs'].append(ref)
        state['active_job'] = ref
        state['revisions'][snapshot['sha256']] = snapshot
        # Retain exact input bytes outside replaceable jobs as well as descriptors.
        _freeze_inputs(subject, snapshot)
        subject.save(state)
        return dict(created, subject_file=str(subject.file), caller=caller_for(job), policy=policy)


def _subject(job, environ=None):
    s = job['planning']['snapshot']
    subject = Subject(job['model_selection']['project_id'], s['logical_output_id'], environ)
    need(str(subject.file) == job['planning']['subject_file'], 'review subject path/scope mismatch')
    return subject


def _active(state, store):
    need(state is not None and state['active_job'] == {'job_id': store.file.parent.name, 'state_root': str(store.root)},
         'planning job does not own active subject')


def _unchanged(store, job):
    need(canonical(store.verified_load()) == canonical(job),
         'planning job changed while waiting for subject lock; retry with current state')


def begin(store, caller, snapshot=None, requested_rereview=False, environ=None):
    job = verify_all_pins(store, caller)
    manifest_policy(job)
    snapshot = snapshot or job['planning']['snapshot']
    check_snapshot(snapshot)
    need(snapshot.get('thinking_admission') == job['planning']['snapshot'].get('thinking_admission'),
         'thinking repair cannot replace predraft admission')
    # Older pinned shapes lack the separate explicit set. Retain their whole
    # creation-time scope conservatively rather than silently reducing authority.
    classes = snapshot_data_classes(snapshot, job['planning'].get(
        'explicit_data_classes', job['planning']['data_classes']))
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        need(snapshot['logical_output_id'] == state['logical_output_id'], 'new revision belongs to another subject')
        need(snapshot['requirements'] == state['requirements'] and snapshot['output_type'] == job['planning']['output_type'],
             'review repair cannot weaken requirements or change output purpose')
        need(not any(_unsettled(job, t) for t in job['tasks']), 'reconcile pending/uncertain owned tasks before a new round')
        previous = state['rounds'][-1] if state['rounds'] else None
        need(not previous or previous['closed'], 'current content round is unfinished')
        need(not previous or not previous.get('charged') or snapshot['sha256'] != previous['snapshot']['sha256'] or requested_rereview or state['findings'],
             'unchanged accepted content needs an explicit re-review request')
        need(state['rounds_used'] < state['round_limit'], 'substantive review budget exhausted')
        round_ = {'number': len(state['rounds']) + 1, 'job_id': job['job_id'], 'snapshot': snapshot, 'charged': False,
                  'closed': False, 'passes': [], 'attempts': [], 'result': None}
        state['rounds'].append(round_)
        state['revisions'][snapshot['sha256']] = snapshot
        _freeze_inputs(subject, snapshot)
        def apply(j):
            j['planning'].update(snapshot=snapshot, round=round_['number'], passes=[], attempts=[],
                                 data_classes=classes)
            j['stages'][0].update(revision=snapshot['sha256'], status='running',
                resources={'planning_snapshot': snapshot, 'prior_findings': state['findings'],
                    'draft_check': {'helper': file_descriptor(Path(job['pins']['workflow']['package_dir']) /
                                                            'shared/planning_review_cli.py'),
                                    'command': 'check-draft', 'maximum_correction_cycles': 1,
                                    'requires_declared_procedural_reads': True, 'acceptance': False}})
            j['requirements'] = snapshot['requirements']
            j['stages'][0]['requirements'] = list(snapshot['requirements'])
        # Reserve the round before the replaceable job. Technical failures do not
        # charge content; the first actual assessment below makes that charge.
        subject.save(state)
        store.transact(caller, apply)
        return deepcopy(round_)


def _family(record, target, role):
    family = models.suitability(target, role, record['profiles'], record['capabilities'])
    # Canonical identity derivation and declarative profile must agree.
    derived = _identity_lineage(record, target)
    need(family == derived, 'reviewer profile lineage disagrees with identity')
    return family


def _identity_lineage(record, target):
    provider_id, model = models.key(target)
    providers = [p for p in record['capabilities']['providers'] if p['providerInstanceId'] == provider_id]
    driver = providers[0].get('driverKind', provider_id) if len(providers) == 1 else provider_id
    if target.get('driver_kind'):
        need(target['driver_kind'] == driver, 'author driver kind differs from frozen host catalog')
    return lineage(driver, model)


def candidates(job, slot_id):
    record = models.validate(job['model_selection'], job['model_selection_sha256'])
    slot = next((s for s in record['review_panel'] if s['slot_id'] == slot_id and s['required']), None)
    need(slot is not None, 'no applicable named review panel slot')
    chain = [{'target': slot['target'], 'role': slot['role'], 'primary': True}]
    chain += [deepcopy(r) for r in record['review_replacements'] if r.get('slot_id') == slot_id and r.get('execution') != 'self-review']
    authors = {a['lineage'] for a in job['planning']['snapshot']['authors']}
    for candidate in chain:
        family = _family(record, candidate['target'], candidate['role'])
        from shared.lineage import DRIVER_LINEAGE, FAMILY_LINEAGE
        known = set(DRIVER_LINEAGE.values()) | set(FAMILY_LINEAGE.values())
        candidate['mode'] = ('non-independent' if family not in known or not authors <= known else
                             'same-lineage' if family in authors else 'cross-lineage')
        need(candidate['mode'] == 'cross-lineage' or not slot.get('independent', True),
             'stronger selected independent slot refuses degraded planning fallback')
        candidate['lineage'] = family
    # Within disclosed authority, exhaust cross-lineage children before same-lineage.
    chain.sort(key=lambda c: c['mode'] != 'cross-lineage')
    seen = set()
    for c in chain:
        identity = digest(canonical(c['target']))
        need(identity not in seen, 'duplicate availability candidates')
        seen.add(identity)
    return chain


def effective_sharing(job):
    revoked = {r['grant_sha256'] for r in job['planning']['sharing_revocations']}
    return [g for g in job['model_selection'].get('sharing', []) if digest(canonical(g)) not in revoked]


def revoke_sharing(store, caller, grants, source, source_file, environ=None):
    """Retain an actual authority revocation; free-form exclusions are refused."""
    job = verify_all_pins(store, caller)
    manifest_policy(job)
    models.source(source)
    source_file = file_descriptor(source_file)
    need(source['answer'] in _regular(Path(source_file['path'])).decode('utf-8'), 'revocation quote differs from source bytes')
    need(grants and all(g in job['model_selection'].get('sharing', []) for g in grants), 'revocation must name actual frozen sharing grants')
    subject = _subject(job, environ)
    need(not Path(source_file['path']).is_relative_to(store.path) and
         not Path(source_file['path']).is_relative_to(subject.store.path), 'authority source must be outside worker/subject state')
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        need(not any(_unsettled(job, t) for t in job['tasks']), 'reconcile owned tasks before changed sharing authority')
        for grant in grants:
            sha = digest(canonical(grant))
            if not any(r['grant_sha256'] == sha for r in state['sharing_revocations']):
                state['sharing_revocations'].append({'grant_sha256': sha, 'grant': deepcopy(grant),
                    'source': deepcopy(source), 'source_file': source_file})
        subject.save(state)
        store.transact(caller, lambda j: j['planning'].update(sharing_revocations=deepcopy(state['sharing_revocations'])))
        return {'sharing': effective_sharing(store.load()), 'revocations': deepcopy(state['sharing_revocations'])}


def exclusions(job, slot_id, sharing=None):
    """Compute policy exclusions. Caller-supplied exclusion prose is never accepted.

    Frozen capabilities/routing/profile validity is checked by selection validation.
    Revocations need persistent actual authority evidence. A supplied current
    sharing list must equal that derived state, never invent another exclusion.
    """
    record = job['model_selection']
    current_sharing = effective_sharing(job)
    need(sharing is None or sharing == current_sharing, 'sharing override lacks a persisted authority revocation')
    for revocation in job['planning']['sharing_revocations']:
        current_file(revocation['source_file'])
        models.source(revocation['source'])
    confidential = set(job['planning']['data_classes']) - models.ORDINARY
    result = []
    for candidate in candidates(job, slot_id):
        reason = None
        if confidential and not any(models.key(g['target']) == models.key(candidate['target']) and
                                    confidential <= set(g['data_classes']) and models.source(g['source']) for g in current_sharing):
            reason = 'privacy: confidential-class authority missing or revoked'
        if not candidate.get('primary'):
            models._authority(candidate['authority'])
            models._authority_target(candidate['authority'], candidate['target'], record)
            if not set(job['planning']['data_classes']) <= set(candidate['authority']['data_classes']):
                reason = 'privacy: replacement authority data scope exceeded'
        result.append(dict(candidate, exclusion=reason))
    return result


def _unavailable(job, candidate, slot_id):
    attempts = [a for a in job['planning']['attempts'] if a['slot_id'] == slot_id and a['target'] == candidate['target']]
    if not attempts:
        return False
    latest = attempts[-1]
    return latest.get('outcome') == 'unavailable' and latest.get('failure') is not None


def _available_candidate(job, slot_id, sharing=None):
    return next((c for c in exclusions(job, slot_id, sharing)
                 if not c['exclusion'] and not _unavailable(job, c, slot_id)), None)


def next_candidate(job, slot_id, sharing=None):
    need(job['planning']['round'] is not None, 'begin a counted content round first')
    need(not any(_unsettled(job, t) for t in job['tasks']), 'pending or uncertain owned review must be reconciled')
    need(not any(a['outcome'] is None for a in job['planning']['attempts']),
         'prepared attempt needs same-request reconciliation before replacement')
    return _available_candidate(job, slot_id, sharing)


def _charge_prepared_attempt(subject, state, job, attempt):
    """Charge only a durable preparation; same-request recovery charges once."""
    round_ = state['rounds'][-1]
    need(round_['number'] == job['planning']['round'] and not round_['closed'], 'round is closed or differs')
    old = next((a for a in round_['attempts'] if a['request_id'] == attempt['request_id']), None)
    if old is not None:
        need(old == attempt, 'subject attempt binding differs')
        return
    need(attempt['task_id'] == 'review-' + str(state['technical_used'] + 1), 'technical attempt sequence differs')
    used = [a for a in round_['attempts'] if a['target'] == attempt['target'] and a['slot_id'] == attempt['slot_id']]
    need(len(used) < job['planning']['attempts_per_candidate'], 'finite candidate technical allowance exhausted')
    need(state['technical_used'] < job['planning']['technical_limit'], 'technical attempt budget exhausted')
    state['technical_used'] += 1
    round_['attempts'].append(deepcopy(attempt))
    subject.save(state)


def _subject_attempt(state, task):
    attempts = state['rounds'][-1]['attempts'] if state['rounds'] else []
    old = next((a for a in attempts if a['task_id'] == task['task_id']), None)
    need(old is not None and all(old[k] == task[k] for k in ('request_id', 'target')),
         'prepared attempt needs same-request launch reconciliation before recording an outcome')
    return old


def _attempt_selection(job, attempt):
    """Immutable preparation binding, separate from current dispatch permission."""
    return {'selection_sha256': job['model_selection_sha256'], 'round': job['planning']['round'],
            **{k: deepcopy(attempt[k]) for k in ('slot_id', 'target', 'mode', 'lineage')}}


def launch(store, caller, slot_id, request_id, sharing=None, environ=None):
    """Reserve one finite technical attempt and prepare an existing immutable brief.

    Returns target and stable request ID to the host coordinator. Never dispatches.
    """
    job = verify_all_pins(store, caller)
    policy = manifest_policy(job)
    need(job['planning']['round'] is not None, 'begin a counted content round first')
    def retained_brief():
        def check(current):
            manifest_policy(current)
            attempt = next(a for a in current['planning']['attempts'] if a['request_id'] == request_id)
            need(attempt['slot_id'] == slot_id and attempt['outcome'] is None,
                 'request ID is already retained by a finished attempt')
            # Recover the original frozen choice, never today's next available one.
            expected = next((c for c in candidates(current, slot_id) if c['target'] == attempt['target']), None)
            need(expected is not None and all(attempt[k] == expected[k] for k in ('target', 'mode', 'lineage')),
                 'request ID target binding differs')
            task = next(t for t in current['tasks'] if t['task_id'] == attempt['task_id'])
            need(task['target'] == expected['target'] and task['request_id'] == request_id,
                 'prepared task binding differs')
            need('brief' in task, 'incomplete launch reservation requires reconciliation')
            brief = task['brief']
            need(brief['path'] == str(store.path / 'briefs' / (task['task_id'] + '-' + digest(request_id.encode()) + '.json')),
                 'prepared brief path binding differs')
            _expected(current, task)  # Rehash immutable bytes and their planning snapshot.
            assigned = strict_load(_regular(Path(brief['path'])))
            selection = _attempt_selection(current, attempt)
            need(assigned.get('model_selection') == task.get('model_selection') == selection,
                 'prepared planning selection/slot binding differs')
            need(all(assigned[k] == task[k] == brief[k] for k in
                     ('task_id', 'request_id', 'stage_id', 'logical_slot_id', 'worker_id')) and
                 assigned['job_id'] == brief['job_id'] == current['job_id'] and
                 assigned['target'] == task['target'] and assigned['role'] == task['role'] == 'review' and
                 assigned['revision'] == brief['revision'] == current['planning']['snapshot']['sha256'] and
                 assigned['snapshot'] == brief['snapshot'] == current.get('snapshot') and
                 assigned['dependency_pins'] == current['pins'] and
                 assigned['effective_definition'] == current['pins'][task['dependency_key']]['effective_workers'][task['worker_id']] and
                 assigned['authorization'] == current['authorization'] and assigned['constraints'] == current['constraints'] and
                 assigned['write_scope'] == task['write_scope'] and
                 assigned['requirements'] == [{'id': r, 'statement': current['requirements'][r]}
                                              for r in current['stages'][0]['requirements']],
                 'immutable prepared task contract differs')
            return (dict(task['brief'], target=attempt['target'], task_id=task['task_id'],
                         request_id=request_id, mode=attempt['mode']), deepcopy(attempt))
        return store.transact(caller, check, 'prepare')
    component(request_id)
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        need(not state['rounds'][-1]['closed'], 'round is closed')
        old = next((a for a in job['planning']['attempts'] if a['request_id'] == request_id), None)
        if old:
            brief, attempt = retained_brief()
            _charge_prepared_attempt(subject, state, job, attempt)
            def dispatch_permission(current):
                # Accounting survives revoked sharing or moved occupancy. Returning
                # a brief still grants dispatch instructions, so recheck separately.
                need(canonical(current) == canonical(job), 'planning job changed during charge recovery; retry with current state')
                candidate = next(c for c in exclusions(current, slot_id, sharing) if c['target'] == attempt['target'])
                need(not candidate['exclusion'], 'current sharing denies prepared dispatch: ' + str(candidate['exclusion']))
                task = next(t for t in current['tasks'] if t['task_id'] == attempt['task_id'])
                handles = task.get('handles', []) + task.get('followups', [])
                need(not any(b.get('kind') == 'identity-mismatch' and b.get('task_id') == task['task_id'] and
                             not b.get('reconciled') for b in current.get('blockers', [])), 'sticky host identity mismatch')
                for event in task.get('dispatch_history', []):
                    for name in ('status_identity', 'receipt_identity', 'configuration_identity'):
                        if isinstance(event.get(name), dict):
                            models.correlate({'target': task['target']}, event[name])
                if not any(h.get('request_id') == request_id for h in handles + task.get('execution_history', [])):
                    require_admission(current, task)
            store.transact(caller, dispatch_permission, 'prepare')
            return brief
        need(job['planning']['round'] and not any(p['slot_id'] == slot_id for p in job['planning']['passes']),
             'slot already reviewed or no round')
        candidate = next_candidate(job, slot_id, sharing)
        need(candidate is not None, 'all permitted children unavailable; explicit direct pass required')
        used = [a for a in state['rounds'][-1]['attempts'] if a['target'] == candidate['target'] and a['slot_id'] == slot_id]
        need(len(used) < job['planning']['attempts_per_candidate'], 'finite candidate technical allowance exhausted')
        # Total technical bound survives replacement jobs. Allow enough for the initial finite chain in every round.
        need(state['technical_used'] < job['planning']['technical_limit'], 'technical attempt budget exhausted')
        task_id = 'review-' + str(state['technical_used'] + 1)
        attempt = {'request_id': request_id, 'task_id': task_id, 'slot_id': slot_id, 'target': candidate['target'],
                   'mode': candidate['mode'], 'lineage': candidate['lineage'], 'outcome': None}
        def apply(j):
            need(not any(t['request_id'] == request_id for t in j['tasks']), 'request ID already retained')
            j['tasks'].append({'task_id': task_id, 'stage_id': 'planning', 'logical_slot_id': task_id,
                'request_id': request_id, 'worker_id': policy['worker_id'], 'dependency_key': 'workflow',
                'role': 'review', 'target': candidate['target'], 'status': 'pending',
                'model_selection': _attempt_selection(j, attempt),
                'attempt': 0, 'handles': [], 'followups': [], 'dispatch_retries': 0,
                'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task_id}})
            require_admission(j, j['tasks'][-1])
            j['planning']['attempts'].append(deepcopy(attempt))
        brief = prepare(store, caller, task_id, verify_pinned_dependency, lambda _: False,
                        'explicit planning panel/availability candidate', bind_inputs=apply)
        # A failed job transaction cannot charge the subject. If this save fails
        # after preparation commits, return no brief; replay recovers the charge
        # under the subject lock before exposing the same durable reservation.
        _charge_prepared_attempt(subject, state, job, attempt)
        return dict(brief, target=candidate['target'], mode=candidate['mode'], task_id=task_id, request_id=request_id)


def host_event(store, caller, task_id, event):
    """Use generic lifecycle correlation and sticky host-identity mismatch rules."""
    job = verify_all_pins(store, caller)
    manifest_policy(job)
    need(not isinstance(event, dict) or 'recorded_at' not in event,
         'recorded_at is local receipt time and cannot be supplied')
    if isinstance(event, dict): event = {**event, 'recorded_at': observed_now()}
    return record_dispatch(store, caller, task_id, event)


def unavailable(store, caller, task_id, failure, environ=None):
    """Settle a failed host call or an evidenced local prelaunch refusal.

    A no-handle refusal needs prelaunch=True, a matching original request_id and
    nonempty tool, call_id and receipt; kind is technical, capacity or permission.
    For a local CLI refusal, call_id is a caller-supplied correlation token for
    that actual invocation; the CLI neither accepts nor emits it.
    After an interrupted charge, replay the original launch first. Charge recovery
    may succeed while current sharing/capacity refuses dispatch. Record that real
    local refusal without inventing a host event or handle. Settlement neither
    dispatches nor adds a charge, changes the binding or grants permission.
    Unknown/possibly active work must first reconcile through the existing host
    lifecycle. A complete substantive response is never a technical failure.
    """
    job = verify_all_pins(store, caller)
    manifest_policy(job)
    task = next(t for t in job['tasks'] if t['task_id'] == task_id)
    from core.jobs import _live_handles, _open_dispatch
    need(not _live_handles(task) and not _open_dispatch(task) and not task.get('blocked_reason') and
         not (task.get('uncertain_calls') and not task.get('handles')),
         'uncertain or pending host work is not unavailability')
    need(not task.get('execution_history'), 'substantive/adverse/incomplete result cannot become unavailability')
    need(failure.get('kind') in ('technical', 'capacity', 'permission') and failure.get('tool') and
         failure.get('call_id') and failure.get('request_id') == task['request_id'] and failure.get('receipt'),
         'actual correlated host tool call/receipt required')
    handles = task.get('handles', []) + task.get('followups', [])
    need((not handles and failure.get('prelaunch') is True) or
         (handles and failure.get('host_task_id') in {h['task_id'] for h in handles}), 'failure must retain owned handle when created')
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        old = _subject_attempt(state, task)
        def apply(j):
            attempt = next(a for a in j['planning']['attempts'] if a['task_id'] == task_id)
            need(attempt['outcome'] is None, 'attempt already has an outcome')
            attempt.update(outcome='unavailable', failure=deepcopy(failure), owned_handles=deepcopy(handles))
            task_ = next(t for t in j['tasks'] if t['task_id'] == task_id)
            task_['status'] = 'failed'
            # The correlated failure settles this reservation even without a host
            # handle. It is not a worker result or a substantive assessment.
            task_.setdefault('execution_history', []).append({'request_id': task_['request_id'],
                'technical_failure': deepcopy(failure), 'accepted_execution': False})
            return deepcopy(attempt)
        updated = store.transact(caller, apply)
        old.update(updated)
        subject.save(state)
        return updated


def _expected(job, task):
    brief = task['brief']
    raw = _regular(Path(brief['path']))
    need(digest(raw) == brief['sha256'], 'immutable planning brief tampered')
    assigned = strict_load(raw)
    need(isinstance(assigned, dict), 'planning brief must be a JSON object')
    claimed = assigned.pop('effective_brief_sha256')
    need(digest(canonical(assigned)) == claimed == brief['effective_brief_sha256'], 'planning brief content hash differs')
    need(assigned['resources']['planning_snapshot'] == job['planning']['snapshot'], 'result belongs to a superseded content round')
    expected = {k: brief[k] for k in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256')}
    expected.update(role='review', revision=brief['revision'], binding=brief['snapshot'], task_id=task['task_id'],
                    requirements=list(job['requirements']))
    return expected


def _completed_identity(job, task):
    from shared.job_acceptance import review_handle
    handle = review_handle(task)
    need(not _unsettled(job, task), 'pending/uncertain/unread host work blocks planning acceptance')
    observed = handle.get('observed_identity', {})
    need(observed.get('status') == 'verified', 'delegated host identity unverified or mismatched')
    need(not any(b.get('kind') == 'identity-mismatch' and b.get('task_id') == task['task_id'] for b in job.get('blockers', [])), 'sticky host identity mismatch')
    models.correlate({'target': task['target']}, observed)
    for event in task.get('dispatch_history', []):
        for name in ('status_identity', 'receipt_identity', 'configuration_identity'):
            observation = event.get(name)
            if isinstance(observation, dict):
                models.correlate({'target': task['target']}, observation)
    authors = job['planning']['snapshot']['authors']
    need(not any(handle['task_id'] == a.get('host_task_id') or handle['child_thread_id'] == a.get('child_thread_id')
                 for a in authors), 'planning reviewer must be a fresh child, not the author execution')
    current = next(a for a in job['planning']['attempts'] if a['task_id'] == task['task_id'])
    actual_family = _identity_lineage(job['model_selection'], observed)
    need(actual_family == current['lineage'], 'observed reviewer lineage differs from candidate')
    for other in job['tasks']:
        if other['task_id'] != task['task_id']:
            need(not any(h.get('child_thread_id') == handle['child_thread_id'] for h in
                         other.get('handles', []) + other.get('followups', [])), 'new review round requires a fresh child execution')
    return handle


def _charge(state):
    round_ = state['rounds'][-1]
    if not round_.get('charged'):
        need(state['rounds_used'] < state['round_limit'], 'substantive review budget exhausted')
        state['rounds_used'] += 1
        round_['charged'] = True


def _retain_findings(state, job, findings, execution_id, family):
    problems = []
    collisions = []
    if not isinstance(findings, list):
        return ['planning findings must be a list'], collisions
    for finding in findings:
        if not (isinstance(finding, dict) and isinstance(finding.get('id'), str) and finding['id']
                and finding.get('severity') in ('blocker', 'major', 'minor', 'note')
                and all(finding.get(k) for k in ('scenario', 'source_evidence', 'smallest_correction'))):
            problems.append('planning finding lacks scenario/evidence/smallest correction')
            continue
        key = family + ':' + finding['id']
        original_key = key
        old = state['findings'].get(key)
        if old and old['finding'] != finding:
            # Preserve both accounts without letting an ID collision strand a
            # result or classify a complete assessment as a malformed envelope.
            base = key + '@' + digest(canonical([execution_id, finding]))
            key = base
            suffix = 0
            while key in state['findings'] and state['findings'][key]['finding'] != finding:
                suffix += 1
                key = base + '-' + str(suffix)
        if key not in state['findings']:
            state['findings'][key] = {'finding': deepcopy(finding), 'lineage': family, 'execution_id': execution_id,
                'content_sha256': job['planning']['snapshot']['content_sha256'], 'status': 'open', 'history': []}
        if key != original_key:
            collision = {'kind': 'finding-id-collision', 'original_key': original_key,
                         'retained_key': key, 'execution_id': execution_id, 'lineage': family}
            collisions.append(collision)
            for account in (original_key, key):
                if collision not in state['findings'][account]['history']:
                    state['findings'][account]['history'].append(deepcopy(collision))
    return problems, collisions


def _coverage(job, assessment):
    need(isinstance(assessment, dict), 'planning assessment must be an object')
    snapshot = job['planning']['snapshot']
    expected = set(job['requirements']) | set(snapshot.get('load_bearing_decisions', []))
    coverage = assessment.get('coverage')
    need(isinstance(coverage, list) and len(coverage) == len(expected) and {c.get('id') for c in coverage} == expected,
         'missing required requirement/load-bearing decision coverage')
    need(all(c.get('outcome') in ('supported', 'contradicted', 'unverified') and c.get('evidence') for c in coverage), 'coverage lacks outcome/evidence')
    inspected = assessment.get('inspected_paths')
    need(isinstance(inspected, list) and all(isinstance(p, str) for p in inspected), 'actual inspected paths required')
    check_snapshot(snapshot, inspected)
    return all(c['outcome'] == 'supported' for c in coverage)


def _check_result_artifacts(job_dir, task_id, result, max_bytes):
    for artifact in result['artifacts']:
        rel = Path(artifact['path'])
        need(rel.as_posix() == artifact['path'] and not rel.is_absolute() and '..' not in rel.parts and
             rel.parts[:3] == ('artifacts', 'tasks', task_id), 'worker evidence escapes assigned task subtree')
        raw = _regular(job_dir / rel, max_bytes=max_bytes)
        need(digest(raw) == artifact['sha256'] and len(raw) == artifact['bytes'], 'worker evidence artifact changed')


def _result_artifacts(store, job, task, result):
    _check_result_artifacts(store.path, task['task_id'], result, job['policy']['max_artifact_bytes'])


def _agreement_content(state, row):
    """Recover legacy agreement binding only from its retained complete pass."""
    clearing = row.get('clearing') or {}
    if clearing.get('content_sha256'):
        return clearing['content_sha256']
    contents = {r['snapshot']['content_sha256'] for r in state.get('rounds', [])
                for p in r.get('passes', []) if p.get('execution_id') == clearing.get('execution_id')
                and p.get('lineage') == clearing.get('lineage')
                and p.get('outcome') in ('approved', 'adverse')
                and p.get('snapshot_sha256') == r['snapshot']['sha256']}
    return next(iter(contents)) if len(contents) == 1 else None


def _agreement_record(state, row):
    if row.get('clearing'):
        return deepcopy(row['clearing'])
    if row['finding']['severity'] not in ('minor', 'note'):
        return {}
    # Old minor/note accounts recorded agreements only in response history.
    # Recover the first agreement in the current uninterrupted agreement chain.
    entries = []
    for entry in reversed(row.get('history', [])):
        if entry.get('status') not in (None, 'rebuttal-agreed') or 'owner_decision' in entry:
            break
        if entry.get('status') == 'rebuttal-agreed':
            entries.append(entry)
    if not entries:
        return {}
    first = entries[-1]
    prior = {k: first.get(k) for k in ('mode', 'lineage', 'execution_id')}
    prior['disposition'] = 'rebuttal-agreed-by-' + str(prior['mode'])
    content = _agreement_content(state, {'clearing': prior})
    if content:
        prior['content_sha256'] = content
    return prior


def _responses(state, job, assessment, execution_id, family, child, mode):
    # An incomplete pass retains its evidence, but cannot partly resolve findings.
    findings = deepcopy(state['findings'])
    responses = assessment.get('responses', [])
    need(len({r['finding_key'] for r in responses}) == len(responses), 'duplicate finding response')
    for response in responses:
        key = response['finding_key']
        need(key in findings, 'response refers to unknown retained finding')
        row = findings[key]
        status = response.get('status')
        carry = status == 'rebuttal-agreed' and row['status'] == 'rebuttal-agreed'
        need(status in ('fixed', 'rebuttal-agreed', 'rejected', 'deferred', 'open') and response.get('evidence'), 'finding response needs disposition and evidence')
        if status == 'fixed':
            need(row['content_sha256'] != job['planning']['snapshot']['content_sha256'], 'unchanged content cannot claim a repair')
        if status == 'rebuttal-agreed':
            need(child and family not in ('unknown', '', None) and family == row['lineage'] and
                 execution_id != row['execution_id'], 'rebuttal needs counted fresh child from original reviewer lineage')
            if carry:
                previous = _agreement_record(state, row)
                need(previous.get('lineage') == family and previous.get('mode') != 'self-review' and
                     previous.get('disposition') == 'rebuttal-agreed-by-' + str(previous.get('mode')) and
                     previous.get('execution_id') and previous['execution_id'] != execution_id,
                     'carried rebuttal lacks original independent clearing')
                need(_agreement_content(state, {'clearing': previous}) == job['planning']['snapshot']['content_sha256'],
                     'carried rebuttal needs unchanged content and retained agreement binding')
                if not row.get('clearing'):
                    row['clearing'] = previous
            else:
                need(row['status'] == 'rejected', 'no recorded coordinator rebuttal to accept')
        if status == 'deferred':
            need(all(response.get(k) for k in ('impact', 'owner', 'next_action')), 'deferral needs impact, owner and next action')
        clearing = {'mode': mode, 'lineage': family, 'execution_id': execution_id,
                    'disposition': status + '-by-' + mode,
                    'content_sha256': job['planning']['snapshot']['content_sha256']}
        row['history'].append(dict(response, execution_id=execution_id, mode=mode, lineage=family))
        if status in ('fixed', 'rebuttal-agreed'):
            if not carry:
                row['clearing'] = clearing
        else:
            row.pop('clearing', None)
        row['status'] = status
    state['findings'] = findings


def check_draft(brief_file, brief_sha256, result_file):
    """Task-scoped diagnostics only. Never opens a job/subject store or accepts work."""
    brief_path = Path(brief_file)
    need(brief_path.is_absolute() and '..' not in brief_path.parts and brief_path.parent.name == 'briefs',
         'draft check requires an absolute immutable job brief path')
    raw_brief = _regular(brief_path)
    need(digest(raw_brief) == brief_sha256, 'immutable draft brief hash differs')
    brief = strict_load(raw_brief)
    need(isinstance(brief, dict), 'draft brief must be an object')
    claimed = brief.pop('effective_brief_sha256')
    need(digest(canonical(brief)) == claimed, 'immutable draft brief content hash differs')
    resources = brief.get('resources')
    need(isinstance(resources, dict), 'draft brief resources must be an object')
    snapshot = resources.get('planning_snapshot')
    need(brief.get('role') == 'review' and not brief.get('document') and isinstance(snapshot, dict),
         'draft checks require a planning review, never a document-only/cold-read slot')
    task_id = component(brief['task_id'])
    need(brief.get('write_scope') == {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task_id},
         'draft check lacks an assigned evidence subtree')
    job_dir = brief_path.parent.parent
    draft_path = Path(result_file)
    need(draft_path.is_absolute() and '..' not in draft_path.parts and
         draft_path.is_relative_to(job_dir / 'artifacts' / 'tasks' / task_id),
         'draft file escapes assigned task subtree')
    expected = {k: brief[k] for k in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id')}
    expected.update(effective_brief_sha256=claimed, role='review', revision=brief['revision'],
                    binding=brief['snapshot'], task_id=task_id,
                    requirements=[r['id'] for r in brief['requirements']])
    job = {'requirements': snapshot['requirements'], 'planning': {'snapshot': snapshot}}
    state = {'findings': deepcopy(brief['resources'].get('prior_findings', {}))}
    selection = brief.get('model_selection')
    need(isinstance(selection, dict) and selection.get('lineage') and selection.get('mode'),
         'draft brief lacks frozen reviewer lineage/mode')
    family, mode = selection['lineage'], selection['mode']
    deferred = ['current_job_subject_and_pins', 'host_identity_options_and_fresh_execution',
                'authoritative_finding_history', 'acceptance_and_remaining_budgets']
    checks, errors = ['brief_hash_and_task_scope'], []
    try:
        result = parse_result(_regular(draft_path, max_bytes=32768), expected, job_dir)['result']
        checks.append('result_contract_and_correlation')
        problems, _ = _retain_findings(state, job, result['findings'], 'draft:' + task_id, family)
        need(not problems, '; '.join(problems))
        checks.append('planning_finding_fields')
        _coverage(job, result.get('planning_review') or {})
        checks.append('coverage_and_declared_reads')
        _check_result_artifacts(job_dir, task_id, result, 16 * 1024 * 1024)
        checks.append('assigned_artifacts')
        assessment = deepcopy(result['planning_review'])
        responses = assessment.get('responses', [])
        need(len({r['finding_key'] for r in responses}) == len(responses), 'duplicate finding response')
        for response in responses:
            try:
                _responses(state, job, dict(assessment, responses=[response]), 'draft:' + task_id,
                           family, True, mode)
            except PlanningError as exc:
                row = state['findings'].get(response['finding_key'], {})
                # No full legacy ledger in the brief. Check other guards, but do
                # not invent its missing content proof or request a fake response.
                if (str(exc) == 'carried rebuttal needs unchanged content and retained agreement binding' and
                        not (row.get('clearing') or {}).get('content_sha256')):
                    deferred.append('legacy_carry_provenance:' + response['finding_key'])
                else:
                    raise
        checks.append('available_finding_response_transitions')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return {'kind': 'planning-draft-diagnostic', 'valid': not errors, 'errors': errors,
            'brief_sha256': brief_sha256, 'checks': checks, 'deferred_checks': deferred,
            'acceptance': False, 'artifact_byte_limit': 16 * 1024 * 1024}


def _adverse(state):
    return [key for key, row in state['findings'].items() if row['finding']['severity'] in ('blocker', 'major')
            and row['status'] not in ('fixed', 'rebuttal-agreed', 'owner-decided', 'waived')]


def _progress(store, job, state):
    """A derived warning, never acceptance, dispatch permission or a budget grant."""
    rounds = state['rounds']
    charged = [r for r in rounds if r.get('charged')]
    latest = rounds[-1] if rounds else None
    incomplete = unchanged = technical = 0
    content = charged[-1]['snapshot']['content_sha256'] if charged else None
    for round_ in reversed(charged):
        passes = round_['passes']
        if not passes or not any(p['outcome'] == 'incomplete' for p in passes):
            break
        incomplete += 1
    for round_ in reversed(charged):
        if (round_['snapshot']['content_sha256'] != content or not round_['passes'] or
                all(p['outcome'] == 'approved' for p in round_['passes'])):
            break
        unchanged += 1
    trailing_attempts = []
    for round_ in reversed(rounds):
        if round_['passes']:
            break  # A substantive pass, including direct fallback, ends a technical streak.
        trailing_attempts.extend(reversed(round_['attempts']))
    for attempt in trailing_attempts:
        if attempt['outcome'] != 'unavailable':
            break
        technical += 1
    budgets = {name: {'used': state[used], 'limit': state[limit],
                      'remaining': max(0, state[limit] - state[used])}
               for name, used, limit in (('content', 'rounds_used', 'round_limit'),
                                         ('technical', 'technical_used', 'technical_limit'))}
    signals = []
    if any(not budget['remaining'] for budget in budgets.values()):
        signals.append('budget_exhausted')
    if incomplete >= 2:
        signals.append('consecutive_incomplete_rounds')
    if unchanged >= 2:
        signals.append('unchanged_content_without_complete_approval')
    if technical >= 2:
        signals.append('consecutive_unavailable_attempts')
    owns_subject = state['active_job'] == {'job_id': job['job_id'], 'state_root': str(store.root)}
    prepared = {a['task_id'] for a in job['planning']['attempts'] if a['outcome'] is None}
    unsettled = [t['task_id'] for t in job['tasks'] if t['task_id'] in prepared or _unsettled(job, t)]
    if not owns_subject:
        action = 'inspect_active_job' if state['active_job'] else 'subject_released'
    elif unsettled:
        action = 'reconcile_owned_work'
    elif latest and not latest['closed'] and latest['passes']:
        action = 'finish_current_round'
    elif latest and latest.get('result') and all(p['outcome'] == 'approved' for p in latest['passes']):
        action = 'inspect_existing_receipt'
    elif signals:
        action = 'diagnose_before_dispatch'
    elif latest and latest.get('result'):
        action = 'repair_then_begin'
    else:
        action = 'continue_within_existing_authority'
    return {'kind': 'planning-progress-diagnostic', 'acceptance': False,
            'job_id': job['job_id'], 'logical_output_id': state['logical_output_id'],
            'subject_sha256': state['sha256'], 'active_job': deepcopy(state['active_job']),
            'budgets': budgets, 'stop_recommended': bool(signals), 'signals': signals,
            'consecutive_incomplete_rounds': incomplete,
            'unchanged_content_rounds_without_complete_approval': unchanged,
            'consecutive_unavailable_attempts': technical, 'unsettled_tasks': unsettled,
            'next_action': action, 'open_adverse_findings': len(_adverse(state)),
            'latest_round': None if latest is None else {
                'number': latest['number'], 'charged': latest['charged'], 'closed': latest['closed'],
                'receipt': deepcopy(latest.get('result')),
                'passes': [{k: p.get(k) for k in ('task_id', 'slot_id', 'outcome', 'error')}
                           for p in latest['passes']]},
            'delivery_and_spend': {'value': None,
                'reason': 'Planning records do not measure implementation, deployment, tokens or monetary cost.'}}


def progress(store, caller, environ=None):
    """Inspect the persistent subject without writing job, findings or counters."""
    job = verify_all_pins(store, caller)
    manifest_policy(job)
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        need(state is not None, 'planning subject is missing')
        return _progress(store, job, state)


def ingest(store, caller, task_id, raw, completion_id, environ=None):
    """Strict generic ingestion plus persistent partial findings and domain coverage.

    Invalid envelopes/coverage are incomplete, complete disagreement is adverse.
    The original transport is retained by the existing job result machinery.
    """
    job = verify_all_pins(store, caller)
    manifest_policy(job)
    task = next(t for t in job['tasks'] if t['task_id'] == task_id)
    attempt = next(a for a in job['planning']['attempts'] if a['task_id'] == task_id)
    need(attempt['outcome'] is None, 'attempt outcome already retained; cannot reclassify adverse to incomplete')
    expected = _expected(job, task)
    # Check host terminal state before consuming any substantive response.
    from shared.job_acceptance import review_handle
    handle = review_handle(task)
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        need(not state['rounds'][-1]['closed'], 'round is closed')
        subject_attempt = _subject_attempt(state, task)
        _charge(state)
        subject.save(state)
        record_result(store, caller, task_id, {'request_id': task['request_id'], 'completion_id': completion_id, 'result': raw})
        fresh = store.load()
        task = next(t for t in fresh['tasks'] if t['task_id'] == task_id)
        complete = False
        error = None
        result = None
        identity_error = None
        finding_errors = []
        finding_collisions = []
        try:
            _completed_identity(fresh, task)
            previous = [p for r in state['rounds'] for p in r['passes']]
            previous += [h for r in state['rounds'] for a in r['attempts'] for h in a.get('owned_handles', [])]
            need(not any(handle['task_id'] == p.get('execution_id', p.get('task_id')) or
                         handle['child_thread_id'] == p.get('child_thread_id') for p in previous),
                 'review must use a fresh owned execution across replacement jobs')
        except ValueError as exc:
            identity_error = str(exc)
        try:
            parsed = parse_result(raw, expected, store.path, job['policy']['max_artifact_bytes'])
            result = parsed['result']
        except (ResultError, JobError) as exc:
            error = str(exc)
            # Preserve recognisable findings from a correlated partial object.
            # This is adverse-history salvage, never acceptance or parser feature evidence.
            try:
                partial = strict_load(raw)
            except JobError:
                partial = None
            if isinstance(partial, dict) and all(partial.get(k) == v for k, v in expected.items()
                    if k in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256')):
                finding_errors, finding_collisions = _retain_findings(state, job, partial.get('findings', []), handle['task_id'], 'unknown' if identity_error else attempt['lineage'])
                if finding_errors:
                    error += '; ' + '; '.join(finding_errors)
        if result:
            finding_errors, finding_collisions = _retain_findings(state, job, result['findings'], handle['task_id'], 'unknown' if identity_error else attempt['lineage'])
            try:
                need(not finding_errors, '; '.join(finding_errors))
                good_coverage = _coverage(job, result.get('planning_review') or {})
                _result_artifacts(store, job, task, result)
                need(identity_error is None, identity_error or '')
                _responses(state, job, result.get('planning_review') or {}, handle['task_id'], attempt['lineage'], True, attempt['mode'])
                complete = True
            except (JobError, KeyError, TypeError) as exc:
                error = str(exc)
                good_coverage = False
        if not complete:
            outcome = 'incomplete'
        else:
            outcome = ('approved' if result['review_verdict'] == 'approve' and good_coverage and
                       result['status'] == 'ready-for-acceptance' and not _adverse(state) and
                       all(r['status'] == 'passed' for r in result['requirements']) else 'adverse')
        pass_ = {'slot_id': attempt['slot_id'], 'task_id': task_id, 'request_id': task['request_id'],
                 'execution_id': handle['task_id'], 'child_thread_id': handle['child_thread_id'],
                 'mode': attempt['mode'], 'lineage': attempt['lineage'], 'outcome': outcome, 'error': error,
                 'finding_collisions': finding_collisions,
                 'selection_sha256': job['model_selection_sha256'], 'snapshot_sha256': job['planning']['snapshot']['sha256'],
                 'transport_sha256': digest(raw), 'inspected_paths': (result or {}).get('planning_review', {}).get('inspected_paths', [])}
        options = [e[name]['options'] for e in task.get('dispatch_history', [])
                   for name in ('status_identity', 'receipt_identity', 'configuration_identity')
                   if isinstance(e.get(name), dict) and 'options' in e[name]]
        pass_.update(requested_target=task['target'], observed_identity=handle.get('observed_identity'),
                     observed_options=options or None, options_status='matched' if options and not identity_error else 'unreported' if not options else 'mismatched')
        def apply(j):
            next(a for a in j['planning']['attempts'] if a['task_id'] == task_id)['outcome'] = outcome
            j['planning']['passes'].append(pass_)
        store.transact(caller, apply)
        state['rounds'][-1]['passes'].append(pass_)
        subject_attempt['outcome'] = outcome
        subject.save(state)
        return pass_


def direct(store, caller, observation, sharing=None, environ=None):
    """A separate, real coordinator self-review. No child-shaped fields accepted."""
    job = verify_all_pins(store, caller)
    manifest_policy(job)
    from core.schema import errors, load_schema_file
    problems = errors(observation, load_schema_file(Path(__file__).parent / 'agents/planning-direct.schema.json'))
    need(not problems, 'invalid direct planning observation: ' + '; '.join(problems[:3]))
    prior = job['planning']['passes']
    need(not any(p['mode'] == 'self-review' for p in prior), 'only one combined self-review per round')
    need(not any(_unsettled(job, t) for t in job['tasks']), 'pending/uncertain tasks block direct review')
    record = models.validate(job['model_selection'], job['model_selection_sha256'])
    child_slots = {p['slot_id'] for p in prior}
    slots = [s for s in record['review_panel'] if s['required'] and s['slot_id'] not in child_slots]
    need(slots, 'no uncovered required slots for self-review')
    # Cover only uncovered slots, preserving all child passes, including adverse.
    for slot in slots:
        need(not slot.get('independent', True), 'stronger selected independent slot refuses self-review')
        actual_target = {k: deepcopy(v) for k, v in record['coordinator'].items()
                         if k in ('providerInstanceId', 'model', 'options', 'runtimeMode')}
        actual_target['execution'] = 'current-context'
        _family(record, actual_target, slot['role'])
        need(next_candidate(job, slot['slot_id'], sharing) is None, 'suitable child reviewers remain available')
        permitted = [r for r in record['review_replacements'] if r.get('execution') == 'self-review' and r.get('slot_id') == slot['slot_id']]
        need(len(permitted) == 1, 'self-review fallback permission missing')
        grant = permitted[0]['authority']
        models._authority(grant)
        models._authority_target(grant, record['coordinator'], record)
        need(set(job['planning']['data_classes']) <= set(grant['data_classes']), 'direct fallback sharing exceeds authority')
    need(observation['snapshot_sha256'] == job['planning']['snapshot']['sha256'] and
         observation['selection_sha256'] == record['selection_sha256'], 'direct observation content/selection mismatch')
    identity = observation['identity']
    need(models.key(identity) == models.key(record['coordinator']) and
         identity.get('observed_options') == record['coordinator'].get('observed_options'), 'direct actual coordinator identity/settings mismatch')
    need(observation['identity_reference'], 'direct identity needs actual session source')
    need({o['id'] for o in observation['requirements']} == set(job['requirements']) and
         len(observation['requirements']) == len(job['requirements']) and
         all(o.get('evidence') and o.get('status') in ('passed', 'failed', 'unverified') for o in observation['requirements']), 'direct requirement outcome coverage incomplete')
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        need(not state['rounds'][-1]['closed'], 'round is closed')
        _charge(state)
        family = _identity_lineage(record, identity)
        execution_id = observation['pass_id']
        need(not any(p['execution_id'] == execution_id for r in state['rounds'] for p in r['passes']), 'direct pass ID reused')
        finding_errors, finding_collisions = _retain_findings(state, job, observation['findings'], execution_id, family)
        # Preserve findings/charge even when coverage or responses fail.
        subject.save(state)
        error = None
        try:
            need(not finding_errors, '; '.join(finding_errors))
            supported = _coverage(job, observation['assessment'])
            _responses(state, job, observation['assessment'], execution_id, family, False, 'self-review')
        except (JobError, KeyError, TypeError) as exc:
            supported = False
            error = str(exc)
        adverse = _adverse(state) or any(f['severity'] in ('blocker', 'major') for f in observation['findings'])
        approved = (observation['review_verdict'] == 'approve' and supported and not adverse and
                    all(o['status'] == 'passed' for o in observation['requirements']))
        path = store.path / 'direct' / (digest(execution_id.encode()) + '.json')
        _retain(path, canonical(observation), 'direct observation is immutable')
        pass_ = {'slot_id': None, 'execution_id': execution_id, 'mode': 'self-review', 'lineage': family,
                 'covered_slot_ids': sorted(s['slot_id'] for s in slots),
                 'outcome': 'incomplete' if error else 'approved' if approved else 'adverse',
                 'error': error, 'observation': file_descriptor(path),
                 'finding_collisions': finding_collisions,
                 'selection_sha256': record['selection_sha256'], 'snapshot_sha256': observation['snapshot_sha256'],
                 'inspected_paths': observation['assessment']['inspected_paths'],
                 'sharing': deepcopy(effective_sharing(job)),
                 'availability': {s['slot_id']: exclusions(job, s['slot_id'], sharing) for s in slots}}
        store.transact(caller, lambda j: j['planning']['passes'].append(pass_) and None)
        state['rounds'][-1]['passes'].append(pass_)
        subject.save(state)
        return pass_


def disposition(store, caller, finding_key, status, evidence, environ=None):
    job = verify_all_pins(store, caller)
    need(status in ('rejected', 'deferred', 'open'), 'repairs/rebuttal agreements require a counted fresh review')
    need(evidence.get('reason') and evidence.get('source'), 'disposition requires evidence and reason')
    source = file_descriptor(evidence['source'])
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        need(finding_key in state['findings'], 'unknown finding')
        if status == 'deferred':
            need(all(evidence.get(k) for k in ('impact', 'owner', 'next_action')), 'deferral needs impact/owner/next action')
        row = state['findings'][finding_key]
        row['status'] = status
        row.pop('clearing', None)
        row['history'].append({'status': status, 'evidence': evidence, 'source': source})
        subject.save(state)
        return deepcopy(row)


def owner_decision(store, caller, decision, environ=None):
    """Scoped actual owner source. No automatic waivers or implied authority."""
    job = verify_all_pins(store, caller)
    models.source(decision['source'])
    source_file = file_descriptor(decision['source_file'])
    need(decision['source']['answer'] in _regular(Path(source_file['path'])).decode('utf-8'), 'owner quote differs from source bytes')
    subject = _subject(job, environ)
    need(not Path(source_file['path']).is_relative_to(store.path) and
         not Path(source_file['path']).is_relative_to(subject.store.path), 'owner decision source must be outside worker/subject state')
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        need(decision.get('logical_output_id') == state['logical_output_id'], 'owner decision belongs to another subject')
        if decision['kind'] == 'limit-increase':
            increases = {k: decision[k] for k in ('round_limit', 'technical_limit') if k in decision}
            need(increases and all(type(v) is int and v > state[k] for k, v in increases.items()), 'explicit limit increase required')
            state.update(increases)
            if 'technical_limit' in increases:
                def apply(j):
                    j['planning']['technical_limit'] = increases['technical_limit']
                    j['policy']['max_repair_cycles'] = increases['technical_limit']
                store.transact(caller, apply)
        else:
            need(decision['kind'] in ('finding-decision', 'finding-waiver') and decision.get('finding_key') in state['findings'], 'scoped finding decision required')
            row = state['findings'][decision['finding_key']]
            row['status'] = 'waived' if decision['kind'] == 'finding-waiver' else 'owner-decided'
            if row['finding']['severity'] in ('blocker', 'major'):
                row['clearing'] = {'mode': 'owner-decision', 'lineage': None,
                                   'disposition': row['status'], 'source': deepcopy(decision['source'])}
            row['history'].append({'owner_decision': decision, 'source_file': source_file})
        state['decisions'].append(dict(decision, source_file=source_file))
        subject.save(state)
        return deepcopy(state['decisions'][-1])


def _panel_coverage(passes, required):
    """Return exact per-slot modes; a single direct pass may cover a subset."""
    modes = {}
    direct_count = 0
    for pass_ in passes:
        if pass_['mode'] == 'self-review':
            direct_count += 1
            slots = pass_.get('covered_slot_ids', [])
            need(pass_['slot_id'] is None and direct_count == 1 and slots,
                 'invalid combined self-review coverage')
        else:
            slots = [pass_['slot_id']]
        for slot in slots:
            need(slot in required and slot not in modes, 'duplicate or arbitrary panel slot coverage')
            modes[slot] = pass_['mode']
    return modes


def finish_round(store, caller, environ=None):
    """Close adverse/incomplete rounds for repair, or issue a consumable receipt."""
    job = verify_all_pins(store, caller)
    manifest_policy(job)
    need(not any(_unsettled(job, t) for t in job['tasks']), 'pending/uncertain tasks block completion')
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        round_ = state['rounds'][-1]
        need(not round_['closed'] and round_['number'] == job['planning']['round'], 'no active content round')
        passes = job['planning']['passes']
        need(passes == round_['passes'] and passes, 'missing or partial persisted review evidence')
        required = {s['slot_id'] for s in job['model_selection']['review_panel'] if s['required']}
        modes = _panel_coverage(passes, required)
        accepted = (all(p['outcome'] == 'approved' for p in passes) and not _adverse(state) and
                    set(modes) == required)
        evidence_errors = []
        for p in passes:
            try:
                check_snapshot(job['planning']['snapshot'], p['inspected_paths'])
            except (JobError, OSError) as exc:
                accepted = False
                evidence_errors.append(str(exc))
        receipt = seal({'schema_version': 1, 'purpose': 'planning-review', 'accepted': accepted,
            'job_id': job['job_id'], 'subject_file': str(subject.file), 'logical_output_id': state['logical_output_id'],
            'snapshot': job['planning']['snapshot'], 'policy_sha256': job['planning']['policy_sha256'],
            'selection_sha256': job['model_selection_sha256'], 'round_number': round_['number'],
            'requested_panel': deepcopy(job['model_selection']['review_panel']),
            'validator_sha256': digest(_regular(Path(__file__))),
            'sharing_revocations': deepcopy(state['sharing_revocations']),
            'rounds_used': state['rounds_used'], 'round_limit': state['round_limit'], 'technical_used': state['technical_used'],
            'passes': passes, 'slot_modes': modes, 'requested_slots': sorted(required), 'degraded_panel': any(
                p['mode'] != 'cross-lineage' for p in passes), 'open_adverse_findings': _adverse(state),
            'evidence_errors': evidence_errors,
            'round_history': [{k: deepcopy(r[k]) for k in ('number', 'charged', 'passes', 'attempts')}
                              for r in state['rounds']],
            'findings': deepcopy(state['findings']), 'owner_decisions': deepcopy(state['decisions']),
            'job_file': str(store.file), 'job_sha256': digest(canonical(job))})
        path = store.path / 'planning-acceptance' / (receipt['sha256'] + '.json')
        _retain(path, canonical(receipt), 'planning receipt changed')
        reference = file_descriptor(path)
        round_.update(closed=True, result=reference)
        state['receipts'].append(reference)
        subject.save(state)
        return {'reference': reference, 'accepted': accepted, 'progress': _progress(store, job, seal(state))}


def validate_receipt(reference, *, expected_snapshot=None, environ=None):
    """Parent-facing validator. Re-read actual job, passes and subject, not flags."""
    current_file(reference)
    receipt = unseal(strict_load(_regular(Path(reference['path']))))
    need(receipt['purpose'] == 'planning-review' and receipt['accepted'], 'no accepted planning review')
    if expected_snapshot is not None:
        need(receipt['snapshot']['sha256'] == expected_snapshot, 'receipt belongs to different reviewed content')
    file = Path(receipt['job_file'])
    store = pinned_store(file.parent.parent, file.parent.name)
    job = verify_all_pins(store)
    manifest_policy(job)
    need(digest(canonical(job)) == receipt['job_sha256'], 'producing planning job changed')
    need(receipt['validator_sha256'] == digest(_regular(Path(__file__))), 'planning acceptance validator changed')
    models.validate(job['model_selection'], receipt['selection_sha256'])
    subject = _subject(job, environ)
    with subject.transaction() as state:
        need(reference in state['receipts'], 'receipt not retained by authoritative subject')
        need(not _adverse(state), 'retained adverse finding blocks readiness')
        round_ = next(r for r in state['rounds'] if r['number'] == receipt['round_number'])
        need(round_['closed'] and round_['result'] == reference and round_['passes'] == receipt['passes'], 'receipt round correlation differs')
        # Replacement jobs share the subject's assessment history. A charged
        # re-review supersedes earlier evidence immediately for that snapshot;
        # an unavailable candidate or technical-only stop does not.
        need(not any(r['number'] > round_['number'] and r.get('charged') and
                     r['snapshot']['sha256'] == receipt['snapshot']['sha256']
                     for r in state['rounds']), 'later substantive review supersedes this receipt')
        required = {s['slot_id'] for s in job['model_selection']['review_panel'] if s['required']}
        modes = _panel_coverage(receipt['passes'], required)
        need(set(modes) == required and receipt['slot_modes'] == modes and
             receipt['requested_slots'] == sorted(required) and
             all(p['outcome'] == 'approved' for p in receipt['passes']), 'required panel coverage differs')
        for decision in receipt['owner_decisions']:
            current_file(decision['source_file'])
        for revocation in receipt['sharing_revocations']:
            current_file(revocation['source_file'])
        for row in state['findings'].values():
            for history in row['history']:
                if history.get('source'):
                    current_file(history['source'])
        for pass_ in receipt['passes']:
            check_snapshot(receipt['snapshot'], pass_['inspected_paths'])
            if pass_['mode'] == 'self-review':
                current_file(pass_['observation'])
                observation = strict_load(_regular(Path(pass_['observation']['path'])))
                need(observation['snapshot_sha256'] == receipt['snapshot']['sha256'], 'direct observation belongs to another revision')
                need(not any(_unsettled(job, t) for t in job['tasks']), 'owned work became pending')
                for slot in pass_['covered_slot_ids']:
                    need(pass_['availability'][slot] == exclusions(job, slot, pass_['sharing']) and
                         next_candidate(job, slot, pass_['sharing']) is None,
                         'direct fallback availability evidence no longer matches')
            else:
                task = next(t for t in job['tasks'] if t['task_id'] == pass_['task_id'])
                handle = _completed_identity(job, task)
                need(handle['task_id'] == pass_['execution_id'] and handle['child_thread_id'] == pass_['child_thread_id'], 'host execution correlation differs')
                raw = _regular(Path(task['result_ref']['transport_path']), max_bytes=32768)
                need(digest(raw) == pass_['transport_sha256'], 'accepted worker result changed')
                parsed = parse_result(raw, _expected(job, task), store.path, job['policy']['max_artifact_bytes'])
                need(parsed['sha256'] == task['result_ref']['sha256'], 'accepted result artifact changed')
                _coverage(job, parsed['result']['planning_review'])
                _result_artifacts(store, job, task, parsed['result'])
        return receipt


def release(store, caller, environ=None):
    """Release a completed/stopped job without erasing subject history or budget."""
    job = verify_all_pins(store, caller)
    need(not any(_unsettled(job, t) for t in job['tasks']), 'live/uncertain jobs cannot be replaced')
    need(not any(a['outcome'] is None for a in job['planning']['attempts']),
         'prepared attempt needs same-request reconciliation before release')
    subject = _subject(job, environ)
    with subject.transaction() as state:
        _unchanged(store, job)
        _active(state, store)
        if state['rounds'] and not state['rounds'][-1]['closed']:
            round_ = state['rounds'][-1]
            need(not round_['passes'] and not round_.get('charged') and
                 all(a['outcome'] == 'unavailable' for a in round_['attempts']),
                 'unfinished content round cannot be replaced')
            round_.update(closed=True, result=None, stopped='technical-only stop; no content assessment')
        state['active_job'] = None
        subject.save(state)
        return {'released': job['job_id'], 'rounds_used': state['rounds_used'], 'findings': deepcopy(state['findings'])}
