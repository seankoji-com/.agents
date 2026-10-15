"""Requirement contracts and their semantic hash.

Progress checkboxes are not part of the contract: ticking a box leaves the hash
unchanged, while any change to an ID, wording, kind or constraint changes it."""
from __future__ import annotations

import re
from pathlib import Path

from .errors import InvalidInput
from .fsutil import hash_value

KINDS = ('inspection', 'command', 'runtime', 'manual')
ID_PATTERN = re.compile(r'^[A-Z][A-Z0-9_-]+$')
_ITEM = re.compile(r'^\s*- \[[ xX]\]\s+(.+)$')
_EXPLICIT = re.compile(r'^\[([A-Z][A-Z0-9_-]+)\]\s+(.+)$')
_METHOD = re.compile(r'\s*\[verify:(inspection|command|runtime|manual)\]\s*')
_PROCESS = re.compile(r'^(Gates green|Persona panel reviewed|No merge conflicts|CI green on the PR)\b', re.I)


def parse_markdown(text: str) -> dict:
    """Read requirements from a '## Definition of done' checklist and constraints
    from a '## Global constraints' section."""
    section = ''
    requirements, constraints = [], []
    for line in text.splitlines():
        heading = re.match(r'^##\s+(.+)', line)
        if heading:
            section = heading.group(1).strip().lower()
            continue
        if section.startswith('definition of done'):
            item = _ITEM.match(line)
            if not item or _PROCESS.match(item.group(1)):
                continue
            value = item.group(1).strip()
            explicit = _EXPLICIT.match(value)
            if not explicit:
                raise InvalidInput('requirement_without_id',
                                   'every Definition of done item needs an [ID] prefix', {'line': value})
            wording = explicit.group(2)
            method = _METHOD.search(wording)
            requirements.append({
                'id': explicit.group(1),
                'text': _METHOD.sub(' ', wording).strip(),
                'kind': method.group(1) if method else 'inspection',
                'required': True,
            })
        elif section.startswith('global constraints'):
            stripped = line.strip()
            if stripped.startswith('- '):
                constraints.append(stripped[2:].strip())
    return {'requirements': requirements, 'constraints': constraints}


def normalise(requirements, constraints) -> dict:
    seen = set()
    clean = []
    for item in requirements:
        if not isinstance(item, dict) or not ID_PATTERN.match(str(item.get('id', ''))):
            raise InvalidInput('requirement_id', 'requirement IDs look like REQ-NAME', {'item': item})
        if item['id'] in seen:
            raise InvalidInput('duplicate_requirement', f'duplicate requirement ID {item["id"]}')
        seen.add(item['id'])
        kind = item.get('kind', 'inspection')
        if kind not in KINDS:
            raise InvalidInput('requirement_kind', f'kind must be one of {KINDS}', {'id': item['id']})
        text = str(item.get('text', '')).strip()
        if not text:
            raise InvalidInput('requirement_text', 'requirement text is empty', {'id': item['id']})
        clean.append({'id': item['id'], 'text': text, 'kind': kind, 'required': item.get('required', True) is not False})
    if not clean:
        raise InvalidInput('no_functional_requirements',
                           'add at least one observable requirement; process boxes do not count')
    return {'requirements': clean, 'constraints': [str(c).strip() for c in constraints if str(c).strip()]}


def contract_hash(contract: dict) -> str:
    return hash_value({'requirements': contract['requirements'], 'constraints': contract['constraints']})


def load_source(path: Path) -> dict:
    try:
        text = Path(path).read_text()
    except OSError as exc:
        raise InvalidInput('requirements_source', f'cannot read requirements source: {exc}') from exc
    parsed = parse_markdown(text)
    return normalise(parsed['requirements'], parsed['constraints'])


def current_contract(state: dict) -> dict:
    """The contract as it stands now: re-read from the source file when one is bound."""
    brief = state['brief']
    source = brief.get('requirements_source')
    if source:
        return load_source(Path(source))
    return {'requirements': brief['requirements'], 'constraints': brief['constraints']}
