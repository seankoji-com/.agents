#!/usr/bin/env python3
"""Check tracked library content and canonical skills; exclude ignored local state."""
import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

SKILLS = ('imps', 'plan', 'ape', 'babysitter', 'ralph', 'focus-group',
          'agent-tuneup', 'tests-omg', 'bug-report', 'unslop')
RETIRED = re.compile(r'agents-bootstrap|PKG/|(?:core|shared|plugins)/|bin/agents|'
                     r'scripts/(?:install|agents_bootstrap|source_runtime)|'
                     r'migration/|agents start|\.local/share/t3-plugins')
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
RETIRED_ROOTS = {'core', 'shared', 'plugins', 'bin', 'bench', 'conformance',
                 'migration', 'docs', 'overrides', 'roles', 'packaging'}


def check(root):
    errors = []
    try:
        tracked = subprocess.check_output(
            ['git', '-C', str(root), 'ls-files', '-z'], stderr=subprocess.DEVNULL
        ).decode().split('\0')
    except (OSError, subprocess.CalledProcessError):
        return ['library root must be a Git checkout']
    paths = {root / p for p in tracked if p and (root / p).is_file()}
    for name in SKILLS:
        folder = root / 'skills' / name
        entry = folder / 'SKILL.md'
        if not entry.is_file():
            errors.append(f'missing skill: {name}')
            continue
        paths.update(p for p in folder.rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts)
        text = entry.read_text(encoding='utf-8')
        front = re.match(r'\A---\n(.*?)\n---\n', text, re.S)
        metadata = front.group(1) if front else ''
        if not re.search(r'^name: ' + re.escape(name) + r'$', metadata, re.M):
            errors.append(f'{name}: missing/mismatched name')
        if not re.search(r'^description: [^\n]+$', metadata, re.M):
            errors.append(f'{name}: missing description')
        if len(text.split()) > 1500:
            errors.append(f'{name}: exceeds 1500 words')
        if name != 'unslop':
            for heading in ('## Triggers', '## Workflow', '## Outputs', '## Boundaries'):
                if heading not in text:
                    errors.append(f'{name}: missing {heading}')
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if Path(relative).parts[0] in RETIRED_ROOTS:
            errors.append(f'{relative}: retired source container')
        if path.is_symlink():
            errors.append(f'{relative}: library files must be self-contained, not symlinks')
            continue
        if path.suffix == '.md':
            text = path.read_text(encoding='utf-8')
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
        elif path.suffix == '.py' and relative.startswith('skills/'):
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
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = check(args.root.resolve())
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Ten standalone skills: metadata, budgets, links and helper imports pass.')
    return 0


if __name__ == '__main__':
    if sys.version_info < (3, 10):
        sys.exit('Python 3.10+ required')
    sys.exit(main())
