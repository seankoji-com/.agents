"""Fast-forward receiving with exact-byte, index and ref recovery."""
import base64
import datetime
from pathlib import Path

from . import bootstrap, discovery, pins
from .io import atomic, canonical, git, load, no_links, read, relative, require, source_lock, write_json

# The same canonical spellings the dotfiles cutover guard accepts (seankoji-com/.dotfiles#576),
# so the adopter and the guard agree on one checkout identity.
ORIGINS = {'https://github.com/seankoji-com/.agents.git', 'https://github.com/seankoji-com/.agents',
           'git@github.com:seankoji-com/.agents.git', 'git@github.com:seankoji-com/.agents',
           'ssh://git@github.com/seankoji-com/.agents.git', 'ssh://git@github.com/seankoji-com/.agents'}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def oid(root, name):
    return git(root, 'rev-parse', '--verify', name).stdout.decode().strip()


def pending(paths):
    file = paths.control / 'journal.json'
    return file.exists() and load(file).get('phase') != 'complete'


def index_tree(root):
    return git(root, 'write-tree').stdout.decode().strip()


def preflight(root, config):
    require(root == Path(git(root, 'rev-parse', '--show-toplevel').stdout.decode().strip()), 'source is not a standalone checkout')
    require(config['origin'] in ORIGINS and config['branch'] == 'main', 'receive requires the configured authenticated .agents/main source')
    require(git(root, 'remote', 'get-url', '--all', 'origin').stdout.decode().splitlines() == [config['origin']],
            'configured origin differs; refusing another source')
    require(git(root, 'symbolic-ref', '-q', 'HEAD').stdout.decode().strip() == 'refs/heads/main',
            'receiver must be on its configured main branch')
    git_dir = Path(git(root, 'rev-parse', '--absolute-git-dir').stdout.decode().strip())
    for name in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-apply','rebase-merge','BISECT_START','index.lock'):
        require(not (git_dir / name).exists(), 'Git operation in progress: ' + name)
    for option in ('core.sparseCheckout','core.autocrlf','core.splitIndex'):
        result = git(root, 'config', '--bool', '--get', option, check=False)
        require(result.returncode == 1 or result.stdout.strip() == b'false', 'unsupported Git checkout semantics: ' + option)
    monitor = git(root,'config','--get','core.fsmonitor',check=False)
    require(monitor.returncode == 1 or monitor.stdout.strip() in (b'false',b'0'),
            'Git filesystem-monitor execution is unsupported during receiving')
    tags = git(root,'ls-files','-v','-z').stdout.split(b'\0')
    require(all(not row or row.startswith(b'H ') for row in tags),
            'unsupported skip-worktree/assume-unchanged index flags')
    configured_hooks = git(root,'config','--path','--get','core.hooksPath',check=False)
    hooks = Path(configured_hooks.stdout.decode().strip()) if configured_hooks.returncode == 0 else git_dir/'hooks'
    if not hooks.is_absolute():
        hooks = root/hooks
    for name in ('reference-transaction','post-index-change','pre-auto-gc','post-checkout','post-merge'):
        hook = hooks/name
        require(not hook.exists() or not hook.stat().st_mode & 0o111,
                'executable Git hook is unsupported during receiving: '+name)
    transport = git(root, 'config', '--get-regexp', r'^(remote\.origin\.(uploadpack|fetch)|core\.attributesfile)', check=False)
    for line in transport.stdout.decode().splitlines():
        require(line == 'remote.origin.fetch +refs/heads/*:refs/remotes/origin/*', 'unsupported Git filter/transport configuration')
    # A configured filter (git-lfs installs filter.lfs.* for every repository) runs only
    # for paths whose attributes select it, so refuse any tracked path that does. This
    # covers the global attributes file; prepare() limits incoming .gitattributes.
    listed = git(root, 'ls-files', '-z').stdout
    selected = git(root, 'check-attr', '--stdin', '-z', 'filter', input=listed).stdout.split(b'\0')
    require(all(value in (b'unspecified', b'unset') for value in selected[2::3]),
            'unsupported Git filter/transport configuration: a tracked path selects a filter')
    require(not (git_dir / 'info/attributes').exists() or not read(git_dir / 'info/attributes').strip(),
            'custom Git attributes are unsupported')
    require(git(root, 'diff', '--no-ext-diff', '--no-textconv', '--quiet', check=False).returncode == 0, 'tracked source is dirty')
    require(git(root, 'diff', '--cached', '--no-ext-diff', '--no-textconv', '--quiet', check=False).returncode == 0, 'source index is staged')
    return oid(root, 'HEAD')


def state(data):
    if data is None:
        return None
    raw, executable = data
    return {'data':base64.b64encode(raw).decode('ascii'), 'mode':0o755 if executable else 0o644}


def observed(path):
    path = no_links(path)
    if not path.exists():
        return None
    return state((read(path), bool(path.stat().st_mode & 0o111)))


