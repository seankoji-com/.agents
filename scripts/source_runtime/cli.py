"""Stable source interface. Source commands never dispatch agents or models."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from . import bootstrap, layout, pins
from .io import Paths, SourceError, git, load, no_links, read, require, source_lock, write_json


def configuration(paths):
    file = paths.control / 'profile.json'
    require(file.exists(), 'agents infrastructure is not installed; explicit self-install required')
    config = load(file)
    require(config.get('schema_version') == 1 and config.get('profile') in ('author', 'receiver'),
            'invalid installed source profile')
    return config


def status(paths):
    config = configuration(paths)
    root = no_links(config['source_root'])
    head = git(root, 'rev-parse', 'HEAD', check=False)
    dirty = git(root, 'status', '--porcelain=v1', '-z', check=False)
    active = load(paths.control / 'active.json') if (paths.control / 'active.json').exists() else None
    installed = load(paths.control / 'bootstrap-active.json')
    upstream = git(root, 'rev-list', '--left-right', '--count', 'HEAD...refs/remotes/origin/' + config['branch'], check=False)
    counts = upstream.stdout.decode().split() if upstream.returncode == 0 else []
    journal = load(paths.control / 'journal.json') if (paths.control / 'journal.json').exists() else None
    history = load(paths.control / 'last-sync.json') if (paths.control / 'last-sync.json').exists() else None
    return {'profile': config['profile'], 'source_root': str(root),
        'source_head': head.stdout.decode().strip() if head.returncode == 0 else None,
        'source_available': head.returncode == 0, 'source_status': os.fsdecode(dirty.stdout).split('\0')[:-1] if dirty.returncode == 0 else None,
        'ahead': int(counts[0]) if len(counts) == 2 else None, 'behind': int(counts[1]) if len(counts) == 2 else None,
        'active': active, 'installed_revision': installed['revision'], 'interpreter': sys.executable,
        'launcher': str(paths.launcher), 'receive_enabled': config['receive_enabled'],
        'pending_recovery': journal if journal and journal.get('phase') != 'complete' else None,
        'last_sync': history, 'actions': ['agents receive disable', 'agents sync', 'agents recover', 'agents rollback PIN'],
        'source_layout': layout.validate(root) if head.returncode == 0 else None,
        'snapshot_retention': 'All pins retained. No garbage collection or abandonment inference.'}


def select(paths, config, explicit_source=None):
    root = no_links(explicit_source or config['source_root'])
    journal = paths.control / 'journal.json'
    require(not journal.exists() or load(journal).get('phase') == 'complete',
            'source update has pending recovery; existing explicit pins remain usable')
    if config['profile'] == 'author':
        return pins.capture_author(paths, root)
    require(explicit_source is None, 'receiver starts use only the active commit; worktree tests need an isolated author profile')
    active_file = paths.control / 'active.json'
    require(active_file.exists(), 'receiver has no validated active commit; run explicit sync/adoption first')
    active = load(active_file)
    pins.verify(paths, active['pin'])
    return {'pin': active['pin'], 'selected_commit': active['commit'], 'profile': 'receiver', 'source_root': str(root)}


def start(paths, name, explicit_source=None, pin=None):
    config = configuration(paths)
    with source_lock(paths):
        if pin is None and config['profile'] == 'author':
            info = layout.skill(no_links(explicit_source or config['source_root']), name)
            if info['exempt']:
                return {'name': name, 'bootstrap_exempt': True, 'skill_file': str(info['file']),
                        'snapshot_written': False, 'profile': 'author'}
        selection = ({'pin': pin, 'selected_commit': None, 'profile': 'pinned-resume'} if pin else
                     select(paths, config, explicit_source))
        package = pins.materialize(paths, selection['pin'], name)
        receipt = {**selection, **package, 'name': name, 'interpreter': sys.executable,
                   'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        file = paths.jobs / 'starts' / (str(uuid.uuid4()) + '.json')
        write_json(file, receipt)
        return {**receipt, 'receipt': str(file), 'snapshot_written': pin is None}


def job_path(paths, job_file, name):
    job = load(job_file)
    matches = [pin for key, pin in job.get('pins', {}).items()
               if next((d.get('plugin') for d in job.get('dependencies', []) if d.get('key') == key), None) == name]
    require(len(matches) == 1, 'job does not pin exactly one requested dependency')
    package = no_links(matches[0]['package_dir'])
    prefix = package.parent.parent
    require(prefix.parent == paths.packages and re.fullmatch(r'[0-9a-f]{64}', prefix.name),
            'legacy job needs its inventoried compatibility runtime; no live package substitution')
    materialized = pins.materialize(paths, prefix.name, name, dependency=True)
    require(materialized['package_root'] == str(package), 'job package differs from source pin materialization')
    # The job recorded these identities when it pinned the package; all must still agree.
    receipt = load(package / 'install-manifest.json')
    for field in ('package_digest', 'installation_id', 'bundle_dir', 'bundle_digest'):
        require(matches[0].get(field) == receipt.get(field), 'job ' + field + ' differs from the pinned package')
    return materialized


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, help='explicit author worktree for this invocation only')
    p.add_argument('--pin', help='exact immutable source pin')
    p.add_argument('--job', type=Path, help='existing job with exact dependency pins')
    sub = p.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('self-install')
    setup.add_argument('--home', type=Path)
    setup.add_argument('--source', dest='install_source', type=Path)
    setup.add_argument('--profile', choices=('author', 'receiver'))
    sub.add_parser('status')
    sub.add_parser('validate-source')
    sub.add_parser('self-test')
    sub.add_parser('permissions',help='print the narrow write grants; never change provider settings')
    sub.add_parser('discovery',help='owner reconciliation of native names; no source files or package installation')
    legacy = sub.add_parser('legacy')
    legacy_actions = legacy.add_subparsers(dest='legacy_action',required=True)
    inventory = legacy_actions.add_parser('inventory')
    inventory.add_argument('--root',type=Path,action='append',default=[])
    inventory.add_argument('--job-file',type=Path,action='append',default=[])
    inventory.add_argument('--run-root',type=Path,action='append',default=[])
    bridge = legacy_actions.add_parser('install-bridge')
    bridge.add_argument('--catalog-root',type=Path,required=True)
    dispatch = legacy_actions.add_parser('dispatch')
    dispatch.add_argument('--job',dest='legacy_job',type=Path,required=True)
    dispatch.add_argument('arguments',nargs=argparse.REMAINDER)
    for command in ('selection', 'agreement', 'planning-review', 'resolve', 'agents'):
        forwarding = sub.add_parser(command, add_help=False)
        forwarding.add_argument('arguments', nargs=argparse.REMAINDER)
    launch = sub.add_parser('start')
    launch.add_argument('name')
    resume = sub.add_parser('resume')
    resume.add_argument('pin_id')
    resume.add_argument('name')
    path = sub.add_parser('path')
    path.add_argument('name')
    for name in ('sync', 'recover'):
        command = sub.add_parser(name)
        if name == 'recover':
            command.add_argument('--restore', action='store_true')
    receive = sub.add_parser('receive')
    receive.add_argument('action', choices=('enable', 'disable'))
    rollback = sub.add_parser('rollback')
    rollback.add_argument('pin_id')
    adopt = sub.add_parser('adopt')
    adopt.add_argument('--from-source', type=Path, required=True)
    return p


def main(argv=None, home=None, infrastructure_source=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'self-install':
            if infrastructure_source is None:
                source = args.install_source or args.source or Path(configuration(Paths(home))['source_root'])
                script = no_links(source / 'scripts/agents_bootstrap.py')
                require(script.is_file(), 'source bootstrap is missing; inspect the selected checkout')
                os.execv(sys.executable, [sys.executable, '-I', str(script), *sys.argv[1:]])
            paths = Paths(args.home or home)
            result = bootstrap.self_install(infrastructure_source, paths, args.install_source or args.source, args.profile)
        else:
            paths = Paths(home)
            if args.command == 'legacy':
                from . import legacy
                if args.legacy_action == 'dispatch':
                    return legacy.dispatch(paths,['--job',str(args.legacy_job),*args.arguments])
                result = (legacy.inventory(paths,args.root,args.job_file,args.run_root) if args.legacy_action == 'inventory'
                          else legacy.install_bridge(paths,args.catalog_root))
                print(json.dumps(result,sort_keys=True))
                return 0
            if args.command in ('selection', 'agreement', 'planning-review', 'resolve', 'agents'):
                return forward(paths, args)
            if args.command == 'status':
                result = status(paths)
            elif args.command == 'permissions':
                roots = [str(paths.state/name) for name in ('jobs','snapshots','locks')]
                anchor = str(paths.home/'.local/state/agents/locks')
                if anchor not in roots:
                    roots.append(anchor)
                result = {'write_roots':roots,'codex':{'sandbox_workspace_write':{'writable_roots':roots}},
                    'claude':{'sandbox':{'filesystem':{'allowWrite':roots}}},
                    'protected':[str(paths.control),str(paths.data/'updater'),str(paths.data/'legacy'),
                        str(paths.launcher),str(paths.home/'.local/bin/t3-plugins'),
                        str(paths.home/'.config/systemd/user/agents-receive.service'),
                        str(paths.home/'.config/systemd/user/agents-receive.timer')],
                    'scope':'Merge only these data subtrees into normal native profiles; retain legacy grants for old jobs. Configuration is not live-access proof.'}
            elif args.command == 'discovery':
                from . import discovery, transaction
                require(args.source is None, 'worktree tests cannot change production discovery')
                with source_lock(paths):
                    require(not transaction.pending(paths), 'recover the pending source transaction before discovery')
                    config = configuration(paths)
                    root = no_links(config['source_root'])
                    selection = select(paths,config)
                    candidate = pins.verify(paths,selection['pin'])
                    prepared = discovery.plan(paths,candidate,root)
                    discovery.apply(paths,prepared)
                    result = {'source_root':str(root),'pin':selection['pin'],
                              'changes':len(prepared['changes']),'source_written':False}
            elif args.command == 'self-test':
                result = bootstrap.self_test()
            elif args.command == 'validate-source':
                root = args.source or Path(configuration(paths)['source_root'])
                result = layout.validate(root)
            elif args.command == 'start':
                result = start(paths, args.name, args.source, args.pin)
            elif args.command == 'resume':
                require(args.pin is None, 'use either resume PIN or --pin, not both')
                result = start(paths, args.name, pin=args.pin_id)
            elif args.command == 'path':
                require(args.pin is not None or args.job is not None, 'path requires --pin or --job; never a moving current path')
                result = job_path(paths, args.job, args.name) if args.job else pins.materialize(paths, args.pin, args.name, dependency=True)
                if args.pin is not None and args.job is not None:
                    require(str(pins.verify(paths, args.pin)) in result['package_root'] or
                            str(paths.packages / args.pin) in result['package_root'], 'job and explicit source pin differ')
                print(result['skill_file'])
                return 0
            elif args.command in ('sync', 'recover', 'rollback'):
                from . import transaction
                if args.command == 'recover' and transaction.pending(paths) and load(paths.control/'journal.json').get('kind') == 'adoption':
                    from . import adoption
                    require(not args.restore, 'adoption restore requires its private restore map; preserve the initialized Git metadata')
                    result = adoption.adopt(paths)
                else:
                    result = transaction.execute(paths, args.command, getattr(args, 'pin_id', None),
                        restore=getattr(args, 'restore', False))
            elif args.command == 'receive':
                from . import services
                result = services.receive(paths, args.action)
            else:
                from . import adoption
                result = adoption.adopt(paths, args.from_source)
        print(json.dumps(result, sort_keys=True, default=str))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print('agents: ' + str(exc), file=sys.stderr)
        return 2


def forward(paths, args):
    """Run workflow logic from its selected source pin, never installed current."""
    require(args.pin is not None, 'workflow commands require --pin from agents start')
    source = pins.verify(paths, args.pin)
    scripts = {'selection':'model_selection_cli.py', 'agreement':'execution_agreement_cli.py',
               'planning-review':'planning_review_cli.py'}
    if args.command in scripts:
        executable = source / 'shared' / scripts[args.command]
        command = [sys.executable, '-I', '-B', str(executable), *args.arguments]
    else:
        # Catalog worker inspection/routing uses this pin's registry and packages.
        if args.command == 'agents' and len(args.arguments) >= 2 and args.arguments[0] in ('list', 'show'):
            pins.materialize(paths, args.pin, args.arguments[1], dependency=True)
        command = [sys.executable, '-I', '-B', '-c',
                   'import sys,runpy;sys.path.insert(0,sys.argv.pop(1));sys.argv[0]=sys.argv.pop(1);runpy.run_path(sys.argv[0],run_name="__main__")',
                   str(source / 'scripts'), str(source / 'scripts/catalog.py'),
                   '--prefix', str(paths.packages / args.pin), '--agents-root', str(paths.registry),
                   args.command, *args.arguments]
    env = {k:v for k,v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    return subprocess.run(command, env=env, check=False).returncode
