"""Run phases.

planned -> executing -> verifying -> ready -> publishing -> completed
verifying -> executing   (bounded repair)
ready -> completed       (local endstate only)
ready|publishing -> verifying   (evidence went stale)
blocked and cancelling interrupt any nonterminal phase; blocked keeps resume_phase.
cancelling -> cancelled only after every owned task is confirmed stopped.
failed is terminal and keeps its evidence."""
from __future__ import annotations

from .errors import Prohibited

PHASES = ('planned', 'executing', 'verifying', 'ready', 'publishing', 'completed',
          'blocked', 'cancelling', 'cancelled', 'failed')
TERMINAL = frozenset({'completed', 'cancelled', 'failed'})
FORWARD = {
    'planned': {'executing'},
    'executing': {'verifying'},
    'verifying': {'ready', 'executing'},
    'ready': {'publishing', 'completed', 'verifying'},
    'publishing': {'completed', 'verifying'},
    'cancelling': {'cancelled'},
}


def allowed(current: str, target: str) -> bool:
    if current in TERMINAL:
        return False
    if target in ('blocked', 'cancelling', 'failed'):
        return current != target and not (current == 'cancelling' and target == 'cancelling')
    return target in FORWARD.get(current, set())


def apply(state: dict, target: str, why: str, at: str) -> None:
    current = state['phase']
    if target not in PHASES:
        raise Prohibited('unknown_phase', f'unknown phase {target}')
    if not allowed(current, target):
        raise Prohibited('transition_prohibited', f'{current} -> {target} is not a permitted transition',
                         {'from': current, 'to': target})
    state['resume_phase'] = current if target == 'blocked' else None
    state['phase'] = target
    event(state, 'transition', f'{current} -> {target}: {why}', at)


def unblock(state: dict, at: str, why: str) -> None:
    if state['phase'] != 'blocked':
        raise Prohibited('not_blocked', 'run is not blocked')
    target = state.get('resume_phase') or 'planned'
    state['phase'] = target
    state['resume_phase'] = None
    event(state, 'transition', f'blocked -> {target}: {why}', at)


def event(state: dict, kind: str, summary: str, at: str) -> None:
    state.setdefault('events', []).append({'at': at, 'kind': kind, 'summary': summary[:500]})
