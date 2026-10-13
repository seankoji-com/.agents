#!/usr/bin/env python3
"""bench-v2 usage parser: per-inference context, deduplicated usage, cache and attribution.

Input is a run manifest (JSON); file paths in it are relative to the manifest:

  {"schema_version": 1,
   "sources": [{"file": "parent.jsonl", "format": "claude-jsonl" | "codex-rollout",
                "role": "parent" | "worker" | "unattributed",
                "task_id": "...", "slot": "...", "stage": "...", "attempt": 0,
                "resumed": false}],
   "boundaries": [{"stage": "s1", "at": "2026-10-12T00:10:00Z"}]}

Definitions, frozen with bench/v2/protocol.md:

- An inference is one model request. Claude JSONL repeats an assistant message once per
  content block: lines with the same message.id (else requestId) are one inference, each
  usage field taking the largest known value. Lines with neither ID are counted alone and
  reported as a gap. An identity already counted in an earlier source (a resumed or
  copied transcript) is a cross-source duplicate and is not counted again; its usage
  merges into the counted row by per-field maximum, independent of source order. A
  copy reporting a different model (a missing model reads as "unknown") is a usage
  conflict, whether it repeats the identity inside one capture or in another source;
  each such copy is compared with the first-counted one and attribution is then incomplete.
- Context is the input the model received for that inference, including cached input.
  claude-jsonl: input_tokens + cache_creation_input_tokens + cache_read_input_tokens.
  codex-rollout: input_tokens, which already includes cached_input_tokens.
- codex-rollout usage is validated per session before any of it is published. A session's
  per-call usage, totals and context are known only when every condition holds:
  1. no source carrying the session has a damaged, undecodable or non-object line;
  2. every token_count from the session's first usage report on has info.total_token_usage
     and info.last_token_usage, each with input, cached input and output tokens as
     non-negative integers (a token_count with null info before the first report claims none);
  3. inside each capture, a repeat collapses only when every reported counter and the event ID
     are identical; a repeat differing in any counter is a usage conflict, and otherwise no
     cumulative counter decreases;
  4. the session's first snapshot proves a zero start: its last_token_usage equals its
     total_token_usage, and a capture not marked "resumed" starts with it;
  5. every snapshot's last_token_usage equals the difference from the previous distinct snapshot;
  6. across captures the snapshots form one increasing sequence, each capture a contiguous run
     of it, and a snapshot recorded twice is identical in every counter and event ID.
  An inference is then one snapshot with last_token_usage as its usage, identified across
  captures by session and required counters. Otherwise the session's usage, totals and
  contexts are unknown, a gap names each failed condition and attribution is incomplete;
  known_lower_bound keeps only rows proven alone by conditions 2 and 5 (or a zero start) with
  nothing unread before them, from one capture so that copies are never summed. Rows without
  a session identity form a session of their own capture; a repeated snapshot there may be a
  copy or a new session, so it is ambiguous and the session unknown.
- A row without a stable identity is counted once per source and attribution is
  incomplete: a copy of it in another source cannot be recognised.
- An unparseable, truncated, non-object or undecodable line may have held an inference.
  Its source, role group and peak/boundary context are then unknown, the parsed usage is
  only a known_lower_bound, and attribution is incomplete. "inferences" counts parsed ones.
- Lines marked isSidechain inside a transcript are native subagent work. They are excluded
  from that source's context and reported as unattributed usage.
- An unknown value is null and its reason is in the adjacent "unknown" map; never 0.
  A source with no inferences has unknown totals. Each unknown total carries a
  known_lower_bound (the sum of known parts), which is a floor and never the total. Peak context is null when any parent
  inference has unknown context; known_max_context is then only a lower bound.
- A stage boundary's last inference is unknown, and attribution incomplete, when any parent
  inference lacks an orderable (timezone-aware) timestamp, when parent inferences from
  different sources share the last instant before it, or when the boundary time is invalid.
  A source's first_at/last_at order by instant and are unknown under the same conditions.
- A source's sha256 is computed over the exact bytes its single parsing read consumed, so
  usage, context, boundaries and the hash describe the same bytes. The file is never reread
  for hashing; bytes written after that read are not described by the summary.

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


# A damaged line may have held an inference: its source's totals and peak become unknown.
DAMAGE_KINDS = ('unparseable_line', 'non_object_line', 'undecodable_line')


def records(path: Path, gaps: list, digest=None):
    """Yield (line number, object) for each JSON object line; damaged lines become gaps.

    ``digest`` (a hashlib object), when given, is fed every byte this one read consumes, so
    the hash names exactly the bytes parsed, never a later read of the same path.
    """
    with open(path, 'rb') as handle:
        for number, data in enumerate(handle, 1):
            if digest is not None:
                digest.update(data)
            try:
                raw = data.decode('utf-8')
            except UnicodeDecodeError:
                gaps.append({'source': str(path), 'kind': 'undecodable_line', 'detail': f'line {number}'})
                raw = data.decode('utf-8', errors='replace')
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except ValueError:
                gaps.append({'source': str(path), 'kind': 'unparseable_line', 'detail': f'line {number}'})
                continue
            if isinstance(item, dict):
                yield number, item
            else:
                gaps.append({'source': str(path), 'kind': 'non_object_line', 'detail': f'line {number}'})


def inference(identity, at, model, values: dict, reasons: dict, context_parts) -> dict:
    unknown = dict(reasons)
    missing = [f for f in context_parts if values.get(f) is None]
    context = None if missing else sum(values[f] for f in context_parts)
    if missing:
        unknown['context'] = 'needs ' + ', '.join(missing)
    return {'id': identity, 'at': at, 'model': model, **{f: values.get(f) for f in FIELDS},
            'context': context, 'unknown': unknown}


def parse_claude(path: Path, gaps: list, digest=None) -> tuple[list, list, dict]:
    merged, order, stats = {}, [], {'duplicates_collapsed': 0, 'lines_without_identity': 0}
    for number, item in records(path, gaps, digest):
        message = item.get('message') if isinstance(item.get('message'), dict) else {}
        if item.get('type') != 'assistant' or message.get('model') == '<synthetic>':
            continue
        identity = message.get('id') or item.get('requestId')
        missing_identity = not identity
        if not identity:
            identity = f'line-{number}'
            stats['lines_without_identity'] += 1
            gaps.append({'source': str(path), 'kind': 'no_identity', 'detail': f'line {number} counted alone'})
        usage = message.get('usage') if isinstance(message.get('usage'), dict) else {}
        side_flag = bool(item.get('isSidechain'))
        key = ('sidechain' if side_flag else 'main', identity)
        model = message.get('model') or 'unknown'
        if key in merged:
            stats['duplicates_collapsed'] += 1
            if model != merged[key]['model']:  # compared as merge_duplicate compares copies across sources
                merged[key]['conflicts'].append(number)
        else:
            order.append(key)
            merged[key] = {'at': item.get('timestamp'), 'model': model, 'values': {},
                           'missing_identity': missing_identity, 'line': number, 'conflicts': []}
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
        # Authored IDs are authoritative: equal timestamps/usage do not make
        # different inferences duplicates. Identityless rows are source-local;
        # matching content is ambiguous and must never erase usage.
        row['_dedupe'] = (f"identity:{key[1]}" if not entry['missing_identity'] else
                          f"unknown:{path.resolve()}:{key[1]}")
        row['_conflicts'] = [f"line {line} names a different model than line {entry['line']}"
                             for line in entry['conflicts']]
        (side if key[0] == 'sidechain' else main).append(row)
    return main, side, stats


CODEX_CACHE_WRITE = 'codex-rollout does not report cache writes'
CODEX_UNREAD = 'a damaged line or a token_count without usage lies between this snapshot and the preceding one'


def parse_codex(path: Path, gaps: list, digest=None) -> tuple[list, list, dict]:
    """Collect each Codex session's token_count observations; resolve_codex validates them.

    Returns rows (one placeholder inference per usage report, filled by resolve_codex),
    the capture's session segments and stats. A segment is one session's contiguous run of
    observations in this capture. Only exact repeats collapse here, and only when the
    session is identified; no usage is derived before every capture has been read. A
    collapsed repeat naming a different model is kept on the row's ``_conflicts``.
    """
    rows, segments, stats = [], [], {'duplicates_collapsed': 0, 'lines_without_identity': 0}
    model, segment, scanned, damage, sequence = 'unknown', None, len(gaps), 0, 0
    models = {}  # each identified session's own latest model evidence in this capture

    def open_segment(session):
        # Damage before a session_meta precedes the session; without one it may be the session's own.
        segments.append({'session': session, 'observations': [], 'damage_start': damage if session is not None else 0})
        return segments[-1]

    for number, item in records(path, gaps, digest):
        damage += sum(gap['kind'] in DAMAGE_KINDS for gap in gaps[scanned:])
        scanned = len(gaps)
        payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
        if item.get('type') == 'session_meta':
            candidate = payload.get('id') or payload.get('session_id') or item.get('session_id')
            if isinstance(candidate, str) and candidate and (segment is None or segment['session'] != candidate):
                if segment is not None and segment['session'] is not None:
                    models[segment['session']] = model
                segment = open_segment(candidate)
                # A model is never carried into a different session; only this session's own evidence counts.
                model = models.get(candidate, 'unknown')
        if item.get('type') in ('session_meta', 'turn_context') and isinstance(payload.get('model'), str):
            model = payload['model']
        if payload.get('type') != 'token_count':
            continue
        if segment is None:
            segment = open_segment(None)
        info = payload.get('info')
        details = info if isinstance(info, dict) else {}
        total, last = details.get('total_token_usage'), details.get('last_token_usage')
        event_id = item.get('id') or details.get('id') or details.get('request_id')
        kind = ('empty' if info is None else
                'valid' if usage_counters(total) and usage_counters(last) else 'invalid')
        observation = {'line': number, 'at': item.get('timestamp'), 'event': event_id, 'total': total,
                       'last': last, 'kind': kind, 'damage': damage, 'repeat': False}
        previous = segment['observations'][-1] if segment['observations'] else None
        if previous is not None and kind != 'empty' and previous['kind'] != 'empty' and \
                (previous['total'], previous['last'], previous['event']) == (total, last, event_id):
            if segment['session'] is not None:
                stats['duplicates_collapsed'] += 1
                previous['damage'] = damage  # identical counters: nothing happened in between
                if model != previous['row']['model']:  # compared as merge_duplicate compares copies across sources
                    previous['row']['_conflicts'].append(f"line {number} names a different model than line {previous['line']}")
                continue
            observation['repeat'] = True  # without a session a repeat may be a copy or a new session
        segment['observations'].append(observation)
        if kind == 'empty':
            continue
        sequence += 1
        session = segment['session']
        if session is None:
            gaps.append({'source': str(path), 'kind': 'no_identity', 'detail': f'line {number} counted; dedupe uncertain'})
            display = f'unknown-event-{number}-{sequence}'
        elif event_id:
            display = f'{session}:{event_id}'
        elif usage_counters(total):
            display = f'{session}:cumulative-' + '-'.join(str(total[name]) for name in CODEX_FIELDS.values())
        else:
            display = f'{session}:line-{number}'
        row = inference(display, item.get('timestamp'), model, {f: None for f in FIELDS},
                        {'cache_write': CODEX_CACHE_WRITE}, ('input',))
        row['_codex'] = observation
        row['_local'] = f'unknown:{path.resolve()}:{number}:{sequence}'
        row['_conflicts'] = []
        observation['row'] = row
        rows.append(row)
    return rows, segments, stats


def usage_counters(value) -> bool:
    """A usage object reporting every required counter as a non-negative integer."""
    return isinstance(value, dict) and all(known(value.get(name)) for name in CODEX_FIELDS.values())


def snapshot_key(total: dict) -> tuple:
    """A cumulative snapshot's position in its session: the required counters only."""
    return tuple(total[name] for name in CODEX_FIELDS.values())


