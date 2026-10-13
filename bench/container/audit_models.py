#!/usr/bin/env python3
"""Emit complete, conservative model attribution from isolated provider transcripts."""
import argparse
import json
from pathlib import Path

ROOTS = {'claudeAgent': Path('/opt/bench-home/.claude/projects'),
         'codex': Path('/opt/bench-home/.codex/sessions')}


def scan(path, provider):
    model = None
    seen = 0
    malformed = 0
    unknown = 0
    ids = set()
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return {'ids': ids, 'inferences': 0, 'unknown': 0, 'malformed': 0,
                'read_error': True, 'unclassified': False}
    for raw in lines:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(item, dict):
            malformed += 1
            continue
        if provider == 'claudeAgent':
            if item.get('type') != 'assistant':
                continue
            seen += 1
            message = item.get('message')
            actual = message.get('model') if isinstance(message, dict) else None
            if isinstance(actual, str) and actual and actual != '<synthetic>':
                ids.add(actual)
            else:
                unknown += 1
        else:
            payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
            if item.get('type') in ('session_meta', 'turn_context'):
                actual = payload.get('model')
                model = actual if isinstance(actual, str) and actual else None
                if model is None:
                    unknown += 1
            if item.get('type') == 'response_item':
                seen += 1
                if model:
                    ids.add(model)
                else:
                    unknown += 1
            elif (item.get('type') == 'event_msg' and isinstance(payload, dict)
                  and payload.get('type') == 'token_count'):
                seen += 1
                if model:
                    ids.add(model)
                else:
                    unknown += 1
    return {'ids': ids, 'inferences': seen, 'unknown': unknown,
            'malformed': malformed, 'read_error': False,
            'unclassified': seen == 0}


def audit(roots, targets, response_identities=None):
    result = {}
    for provider, root in roots.items():
        files = sorted(root.rglob('*.jsonl')) if root.exists() else []
        ids = set()
        total_inferences = total_unknown = total_malformed = unreadable = unclassified = 0
        sources = []
        for path in files:
            row = scan(path, provider)
            ids.update(row['ids'])
            total_inferences += row['inferences']
            total_unknown += row['unknown']
            total_malformed += row['malformed']
            unreadable += int(row['read_error'])
            unclassified += int(row['unclassified'])
            sources.append({'source': path.name, 'inferences': row['inferences'],
                            'unknown_records': row['unknown'], 'malformed_records': row['malformed'],
                            'read_error': row['read_error'], 'unclassified': row['unclassified']})
        expected = (response_identities[provider]['response_model_id'] if response_identities is not None else targets[provider]['model'])
        reasons = []
        if total_inferences == 0:
            reasons.append('no attributable inference records')
        if total_unknown:
            reasons.append('inference records have unknown model attribution')
        if total_malformed:
            reasons.append('malformed transcript records were skipped')
        if unreadable:
            reasons.append('one or more transcript sources could not be read')
        if unclassified:
            reasons.append('one or more transcript sources had no recognized inference records')
        if ids != {expected}:
            reasons.append('observed model IDs do not equal the frozen target')
        result[provider] = {'expected': expected, 'actual_ids': sorted(ids),
                            'transcript_files': len(files), 'inference_records': total_inferences,
                            'unknown_records': total_unknown, 'malformed_records': total_malformed,
                            'unreadable_sources': unreadable, 'unclassified_sources': unclassified,
                            'sources': sources, 'reasons': reasons,
                            'verified': not reasons}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=tuple(ROOTS), required=True)
    args = parser.parse_args()
    from identity_metadata import valid_identity
    policy = json.loads(Path('/bench/config/runtime-targets.json').read_text(encoding='utf-8'))
    targets = policy['targets']
    identities = policy.get('response_identity_metadata', {}).get('identities', {})
    if not valid_identity(identities.get(args.provider), args.provider, targets[args.provider]['model']):
        print(json.dumps({'verified': False, 'reason': 'primary response identity metadata unavailable'}))
        return 2
    entries = audit({args.provider: ROOTS[args.provider]}, targets, identities)
    verified = entries[args.provider]['verified']
    print(json.dumps({'provider': args.provider, 'model_audit': entries[args.provider],
                      'verified': verified}, sort_keys=True))
    return 0 if verified else 2


if __name__ == '__main__':
    raise SystemExit(main())
