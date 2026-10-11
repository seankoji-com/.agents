#!/usr/bin/env python3
"""Frozen token parser for Claude Code session transcripts (JSONL).

A Claude Code transcript writes one line per content block, so a single API response
appears on several lines that repeat the same `message.id` and usage. The parser
counts each message ID once, taking the largest value seen for each usage field.
Synthetic messages (model `<synthetic>`, no API call) are skipped.

Reported per model:
  counted     = input_tokens + output_tokens + cache_creation_input_tokens
  cache_read  = cache_read_input_tokens, reported separately and never counted
A usage field that is missing or not an integer makes that total `null` ("unknown");
it is never treated as 0. Codex rollout files are read the same way where they report
`token_count` events; any other provider is unknown.

Usage:
  python3 bench/tools/tokens.py session FILE.jsonl
  python3 bench/tools/tokens.py run WORKSPACE --projects-dir DIR [--codex-dir DIR]
`run` finds the workspace's Claude Code project directory (`DIR/<encoded path>`),
treats the session whose first prompt starts with the frozen worker prompt as the
parent, and every other session or subagent file there as a descendant.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

FIELDS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
COUNTED = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens')
PARENT_PROMPT_PREFIX = 'Follow the installed imps entry at '


def _lines(path: Path):
    with open(path, encoding='utf-8', errors='replace') as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict):
                yield item


def _known(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(part.get('text', '') for part in content if isinstance(part, dict) and part.get('type') == 'text')
    return ''


def parse_session(path: Path) -> dict:
    """Usage totals for one Claude Code session file, by model."""
    messages, stamps = {}, []
    first_prompt = None
    for item in _lines(path):
        stamp = item.get('timestamp')
        if isinstance(stamp, str):
            stamps.append(stamp)
        message = item.get('message') if isinstance(item.get('message'), dict) else {}
        if item.get('type') == 'user' and first_prompt is None and not item.get('isMeta'):
            text = _text(message.get('content'))
            if text.strip():
                first_prompt = text
        if item.get('type') != 'assistant' or message.get('model') == '<synthetic>':
            continue
        key = message.get('id') or item.get('requestId') or item.get('uuid')
        usage = message.get('usage') if isinstance(message.get('usage'), dict) else {}
        entry = messages.setdefault(key, {'model': message.get('model') or 'unknown', 'usage': {}})
        for field in FIELDS:
            value = usage.get(field)
            previous = entry['usage'].get(field, 'absent')
            if not _known(value):
                entry['usage'].setdefault(field, None)
            elif previous in ('absent', None) or value > previous:
                entry['usage'][field] = value
    by_model = {}
    for entry in messages.values():
        totals = by_model.setdefault(entry['model'], {'messages': 0, **{f: 0 for f in FIELDS}})
        totals['messages'] += 1
        for field in FIELDS:
            value = entry['usage'].get(field)
            totals[field] = None if totals[field] is None or value is None else totals[field] + value
    for totals in by_model.values():
        totals['counted'] = None if any(totals[f] is None for f in COUNTED) else sum(totals[f] for f in COUNTED)
        totals['cache_read'] = totals['cache_read_input_tokens']
    stamps.sort()
    return {'file': path.name, 'first_prompt_prefix': (first_prompt or '')[:80], 'by_model': by_model,
            'started_at': stamps[0] if stamps else None, 'ended_at': stamps[-1] if stamps else None}


def parse_codex(path: Path) -> dict:
    """The last cumulative token_count in a Codex rollout file, or unknown."""
    meta, last = {}, None
    for item in _lines(path):
        payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
        if item.get('type') == 'session_meta':
            meta = payload
        info = payload.get('info') if payload.get('type') == 'token_count' else None
        if isinstance(info, dict) and isinstance(info.get('total_token_usage'), dict):
            last = info['total_token_usage']
    usage = {k: (v if _known(v) else None) for k, v in (last or {}).items()}
    return {'file': path.name, 'cwd': meta.get('cwd'), 'model': meta.get('model'), 'usage': usage or None}


def encode_project(workspace: Path) -> str:
    return re.sub(r'[^A-Za-z0-9-]', '-', str(workspace))


def _sum(values):
    values = list(values)
    return None if not values or any(v is None for v in values) else sum(values)


def parse_run(workspace: Path, projects_dir: Path, codex_dir: Path | None = None) -> dict:
    project = projects_dir / encode_project(workspace)
    if not project.is_dir():
        return {'project_dir_found': False, 'parent': None, 'descendants': []}
    sessions = sorted(project.glob('*.jsonl'))
    parsed = [parse_session(p) for p in sessions]
    parents = [s for s in parsed if s['first_prompt_prefix'].startswith(PARENT_PROMPT_PREFIX)]
    parent = min(parents, key=lambda s: s['started_at'] or '') if parents else None
    descendants = [dict(s, kind='claude-session') for s in parsed if s is not parent]
    for sub in sorted(project.glob('*/subagents/*.jsonl')):
        descendants.append(dict(parse_session(sub), kind='claude-subagent'))
    if codex_dir and codex_dir.is_dir() and parent:
        # Codex files rollouts under YYYY/MM/DD in local time; scan the run's days and a day either side.
        first = datetime.fromisoformat((parent['started_at'] or '').replace('Z', '+00:00')).date()
        last = datetime.fromisoformat((parent['ended_at'] or '').replace('Z', '+00:00')).date()
        days = [first + timedelta(days=n) for n in range(-1, (last - first).days + 2)]
        rollouts = [r for d in days for r in sorted((codex_dir / f'{d:%Y/%m/%d}').glob('rollout-*.jsonl'))]
        for rollout in rollouts:
            item = parse_codex(rollout)
            cwd = item.get('cwd') or ''
            if cwd == str(workspace) or cwd.startswith(str(workspace) + '/'):
                descendants.append(dict(item, kind='codex-rollout'))
    opus = {}
    if parent:
        opus = {m: t for m, t in parent['by_model'].items() if 'opus' in m}
    summary = {
        'counted': _sum(t['counted'] for t in opus.values()),
        'cache_read': _sum(t['cache_read'] for t in opus.values()),
        'other_models_in_parent': sorted(m for m in (parent or {}).get('by_model', {}) if 'opus' not in m),
    }
    return {'project_dir_found': True, 'parent': parent, 'parent_opus': summary, 'descendants': descendants}


def wallclock_seconds(started: str | None, ended: str | None):
    if not started or not ended:
        return None
    parse = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00'))
    return round((parse(ended) - parse(started)).total_seconds(), 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='cmd', required=True)
    one = sub.add_parser('session')
    one.add_argument('file', type=Path)
    run = sub.add_parser('run')
    run.add_argument('workspace', type=Path)
    run.add_argument('--projects-dir', type=Path, required=True)
    run.add_argument('--codex-dir', type=Path)
    args = parser.parse_args(argv)
    if args.cmd == 'session':
        result = parse_session(args.file)
    else:
        result = parse_run(args.workspace, args.projects_dir, args.codex_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
