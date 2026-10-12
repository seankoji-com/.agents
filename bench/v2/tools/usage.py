#!/usr/bin/env python3
"""bench-v2 usage parser: per-inference context, deduplicated usage, cache and attribution.

Input is a run manifest (JSON); file paths in it are relative to the manifest:

  {"schema_version": 1,
   "sources": [{"file": "parent.jsonl", "format": "claude-jsonl" | "codex-rollout",
                "role": "parent" | "worker" | "unattributed",
                "task_id": "...", "slot": "...", "stage": "...", "attempt": 0}],
   "boundaries": [{"stage": "s1", "at": "2026-10-12T00:10:00Z"}]}

Definitions, frozen with bench/v2/protocol.md:

- An inference is one model request. Claude JSONL repeats an assistant message once per
  content block: lines with the same message.id (else requestId) are one inference, each
  usage field taking the largest known value. Lines with neither ID are counted alone and
  reported as a gap. An identity already counted in an earlier source (a resumed or
  copied transcript) is a cross-source duplicate and is not counted again.
- Context is the input the model received for that inference, including cached input.
  claude-jsonl: input_tokens + cache_creation_input_tokens + cache_read_input_tokens.
  codex-rollout: input_tokens, which already includes cached_input_tokens.
- codex-rollout per-call usage is last_token_usage when present, otherwise the difference
  between consecutive cumulative total_token_usage snapshots. A repeated identical snapshot
  is the same inference. A decreasing cumulative counter makes that inference unknown.
- Lines marked isSidechain inside a transcript are native subagent work. They are excluded
  from that source's context and reported as unattributed usage.
- An unknown value is null and its reason is in the adjacent "unknown" map; never 0.
  A source with no inferences has unknown totals. Each unknown total carries a
  known_lower_bound (the sum of known parts), which is a floor and never the total. Peak context is null when any parent
  inference has unknown context; known_max_context is then only a lower bound.

Usage: python3 bench/v2/tools/usage.py MANIFEST.json
Prints one JSON summary. Standard library only; reads files, never the network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ('input', 'cache_read', 'cache_write', 'output')
CLAUDE_FIELDS = {'input': 'input_tokens', 'cache_read': 'cache_read_input_tokens',
                 'cache_write': 'cache_creation_input_tokens', 'output': 'output_tokens'}
CODEX_FIELDS = {'input': 'input_tokens', 'cache_read': 'cached_input_tokens', 'output': 'output_tokens'}
FORMATS = ('claude-jsonl', 'codex-rollout')
ROLES = ('parent', 'worker', 'unattributed')


def known(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def when(stamp):
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None  # a time without a zone cannot be ordered against boundaries


def records(path: Path, gaps: list):
    with open(path, encoding='utf-8', errors='replace') as handle:
        for number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except ValueError:
                gaps.append({'source': path.name, 'kind': 'unparseable_line', 'detail': f'line {number}'})
                continue
            if isinstance(item, dict):
                yield number, item


def inference(identity, at, model, values: dict, reasons: dict, context_parts) -> dict:
    unknown = dict(reasons)
    missing = [f for f in context_parts if values.get(f) is None]
    context = None if missing else sum(values[f] for f in context_parts)
    if missing:
        unknown['context'] = 'needs ' + ', '.join(missing)
    return {'id': identity, 'at': at, 'model': model, **{f: values.get(f) for f in FIELDS},
            'context': context, 'unknown': unknown}


def parse_claude(path: Path, gaps: list) -> tuple[list, list, dict]:
    merged, order, stats = {}, [], {'duplicates_collapsed': 0, 'lines_without_identity': 0}
    for number, item in records(path, gaps):
        message = item.get('message') if isinstance(item.get('message'), dict) else {}
        if item.get('type') != 'assistant' or message.get('model') == '<synthetic>':
            continue
        identity = message.get('id') or item.get('requestId')
        if not identity:
            identity = f'{path.name}#line-{number}'
            stats['lines_without_identity'] += 1
            gaps.append({'source': path.name, 'kind': 'no_identity', 'detail': f'line {number} counted alone'})
        usage = message.get('usage') if isinstance(message.get('usage'), dict) else {}
        key = ('sidechain' if item.get('isSidechain') else 'main', identity)
        if key in merged:
            stats['duplicates_collapsed'] += 1
        else:
            order.append(key)
            merged[key] = {'at': item.get('timestamp'), 'model': message.get('model') or 'unknown', 'values': {}}
        values = merged[key]['values']
        for field, name in CLAUDE_FIELDS.items():
            value = usage.get(name)
            if known(value) and (values.get(field) is None or value > values[field]):
                values[field] = value
            else:
                values.setdefault(field, None)
    main, side = [], []
    for key in order:
        entry = merged[key]
        reasons = {f: f'usage.{CLAUDE_FIELDS[f]} missing or not a non-negative integer'
                   for f in FIELDS if entry['values'].get(f) is None}
        row = inference(key[1], entry['at'], entry['model'], entry['values'], reasons,
                        ('input', 'cache_write', 'cache_read'))
        (side if key[0] == 'sidechain' else main).append(row)
    return main, side, stats


def parse_codex(path: Path, gaps: list) -> tuple[list, list, dict]:
    rows, stats = [], {'duplicates_collapsed': 0, 'lines_without_identity': 0}
    model, previous, sequence = 'unknown', None, 0
    for number, item in records(path, gaps):
        payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
        if item.get('type') in ('session_meta', 'turn_context') and isinstance(payload.get('model'), str):
            model = payload['model']
        info = payload.get('info') if payload.get('type') == 'token_count' else None
        if not isinstance(info, dict):
            continue
        total = info.get('total_token_usage') if isinstance(info.get('total_token_usage'), dict) else None
        last = info.get('last_token_usage') if isinstance(info.get('last_token_usage'), dict) else None
        if total is not None and total == previous:
            stats['duplicates_collapsed'] += 1
            continue
        values, reasons = {}, {'cache_write': 'codex-rollout does not report cache writes'}
        for field, name in CODEX_FIELDS.items():
            if last is not None:
                value = last.get(name)
                values[field] = value if known(value) else None
                if values[field] is None:
                    reasons[field] = f'last_token_usage.{name} missing'
                if previous is not None and total is not None and known(value) and known(total.get(name)) \
                        and known(previous.get(name)) and total[name] - previous[name] != value:
                    gaps.append({'source': path.name, 'kind': 'per_call_vs_cumulative_mismatch',
                                 'detail': f'line {number} {name}: last_token_usage kept'})
            elif total is not None:
                now, before = total.get(name), (previous or {}).get(name, 0)
                if not known(now) or not known(before):
                    values[field], reasons[field] = None, f'total_token_usage.{name} missing'
                elif now < before:
                    values[field], reasons[field] = None, f'cumulative {name} decreased (reset or reordering)'
                    gaps.append({'source': path.name, 'kind': 'counter_decreased', 'detail': f'line {number} {name}'})
                else:
                    values[field] = now - before
            else:
                values[field], reasons[field] = None, 'token_count without usage'
        if last is None and previous is None and total is not None:
            gaps.append({'source': path.name, 'kind': 'assumption',
                         'detail': f'line {number}: first cumulative snapshot taken as usage from zero'})
        if total is not None:
            previous = total
        sequence += 1
        values['cache_write'] = None
        rows.append(inference(f'{path.name}#{sequence}', item.get('timestamp'), model, values, reasons, ('input',)))
    return rows, [], stats


def totals(rows: list, empty_reason: str) -> tuple[dict, dict]:
    result, unknown = {}, {}
    for field in (*FIELDS, 'context'):
        if not rows:
            result[field], unknown[field] = None, empty_reason
            continue
        missing = sum(1 for row in rows if row[field] is None)
        result[field] = None if missing else sum(row[field] for row in rows)
        if missing:
            unknown[field] = f'unknown in {missing} of {len(rows)} inference(s)'
    result['inferences'] = len(rows)
    result['known_lower_bound'] = lower_bound(result, [{f: r[f] for f in (*FIELDS, 'context')} for r in rows])
    return result, unknown


def lower_bound(result: dict, parts: list) -> dict:
    """For each unknown total, the sum of the values that are known: a floor, never the total."""
    bound = {}
    for field in (*FIELDS, 'context'):
        if result.get(field) is None:
            bound[field] = sum(p[field] if p.get(field) is not None else
                               (p.get('known_lower_bound') or {}).get(field, 0) for p in parts)
    return bound


def combine(parts: list, label: str) -> tuple[dict, dict]:
    result, unknown = {}, {}
    for field in (*FIELDS, 'context'):
        values = [p[0].get(field) for p in parts]
        if not parts:
            result[field], unknown[field] = None, f'no {label}'
        elif any(v is None for v in values):
            result[field] = None
            unknown[field] = f'unknown in {sum(v is None for v in values)} of {len(parts)} {label}'
        else:
            result[field] = sum(values)
    result['known_lower_bound'] = lower_bound(result, [p[0] for p in parts])
    return result, unknown


def summarise(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema_version') != 1:
        raise ValueError('manifest schema_version must be 1')
    base, gaps, seen = manifest_path.parent, [], set()
    sources, parent_rows, side_rows, workers, unattributed = [], [], [], {}, []
    for spec in manifest.get('sources', []):
        if spec.get('format') not in FORMATS or spec.get('role') not in ROLES:
            raise ValueError(f'source {spec.get("file")!r}: unknown format or role')
        path = (base / spec['file']).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError(f'source {spec["file"]!r} escapes the manifest directory')
        parse = parse_claude if spec['format'] == 'claude-jsonl' else parse_codex
        rows, side, stats = parse(path, gaps)
        counted = []
        for row in rows:
            key = (spec['format'], row['id'])
            if key in seen:
                stats['duplicates_collapsed'] += 1
                gaps.append({'source': path.name, 'kind': 'duplicate_across_sources', 'detail': row['id']})
                continue
            seen.add(key)
            counted.append(row)
        source_totals, source_unknown = totals(counted, 'no inferences found in source')
        stamps = sorted(s for s in (r['at'] for r in counted) if isinstance(s, str))
        sources.append({'file': spec['file'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'format': spec['format'], 'role': spec['role'], 'task_id': spec.get('task_id'),
                        'slot': spec.get('slot'), 'stage': spec.get('stage'), 'attempt': spec.get('attempt'),
                        **stats, 'first_at': stamps[0] if stamps else None, 'last_at': stamps[-1] if stamps else None,
                        'totals': source_totals, 'unknown': source_unknown})
        if side:
            side_rows.extend(side)
            gaps.append({'source': path.name, 'kind': 'native_sidechain_unattributed',
                         'detail': f'{len(side)} inference(s) excluded from this source'})
        if spec['role'] == 'parent':
            parent_rows.extend(counted)
        elif spec['role'] == 'worker':
            if not spec.get('task_id'):
                raise ValueError(f'worker source {spec["file"]!r} needs task_id')
            workers.setdefault(spec['task_id'], {'task_id': spec['task_id'], 'slot': spec.get('slot'),
                                                 'stage': spec.get('stage'), 'attempt': spec.get('attempt'),
                                                 'sources': [], 'rows': []})
            workers[spec['task_id']]['sources'].append(spec['file'])
            workers[spec['task_id']]['rows'].extend(counted)
        else:
            unattributed.append((spec['file'], counted))
            gaps.append({'source': path.name, 'kind': 'unattributed_source', 'detail': 'no owning task recorded'})

    parent_rows.sort(key=lambda r: (when(r['at']) is None, when(r['at']) or datetime(1, 1, 1, tzinfo=timezone.utc)))
    contexts = [r for r in parent_rows if r['context'] is not None]
    unknown_contexts = len(parent_rows) - len(contexts)
    peak = max(contexts, key=lambda r: r['context']) if contexts else None
    parent_totals, parent_unknown = totals(parent_rows, 'no parent inferences')
    boundary_rows = []
    for boundary in manifest.get('boundaries', []):
        at = when(boundary.get('at'))
        before = [r for r in parent_rows if at and when(r['at']) and when(r['at']) <= at]
        row = before[-1] if before else None
        reason = (None if row and row['context'] is not None else
                  'no parent inference before boundary' if row is None else row['unknown'].get('context'))
        boundary_rows.append({'stage': boundary.get('stage'), 'at': boundary.get('at'),
                              'inference': row['id'] if row else None,
                              'context': row['context'] if row else None, 'reason': reason})
    parent = {
        'inferences': parent_rows,
        'peak_context': None if unknown_contexts or not peak else peak['context'],
        'peak_inference': None if unknown_contexts or not peak else peak['id'],
        'known_max_context': peak['context'] if peak else None,
        'peak_reason': (f'context unknown for {unknown_contexts} parent inference(s); known_max_context is a lower bound'
                        if unknown_contexts else None if peak else 'no parent inferences'),
        'stage_boundary_context': boundary_rows,
        'totals': parent_totals, 'unknown': parent_unknown,
    }
    worker_list = []
    for worker in workers.values():
        worker_totals, worker_unknown = totals(worker.pop('rows'), 'no inferences found for task')
        worker_list.append(dict(worker, totals=worker_totals, unknown=worker_unknown))
    side_totals, side_unknown = totals(side_rows, 'none observed') if side_rows else ({}, {})
    attributed = [(parent_totals, parent_unknown)] + [(w['totals'], w['unknown']) for w in worker_list]
    extra = [totals(rows, 'no inferences found in source') for _, rows in unattributed]
    if side_rows:
        extra.append((side_totals, side_unknown))
    attributed_totals, attributed_unknown = combine(attributed, 'parent/worker totals')
    observed_totals, observed_unknown = combine(attributed + extra, 'observed totals')
    return {
        'schema_version': 1, 'protocol': 'bench-v2', 'sources': sources, 'parent': parent, 'workers': worker_list,
        'sidechain': {'inferences': len(side_rows), 'totals': side_totals, 'unknown': side_unknown},
        'unattributed_sources': [file for file, _ in unattributed],
        'aggregate': {'attribution_complete': not unattributed and not side_rows,
                      'attributed': {'totals': attributed_totals, 'unknown': attributed_unknown},
                      'all_observed': {'totals': observed_totals, 'unknown': observed_unknown}},
        'gaps': gaps,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(summarise(args.manifest), indent=2))
    except (OSError, ValueError) as exc:
        print(f'usage.py: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
