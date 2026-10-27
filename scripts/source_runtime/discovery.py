"""Per-skill native links. No credentials or provider settings are managed here."""
import os
from pathlib import Path
import uuid

from . import layout
from .io import load, no_links, relative, require, write_json


def current(path):
    no_links(path.parent)
    if path.is_symlink():
        return {'link': os.readlink(path)}
    require(not path.exists(), 'native skill collision; preserve existing destination: ' + str(path))
    return None


def receipt(paths):
    file = paths.control / 'discovery.json'
    result = load(file) if file.exists() else {'schema_version':1, 'links':[]}
    require(type(result.get('schema_version')) is int and result['schema_version'] == 1,
            'unsupported discovery receipt')
    return result


def plan(paths, candidate, live, previous_receipt=None):
    registry = load(Path(candidate) / 'discovery.json')
    require(registry.get('schema_version') == 1, 'unsupported discovery registry')
    names = layout.validate(candidate)['skills']
    desired = {}
    roots = set()
    ids = set()
    for provider in registry['providers']:
        require(provider['id'] not in ids, 'duplicate discovery provider')
        ids.add(provider['id'])
        require(provider['registration'] in ('link', 'shared'), 'unsupported discovery registration')
        if provider['registration'] == 'shared':
            require(set(provider) == {'id', 'registration'}, 'shared discovery cannot own native paths')
            continue
        require(set(provider) == {'id','registration','root'}, 'invalid native discovery fields')
        root = no_links(paths.home / relative(provider['root']))
        require(root.is_relative_to(paths.home) and root != paths.home / '.agents/skills',
                'native discovery root must be a separate home subdirectory')
        roots.add(root)
        for name in names:
            desired[str(root / name)] = str(Path(live) / 'skills' / name)
    previous = {row['path']:row['target'] for row in (previous_receipt or receipt(paths))['links']}
    changes = []
    for value in sorted(set(previous) | set(desired)):
        path = Path(value)
        require(path.is_absolute() and path.is_relative_to(paths.home), 'unsafe prior native discovery path')
        before = current(path)
        old = previous.get(value)
        if old is not None:
            require(before is None or before == {'link':old}, 'owned native skill was changed; reconcile explicitly: ' + value)
        elif before is not None:
            # A matching link without our receipt remains somebody else's file.
            require(False, 'unowned native skill link collision: ' + value)
        after = {'link':desired[value]} if value in desired else None
        if before != after:
            changes.append({'path':value, 'before':before, 'after':after})
    return {'changes':changes, 'receipt':{'schema_version':1,
        'links':[{'path':p,'target':t} for p,t in sorted(desired.items())]}}


def apply(paths, prepared, reverse=False):
    """Idempotent journal apply. Refuse anything other than recorded old/new."""
    for row in prepared['changes']:
        path = Path(row['path'])
        require(path.is_absolute() and path.is_relative_to(paths.home), 'unsafe journal discovery destination')
        before, after = (row['after'], row['before']) if reverse else (row['before'], row['after'])
        observed = current(path)
        require(observed == before or observed == after, 'native alias changed during apply; recovery stopped')
        if observed == after:
            continue
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if after is None:
            path.unlink()
        else:
            temporary = path.parent / ('.agents-link-' + str(uuid.uuid4()))
            try:
                temporary.symlink_to(after['link'], target_is_directory=True)
                os.replace(temporary, path)
            finally:
                if temporary.is_symlink():
                    temporary.unlink()
    if not reverse:
        write_json(paths.control / 'discovery.json', prepared['receipt'])
