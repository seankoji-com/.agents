"""Explicit installation of stable resolver infrastructure, outside source."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import PROTOCOL
from .io import Paths, atomic, canonical, digest, load, no_links, read, require, source_lock, write_json
from .pins import read_author, records


def launcher_bytes(paths, interpreter):
    require(Path(interpreter).is_absolute() and not any(c.isspace() for c in interpreter),
            'launcher needs an absolute interpreter path without whitespace')
    # The control record and this launcher live outside normal agent write roots.
    # Verify all installed executable inputs before importing any of them.
    text = '''#!INTERPRETER -I
import hashlib,json,os,sys
from pathlib import Path
sys.dont_write_bytecode=True
record_path=Path(CONTROL)
try:
    for p in (record_path,*record_path.parents):
        if p.is_symlink(): raise ValueError('linked bootstrap control path')
    record=json.loads(record_path.read_bytes())
    root=Path(record['installation'])
    for p in (root,*root.parents):
        if p.is_symlink(): raise ValueError('linked bootstrap installation')
    raw=(root/'installation.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=record['manifest_sha256']: raise ValueError('bootstrap manifest integrity failure')
    manifest=json.loads(raw)
    if manifest['protocol']!=1: raise ValueError('unsupported bootstrap protocol; explicit self-install required')
    expected={'installation.json'}
    for row in manifest['files']:
        name=row['path']; rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts: raise ValueError('unsafe bootstrap path')
        path=root/rel
        if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError('linked bootstrap file')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']: raise ValueError('bootstrap installation integrity failure')
        if bool(path.stat().st_mode&0o111)!=row['executable']: raise ValueError('bootstrap executable mode changed')
        expected.add(name)
    if {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}!=expected: raise ValueError('unexpected bootstrap executable inputs')
    sys.path.insert(0,str(root));sys.path.insert(0,str(root/'scripts'))
    from source_runtime.cli import main
    raise SystemExit(main(home=HOME))
except (OSError,ValueError,KeyError,TypeError) as error:
    sys.exit('agents bootstrap: '+str(error))
'''
    return text.replace('INTERPRETER', interpreter).replace('CONTROL', repr(str(paths.control / 'bootstrap-active.json'))).replace('HOME', repr(str(paths.home))).encode()


def self_test():
    """Candidate test uses only its own disposable state and locks."""
    with tempfile.TemporaryDirectory(prefix='agents-self-test-') as temporary:
        temporary = Path(temporary).resolve()
        paths = Paths(temporary)
        # A parent XDG override must not select live state during this test.
        paths.state = temporary / 'state'
        paths.control = paths.state / 'control'
        with source_lock(paths, timeout=1):
            file = paths.state / 'probe.json'
            write_json(file, {'protocol': PROTOCOL})
            require(load(file) == {'protocol': PROTOCOL}, 'candidate atomic IO self-test failed')
    return {'ok': True, 'protocol': PROTOCOL, 'interpreter': sys.executable}


def self_install(infrastructure_source, paths, source=None, profile=None):
    infrastructure_source = no_links(infrastructure_source)
    before = read_author(infrastructure_source)
    values = {name: value for name, value in before.items() if name.split('/')[0] in ('core', 'shared', 'scripts')}
    require(records(before) == records(read_author(infrastructure_source)), 'infrastructure changed during self-install')
    prepared = prepare(paths, values)
    revision, target, manifest_bytes, manifest = (prepared[k] for k in ('revision','target','manifest_bytes','manifest'))
    launcher = launcher_bytes(paths, str(Path(sys.executable).resolve()))
    with source_lock(paths):
        receipt_file = paths.control / 'launcher.json'
        if paths.launcher.exists():
            require(receipt_file.exists() and load(receipt_file).get('sha256') == digest(read(paths.launcher)),
                    'unrelated or modified agents executable; preserve it before explicit reconciliation')
        config_file = paths.control / 'profile.json'
        config = load(config_file) if config_file.exists() else {'schema_version': 1, 'profile': 'author',
            'source_root': str(paths.home / '.agents'), 'origin': 'https://github.com/seankoji-com/.agents.git',
            'branch': 'main', 'receive_enabled': False}
        if source is not None:
            config['source_root'] = str(no_links(source))
        if profile is not None:
            require(profile in ('author', 'receiver'), 'invalid source profile')
            config['profile'] = profile
        if config['profile'] == 'author':
            config['receive_enabled'] = False
        active_file = paths.control / 'bootstrap-active.json'
        if active_file.exists():
            write_json(paths.control / 'bootstrap-previous.json', load(active_file))
        atomic(paths.launcher, launcher, 0o755)
        write_json(receipt_file, {'schema_version': 1, 'sha256': digest(launcher), 'interpreter': manifest['interpreter']})
        write_json(config_file, config)
        write_json(active_file, {'schema_version': 1, 'protocol': PROTOCOL, 'installation': str(target),
                                'revision': revision, 'manifest_sha256': digest(manifest_bytes)})
    return {'launcher': str(paths.launcher), 'installed_revision': revision, 'source_root': config['source_root'],
            'profile': config['profile'], 'interpreter': manifest['interpreter'], 'receive_enabled': config['receive_enabled']}


def prepare(paths, values):
    """Validate a successor without touching any active installation pointer."""
    values = {name:value for name,value in values.items() if name.split('/')[0] in ('core','shared','scripts')}
    rows = records(values)
    require(rows, 'no infrastructure files to install')
    revision = digest(canonical(rows))
    target = no_links(paths.data / 'updater' / revision)
    paths.data.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths.control.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = {'schema_version': 1, 'protocol': PROTOCOL, 'revision': revision, 'files': rows,
                'interpreter': str(Path(sys.executable).resolve())}
    manifest_bytes = canonical(manifest)
    if target.exists():
        require(read(target / 'installation.json') == manifest_bytes, 'existing infrastructure installation differs')
        for row in rows:
            require(digest(read(target / row['path'])) == row['sha256'], 'existing infrastructure was modified')
            require(bool((target/row['path']).stat().st_mode & 0o111) == row['executable'],
                    'existing infrastructure executable mode changed')
    else:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix='.install-', dir=target.parent) as temporary:
            staging = Path(temporary) / 'candidate'
            for row in rows:
                data, executable = values[row['path']]
                atomic(staging / row['path'], data, 0o555 if executable else 0o444)
            atomic(staging / 'installation.json', manifest_bytes, 0o444)
            os.rename(staging, target)
    require({p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()} ==
            {row['path'] for row in rows} | {'installation.json'}, 'unexpected candidate updater executable inputs')
    # Candidate execution precedes every live pointer/launcher mutation.
    result = subprocess.run([sys.executable, '-I', str(target / 'scripts/agents_bootstrap.py'), 'self-test'],
                            capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, 'candidate updater self-test failed; previous installation retained: ' + result.stderr[-1000:])
    observed = json.loads(result.stdout)
    require(observed.get('ok') is True and observed.get('protocol') == PROTOCOL and
            Path(observed['interpreter']).resolve() == Path(sys.executable).resolve(), 'candidate interpreter/protocol mismatch')
    return {'revision':revision, 'target':target, 'manifest_bytes':manifest_bytes, 'manifest':manifest}
