#!/usr/bin/env python3
"""Check library source, canonical skills and README contracts; exclude ignored state."""
import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

SKILLS = ('babysitter', 'review-loop', 'challenge', 'focus-group',
          'agent-tuneup', 'test-writer', 'raise-issue', 'unslop', 'ship',
          'grilling', 'ketchup', 'bro', 'review', 'design-chooser', 'raise-pr',
          'agent-docs', 'implement')
RETIRED = re.compile(r'agents-bootstrap|PKG/|(?:core|shared|plugins)/|bin/agents|'
                     r'scripts/(?:install|agents_bootstrap|source_runtime)|'
                     r'migration/|agents start|\.local/share/t3-plugins')
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
# Skills stand alone, so the reviewer order is copied; every bold copy must match.
ORDER = re.compile(r'\*\*([^*,\n]+(?:, [^*,\n]+){3,})\*\*')
RETIRED_ROOTS = {'core', 'shared', 'plugins', 'bin', 'bench', 'conformance',
                 'migration', 'docs', 'overrides', 'roles', 'packaging'}
CATALOG_START = '<!-- skill-catalog:start -->'
CATALOG_END = '<!-- skill-catalog:end -->'
DOC_REVIEW = re.compile(r'<!-- skills-review: ([^\s]+) -->')


def description_value(value):
    """Read the single-line scalar format used by skill descriptions."""
    if not value or value[0] in '|>':
        raise ValueError('description must be a single-line string')
    if value.startswith('"'):
        value = json.loads(value)
    elif value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise ValueError('unterminated quoted description')
        value = value[1:-1].replace("''", "'")
    if not value.strip() or '\n' in value or '\r' in value:
        raise ValueError('description must be a single-line string')
    return value


def readme_contract(root, descriptions, paths, update=False, acknowledge=False):
    """Check generated facts and require a docs review after instruction changes."""
    readme = root / 'README.md'
    if not readme.is_file() or readme.is_symlink():
        return ['README.md: missing regular file']
    text = readme.read_text(encoding='utf-8')
    if text.count(CATALOG_START) != 1 or text.count(CATALOG_END) != 1:
        return ['README.md: expected one skill-catalog marker pair']
    start = text.index(CATALOG_START) + len(CATALOG_START)
    end = text.index(CATALOG_END)
    if start > end:
        return ['README.md: skill-catalog markers are reversed']
    rows = ['| Skill | When to use it |', '| --- | --- |']
    for name in sorted(descriptions):
        description = descriptions[name].replace('|', r'\|')
        rows.append(f'| [{name}](skills/{name}/SKILL.md) | {description} |')
    catalog = '\n\n' + '\n'.join(rows) + '\n\n'
    errors = []
    if update:
        text = text[:start] + catalog + text[end:]
    elif text[start:end] != catalog:
        errors.append('README.md: stale skill catalog; review the docs, then run '
                      'scripts/check_library.py --update-readme --acknowledge-docs')

    # Use the Git source set, including references but excluding ignored notes.
    # Normalize line endings so checkouts on different platforms agree.
    digest = hashlib.sha256()
    sources = []
    for path in sorted(paths):
        relative = path.relative_to(root)
        if (len(relative.parts) >= 3 and relative.parts[0] == 'skills'
                and relative.parts[1] in descriptions and path.suffix == '.md'):
            sources.append(path)
    for path in sources:
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(path.read_text(encoding='utf-8').encode() + b'\0')
    receipt = digest.hexdigest()
    reviews = list(DOC_REVIEW.finditer(text))
    if len(reviews) != 1:
        return errors + ['README.md: expected one skills-review receipt']
    if acknowledge:
        text = DOC_REVIEW.sub(f'<!-- skills-review: {receipt} -->', text)
    elif reviews[0].group(1) != receipt:
        errors.append('README.md: skill instructions changed; review prose and diagrams, '
                      'then run scripts/check_library.py --update-readme --acknowledge-docs')

    for diagram in re.findall(r'```mermaid\n(.*?)\n```', text, re.S):
        nodes = re.findall(r'\w+\["([^"\n]+)"\]:::skill(?![\w-])', diagram)
        if diagram.count(':::skill') != len(nodes):
            errors.append('README.md: malformed Mermaid skill node')
        for label in nodes:
            name = label.split('<br/>', 1)[0]
            if name not in descriptions:
                errors.append(f'README.md: unknown Mermaid skill: {name}')
    anchors = set()
    for heading in re.findall(r'^#{1,6} (.+)$', text, re.M):
        slug = re.sub(r'[^\w -]', '', heading.lower()).replace(' ', '-')
        suffix = 0
        anchor = slug
        while anchor in anchors:
            suffix += 1
            anchor = f'{slug}-{suffix}'
        anchors.add(anchor)
    for target in LINK.findall(text):
        if target.startswith('#') and unquote(target[1:]) not in anchors:
            errors.append(f'README.md: broken heading link: {target}')
    if (update or acknowledge) and not errors:
        readme.write_text(text, encoding='utf-8')
    return errors


