"""Content-addressed source snapshots and exact package materialization."""
import io
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace

from . import layout
from .io import atomic, canonical, digest, git, load, no_links, read, regular_files, relative, require

DIRECTORIES = {'bin', 'core', 'plugins', 'references', 'roles', 'scripts', 'shared', 'skills'}
ROOT_FILES = {'.agents-source.json', 'discovery.json'}
MAX_CAPTURE_BYTES = 128 * 1024 * 1024


def runtime_path(name):
    path = relative(name)
    return path.parts[0] in DIRECTORIES or name in ROOT_FILES


def entry(name, data, executable):
    require(not layout.SECRET.search(name), 'private credential/runtime path cannot enter a source pin: ' + name)
    return {'path': name, 'sha256': digest(data), 'executable': bool(executable)}


def author_files(root):
    names = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').stdout
    return sorted({os.fsdecode(name) for name in names.split(b'\0') if name and runtime_path(os.fsdecode(name))})


def read_author(root):
    values = {}
    total = 0
    managed = set(layout.validate(root)['skills'])
    for name in author_files(root):
        parts = Path(name).parts
        if parts[0] == 'skills' and len(parts) > 1 and parts[1] not in managed:
            continue  # A foreign store stays visible, but is never captured/claimed.
        path = no_links(root / name)
        if not path.exists():  # A tracked deletion belongs to this dirty snapshot.
            continue
        data = read(path)
        total += len(data)
        require(total <= MAX_CAPTURE_BYTES, 'source capture exceeds its bounded byte limit')
        values[name] = (data, bool(path.stat().st_mode & 0o111))
    return values


def records(values):
    return [entry(name, *value) for name, value in sorted(values.items())]


def seal(paths, values):
    rows = records(values)
    pin = digest(canonical(rows))
    destination = no_links(paths.snapshots / pin)
    if destination.exists():
        verify(paths, pin)
        return pin
    paths.snapshots.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.capture-', dir=paths.snapshots) as temporary:
        staging = Path(temporary) / 'pin'
        source = staging / 'source'
        for row in rows:
            data, executable = values[row['path']]
            atomic(source / row['path'], data, 0o555 if executable else 0o444)
        layout.validate(source)
        atomic(staging / 'snapshot.json', canonical({'schema_version': 1, 'pin': pin, 'files': rows}), 0o444)
        # Accidental imports cannot add bytecode or generated files to the pin.
        for folder in sorted((p for p in source.rglob('*') if p.is_dir()), reverse=True):
            folder.chmod(0o555)
        source.chmod(0o555)
        os.rename(staging, destination)
        destination.chmod(0o555)
    return pin


def capture_author(paths, root, after_read=None):
    root = no_links(root)
    head = os.fsdecode(git(root, 'rev-parse', 'HEAD').stdout).strip()
    first = read_author(root)
    if after_read is not None:  # Deterministic race fixture, never a CLI hook.
        after_read()
    second = read_author(root)
    require(records(first) == records(second) and
            os.fsdecode(git(root, 'rev-parse', 'HEAD').stdout).strip() == head,
            'source changed during capture; no unstable pin was published')
    pin = seal(paths, first)
    return {'pin': pin, 'selected_commit': head, 'profile': 'author', 'source_root': str(root)}


def commit_files(root, commit, runtime_only=True):
    require(re.fullmatch(r'[0-9a-f]{40}', commit) is not None, 'receiver requires an exact full commit')
    require(os.fsdecode(git(root, 'rev-parse', '--verify', commit + '^{commit}').stdout).strip() == commit,
            'receiver commit is not a commit object')
    entries = []
    for item in git(root, 'ls-tree', '-rz', '--full-tree', commit).stdout.split(b'\0'):
        if not item:
            continue
        header, raw_name = item.split(b'\t', 1)
        mode, kind, oid = header.split()
        require(kind == b'blob' and mode in (b'100644', b'100755'),
                'source commit contains unsupported symlinks, submodules or modes')
        name = os.fsdecode(raw_name)
        if not runtime_only or runtime_path(name):
            entries.append((name, oid.decode(), mode == b'100755'))
    stream = io.BytesIO(git(root, 'cat-file', '--batch', input=''.join(oid + '\n' for _, oid, _ in entries).encode()).stdout)
    result = {}
    total = 0
    for name, oid, executable in entries:
        actual, kind, raw_size = stream.readline().strip().split()
        require(actual.decode() == oid and kind == b'blob', 'Git batch object correlation differs')
        size = int(raw_size)
        total += size
        require(size <= 16 * 1024 * 1024 and total <= MAX_CAPTURE_BYTES, 'Git source export exceeds its bounded byte limit')
        data = stream.read(size)
        require(len(data) == size and stream.read(1) == b'\n', 'incomplete Git source export')
        result[name] = (data, executable)
    require(stream.read() == b'', 'unexpected Git batch output')
    return result


