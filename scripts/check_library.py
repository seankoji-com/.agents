#!/usr/bin/env python3
"""Check library source, canonical skills and README contracts; exclude ignored state."""
import argparse
import ast
import hashlib
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

SKILLS = ('babysitter', 'review-loop', 'challenge', 'focus-group',
          'agent-tuneup', 'test-writer', 'raise-issue', 'ship',
          'think', 'review', 'choose-design', 'raise-pr',
          'implement', 'github-writing', 'design-loop', 'backlog-burn')
RETIRED = re.compile(r'agents-bootstrap|PKG/|(?:core|shared|plugins)/|bin/agents|'
                     r'scripts/(?:install|agents_bootstrap|source_runtime)|'
                     r'migration/|agents start|\.local/share/t3-plugins')
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
# Skills stand alone, so the reviewer order is copied; every bold copy must match.
ORDER = re.compile(r'\*\*([^*,\n]+(?:, [^*,\n]+){3,})\*\*')
RETIRED_ROOTS = {'core', 'shared', 'plugins', 'bin', 'bench', 'conformance',
                 'migration', 'docs', 'overrides', 'roles', 'packaging'}
# A dispatched child reads one card instead of a skill and everything it links to.
CARDS = ('skills/review/references/assigned-reviewer.md',
         'skills/review/references/implementation-participant.md')
CARD_WORDS = 600
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


def mermaid_errors(label, diagrams, names):
    """Every Mermaid node annotated as a skill must name a registered skill."""
    errors = []
    for diagram in diagrams:
        nodes = re.findall(r'\w+\["([^"\n]+)"\]:::skill(?![\w-])', diagram)
        if diagram.count(':::skill') != len(nodes):
            errors.append(f'{label}: malformed Mermaid skill node')
        for node in nodes:
            name = node.split('<br/>', 1)[0]
            if name not in names:
                errors.append(f'{label}: unknown Mermaid skill: {name}')
    return errors


def local_links(path):
    """Resolve the relative Markdown links in one file to existing .md files."""
    found = set()
    for target in LINK.findall(path.read_text(encoding='utf-8')):
        parsed = urlsplit(target)
        if parsed.scheme or not parsed.path:
            continue
        dest = (path.parent / unquote(parsed.path)).resolve()
        if dest.suffix == '.md' and dest.is_file():
            found.add(dest)
    return found


def load_stats(root):
    """Words an agent reads per skill: the entry, its own folder, and every link followed."""
    skills = (root / 'skills').resolve()
    rows = []
    for name in sorted(SKILLS):
        entry = skills / name / 'SKILL.md'
        if not entry.is_file():
            continue
        seen, stack = {entry}, [entry]
        while stack:
            for dest in local_links(stack.pop()):
                if dest not in seen and skills in dest.parents:
                    seen.add(dest)
                    stack.append(dest)
        words = {path: len(path.read_text(encoding='utf-8').split()) for path in seen}
        own = sum(count for path, count in words.items() if skills / name in path.parents)
        rows.append((name, words[entry], own, sum(words.values()), len(seen)))
    return rows


def card_contract(root):
    """Role cards are the whole reading list for a child agent: short and link-free."""
    errors = []
    for relative in CARDS:
        path = root / relative
        if not path.is_file():
            errors.append(f'{relative}: missing role card')
            continue
        text = path.read_text(encoding='utf-8')
        if len(text.split()) > CARD_WORDS:
            errors.append(f'{relative}: role card exceeds {CARD_WORDS} words')
        if LINK.search(text):
            errors.append(f'{relative}: role card must not link to other files')
    return errors


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

    errors.extend(mermaid_errors(
        'README.md', re.findall(r'```mermaid\n(.*?)\n```', text, re.S), descriptions))
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


def site_contract(root):
    """Keep the Pages site's skill list and install commands in step with SKILLS."""
    page = root / 'site' / 'index.html'
    if not page.is_file():
        return ['site/index.html: missing Pages site']
    text = page.read_text(encoding='utf-8')
    listed = re.findall(r'\{ name: "([a-z0-9-]+)", group:', text)
    errors = [f'site/index.html: duplicate skill: {name}'
              for name in sorted({n for n in listed if listed.count(n) > 1})]
    errors += [f'site/index.html: missing skill: {name}'
               for name in sorted(set(SKILLS) - set(listed))]
    errors += [f'site/index.html: unknown skill: {name}'
               for name in sorted(set(listed) - set(SKILLS))]
    for name in re.findall(r'--skill ([a-z0-9-]+)', text):
        if name not in SKILLS:
            errors.append(f'site/index.html: install command names unknown skill: {name}')
    for array in re.findall(r'uses: \[([^\]]*)\]', text):
        for name in re.findall(r'"([^"]+)"', array):
            if name not in SKILLS:
                errors.append(f'site/index.html: unknown related skill: {name}')
    for name in re.findall(r'^\s*\["[^"]+", "([^"]+)"\],$', text, re.M):
        if name not in SKILLS:
            errors.append(f'site/index.html: picker names unknown skill: {name}')
    guide = root / 'site' / 'workflows.html'
    if not guide.is_file():
        return errors + ['site/workflows.html: missing workflow guide']
    text = guide.read_text(encoding='utf-8')
    diagrams = [html.unescape(body) for body in
                re.findall(r'<pre class="mermaid">(.*?)</pre>', text, re.S)]
    if not diagrams:
        errors.append('site/workflows.html: missing Mermaid diagrams')
    errors += mermaid_errors('site/workflows.html', diagrams, SKILLS)
    for name in re.findall(r'/skills/([a-z0-9-]+)/', text):
        if name not in SKILLS:
            errors.append(f'site/workflows.html: links unknown skill: {name}')
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
    errors.extend(site_contract(root))
    errors.extend(card_contract(root))
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
                # pstack's public repository name overlaps a retired local folder.
                local_text = re.sub(r'https://github\.com/cursor/plugins/[^\s<>)]+', '', line)
                if RETIRED.search(local_text):
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
    parser.add_argument('--stats', action='store_true',
                        help='print the words each skill loads, then exit')
    args = parser.parse_args()
    if args.stats:
        print(f'{"skill":<16}{"entry":>7}{"own folder":>12}{"all links":>11}{"files":>7}')
        for name, entry, own, closure, files in load_stats(args.root.resolve()):
            print(f'{name:<16}{entry:>7}{own:>12}{closure:>11}{files:>7}')
        print('Words, not tokens. "all links" is the cost of following every link; '
              f'a child reading a role card loads at most {CARD_WORDS}.')
        return 0
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
