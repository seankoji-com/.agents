#!/usr/bin/env python3
"""Record real terminal sessions of the catalog CLI in a throwaway home directory.

Each session runs its commands through ``/bin/sh`` with ``HOME`` pointing at a fresh
temporary directory and a ``t3-plugins`` launcher for this checkout first on ``PATH``,
so the commands shown are exactly the commands that ran. Output lines are timestamped
as they arrive. Before anything is written, machine-specific strings (the temporary
home, this checkout, the real home, user and host names) are replaced with neutral
placeholders (``~``, ``<checkout>``, ``<home>``), and the result is scanned for anything that still looks private. A
leak fails the run and writes nothing.

    python3 scripts/capture_terminal.py            # writes docs/assets/recordings/*.json, *.txt
    python3 scripts/capture_terminal.py --out DIR  # somewhere else

Then ``python3 scripts/render_demo.py`` turns the quickstart transcript into the
homepage recording, and ``--video`` renders the MP4/WebM. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'docs' / 'assets' / 'recordings'
FORMAT = 1

# name -> (summary, commands). Commands run in order in one home directory, from ~/project.
# A command is a string (expected exit 0) or (command, expected exit).
SESSIONS = {
    'quickstart': ('Install the catalog, check it, and print the first prompt for T3.', [
        't3-plugins list',
        't3-plugins setup',
        't3-plugins doctor',
        'ls ~/.claude/skills',
        't3-plugins prompt imps doctor',
    ]),
    'tuneup-audit': ('Audit a synthetic Claude settings file with the installed helper; no model call.', [
        "printf '%s\\n' '{\"permissions\":{\"allow\":[\"Bash(*)\"]}}' > example-settings.json",
        ('python3 "$(dirname "$(t3-plugins path agent-tuneup)")/scripts/audit.py" '
         '--provider claude --settings example-settings.json', 1),  # 1: findings reported
    ]),
}

RUNTIME_PATHS = ('bin', 'core', 'plugins', 'shared', 'scripts/catalog.py', 'scripts/install.py',
                 'scripts/skills.py', 'scripts/registry.py', 'scripts/routing.py')
PLACEHOLDER_HOME = '~'
PLACEHOLDER_CHECKOUT = '<checkout>'
PLACEHOLDER_REAL_HOME = '<home>'  # the operator's own home; it should never appear
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
TOKEN = re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9-]{20,}'
                   r'|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b')
HOME_DIR = re.compile(r'/(?:home|Users)/[^/\s"\']+')
TEMP_DIR = re.compile(r'(?:/private)?/(?:tmp|var/folders)/[^\s"\']+')


class LeakError(RuntimeError):
    """Redacted output still contains something machine-specific."""


def machine_strings(tmp_home: str | None = None) -> list[tuple[str, str]]:
    """(real, placeholder) pairs, longest first so nested paths are replaced whole."""
    pairs = []
    if tmp_home:
        pairs.append((tmp_home, PLACEHOLDER_HOME))
        real_tmp = os.path.realpath(tmp_home)
        if real_tmp != tmp_home:
            pairs.append((real_tmp, PLACEHOLDER_HOME))
    pairs.append((str(ROOT), PLACEHOLDER_CHECKOUT))
    home = os.path.expanduser('~')
    if home not in ('/', '~'):
        pairs.append((home, PLACEHOLDER_REAL_HOME))
    return sorted(set(pairs), key=lambda p: -len(p[0]))


def redact(text: str, pairs: list[tuple[str, str]]) -> str:
    for real, placeholder in pairs:
        text = text.replace(real, placeholder)
    return text


def leaks(text: str, user: str | None = None, host: str | None = None) -> list[str]:
    """Anything private that survived redaction. An empty list means the text is safe."""
    found = []
    for pattern, label in ((EMAIL, 'email'), (TOKEN, 'token'), (HOME_DIR, 'home directory'),
                           (TEMP_DIR, 'temporary path')):
        found += [f'{label}: {m.group(0)}' for m in pattern.finditer(text)]
    user = getpass.getuser() if user is None else user
    host = socket.gethostname() if host is None else host
    # A user name counts when it appears as a path component or an address part; an
    # organisation slug that merely starts with the same letters does not.
    if user and re.search(rf'(?:^|[/\\@\s"]){re.escape(user)}(?:$|[/\\@\s"])', text):
        found.append(f'user name: {user}')
    if host and host not in ('localhost',) and len(host) > 2 and re.search(rf'\b{re.escape(host)}\b', text):
        found.append(f'host name: {host}')
    return found


def launcher(bin_dir: Path) -> None:
    """A ``t3-plugins`` on PATH that runs this checkout, like the Homebrew wrapper does."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / 't3-plugins'
    script.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} '
                      f'{shlex.quote(str(ROOT / "bin" / "t3-plugins"))} "$@"\n')
    script.chmod(0o755)


