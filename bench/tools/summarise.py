#!/usr/bin/env python3
"""Record one finished benchmark attempt: sanitised summary and outputs in bench/runs,
raw transcripts in the private directory.

Collects tokens (tokens.py), the audit (audit.py), the delegations the worker made
(`delegate_task` calls in its transcript), and the task's result (task_a.py or
grade_task_b.py). Copies the raw transcripts to PRIVATE/runs/<version>/<slot>/ and
records their sha256. Absolute paths in every committed file (summary, report, copied output, patches)
are replaced with `<workspace>`, `<package>` and `<home>`.

Usage: python3 bench/tools/summarise.py --version old --slot a1 --attempt 1
         --workspace WS --package VERSION_DIR --thread-id ID --thread-json FILE
         --private DIR [--bundle FILE] [--audit-decision TEXT] [--retry-reason TEXT]
--thread-json is a JSON object the executor writes from t3_thread_read and
t3_thread_configuration: `outcome`, `started_at`, `ended_at`, `modelSelection`,
`runtimeMode` and `final_message`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH / 'checks'))
import audit  # noqa: E402
import verify_package  # noqa: E402
import task_a  # noqa: E402
import tokens  # noqa: E402

PROJECTS = Path.home() / '.claude' / 'projects'
CODEX = Path.home() / '.codex' / 'sessions'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sanitise(text: str, workspace: Path, package: Path) -> str:
    for path, label in ((workspace, '<workspace>'), (package, '<package>'), (Path.home(), '<home>')):
        # Longest form first: the resolved path, then the path as given (/private/var vs /var).
        for form in sorted({str(path), str(Path(path).resolve()), str(path).replace('/private/', '/', 1)},
                           key=len, reverse=True):
            text = text.replace(form, label)
    return text


def sanitise_tree(root: Path, workspace: Path, package: Path) -> None:
    """Replace machine paths in committed copies of worker output (text files only)."""
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        clean = sanitise(text, workspace, package)
        if clean != text:
            path.write_text(clean)


def delegations(parent_file: Path) -> list:
    found = []
    for name, data in audit.tool_calls(parent_file):
        if name.split('__')[-1] != 'delegate_task':
            continue
        target = data.get('target') or {}
        task = str(data.get('task', ''))
        found.append({'provider': target.get('providerInstanceId') or 'inherit', 'model': target.get('model') or 'inherit',
                      'options': target.get('options'), 'runtime_mode': data.get('runtimeMode') or 'inherit',
                      'role': data.get('role'), 'title': data.get('title'),
                      'reason': next((line.strip() for line in task.splitlines() if line.strip()), '')[:300]})
    return found


def git(workspace: Path, *args) -> str:
    return subprocess.run(['git', *args], cwd=workspace, capture_output=True, text=True, check=True).stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for flag in ('--version', '--slot', '--thread-id'):
        parser.add_argument(flag, required=True)
    parser.add_argument('--attempt', type=int, required=True)
    for flag in ('--workspace', '--package', '--thread-json', '--private'):
        parser.add_argument(flag, type=Path, required=True)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--audit-decision', default='pending')
    parser.add_argument('--retry-reason')
    parser.add_argument('--runs-dir', type=Path, default=BENCH / 'runs')
    parser.add_argument('--projects-dir', type=Path, default=PROJECTS)
    parser.add_argument('--codex-dir', type=Path, default=CODEX)
    args = parser.parse_args(argv)
    task = args.slot[0]
    workspace, package = args.workspace.resolve(), args.package.resolve()
    dest = args.runs_dir / args.version / args.slot
    if args.attempt > 1:
        dest = dest / f'attempt-{args.attempt}'
    private = args.private / 'runs' / args.version / args.slot / f'attempt-{args.attempt}'
    if dest.exists() or private.exists():
        sys.exit(f'{dest} or {private} already exists')
    thread = json.loads(args.thread_json.read_text())

    run = tokens.parse_run(args.workspace, args.projects_dir, args.codex_dir)
    audited = audit.audit(workspace, package, task, args.projects_dir, args.codex_dir)
    project = tokens.project_dir(args.workspace, args.projects_dir)
    raw = sorted(project.glob('*.jsonl')) + sorted(project.glob('*/subagents/*.jsonl'))
    raw += [p for d in run['descendants'] if d.get('kind') == 'codex-rollout' for p in args.codex_dir.rglob(d['file'])]
    (private / 'transcripts').mkdir(parents=True)
    hashes = {}
    for path in raw:
        copy = private / 'transcripts' / path.name
        shutil.copy2(path, copy)
        hashes[path.name] = sha256(copy)
    (private / 'audit.json').write_text(json.dumps(audited, indent=2))
    hashes['audit.json'] = sha256(private / 'audit.json')
    state = workspace / '.bench-state'
    if state.is_dir():
        shutil.copytree(state, private / 'bench-state')

    dest.mkdir(parents=True)
    fixture_head = git(workspace, 'rev-list', '--max-parents=0', 'HEAD').strip()
    if task == 'a':
        out = workspace / 'out'
        result = {'task_a_checks': task_a.check(out, BENCH / 'fixtures/task_a/workspace/data') if out.is_dir() else None}
        changed = [p for p in git(workspace, 'diff', '--name-only', fixture_head, 'HEAD').splitlines() if p]
        for rel in changed:
            src = workspace / rel
            if src.is_file() and not rel.startswith('vendor/'):
                target = dest / 'output' / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
        sanitise_tree(dest / 'output', workspace, package)
    else:
        result = {'hidden_tests': None}
        if args.bundle:
            graded = subprocess.run([sys.executable, str(HERE / 'grade_task_b.py'), str(workspace), str(args.bundle),
                                     '--full', '--json'], capture_output=True, text=True)
            result['hidden_tests'] = json.loads(graded.stdout) if graded.stdout.strip() else {'error': graded.stderr}
        patches = dest / 'output'
        patches.mkdir()
        git(workspace, 'format-patch', '--quiet', '-o', str(patches), f'{fixture_head}..HEAD')
        sanitise_tree(patches, workspace, package)
    final = thread.get('final_message') or ''
    (dest / 'report.md').write_text(sanitise(final, workspace, package) + '\n')
    parent = run.get('parent') or {}
    summary = {
        'version': args.version, 'slot': args.slot, 'attempt': args.attempt, 'retry_reason': args.retry_reason,
        'workspace_id': workspace.name, 'thread_id': args.thread_id,
        'outcome': thread.get('outcome'), 'model_selection': thread.get('modelSelection'),
        'runtime_mode': thread.get('runtimeMode'),
        'wallclock_seconds': {
            'thread': tokens.wallclock_seconds(thread.get('started_at'), thread.get('ended_at')),
            'transcript': tokens.wallclock_seconds(parent.get('started_at'), parent.get('ended_at'))},
        'parent_opus_tokens': run.get('parent_opus'),
        'parent_by_model': parent.get('by_model'),
        'descendants': [{'kind': d['kind'], 'file_sha256': hashes.get(d['file']),
                         'by_model': d.get('by_model'), 'model': d.get('model'), 'usage': d.get('usage')}
                        for d in run['descendants']],
        'delegations': delegations(project / parent['file']) if parent else [],
        # The protocol re-verifies the package around the runs; each record keeps its own check too.
        'package_verification': verify_package.verify(package),
        'audit': {'void': audited['void'], 'review': audited['review'], 'decision': args.audit_decision},
        'result': json.loads(sanitise(json.dumps(result), workspace, package)),
        'raw_sha256': hashes,
    }
    summary['delegation_count'] = len(summary['delegations'])
    text = sanitise(json.dumps(summary, indent=2), workspace, package)
    (dest / 'summary.json').write_text(text + '\n')
    print(json.dumps({'summary': str(dest / 'summary.json'), 'private': str(private)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
