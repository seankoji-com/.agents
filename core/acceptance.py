"""Readiness: evidence counts only while it is bound to the current snapshot,
contract hash and policy hash and its artifacts still hash the same.

Status labels stay distinct: passed, failed, unverified, unavailable, waived.
A waiver satisfies readiness only where policy permits it and is reported as
waived, never as passed."""
from __future__ import annotations

from pathlib import Path

from . import contract, review as review_rules, snapshot
from .fsutil import hash_value, verify_artifact

LABELS = ('passed', 'failed', 'unverified', 'unavailable', 'waived')


EVIDENCE_POLICY = ('checks', 'review', 'role_overrides', 'model_preferences', 'repository_policy')


def policy_hash(state: dict) -> str:
    """Hash only the policy that decides what counts as evidence: checks, review
    and target selection. Limits, budgets and paths can change without staling it."""
    policy = state.get('policy') or {}
    return hash_value({'policy': {key: policy.get(key) for key in EVIDENCE_POLICY}, 'roles': state.get('roles') or {}})


def exclusions(state: dict, state_root) -> list:
    items = [state_root]
    source = state['brief'].get('requirements_source')
    if source:
        items.append(source)
    return items


def binding(state: dict, state_root, current: dict | None = None) -> dict:
    current = current or contract.current_contract(state)
    return {
        'snapshot': snapshot.take(state['repo']['worktree'], exclusions(state, state_root)),
        'contract_hash': contract.contract_hash(current),
        'policy_hash': policy_hash(state),
    }


def staleness(entry: dict, bind: dict, run_dir: Path) -> str | None:
    if entry.get('invalidated'):
        return f'invalidated by {entry["invalidated"]}'
    if not snapshot.same(entry.get('snapshot'), bind['snapshot']):
        before, after = entry.get('snapshot') or {}, bind['snapshot']
        if before.get('head') != after.get('head'):
            return 'HEAD changed since this evidence was recorded'
        return 'working-tree content changed since this evidence was recorded'
    if entry.get('contract_hash') != bind['contract_hash']:
        return 'requirements or constraints changed'
    if entry.get('policy_hash') != bind['policy_hash']:
        return 'check or review policy changed'
    for artifact in entry.get('artifacts') or ([entry['artifact']] if entry.get('artifact') else []):
        problem = verify_artifact(run_dir, artifact)
        if problem:
            return f'{problem}: {artifact.get("path")}'
    return None


def _latest(items, predicate):
    for item in reversed(items):
        if predicate(item):
            return item
    return None


def _waived(state, target, bind, run_dir):
    waiver = _latest(state.get('waivers', []), lambda item: item['target'] == target)
    if waiver and staleness(waiver, bind, run_dir) is None:
        return waiver
    return None


