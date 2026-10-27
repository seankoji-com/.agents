"""Conservative old-job inventory and a job-bound compatibility command."""
from collections import Counter
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from .io import atomic, canonical, digest, load, no_links, read, regular_files, relative, require, run_verified, source_lock, write_json

# Isolated (-I: no inherited PYTHONPATH, user site or script-directory import path);
# only the verified retained scripts directory is added, as pinned forwarding does.
RUNPY = 'import sys,runpy;sys.path.insert(0,sys.argv.pop(1));sys.argv[0]=sys.argv.pop(1);runpy.run_path(sys.argv[0],run_name="__main__")'


def isolated_catalog(root, *arguments):
    return [str(Path(sys.executable).resolve()),'-I','-B','-c',RUNPY,str(root/'scripts'),str(root/'scripts/catalog.py'),*arguments]


def classify(file):
    try:
        job = load(file)
        require(isinstance(job,dict) and type(job.get('schema_version')) is int and job['schema_version'] == 1 and
                isinstance(job.get('pins'),dict) and all(isinstance(pin,dict) for pin in job['pins'].values()) and
                job.get('job_id'), 'unrecognized job state')
        live = any(handle.get('status') not in ('completed','failed','cancelled','interrupted') or
            handle.get('has_pending_child_runs') for task in job.get('tasks',[])
            for handle in task.get('handles',[])+task.get('followups',[]))
        # A stale index/live flag is not abandonment evidence. Unknowns stay.
        terminal = job.get('status') in ('completed','cancelled','discarded') and not live
        return ('terminal' if terminal else 'resumable'),job,None
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return 'missing/unknown',None,str(exc)


