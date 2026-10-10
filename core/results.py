"""Structured child results: one fenced JSON block at the end of the child's final
message. The parent extracts it, stores it as an artifact and validates it here.
A prose summary or a `completed` status is never acceptance evidence."""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

from . import contract, schema, snapshot
from .errors import InvalidInput
from .fsutil import contained

FENCE = re.compile(r'```([^\n`]*)\n(.*?)\n?```', re.S)
TAG = 't3-result'
# Fields a child may never set: they belong to the operator and the run record.
OVERREACH = ('constraints', 'authorization', 'authorized_actions', 'endstate', 'phase', 'run_status',
             'completion', 'completed', 'requirements_contract', 'policy', 'acceptance_override')


class Malformed(Exception):
    pass


class Rejected(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def extract(text: str) -> dict:
    """Return the result object or raise Malformed."""
    if not isinstance(text, str) or not text.strip():
        raise Malformed('final message is empty')
    blocks = [(info.strip().split(), body) for info, body in FENCE.findall(text)]
    tagged = [body for info, body in blocks if TAG in info]
    if len(tagged) > 1:
        raise Malformed(f'{len(tagged)} blocks tagged {TAG}; expected exactly one')
    if tagged:
        body = tagged[0]
    else:
        plain = [body for info, body in blocks if info[:1] == ['json']]
        if len(plain) != 1:
            raise Malformed(f'expected one fenced JSON result block, found {len(plain)}')
        body = plain[0]
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise Malformed(f'result block is not valid JSON: {exc.msg} at line {exc.lineno}') from exc
    if not isinstance(value, dict):
        raise Malformed('result block must be a JSON object')
    return value


def glob_match(path: str, pattern: str) -> bool:
    """Per-segment glob: `*`, `?` and `[...]` stay inside one path segment and
    `**` spans any number of segments, so `src/*.py` does not own `src/util/x.py`."""
    parts, pats = path.split('/'), pattern.strip('/').split('/')

    def walk(i, j):
        if j == len(pats):
            return i == len(parts)
        if pats[j] == '**':
            return any(walk(k, j + 1) for k in range(i, len(parts) + 1))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], pats[j]) and walk(i + 1, j + 1)
    return walk(0, 0)


def owns(patterns, path: str) -> bool:
    """Whether ownership `patterns` cover `path`; empty ownership covers every path."""
    return not patterns or any(glob_match(path, pattern) for pattern in patterns)


def _owned(path: str, patterns) -> bool:
    return owns(patterns, path)


def requirement_ids(task: dict, current: dict) -> tuple[set, list]:
    """(IDs this task answers for in the current contract, task IDs the contract no longer has)."""
    known = {item['id'] for item in current['requirements']}
    if not task.get('requirement_ids'):
        return known, []
    return set(task['requirement_ids']) & known, sorted(set(task['requirement_ids']) - known)


def validate(state: dict, task: dict, result: dict, worktree: str | None, roots=()) -> dict:
    """Schema first (Malformed), then claims against reality (Rejected). Absolute
    evidence must sit under the task worktree, the run's checkout or `roots`."""
    overreach = sorted(key for key in result if key in OVERREACH)
    if overreach:
        raise Rejected('result_overreach', 'child result tries to set operator-owned fields',
                       {'fields': overreach})
    try:
        schema.validate(result, 'result')
    except InvalidInput as exc:
        raise Malformed('; '.join(exc.details.get('errors', [exc.message]))) from exc
    if result['task_id'] != task['id']:
        raise Rejected('result_task_mismatch', 'result names a different task',
                       {'expected': task['id'], 'got': result['task_id']})
    current = contract.current_contract(state)
    allowed_ids, _dropped = requirement_ids(task, current)
    unknown = sorted({item['id'] for item in result['requirements']} - allowed_ids)
    if unknown:
        raise Rejected('result_requirement_unknown', 'result reports requirements outside this task '
                                                     'or no longer in the contract', {'ids': unknown})
    original = {req['id']: req['text'] for req in current['requirements']}
    for item in result['requirements']:
        if item.get('text') is not None:
            if item['text'] != original.get(item['id']):
                raise Rejected('result_contract_rewrite', 'result rewrites a requirement', {'id': item['id']})
    if task.get('kind') == 'review' and result.get('verdict') not in ('approve', 'adverse'):
        raise Malformed('review results need verdict approve or adverse')
    if worktree and task.get('writes'):
        base = task.get('base_sha') or state['repo'].get('base_sha')
        if task.get('self_base'):
            # Work done in the parent's checkout is judged against the tree as it stood when the task started.
            actual = snapshot.changed_since(worktree, task['self_base'])
        else:
            actual = snapshot.changed_files(worktree, base) if base else set()
        claimed = set(result['changed_files'])
        missing = sorted(claimed - actual)
        if missing:
            raise Rejected('result_files_absent', 'result claims changes that do not exist in the worktree',
                           {'files': missing})
        outside = sorted(path for path in actual if not _owned(path, task.get('files')))
        if outside:
            raise Rejected('result_files_unowned', 'worktree changes fall outside the task file ownership',
                           {'files': outside})
        if result.get('commit') and not snapshot.commit_reachable(worktree, result['commit']):
            raise Rejected('result_commit_absent', 'claimed commit is not in the task worktree',
                           {'commit': result['commit']})
        if result['status'] == 'done' and not actual:
            raise Rejected('result_no_changes', 'a writing task reported done with no changes in its worktree')
        if result['status'] == 'done' and Path(worktree).resolve() != Path(state['repo']['worktree']).resolve():
            dirty = snapshot.git(worktree, 'status', '--porcelain', '--untracked-files=normal').strip()
            head = snapshot.git(worktree, 'rev-parse', 'HEAD').strip()
            if dirty or head == base:
                raise Rejected('result_uncommitted', 'a task worktree must hold its work as commits; integration merges '
                                                     'commits only', {'uncommitted': dirty.splitlines()[:20]})
    elif not task.get('writes') and result['changed_files']:
        # Usually the files it read (a review listing what it reviewed). One correction round fixes the report.
        raise Malformed('a read-only task must report "changed_files": [] (list files you read in findings or notes, '
                        f'not here); got {result["changed_files"][:10]}')
    bases = [root for root in (worktree, state['repo'].get('worktree')) if root]
    permitted = bases + [root for root in roots if root]
    for item in result['requirements']:
        for evidence in item.get('evidence', []):
            path = Path(evidence['path'])
            if item['status'] != 'passed':
                continue
            if not path.is_absolute():
                if not any((Path(root) / path).is_file() for root in bases):
                    # Probably relative to the child's own working directory; ask once for absolute paths.
                    raise Malformed(f'evidence path {evidence["path"]!r} for {item["id"]} is relative and does not '
                                    'exist under the task directory; report absolute paths')
                path = next(Path(root) / path for root in bases if (Path(root) / path).is_file())
            elif not path.is_file():
                raise Rejected('result_evidence_absent', 'result claims evidence that does not exist',
                               {'id': item['id'], 'path': evidence['path']})
            try:
                contained(path, permitted)
            except InvalidInput as exc:
                raise Rejected('result_evidence_outside', 'result claims evidence outside the task worktree, '
                                                          'the run directory and the policy evidence roots',
                               {'id': item['id'], 'path': evidence['path'], 'problem': exc.code}) from exc
    return result