def delta_mismatches(last: dict, total: dict, previous) -> list:
    """Counters whose per-call value differs from the cumulative difference (no previous: zero).

    Required counters are always compared; an optional counter (total_tokens,
    reasoning_output_tokens) is compared whenever every snapshot involved reports it.
    """
    names = [name for name in last if known(last[name]) and known(total.get(name))
             and (previous is None or known(previous.get(name)))]
    return [name for name in names if total[name] - (previous[name] if previous is not None else 0) != last[name]]


def check_segment(segment: dict, damaged: int, session_usage=(False, None)) -> list:
    """Conditions 1-3 and 5 inside one capture; marks each observation proven or not.

    Returns problems as (kind, detail, observation). An observation is proven when it is
    complete and either starts its run from zero or is exactly its predecessor plus its
    per-call usage, with nothing unread (damage, a usage-less token_count) in between.
    ``session_usage`` is (has_usage, first_instant) for the whole session across captures:
    an empty token_count is exempt only when it provably precedes every usage report, and a
    snapshot whose required counters recur or decrease breaks the run, so later rows that
    copy an earlier request are never proven and never enter the floor.
    """
    has_usage, first_instant = session_usage
    problems, previous, seen_usage, unread, seen_keys, broken = [], None, False, False, set(), False
    if damaged:
        problems.append(('session_damaged', f'{damaged} damaged line(s) in this capture may hold the session\'s usage', None))
    for observation in segment['observations']:
        line, kind = observation['line'], observation['kind']
        if kind == 'empty':
            at = when(observation['at'])
            if seen_usage or has_usage and (first_instant is None or at is None or at >= first_instant):
                problems.append(('token_count_without_usage', f'line {line}: token_count without info after usage was reported', observation))
                unread = True
            continue
        observation['proven'], observation['why'] = False, None
        if kind == 'invalid':
            problems.append(('token_count_without_usage', f'line {line}: token_count lacks complete info.total_token_usage '
                             'and info.last_token_usage (input, cached input and output tokens)', observation))
            observation['why'] = 'token_count lacks complete total_token_usage and last_token_usage'
        if observation['repeat']:
            problems.append(('ambiguous_repeated_snapshot', f'line {line}: snapshot repeats without a session identity '
                             '(a copied line or a new session)', observation))
            observation['why'] = 'repeated snapshot without a session identity'
        complete = usage_counters(observation['total'])
        if complete and snapshot_key(observation['total']) in seen_keys:
            broken = True  # a replayed or reset snapshot: it and every later row are unproven
        if complete:
            seen_keys.add(snapshot_key(observation['total']))
        gap_before = unread or observation['damage'] > (previous['damage'] if previous else segment['damage_start'])
        ordered = previous is not None and usage_counters(previous['total']) and complete
        if ordered and snapshot_key(previous['total']) == snapshot_key(observation['total']) and not observation['repeat']:
            problems.append(('usage_conflict', f"line {line}: snapshot repeats line {previous['line']} "
                             'with a different counter or event ID', observation))
            observation['why'] = previous['why'] = 'the same snapshot is reported with different counters'
            previous['proven'] = False
        elif ordered:
            decreased = [name for name in CODEX_FIELDS.values() if observation['total'][name] < previous['total'][name]]
            for name in decreased:
                problems.append(('counter_decreased', f'line {line} {name}: cumulative counter decreased', observation))
            if decreased:
                observation['why'] = 'a cumulative counter decreased (reset or reordering)'
                broken = True
        if kind == 'valid' and observation['why'] is None and not broken:
            if previous is None and not gap_before and not delta_mismatches(observation['last'], observation['total'], None):
                observation['proven'] = True
            elif previous is None:
                observation['why'] = (CODEX_UNREAD if gap_before else 'first snapshot is not a zero start: '
                                      'last_token_usage differs from total_token_usage')
            elif previous['kind'] == 'valid':
                mismatched = delta_mismatches(observation['last'], observation['total'], previous['total'])
                for name in mismatched:
                    problems.append(('per_call_vs_cumulative_mismatch', f'line {line} {name}: last_token_usage '
                                     'differs from the cumulative difference', observation))
                observation['proven'] = not mismatched and not gap_before
                observation['why'] = (None if observation['proven'] else CODEX_UNREAD if gap_before else
                                      'last_token_usage disagrees with the cumulative counters')
            else:
                observation['why'] = 'a token_count without complete usage lies between this snapshot and the preceding one'
        previous, seen_usage, unread = observation, True, False
    return problems