def capture_receiver(paths, root, commit):
    pin = seal(paths, commit_files(root, commit))
    return {'pin': pin, 'selected_commit': commit, 'profile': 'receiver', 'source_root': str(root)}


def verify(paths, pin):
    require(re.fullmatch(r'[0-9a-f]{64}', pin) is not None, 'invalid source pin')
    directory = no_links(paths.snapshots / pin)
    source = directory / 'source'
    manifest = load(directory / 'snapshot.json')
    require(manifest.get('schema_version') == 1 and manifest.get('pin') == pin, 'snapshot identity differs')
    values = {}
    for path in sorted(source.rglob('*')):
        no_links(path)
        if path.is_file():
            values[path.relative_to(source).as_posix()] = (read(path), bool(path.stat().st_mode & 0o111))
    actual = records(values)
    require(actual == manifest['files'] and digest(canonical(actual)) == pin,
            'snapshot integrity failure; refusing altered or unexpected pin bytes')
    layout.validate(source)
    return source


def materialize(paths, pin, name, dependency=False):
    """Reuse the existing package/worker contract without executing source code."""
    import install as installer
    import registry
    source = verify(paths, pin)
    identity = load(source / '.agents-source.json')
    require(dependency or name not in identity.get('legacy_only_plugins', []),
            'retired workflow cannot start a new top-level invocation')
    info = layout.skill(source, name) if not dependency else None
    prefix = paths.packages / pin
    if info is not None and info['manifest'] is None:
        return {'package_root': str(info['file'].parent), 'skill_file': str(info['file']),
                'manifest_file': None, 'package_prefix': str(prefix), 'registry_root': str(paths.registry)}
    planned = installer.plan_install(source, name, immutable=True)
    version = prefix / name / planned['manifest']['version']
    if version.exists():
        receipt = load(version / installer.MANIFEST)
        require(receipt['files'] == planned['manifest']['files'] and receipt['plugin'] == name and
                receipt['agents_root'] == str(paths.registry), 'pinned package metadata differs from the source pin')
        registry.verify_package_files(version, receipt)
        require(receipt['package_digest'] == registry.package_digest(planned['manifest']), 'pinned package digest differs')
    else:
        installer.install(SimpleNamespace(source=str(source), plugin=name, prefix=str(prefix),
            agents_root=str(paths.registry), force=False, dry_run=False, immutable=True))
        receipt = load(version / installer.MANIFEST)
    expected_files = {r['path'] for r in planned['manifest']['files']} | {installer.MANIFEST}
    require(regular_files(version) == expected_files,
            'unexpected executable input in pinned package')
    _, assets = registry.declared_assets(source / 'plugins' / name, source / 'shared')
    if assets:
        expected = registry.create_bundle(paths.registry, receipt['installation_id'], name,
            receipt['version'], assets, registry.package_digest(planned['manifest']))
        require(expected['bundle_dir'] == receipt.get('bundle_dir') and
                expected['bundle_digest'] == receipt.get('bundle_digest'), 'worker bundle is not from this source pin')
        bundle = Path(expected['bundle_dir'])
        require(regular_files(bundle) ==
                {a[0] for a in assets} | {'manifest.json'}, 'unexpected input in pinned worker bundle')
    for path in version.rglob('*'):
        no_links(path)
        if path.is_dir():
            path.chmod(0o555)
    (version / installer.MANIFEST).chmod(0o444)
    version.chmod(0o555)
    registry.verify_package_files(version, receipt)
    entry = version / 'SKILL.md'
    if dependency and not entry.exists():
        entry = version / load(version / 'plugin.json')['entry']
    return {'package_root': str(version), 'skill_file': str(entry),
            'manifest_file': str(version / 'plugin.json'), 'package_prefix': str(prefix),
            'registry_root': str(paths.registry)}
