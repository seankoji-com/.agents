#!/usr/bin/env python3
"""Planning review APIs as deterministic JSON-file commands. Never dispatches."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.jobs.store import _regular, strict_load
from shared.job_coordinator import pinned_store
from shared import planning_review as planning
from core.errors import CoreError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('capture', 'check-draft', 'create', 'begin', 'next', 'launch', 'host-event',
        'unavailable', 'result', 'direct', 'disposition', 'owner-decision', 'revoke-sharing', 'finish', 'validate', 'release'))
    parser.add_argument('--input', required=True)
    parser.add_argument('--state-root')
    parser.add_argument('--job')
    parser.add_argument('--prefix')
    parser.add_argument('--agents-root')
    args = parser.parse_args(argv)
    try:
        data = strict_load(_regular(Path(args.input)))
        if args.command == 'capture':
            out = planning.capture(data)
        elif args.command == 'check-draft':
            out = planning.check_draft(data['brief_file'], data['brief_sha256'], data['result_file'])
            print(json.dumps(out, sort_keys=True, ensure_ascii=False))
            return 0 if out['valid'] else 2
        elif args.command == 'validate':
            out = planning.validate_receipt(data['reference'], expected_snapshot=data.get('expected_snapshot'))
            if data.get('report_head'):
                out = {'receipt': out, 'head_observation': planning.head_observation(out['snapshot'])}
        elif args.command == 'create':
            planning.need(all((args.state_root, args.prefix, args.agents_root)), 'create needs state root, prefix and agents root')
            out = planning.create(data, args.state_root, args.prefix, args.agents_root)
        else:
            planning.need(args.state_root and args.job, 'job and state root required')
            store = pinned_store(args.state_root, args.job)
            caller = data['caller']
            if args.command == 'begin':
                out = planning.begin(store, caller, data.get('snapshot'), data.get('requested_rereview', False))
            elif args.command == 'next':
                job = planning.verify_all_pins(store, caller)
                planning.manifest_policy(job)
                out = planning.next_candidate(job, data['slot_id'], data.get('sharing'))
            elif args.command == 'launch':
                out = planning.launch(store, caller, data['slot_id'], data['request_id'], data.get('sharing'))
            elif args.command == 'host-event':
                out = planning.host_event(store, caller, data['task_id'], data['event'])
            elif args.command == 'unavailable':
                out = planning.unavailable(store, caller, data['task_id'], data['failure'])
            elif args.command == 'result':
                out = planning.ingest(store, caller, data['task_id'], _regular(Path(data['result_file']), max_bytes=32768), data['completion_id'])
            elif args.command == 'direct':
                out = planning.direct(store, caller, data['observation'], data.get('sharing'))
            elif args.command == 'disposition':
                out = planning.disposition(store, caller, data['finding_key'], data['status'], data['evidence'])
            elif args.command == 'owner-decision':
                out = planning.owner_decision(store, caller, data['decision'])
            elif args.command == 'revoke-sharing':
                out = planning.revoke_sharing(store, caller, data['grants'], data['source'], data['source_file'])
            elif args.command == 'finish':
                out = planning.finish_round(store, caller)
            else:
                out = planning.release(store, caller)
        print(json.dumps(out, sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, StopIteration, CoreError) as exc:
        print('planning_review_error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