def resolve_codex(parsed: list, damage: dict, gaps: list, conflicts: list, unknown_sessions: list) -> tuple[dict, dict]:
    """Publish Codex usage only for sessions every capture of which passes conditions 1-6.

    parsed holds (source index, spec, segments). Returns per-source counts of per-call
    mismatches and of sessions whose usage is unknown; both leave that source's totals unknown.
    """
    groups, mismatches, unproven = {}, {}, {}
    for index, spec, segments in parsed:
        for segment in segments:
            key = segment['session'] if segment['session'] is not None else ('local', index, id(segment))
            groups.setdefault(key, []).append((index, spec, segment))
    for key, members in groups.items():
        label = f'session {key}' if isinstance(key, str) else 'capture without a session identity'
        problems = []
        # The session's first usage instant, known across every capture: an empty token_count
        # is only exempt from the usage-less rule when it provably precedes it.
        instants = [when(o['at']) for _, _, segment in members for o in segment['observations'] if o['kind'] == 'valid']
        session_usage = (bool(instants), min(instants) if instants and all(i is not None for i in instants) else None)
        for index, spec, segment in members:
            for kind, detail, observation in check_segment(segment, damage[index], session_usage):
                problems.append((kind, detail, index, spec, observation))
        usage = [(index, spec, segment, [o for o in segment['observations'] if o['kind'] != 'empty'])
                 for index, spec, segment in members]
        # Alignment needs every snapshot complete; local order problems are already reported.
        if all(o['kind'] == 'valid' for *_, observations in usage for o in observations) and \
                all(kind in ('session_damaged', 'token_count_without_usage') for kind, *_ in problems):
            problems += check_alignment(usage)
        for kind, detail, index, spec, observation in problems:
            gap = {'source': spec['file'], 'kind': kind, 'detail': f'{label}: {detail}'}
            if kind == 'per_call_vs_cumulative_mismatch':
                mismatches[index] = mismatches.get(index, 0) + 1
            if kind == 'usage_conflict':
                first = observation.get('first_source', spec['file']) if observation else spec['file']
                gap['first_source'] = first
                conflicts.append({'source': spec['file'], 'first_source': first,
                                  'inference': observation['row']['id'] if observation else label,
                                  'fields': ['cumulative_snapshot']})
            gaps.append(gap)
        if not problems:
            for index, spec, segment, observations in usage:
                for observation in observations:
                    fill(observation, {f: observation['last'][CODEX_FIELDS[f]] for f in CODEX_FIELDS}, {})
                    observation['row']['_dedupe'] = (observation['row']['_local'] if segment['session'] is None else
                                                      f"{segment['session']}:cumulative:{json.dumps(snapshot_key(observation['total']))}")
            continue
        # Unknown session: rows are counted per capture and only one capture's individually
        # proven rows form the floor, so two copies of one request are never summed.
        reason = f'Codex {label}: usage unknown ({problems[0][1]})'
        unknown_sessions.append(label)
        for index in {index for index, _, _, _ in usage}:
            unproven[index] = unproven.get(index, 0) + 1
        floor = max(usage, key=lambda entry: sum(o['proven'] for o in entry[3]))
        for entry in usage:
            for observation in entry[3]:
                proven = entry is floor and observation['proven']
                values = ({f: observation['last'][CODEX_FIELDS[f]] for f in CODEX_FIELDS} if proven
                          else {f: None for f in CODEX_FIELDS})
                why = observation['why'] if entry is floor else 'another capture of this session supplies the floor'
                fill(observation, values, {} if proven else {f: f'{why}; {reason}' if why else reason for f in CODEX_FIELDS})
                observation['row']['_dedupe'] = observation['row']['_local']
    return mismatches, unproven


