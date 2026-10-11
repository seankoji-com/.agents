"""Admit observations and evidence, never readiness or executable actions."""
from __future__ import annotations

from pathlib import Path

from . import acceptance, contract, planning, review, schema, snapshot
from .errors import InvalidInput, Prohibited
from .fsutil import copy_artifact
from .store import now_iso

TERMINAL = ('completed', 'failed', 'cancelled', 'interrupted')


def pending(child):
    return (child['status'] not in TERMINAL or child.get('has_pending_child_runs', False)
            or child.get('work_state') == 'waiting_for_children')


def current(state, root, payload):
    supplied = payload['binding']
    bind = acceptance.binding(state, root)
    if (not snapshot.same(supplied['snapshot'], bind['snapshot'])
            or supplied['contract_hash'] != bind['contract_hash']
            or supplied['policy_hash'] != bind['policy_hash']):
        raise Prohibited('stale_evidence', 'evidence must carry the binding taken before verification; the tree or contract changed')
    return supplied


def artifacts(state, run_dir, root, paths, category):
    roots = [run_dir, state['repo']['worktree'], *state['policy'].get('evidence_roots', [])]
    return [copy_artifact(Path(path), run_dir, category, roots) for path in paths]


def supersede(state, target):
    for waiver in state['waivers']:
        if waiver['target'] == target:
            waiver['invalidated'] = 'new evidence for ' + target


