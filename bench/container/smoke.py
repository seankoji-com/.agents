#!/usr/bin/env python3
"""No-model network, mount and helper smoke check for one fresh container."""
import hashlib
import ipaddress
import json
import os
import socket
import ssl
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

INPUT = Path('/bench/input/brief.txt')
EXPECTED_HOME = {'.agents', '.claude', '.codex', '.config', '.local'}


def isolated_home_entries_valid(entries):
    actual = set(entries)
    # Claude Code creates this isolated runtime metadata file on first boot.
    # It is generated inside the disposable image home, never mounted from host.
    return EXPECTED_HOME <= actual and actual - EXPECTED_HOME <= {'.npm', '.claude.json'}


def check(name, ok, detail=''):
    print(json.dumps({'probe': name, 'passed': bool(ok), 'detail': detail}, sort_keys=True))
    if not ok:
        raise RuntimeError(name + ' failed')


def tcp_reaches(host, port, timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def host_gateway_address(resolve=socket.gethostbyname, name='host.docker.internal'):
    """The host-gateway address, or None when it is unresolved or names this container."""
    try:
        address = resolve(name)
        parsed = ipaddress.ip_address(address)
    except (OSError, ValueError):
        return None
    return None if parsed.is_loopback or parsed.is_unspecified else address


def network_controls(port, reaches=tcp_reaches, resolve=socket.gethostbyname):
    """Pair each container-side negative with a positive control from the same run.

    A probe that cannot reach anything, or a host name that does not resolve,
    would make the negatives pass vacuously. The gateway connect proves the
    probe can succeed; the resolved host-gateway address names the target
    the loopback negative actually tried.
    """
    rows = [('gateway-reachable-positive-control', reaches('gateway.bench.test', 8443),
             'the same TCP probe reaches the model gateway')]
    direct = {host: reaches(host, 443) for host in ('api.anthropic.com', 'api.openai.com')}
    rows.append(('no-direct-provider-egress', not any(direct.values()),
                 'provider hosts reachable only through gateway'))
    host = host_gateway_address(resolve)
    rows.append(('host-gateway-resolves-positive-control', host is not None,
                 'host.docker.internal resolves to a non-loopback address'))
    rows.append(('host-loopback-excluded', host is not None and port > 0 and not reaches(host, port),
                 'task-owned host loopback fixture is unreachable from the internal agent network'))
    return rows


def workspace_entry(path):
    """Describe one entry by type, mode and owner without following links or opening special files.

    The value is '<kind> mode=<octal> uid=<n> gid=<n>', plus links=<n> for files,
    where kind is 'directory', 'symlink:<target>', 'special:<letter>',
    'unreadable' or the file's SHA-256.
    """
    info = os.lstat(path)
    metadata = f' mode={stat.S_IMODE(info.st_mode):04o} uid={info.st_uid} gid={info.st_gid}'
    if stat.S_ISDIR(info.st_mode):
        return 'directory' + metadata
    if stat.S_ISLNK(info.st_mode):
        return 'symlink:' + os.readlink(path) + metadata
    if not stat.S_ISREG(info.st_mode):
        return 'special:' + stat.filemode(info.st_mode)[0] + metadata
    metadata += f' links={info.st_nlink}'
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return 'unreadable' + metadata
    with os.fdopen(descriptor, 'rb') as stream:
        return hashlib.sha256(stream.read()).hexdigest() + metadata


def workspace_snapshot(root):
    """Record every workspace entry by type and metadata so pre-seeded Git metadata is baseline.

    Directories, links and special files are recorded as well as file hashes,
    each with its mode bits and owner, so an empty directory created or a mode
    or owner changed outside the assigned path is a change. The root itself is
    recorded under '.'.
    """
    snapshot = {Path('.'): workspace_entry(root)}

    def unlisted(error):
        raise error  # An unreadable directory fails the smoke closed.
    for folder, directories, files in os.walk(root, onerror=unlisted):
        for name in directories + files:
            path = Path(folder) / name
            snapshot[path.relative_to(root)] = workspace_entry(path)
    return snapshot


NOT_WRITABLE = ('symlink:', 'special:', 'unreadable')


def entry_kind(value):
    return str(value).split(' ', 1)[0]


def assigned_workspace_changes_confined(before, after, assigned_root, output=None):
    """Changes stay below assigned_root, except creating its ancestors as directories.

    Below assigned_root entries may be added or removed; of the entries that
    already existed only `output` may change, and only as a regular file. Any
    unreadable entry outside assigned_root fails, since its change is invisible.
    """
    changed = {path for path in before.keys() | after.keys()
               if before.get(path) != after.get(path)}
    ancestors = set(assigned_root.parents) - {Path('.')}

    def regular(value):
        return value is not None and not str(value).startswith(('directory ', *NOT_WRITABLE))

    def permitted(path):
        if path.is_relative_to(assigned_root):
            value = after.get(path)
            if path not in before or value is None:
                return value is None or not str(value).startswith(NOT_WRITABLE)
            return path == output and regular(before[path]) and regular(value)
        return (path in ancestors and path not in before
                and entry_kind(after.get(path)) == 'directory')
    unreadable_outside = any(entry_kind(value) == 'unreadable' and not path.is_relative_to(assigned_root)
                             for path, value in after.items())
    return bool(changed) and not unreadable_outside and all(permitted(path) for path in changed)


def main():
    home = Path(os.environ['HOME'])
    home_entries = sorted(path.name for path in home.iterdir())
    check('home-confinement', home == Path('/opt/bench-home')
          and isolated_home_entries_valid(home_entries),
          'fresh provider homes and only the task-local npm cache are present')
    digest = hashlib.sha256(INPUT.read_bytes()).hexdigest()
    expected = Path('/bench/input/brief.sha256').read_text(encoding='ascii').strip()
    check('pinned-input-read-hash', digest == expected, digest)

    output = Path('/bench/ws/smoke/task-1/result.json')
    workspace = Path('/bench/ws')
    before = workspace_snapshot(workspace)
    helper = __import__('subprocess').run(
        [sys.executable, '/opt/bench/smoke_helper.py', str(INPUT), str(output)],
        check=True, capture_output=True, text=True, timeout=10)
    result = json.loads(output.read_text(encoding='utf-8'))
    allowed = Path('/bench/ws/smoke/task-1')
    after = workspace_snapshot(workspace)
    confined = assigned_workspace_changes_confined(
        before, after, allowed.relative_to(workspace), output.relative_to(workspace))
    check('assigned-write-helper', result.get('input_sha256') == digest and helper.returncode == 0 and confined,
          'helper wrote only under its assigned workspace')

    request = urllib.request.Request('http://github.bench.test:8080/api/v3/user')
    with urllib.request.urlopen(request, timeout=5) as response:
        gh = json.loads(response.read())
    check('synthetic-github', response.status == 200 and gh.get('login') == 'bench-user', 'fixture route reached')

    ca = ssl.create_default_context(cafile='/run/secrets/bench-gateway-ca.pem')
    req = urllib.request.Request('https://gateway.bench.test:8443/healthz')
    with urllib.request.urlopen(req, context=ca, timeout=5) as response:
        gateway_status = response.status
    check('gateway-tls', gateway_status == 200, 'trusted gateway certificate; TLS verification enabled')

    port = int(os.environ.get('BENCH_HOST_LOOPBACK_PORT', '0'))
    for name, ok, detail in network_controls(port):
        check(name, ok, detail)

    t3 = urllib.request.urlopen('http://127.0.0.1:3773/', timeout=5)
    check('headless-t3-server', t3.status in range(200, 400), 'local server responds')
    print(json.dumps({'smoke': 'passed', 'model_requests': 0}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'smoke': 'failed', 'error': type(exc).__name__}, sort_keys=True), file=sys.stderr)
        sys.exit(1)
