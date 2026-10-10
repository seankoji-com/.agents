#!/usr/bin/env python3
"""Live conformance helpers. They build fixtures and collect and grade evidence;
they never start a model or a provider. Live runs happen in T3 threads (see
conformance/procedure.md).

  conformance.py setup --dest DIR                      fixture repo, one branch per case
  conformance.py find-run --worktree PATH [--since ISO]
  conformance.py collect --run-id ID --provider P --model M --case C --repeat N
                         --t3-version V --thread-id T [--transcript FILE] [--elapsed S]
                         [--interventions N] [--note TEXT]
  conformance.py compile                               compatibility.json -> compatibility.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFORMANCE = ROOT / 'conformance'
CASES = json.loads((CONFORMANCE / 'cases.json').read_text())
FIXTURE = ROOT / 'tests' / 'fixtures' / 'bugfix-cli'
GIT_ENV = {'GIT_AUTHOR_NAME': 'imps conformance', 'GIT_AUTHOR_EMAIL': 'conformance@example.invalid',
           'GIT_COMMITTER_NAME': 'imps conformance', 'GIT_COMMITTER_EMAIL': 'conformance@example.invalid'}
HOME = str(Path.home())


def state_root() -> Path:
    explicit = os.environ.get('T3_PLUGINS_STATE_ROOT')
    if explicit:
        return Path(explicit).expanduser()
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state') / 't3-plugins' / 'imps'


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True,
                          env=dict(os.environ, **GIT_ENV)).stdout.strip()


def sanitise(text: str) -> str:
    if HOME in ('', '/'):
        return text
    return re.sub(r'(?<![\w.~/-])' + re.escape(HOME) + r'(?![\w.-])', '~', text)


def setup(args):
    dest = Path(args.dest).expanduser().resolve()
    if dest.exists():
        raise SystemExit(f'{dest} exists; choose a new directory')
    shutil.copytree(FIXTURE, dest, ignore=shutil.ignore_patterns('__pycache__', '.claude', '.mcp.json'))
    git(dest, 'init', '-q', '-b', 'main')
    git(dest, 'add', '-A')
    git(dest, 'commit', '-qm', 'wordstat fixture')
    for name, case in CASES['cases'].items():
        git(dest, 'checkout', '-q', '-b', case['branch'], 'main')
        policy = dict(case['policy'], model_preferences=CASES['model_preferences'])
        (dest / '.t3-plugins').mkdir(exist_ok=True)
        (dest / '.t3-plugins' / 'imps.json').write_text(json.dumps({'schema_version': 1, 'policy': policy}, indent=2) + '\n')
        git(dest, 'add', '-A')
        git(dest, 'commit', '-qm', f'conformance policy: {name}')
    git(dest, 'checkout', '-q', 'main')
    print(json.dumps({'fixture': str(dest), 'branches': [c['branch'] for c in CASES['cases'].values()]}))


def runs_for(worktree: Path, since: str | None):
    root = state_root() / 'runs'
    found = []
    for run_json in sorted(root.glob('*/run.json')):
        state = json.loads(run_json.read_text())
        if Path(state['repo']['worktree']).resolve() != worktree.resolve():
            continue
        if since and state['created_at'] < since:
            continue
        found.append(state)
    return found


def find_run(args):
    states = runs_for(Path(args.worktree), args.since)
    print(json.dumps([{'run_id': s['run_id'], 'phase': s['phase'], 'created_at': s['created_at'],
                       'tasks': [{'id': t['id'], 'status': t['status'],
                                  'host_task_ids': [r.get('task_id') for r in t.get('rounds') or [] if r.get('task_id')]}
                                 for t in s['tasks']]} for s in states]))


def grade(case: str, state: dict, report: dict) -> dict:
    blocker = report.get('blocker') or {}
    reviews = [r for r in report['reviews'] if r['verdict'] != 'unavailable']
    checks = []
    if case == 'bugfix':
        main = [t for t in state['tasks'] if t.get('kind') == 'code']
        checks = [
            ('outcome completed', report['outcome'] == 'completed'),
            ('every requirement passed', all(r['status'] == 'passed' for r in report['requirements'])),
            ('review passed', report['review']['status'] == 'passed'),
            ('implementation result block validated', any((t.get('result') or {}).get('artifact') for t in main)),
        ]
    elif case == 'missing-capability':
        checks = [
            ('not completed', report['outcome'] != 'completed'),
            ('blocked on a missing capability', blocker.get('code') in ('provider_unavailable', 'capability_unavailable')),
            ('capabilities recorded unavailable', (state.get('capabilities') or {}).get('available') is False),
        ]
    elif case == 'adverse-review':
        review_rounds = [r for t in state['tasks'] if t.get('kind') == 'review' for r in t.get('rounds') or [] if r.get('task_id')]
        checks = [
            ('not completed', report['outcome'] != 'completed'),
            ('blocked at the repair limit', blocker.get('code') == 'repair_limit'),
            ('adverse verdict retained', [r['verdict'] for r in reviews] == ['adverse']),
            ('exactly one reviewer dispatched', len(review_rounds) == 1),
        ]
    elif case == 'pending-task':
        survey = next((t for t in state['tasks'] if t['id'] == 'survey'), {})
        rounds = [r for r in survey.get('rounds') or [] if r.get('task_id')]
        # A correction round (malformed first result) is a designed, distinct round; a
        # second *initial* dispatch, or a reused request ID, would be the duplicate.
        checks = [
            ('exactly one initial dispatch', sum(1 for r in rounds if r.get('purpose') == 'initial') == 1),
            ('every round has its own clientRequestId', all(r.get('client_request_id') for r in rounds)
             and len({r.get('client_request_id') for r in rounds}) == len(rounds)),
            ('result accepted after resume', survey.get('status') in ('accepted', 'integrated')),
            ('resume recorded', sum(1 for e in state['events'] if e['kind'] == 'record:capabilities') >= 2),
        ]
    elif case == 'provider-switch':
        survey = next((t for t in state['tasks'] if t['id'] == 'survey'), {})
        checks = [
            ('provider_switch recorded', any(e['kind'] == 'provider_switch' for e in state['events'])),
            ('same parent thread kept', not state['host'].get('previous_parent_thread_ids')),
            ('exactly one initial dispatch', sum(1 for r in survey.get('rounds') or [] if r.get('purpose') == 'initial') == 1),
            ('run completed under the new provider', report['outcome'] == 'completed'),
        ]
    return {'checks': [{'name': name, 'passed': bool(ok)} for name, ok in checks],
            'passed': bool(checks) and all(ok for _, ok in checks)}


def collect(args):
    run_dir = state_root() / 'runs' / args.run_id
    state = json.loads((run_dir / 'run.json').read_text())
    prefix = Path(os.environ.get('T3_PLUGINS_PREFIX', '~/.local/share/t3-plugins')).expanduser()
    cli = prefix / 'imps' / 'current' / 'core' / 'cli.py'
    if not cli.is_file():
        raise SystemExit(f'no installed imps core at {cli}; set T3_PLUGINS_PREFIX to the install prefix')
    out = subprocess.run([sys.executable, str(cli), 'report', '--run-id', args.run_id], capture_output=True, text=True)
    try:
        envelope = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f'report failed ({out.returncode}): {out.stderr.strip() or out.stdout.strip()}') from None
    if out.returncode != 0 or not envelope.get('ok'):
        raise SystemExit(f'report failed ({out.returncode}): {envelope.get("error")}')
    report = envelope['data']['report']
    target = CONFORMANCE / 'results' / args.t3_version / args.provider / args.case / str(args.repeat)
    if target.exists():
        raise SystemExit(f'{target} exists; repeats are never overwritten')
    target.mkdir(parents=True)
    (target / 'report.json').write_text(sanitise(json.dumps(report, indent=2)) + '\n')
    (target / 'report.md').write_text(sanitise((run_dir / 'reports' / 'report.md').read_text()))
    results = sorted((run_dir / 'artifacts' / 'results').glob('*.json')) if (run_dir / 'artifacts' / 'results').is_dir() else []
    combined = {path.name: json.loads(path.read_text()) for path in results}
    (target / 'result.json').write_text(sanitise(json.dumps(combined, indent=2)) + '\n')
    if args.transcript:
        (target / 'transcript.md').write_text(sanitise(Path(args.transcript).read_text()))
    verdict = grade(args.case, state, report)
    usage = {'run_id': args.run_id, 'thread_id': args.thread_id, 'provider': args.provider, 'model': args.model,
             'elapsed_seconds': args.elapsed, 'active_budget_seconds': state['budget']['spent_seconds'],
             'tokens': None, 'cost_usd': None,
             'note': 'T3 does not expose token usage or cost to the parent at the tested version; recorded as null'}
    (target / 'usage.json').write_text(json.dumps(usage, indent=2) + '\n')
    record = {'case': args.case, 'repeat': args.repeat, 'run_id': args.run_id, 'thread_id': args.thread_id,
              'plugin_version': state['plugin']['version'], 'starting_revision': state['repo']['base_sha'],
              'outcome': report['outcome'], 'blocker': (report.get('blocker') or {}).get('code'),
              'grade': verdict, 'interventions': args.interventions, 'elapsed_seconds': args.elapsed,
              'note': args.note, 'artifacts': str(target.relative_to(ROOT))}
    (target / 'grade.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))


def compile_report(args):
    data = json.loads((CONFORMANCE / 'compatibility.json').read_text())
    lines = ['# Provider compatibility', '',
             f'Generated from `compatibility.json`. T3 server `{data["t3_version"]}`; plugin `{data["plugin_version"]}`. '
             'A provider is `verified` only when every critical case passed 3/3 repeats with no intervention and no '
             'false completion; 1-2 of 3 is `partial`.', '',
             '| Provider | Model | Status | Cases (passes/repeats) | Child-write probe | Interventions | Usage/cost |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for row in data['providers']:
        cases = ', '.join(f'{name} {sum(r["passed"] for r in reps)}/{len(reps)}'
                          for name, reps in row.get('cases', {}).items()) or 'none'
        probe = row.get('child_write_probe')
        probe_text = 'not run' if probe is None else ('writes outside parent checkout' if probe.get('sibling_write')
                                                      else 'cannot write outside parent checkout') if 'sibling_write' in probe else probe.get('status', 'n/a')
        lines.append(f'| {row["provider_instance_id"]} | {row.get("model_id") or "n/a"} | `{row["status"]}` | {cases} | '
                     f'{probe_text} | {row.get("interventions", 0)} | {row.get("usage_cost") if row.get("usage_cost") is not None else "null"} |')
    lines += ['']
    for row in data['providers']:
        lines += [f'## {row["provider_instance_id"]}', '', row.get('summary', ''), '']
        for name, reps in row.get('cases', {}).items():
            for rep in reps:
                lines.append(f'- {name} #{rep["repeat"]}: {"pass" if rep["passed"] else "FAIL"}; outcome `{rep.get("outcome")}`'
                             + (f', block `{rep["blocker"]}`' if rep.get('blocker') else '')
                             + f'; elapsed {rep.get("elapsed_seconds")}s; artifacts `{rep.get("artifacts")}`'
                             + (f'. {rep["note"]}' if rep.get('note') else ''))
        lines.append('')
    for section in data.get('notes', []):
        lines += [f'## {section["title"]}', '', section['text'], '']
    (CONFORMANCE / 'compatibility.md').write_text('\n'.join(lines).rstrip() + '\n')
    print(json.dumps({'written': 'conformance/compatibility.md'}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='op', required=True)
    p = sub.add_parser('setup')
    p.add_argument('--dest', required=True)
    p = sub.add_parser('find-run')
    p.add_argument('--worktree', required=True)
    p.add_argument('--since')
    p = sub.add_parser('collect')
    for name in ('run-id', 'provider', 'model', 'case', 't3-version', 'thread-id'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--repeat', type=int, required=True)
    p.add_argument('--transcript')
    p.add_argument('--elapsed', type=float)
    p.add_argument('--interventions', type=int, default=0)
    p.add_argument('--note')
    sub.add_parser('compile')
    args = parser.parse_args(argv)
    {'setup': setup, 'find-run': find_run, 'collect': collect, 'compile': compile_report}[args.op](args)


if __name__ == '__main__':
    main()
