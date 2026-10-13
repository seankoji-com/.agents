#!/usr/bin/env python3
"""Build and verify the read-only package arms used by the bench-v2 quality starts.

baseline: the packages named in migration/rebuild/baseline.json, installed by that
commit's own scripts/install.py from a private clone checked out at base_commit. Every
plugin's install-manifest and content digests must equal the recorded values.
rebuilt: the current tree's packages and agent bundles, installed by the current
installer. The plugins/, core/, shared/ and scripts/ paths must be clean.

Both arms are built once into OUT, then made read-only. OUT is later mounted into each
start's agent container at the same absolute path, so receipts that record absolute
paths (the rebuilt arm's bundle_dir) stay valid without relocation. The installer runs
with HOME and XDG roots inside OUT; no owner directory is read or written.

  python3 bench/container/packages.py build --arm baseline|rebuilt --out OUT
  python3 bench/container/packages.py verify OUT/package-identity.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'migration' / 'rebuild' / 'baseline.json'
IDENTITY = 'package-identity.json'
CLEAN_PATHS = ('plugins', 'core', 'shared', 'scripts')
# Docker -v splits on ':'; a comma breaks --mount. Neither may appear in a mounted path.
SAFE_MOUNT_PATH = re.compile(r'/[A-Za-z0-9._/@+-]+')


class PackageError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_digest(root: Path) -> str:
    """SHA-256 over every entry below root: relative path, type, mode and content or link target."""
    digest = hashlib.sha256()
    root = Path(root)
    for path in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode) & 0o111  # exec bits only; read-only conversion is not content
        if stat.S_ISLNK(info.st_mode):
            record = f'L\0{rel}\0{os.readlink(path)}'
        elif stat.S_ISDIR(info.st_mode):
            record = f'D\0{rel}'
        elif stat.S_ISREG(info.st_mode):
            record = f'F\0{rel}\0{mode:o}\0{sha256_bytes(path.read_bytes())}'
        else:
            raise PackageError(f'unsupported file type in package tree: {rel}')
        digest.update(record.encode('utf-8') + b'\n')
    return digest.hexdigest()


def make_read_only(root: Path) -> None:
    """Drop every write bit; keep read and traverse for the container's worker UID."""
    root = Path(root)
    for path in sorted(root.rglob('*'), key=lambda item: -len(item.parts)):
        if path.is_symlink():
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_dir():
            path.chmod(0o555)
        else:
            path.chmod(0o555 if mode & 0o111 else 0o444)
    root.chmod(0o555)


def _isolated_env(out: Path) -> dict:
    home = out / 'user-root'
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'LANG', 'LC_ALL', 'TZ', 'SYSTEMROOT'}}
    env.update(HOME=str(home), XDG_STATE_HOME=str(home / '.local' / 'state'),
               XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local' / 'share'),
               XDG_CACHE_HOME=str(home / '.cache'), GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL=os.devnull, PYTHONDONTWRITEBYTECODE='1')
    for key in ('T3_PLUGINS_PREFIX', 'T3_PLUGINS_AGENTS_ROOT'):
        env.pop(key, None)
    return env


def _run(argv, env, cwd=None, run=subprocess.run, timeout=600):
    result = run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        tail = (result.stderr or result.stdout or '').strip().splitlines()[-1:] or ['no output']
        raise PackageError(f'{Path(argv[1]).name if len(argv) > 1 else argv[0]} failed: {tail[0][:300]}')
    return result.stdout


def _install_result(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.startswith('{')]
    if not lines:
        raise PackageError('installer printed no JSON result')
    value = json.loads(lines[-1])
    # The current installer wraps its result as {"ok": true, "data": {...}}.
    if isinstance(value, dict) and 'ok' in value:
        if value.get('ok') is not True or not isinstance(value.get('data'), dict):
            raise PackageError('installer reported failure')
        value = value['data']
    if not isinstance(value, dict) or not value.get('version_dir') or not value.get('entry'):
        raise PackageError('installer result lacks version_dir or entry')
    return value


