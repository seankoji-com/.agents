#!/usr/bin/env python3
"""Discover, install, and invoke the T3 plugin catalog without a model client."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import install as installer
import skills

ROOT = Path(__file__).resolve().parent.parent


def catalog():
    plugins = []
    for path in sorted((ROOT / 'plugins').glob('*/plugin.json')):
        meta = json.loads(path.read_text())
        installer.validate_name(meta['name'])
        if meta['name'] != path.parent.name:
            raise ValueError(f'catalog name does not match folder: {path.parent.name}')
        plugins.append(meta)
    return plugins


def snapshot_matches_bundle(manifest, plugin):
    """Compare content, not Git provenance: archives and checkouts can be identical."""
    return manifest['files'] == installer.plan_install(ROOT, plugin)['manifest']['files']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default=os.environ.get('T3_PLUGINS_PREFIX', '~/.local/share/t3-plugins'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='list bundled plugins')
    setup = sub.add_parser('setup', help='install snapshots and provider skill adapters together')
    setup.add_argument('plugin', nargs='?')
    setup.add_argument('--root', action='append', help='skill directory; repeat for multiple providers')
    adapters = sub.add_parser('skills', help='install or remove T3 slash-menu skill adapters')
    adapters.add_argument('action', choices=('install', 'uninstall'))
    adapters.add_argument('plugin', nargs='?')
    adapters.add_argument('--root', required=True, help='provider skill directory on the T3 environment')
    helps = {'path': 'print the installed entry path of one plugin',
             'prompt': 'print a prompt that reads the installed entry and runs REQUEST (default: doctor)',
             'doctor': 'check installed file integrity for all plugins or one named plugin'}
    for name in ('path', 'prompt', 'doctor'):
        command = sub.add_parser(name, help=helps[name])
        command.add_argument('plugin', nargs='?' if name == 'doctor' else None)
        if name == 'prompt':
            command.add_argument('request', nargs=argparse.REMAINDER, default=['doctor'])
    install = sub.add_parser('install', help='install all plugins or one named plugin')
    install.add_argument('plugin', nargs='?')
    install.add_argument('--dry-run', action='store_true')
    install.add_argument('--force', action='store_true')
    remove = sub.add_parser('uninstall', help='remove owned files, preserving state and local edits')
    remove.add_argument('plugin')
    remove.add_argument('--dry-run', action='store_true')
    remove.add_argument('--force', action='store_true', help='also remove locally modified owned files')
    remove.add_argument('--version', help='remove only this installed snapshot')
    activate = sub.add_parser('activate', help='activate an installed snapshot')
    activate.add_argument('plugin')
    activate.add_argument('version')
    args = parser.parse_args(argv)
    try:
        plugins = catalog()
        if getattr(args, 'plugin', None) is not None:
            installer.validate_name(args.plugin)
            if args.plugin not in {p['name'] for p in plugins}:
                raise ValueError(f'unknown plugin: {args.plugin}')
            plugins = [p for p in plugins if p['name'] == args.plugin]
        if args.command == 'list':
            for meta in plugins:
                print(f"{meta['name']:20} {meta['description']}")
            return 0
        prefix = Path(args.prefix).expanduser().absolute()
        if args.command == 'setup':
            roots = args.root or [str(Path.home() / path) for path in
                                  ('.agents/skills', '.claude/skills', '.gemini/config/skills')]
            for meta in plugins:
                code = installer.main(['--plugin', meta['name'], '--prefix', str(prefix)])
                if code:
                    return code
                for root in roots:
                    print(json.dumps(skills.install(root, prefix, meta)))
            return 0
        if args.command == 'skills':
            for meta in plugins:
                receipt = (skills.install(args.root, prefix, meta) if args.action == 'install'
                           else skills.uninstall(args.root, meta))
                print(json.dumps(receipt))
            return 0
        if args.command in ('install', 'uninstall', 'activate'):
            # Per-plugin atomic activation. An all-catalog install can be partial;
            # each receipt identifies what completed, and retries are idempotent.
            for meta in plugins:
                forwarded = ['--plugin', meta['name'], '--prefix', str(prefix)]
                if args.command == 'uninstall':
                    forwarded.append('--uninstall')
                    if getattr(args, 'version', None):
                        forwarded.extend(['--version', args.version])
                if args.command == 'activate':
                    forwarded.extend(['--activate', args.version])
                for flag in ('dry_run', 'force'):
                    if getattr(args, flag, False):
                        forwarded.append('--' + flag.replace('_', '-'))
                code = installer.main(forwarded)
                if code:
                    return code
            return 0
        failed = False
        for meta in plugins:
            current = prefix / meta['name'] / 'current'
            entry = current / meta['entry']
            if args.command == 'doctor':
                errors = []
                try:
                    if not current.is_symlink() or not current.resolve().is_relative_to(current.parent.resolve()):
                        raise ValueError('missing or external current symlink')
                    manifest = installer.load_manifest(current / installer.MANIFEST)
                    if manifest.get('plugin') != meta['name']:
                        raise ValueError('manifest plugin mismatch')
                    if not snapshot_matches_bundle(manifest, meta['name']):
                        errors.append('snapshot_outdated: run t3-plugins install ' + meta['name'])
                    for item in manifest['files']:
                        path = installer.owned_path(current.resolve(), item['path'])
                        if not path.is_file() or installer.sha256(path) != item['sha256']:
                            errors.append('missing_or_modified:' + item['path'])
                    if not entry.is_file():
                        errors.append('missing_entry')
                except (OSError, ValueError, installer.InstallError) as exc:
                    if not current.is_symlink() and not current.exists():
                        errors.append(f"not_installed: run t3-plugins install {meta['name']}")
                    else:
                        errors.append(f'installation_invalid: {exc}')
                failed |= bool(errors)
                print(json.dumps({'plugin': meta['name'], 'ok': not errors, 'errors': errors,
                                  'scope': 'installed file integrity and package currency; provider behavior not tested'}))
            else:
                if not entry.is_file():
                    raise ValueError(f"{meta['name']} is not installed; run t3-plugins install {meta['name']}")
                if args.command == 'path':
                    print(entry)
                else:
                    print(f"Read {entry} and run: {' '.join(args.request) or 'doctor'}")
        return 1 if failed else 0
    except (ValueError, OSError, KeyError, installer.InstallError) as exc:
        print(f't3-plugins: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