def verify_paths(root, rows):
    for row in rows:
        path = root / relative(row['path'])
        require(observed(path) in (row['before'], row['after']),
                'source owner edit or unrecorded bytes; recovery stopped: ' + row['path'])


def prepare(paths, root, old, new):
    before = pins.commit_files(root, old, runtime_only=False)
    after = pins.commit_files(root, new, runtime_only=False)
    for tree in (before,after):
        for name,(data,_) in tree.items():
            require(Path(name).name != '.gitmodules', 'Git submodules are unsupported')
            if Path(name).name == '.gitattributes':
                for line in data.decode().splitlines():
                    fields = line.split()
                    require(not fields or fields[0].startswith('#') or len(fields) == 2 and fields[1] == 'export-ignore',
                            'unsupported Git attributes/filter; no source files changed')
    rows = []
    for name in sorted(before.keys() | after.keys()):
        a, b = state(before.get(name)), state(after.get(name))
        if a == b:
            continue
        path = root / relative(name)
        require(observed(path) == a, 'untracked collision or source changed before staging: ' + name)
        # File/directory transitions require manual reconciliation, never cleanup.
        for parent in path.parents:
            if parent == root:
                break
            require(not parent.exists() or parent.is_dir(), 'candidate parent collides with an existing file')
        rows.append({'path':name,'before':a,'after':b})
    selected = pins.capture_receiver(paths, root, new)
    candidate = pins.verify(paths, selected['pin'])
    for name in load(candidate / '.agents-source.json')['required_skills']:
        pins.materialize(paths, selected['pin'], name)
    # Infrastructure does not auto-activate. Explicit self-install remains required.
    bootstrap.prepare(paths, after)
    links = discovery.plan(paths, candidate, root)
    return {'schema_version':1,'kind':'receive','phase':'prepared','created_at':now(),
        'source_root':str(root),'ref':'refs/heads/main','old':old,'new':new,
        'old_tree':oid(root, old+'^{tree}'),'new_tree':oid(root, new+'^{tree}'),
        'files':rows,'links':links,'old_discovery':discovery.receipt(paths),
        'old_active':load(paths.control/'active.json') if (paths.control/'active.json').exists() else None,
        'new_active':{'schema_version':1,'commit':new,'pin':selected['pin'],'activated_at':now()}}


def phase(paths, journal, name, hook):
    journal['phase'] = name
    write_json(paths.control / 'journal.json', journal)
    if hook:
        hook(name)


def apply(paths, journal, reverse=False, hook=None):
    require(journal.get('schema_version') == 1 and journal.get('kind') == 'receive', 'unsupported recovery journal')
    root = no_links(journal['source_root'])
    config = load(paths.control / 'profile.json')
    require(str(root) == config['source_root'] and journal['ref'] == 'refs/heads/main', 'recovery source identity differs')
    verify_paths(root, journal['files'])
    require(index_tree(root) in (journal['old_tree'],journal['new_tree']), 'source index changed; recovery stopped')
    current = oid(root, journal['ref'])
    require(current in (journal['old'],journal['new']), 'source branch changed; recovery stopped')
    # Validate every alias before the first source mutation as well as at use.
    for row in journal['links']['changes']:
        require(discovery.current(Path(row['path'])) in (row['before'],row['after']), 'native alias owner edit; recovery stopped')
    desired = 'before' if reverse else 'after'
    target = journal['old'] if reverse else journal['new']
    phase(paths, journal, 'restoring' if reverse else 'applying', hook)
    for number, row in enumerate(journal['files']):
        path = root / relative(row['path'])
        actual = observed(path)
        require(actual in (row['before'],row['after']), 'source changed during apply; recovery stopped')
        value = row[desired]
        if actual != value:
            if value is None:
                path.unlink()
            else:
                atomic(path, base64.b64decode(value['data'], validate=True), value['mode'])
        if hook:
            hook('file:' + str(number))
    phase(paths, journal, 'files', hook)
    require(index_tree(root) in (journal['old_tree'],journal['new_tree']), 'source index changed during apply')
    git(root, 'read-tree', target)
    phase(paths, journal, 'index', hook)
    current = oid(root, journal['ref'])
    require(current in (journal['old'],journal['new']), 'source ref changed during apply')
    git(root, 'update-ref', journal['ref'], target, current)
    phase(paths, journal, 'ref', hook)
    discovery.apply(paths, journal['links'], reverse=reverse)
    if reverse:
        write_json(paths.control/'discovery.json', journal['old_discovery'])
    phase(paths, journal, 'links', hook)
    verify_paths(root, journal['files'])
    require(all(observed(root/relative(row['path'])) == row[desired] for row in journal['files']),
            'source changed before activation')
    require(oid(root,'HEAD') == target and index_tree(root) == oid(root,target+'^{tree}'), 'source/index/ref mismatch')
    require(git(root,'diff','--no-ext-diff','--no-textconv','--quiet',check=False).returncode == 0, 'source changed before activation')
    active = journal['old_active'] if reverse else journal['new_active']
    if active is None:
        file = paths.control/'active.json'
        if file.exists():
            file.unlink()
    else:
        pins.verify(paths, active['pin'])
        write_json(paths.control/'active.json', active)
        validated_file = paths.control/'validated-pins.json'
        validated = load(validated_file) if validated_file.exists() else {}
        validated[active['pin']] = active
        write_json(validated_file, validated)
    marker = paths.control/'cutover.json'
    if marker.exists():
        record = load(marker)
        require(record.get('source_root') == str(root) and record.get('repository_id') == '1411719736',
                'cutover identity differs during receiving')
        record['identity_sha256'] = pins.digest(read(root/'.agents-source.json'))
        write_json(marker,record)
    phase(paths, journal, 'active', hook)
    journal['restored'] = reverse
    journal['completed_at'] = now()
    phase(paths, journal, 'complete', hook)
    return {'status':'restored' if reverse else 'applied','active':active, 'source_head':target}


