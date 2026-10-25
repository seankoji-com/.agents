#!/usr/bin/env python3
"""Explicit owner delegation, revision approvals and the pinned commit guard.

No dispatch or human-authentication claim. Native observations are retained host
provenance under the same trusted coordinator/source boundary as direct approval.
Derived decisions never claim to be the owner's literal per-revision answer.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
from pathlib import Path
import sys

import study as fg
from core.jobs.store import JobError, _regular, canonical, digest, strict_load

OPERATIONS = ['create', 'plan-revision', 'prepare', 'acceptance']


def need(ok, message):
    if not ok:
        fg.refuse('delegated_authority_invalid', message)


def descriptor(path):
    path = Path(path)
    raw = _regular(path)
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


def reopen(row, study=None):
    need(isinstance(row, dict) and Path(row['path']).is_absolute(), 'absolute authority evidence path required')
    path = Path(row['path'])
    if study is not None:
        need(not path.resolve().is_relative_to(study.job_dir.resolve()), 'owner evidence must be outside job/worker scopes')
    raw = _regular(path)
    need(digest(raw) == row['sha256'] and len(raw) == row['bytes'], 'authority evidence bytes changed')
    return raw


def owner_source(study, owner):
    need(isinstance(owner, dict) and owner.get('id') and owner.get('message_ref'), 'real owner identity/reference required')
    raw = reopen(owner['source'], study)
    # Full contextual bytes are retained. Neither hash nor metadata authenticates
    # a person; the caller must genuinely record an owner-authorized grant.
    need(owner.get('context') == raw.decode('utf-8') and owner.get('quote') and owner['quote'] in owner['context'],
         'retain the full original owner context and verbatim authority quote')
    native = strict_load(reopen(owner['native_observation'], study))
    records = owner.get('native_messages')
    need(isinstance(records, list) and records and all(isinstance(r, dict) and
         r.get('messageId') and r.get('creationSource') for r in records), 'native message IDs/creationSource required')
    # Retain the complete observation, not a new claim of cryptographic proof.
    def contains(value, expected):
        if isinstance(value, dict):
            return all(value.get(k) == v for k, v in expected.items()) or any(contains(v, expected) for v in value.values())
        return isinstance(value, list) and any(contains(v, expected) for v in value)
    need(all(contains(native, r) for r in records), 'native provenance not present in retained observation')
    for amendment in owner.get('amendments', []):
        amended = reopen(amendment['source'], study).decode('utf-8')
        need(amendment.get('context') == amended and amendment.get('quote') and amendment['quote'] in amended,
             'owner amendment source/context/quote changed')


def retained(plan):
    return {k: copy.deepcopy(v) for k, v in plan.items() if k not in ('mode', 'limits')}


def chain(study, folder):
    rows = []
    base = study.dir / folder
    for n, path in enumerate(sorted(base.glob('*.json')) if base.exists() else []):
        row = study.read(str(path.relative_to(study.dir)))
        need(path.name == f'{n:04d}.json' and row.get('sequence') == n and
             row.get('previous_record_sha256') == (rows[-1]['record_sha256'] if rows else None) and
             row.get('record_sha256') == fg.sha({k:v for k,v in row.items() if k != 'record_sha256'}),
             'authority append-only chain is invalid')
        rows.append(row)
    return rows


def append(study, folder, body):
    rows = chain(study, folder)
    row = dict(copy.deepcopy(body), sequence=len(rows),
               previous_record_sha256=rows[-1]['record_sha256'] if rows else None)
    row['record_sha256'] = fg.sha(row)
    study.retain(f'{folder}/{len(rows):04d}.json', row, 'authority history changed')
    return row


def grant(study, data, now=None):
    """Explicit coordinator recording of a real contextual owner grant, not inference."""
    with study.locked():
        revision = study.require()['revision']; plan = study.plan(revision)['plan']
        fg.safe_id(data.get('id'), 'grant id')
        need(not any(r['id'] == data['id'] for r in chain(study, 'authority/grants')), 'grant ID already used')
        owner_source(study, data['owner'])
        need(data.get('delegate', {}).get('id') and isinstance(data['delegate'].get('caller'), dict), 'bound delegate/caller required')
        limits = data['constraints']
        need(limits.get('product_writes') is False and set(limits.get('modes', [])) <= set(fg.MODES) and
             limits.get('modes') and plan['mode'] in limits['modes'], 'only explicitly bounded existing modes, no product writes')
        for key in ('max_tasks', 'max_concurrency', 'max_attempts_per_slot', 'max_repair_cycles'):
            need(type(limits.get(key)) is int and limits[key] >= (0 if key == 'max_repair_cycles' else 1), 'invalid grant bound: '+key)
        fg.parse_time(limits['deadline'], 'grant deadline')
        expires = fg.parse_time(data['expires_at'], 'grant expiry')
        moment = fg.utc_now(now)
        need(moment < expires <= fg.parse_time(limits['deadline'], 'deadline'), 'grant expiry must be future and within its deadline')
        review = data.get('review')
        need(isinstance(review, dict) and review.get('providerInstanceId') and review.get('model') and
             isinstance(review.get('options'), dict), 'owner-selected exact independent reviewer required')
        review_source = data.get('review_source', data['owner']['source'])
        need(review_source in [data['owner']['source']] + [r['source'] for r in data['owner'].get('amendments', [])],
             'review choice must retain its actual original or amended owner source')
        identity = data.get('package', {})
        need(identity.get('installation_id') and identity.get('dependency_key') and
             all(fg.HEX64.fullmatch(str(identity.get(k, ''))) for k in ('package_digest', 'bundle_digest')),
             'exact installed package/adoption identity required')
        body = {**data, 'schema_version':1, 'kind':'owner-delegation', 'review_source':review_source,
            'base_limits':copy.deepcopy(plan['limits']),
            'study_id':study.id, 'study_root':str(study.root), 'retained_sha256':fg.sha(retained(plan)),
            'created_at':fg.stamp(moment)}
        bounds(study, body, plan, study.ledger(), None, moment)
        return append(study, 'authority/grants', body)


def find_grant(study, grant_id):
    row = next((r for r in chain(study, 'authority/grants') if r['id'] == grant_id), None)
    need(row is not None, 'unknown grant')
    need(not any(r['grant_id'] == grant_id for r in chain(study, 'authority/revocations')), 'grant revoked')
    return row


def revoke(study, data, now=None):
    with study.locked():
        grant_row = find_grant(study, data['grant_id'])
        owner_source(study, data['owner'])
        need(data['owner']['id'] == grant_row['owner']['id'], 'revocation owner differs')
        return append(study, 'authority/revocations', {'kind':'revocation','grant_id':data['grant_id'],
            'owner':data['owner'],'reason':fg.text(data.get('reason'), 'revocation reason'), 'at':fg.stamp(fg.utc_now(now))})


def bounds(study, grant_row, plan, ledger, job, now):
    owner_source(study, grant_row['owner'])
    need(grant_row['study_id'] == study.id and grant_row['study_root'] == str(study.root), 'grant study binding differs')
    need(fg.sha(retained(plan)) == grant_row['retained_sha256'], 'retained panel/options/sharing/material or protocol changed')
    limits = grant_row['constraints']
    need(plan['mode'] in limits['modes'], 'mode outside owner grant')
    need(not ledger['cancel_requested'] and not ledger.get('deadline_expired'), 'study cancellation/deadline hold')
    need(fg.ceiling(plan, ledger)['max_tasks'] <= limits['max_tasks'] and sum(ledger['charged'].values()) <= limits['max_tasks'], 'lifetime ceiling exceeded')
    for key in ('max_concurrency', 'max_attempts_per_slot'):
        need(plan['limits'][key] <= limits[key], 'dynamic plan exceeds '+key)
    need(plan['limits']['hard_stop_required'] == grant_row['base_limits']['hard_stop_required'], 'hard-stop policy changed')
    for key in fg.POOLS.values():
        need(plan['limits'][key] <= grant_row['base_limits'][key], 'shared repair pool exceeds grant: '+key)
    need(fg.parse_time(plan['limits']['deadline'], 'deadline') <= fg.parse_time(limits['deadline'], 'grant deadline'), 'deadline exceeds owner grant')
    # Per-input attempts and total charges are retained by admission; refuse a
    # changed current ledger as well, never refund/reset it to fit a grant.
    for attempts in ledger.get('slots', {}).values():
        need(type(attempts) is int and 0 <= attempts <= limits['max_attempts_per_slot'], 'per-input attempts exceed owner grant')
    open_requests = [r for r in ledger['requests'].values() if r.get('state') == 'open']
    need(len(open_requests) <= limits['max_concurrency'], 'live study concurrency exceeds grant')
    if job is not None:
        need(job['policy']['max_repair_cycles'] <= limits['max_repair_cycles'] and
             job['policy'].get('max_live_workers') is not None and
             job['policy']['max_live_workers'] <= limits['max_concurrency'], 'generic job bounds exceed grant')
        lifecycle = fg.lifecycle_module()
        occupancy = lifecycle.occupied_work(lifecycle.reconcile_view(study, plan, ledger, job, None))
        need(occupancy['count'] <= limits['max_concurrency'], 'unresolved owned work exceeds concurrency')
    need(not fg.rehash_stimulus(plan), 'approved material changed')
    fg.evidence_module().require_pack(study, plan)
    fg.recorded_carry(study, fg.sha(plan))
    # Expiry is the last live authority predicate, checked again at persistence.
    need(now < fg.parse_time(grant_row['expires_at'], 'expiry') and
         now < fg.parse_time(plan['limits']['deadline'], 'deadline'), 'grant or plan expired')


def reviewed(study, revision, grant_row):
    fg.planning_gate(study, revision)  # validates real pinned receipt, history, findings and identity
    desc = fg.planning_module().descriptor(study, revision)
    meta = strict_load(_regular(Path(desc['planning_review']['path'])))
    raw = reopen(meta['reference']); receipt = strict_load(raw)
    passes = receipt['passes']
    need(passes and all(p.get('mode') == 'cross-lineage' and p.get('outcome') == 'approved' and
         fg.planning_module().equal_target(p.get('requested_target', {}), grant_row['review']) and
         p.get('observed_identity', {}).get('status') == 'verified' and p.get('options_status') == 'matched'
         for p in passes), 'actual independent owner-selected review identity/options required')
    return {'descriptor_sha256':fg.sha(desc), 'receipt':descriptor(meta['reference']['path'])}


def approve_delegated(study, data, now=None):
    with study.locked():
        revision = study.require()['revision']
        need(data['revision'] == revision, 'stale delegated approval revision')
        plan = study.plan(revision)['plan']; row = find_grant(study, data['grant_id'])
        need(data['delegate'] == row['delegate'], 'delegate/caller differs')
        review = reviewed(study, revision, row)
        bounds(study, row, plan, study.ledger(), None, fg.utc_now(now))
        records = study.approvals(revision)
        limit = fg.ceiling(plan, study.ledger())
        need(not records or records[-1].get('kind') != 'delegated-approval' or
             fg.approval_state(records, revision, limit)['state'] != 'approved', 'delegated revision already approved')
        body = {'schema_version':1, 'revision':revision,'sequence':len(records),'kind':'delegated-approval',
            'previous_record_sha256':records[-1]['record_sha256'] if records else None,
            'message_ref':row['owner']['message_ref'], 'statement':fg.instruction(revision, limit),
            'source':row['owner']['source']['path'], 'source_sha256':row['owner']['source']['sha256'],
            'derived':True, 'owner':row['owner'], 'grant_id':row['id'], 'grant_sha256':row['record_sha256'],
            'delegate':row['delegate'], 'review':review,
            'scope':{'actions':['run','resume'],'max_tasks':limit['max_tasks'],'sharing':plan['sharing'],
                     'charged_at_approval':sum(study.ledger()['charged'].values())}}
        body['record_sha256'] = fg.sha(body)
        study.retain(f'approvals/{revision}/{len(records):04d}.json', body, 'approval history changed')
        return body


def check_live(study, job=None, caller=None, now=None):
    revision = study.require()['revision']; plan = study.plan(revision)['plan']
    records = study.approvals(revision)
    need(records, 'current revision approval required')
    approval = records[-1]
    if approval.get('kind') != 'delegated-approval':
        if job is not None and job.get('authorization', {}).get('delegated_authority', {}).get('mode') == 'delegated':
            need(False, 'delegated job marker no longer matches owner approval')
        # Direct semantics are unchanged, including the literal affirmative grammar.
        if job is not None:
            raw = _regular(Path(approval['source']))
            need(digest(raw) == approval['source_sha256'], 'direct owner source changed')
            fg.affirmative(approval['statement'], raw, fg.instruction(revision, fg.ceiling(plan, study.ledger())))
        return approval
    row = find_grant(study, approval['grant_id'])
    need(fg.approval_state(records, revision, fg.ceiling(plan, study.ledger()))['state'] == 'approved',
         'delegated exact approval ceiling is insufficient')
    need(row['record_sha256'] == approval['grant_sha256'] and row['delegate'] == approval['delegate'], 'grant/approval binding changed')
    if caller is not None:
        need(caller == row['delegate']['caller'], 'actual generic caller differs from owner-bound delegate')
    if job is not None:
        marker = job.get('authorization', {}).get('delegated_authority')
        need(marker == marker_for(study, approval), 'delegated marker missing, stripped or changed')
        need(set(job['policy'].get('transaction_guard_required', [])) == set(OPERATIONS), 'required guard operations stripped')
        need(job['authorization'].get('study_revision') == revision, 'generic/study revision differs')
        need(set(job['authorization'].get('actions', [])) <= {'dispatch approved study tasks'} and
             job['authorization'].get('sharing') == plan['sharing'], 'generic authority exceeds granted study-only actions/sharing')
        identity = row['package']
        pin = job['pins'].get(identity['dependency_key'], {})
        need(job['installation_id'] == identity['installation_id'] and pin.get('package_digest') == identity['package_digest'] and
             pin.get('bundle_digest') == identity['bundle_digest'] and pin.get('installation_id') == identity['installation_id'], 'package/adoption identity differs')
    need(reviewed(study, revision, row) == approval['review'], 'accepted independent review changed')
    bounds(study, row, plan, study.ledger(), job, fg.utc_now(now))
    return approval


def marker_for(study, approval):
    return {'mode':'delegated','study_root':str(study.root),'study_id':study.id,
            'grant_id':approval['grant_id'],'approval_sha256':approval['record_sha256']}


def candidate_scope(job):
    """Authored fields after core runtime normalization, not mutable execution history."""
    task_fields = ('task_id','stage_id','logical_slot_id','worker_id','dependency_key','target','write_scope',
                   'requirements','context_policy','document','context_files','max_followups','review_required',
                   'role','review_task_ids','reviewed_task_ids','reviewed_documents','independent_of_author',
                   'document_authors','selection_binding')
    stage_fields = ('id','depends_on','requirements','criteria','resources','validator_dependency','validator_contract',
                    'revision','outputs','stop_conditions','execution_mode','validator_limits','independent_of_author',
                    'lineage_waiver','document_authors','selection_binding')
    out = {k:copy.deepcopy(job.get(k)) for k in ('requirements','dependencies','constraints','authorization','policy',
           'model_selection','model_selection_sha256','model_selection_history','invocation_id','scope_id')}
    out['tasks'] = [{k:t[k] for k in task_fields if k in t} for t in job['tasks']]
    out['stages'] = [{k:s[k] for k in stage_fields if k in s} for s in job['stages']]
    return out


def revision_inputs(study, job, revision, kind, new_plan):
    """Freeze a derived generic decision and exact canonical candidate, never apply."""
    with study.locked():
        approval = check_live(study)
        need(approval.get('kind') == 'delegated-approval' and revision == approval['revision'], 'delegated exact revision required')
        row = find_grant(study, approval['grant_id'])
        caller = row['delegate']['caller']
        new_plan.setdefault('authorization', copy.deepcopy(job['authorization'])).update(
            study_revision=revision, delegated_authority=marker_for(study, approval))
        new_plan.setdefault('policy', copy.deepcopy(job['policy']))['transaction_guard_required'] = OPERATIONS[:]
        candidate_sha = fg.sha(new_plan)
        tag = fg.sha({'revision':revision,'kind':kind,'candidate':candidate_sha,'generation':fg.sha(job)})[:24]
        revision_id = 'fg-delegated-' + tag
        # Separate from all owner-native files and worker scopes. Its label and
        # full provenance explicitly identify a derived delegate decision.
        body = {'kind':'derived-delegated-decision','instruction':approval['statement'],
                'owner':row['owner'],'grant_sha256':row['record_sha256'],'revision_id':revision_id,
                'candidate_sha256':candidate_sha}
        path = study.root / 'delegated-decisions' / study.id / (tag + '.json')
        from core.jobs.store import _retain
        _retain(path, canonical(body), 'derived decision changed')
        decision = {'id':revision_id,'scope':'plan:'+revision_id,'quote':approval['statement'],
                    'source':str(path),'source_sha256':digest(canonical(body)), 'derived_delegation':True,
                    'owner_source':row['owner']['source']}
        expected = copy.deepcopy(job)
        expected['decisions'].append(decision); expected['history'].append({'kind':'owner-decision','decision_id':revision_id})
        proof = {'kind':'delegated-application-proof','revision':revision,'revision_id':revision_id,
                 'candidate_sha256':candidate_sha,'generation':fg.sha(expected),'grant_sha256':row['record_sha256'],
                 'approval_sha256':approval['record_sha256'],'caller':caller,'derived_source':descriptor(path),
                 'candidate':copy.deepcopy(new_plan),'normalized_scope_sha256':fg.sha(candidate_scope({**job,**new_plan}))}
        proof_path = study.dir / 'authority/proofs' / (tag + '.json')
        study.retain(f'authority/proofs/{tag}.json', proof, 'exact revision proof changed')
        return {'decision_input':{'caller':caller,'decision':decision},
                'plan_revision_input':{'caller':caller,'revision':{'id':revision_id,'owner_decision_id':revision_id,
                    'authority_proof':descriptor(proof_path)},'new_plan':new_plan}}


def commit_guard(study, *, caller=None):
    @contextlib.contextmanager
    def guard(before, operation, context):
        with study.locked():  # Generic Store already holds job.lock. Never invert.
            if caller is not None:
                need(context.get('caller') == caller, 'actual transaction caller differs from bound delegate')
            check_live(study, caller=caller)
            def final(old, proposed, frozen):
                approval = check_live(study, proposed, caller)
                fg.planning_module().validate_job(proposed, previous=old, creating=operation == 'create')
                if operation == 'plan-revision' and approval.get('kind') == 'delegated-approval':
                    proof = strict_load(reopen(frozen.get('revision', {}).get('authority_proof')))
                    need(proof['revision_id'] == frozen['revision']['id'] and proof['revision'] == approval['revision'] and
                         proof['candidate_sha256'] == frozen['requested_plan_sha256'] and proof['generation'] == fg.sha(old) and
                         proof['caller'] == caller and proof['grant_sha256'] == approval['grant_sha256'] and
                         proof['approval_sha256'] == approval['record_sha256'] and
                         fg.sha(proof['candidate']) == proof['candidate_sha256'] and
                         fg.sha(candidate_scope(proposed)) == proof['normalized_scope_sha256'],
                         'stale generation, candidate or delegated application proof')
                    reopen(proof['derived_source'])
                # Check expiry last, after reopening proof and all dynamic input.
                if approval.get('kind') == 'delegated-approval':
                    grant_row = find_grant(study, approval['grant_id'])
                    deadline = study.plan(approval['revision'])['plan']['limits']['deadline']
                    end = min(fg.parse_time(grant_row['expires_at'], 'expiry'), fg.parse_time(deadline, 'deadline'))
                    need(fg.utc_now() < end, 'grant or deadline expired before persistence')
            yield final
    return guard


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('grant','status','revoke','approve-delegated','revision-inputs'))
    parser.add_argument('--state-root', required=True); parser.add_argument('--study', required=True)
    parser.add_argument('--input'); parser.add_argument('--now')
    args = parser.parse_args(argv)
    study = fg.Study(args.state_root, args.study)
    try:
        data = fg.load_json(args.input, 'authority request') if args.input else None
        if args.command == 'status':
            out = {'grants':chain(study,'authority/grants'),'revocations':chain(study,'authority/revocations'),
                   'trust_boundary':'coordinator-retained native owner provenance; not cryptographic authentication'}
        elif args.command == 'revision-inputs':
            # Atomic read only; this operation never takes job.lock under study.lock.
            job = fg.lifecycle_module().load_job(study)
            need(job is not None, 'generic job required')
            out = revision_inputs(study, job, data['revision'], data['kind'], data['new_plan'])
        else:
            out = {'grant':grant,'revoke':revoke,'approve-delegated':approve_delegated}[args.command](study,data,args.now)
        print(json.dumps({'ok':True,'data':out},sort_keys=True)); return 0
    except (fg.StudyError, JobError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'ok':False,'error':{'code':getattr(exc,'code','invalid_authority'),'message':str(exc)}})); return getattr(exc,'exit_code',2)


if __name__ == '__main__':
    raise SystemExit(main())
