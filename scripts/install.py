#!/usr/bin/env python3
"""Install, activate or uninstall a t3-plugins plugin.

  python3 scripts/install.py [--plugin imps] [--dry-run] [--force]
  python3 scripts/install.py --activate VERSION      # roll back or forward
  python3 scripts/install.py --uninstall [--version VERSION]

Copies plugins/<plugin>/ plus its own copy of core/ to
<prefix>/<plugin>/<version>/, writes an ownership manifest there and atomically
repoints <prefix>/<plugin>/current. The prefix defaults to
~/.local/share/t3-plugins. Run state (~/.local/state/t3-plugins) is never touched.
Prints one JSON object on stdout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
MANIFEST = 'install-manifest.json'
SKIP_DIRS = {'__pycache__', '.pytest_cache'}
SKIP_SUFFIXES = ('.pyc', '.pyo')
SKIP_FILES = {'.DS_Store', 'Thumbs.db'}


class InstallError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_under(root: Path):
    for path in sorted(root.rglob('*')):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and path.name not in SKIP_FILES and not path.name.endswith(SKIP_SUFFIXES):
            yield path


def source_files(source: Path, plugin: str) -> dict:
    """Installed relative path -> source file."""
    validate_name(plugin)
    plugin_dir = source / 'plugins' / plugin
    if not (plugin_dir / 'plugin.json').is_file():
        raise InstallError('unknown_plugin', f'no plugin named {plugin} under {source / "plugins"}')
    mapping = {path.relative_to(plugin_dir).as_posix(): path for path in files_under(plugin_dir)}
    for path in files_under(source / 'core'):
        mapping['core/' + path.relative_to(source / 'core').as_posix()] = path
    for path in files_under(source / 'shared'):
        mapping['shared/' + path.relative_to(source / 'shared').as_posix()] = path
    for path in mapping.values():
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise InstallError('source_path_escape', 'source file escapes its package')
    if MANIFEST in mapping:
        raise InstallError('reserved_name', f'{MANIFEST} is reserved for the installer')
    return mapping


def validate_name(plugin: str) -> None:
    if not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', plugin):
        raise InstallError('invalid_plugin', 'plugin must be a kebab-case name')


def git_commit(source: Path, paths) -> tuple[str | None, bool]:
    """The last commit that touched the installed paths, and whether they are dirty.
    Commits elsewhere in the repository (docs, conformance results) leave it unchanged."""
    try:
        head = subprocess.run(['git', '-C', str(source), 'log', '-1', '--format=%H', '--', *paths], capture_output=True, text=True)
    except FileNotFoundError:
        return None, True  # no git binary: fall back to the content-hash version, as for a non-git source
    if head.returncode != 0 or not head.stdout.strip():
        return None, True
    dirty = subprocess.run(['git', '-C', str(source), 'status', '--porcelain', '--', *paths], capture_output=True, text=True)
    return head.stdout.strip(), bool(dirty.stdout.strip())


def plan_install(source: Path, plugin: str) -> dict:
    mapping = source_files(source, plugin)
    meta = json.loads((source / 'plugins' / plugin / 'plugin.json').read_text())
    if not re.fullmatch(r'\d+\.\d+\.\d+', meta.get('version', '')):
        raise InstallError('invalid_version', 'plugin version must be major.minor.patch')
    entry = meta.get('entry', 'entry.md')
    if entry not in mapping or Path(entry).is_absolute() or '..' in Path(entry).parts:
        raise InstallError('invalid_entry', 'entry must name a bundled file')
    entries = [{'path': rel, 'sha256': sha256(path), 'mode': 0o755 if os.access(path, os.X_OK) else 0o644}
               for rel, path in sorted(mapping.items())]
    content = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    commit, dirty = git_commit(source, ['plugins/' + plugin, 'core', 'shared'])
    if commit and not dirty:
        version = f'{meta["version"]}+g{commit[:12]}'
    else:
        version = f'{meta["version"]}+content.{content[:12]}'
    manifest = {'schema_version': 1, 'plugin': plugin, 'version': version,
                'source_commit': commit if commit and not dirty else None, 'files': entries}
    return {'manifest': manifest, 'mapping': mapping, 'entry': meta.get('entry', 'entry.md')}


def owned_path(version_dir: Path, rel: str) -> Path:
    """Resolve a manifest path inside its version directory, refusing absolute
    paths, `..`, and symlinked components that would lead elsewhere."""
    candidate = Path(rel)
    if candidate.is_absolute() or not rel or any(part in ('..', '') for part in candidate.parts):
        raise InstallError('manifest_path_escape', 'manifest path must be relative and inside the version directory',
                           {'path': rel})
    current = version_dir
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise InstallError('manifest_path_escape', 'manifest path crosses a symlink', {'path': rel})
    if version_dir.exists() and not current.resolve().is_relative_to(version_dir.resolve()):
        raise InstallError('manifest_path_escape', 'manifest path resolves outside the version directory', {'path': rel})
    return current


def write_atomic(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def repoint(plugin_root: Path, version: str) -> None:
    link = plugin_root / 'current'
    if link.exists() and not link.is_symlink():
        raise InstallError('current_not_symlink', f'{link} exists and is not a symlink; refusing to replace it')
    tmp = plugin_root / f'.current.{os.getpid()}'
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(version, tmp)
    os.replace(tmp, link)


def local_modifications(version_dir: Path, manifest: dict) -> list:
    changed = []
    for entry in manifest['files']:
        path = owned_path(version_dir, entry['path'])
        if path.is_file() and sha256(path) != entry['sha256']:
            changed.append(entry['path'])
    return changed


def prefix_path(args) -> Path:
    return Path(args.prefix).expanduser().absolute()


def active_version(plugin_root: Path) -> str | None:
    link = plugin_root / 'current'
    return os.readlink(link) if link.is_symlink() else None


def install(args) -> dict:
    prefix = prefix_path(args)
    planned = plan_install(SOURCE if not args.source else Path(args.source), args.plugin)
    manifest = planned['manifest']
    plugin_root = prefix / args.plugin
    version_dir = plugin_root / manifest['version']
    entry = plugin_root / 'current' / planned['entry']
    existing = version_dir / MANIFEST
    action = 'install'
    if existing.is_file() and not (args.force and load_manifest(existing, strict=False) is None):
        old = load_manifest(existing)
        modified = local_modifications(version_dir, old)
        if modified and not args.force:
            raise InstallError('locally_modified', 'installed files were modified locally; rerun with --force to overwrite',
                               {'files': modified, 'version_dir': str(version_dir)})
        if old == manifest and not modified:
            # Identical snapshot already on disk; only `current` may still need repointing.
            action = 'already_installed' if active_version(plugin_root) == manifest['version'] else 'reactivated'
    result = {'action': action, 'plugin': args.plugin, 'version': manifest['version'],
              'source_commit': manifest['source_commit'], 'version_dir': str(version_dir), 'entry': str(entry),
              'paste': f'Read {entry} and run: doctor', 'dry_run': bool(args.dry_run),
              'files': len(manifest['files'])}
    if args.dry_run:
        return result
    refuse_symlinks(plugin_root, version_dir)
    for item in manifest['files']:
        source = planned['mapping'][item['path']]
        target = owned_path(version_dir, item['path'])
        if target.is_file() and sha256(target) == item['sha256'] and (target.stat().st_mode & 0o777) == item['mode']:
            continue
        write_atomic(target, source.read_bytes(), item['mode'])
    write_atomic(existing, (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(), 0o644)
    repoint(plugin_root, manifest['version'])
    return result


def activate(args) -> dict:
    plugin_root = prefix_path(args) / args.plugin
    if args.activate not in installed_versions(plugin_root):
        raise InstallError('unknown_version', f'no installed version {args.activate}',
                           {'installed': installed_versions(plugin_root),
                            'preserved_modified': preserved_versions(plugin_root)})
    if not args.dry_run:
        repoint(plugin_root, args.activate)
    return {'action': 'activate', 'version': args.activate, 'dry_run': bool(args.dry_run),
            'entry': str(plugin_root / 'current' / snapshot_entry(plugin_root / args.activate))}


def snapshot_entry(version_dir: Path) -> str:
    """The entry file a snapshot declares in its own plugin.json."""
    try:
        entry = json.loads((version_dir / 'plugin.json').read_text()).get('entry')
    except (OSError, ValueError, AttributeError):
        entry = None
    return entry if isinstance(entry, str) and entry else 'entry.md'


def load_manifest(path: Path, strict=True) -> dict | None:
    """The parsed manifest; a corrupt one raises manifest_corrupt (or is None when not strict)."""
    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        manifest = None
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list) or not all(
            isinstance(e, dict) and isinstance(e.get('path'), str) and isinstance(e.get('sha256'), str)
            for e in manifest['files']):
        if not strict:
            return None
        raise InstallError('manifest_corrupt', f'{path} is not a valid install manifest; reinstall with --force to replace it',
                           {'path': str(path)})
    return manifest


def snapshot_manifests(plugin_root: Path):
    if not plugin_root.is_dir():
        return
    for path in sorted(plugin_root.iterdir()):
        if not path.is_symlink() and (path / MANIFEST).is_file():
            yield path.name, load_manifest(path / MANIFEST, strict=False)


def installed_versions(plugin_root: Path, include_preserved=False) -> list:
    """Complete snapshots. A half-uninstalled snapshot that only keeps ownership of
    locally modified files (`preserved_modified`) is not installed unless asked for."""
    return sorted(name for name, manifest in snapshot_manifests(plugin_root)
                  if include_preserved or not (manifest or {}).get('preserved_modified'))


def preserved_versions(plugin_root: Path) -> list:
    return sorted(name for name, manifest in snapshot_manifests(plugin_root) if (manifest or {}).get('preserved_modified'))


def refuse_symlinks(*paths: Path) -> None:
    for path in paths:
        if path.is_symlink():
            raise InstallError('manifest_path_escape', f'{path} is a symlink; refusing to work through it')


def uninstall(args) -> dict:
    plugin_root = prefix_path(args) / args.plugin
    refuse_symlinks(plugin_root)
    if plugin_root.is_dir():
        refuse_symlinks(*[p for p in plugin_root.iterdir() if p.name != 'current' and not p.name.startswith('.current')])
    installed = installed_versions(plugin_root, include_preserved=True)
    if args.version and args.version not in installed:
        raise InstallError('unknown_version', f'{args.version!r} is not an installed version of {args.plugin}',
                           {'installed': installed})
    versions = [args.version] if args.version else installed
    removed, kept = [], []
    for version in versions:
        version_dir = plugin_root / version
        refuse_symlinks(version_dir)
        manifest_path = version_dir / MANIFEST
        if not manifest_path.is_file():
            raise InstallError('unknown_version', f'no installed version {version}')
        manifest = load_manifest(manifest_path)
        paths = [(entry, owned_path(version_dir, entry['path'])) for entry in manifest['files']]
        owned_modules = {(path.parent, path.stem) for entry, path in paths if entry['path'].endswith('.py')}
        owned_dirs = {parent for _, path in paths for parent in path.parents if version_dir in parent.parents}
        kept_entries = []
        for entry, path in paths:
            if not path.is_file():
                continue
            if sha256(path) != entry['sha256'] and not args.force:
                kept.append(str(path))
                kept_entries.append(entry)
                continue
            if not args.dry_run:
                path.unlink()
            removed.append(str(path))
        if not args.dry_run:
            if kept_entries:
                # Keep ownership of what we did not delete, so a reinstall still
                # sees the local modification and refuses to overwrite it.
                manifest['files'] = kept_entries
                manifest['preserved_modified'] = True
                write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(), 0o644)
            else:
                manifest_path.unlink()
            for cache in sorted(version_dir.rglob('__pycache__')):
                if cache.is_symlink() or not cache.is_dir():
                    continue
                for item in cache.iterdir():
                    # Bytecode of an owned module only (name.<tag>.pyc next to an owned name.py).
                    if (item.suffix in ('.pyc', '.pyo') and not item.is_symlink()
                            and (cache.parent, item.name.split('.')[0]) in owned_modules):
                        item.unlink()
                if not any(cache.iterdir()):
                    cache.rmdir()
            # Only directories that held owned files; a user-created directory stays even when empty.
            for directory in sorted(owned_dirs, key=lambda p: len(p.parts), reverse=True):
                if directory.is_dir() and not directory.is_symlink() and not any(directory.iterdir()):
                    directory.rmdir()
            if version_dir.is_dir() and not any(version_dir.iterdir()):
                version_dir.rmdir()
    link = plugin_root / 'current'
    # Only when the active version is really gone: a version kept for its local edits keeps its manifest.
    if not args.dry_run and link.is_symlink() and not (plugin_root / os.readlink(link) / MANIFEST).is_file():
        link.unlink()
    if not args.dry_run and plugin_root.is_dir() and not any(plugin_root.iterdir()):
        plugin_root.rmdir()
    return {'action': 'uninstall', 'versions': versions, 'removed': len(removed), 'kept_modified': kept,
            'dry_run': bool(args.dry_run), 'state_untouched': True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--plugin', default='imps')
    parser.add_argument('--prefix', default=os.environ.get('T3_PLUGINS_PREFIX', '~/.local/share/t3-plugins'))
    parser.add_argument('--source', help=argparse.SUPPRESS)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true', help='overwrite or remove locally modified owned files')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--uninstall', action='store_true')
    group.add_argument('--activate', metavar='VERSION')
    parser.add_argument('--version', help='with --uninstall: remove only this version')
    args = parser.parse_args(argv)
    if args.version and not args.uninstall:
        parser.error('--version requires --uninstall')
    try:
        validate_name(args.plugin)
        if args.uninstall:
            data = uninstall(args)
        elif args.activate:
            data = activate(args)
        else:
            data = install(args)
        print(json.dumps({'ok': True, 'data': data}))
        return 0
    except InstallError as exc:
        print(json.dumps({'ok': False, 'error': {'code': exc.code, 'message': exc.message, 'details': exc.details}}))
        print(f'{exc.code}: {exc.message}', file=sys.stderr)
        return 4 if exc.code == 'locally_modified' else 2
    except OSError as exc:
        print(json.dumps({'ok': False, 'error': {'code': 'io_error', 'message': str(exc), 'details': {}}}))
        return 5


if __name__ == '__main__':
    raise SystemExit(main())