def _plugin_record(prefix: Path, plugin: str, result: dict) -> dict:
    version_dir = Path(result['version_dir'])
    if not version_dir.resolve().is_relative_to(prefix.resolve()):
        raise PackageError(f'{plugin} installed outside its scratch prefix')
    manifest_path = version_dir / 'install-manifest.json'
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    entry = Path(result['entry'])
    current = version_dir.parent / 'current'
    # Workers receive version directories, never a `current` path.
    relative = entry.relative_to(current) if entry.is_relative_to(current) else entry.relative_to(version_dir)
    version_entry = version_dir / relative
    if not version_entry.is_file():
        raise PackageError(f'{plugin} entry missing from its version directory')
    record = {'version': manifest.get('version'), 'source_commit': manifest.get('source_commit'),
              'files': len(manifest.get('files', [])),
              'version_dir': str(version_dir), 'entry': str(version_entry),
              'install_manifest_sha256': sha256_bytes(raw),
              'package_content_sha256': sha256_bytes(json.dumps(manifest['files'], sort_keys=True).encode())}
    if manifest.get('bundle_digest'):
        record['bundle_digest'] = manifest['bundle_digest']
    return record


def checkout_baseline(root: Path, commit: str, dest: Path, env: dict, run=subprocess.run) -> None:
    """A private clone at the recorded commit; the shared repository's metadata is only read."""
    _run(['git', 'clone', '--quiet', '--no-checkout', '--shared', str(root), str(dest)], env, run=run)
    _run(['git', '-C', str(dest), 'checkout', '--quiet', '--detach', commit], env, run=run)
    head = _run(['git', '-C', str(dest), 'rev-parse', 'HEAD'], env, run=run).strip()
    if head != commit:
        raise PackageError('baseline clone is not at the recorded base commit')


def require_clean(root: Path, env: dict, run=subprocess.run) -> str:
    status = _run(['git', '-C', str(root), 'status', '--porcelain', '--', *CLEAN_PATHS], env, run=run)
    if status.strip():
        raise PackageError('rebuilt source has uncommitted changes under plugins/, core/, shared/ or scripts/')
    return _run(['git', '-C', str(root), 'rev-parse', 'HEAD'], env, run=run).strip()