def check_alignment(usage: list) -> list:
    """Condition 6, then conditions 4 and 5 over the merged snapshot sequence of one session."""
    merged, events, problems = {}, {}, []
    for index, spec, segment, observations in usage:
        for observation in observations:
            snapshot = snapshot_key(observation['total'])
            if snapshot not in merged:
                merged[snapshot] = (index, spec, observation)
            else:
                _, first_spec, first = merged[snapshot]
                if (first['event'] is None) != (observation['event'] is None):
                    problems.append(('session_alignment_ambiguous', f"line {observation['line']}: captures mix explicit "
                                     'event IDs with snapshot identities', index, spec, observation))
                elif (first['total'], first['last'], first['event']) != \
                        (observation['total'], observation['last'], observation['event']):
                    observation['first_source'] = first_spec['file']
                    problems.append(('usage_conflict', f"line {observation['line']}: snapshot differs from the copy in "
                                     f"{first_spec['file']}", index, spec, observation))
            if observation['event'] is not None:
                earlier = events.setdefault(observation['event'], (snapshot, spec))
                if earlier[0] != snapshot:
                    observation['first_source'] = earlier[1]['file']
                    problems.append(('usage_conflict', f"line {observation['line']}: event {observation['event']} has "
                                     f"another snapshot in {earlier[1]['file']}", index, spec, observation))
    if problems or not merged:
        return problems
    order = sorted(merged)
    position = {snapshot: number for number, snapshot in enumerate(order)}
    for before, after in zip(order, order[1:]):
        if any(a < b for a, b in zip(after, before)):
            index, spec, observation = merged[after]
            problems.append(('session_alignment_ambiguous', f"line {observation['line']}: snapshots across captures "
                             'are not one increasing sequence', index, spec, observation))
    for index, spec, segment, observations in usage:
        places = [position[snapshot_key(o['total'])] for o in observations]
        if places and places != list(range(places[0], places[0] + len(places))):
            problems.append(('session_alignment_ambiguous', 'a capture skips a snapshot another capture records',
                             index, spec, observations[0]))
    if problems:
        return problems
    index, spec, first = merged[order[0]]
    starters = [s for _, s, _, observations in usage if observations and snapshot_key(observations[0]['total']) == order[0]]
    if delta_mismatches(first['last'], first['total'], None):
        problems.append(('cumulative_baseline_unknown', f"line {first['line']}: first snapshot is not a zero start "
                         '(last_token_usage differs from total_token_usage) and no earlier snapshot of this session '
                         'is in any source', index, spec, first))
    elif all(s.get('resumed') for s in starters):
        problems.append(('cumulative_baseline_unknown', f"line {first['line']}: only captures marked resumed start "
                         'this session; no earlier snapshot of it is in any source', index, spec, first))
    for before, after in zip(order, order[1:]):
        index, spec, observation = merged[after]
        for name in delta_mismatches(observation['last'], observation['total'], merged[before][2]['total']):
            problems.append(('per_call_vs_cumulative_mismatch', f"line {observation['line']} {name}: last_token_usage "
                             'differs from the cumulative difference', index, spec, observation))
    return problems


