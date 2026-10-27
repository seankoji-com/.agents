#!/usr/bin/env python3
"""Discover, install, and invoke the T3 plugin catalog without a model client."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import install as installer
import routing
import skills
import registry
import manifest_data

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'shared'))
import learning_grants
import learning_store

ROOT = Path(__file__).resolve().parent.parent
# Removed from the catalog. Setup deletes their owned, unmodified skill adapters;
# `uninstall` still accepts them so old snapshots can be removed.
RETIRED = ('offload-sidecar', 'prompt-builder')


def default_skill_roots():
    """Use each provider's native discovery root without a shared second copy."""
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    codex = Path(os.environ.get('CODEX_HOME') or home / '.codex')
    return list(dict.fromkeys(str(root) for root in (
        home / '.claude/skills', codex / 'skills', config / 'opencode/skills',
        home / '.gemini/config/skills', home / '.gemini/skills', config / 'muse/skills')))


def catalog(include_deprecated=False):
    plugins = []
    for path in sorted((ROOT / 'plugins').glob('*/plugin.json')):
        meta = manifest_data.load(path)
        installer.validate_name(meta['name'])
        if meta['name'] != path.parent.name:
            raise ValueError(f'catalog name does not match folder: {path.parent.name}')
        skills.validate_picker(meta)
        if include_deprecated or not meta.get('deprecated'):
            plugins.append(meta)
    return plugins


def retired_meta(args, prefix):
    """A plugin that left the catalog can still be removed: `uninstall` accepts it when
    an installed manifest records it, and `skills uninstall` when it is a known retirement."""
    if args.command == 'skills' and args.action == 'uninstall' and args.plugin in RETIRED:
        return {'name': args.plugin}
    if args.command != 'uninstall':
        return None
    for _, manifest in installer.snapshot_manifests(prefix / args.plugin):
        # A retired plugin's corrupt manifest still reaches the installer, which names the file.
        if (manifest or {}).get('plugin') == args.plugin or (manifest is None and args.plugin in RETIRED):
            return {'name': args.plugin}
    return None


def snapshot_matches_bundle(manifest, plugin):
    """Compare content, not Git provenance: archives and checkouts can be identical."""
    return manifest['files'] == installer.plan_install(ROOT, plugin)['manifest']['files']