def evaluate(state: dict, state_root, run_dir: Path, bind: dict | None = None) -> dict:
    bind = bind or binding(state, state_root)
    stale, missing, failed = [], [], []
    requirements = []
    current = contract.current_contract(state)
    for req in current['requirements']:
        entry = _latest(state.get('acceptance', []), lambda item: item['requirement_id'] == req['id'] and not item.get('invalidated'))
        row = {'id': req['id'], 'text': req['text'], 'kind': req['kind'], 'required': req['required'],
               'status': 'unverified', 'explanation': None, 'evidence': []}
        if entry:
            reason = staleness(entry, bind, run_dir)
            if reason:
                row['stale_reason'] = reason
                if req['required']:
                    stale.append({'obligation': f'requirement:{req["id"]}', 'reason': reason})
            else:
                row.update(status=entry['status'], explanation=entry.get('explanation'),
                           evidence=entry.get('artifacts', []), evidence_kind=entry.get('kind'))
        if row['status'] != 'passed' and _waived(state, f'requirement:{req["id"]}', bind, run_dir):
            row['status'] = 'waived'
        if req['required'] and row['status'] not in ('passed', 'waived'):
            (failed if row['status'] == 'failed' else missing).append(
                {'obligation': f'requirement:{req["id"]}', 'status': row['status']})
        requirements.append(row)
    checks = []
    for check in state['policy'].get('checks', []):
        entry = _latest(state.get('checks', []), lambda item: item['name'] == check['name'] and not item.get('invalidated'))
        row = {'name': check['name'], 'required': check.get('required', True), 'status': 'unverified',
               'argv': check['argv']}
        if entry:
            reason = staleness(entry, bind, run_dir)
            if reason:
                row['stale_reason'] = reason
                if row['required']:
                    stale.append({'obligation': f'check:{check["name"]}', 'reason': reason})
            else:
                row.update(status=entry['status'], exit_code=entry.get('exit_code'), artifact=entry.get('artifact'))
        if (row['status'] != 'passed' and not check.get('repository_required')
                and _waived(state, f'check:{check["name"]}', bind, run_dir)):
            row['status'] = 'waived'
        if row['required'] and row['status'] not in ('passed', 'waived'):
            (failed if row['status'] == 'failed' else missing).append(
                {'obligation': f'check:{check["name"]}', 'status': row['status']})
        checks.append(row)
    review_policy = state['policy'].get('review') or {}
    review = {'required': bool(review_policy.get('required')), 'status': 'unverified'}
    rows = []
    for perspective in review_rules.perspectives(review_policy):
        row = {'id': perspective['id'], 'status': 'unverified'}
        entry = _latest(state.get('reviews', []), lambda item: not item.get('invalidated')
                        and item.get('perspective_id', 'default') == perspective['id'])
        if entry:
            row.update(round=entry['round'], selection=entry.get('selection'), why=entry.get('why'))
            reason = staleness(entry, bind, run_dir)
            if reason:
                row['stale_reason'] = reason
                if review['required']:
                    stale.append({'obligation': 'review', 'reason': reason})
            else:
                row['status'] = {'approve': 'passed', 'adverse': 'failed'}.get(entry['verdict'], 'unavailable')
                row['verdict'] = entry['verdict']
        rows.append(row)
    review.update({key: value for key, value in rows[0].items() if key != 'id'})
    if len(rows) > 1:
        review['perspectives'] = rows
        review['status'] = ('failed' if any(row['status'] == 'failed' for row in rows)
                            else 'passed' if all(row['status'] == 'passed' for row in rows)
                            else 'unavailable' if any(row['status'] == 'unavailable' for row in rows)
                            else 'unverified')
        review.pop('verdict', None)
        if review['status'] in ('passed', 'failed'):
            review['verdict'] = 'approve' if review['status'] == 'passed' else 'adverse'
    if (review['status'] != 'passed' and review_policy.get('waivable', True)
            and _waived(state, 'review', bind, run_dir)):
        review['status'] = 'waived'
    if review['required'] and review['status'] not in ('passed', 'waived'):
        (failed if review['status'] == 'failed' else missing).append({'obligation': 'review', 'status': review['status']})
    ready = not stale and not missing and not failed
    status = 'ready' if ready else 'failed' if failed else 'stale' if stale else 'incomplete'
    counts = {label: sum(1 for row in requirements if row['status'] == label) for label in LABELS}
    return {'ready': ready, 'status': status, 'binding': bind, 'requirements': requirements, 'checks': checks,
            'review': review, 'missing': missing, 'failed': failed, 'stale': stale, 'counts': counts}


def remote_confirmed(state: dict, bind: dict) -> tuple[bool, str]:
    """A local pass never satisfies a remote endstate: require an independent
    observation of that outcome at the verified head."""
    endstate = state['authorization']['endstate']
    if endstate == 'local':
        return True, 'local endstate'
    if bind['snapshot'].get('dirty_paths'):
        return False, 'verified changes are not committed, so no pull request can contain them'
    remote = state.get('remote') or {}
    receipt = (remote.get('receipts') or [None])[-1]
    if not receipt:
        return False, f'no receipt records the {endstate} outcome'
    observations = remote.get('observations', [])
    wanted = {'pr': ('open', 'merged'), 'merge': ('merged',)}.get(endstate, ())
    for item in reversed(observations):
        if item.get('kind') != 'pr':
            continue
        if not same_remote(item, receipt):
            return False, f'observed {item.get("url")!r}, not the recorded receipt {receipt.get("url")!r}'
        if item.get('state') not in wanted:
            return False, f'observed {endstate} state {item.get("state")!r}'
        if item.get('head_sha') != bind['snapshot']['head']:
            return False, 'observed PR head differs from the verified head'
        return True, f'observed {item.get("url")} {item.get("state")} at {item.get("observed_at")}'
    return False, f'no observation confirms the {endstate} outcome'


def same_remote(observation: dict, receipt: dict) -> bool:
    """An observation confirms a receipt only when it names the same PR."""
    def norm(url):
        return str(url or '').strip().rstrip('/').lower()
    if norm(observation.get('url')) != norm(receipt.get('url')):
        return False
    numbers = (observation.get('number'), receipt.get('number'))
    return None in numbers or str(numbers[0]) == str(numbers[1])