def fill(observation: dict, values: dict, reasons: dict) -> None:
    row = observation['row']
    reasons = dict(reasons, cache_write=CODEX_CACHE_WRITE)
    fresh = inference(row['id'], row['at'], row['model'], {**values, 'cache_write': None}, reasons, ('input',))
    row.update({key: fresh[key] for key in (*FIELDS, 'context', 'unknown')})


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
        bound[field] = sum(p[field] if p.get(field) is not None else
                           (p.get('known_lower_bound') or {}).get(field, 0) for p in parts)
    return bound


def hidden_usage(damaged: int, mismatched: int, subject: str = 'line(s) may hold inferences',
                 sessions: int = 0) -> str | None:
    """Why a capture may hold usage that no parsed inference accounts for, if it may."""
    parts = []
    if damaged:
        parts.append(f'{damaged} unparseable or truncated {subject}')
    if mismatched:
        parts.append(f'{mismatched} per-call usage record(s) disagree with the cumulative counters, '
                     'which may count requests the capture does not show')
    if sessions:
        parts.append(f'{sessions} Codex session(s) fail validation, so their usage is known only as a floor')
    return '; '.join(parts) or None


def damaged_totals(result: dict, unknown: dict, damaged: int, mismatched: int = 0, sessions: int = 0) -> None:
    """Parse damage or unaccounted usage hides usage: every total is unknown, its known parts only a floor."""
    if not damaged and not mismatched and not sessions:
        return
    reason = f'{hidden_usage(damaged, mismatched, sessions=sessions)}; known_lower_bound sums the parsed ones'
    for field in (*FIELDS, 'context'):
        result[field] = None
        unknown[field] = reason if field not in unknown else f'{reason}; {unknown[field]}'


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


def manifest_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate manifest key: {key}')
        result[key] = value
    return result

def reject_constant(value):
    raise ValueError(f'non-finite manifest number: {value}')


CONTEXT_PARTS = {'claude-jsonl': ('input', 'cache_write', 'cache_read'), 'codex-rollout': ('input',)}


def merge_duplicate(first: dict, row: dict, context_parts) -> list:
    """Fold a cross-source copy of an inference into its first-counted row.

    Each usage field takes the largest known value, as parse_claude does within one
    source, so a partial capture and its final copy give the same result in either
    order. Returns the fields that cannot be merged that way (a different model).
    """
    conflicts = []
    if first['model'] != row['model']:
        conflicts.append('model')
    for field in FIELDS:
        value = row.get(field)
        if value is not None and (first[field] is None or value > first[field]):
            first[field] = value
        if first[field] is not None:
            first['unknown'].pop(field, None)
    stamps = [s for s in (first['at'], row['at']) if when(s) is not None]
    if stamps:
        first['at'] = min(stamps, key=when)
    if all(first[f] is not None for f in context_parts):
        first['context'] = sum(first[f] for f in context_parts)
        first['unknown'].pop('context', None)
    return conflicts