def apply(state, root, run_dir, kind, payload):
    schema.validate(payload, 'submission-' + kind, 'submission_invalid')
    if state['phase'] == 'cancelled' and kind != 'note':
        raise Prohibited('cancelled', 'a cancelled run accepts notes only')
    at = now_iso()
    if kind in ('check', 'evidence', 'review'):
        bind = current(state, root, payload)
        entry = dict(bind, recorded_at=at)
        if kind == 'check':
            check = next((c for c in state['policy']['checks'] if c['name'] == payload['name']), None)
            if check is None:
                raise InvalidInput('unknown_check', 'no check named ' + payload['name'])
            if payload['argv'] != check['argv']:
                raise InvalidInput('argv_mismatch', 'argv must match the planned check exactly')
            cwd = Path(check.get('cwd') or state['repo']['worktree'])
            if not cwd.is_absolute():
                cwd = Path(state['repo']['worktree']) / cwd
            if Path(payload['cwd']).resolve() != cwd.resolve():
                raise InvalidInput('cwd_mismatch', 'cwd must match the planned check')
            code = payload['exit_code']
            reason = payload.get('unavailable_reason')
            if (code is None and not reason) or (code == 0 and reason):
                raise InvalidInput('check_contradiction', 'null exit needs an unavailable reason; zero exit cannot be unavailable')
            artifact = artifacts(state, run_dir, root, [payload['log']], 'checks')[0]
            status = 'passed' if code == 0 else 'unavailable' if reason or code in (124, 126, 127) else 'failed'
            entry.update(name=check['name'], argv=check['argv'], cwd=str(cwd.resolve()), exit_code=code,
                         status=status, artifact=artifact, unavailable_reason=reason)
            state['checks'].append(entry)
            supersede(state, 'check:' + check['name'])
        elif kind == 'evidence':
            req = next((r for r in contract.current_contract(state)['requirements']
                        if r['id'] == payload['requirement_id']), None)
            if req is None:
                raise InvalidInput('unknown_requirement', 'no requirement ' + payload['requirement_id'])
            if req['kind'] != payload['kind']:
                raise Prohibited('evidence_kind', f'{req["id"]} needs {req["kind"]} evidence')
            paths = payload.get('artifacts', [])
            if payload['status'] == 'passed' and not paths:
                raise Prohibited('evidence_missing', 'a passed requirement needs artifact files')
            if payload['kind'] == 'manual' and payload['status'] == 'passed' and not payload.get('verifier'):
                raise InvalidInput('manual_verifier', 'manual evidence names its verifier')
            entry.update({k: v for k, v in payload.items() if k != 'binding'})
            entry['artifacts'] = artifacts(state, run_dir, root, paths, 'evidence')
            state['acceptance'].append(entry)
            supersede(state, 'requirement:' + req['id'])
        else:
            known = {r['id'] for r in review.perspectives(state['policy']['review'])}
            if payload['perspective_id'] not in known:
                raise InvalidInput('review_perspective', 'unknown review perspective')
            child = next((c for c in state['children'] if c['task_id'] == payload['task_id']), None)
            if child is None or pending(child):
                raise Prohibited('review_pending', 'review needs its recorded terminal child task')
            verdict = payload['verdict']
            if verdict == 'approve' and child['status'] != 'completed':
                raise Prohibited('review_unavailable', 'an unsuccessful child cannot approve a review')
            if any(f['severity'] in ('blocker', 'major') for f in payload['findings']):
                verdict = 'adverse'
            previous = [r for r in state['reviews'] if r['perspective_id'] == payload['perspective_id']]
            if any(r['verdict'] == 'adverse' and r['snapshot'] == bind['snapshot'] for r in previous):
                raise Prohibited('adverse_revision', 'an adverse review is final for that revision; repair before reviewing again')
            entry.update({k: v for k, v in payload.items() if k not in ('binding', 'artifacts')})
            entry.update(verdict=verdict, round=len(previous) + 1,
                         artifacts=artifacts(state, run_dir, root, payload['artifacts'], 'reviews'))
            state['reviews'].append(entry)
            supersede(state, 'review')
        # Artifact collection must not certify a tree edited while copying.
        current(state, root, payload)
        return entry
    if kind == 'child':
        parent = state['host'].get('parent_thread_id')
        if not parent or payload['parent_thread_id'] != parent:
            raise Prohibited('parent_mismatch', 'only this run parent can observe its child tasks')
        child = next((c for c in state['children'] if c['task_id'] == payload['task_id']), None)
        if child:
            if child['client_request_id'] != payload['client_request_id']:
                raise Prohibited('child_identity', 'a task ID cannot change its request identity')
            child.update(payload)
        else:
            if any(c['client_request_id'] == payload['client_request_id'] for c in state['children']):
                raise Prohibited('child_identity', 'a request identity cannot change its task ID')
            state['children'].append(dict(payload))
        return payload
    if kind == 'waive':
        target = payload['target']
        if target.startswith('check:'):
            check = next((c for c in state['policy']['checks'] if 'check:' + c['name'] == target), None)
            if check is None:
                raise InvalidInput('unknown_check', target)
            if check.get('repository_required'):
                raise Prohibited('waiver_forbidden', 'repository checks cannot be waived')
        elif target.startswith('requirement:'):
            if not any('requirement:' + r['id'] == target for r in contract.current_contract(state)['requirements']):
                raise InvalidInput('unknown_requirement', target)
        elif target != 'review':
            raise InvalidInput('waiver_target', 'unknown waiver target')
        elif not state['policy']['review'].get('waivable', True):
            raise Prohibited('waiver_forbidden', 'review cannot be waived')
        entry = dict(payload, **acceptance.binding(state, root), recorded_at=at)
        state['waivers'].append(entry)
        return entry
    if kind == 'policy':
        changes = payload['policy']
        # Add obligations, never rewrite or drop existing ones or retarget a role.
        for key in changes:
            if key not in ('checks', 'review', 'brief_notes'):
                raise Prohibited('policy_change', 'policy updates cannot retarget or remove obligations')
        proposed = planning.deep_merge(state['policy'], changes)
        if any(c not in proposed.get('checks', []) for c in state['policy']['checks']):
            raise Prohibited('policy_change', 'existing checks must survive unchanged')
        old = state['policy']['review']
        new = proposed['review']
        if ((old.get('required') and not new.get('required')) or (not old.get('waivable', True) and new.get('waivable', True))
                or any(new.get(k) != v for k, v in old.items() if k not in ('required', 'waivable'))):
            raise Prohibited('policy_change', 'existing review obligations must survive unchanged')
        if len({c['name'] for c in proposed['checks']}) != len(proposed['checks']):
            raise InvalidInput('duplicate_check', 'check names must be unique')
        review.perspectives(new)
        state['policy'] = proposed
        return proposed
    if kind == 'remote':
        if state['authorization']['endstate'] == 'local':
            raise Prohibited('remote_unauthorized', 'the run authorizes local work only')
        group = 'receipts' if payload['type'] == 'receipt' else 'observations'
        entry = dict(payload, observed_at=at)
        state['remote'][group].append(entry)
        return entry
    if kind == 'cancel':
        live = [c['task_id'] for c in state['children'] if pending(c)]
        if live:
            raise Prohibited('children_pending', 'confirm task-owned children stopped before cancelling', {'task_ids': live})
        state['phase'] = 'cancelled'
        return {'cancelled': True}
    entry = dict(payload, recorded_at=at)
    state['notes'].append(entry)
    return entry
