#!/usr/bin/env python3
"""Exec a T3-selected native CLI as the isolated worker UID.

This changes Linux process credentials only. T3 supplies all arguments, owns
all launches and schedules all children. There is no task/model/agent broker.
"""
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

WORKER_UID = 1001
DROP = ('/usr/bin/setpriv', '--reuid=1001', '--regid=1001', '--clear-groups',
        '--no-new-privs', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all')
SHIM = '/opt/bench/native_exec.py'
T3_SETTINGS = '/bench/t3/userdata/settings.json'
PROGRAMS = ('claude', 'codex')


def _binary_paths(value, where='settings'):
    """Yield every configured binaryPath in T3 settings, whatever its nesting."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'binaryPath':
                yield where + '.' + key, item
            else:
                yield from _binary_paths(item, where + '.' + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _binary_paths(item, f'{where}[{index}]')


def binary_resolution_report(settings_text, search_path, home):
    """Check that T3's default and configured provider commands resolve to this shim.

    T3 spawns the command named by each provider's binaryPath (default `claude`
    or `codex`) from its own PATH. Any command that resolves elsewhere would run
    the native CLI with coordinator credentials, so the report fails closed.
    """
    import shutil
    rows = []

    def resolve(where, command, expected=None):
        if not isinstance(command, str):
            rows.append({'where': where, 'resolves_to_shim': False, 'reason': 'non-string binaryPath'})
            return
        command = command or expected or ''
        if command.startswith('~/'):
            command = home.rstrip('/') + command[1:]
        found = command if '/' in command else shutil.which(command, path=search_path)
        name = os.path.basename(command)
        ok = (bool(found) and os.path.realpath(found) == SHIM and name in PROGRAMS
              and (expected is None or name == expected))
        rows.append({'where': where, 'command_name': name if name in PROGRAMS else 'other',
                     'resolves_to_shim': ok})

    for program in PROGRAMS:
        resolve('default.' + program, program, program)
    try:
        settings = json.loads(settings_text) if settings_text is not None else {}
    except ValueError:
        return {'verified': False, 'rows': rows, 'reason': 'T3 settings are not valid JSON'}
    for where, command in _binary_paths(settings):
        resolve(where, command)
    return {'verified': all(row['resolves_to_shim'] for row in rows), 'rows': rows}


def t3_binary_resolution(settings_path=T3_SETTINGS, proc=Path('/proc')):
    """Coordinator-side probe: read the running `t3 serve` PATH and its settings."""
    paths = set()
    home = '/opt/bench-home'
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / 'cmdline').read_bytes().split(b'\0')
            if b'serve' not in argv or b'/bench/t3' not in argv:
                continue
            environ = dict(item.split(b'=', 1) for item in (entry / 'environ').read_bytes().split(b'\0')
                           if b'=' in item)
        except OSError:
            continue
        paths.add(environ.get(b'PATH', b'').decode('utf-8', 'replace'))
        home = environ.get(b'HOME', home.encode()).decode('utf-8', 'replace')
    if len(paths) != 1:
        return {'verified': False, 'rows': [], 'reason': 'one running T3 server PATH is required'}
    settings = Path(settings_path)
    if settings.is_symlink():
        return {'verified': False, 'rows': [], 'reason': 'T3 settings path is a symlink'}
    text = settings.read_text(encoding='utf-8') if settings.is_file() else None
    return binary_resolution_report(text, paths.pop(), home)


def main():
    program = Path(sys.argv[0]).name
    if program not in ('claude', 'codex') or sys.platform != 'linux':
        raise SystemExit('isolated native launcher is Linux-only and supports the pinned CLIs')
    real = '/usr/local/bin/' + program + '-native'
    if os.geteuid() == 0:
        row = {'program': program, 'pid': os.getpid(), 'parent_uid': 0,
               'worker_uid': WORKER_UID, 'nonce': secrets.token_hex(16),
               'argv_sha256': hashlib.sha256(json.dumps(sys.argv[1:]).encode()).hexdigest()}
        fd = os.open('/bench/t3/native-launches.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
        os.execv(DROP[0], [*DROP, real, *sys.argv[1:]])
    if os.geteuid() != WORKER_UID:
        raise SystemExit('native launcher has an unexpected UID')
    # Native descendants inherit the same non-privileged UID. They cannot use
    # this root-owned executable to regain coordinator credentials.
    os.execv(real, [real, *sys.argv[1:]])


if __name__ == '__main__':
    main()