def inventory(paths, roots, job_files=(), run_roots=()):
    records = {}
    claims = []
    for root in roots:
        root = no_links(root)
        index = load(root/'job-index.json')
        require(index.get('schema_version') == 1 and isinstance(index.get('jobs'),dict), 'invalid old job index; preserve it')
        for key,row in index['jobs'].items():
            require(isinstance(row.get('job_id'),str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',row['job_id']), 'unsafe indexed job ID')
            state = Path(row['state_root'])
            require(state.is_absolute(), 'legacy job root must be absolute')
            file = state/row['job_id']/'job.json'
            records.setdefault(str(file),{'index_refs':[]})['index_refs'].append({'index':str(root/'job-index.json'),'key':key,'record':row})
        claim_file = root/'claims.json'
        if claim_file.exists():
            for identity,claim in load(claim_file).items():
                # Claims cannot be retired merely because no job was found.
                claims.append({'installation_id':identity,'claim':claim,'classification':'missing/unknown',
                               'reason':'preserve until owner-reviewed zero-reference reconciliation'})
    for file in job_files:
        require(Path(file).is_absolute(), 'explicit legacy job locator must be absolute')
        records.setdefault(str(file),{'index_refs':[]})
    for file,row in records.items():
        category,job,error = classify(file)
        row.update(path=file,classification=category,error=error)
        row['pins'] = job.get('pins',{}) if job else {}
        row['job_id'] = job.get('job_id') if job else None
        row['stored_commands'] = []
        for pin in row['pins'].values():
            for field in ('compatible_pinned_argv','compatible_pinned_invocation'):
                if field in pin:
                    row['stored_commands'].append({'field':field,'value':pin[field]})
            try:
                trace_pin(pin,row)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                row['classification'] = 'missing/unknown'
                row.setdefault('unresolved_pins',[]).append(str(exc))
        def trace(value,key=''):
            if isinstance(value,dict):
                for field,part in value.items():
                    trace(part,field)
            elif isinstance(value,list):
                if key.endswith('argv') and all(isinstance(part,str) for part in value):
                    row['stored_commands'].append({'field':key,'value':value})
                else:
                    for part in value:
                        trace(part,key)
            elif isinstance(value,str) and key in ('command','invocation','compatible_pinned_invocation'):
                row['stored_commands'].append({'field':key,'value':value})
        if job:
            trace(job)
        executables = set()
        for command in row['stored_commands']:
            value = command['value']
            try:
                argv = shlex.split(value) if isinstance(value,str) else value
                if argv:
                    executables.add(argv[0])
            except ValueError:
                row.setdefault('unparsed_commands',[]).append(command)
        row['executable_dependencies'] = sorted(executables)
    runs = {}
    for state in run_roots:
        state = no_links(state)
        for file in sorted((state/'runs').glob('*/run.json')):
            record = {'path':str(file),'state_root':str(state),'classification':'missing/unknown'}
            runs[str(file)] = record
            try:
                run = load(file)
                require(type(run.get('schema_version')) is int and run['schema_version'] in (1,2) and
                        run.get('run_id') == file.parent.name, 'unrecognized retained gate run')
                plugin = run['plugin']
                package = no_links(plugin['package_dir'])
                receipt_file = package/'install-manifest.json'
                receipt = load(receipt_file)
                for row in receipt['files']:
                    require(digest(read(package/relative(row['path']))) == row['sha256'],
                            'retained gate package integrity failure')
                record.update(plugin=plugin,receipt_sha256=digest(read(receipt_file)),
                    classification='terminal' if run.get('phase') in ('completed','cancelled') else 'resumable',
                    interpreter=str(Path(sys.executable).resolve()),
                    status_argv=[sys.executable,str(package/'cli.py'),'status','--state-root',str(state),'--run-id',run['run_id']])
            except (OSError,ValueError,KeyError,TypeError) as exc:
                record['reason'] = str(exc)
    result = {'schema_version':1,'jobs':records,'claims':claims,'runs':runs,
        'run_summary':dict(Counter(row['classification'] for row in runs.values())),
        'summary':dict(Counter(row['classification'] for row in records.values())),
        'retirement':'No automatic deletion. Owner-reviewed report and zero resumable/unknown references are required.',
        'test_leaks':[]}
    with source_lock(paths):
        write_json(paths.control/'legacy-inventory.json',result)
    return {'jobs':len(records),'classifications':result['summary'],'claims_preserved':len(claims),
            'retained_gate_runs':len(runs),'run_classifications':result['run_summary'],
            'inventory':str(paths.control/'legacy-inventory.json'),'retirement':result['retirement']}


def trace_pin(pin,row):
    require(isinstance(pin,dict) and Path(pin.get('package_dir','')).is_absolute(), 'unresolved legacy package locator')
    package = no_links(pin['package_dir'])
    manifest_file = package/'install-manifest.json'
    receipt = load(manifest_file)
    require(receipt.get('package_digest') == pin.get('package_digest') and pin.get('package_digest'),
            'legacy package digest differs or is unrecorded')
    for file in receipt['files']:
        require(digest(read(package/relative(file['path']))) == file['sha256'],
                'retained job package integrity failure')
    entry = package/relative(load(package/'plugin.json').get('entry','entry.md'))
    commands = sorted(set(re.findall(r't3-plugins[^`\n]*',read(entry).decode())))
    row['stored_commands'].extend({'field':'entry-command','value':command} for command in commands)
    row.setdefault('runtime_receipts',[]).append({'path':str(manifest_file),
        'sha256':digest(read(manifest_file)),'installation_id':receipt.get('installation_id')})


def runtime_values(root):
    root = no_links(root)
    result = {}
    total = 0
    for file in sorted(root.rglob('*')):
        no_links(file)
        if any(part == '__pycache__' for part in file.relative_to(root).parts) or file.suffix in ('.pyc','.pyo'):
            continue
        if not file.is_file():
            continue
        name = file.relative_to(root).as_posix()
        require(Path(name).parts[0] in ('core','shared','scripts','plugins'), 'unexpected input in legacy runtime')
        data = read(file)
        total += len(data)
        require(total <= 128*1024*1024, 'legacy runtime exceeds bounded copy size')
        result[name] = (data,bool(file.stat().st_mode & 0o111))
    require('scripts/catalog.py' in result and 'core/cli.py' in result, 'legacy catalog runtime is incomplete')
    return result


def install_bridge(paths,catalog_root):
    """Copy complete runtime bytes out of the keg; never relocate pinned jobs."""
    values = runtime_values(catalog_root)
    rows = [{'path':name,'sha256':digest(data),'executable':executable} for name,(data,executable) in sorted(values.items())]
    require(rows == [{'path':name,'sha256':digest(data),'executable':executable}
        for name,(data,executable) in sorted(runtime_values(catalog_root).items())], 'legacy source changed during retention')
    revision = digest(canonical(rows))
    target = no_links(paths.data/'legacy'/revision)
    for row in rows:
        file = target/row['path']
        data,executable = values[row['path']]
        if file.exists():
            require(read(file) == data, 'retained legacy runtime was changed')
        else:
            atomic(file,data,0o555 if executable else 0o444)
    manifest = {'schema_version':1,'revision':revision,'files':rows,'root':str(target),
                'interpreter':str(Path(sys.executable).resolve())}
    manifest_bytes = canonical(manifest)
    atomic(target/'runtime.json',manifest_bytes,0o444)
    require(regular_files(target) ==
            {row['path'] for row in rows} | {'runtime.json'}, 'unexpected retained legacy executable inputs')
    # Execute a nonmutating catalog parse through the retained interpreter.
    with tempfile.TemporaryDirectory(prefix='agents-pycache-') as cache:
        command = isolated_catalog(target,'--help')
        checked = subprocess.run([command[0],'-X','pycache_prefix='+cache,*command[1:]],capture_output=True,timeout=20)
    require(checked.returncode == 0, 'retained legacy catalog/interpreter is not runnable')
    launcher = paths.home/'.local/bin/t3-plugins'
    control = paths.control/'legacy-runtime.json'
    text = ('#!'+str(Path(sys.executable).resolve())+' -I\n'
        'import sys\nfrom pathlib import Path\n'
        'sys.dont_write_bytecode=True\n'
        'control=Path('+repr(str(paths.control/'bootstrap-active.json'))+')\n'
        # Reuse the stable resolver's installation verification before dispatch.
        'import runpy\nsys.argv=["agents","legacy","dispatch",*sys.argv[1:]]\n'
        'runpy.run_path('+repr(str(paths.launcher))+',run_name="__main__")\n').encode()
    with source_lock(paths):
        require((paths.control/'legacy-inventory.json').exists(), 'inventory all indexed old jobs before bridge installation')
        old_receipt = paths.control/'legacy-launcher.json'
        if launcher.exists():
            require(old_receipt.exists() and load(old_receipt)['sha256'] == digest(read(launcher)),
                    'unrelated t3-plugins executable; preserve it')
        write_json(control,{'schema_version':1,'manifest_sha256':digest(manifest_bytes),'root':str(target)})
        atomic(launcher,text,0o755)
        write_json(old_receipt,{'schema_version':1,'sha256':digest(text)})
    return {'bridge':str(launcher),'retained_runtime':str(target),'interpreter':manifest['interpreter'],
            'revision':revision,'inventory':str(paths.control/'legacy-inventory.json')}


def dispatch(paths,argv):
    arguments = list(argv)
    require(arguments[:1] == ['--job'] and len(arguments) >= 4,
            'legacy compatibility requires --job INVENTORIED_JOB and an old-job command; new invocations are disabled')
    file = no_links(arguments[1])
    inventory_file = paths.control/'legacy-inventory.json'
    indexed = load(inventory_file)['jobs']
    require(str(file) in indexed and indexed[str(file)]['classification'] in ('resumable','terminal'),
            'legacy job is not inventoried; preserve unknowns and reconcile before executing')
    category,job,error = classify(file)
    require(job is not None and job['job_id'] == indexed[str(file)]['job_id'], 'inventoried job identity differs')
    require(job['pins'] == indexed[str(file)]['pins'], 'legacy job pins changed; re-inventory without substituting dependencies')
    action = arguments[2]
    allowed = {'path','agents','selection','agreement','planning-review','resolve','doctor'}
    require(action in allowed, 'legacy compatibility cannot create/register/install/uninstall/activate new workflows')
    record = load(paths.control/'legacy-runtime.json')
    root = no_links(record['root'])
    raw = read(root/'runtime.json')
    require(digest(raw) == record['manifest_sha256'], 'retained legacy runtime manifest integrity failure')
    manifest = load(root/'runtime.json')
    expected = {'runtime.json'}
    for row in manifest['files']:
        target = root/relative(row['path'])
        require(digest(read(target)) == row['sha256'] and bool(target.stat().st_mode & 0o111) == row['executable'],
                'retained legacy runtime integrity failure')
        expected.add(row['path'])
    require(regular_files(root) == expected,
            'unexpected legacy runtime executable inputs')
    dependencies = {dependency['plugin'] for dependency in job.get('dependencies',[])}
    if action == 'path':
        require(len(arguments) == 4 and arguments[3] in dependencies, 'path must name an inventoried dependency')
        command = isolated_catalog(root,*arguments)
    elif action in ('selection','agreement','planning-review'):
        helpers = {'selection':'model_selection_cli.py','agreement':'execution_agreement_cli.py',
                   'planning-review':'planning_review_cli.py'}
        require(len(arguments) >= 6 and '--input' in arguments[3:], 'old-job helper needs an explicit input file')
        # Do not admit new frozen authorities, installations, jobs or workflow plans.
        require(arguments[3] not in ('freeze','save-authority','admit','create','prepare-initial'),
                'legacy compatibility refuses new-job/model admission')
        pin = job['pins'].get('workflow') or next(iter(job['pins'].values()))
        package = Path(pin['package_dir'])
        require(package.is_absolute(), 'legacy package locator must be absolute')
        import registry
        # The install receipt, not a plugin manifest: load_manifest expects a plugin directory.
        receipt = json.loads(registry.read_regular(package/'install-manifest.json','package receipt').decode('utf-8'))
        require(pin['package_digest'] == receipt['package_digest'] == registry.package_digest(receipt),
                'legacy pinned package digest differs')
        registry.verify_package_files(package,receipt)
        if receipt.get('bundle_dir'):
            bundle = registry.verify_bundle(Path(receipt['bundle_dir']),receipt['installation_id'],
                receipt['plugin'],receipt['version'],receipt['package_digest'])
            require(bundle['bundle_digest'] == pin.get('bundle_digest') == receipt['bundle_digest'],
                    'legacy pinned worker bundle differs')
        command = [sys.executable,'-I','-B',str(package/'shared'/helpers[action]),*arguments[3:]]
    elif action == 'resolve':
        # Read-only candidate inspection through the verified retained catalog.
        require(len(arguments) >= 4, 'resolve needs a role')
        command = isolated_catalog(root,'resolve',*arguments[3:])
    else:
        require(action in ('agents','doctor') and len(arguments) >= 4, 'legacy command not needed by the inventoried resume contract')
        # Worker access is restricted to this job's package prefix and registry.
        name = arguments[4] if action == 'agents' and len(arguments) >= 5 else arguments[3]
        require(name in dependencies, 'worker/doctor command must name an inventoried dependency')
        require(action != 'agents' or arguments[3] in ('list','show'), 'legacy worker registration/overrides are disabled')
        dependency = next(d for d in job['dependencies'] if d['plugin'] == name)
        pin = job['pins'][dependency['key']]
        if action == 'agents' and arguments[3] == 'show':
            # The job froze its effective workers; never recompose them from live overrides.
            require(len(arguments) == 6, 'agents show needs PLUGIN WORKER')
            import registry  # noqa: F401  puts the source root on sys.path
            from shared.job_coordinator import verify_pinned_dependency
            verify_pinned_dependency(dependency,pin)
            worker = name+'/'+arguments[5]
            record = pin['effective_workers'].get(worker)
            require(record is not None, 'worker is not pinned by this job: '+worker)
            print(json.dumps({'worker': {'id': worker, 'bundle_digest': pin['bundle_digest']},
                'provenance': {'source': 'job pin', 'job': str(file), 'bundle_dir': pin['bundle_dir'],
                    'base_sha256': record['base_sha256'], 'override_status': record['override_status'],
                    'override_sha256': record['override_sha256']},
                'definition': record['bytes']}))
            return 0
        receipt = load(Path(pin['package_dir'])/'install-manifest.json')
        prefix = Path(pin['package_dir']).parent.parent
        # The retained catalog's doctor reads the version named by current and takes no
        # version argument; refuse rather than check another version.
        if action == 'doctor':
            current = prefix/name/'current'
            require(current.is_symlink() and current.resolve() == Path(pin['package_dir']).resolve(),
                    'retained current version differs from this job\'s pin; use agents list, which reports every version')
        command = isolated_catalog(root,'--prefix',str(prefix),'--agents-root',receipt['agents_root'],*arguments[2:])
    env = {k:v for k,v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH')}
    return run_verified(command,env)
