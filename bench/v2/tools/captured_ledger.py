#!/usr/bin/env python3
"""Create and verify coordinator-owned prelaunch and captured-transport ledgers.

The files must be written in a location that the worker cannot modify. Hashes
bind their contents, but do not prove authorship against a privileged forger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def create_prelaunch(scenario: str, run_id: str, nonce: str, inputs: dict[str, str], path: Path) -> dict:
    record = {'schema_version': 1, 'kind': 'prelaunch', 'scenario': scenario,
              'run_id': run_id, 'prelaunch_nonce': nonce, 'input_sha256': inputs}
    record['ledger_sha256'] = digest_bytes(canonical(record))
    write_record(path, record)
    return record


def create_capture(prelaunch_path: Path, context_path: Path, path: Path) -> dict:
    prelaunch = json.loads(prelaunch_path.read_text(encoding='utf-8'))
    context = json.loads(context_path.read_text(encoding='utf-8'))
    body = {'schema_version': 1, 'kind': 'captured-transport',
            'prelaunch_sha256': digest_file(prelaunch_path),
            'context_sha256': digest_file(context_path),
            'run_id': prelaunch['run_id'], 'scenario': prelaunch['scenario'],
            'observed_ids': context['observed_ids'],
            'artifact_sha256': {name: row['sha256'] for name, row in context['artifacts'].items()}}
    body['capture_sha256'] = digest_bytes(canonical(body))
    write_record(path, body)
    return body


def verify(prelaunch_path: Path | None, context_path: Path | None, capture_path: Path | None,
           scenario: str, input_sha256: dict[str, str], outputs: list[str], required_ids: list[str]) -> dict[str, bool]:
    prelaunch_path = Path(prelaunch_path) if prelaunch_path is not None else None
    context_path = Path(context_path) if context_path is not None else None
    capture_path = Path(capture_path) if capture_path is not None else None
    checks = {'ledger-paths-required': bool(prelaunch_path and context_path and capture_path)}
    if not checks['ledger-paths-required']:
        return checks
    try:
        assert prelaunch_path is not None and context_path is not None and capture_path is not None
        p = json.loads(prelaunch_path.read_text(encoding='utf-8'))
        c = json.loads(context_path.read_text(encoding='utf-8'))
        t = json.loads(capture_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {**checks, 'ledger-records-readable': False}
    if not all(isinstance(record, dict) for record in (p, c, t)):
        return {**checks, 'ledger-records-objects': False}
    p_hash_body = dict(p)
    p_hash = p_hash_body.pop('ledger_sha256', None)
    t_hash_body = dict(t)
    t_hash = t_hash_body.pop('capture_sha256', None)
    checks.update({
        'ledger-records-readable': True,
        'prelaunch-ledger-integrity': p.get('schema_version') == 1 and p.get('kind') == 'prelaunch' and p_hash == digest_bytes(canonical(p_hash_body)),
        'capture-ledger-integrity': t.get('schema_version') == 1 and t.get('kind') == 'captured-transport' and t_hash == digest_bytes(canonical(t_hash_body)),
        'prelaunch-scenario-and-inputs': p.get('scenario') == scenario and p.get('input_sha256') == input_sha256,
        'context-bound-to-prelaunch': c.get('scenario') == p.get('scenario') == scenario and c.get('run_id') == p.get('run_id') and c.get('prelaunch_nonce') == p.get('prelaunch_nonce'),
        'capture-bound-to-records': t.get('prelaunch_sha256') == digest_file(prelaunch_path) and t.get('context_sha256') == digest_file(context_path) and t.get('run_id') == p.get('run_id') and t.get('scenario') == scenario,
        'capture-covers-observed-ids': isinstance(t.get('observed_ids'), dict) and t.get('observed_ids') == c.get('observed_ids') and set(required_ids) <= set(t.get('observed_ids', {})),
    })
    artifacts = c.get('artifacts', {})
    checks['capture-covers-output-hashes'] = (isinstance(artifacts, dict) and set(artifacts) == set(outputs) and
        t.get('artifact_sha256') == {name: row.get('sha256') for name, row in artifacts.items() if isinstance(row, dict)})
    return checks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    pre = sub.add_parser('prelaunch'); pre.add_argument('scenario'); pre.add_argument('run_id'); pre.add_argument('nonce'); pre.add_argument('inputs_json'); pre.add_argument('output')
    cap = sub.add_parser('capture'); cap.add_argument('prelaunch'); cap.add_argument('context'); cap.add_argument('output')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prelaunch':
            result = create_prelaunch(args.scenario, args.run_id, args.nonce, json.loads(Path(args.inputs_json).read_text()), Path(args.output))
        else:
            result = create_capture(Path(args.prelaunch), Path(args.context), Path(args.output))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f'captured_ledger.py: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