def check(root, update_readme=False, acknowledge_docs=False):
    errors = []
    try:
        tracked = subprocess.check_output(
            ['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others',
             '--exclude-standard'], stderr=subprocess.DEVNULL
        ).decode().split('\0')
    except (OSError, subprocess.CalledProcessError):
        return ['library root must be a Git checkout']
    paths = {root / p for p in tracked
             if p and not p.startswith('skills/synced/') and (root / p).is_file()}
    entries = {Path(p).parts[1] for p in tracked
               if len(Path(p).parts) == 3 and Path(p).parts[0] == 'skills'
               and Path(p).name == 'SKILL.md' and Path(p).parts[1] != 'synced'}
    for name in sorted(entries - set(SKILLS)):
        errors.append(f'unregistered skill: {name}; add it to SKILLS and update the README')
    orders = {}
    descriptions = {}
    for name in SKILLS:
        folder = root / 'skills' / name
        entry = folder / 'SKILL.md'
        if not entry.is_file():
            errors.append(f'missing skill: {name}')
            continue
        text = entry.read_text(encoding='utf-8')
        front = re.match(r'\A---\n(.*?)\n---\n', text, re.S)
        metadata = front.group(1) if front else ''
        if not re.search(r'^name: ' + re.escape(name) + r'$', metadata, re.M):
            errors.append(f'{name}: missing/mismatched name')
        if not re.search(r'^description: [^\n]+$', metadata, re.M):
            errors.append(f'{name}: missing description')
        else:
            value = re.search(r'^description: ([^\n]+)$', metadata, re.M).group(1)
            try:
                descriptions[name] = description_value(value)
            except (ValueError, TypeError):
                errors.append(f'{name}: invalid single-line description')
        if len(text.split()) > 1500:
            errors.append(f'{name}: exceeds 1500 words')
        if not front or not text[front.end():].strip():
            errors.append(f'{name}: missing instructions')
    if len(descriptions) == len(SKILLS):
        errors.extend(readme_contract(root, descriptions, paths, update_readme, acknowledge_docs))
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if Path(relative).parts[0] in RETIRED_ROOTS:
            errors.append(f'{relative}: retired source container')
        if path.is_symlink():
            errors.append(f'{relative}: library files must be self-contained, not symlinks')
            continue
        if path.suffix == '.md':
            text = path.read_text(encoding='utf-8')
            if not relative.startswith('skills/synced/'):
                for order in ORDER.findall(text):
                    orders.setdefault(order, []).append(relative)
            for number, line in enumerate(text.splitlines(), 1):
                if RETIRED.search(line):
                    errors.append(f'{relative}:{number}: retired dependency')
            for target in LINK.findall(text):
                parsed = urlsplit(target)
                if parsed.scheme or not parsed.path:
                    continue
                dest = (path.parent / unquote(parsed.path)).resolve()
                if not dest.is_relative_to(root.resolve()) or not dest.exists():
                    errors.append(f'{relative}: broken/escaping link {target}')
        elif relative.startswith('skills/') and (
                path.suffix == '.py' or
                path.read_bytes().startswith(b'#!/usr/bin/env python3\n')):
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except SyntaxError:
                errors.append(f'{relative}: invalid Python syntax')
                continue
            for node in ast.walk(tree):
                imports = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                           else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                for module in imports:
                    if module.split('.')[0] not in sys.stdlib_module_names:
                        errors.append(f'{relative}: non-stdlib import {module}')
    if len(orders) > 1:
        found = '; '.join(f'{order} in {", ".join(sorted(files))}'
                          for order, files in sorted(orders.items()))
        errors.append(f'reviewer order differs: {found}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--update-readme', action='store_true', help='regenerate the skill catalog')
    parser.add_argument('--acknowledge-docs', action='store_true',
                        help='record that prose and diagrams were reviewed against current skills')
    args = parser.parse_args()
    errors = check(args.root.resolve(), args.update_readme, args.acknowledge_docs)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'{len(SKILLS)} standalone skills: metadata, budgets, links, README and helper imports pass.')
    return 0


if __name__ == '__main__':
    if sys.version_info < (3, 10):
        sys.exit('Python 3.10+ required')
    sys.exit(main())