def build_arm(arm: str, out: Path, *, root: Path = ROOT, baseline_path: Path = BASELINE,
              run=subprocess.run, python: str = sys.executable) -> dict:
    out = Path(out)
    if not out.is_absolute() or not SAFE_MOUNT_PATH.fullmatch(str(out)):
        raise PackageError('package output must be an absolute path without ":" or ","')
    if out.exists():
        raise PackageError('package output already exists; arms are built once and never overwritten')
    if arm not in ('baseline', 'rebuilt'):
        raise PackageError('arm must be baseline or rebuilt')
    baseline = json.loads(Path(baseline_path).read_text(encoding='utf-8'))
    plugins = [row['name'] for row in baseline['plugins']]
    out.mkdir(parents=True, mode=0o755)
    env = _isolated_env(out)
    for key in ('HOME', 'XDG_STATE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    prefix, agents_root = out / 'prefix', out / 'agents'
    if arm == 'baseline':
        source = out / 'source'
        checkout_baseline(Path(root), baseline['base_commit'], source, env, run=run)
        source_commit = baseline['base_commit']
        installer = source / 'scripts' / 'install.py'
        extra = []
    else:
        source = Path(root)
        source_commit = require_clean(source, env, run=run)
        installer = source / 'scripts' / 'install.py'
        extra = ['--agents-root', str(agents_root)]
    records = {}
    for plugin in plugins:
        stdout = _run([python, str(installer), '--plugin', plugin, '--prefix', str(prefix), *extra],
                      env, cwd=str(source), run=run)
        records[plugin] = _plugin_record(prefix, plugin, _install_result(stdout))
    mismatches = []
    if arm == 'baseline':
        expected = {row['name']: row for row in baseline['plugins']}
        for plugin, record in records.items():
            for field in ('installed_version', 'install_manifest_sha256', 'package_content_sha256'):
                want = expected[plugin][field]
                got = record['version'] if field == 'installed_version' else record[field]
                if want != got:
                    mismatches.append(f'{plugin}.{field}')
        if mismatches:
            raise PackageError('baseline build differs from baseline.json: ' + ', '.join(mismatches))
        # baseline.json records that this commit has no managed agent bundles. The schema
        # needs one named digest, so the record names the identity document that says so.
        bundle_digests = {'baseline-identity-no-agent-bundles': sha256_bytes(Path(baseline_path).read_bytes())}
    else:
        bundle_digests = {plugin: record['bundle_digest'] for plugin, record in records.items()
                          if record.get('bundle_digest')}
        if not bundle_digests:
            raise PackageError('rebuilt arm installed no agent bundles')
    identity = {
        'schema_version': 1, 'arm': arm, 'source_commit': source_commit,
        'baseline_identity_sha256': sha256_bytes(Path(baseline_path).read_bytes()),
        'prefix': str(prefix), 'agents_root': str(agents_root) if arm == 'rebuilt' else None,
        'plugins': records,
        'package_digests': {plugin: record['install_manifest_sha256'] for plugin, record in records.items()},
        'package_content_digests': {plugin: record['package_content_sha256'] for plugin, record in records.items()},
        'bundle_digests': bundle_digests,
        'prefix_tree_sha256': tree_digest(prefix),
        'agents_tree_sha256': tree_digest(agents_root) if agents_root.exists() else None,
    }
    make_read_only(prefix)
    if agents_root.exists():
        make_read_only(agents_root)
    path = out / IDENTITY
    path.write_text(json.dumps(identity, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o444)
    out.chmod(0o555)
    return identity


def verify_identity(path: Path) -> dict:
    """Re-hash the read-only arm against its identity; any write, addition or removal fails."""
    path = Path(path)
    identity = json.loads(path.read_text(encoding='utf-8'))
    out = path.parent
    problems = []
    if identity.get('schema_version') != 1 or identity.get('arm') not in ('baseline', 'rebuilt'):
        problems.append('identity schema')
    if Path(identity.get('prefix', '')) != out / 'prefix':
        problems.append('prefix is not inside the identity directory')
    elif tree_digest(out / 'prefix') != identity.get('prefix_tree_sha256'):
        problems.append('prefix tree changed')
    agents = identity.get('agents_root')
    if agents is not None and tree_digest(Path(agents)) != identity.get('agents_tree_sha256'):
        problems.append('agents tree changed')
    writable = [p for p in [out / 'prefix', *(out / 'prefix').rglob('*')]
                if not p.is_symlink() and p.exists() and stat.S_IMODE(p.stat().st_mode) & 0o222]
    if writable:
        problems.append('package tree is writable')
    for plugin, record in identity.get('plugins', {}).items():
        manifest = Path(record.get('version_dir', '')) / 'install-manifest.json'
        if not manifest.is_file() or sha256_bytes(manifest.read_bytes()) != record.get('install_manifest_sha256'):
            problems.append(f'{plugin} install manifest changed')
        if not Path(record.get('entry', '')).is_file():
            problems.append(f'{plugin} entry missing')
    return {'verified': not problems, 'problems': problems, 'arm': identity.get('arm'),
            'identity_sha256': sha256_bytes(path.read_bytes())}


def container_view(identity: dict) -> dict:
    """Mounts and environment that expose an arm at its own absolute paths, read-only."""
    out = str(Path(identity['prefix']).parent)
    env = {'T3_PLUGINS_PREFIX': identity['prefix']}
    if identity.get('agents_root'):
        env['T3_PLUGINS_AGENTS_ROOT'] = identity['agents_root']
    return {'mounts': [(out, out, False)], 'env': env}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build', help='build one arm once into a new read-only directory')
    build.add_argument('--arm', choices=('baseline', 'rebuilt'), required=True)
    build.add_argument('--out', type=Path, required=True)
    check = sub.add_parser('verify', help='re-hash an arm against its package-identity.json')
    check.add_argument('identity', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            identity = build_arm(args.arm, args.out.absolute())
            print(json.dumps({'built': True, 'arm': identity['arm'],
                              'package_digests': identity['package_digests'],
                              'bundle_digests': identity['bundle_digests']}, sort_keys=True))
            return 0
        result = verify_identity(args.identity)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['verified'] else 1
    except (OSError, ValueError, KeyError, PackageError, subprocess.SubprocessError) as exc:
        print(f'packages.py: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