def sync(paths, config, fetcher=None, hook=None):
    require(config['profile'] == 'receiver', 'automatic/manual receiving is disabled for the author profile')
    require(not pending(paths), 'pending recovery; run agents recover or agents recover --restore')
    choice = paths.control/'rollback.json'
    if choice.exists() and load(choice).get('hold'):
        return {'status':'held','reason':'operator rollback remains selected; agents rollback follow-source resumes updates'}
    root = no_links(config['source_root'])
    old = preflight(root, config)
    upstream = 'refs/remotes/origin/main'
    prior = git(root,'rev-parse','--verify',upstream,check=False)
    if prior.returncode == 0:
        require(git(root,'merge-base','--is-ancestor',old,upstream,check=False).returncode == 0,
                'source is ahead or diverged; no fetch/apply attempted')
    if fetcher:
        fetcher(root)
    else:
        git(root,'-c','protocol.file.allow=never','fetch','--no-auto-maintenance','--no-tags','--no-recurse-submodules',
            'origin','refs/heads/main:refs/remotes/origin/main',timeout=60)
    new = oid(root, upstream)
    require(preflight(root,config) == old, 'source changed during fetch')
    require(git(root,'merge-base','--is-ancestor',old,new,check=False).returncode == 0, 'upstream rewrote or diverged from source')
    if prior.returncode == 0:
        require(git(root,'merge-base','--is-ancestor',prior.stdout.decode().strip(),new,check=False).returncode == 0,
                'upstream history was rewritten; refusing it')
    if old == new and (paths.control/'active.json').exists():
        active = load(paths.control/'active.json')
        if active['commit'] == old:
            pins.verify(paths,active['pin'])
            return {'status':'unchanged','active':active,'source_head':old}
    journal = prepare(paths,root,old,new)
    require(preflight(root,config) == old, 'source changed during candidate validation')
    write_json(paths.control/'journal.json',journal)
    if hook:
        hook('prepared')
    return apply(paths,journal,hook=hook)


def execute(paths, action, pin=None, restore=False, fetcher=None, hook=None):
    with source_lock(paths):
        config = load(paths.control/'profile.json')
        try:
            if action == 'sync':
                result = sync(paths,config,fetcher,hook)
            elif action == 'recover':
                require(pending(paths), 'no pending transaction to recover')
                result = apply(paths,load(paths.control/'journal.json'),reverse=restore,hook=hook)
            else:
                require(not pending(paths), 'recover the pending source transaction before runtime rollback')
                if pin == 'follow-source':
                    write_json(paths.control/'rollback.json', {'hold':False,'at':now()})
                    result = {'status':'following-source-on-next-sync'}
                else:
                    validated = load(paths.control/'validated-pins.json')
                    require(pin in validated, 'rollback requires a previously validated receiver pin')
                    pins.verify(paths,pin)
                    write_json(paths.control/'rollback.json', {'hold':True,'pin':pin,'at':now()})
                    write_json(paths.control/'active.json',validated[pin])
                    result = {'status':'rolled-back','active':validated[pin]}
        except (OSError,ValueError,KeyError) as exc:
            history(paths,{'status':'error','action':action,'at':now(),'reason':str(exc)})
            raise
        history(paths,{**result,'action':action,'at':now()})
        return result


def history(paths, value):
    file = paths.control/'last-sync.json'
    write_json(file,value)
    # Bounded rotation, outside the checkout. No daemon or second scheduler.
    logs = paths.state/'logs'
    logs.mkdir(parents=True,exist_ok=True,mode=0o700)
    for index in range(4,0,-1):
        previous = logs/('sync.'+str(index)+'.json')
        if previous.exists():
            previous.replace(logs/('sync.'+str(index+1)+'.json'))
    atomic(logs/'sync.1.json',canonical(value))
