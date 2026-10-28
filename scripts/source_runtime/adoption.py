"""Explicit, resumable in-place adoption of a populated ~/.agents directory."""
import base64
import os
from pathlib import Path
import uuid

from . import discovery, layout, pins, transaction
from .io import atomic, canonical, digest, git, load, no_links, read, index_matches_head, relative, require, source_lock, tracked_clean, write_json


def legacy_owned(folder):
    """Only exact receipt-owned adapter bytes may be archived automatically."""
    no_links(folder)
    marker = next((folder/name for name in ('.dotfiles-skill.json','.t3-plugins-skill.json') if (folder/name).is_file()),None)
    require(marker is not None, 'unowned old skill requires explicit reconciliation: ' + str(folder))
    receipt = load(marker)
    require(receipt.get('schema_version') == 1 and receipt.get('name') == folder.name, 'invalid old skill ownership receipt')
    files = dict(receipt.get('files',{}))
    if marker.name == '.t3-plugins-skill.json':
        files['SKILL.md'] = receipt.get('sha256')
    require('SKILL.md' in files, 'old skill receipt omits its body')
    for name,sha in files.items():
        require(digest(read(folder/relative(name))) == sha, 'modified old skill requires explicit reconciliation: ' + str(folder/name))
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() or p.is_symlink()}
    require(actual == set(files) | {marker.name}, 'custom old picker/skill files require explicit reconciliation: ' + str(folder))
    return sorted(actual)


def prepare(paths, source):
    source = no_links(source)
    root = paths.home/'.agents'
    no_links(root)
    commit = transaction.oid(source,'HEAD')
    require(Path(git(source,'rev-parse','--show-toplevel').stdout.decode().strip()) == source,
            'adoption source must be a standalone checkout')
    require(git(source,'remote','get-url','origin').stdout.decode().strip() in transaction.ORIGINS,
            'adoption source must have the expected canonical origin')
    require(tracked_clean(source) and
            index_matches_head(source),
            'adoption requires reviewed committed source, not dirty infrastructure')
    values = pins.commit_files(source,commit,runtime_only=False)
    require('.agents-source.json' in values, 'adoption commit has no source identity')
    selection = pins.capture_receiver(paths,source,commit)
    candidate = pins.verify(paths,selection['pin'])
    info = layout.validate(candidate)
    for name in info['skills']:
        existing = root/'skills'/name
        if existing.is_dir() and layout.skill(candidate,name)['exempt']:
            extras = [p for p in existing.rglob('*') if p.is_file() and p.relative_to(existing).as_posix() != 'SKILL.md']
            require(not extras, 'custom picker/helper files require explicit reconciliation for an exempt skill: ' + name)
    provenance_name = 'migration/issue-198-source-provenance.json'
    provenance = {}
    if provenance_name in values:
        import json
        provenance = json.loads(values[provenance_name][0])['files']
    rows = []
    old_discovery = discovery.receipt(paths)
    imported = {row['path']:row['target'] for row in old_discovery['links']}
    old_names = ['t3-'+name for name in info['skills'] if name != 'unslop']
    old_names += ['t3-'+name for name in info['identity'].get('legacy_only_plugins',[])]
    owned_names = set()
    for name in old_names:
        folder = root/'skills'/name
        if not folder.exists():
            continue
        for name_in_folder in legacy_owned(folder):
            file = folder/name_in_folder
            rows.append({'path':str(file.relative_to(paths.home)), 'before':transaction.observed(file),'after':None})
        owned_names.add(name)
    registry = load(candidate/'discovery.json')
    legacy_roots = registry.get('legacy_roots',[])
    for native in legacy_roots:
        native_root = no_links(paths.home/relative(native))
        for name in old_names:
            link = native_root/name
            if link.is_symlink():
                require(name in owned_names and os.readlink(link) == str(root/'skills'/name),
                        'unowned old native skill link; preserve it: ' + str(link))
                imported[str(link)] = os.readlink(link)
            elif link.exists():
                for rel in legacy_owned(link):
                    file = link/rel
                    rows.append({'path':str(file.relative_to(paths.home)), 'before':transaction.observed(file),'after':None})
        # An old utility link can transfer only against the frozen source hash.
        utility = native_root/'unslop'
        if utility.is_symlink():
            original = provenance.get('skills/unslop/SKILL.md',{}).get('original_sha256')
            require(os.readlink(utility) == str(root/'skills/unslop') and
                    (digest(read(root/'skills/unslop/SKILL.md')) == original or
                     str(utility) in imported), 'unowned utility alias requires explicit reconciliation')
            imported[str(utility)] = os.readlink(utility)
    for name,value in sorted(values.items()):
        file = root/relative(name)
        before,after = transaction.observed(file),transaction.state(value)
        if before == after:
            continue
        if before is not None:
            original = provenance.get(name,{}).get('original_sha256')
            require(original is not None and digest(base64.b64decode(before['data'])) == original,
                    'existing source file collision requires explicit reconciliation: ' + name)
        rows.append({'path':str(file.relative_to(paths.home)),'before':before,'after':after})
    previous = {'schema_version':1,'links':[{'path':path,'target':target} for path,target in sorted(imported.items())]}
    aliases = discovery.plan(paths,candidate,root,previous_receipt=previous)
    head_ref = None
    if (root/'.git').exists():
        require(transaction.oid(root,'HEAD') == commit and source == root,
                'existing Git adoption must select its own exact source checkout')
        head_ref = git(root,'symbolic-ref','-q','HEAD',check=False).stdout.decode().strip() or None
    for name in info['skills']:
        pins.materialize(paths,selection['pin'],name)
    backup = paths.control/'adoptions'/str(uuid.uuid4())
    for row in rows:
        if row['before'] is not None:
            atomic(backup/'files'/relative(row['path']),base64.b64decode(row['before']['data']),row['before']['mode'])
    journal = {'schema_version':1,'kind':'adoption','phase':'prepared','created_at':transaction.now(),
        'source_root':str(root),'donor':str(source),'commit':commit,'pin':selection['pin'],
        'identity_sha256':digest(values['.agents-source.json'][0]),'files':rows,'links':aliases,
        'old_discovery':old_discovery,'backup':str(backup),
        'git_existed':(root/'.git').exists(),'head_ref':head_ref,
        'legacy_paths':['agents/t3-plugins','.t3-plugins-registry.lock','.dotfiles-wiring.json','mcp.json','plugins/marketplace.json','skills/synced']}
    write_json(backup/'restore-map.json',journal)
    return journal


