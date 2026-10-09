"""Every blocked outcome names its reason, the task IDs involved and one complete
resume command. CODES is the full registry; tests drive each one."""
from __future__ import annotations

from .fsutil import hash_value

# code -> (decision the resume command applies, what the operator is deciding)
CODES = {
    'capability_unavailable': ('retry', 'T3 orchestration capability missing; re-run discovery once it is available'),
    'provider_unavailable': ('retry', 'every configured target for this work is unavailable; retry after enabling one'),
    'malformed_result': ('retry-task', 'child result stayed malformed after one correction; dispatch a fresh round'),
    'result_rejected': ('retry-task', 'child result claimed files, commits or authority it does not have'),
    'task_failed': ('retry-task', 'delegated task ended in failure'),
    'cross_parent_resume': ('adopt-parent', 'run belongs to another T3 parent thread; adopt only after its tasks are stopped'),
    'cancel_unconfirmed': ('retry-cancel', 'cancellation was requested but not confirmed for these tasks'),
    'repair_limit': ('raise-repair-limit', 'repair limit reached; allow one more repair round'),
    'budget_exhausted': ('raise-budget', 'active-time budget exhausted; allow one more hour'),
    'integration_failed': ('retry-integration', 'integrating a task branch failed; resolve and retry'),
    'endstate_unsupported': ('set-endstate', 'requested endstate is not supported in v1; finish locally'),
    'remote_unconfirmed': ('retry', 'remote outcome could not be confirmed by observation'),
    'evidence_unavailable': ('retry', 'required evidence is unverified or tooling is unavailable'),
    'operator': ('retry', 'blocked by the workflow; resolve the stated reason and retry'),
}


def resume_argv(ctx, state: dict, blocker_id: str, decision: str, task_ids) -> list:
    argv = ['python3', str(ctx.cli_path), 'unblock', '--state-root', str(ctx.state_root),
            '--run-id', state['run_id'], '--blocker-id', blocker_id, '--decision', decision]
    if decision == 'raise-repair-limit':
        argv += ['--value', str(int(state['policy']['repair_limit']) + 1)]
    elif decision == 'raise-budget':
        argv += ['--value', str(int(state['budget']['seconds']) + 3600)]
    elif decision == 'set-endstate':
        argv += ['--value', 'local']
    elif decision == 'adopt-parent':
        argv += ['--value', str(ctx.parent_thread_id or state['host'].get('parent_thread_id'))]
    elif decision in ('retry-task', 'retry-integration') and task_ids:
        argv += ['--task-id', task_ids[0]]
    return argv


def make(ctx, state: dict, code: str, reason: str, task_ids=(), at: str = '') -> dict:
    if code not in CODES:
        code = 'operator'
    task_ids = sorted({str(item) for item in task_ids if item})
    decision, meaning = CODES[code]
    # Stable across claim/release (which bump the generation) so a printed resume
    # command stays valid; distinct from any earlier, already resolved occurrence.
    resolved = sum(1 for item in state.get('blockers', []) if item.get('status') == 'resolved')
    blocker_id = 'B-' + hash_value([code, task_ids, reason, resolved])[:10]
    prompt = None
    entry = (state.get('plugin') or {}).get('entry')
    if entry:
        prompt = f'Read {entry} and run: resume {state["run_id"]}'
    return {
        'id': blocker_id,
        'code': code,
        'reason': reason or meaning,
        'meaning': meaning,
        'task_ids': task_ids,
        'resume': {'argv': resume_argv(ctx, state, blocker_id, decision, task_ids), 'decision': decision,
                   'then': prompt},
        'status': 'active',
        'at': at,
    }


def active(state: dict) -> list:
    return [item for item in state.get('blockers', []) if item.get('status') == 'active']
