"""Structured child results: one fenced JSON block at the end of the child's final
message. The parent extracts it, stores it as an artifact and validates it here.
A prose summary or a `completed` status is never acceptance evidence."""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

from . import schema, snapshot
from .errors import InvalidInput

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


def _owned(path: str, patterns) -> bool:
    return not patterns or any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def validate(state: dict, task: dict, result: dict, worktree: str | None) -> dict:
    """Schema first (Malformed), then claims against reality (Rejected)."""
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
    allowed_ids = set(task.get('requirement_ids') or []) or {item['id'] for item in state['brief']['requirements']}
    unknown = sorted({item['id'] for item in result['requirements']} - allowed_ids)
    if unknown:
        raise Rejected('result_requirement_unknown', 'result reports requirements outside this task',
                       {'ids': unknown})
    for item in result['requirements']:
        if item.get('text') is not None:
            original = {req['id']: req['text'] for req in state['brief']['requirements']}
            if item['text'] != original.get(item['id']):
                raise Rejected('result_contract_rewrite', 'result rewrites a requirement', {'id': item['id']})
    if task.get('kind') == 'review' and result.get('verdict') not in ('approve', 'adverse'):
        raise Malformed('review results need verdict approve or adverse')
    if worktree and task.get('writes'):
        base = task.get('base_sha') or state['repo'].get('base_sha')
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
    elif not task.get('writes') and result['changed_files']:
        raise Rejected('result_unexpected_writes', 'a read-only task reported changed files',
                       {'files': result['changed_files']})
    roots = [root for root in (worktree, state['repo'].get('worktree')) if root]
    for item in result['requirements']:
        for evidence in item.get('evidence', []):
            path = Path(evidence['path'])
            if not path.is_absolute():
                path = Path(roots[0]) / path if roots else path
            if item['status'] == 'passed' and not path.is_file():
                raise Rejected('result_evidence_absent', 'result claims evidence that does not exist',
                               {'id': item['id'], 'path': evidence['path']})
    return result