def summarise(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(), object_pairs_hook=manifest_pairs, parse_constant=reject_constant)
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest.get('schema_version') != 1:
        raise ValueError('manifest schema_version must be 1')
    if set(manifest) - {'schema_version', 'sources', 'boundaries'}:
        raise ValueError('manifest contains unsupported fields')
    if not isinstance(manifest.get('sources'), list) or not isinstance(manifest.get('boundaries', []), list):
        raise ValueError('manifest sources and boundaries must be arrays')
    base, gaps, seen = manifest_path.parent, [], set()
    sources, parent_rows, side_rows, workers, unattributed = [], [], [], {}, []
    seen, seen_owners, seen_sources = set(), {}, {}
    first_rows, conflicts, pending_totals, parent_damage, parent_mismatch, parent_unproven = {}, [], [], 0, 0, 0

    def record_local_conflicts(row, spec):
        # Copies inside one capture are compared exactly as copies across captures are.
        for detail in row.pop('_conflicts', ()):
            conflicts.append({'source': spec['file'], 'first_source': spec['file'],
                              'inference': row['id'], 'fields': ['model']})
            gaps.append({'source': spec['file'], 'first_source': spec['file'], 'kind': 'usage_conflict',
                         'detail': f"{row['id']}: model differs within source ({detail})"})

    def record_merge(key, row, spec):
        first = first_rows[key]
        if first is row:
            return
        before = {f: first[f] for f in FIELDS}
        fields = merge_duplicate(first, row, CONTEXT_PARTS[spec['format']])
        if fields:
            conflicts.append({'source': spec['file'], 'first_source': seen_sources[key],
                              'inference': row['id'], 'fields': fields})
            gaps.append({'source': spec['file'], 'first_source': seen_sources[key], 'kind': 'usage_conflict',
                         'detail': f"{row['id']}: {', '.join(fields)} differ across sources"})
        if before != {f: first[f] for f in FIELDS}:
            gaps.append({'source': spec['file'], 'first_source': seen_sources[key],
                         'kind': 'usage_merged_across_sources', 'detail': f"{row['id']}: per-field maximum kept"})
    parsed, unknown_sessions, damage, identityless = [], [], {}, []
    for source_index, spec in enumerate(manifest.get('sources', [])):
        if not isinstance(spec, dict) or not isinstance(spec.get('file'), str) or not spec.get('file'):
            raise ValueError('each source needs a non-empty string file')
        if set(spec) - {'file', 'format', 'role', 'task_id', 'slot', 'stage', 'attempt', 'resumed'}:
            raise ValueError(f'source {spec.get("file")!r} contains unsupported fields')
        if (spec.get('format') not in FORMATS or spec.get('role') not in ROLES
                or any(k in spec and spec[k] is not None and (not isinstance(spec[k], str) or not spec[k])
                       for k in ('task_id', 'slot', 'stage'))
                or ('attempt' in spec and (isinstance(spec['attempt'], bool) or not isinstance(spec['attempt'], int)
                                           or spec['attempt'] < 0))
                or not isinstance(spec.get('resumed', False), bool)):
            raise ValueError(f'source {spec.get("file")!r}: unknown format or role')
        if spec['role'] == 'worker' and not spec.get('task_id'):
            raise ValueError(f'worker source {spec["file"]!r} needs task_id')
        path = (base / spec['file']).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError(f'source {spec["file"]!r} escapes the manifest directory')
        gap_start, read = len(gaps), hashlib.sha256()
        # The reported sha256 is of the bytes this parse read; a later change to the file is not them.
        if spec['format'] == 'claude-jsonl':
            (rows, side, stats), segments = parse_claude(path, gaps, read), []
        else:
            (rows, segments, stats), side = parse_codex(path, gaps, read), []
        for gap in gaps[gap_start:]:
            gap['source'] = spec['file']
        damage[source_index] = sum(gap['kind'] in DAMAGE_KINDS for gap in gaps[gap_start:])
        parsed.append((source_index, spec, read.hexdigest(), rows, side, stats, segments))
    # A Codex session's usage is published only after every capture of it is validated
    # together (resolve_codex), and before cross-source copies are merged.
    mismatch, unproven = resolve_codex([(index, spec, segments) for index, spec, _, _, _, _, segments in parsed],
                                       damage, gaps, conflicts, unknown_sessions)
    for source_index, spec, parsed_sha256, rows, side, stats, _ in parsed:
        mismatch.setdefault(source_index, 0)
        unproven.setdefault(source_index, 0)
        counted = []
        for row in rows:
            row.pop('_codex', None)
            row.pop('_local', None)
            record_local_conflicts(row, spec)
            identity = row.pop('_dedupe', row['id'])
            if isinstance(identity, str) and identity.startswith('unknown:'):
                identity = f'{identity}:manifest-source-{source_index}'
                identityless.append(row['id'])  # a copy elsewhere cannot be recognised
            key = (spec['format'], identity)
            row['source'] = spec['file']
            owner = tuple(spec.get(k) for k in ('role', 'task_id', 'slot', 'stage', 'attempt')) + ('main',)
            if key in seen_owners and seen_owners[key] != owner:
                raise ValueError(f'inference identity {row["id"]!r} has conflicting role/task ownership')
            seen_owners[key] = owner
            if key in seen:
                stats['duplicates_collapsed'] += 1
                gaps.append({'source': spec['file'], 'first_source': seen_sources[key],
                             'kind': 'duplicate_across_sources', 'detail': row['id']})
                record_merge(key, row, spec)
                continue
            seen.add(key)
            seen_sources[key] = spec['file']
            first_rows[key] = row
            counted.append(row)
        # Per-source totals wait until every source is read: a later copy of an
        # inference can still raise the usage of a row counted here.
        entry = {'file': spec['file'], 'sha256': parsed_sha256,
                 'format': spec['format'], 'role': spec['role'], 'task_id': spec.get('task_id'),
                 'slot': spec.get('slot'), 'stage': spec.get('stage'), 'attempt': spec.get('attempt'),
                 **stats, 'damaged_lines': damage[source_index], 'usage_mismatches': mismatch[source_index],
                 'first_at': None, 'last_at': None, 'totals': None, 'unknown': None}
        sources.append(entry)
        pending_totals.append((entry, counted, damage[source_index], mismatch[source_index], unproven[source_index]))
        side_counted = []
        for row in side:
            record_local_conflicts(row, spec)
            identity = row.pop('_dedupe', row['id'])
            if isinstance(identity, str) and identity.startswith('unknown:'):
                identity = f'{identity}:manifest-source-{source_index}'
                identityless.append(row['id'])
            key = (spec['format'], identity)
            row['source'] = spec['file']
            owner = tuple(spec.get(k) for k in ('role', 'task_id', 'slot', 'stage', 'attempt')) + ('sidechain',)
            if key in seen_owners and seen_owners[key] != owner:
                raise ValueError(f'sidechain inference identity {row["id"]!r} has conflicting role/task ownership')
            seen_owners[key] = owner
            if key in seen:
                gaps.append({'source': spec['file'], 'first_source': seen_sources[key],
                             'kind': 'duplicate_sidechain_across_sources', 'detail': row['id']})
                record_merge(key, row, spec)
            else:
                seen.add(key)
                seen_sources[key] = spec['file']
                first_rows[key] = row
                side_counted.append(row)
        if side_counted:
            side_rows.extend(side_counted)
            gaps.append({'source': spec['file'], 'kind': 'native_sidechain_unattributed',
                         'detail': f'{len(side_counted)} inference(s) excluded from this source'})
        if spec['role'] == 'parent':
            parent_rows.extend(counted)
            parent_damage += damage[source_index]
            parent_mismatch += mismatch[source_index]
            parent_unproven += unproven[source_index]
        elif spec['role'] == 'worker':
            existing = workers.get(spec['task_id'])
            metadata = (spec.get('slot'), spec.get('stage'), spec.get('attempt'))
            if existing and metadata != (existing['slot'], existing['stage'], existing['attempt']):
                raise ValueError(f'worker task {spec["task_id"]!r} has conflicting slot/stage/attempt metadata')
            workers.setdefault(spec['task_id'], {'task_id': spec['task_id'], 'slot': spec.get('slot'),
                                                 'stage': spec.get('stage'), 'attempt': spec.get('attempt'),
                                                 'sources': [], 'rows': [], 'damage': 0, 'mismatch': 0, 'unproven': 0})
            workers[spec['task_id']]['sources'].append(spec['file'])
            workers[spec['task_id']]['damage'] += damage[source_index]
            workers[spec['task_id']]['mismatch'] += mismatch[source_index]
            workers[spec['task_id']]['unproven'] += unproven[source_index]
            workers[spec['task_id']]['rows'].extend(counted)
        else:
            unattributed.append((spec['file'], counted, damage[source_index], mismatch[source_index], unproven[source_index]))
            gaps.append({'source': spec['file'], 'kind': 'unattributed_source', 'detail': 'no owning task recorded'})

    for entry, counted, damaged, mismatched, sessions in pending_totals:
        # Order by instant, never by string: offsets and naive times do not sort lexically.
        stamps = sorted((r['at'] for r in counted if when(r['at']) is not None), key=when)
        entry['first_at'], entry['last_at'] = (stamps[0], stamps[-1]) if stamps else (None, None)
        entry['totals'], entry['unknown'] = totals(counted, 'no inferences found in source')
        damaged_totals(entry['totals'], entry['unknown'], damaged, mismatched, sessions)
        unordered = len(counted) - len(stamps)
        span_reason = '; '.join(filter(None, (
            hidden_usage(damaged, mismatched, sessions=sessions),
            f'{unordered} inference(s) have a missing, invalid or timezone-naive timestamp' if unordered else None)))
        if counted and span_reason:
            entry['first_at'] = entry['last_at'] = None
            entry['unknown']['first_at'] = entry['unknown']['last_at'] = span_reason
    parent_rows.sort(key=lambda r: (when(r['at']) is None, when(r['at']) or datetime(1, 1, 1, tzinfo=timezone.utc)))
    contexts = [r for r in parent_rows if r['context'] is not None]
    unknown_contexts = len(parent_rows) - len(contexts)
    peak = max(contexts, key=lambda r: r['context']) if contexts else None
    parent_totals, parent_unknown = totals(parent_rows, 'no parent inferences')
    damaged_totals(parent_totals, parent_unknown, parent_damage, parent_mismatch, parent_unproven)
    damage_reason = hidden_usage(parent_damage, parent_mismatch, 'parent line(s) may hold a larger or later inference',
                                 parent_unproven)
    boundary_rows, unordered_boundaries = [], 0
    bad_time_rows = [r for r in parent_rows if when(r['at']) is None]
    # One parent inference that cannot be placed in time may fall before any boundary,
    # so no boundary's last inference is known, even where older ones are orderable.
    order_reason = (f'parent timestamps missing, invalid, or timezone-naive for {len(bad_time_rows)} '
                    'inference(s); cannot attribute boundary' if bad_time_rows else None)
    if manifest.get('boundaries'):
        for bad_row in bad_time_rows:
            gaps.append({'source': bad_row['source'], 'kind': 'timestamp_unorderable', 'detail': bad_row['id']})
    for boundary in manifest.get('boundaries', []):
        if not isinstance(boundary, dict) or set(boundary) - {'stage', 'at'} or not isinstance(boundary.get('stage'), str):
            raise ValueError('each boundary needs only a string stage and timestamp')
        at = when(boundary.get('at'))
        if at is None:
            unordered_boundaries += 1
            boundary_rows.append({'stage': boundary.get('stage'), 'at': boundary.get('at'),
                                  'inference': None, 'context': None, 'reason': 'boundary timestamp missing, invalid, or timezone-naive'})
            gaps.append({'source': '<manifest>', 'kind': 'invalid_boundary_timestamp', 'detail': str(boundary.get('at'))})
            continue
        before = [r for r in parent_rows if when(r['at']) is not None and when(r['at']) <= at]
        row = before[-1] if before else None
        # Inferences from different captures stamped with the same instant have no known order.
        tied = row is not None and len({r['source'] for r in before if when(r['at']) == when(row['at'])}) > 1
        reason = (None if row and row['context'] is not None else
                  'no parent inference before boundary' if row is None else row['unknown'].get('context'))
        unordered = '; '.join(filter(None, (
            order_reason, 'parent inferences from different sources share the last timestamp before the '
            'boundary; their order is unknown' if tied else None)))
        if unordered:
            unordered_boundaries += 1
            gaps.append({'source': '<manifest>', 'kind': 'boundary_order_unknown',
                         'detail': f"{boundary.get('stage')}: {unordered}"})
        override = '; '.join(filter(None, (damage_reason, unordered)))
        if override:
            reason = override
        boundary_rows.append({'stage': boundary.get('stage'), 'at': boundary.get('at'),
                              'inference': row['id'] if row and not override else None,
                              'context': row['context'] if row and not override else None, 'reason': reason})
    peak_unknown = unknown_contexts or parent_damage or parent_mismatch or parent_unproven
    parent = {
        'inferences': parent_rows,
        'peak_context': None if peak_unknown or not peak else peak['context'],
        'peak_inference': None if peak_unknown or not peak else peak['id'],
        'known_max_context': peak['context'] if peak else None,
        'peak_reason': (f'context unknown for {unknown_contexts} parent inference(s); known_max_context is a lower bound'
                        if unknown_contexts else f'{damage_reason}; known_max_context is a lower bound'
                        if damage_reason else None if peak else 'no parent inferences'),
        'stage_boundary_context': boundary_rows,
        'totals': parent_totals, 'unknown': parent_unknown,
    }
    worker_list = []
    for worker in workers.values():
        worker_rows, worker_damage = worker.pop('rows'), worker.pop('damage')
        worker_mismatch, worker_unproven = worker.pop('mismatch'), worker.pop('unproven')
        worker_totals, worker_unknown = totals(worker_rows, 'no inferences found for task')
        damaged_totals(worker_totals, worker_unknown, worker_damage, worker_mismatch, worker_unproven)
        worker_list.append(dict(worker, inferences=worker_rows, totals=worker_totals, unknown=worker_unknown))
    side_totals, side_unknown = totals(side_rows, 'none observed') if side_rows else ({}, {})
    if side_rows:  # a damaged Claude line may have been a sidechain inference
        damaged_totals(side_totals, side_unknown,
                       sum(damage[index] for index, spec, *_ in parsed if spec['format'] == 'claude-jsonl'))
    attributed = [(parent_totals, parent_unknown)] + [(w['totals'], w['unknown']) for w in worker_list]
    extra = []
    for _, rows, damaged, mismatched, sessions in unattributed:
        extra.append(totals(rows, 'no inferences found in source'))
        damaged_totals(*extra[-1], damaged, mismatched, sessions)
    if side_rows:
        extra.append((side_totals, side_unknown))
    attributed_totals, attributed_unknown = combine(attributed, 'parent/worker totals')
    observed_totals, observed_unknown = combine(attributed + extra, 'observed totals')
    return {
        'schema_version': 1, 'protocol': 'bench-v2', 'sources': sources, 'parent': parent, 'workers': worker_list,
        'sidechain': {'inferences': len(side_rows), 'totals': side_totals, 'unknown': side_unknown},
        'unattributed_sources': [file for file, *_ in unattributed],
        'aggregate': {'attribution_complete': not unattributed and not side_rows and not conflicts
                                              and not unknown_sessions and not any(damage.values())
                                              and not any(mismatch.values()) and not identityless
                                              and not unordered_boundaries,
                      'usage_conflicts': conflicts,
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
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f'usage.py: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