def apply(paths,journal,hook=None):
    require(journal.get('kind') == 'adoption' and journal.get('schema_version') == 1, 'invalid adoption journal')
    root = no_links(paths.home/'.agents')
    require(journal['source_root'] == str(root), 'adoption destination differs')
    transaction.verify_paths(paths.home,journal['files'])
    for row in journal['links']['changes']:
        require(discovery.current(Path(row['path'])) in (row['before'],row['after']), 'adoption alias owner edit; recovery stopped')
    marker = paths.control/'cutover.json'
    # Guard-only hosts fail closed throughout interrupted adoption.
    write_json(marker,{'schema_version':1,'phase':'pending','source_root':str(root),
        'repository_id':'1411719736','identity_sha256':journal['identity_sha256']})
    transaction.phase(paths,journal,'adopting',hook)
    for number,row in enumerate(journal['files']):
        file = paths.home/relative(row['path'])
        actual = transaction.observed(file)
        require(actual in (row['before'],row['after']), 'owner edit during adoption; stopped')
        after = row['after']
        if actual != after:
            if after is None:
                file.unlink()
            else:
                atomic(file,base64.b64decode(after['data']),after['mode'])
        if hook:
            hook('file:'+str(number))
    # Remove only now-empty legacy adapter directories, never foreign contents.
    for row in journal['files']:
        if row['after'] is None:
            parent = (paths.home/relative(row['path'])).parent
            while parent != paths.home and parent != root and parent.name != 'skills':
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
    transaction.phase(paths,journal,'files',hook)
    if not (root/'.git').exists():
        git(root,'init','-q','-b','main')
        git(root,'remote','add','origin','https://github.com/seankoji-com/.agents.git')
    origin = git(root,'remote','get-url','origin').stdout.decode().strip()
    require(origin in transaction.ORIGINS, 'adoption destination origin changed')
    if git(root,'cat-file','-e',journal['commit']+'^{commit}',check=False).returncode != 0:
        donor = no_links(journal['donor'])
        require(transaction.oid(donor,'HEAD') == journal['commit'], 'adoption donor changed; recovery needs original commit')
        git(root,'fetch','--no-tags','--no-write-fetch-head',str(donor),journal['commit'],timeout=60)
    existing = git(root,'rev-parse','--verify','refs/heads/main',check=False)
    old = existing.stdout.decode().strip() if existing.returncode == 0 else '0'*40
    require(old in ('0'*40,journal['commit']), 'adoption branch changed; stopped')
    # read-tree replaces the index, so only a state adoption itself produced may be
    # replaced: the commit's tree, or the empty index of a repository adoption created.
    # Anything else is owner work (staged or index-only); stop and keep it.
    index = git(root,'write-tree').stdout.decode().strip()
    permitted = {git(root,'rev-parse',journal['commit']+'^{tree}').stdout.decode().strip()}
    if not journal['git_existed']:
        permitted.add(git(root,'hash-object','-t','tree','--stdin',input=b'').stdout.decode().strip())
    require(index in permitted, 'adoption index holds owner changes; stopped without replacing them')
    head = git(root,'symbolic-ref','-q','HEAD',check=False).stdout.decode().strip() or None
    require(head in ({journal['head_ref'],'refs/heads/main'} if journal['git_existed'] else {'refs/heads/main'}),
            'adoption HEAD moved to another branch; stopped')
    # A detached HEAD has no ref to compare, so the commit itself must still be ours.
    head_commit = git(root,'rev-parse','--verify','-q','HEAD',check=False).stdout.decode().strip()
    require(head_commit in ({journal['commit']} if journal['git_existed'] else {'',journal['commit']}),
            'adoption HEAD moved to another commit; stopped')
    git(root,'read-tree',journal['commit'])
    git(root,'update-ref','refs/heads/main',journal['commit'],old)
    git(root,'symbolic-ref','HEAD','refs/heads/main')
    transaction.phase(paths,journal,'ref',hook)
    discovery.apply(paths,journal['links'])
    require(tracked_clean(root) and
            index_matches_head(root),
            'adopted source/index differs; preserve owner edits and recover explicitly')
    # Untracked residues must be the inventoried ignored paths or foreign skills.
    layout.validate(root)
    pins.verify(paths,journal['pin'])
    active = {'schema_version':1,'commit':journal['commit'],'pin':journal['pin'],'activated_at':transaction.now()}
    write_json(paths.control/'active.json',active)
    write_json(paths.control/'validated-pins.json',{journal['pin']:active})
    write_json(marker,{'schema_version':1,'phase':'active','source_root':str(root),
        'repository_id':'1411719736','identity_sha256':journal['identity_sha256']})
    config = load(paths.control/'profile.json')
    config['source_root'] = str(root)
    if config['profile'] == 'author':
        config['receive_enabled'] = False
    write_json(paths.control/'profile.json',config)
    transaction.phase(paths,journal,'complete',hook)
    return {'status':'adopted','source_root':str(root),'commit':journal['commit'],'pin':journal['pin'],
        'backup':journal['backup'],'profile':config['profile'],'receive_enabled':config['receive_enabled']}


def adopt(paths,source=None,hook=None):
    with source_lock(paths):
        file = paths.control/'journal.json'
        if transaction.pending(paths):
            journal = load(file)
            require(journal.get('kind') == 'adoption', 'recover the pending receiver transaction first')
            require(source is None or str(no_links(source)) == journal['donor'], 'pending adoption has a different donor')
        else:
            require(source is not None, 'adoption requires an explicit reviewed source checkout')
            journal = prepare(paths,source)
            write_json(file,journal)
        return apply(paths,journal,hook)