def resolve_job_pin(job_path: Path, plugin: str) -> Path:
    """Resolve only an explicitly declared, intact dependency from a versioned job."""
    try: job = json.loads(registry.read_regular(job_path, 'job state').decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc: raise ValueError(f'job file is missing or malformed: {job_path}') from exc
    if not isinstance(job, dict) or job.get('schema_version') != 1:
        raise ValueError('job has unsupported or missing schema_version')
    deps = job.get('dependencies'); pins = job.get('pins')
    if not isinstance(deps, list) or not isinstance(pins, dict): raise ValueError('job dependency/pin state is malformed')
    seen = set()
    for dep in deps:
        if (not isinstance(dep, dict) or not isinstance(dep.get('key'), str) or
                not isinstance(dep.get('plugin'), str) or dep['key'] in seen):
            raise ValueError('job dependency records are malformed or duplicated')
        seen.add(dep['key'])
    if set(pins) != seen:
        raise ValueError('job dependency pins are missing or undeclared')
    declared = [d for d in deps if d.get('plugin') == plugin]
    if not declared: raise ValueError(f'undeclared job dependency: {plugin}')
    candidates = []
    for dep in declared:
        key = dep.get('key')
        pin = pins.get(key)
        if not isinstance(key, str) or not isinstance(pin, dict): raise ValueError(f'unresolved job dependency pin: {key!r}')
        candidates.append((key, pin))
    paths = {str(Path(pin.get('package_dir', '')).absolute()) for _, pin in candidates}
    if len(paths) != 1: raise ValueError(f'ambiguous dependency pin for {plugin}')
    key, pin = candidates[0]
    package = Path(pin.get('package_dir', '')).absolute()
    if not Path(pin.get('package_dir', '')).is_absolute():
        raise ValueError(f'package pin path must be absolute: {key}')
    if package.is_symlink(): raise ValueError(f'pinned package directory is a symlink: {key}')
    try: mf = json.loads(registry.read_regular(package / installer.MANIFEST, 'package receipt').decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc: raise ValueError(f'pinned package is missing or corrupt: {key}') from exc
    if (mf.get('plugin') != plugin or package.name != mf.get('version') or
            pin.get('package_digest') != mf.get('package_digest') or
            (pin.get('installation_id') is not None and pin.get('installation_id') != mf.get('installation_id'))):
        raise ValueError(f'wrong or changed package pin: {key}')
    if registry.package_digest(mf) != mf.get('package_digest'):
        raise ValueError(f'pinned package manifest digest mismatch: {key}')
    registry.verify_package_files(package, mf)
    try: plugin_manifest = json.loads(registry.read_regular(package / 'plugin.json', 'plugin manifest').decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc: raise ValueError(f'pinned plugin manifest is missing: {key}') from exc
    if plugin_manifest.get('workers') and not mf.get('bundle_dir'):
        raise ValueError(f'worker package has no complete external bundle: {key}')
    if plugin_manifest.get('workers'):
        required_pin = ('installation_id', 'package_dir', 'package_digest', 'bundle_dir', 'bundle_digest')
        if any(not pin.get(field) for field in required_pin):
            raise ValueError(f'worker dependency pin is incomplete: {key}')
        if os.path.realpath(pin['package_dir']) != os.path.realpath(package):
            raise ValueError(f'package path does not match dependency pin: {key}')
    if mf.get('bundle_dir'):
        checked = registry.verify_bundle(Path(mf['bundle_dir']), mf.get('installation_id'), plugin,
                                         mf.get('version'), mf.get('package_digest'))
        if checked['bundle_digest'] != mf.get('bundle_digest') or pin.get('bundle_dir') != mf.get('bundle_dir') or pin.get('bundle_digest') != mf.get('bundle_digest'):
            raise ValueError(f'pinned worker bundle integrity failure: {key}')
    elif pin.get('bundle_dir') or pin.get('bundle_digest'):
        raise ValueError(f'job pin references a bundle absent from legacy package: {key}')
    return package


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default=os.environ.get('AGENTS_PREFIX', '~/.local/share/agents'))
    parser.add_argument('--agents-root', default=os.environ.get('AGENTS_REGISTRY_ROOT'))
    parser.add_argument('--job', metavar='JOB', help='resolve package paths from this pinned job.json')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='list bundled plugins')
    selection = sub.add_parser('selection', help='validate frozen upfront model choices; no dispatch')
    selection.add_argument('selection_args', nargs=argparse.REMAINDER)
    agreement = sub.add_parser('agreement', help='inspect/admit scoped agreements and observed delivery')
    agreement.add_argument('agreement_args', nargs=argparse.REMAINDER)
    planning = sub.add_parser('planning-review', help='pinned planning review jobs and receipts; no dispatch')
    planning.add_argument('planning_args', nargs=argparse.REMAINDER)
    adoption = sub.add_parser('adopt', help='verify and adopt a relocated installation receipt')
    adoption.add_argument('--from-prefix', required=True)
    adoption.add_argument('--agents-root', dest='agents_root_command', default=argparse.SUPPRESS)
    agents = sub.add_parser('agents', help='inspect managed worker definitions')
    agent_sub = agents.add_subparsers(dest='agent_command', required=True)
    agent_list = agent_sub.add_parser('list', help='list installed workers and integrity')
    agent_list.add_argument('plugin', nargs='?')
    agent_show = agent_sub.add_parser('show', help='show an effective worker definition')
    agent_show.add_argument('plugin'); agent_show.add_argument('worker')
    for action in ('enable-override', 'disable-override'):
        command = agent_sub.add_parser(action, help='explicitly enable or disable a worker override')
        command.add_argument('worker_id'); command.add_argument('--base-digest', required=True)
    setup = sub.add_parser('setup', help='install snapshots and provider skill adapters together')
    setup.add_argument('plugin', nargs='?')
    setup.add_argument('--root', action='append', help='skill directory; repeat for multiple providers')
    setup.add_argument('--capabilities', metavar='FILE',
                       help='saved orchestrator_capabilities response; writes the routing config if none exists')
    setup.add_argument('--grant-learnings', action='store_true',
                       help='apply the printed subtree grants after backing up provider configs')
    setup.add_argument('--agents-root', dest='agents_root_command', default=argparse.SUPPRESS)
    resolve = sub.add_parser('resolve', help='list available routing candidates, preferred workhorse then tier order')
    resolve.add_argument('role')
    resolve.add_argument('--capabilities', metavar='FILE', required=True,
                         help='saved orchestrator_capabilities response')
    resolve.add_argument('--repo', default='.', help='repository whose .agents/routing.json takes precedence')
    resolve.add_argument('--implementer-lineage', metavar='LINEAGE',
                         help='list candidates of other lineages first and mark each as independent or not')
    resolve.add_argument('--profiles', metavar='FILE', help='sourced model suitability and per-role quality floors')
    adapters = sub.add_parser('skills', help='install or remove T3 slash-menu skill adapters')
    adapters.add_argument('action', choices=('install', 'uninstall'))
    adapters.add_argument('plugin', nargs='?')
    adapters.add_argument('--root', required=True, help='provider skill directory on the T3 environment')
    helps = {'path': 'print the installed entry path of one plugin',
             'prompt': 'print a prompt that reads the installed entry and runs REQUEST (or offers the operation picker)',
             'doctor': 'check installed file integrity for all plugins or one named plugin'}
    for name in ('path', 'prompt', 'doctor'):
        command = sub.add_parser(name, help=helps[name])
        command.add_argument('plugin', nargs='?' if name == 'doctor' else None)
        if name == 'doctor':
            command.add_argument('--agents-root', dest='agents_root_command', default=argparse.SUPPRESS)
            command.add_argument('--project', dest='doctor_project', default=None,
                                 help='also refuse a learnings root inside this project, as its plugin runs would')
        if name == 'prompt':
            command.add_argument('request', nargs=argparse.REMAINDER, default=[])
    install = sub.add_parser('install', help='install all plugins or one named plugin')
    install.add_argument('plugin', nargs='?')
    install.add_argument('--dry-run', action='store_true')
    install.add_argument('--force', action='store_true')
    install.add_argument('--agents-root', dest='agents_root_command', default=argparse.SUPPRESS)
    remove = sub.add_parser('uninstall', help='remove owned files, preserving state and local edits')
    remove.add_argument('plugin')
    remove.add_argument('--dry-run', action='store_true')
    remove.add_argument('--force', action='store_true', help='also remove locally modified owned files')
    remove.add_argument('--version', help='remove only this installed snapshot')
    remove.add_argument('--agents-root', dest='agents_root_command', default=argparse.SUPPRESS)
    activate = sub.add_parser('activate', help='activate an installed snapshot')
    activate.add_argument('plugin')
    activate.add_argument('version')
    activate.add_argument('--agents-root', dest='agents_root_command', default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == 'selection':
        from shared.model_selection_cli import main as selection_main
        return selection_main(args.selection_args)
    if args.command == 'agreement':
        from shared.execution_agreement_cli import main as agreement_main
        return agreement_main(args.agreement_args)
    if args.command == 'planning-review':
        from shared.planning_review_cli import main as planning_main
        return planning_main(args.planning_args)
    try:
        if args.command == 'resolve':
            try:
                config, sources = routing.effective_config(repo=Path(args.repo).absolute())
            except routing.RoutingError as exc:
                if exc.code != 'config_missing' or not args.profiles:
                    raise
                config, sources = None, []
            profiles = json.loads(Path(args.profiles).read_text()) if args.profiles else None
            result = routing.resolve(args.role, routing.load_capabilities(args.capabilities), config,
                                     args.implementer_lineage, profiles)
            print(json.dumps(dict(result, sources=sources)))
            return 0 if result['candidates'] else 1
        prefix = Path(args.prefix).expanduser().absolute()
        agents_root = registry.registry_root(getattr(args, 'agents_root_command', None) or args.agents_root)
        if args.command == 'adopt':
            print(json.dumps(registry.adopt(prefix, Path(args.from_prefix).expanduser().absolute(), agents_root)))
            return 0
        if args.command == 'agents':
            if args.agent_command == 'list':
                for item in registry.inspect_agents(agents_root, args.plugin, prefix): print(json.dumps(item))
            elif args.agent_command == 'show':
                print(json.dumps(registry.show_agent(agents_root, args.plugin, args.worker, prefix)))
            else:
                enabled = args.agent_command == 'enable-override'
                if enabled:
                    plugin_name = args.worker_id.split('/', 1)[0]
                    current = prefix / plugin_name / 'current'
                    if not current.is_symlink() or not current.resolve().is_relative_to((prefix / plugin_name).resolve()):
                        raise ValueError('cannot enable override without a safe active plugin installation')
                    active_version = current.resolve().name
                    worker = next((item for item in registry.inspect_agents(agents_root, plugin_name, prefix)
                                   if item['id'] == args.worker_id and item['version'] == active_version), None)
                    if not worker: raise ValueError(f'worker is not active: {args.worker_id}')
                    if worker['bundle_digest'] != args.base_digest:
                        raise ValueError('override base digest is stale; inspect agents show and use the active bundle digest')
                print(json.dumps(registry.set_override(agents_root, args.worker_id, args.base_digest, enabled)))
            return 0
        plugins = catalog(include_deprecated=getattr(args, 'plugin', None) is not None)
        if getattr(args, 'plugin', None) is not None:
            installer.validate_name(args.plugin)
            if args.plugin not in {p['name'] for p in plugins}:
                retired = retired_meta(args, prefix)
                if retired is None:
                    hint = ''
                    if args.plugin in RETIRED:
                        hint = (f' (retired; nothing of it is installed under {prefix})' if args.command == 'uninstall'
                                else f' (retired; scripts/catalog.py uninstall {args.plugin} removes an old installation)')
                    raise ValueError(f'unknown plugin: {args.plugin}{hint}')
                plugins = [retired]
            plugins = [p for p in plugins if p['name'] == args.plugin]
        if args.command == 'list':
            for meta in plugins:
                print(f"{meta['name']:20} {meta['description']}")
            return 0
        for meta in plugins:
            if meta.get('deprecated'):
                print(f"agents: {meta['name']} is deprecated; use {meta['replacement']} for new work. "
                      'Existing packages and state are preserved.', file=sys.stderr)
        if args.command == 'setup':
            roots = args.root or default_skill_roots()
            for meta in plugins:
                code = installer.main(['--plugin', meta['name'], '--prefix', str(prefix), '--agents-root', str(agents_root)])
                if code:
                    return code
                for root in roots:
                    print(json.dumps(skills.install(root, prefix, meta)))
            for root in roots:
                for name in (*RETIRED, *(p['name'] for p in catalog(include_deprecated=True)
                                         if p.get('deprecated') and p['name'] not in {m['name'] for m in plugins})):
                    receipt = skills.remove_retired(root, name)
                    if receipt:
                        print(json.dumps(receipt))
            caps = routing.load_capabilities(args.capabilities) if args.capabilities else None
            # Setup is global, not a project run. Storage enforces project containment
            # when a plugin loads lessons; cwd=$HOME must not reject the default root.
            for receipt in learning_grants.setup_grants(None, caps, args.grant_learnings):
                print(json.dumps({'learnings_grant': receipt}))
                if receipt['status'] == 'manual':
                    print(f"agents: {receipt['action']}\n{receipt['snippet']}", file=sys.stderr)
            if args.capabilities:
                receipt = routing.write_default(args.capabilities)
                print(json.dumps(receipt))
                if not receipt['valid']:
                    print(f"agents: kept the existing routing config, which is invalid: {receipt['error']}",
                          file=sys.stderr)
                    return 1
            return 0
        if args.command == 'skills':
            for meta in plugins:
                if args.action == 'uninstall' and meta['name'] in RETIRED:
                    # Retired adapters only exist under their historical t3- names.
                    receipt = (skills.remove_retired(args.root, meta['name'])
                               or {'name': 't3-' + meta['name'], 'removed': False})
                    if receipt.get('preserved'):
                        raise ValueError(receipt['preserved'])
                else:
                    receipt = (skills.install(args.root, prefix, meta) if args.action == 'install'
                               else skills.uninstall(args.root, meta))
                print(json.dumps(receipt))
            return 0
        if args.command in ('install', 'uninstall', 'activate'):
            # Per-plugin atomic activation. An all-catalog install can be partial;
            # each receipt identifies what completed, and retries are idempotent.
            for meta in plugins:
                forwarded = ['--plugin', meta['name'], '--prefix', str(prefix), '--agents-root', str(agents_root)]
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
        reference_errors = registry.validate_job_references()
        # Optional storage: report whether this process may write lessons, without failing doctor.
        # Global by default; --project adds the containment refusal a plugin run for that project applies.
        learnings_write = (learning_store.probe_write(getattr(args, 'doctor_project', None))
                           if args.command == 'doctor' else None)
        for meta in plugins:
            current = prefix / meta['name'] / 'current'
            entry = current / meta['entry']
            if args.command == 'doctor':
                errors = []
                errors.extend(reference_errors)
                try:
                    if not current.is_symlink() or not current.resolve().is_relative_to(current.parent.resolve()):
                        raise ValueError('missing or external current symlink')
                    manifest = installer.load_manifest(current / installer.MANIFEST)
                    if manifest.get('plugin') != meta['name']:
                        raise ValueError('manifest plugin mismatch')
                    if manifest.get('version') != current.resolve().name:
                        raise ValueError('manifest version mismatch')
                    if not snapshot_matches_bundle(manifest, meta['name']):
                        errors.append('snapshot_outdated: run agents start ' + meta['name'])
                    if manifest.get('bundle_dir'):
                        registry.assert_owned_locator(agents_root, manifest.get('installation_id'), prefix)
                        if os.path.realpath(Path(manifest.get('agents_root', '')).expanduser()) != os.path.realpath(agents_root):
                            errors.append('worker_bundle_agents_root_mismatch')
                        expected_bundle = registry.bundle_dir(agents_root, manifest.get('installation_id'),
                                                              meta['name'], manifest.get('version'))
                        if os.path.realpath(manifest['bundle_dir']) != os.path.realpath(expected_bundle):
                            errors.append('worker_bundle_path_mismatch')
                        checked = registry.verify_bundle(Path(manifest['bundle_dir']), manifest.get('installation_id'),
                                                         meta['name'], manifest.get('version'), manifest.get('package_digest'))
                        if checked['bundle_digest'] != manifest.get('bundle_digest'):
                            errors.append('worker_bundle_digest_mismatch')
                    elif registry.load_manifest(ROOT / 'plugins' / meta['name']).get('workers'):
                        errors.append('worker_bundle_missing')
                    for item in manifest['files']:
                        path = installer.owned_path(current.resolve(), item['path'])
                        if not path.is_file() or installer.sha256(path) != item['sha256']:
                            errors.append('missing_or_modified:' + item['path'])
                    if not entry.is_file():
                        errors.append('missing_entry')
                except (OSError, ValueError, installer.InstallError) as exc:
                    if not current.is_symlink() and not current.exists():
                        errors.append(f"not_installed: run agents start {meta['name']}")
                    else:
                        errors.append(f'installation_invalid: {exc}')
                failed |= bool(errors)
                print(json.dumps({'plugin': meta['name'], 'ok': not errors, 'errors': errors,
                                  'learnings_write': learnings_write,
                                  'scope': 'installed file integrity and package currency; learnings_write probes '
                                           'this process globally, or for --project when given; '
                                           'provider behavior not tested'}))
            else:
                job_arg = args.job if args.job is not None else getattr(args, 'job', None)
                if args.command == 'path' and job_arg:
                    package = resolve_job_pin(Path(job_arg), args.plugin)
                    pinned_meta = json.loads((package / 'plugin.json').read_text(encoding='utf-8'))
                    pinned_entry = package / pinned_meta.get('entry', 'entry.md')
                    if not pinned_entry.is_file(): raise ValueError(f'pinned entry missing: {pinned_entry}')
                    print(pinned_entry)
                    return 0
                if not entry.is_file():
                    raise ValueError(f"{meta['name']} is not installed; run agents start {meta['name']}")
                if args.command == 'path':
                    print(entry)
                else:
                    request = ' '.join(args.request).strip()
                    if request:
                        print(f'Read {entry} and run: {request}')
                    elif meta.get('default_operation'):
                        print(f'Read {entry} and start the default workflow using relevant current conversation context. '
                              'Ask only for missing facts; never ask which operation to run.')
                    elif meta.get('context_on_empty'):
                        print(f'Read {entry} and use relevant current conversation context. '
                              'Ask only for missing facts; do not invent a symptom.')
                    else:
                        options = ', '.join(meta['picker'])
                        print(f'Read {entry}. Ask through the host\'s native question picker. '
                              f'Recommend the first option and do nothing until the owner answers. '
                              f'Options: {options}.')
        return 1 if failed else 0
    except (ValueError, OSError, KeyError, installer.InstallError, routing.RoutingError) as exc:
        print(f'agents: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