def run_step(command, cwd: Path, env: dict) -> dict:
    command, expect = (command, 0) if isinstance(command, str) else command
    start = time.monotonic()
    lines = []
    with subprocess.Popen(['/bin/sh', '-c', command], cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1) as proc:
        for line in proc.stdout:
            lines.append([round(time.monotonic() - start, 3), line.rstrip('\n')])
        code = proc.wait()
    return {'command': command, 'exit': code, 'expected_exit': expect, 'seconds': round(time.monotonic() - start, 3), 'lines': lines}


def record(sessions=SESSIONS) -> dict:
    """Run every session in one fresh home and return redacted transcripts by name."""
    out = {}
    with tempfile.TemporaryDirectory(prefix='t3-capture-') as tmp:
        home = Path(tmp) / 'home'
        project = home / 'project'
        project.mkdir(parents=True)
        bin_dir = Path(tmp) / 'bin'
        launcher(bin_dir)
        env = {'HOME': str(home), 'PATH': f'{bin_dir}:/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'LC_ALL': 'C.UTF-8', 'PYTHONUNBUFFERED': '1', 'TERM': 'dumb', 'COLUMNS': '80',
               'TMPDIR': str(Path(tmp) / 'scratch')}
        Path(env['TMPDIR']).mkdir()
        pairs = machine_strings(str(home)) + [(str(Path(tmp)), '<scratch>')]
        pairs = sorted(set(pairs), key=lambda p: -len(p[0]))
        # The commit that last changed the code these commands run, so a docs-only
        # commit does not make the recording look out of date.
        commit = subprocess.run(['git', '-C', str(ROOT), 'log', '-1', '--format=%h', '--abbrev=7', '--',
                                 *RUNTIME_PATHS], capture_output=True, text=True).stdout.strip() or None
        for name, (summary, commands) in sessions.items():
            steps = [run_step(command, project, env) for command in commands]
            for step in steps:
                step['lines'] = [[t, redact(text, pairs)] for t, text in step['lines']]
            out[name] = {
                'format': FORMAT,
                'name': name,
                'summary': summary,
                'recorded': dt.date.today().isoformat(),
                'commit': commit,
                'environment': {'os': f'{platform.system()} {platform.machine()}',
                                'python': platform.python_version(),
                                'home': 'empty temporary home directory, shown as ~'},
                'note': ('Real output at recorded times. Commands run through /bin/sh from ~/project; '
                         't3-plugins runs this checkout. Machine paths are replaced with ~ and <checkout>.'),
                'steps': steps,
            }
    return out


def transcript_text(session: dict) -> str:
    env = session['environment']
    head = [f"# {session['name']}: {session['summary']}",
            f"# recorded {session['recorded']} at commit {session['commit']} on {env['os']}, "
            f"Python {env['python']}, {env['home']}"]
    body = []
    for step in session['steps']:
        body.append(f"$ {step['command']}")
        body += [text for _, text in step['lines']]
        body.append(f"# exit {step['exit']} after {step['seconds']:.2f}s")
    return '\n'.join(head + body) + '\n'


def write(sessions: dict, out: Path) -> list[Path]:
    """Check every transcript for leaks, then write all of them, or nothing."""
    rendered = {}
    for name, session in sessions.items():
        data = json.dumps(session, indent=1, ensure_ascii=False) + '\n'
        text = transcript_text(session)
        problems = leaks(data) + leaks(text)
        if problems:
            raise LeakError(f'{name}: ' + '; '.join(sorted(set(problems))))
        rendered[out / f'{name}.json'] = data
        rendered[out / f'{name}.txt'] = text
    out.mkdir(parents=True, exist_ok=True)
    for path, content in rendered.items():
        path.write_text(content)
    return list(rendered)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    sessions = record()
    failed = [f"{name}: `{s['command']}` exited {s['exit']}" for name, sess in sessions.items()
              for s in sess['steps'] if s['exit'] != s['expected_exit']]
    if failed:
        print('capture_terminal: unexpected exit status\n  ' + '\n  '.join(failed), file=sys.stderr)
        return 1
    try:
        paths = write(sessions, args.out)
    except LeakError as exc:
        print(f'capture_terminal: refusing to write, private data survived redaction: {exc}', file=sys.stderr)
        return 1
    for path in paths:
        try:
            shown = path.relative_to(ROOT)
        except ValueError:
            shown = path
        print(f'wrote {shown}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
