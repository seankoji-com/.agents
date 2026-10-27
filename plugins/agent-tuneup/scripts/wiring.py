#!/usr/bin/env python3
"""Read-only central wiring coverage. Evidence binding never proves native loading."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import importlib.util

_spec = importlib.util.spec_from_file_location('tuneup_agent_inventory', Path(__file__).with_name('agent_inventory.py'))
agent_inventory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_inventory)

SURFACES = ('global-rules', 'skills', 'permissions', 'mcp', 'roles', 'orchestration',
            'repository-entrypoints', 'worktree-bootstrap', 'lazy-context', 'discovery')
STATES = {'configured', 'unknown', 'unsupported', 'intentional-difference'}
RETIRED = {'hatch-pet', 't3-hatch-pet', 'sync-harness-permissions',
           't3-sync-harness-permissions'}


def is_alias(path):
    # Python 3.11 lacks Path.is_junction(). Windows exposes junctions and other
    # reparse points through lstat file attributes; treat all of them as aliases.
    info = path.lstat()
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))


def read_file(path):
    """Explicit read aliases are allowed; devices and FIFOs are not."""
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('unsafe_evidence')
        return stream.read()


def absolute(value):
    if not isinstance(value, str):
        raise ValueError('invalid_wiring_path')
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('invalid_wiring_path')
    return path


def evidence_state(items):
    if not isinstance(items, list):
        raise ValueError('invalid_wiring_evidence')
    if not items:
        return 'unknown'
    validated = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
            raise ValueError('invalid_wiring_evidence')
        path = absolute(item['path'])
        expected = item['sha256']
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('invalid_wiring_evidence')
        validated.append((path, expected))
    for path, expected in validated:
        try:
            if hashlib.sha256(read_file(path)).hexdigest() != expected:
                return 'stale'
        except (OSError, ValueError):
            return 'unreadable'
    return 'bound'


def skill_receipts(entry):
    """Describe recognized owners without adopting or modifying any files."""
    receipts = []
    source = source_skill_owner(entry)
    if source is not None:
        return [source]
    for marker, owner in (('.agents-skill.json', 'agents'), ('.t3-plugins-skill.json','t3-plugins'),
                          ('.dotfiles-skill.json', 'dotfiles')):
        path = entry / marker
        try:
            path.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            receipts.append({'owner': owner, 'status': 'invalid'})
            continue
        status = 'invalid'
        try:
            receipt = json.loads(read_file(path))
            if not isinstance(receipt, dict) or type(receipt.get('schema_version')) is not int:
                raise ValueError('invalid_receipt')
            if receipt['schema_version'] != 1:
                receipts.append({'owner': owner, 'status': 'unsupported'})
                continue
            if receipt.get('name') != entry.name:
                raise ValueError('invalid_receipt')
            files = receipt.get('files', {})
            if not isinstance(files, dict):
                raise ValueError('invalid_receipt')
            files = dict(files)
            if owner in ('agents','t3-plugins'):
                if not set(files) <= {'agents/openai.yaml'}:
                    raise ValueError('invalid_receipt')
                files['SKILL.md'] = receipt.get('sha256')
            if 'SKILL.md' not in files:
                raise ValueError('invalid_receipt')
            for name, expected in files.items():
                if (not isinstance(name, str) or not name or '\\' in name or ':' in name
                        or any(part in {'', '.', '..'} for part in name.split('/'))
                        or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
                    raise ValueError('invalid_receipt')
            status = 'verified'
            for name, expected in files.items():
                if not (entry / name).resolve().is_relative_to(entry.resolve()):
                    raise ValueError('invalid_receipt')
                try:
                    if hashlib.sha256(read_file(entry / name)).hexdigest() != expected:
                        status = 'modified'
                except FileNotFoundError:
                    status = 'modified'
        except (OSError, ValueError, TypeError):
            status = 'invalid'
        receipts.append({'owner': owner, 'status': status})
    return receipts or [{'owner': 'unmanaged', 'status': 'unmanaged'}]


def source_skill_owner(entry):
    """Describe protected source/link ownership without hashing editable bodies."""
    recognized = False
    try:
        resolved = entry.resolve(strict=True)
        if not resolved.is_dir() or resolved.parent.name != 'skills':
            return None
        root = resolved.parent.parent
        identity_path = root/'.agents-source.json'
        if not identity_path.is_file():
            return None
        control = Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'agents/control'
        marker_path = control/'cutover.json'
        if not marker_path.is_file():
            return None
        recognized = True
        if any(path.is_symlink() for path in (marker_path,*marker_path.parents,identity_path,*identity_path.parents)):
            raise ValueError('linked_source_identity')
        marker = json.loads(read_file(marker_path))
        identity = read_file(identity_path)
        value = json.loads(identity)
        if (marker.get('schema_version') != 1 or marker.get('phase') != 'active' or
                marker.get('source_root') != str(root) or marker.get('repository_id') != '1411719736' or
                value.get('schema_version') != 1 or value.get('repository_id') != '1411719736' or
                marker.get('identity_sha256') != hashlib.sha256(identity).hexdigest()):
            return {'owner':'agents-source','status':'invalid'}
        header = read_file(resolved/'SKILL.md').decode().split('\n---\n',1)[0]
        if not re.search(r'(?m)^  agents-bootstrap(?:-exempt)?: *[\"\']?(?:1|true)[\"\']? *$',header):
            return None
        if entry.absolute() != resolved:
            receipt = json.loads(read_file(control/'discovery.json'))
            if not any(row.get('path') == str(entry.absolute()) and row.get('target') == str(resolved)
                       for row in receipt.get('links',[])):
                return None
        return {'owner':'agents-source','status':'identity-bound'}
    except (OSError,ValueError,TypeError,KeyError,RuntimeError):
        return {'owner':'agents-source','status':'invalid'} if recognized else None


def skill_inventory(shared, providers, add):
    """Count only immediate skill entries. Never walk vendor trees or run launchers."""
    roots = [(None, absolute(shared))] if shared else []
    for index, provider in enumerate(providers):
        supplied = provider.get('skill_roots', [])
        if not isinstance(supplied, list):
            raise ValueError('invalid_skill_roots')
        roots.extend((index, absolute(path)) for path in supplied)
    rows, shared_seen = [], set()
    seen = {index: set() for index in range(len(providers))}
    for number, (provider_index, root) in enumerate(roots):
        location = f'wiring.skill_roots[{number}]'
        row = {'root': number, 'provider': provider_index, 'skills': 0, 'aliases': 0,
               'receipt_owned': 0, 'local_or_vendor': 0, 'retired_skills': 0,
               'entries': [], 'status': 'observed'}
        try:
            entries = sorted(root.iterdir())
            for entry in entries:
                # A broken retired alias must still be reported.
                if entry.name in RETIRED:
                    row['retired_skills'] += 1
                    add('retired_skill_present', location)
                receipts = skill_receipts(entry)
                if not (entry / 'SKILL.md').is_file() and receipts[0]['status'] == 'unmanaged':
                    continue
                row['skills'] += 1
                alias = is_alias(entry) or is_alias(root)
                row['aliases'] += int(alias)
                row['entries'].append({'skill': row['skills'] - 1, 'receipts': receipts})
                owned = all(receipt['status'] in ('verified','identity-bound') for receipt in receipts)
                row['receipt_owned'] += int(owned)
                row['local_or_vendor'] += int(receipts[0]['status'] == 'unmanaged')
                for receipt in receipts:
                    if receipt['status'] not in {'verified', 'identity-bound', 'unmanaged'}:
                        add('skill_receipt_' + receipt['status'], location + f'.skills[{row["skills"] - 1}]')
                try:
                    identity = str(entry.resolve())
                except (OSError, RuntimeError):
                    add('skill_entry_unresolvable', location + f'.skills[{row["skills"] - 1}]')
                    continue
                if provider_index is None:
                    if identity in shared_seen and any(p.get('reads_shared_skills') is True for p in providers):
                        add('duplicate_skill_discovery', location)
                    shared_seen.add(identity)
                else:
                    effective = seen[provider_index]
                    if (identity in effective or (providers[provider_index].get('reads_shared_skills') is True
                                                 and identity in shared_seen)):
                        add('duplicate_skill_discovery', location)
                    effective.add(identity)
                if provider_index is not None and shared:
                    shared_entry = absolute(shared) / entry.name
                    if shared_entry.is_dir():
                        # Providers reading the shared root need no individual aliases.
                        if providers[provider_index].get('reads_shared_skills') is True:
                            add('redundant_skill_alias' if alias else 'provider_skill_copy', location)
                        elif not alias:
                            add('provider_skill_copy', location)
        except OSError:
            row['status'] = 'unreadable'
            add('skill_root_unreadable', location)
        rows.append(row)
    return rows


def inspect(catalog, inventory, private=None):
    """All catalog rows and required surfaces remain visible, including missing input.

    Surface states/reasons are operator observations backed by file digests. This
    verifies coverage and freshness, not the truth of native runtime assertions.
    """
    if (not isinstance(inventory, dict) or type(inventory.get('version', 1)) is not int
            or inventory.get('version', 1) not in {1, 2}):
        raise ValueError('invalid_wiring_inventory')
    version = inventory.get('version', 1)
    if version == 1 and (set(inventory) & {'role_roots', 'role_evidence'} or any(
            isinstance(p, dict) and set(p) & {'agent_roots', 'agent_configs', 'ownership_receipts',
                'caller_references', 'assessments', 'read_paths', 'adapter'}
            for p in inventory.get('providers', []))):
        raise ValueError('mixed_wiring_versions')
    catalog_ids = [p['providerInstanceId'] for p in catalog['providers']]
    supplied = inventory.get('providers', [])
    if not isinstance(supplied, list):
        raise ValueError('invalid_wiring_inventory')
    if any(not isinstance(p, dict) or not isinstance(p.get('provider_instance_id'), str) for p in supplied):
        raise ValueError('invalid_wiring_inventory')
    ids = [p['provider_instance_id'] for p in supplied]
    if len(set(ids)) != len(ids) or set(ids) - set(catalog_ids):
        raise ValueError('invalid_wiring_inventory')
    indexed = dict(zip(ids, supplied))
    ordered = [indexed.get(ident, {}) for ident in catalog_ids]
    findings = []

    def add(code, location):
        finding = {'code': code, 'location': location}
        if finding not in findings:
            findings.append(finding)

    authorities = inventory.get('authorities', {})
    if not isinstance(authorities, dict) or set(authorities) - set(SURFACES):
        raise ValueError('invalid_wiring_authorities')
    authority_rows = []
    for surface in SURFACES:
        state = evidence_state(authorities.get(surface, []))
        authority_rows.append({'surface': surface, 'evidence': state})
        if state != 'bound':
            add('central_authority_' + state, 'wiring.authorities.' + surface)
    rows = []
    for index, provider in enumerate(ordered):
        surfaces = provider.get('surfaces', {})
        if not isinstance(surfaces, dict) or set(surfaces) - set(SURFACES):
            raise ValueError('invalid_wiring_surfaces')
        cells = []
        for surface in SURFACES:
            cell = surfaces.get(surface, {})
            state = cell.get('state', 'unknown')
            if state not in STATES:
                raise ValueError('invalid_wiring_state')
            evidence = evidence_state(cell.get('evidence', []))
            reason = isinstance(cell.get('reason'), str) and bool(cell['reason'].strip())
            location = f'wiring.providers[{index}].{surface}'
            if state == 'unknown' or evidence != 'bound' or (state != 'configured' and not reason):
                add('wiring_surface_unverified', location)
            cells.append({'surface': surface, 'declared': state, 'evidence': evidence})
        runtime_version = provider.get('runtime_version')
        if runtime_version is not None and (not isinstance(runtime_version, str) or not runtime_version.strip()):
            raise ValueError('invalid_runtime_version')
        if runtime_version is None:
            add('runtime_version_unknown', f'wiring.providers[{index}]')
        rows.append({'provider': index, 'version': 'observed' if runtime_version else 'unknown', 'surfaces': cells})
    if not inventory.get('shared_skills'):
        add('shared_skills_unknown', 'wiring.shared_skills')
    skills = skill_inventory(inventory.get('shared_skills'), ordered, add)
    agents = {'version': 1, 'coverage': 'unavailable', 'normalization': 'unavailable',
              'reason': 'wiring v1 has no detailed agent/role evidence', 'fatal': False}
    if version == 2:
        agents, plan = agent_inventory.inspect(catalog, inventory)
        if private is not None:
            private['agent_plan'] = plan
        for index, row in enumerate(rows):
            for cell in row['surfaces']:
                if cell['surface'] == 'orchestration':
                    cell['agent_inventory'] = agents['providers'][index]
                elif cell['surface'] == 'roles':
                    cell['role_inventory'] = agents['roles']
        for finding in agents['findings']:
            add(finding['code'], finding['location'])
    return {'version': version, 'providers': rows, 'authorities': authority_rows, 'skill_roots': skills,
            'agent_inventory': agents,
            'findings': findings, 'writes': 0, 'loading': 'unverified',
            'coverage': 'declared_paths_only', 'semantics': 'operator_observations_not_runtime_proof'}
