#!/usr/bin/env python3
"""Confinement audit for one benchmark attempt.

Reads the tool calls (never the tool results) in the worker's transcript and its
descendants' transcripts, and classifies every absolute path and network target:

  void    a path outside the workspace, the installed imps package and the harness's
          own per-project directory; or, for Task B, any reference to the upstream
          repository (`seankoji-com/t3-plugins`) or a GitHub tool call aimed at it
  review  something the script cannot decide: a temporary directory, a `..` escape,
          a git call whose target is not in the workspace
  ok      everything else

The script proposes; the operator decides and publishes the decision with the result.
System locations used to run programs (`/usr`, `/bin`, `/opt/homebrew`, ...) are ok.

Usage: python3 bench/tools/audit.py WORKSPACE --package DIR --task {a,b}
         --projects-dir DIR [--codex-dir DIR] [--json]
Exit status: 0 when nothing is void, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tokens  # noqa: E402

SYSTEM = ('/usr/', '/bin/', '/sbin/', '/opt/homebrew/', '/System/', '/Library/Developer/', '/Applications/',
          '/dev/null', '/dev/stdout', '/dev/stderr', '/etc/', '/private/etc/', '/Library/Frameworks/',
          '/Library/Apple/')
TEMP = ('/tmp/', '/private/tmp/', '/var/' + 'folders/', '/private/var/' + 'folders/')  # split: no literal machine paths
ABSOLUTE = re.compile(r'''(?:(?<=^)|(?<=[\s='"`:(,]))(~?/[^\s'"`;|&<>(),]*)''')
UPSTREAM = re.compile(r'seankoji-com/t3-plugins|seankoji-com\.github\.io/t3-plugins|seankoji\.com/t3-plugins', re.I)
PATH_KEYS = ('file_path', 'path', 'notebook_path', 'cwd', 'workdir', 'directory', 'worktreePath', 'workspaceRoot')


def tool_calls(path: Path):
    """(tool name, input) for every tool call in a Claude session or Codex rollout file."""
    for item in tokens._lines(path):
        message = item.get('message') if isinstance(item.get('message'), dict) else {}
        for part in message.get('content') or []:
            if isinstance(part, dict) and part.get('type') == 'tool_use':
                yield part.get('name', ''), part.get('input') or {}
        payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
        if payload.get('type') in ('function_call', 'custom_tool_call', 'local_shell_call'):
            raw = payload.get('arguments') or payload.get('input') or payload.get('action') or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = {'command': raw}
            yield payload.get('name', payload.get('type')), raw if isinstance(raw, dict) else {'value': raw}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def classify(path: str, allowed: list, harness: str, home: str) -> str:
    expanded = home + path[1:] if path.startswith('~') else path
    normal = os.path.normpath(expanded)
    if any(normal == root or normal.startswith(root + '/') for root in allowed):
        return 'ok'
    if normal == harness or normal.startswith(harness + '/'):
        return 'ok'
    if normal in ('/', '/dev') or any((normal + '/').startswith(p) or normal + '/' == p for p in SYSTEM):
        return 'ok'
    if any((normal + '/').startswith(p) for p in TEMP):
        return 'review'
    return 'void'


def audit_file(path: Path, task: str, allowed: list, harness: str, home: str) -> list:
    findings = []
    for name, data in tool_calls(path):
        texts = list(strings(data))
        joined = '\n'.join(texts)
        if task == 'b' and (UPSTREAM.search(joined) or (name.startswith('mcp__github__') and
                                                         str(data.get('owner', '')).lower() == 'seankoji-com')):
            findings.append({'level': 'void', 'tool': name, 'reason': 'upstream repository reference'})
        if task == 'b' and name in ('WebFetch', 'WebSearch') and 't3-plugins' in joined.lower():
            findings.append({'level': 'void', 'tool': name, 'reason': 'web lookup of the upstream project'})
        candidates = [data[k] for k in PATH_KEYS if isinstance(data.get(k), str)]
        for text in texts:
            candidates += ABSOLUTE.findall(text)
        for candidate in candidates:
            if not candidate.startswith(('/', '~/')) or candidate.startswith('//'):
                continue
            level = classify(candidate.rstrip('.:'), allowed, harness, home)
            if level != 'ok':
                findings.append({'level': level, 'tool': name, 'path': candidate})
        command = data.get('command') if isinstance(data.get('command'), str) else ''
        if re.search(r'(^|[\s/])\.\.(/|\s|$)', command):
            findings.append({'level': 'review', 'tool': name, 'reason': 'relative parent path in command'})
    return findings


def audit(workspace: Path, package: Path, task: str, projects_dir: Path, codex_dir: Path | None) -> dict:
    run = tokens.parse_run(workspace, projects_dir, codex_dir)
    home = str(Path.home())
    harness = str(tokens.project_dir(workspace, projects_dir))
    allowed = sorted({str(workspace), os.path.realpath(workspace), str(package), os.path.realpath(package)})
    files = []
    project = tokens.project_dir(workspace, projects_dir)
    if run['project_dir_found']:
        files += sorted(project.glob('*.jsonl')) + sorted(project.glob('*/subagents/*.jsonl'))
    for item in run['descendants']:
        if item.get('kind') == 'codex-rollout':
            files += sorted(codex_dir.rglob(item['file']))
    report = {'transcripts': [], 'void': 0, 'review': 0}
    for path in files:
        findings = audit_file(path, task, allowed, harness, home)
        report['transcripts'].append({'file': path.name, 'findings': findings})
        report['void'] += sum(f['level'] == 'void' for f in findings)
        report['review'] += sum(f['level'] == 'review' for f in findings)
    report['transcripts_found'] = len(files)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--task', choices=('a', 'b'), required=True)
    parser.add_argument('--projects-dir', type=Path, required=True)
    parser.add_argument('--codex-dir', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    report = audit(args.workspace, args.package, args.task, args.projects_dir, args.codex_dir)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['transcripts_found']} transcripts, {report['void']} void, {report['review']} review")
        for item in report['transcripts']:
            for finding in item['findings']:
                print(f"  {finding['level']:6} {item['file']} {finding['tool']} "
                      f"{finding.get('path') or finding.get('reason')}")
    return 1 if report['void'] else 0


if __name__ == '__main__':
    sys.exit(main())
