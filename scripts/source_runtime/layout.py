"""Canonical skills and data-only manifests. No source file generation."""
import json
from pathlib import Path
import re

from . import PROTOCOL
from .io import SourceError, load, read, require

NAME = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
SECRET = re.compile(r'(^|/)(\.env(?:\..*)?|.*\.(?:pem|key|p12)|id_(?:rsa|ed25519)|mcp\.json)$')


def scalar(text):
    text = text.strip()
    if text.startswith('"'):
        value = json.loads(text)
        require(isinstance(value, str), 'frontmatter values must be strings')
        return value
    if text.startswith("'"):
        require(text.endswith("'"), 'unterminated frontmatter string')
        return text[1:-1].replace("''", "'")
    require(text and not text.startswith(('{', '[', '&', '*', '!')), 'unsupported frontmatter scalar')
    return text


def frontmatter(raw):
    text = raw.decode('utf-8')
    require(text.startswith('---\n') and '\n---\n' in text[4:], 'skill needs portable frontmatter')
    header, body = text[4:].split('\n---\n', 1)
    result = {}
    parent = None
    folded = None
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if folded and line.startswith(' '):
            result[folded] += ' ' + line.strip()
            continue
        folded = None
        match = re.fullmatch(r'( *)([A-Za-z0-9_/-]+):(?: +(.*))?', line)
        require(match is not None, 'unsupported portable frontmatter line')
        indent, key, value = match.groups()
        target = result
        if indent:
            require(parent == 'metadata', 'only metadata may contain nested frontmatter')
            target = result[parent]
        else:
            parent = None
        require(key not in target, 'duplicate frontmatter field: ' + key)
        if value is None:
            require(not indent and key == 'metadata', 'unsupported frontmatter object')
            result[key] = {}
            parent = key
        elif value in ('>', '>-', '|', '|-'):
            require(not indent, 'multiline metadata is unsupported')
            target[key] = ''
            folded = key
        else:
            target[key] = scalar(value)
    require(set(result) <= {'name', 'description', 'license', 'compatibility', 'metadata', 'allowed-tools'},
            'nonportable skill frontmatter')
    require(NAME.fullmatch(result.get('name', '')) is not None and result.get('description'),
            'skill name and description are required')
    return result, body


def skill(root, name):
    require(NAME.fullmatch(name) is not None, 'invalid skill name')
    folder = Path(root) / 'skills' / name
    file = folder / 'SKILL.md'
    meta, body = frontmatter(read(file))
    require(meta['name'] == name, 'skill name differs from its directory')
    manifest_path = Path(root) / 'plugins' / name / 'plugin.json'
    manifest = load(manifest_path) if manifest_path.exists() else None
    if manifest is not None:
        require(manifest['name'] == name and manifest['entry'] in ('entry.md', 'SKILL.md'), 'skill/manifest identity mismatch')
        require(not any(key in manifest for key in ('description','short_description','argument_hint')),
                'skill frontmatter exclusively owns description and invocation hints')
    extra = [p for p in folder.rglob('*') if p.is_file() and p != file]
    metadata = meta.get('metadata', {})
    exempt = metadata.get('agents-bootstrap-exempt') == 'true'
    if exempt:
        require(manifest is None and not extra, 'bootstrap exemption requires exactly one prose SKILL.md')
    else:
        require(metadata.get('agents-bootstrap') == str(PROTOCOL), 'unsupported or missing skill bootstrap protocol')
        command = '"$HOME/.local/bin/agents" start ' + name
        require(command in body and 'pinned SKILL.md' in body, 'skill must reload its full pinned body before substantive work')
        require(not re.search(r'(?:python\S*|Read)\s+[^\n]*(?:~|\$HOME)/\.agents/(?:plugins|shared|scripts|core)', body),
                'skill helper reads must resolve through its pin, not live source')
    return {'name': name, 'file': file, 'metadata': meta, 'body': body,
            'manifest': manifest, 'manifest_file': manifest_path if manifest else None, 'exempt': exempt}


def validate(root):
    root = Path(root)
    identity = load(root / '.agents-source.json')
    require(type(identity.get('schema_version')) is int and identity['schema_version'] == 1,
            'unsupported source identity schema')
    require(identity.get('repository_id') == '1411719736' and type(identity.get('bootstrap_protocol')) is int and identity.get('bootstrap_protocol') == PROTOCOL,
            'unsupported repository identity or bootstrap protocol; self-install compatible infrastructure first')
    required = identity.get('required_skills', [])
    require(isinstance(required, list) and len(set(required)) == len(required), 'invalid required skill names')
    for name in required:
        skill(root, name)
    managed, foreign = [], []
    for file in sorted((root / 'skills').glob('*/SKILL.md')):
        try:
            meta, _ = frontmatter(read(file))
        except (SourceError, UnicodeError):
            if file.parent.name in required:
                raise
            foreign.append(file.parent.name)
            continue
        metadata = meta.get('metadata', {})
        if file.parent.name in required or 'agents-bootstrap' in metadata or 'agents-bootstrap-exempt' in metadata:
            skill(root, file.parent.name)
            managed.append(file.parent.name)
        else:
            foreign.append(file.parent.name)
    return {'identity': identity, 'skills': managed, 'foreign_skills': foreign}
