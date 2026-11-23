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
          'agent-tuneup', 'reremember', 'test-writer', 'raise-issue', 'ship',
          'think', 'review', 'choose-design', 'raise-pr',
          'implement', 'github-writing', 'hillclimb', 'backlog-burn', 'plan-report',
          'binaric', 'settle', 'ocr', 'new-skill', 'vote')
RETIRED = re.compile(r'agents-bootstrap|PKG/|(?:core|shared|plugins)/|bin/agents|'
                     r'scripts/(?:install|agents_bootstrap|source_runtime)|'
                     r'migration/|agents start|\.local/share/t3-plugins')
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
RETIRED_ROOTS = {'core', 'shared', 'plugins', 'bin', 'bench', 'conformance',
                 'migration', 'docs', 'overrides', 'roles', 'packaging'}
# A dispatched child reads one card instead of a skill and everything it links to.
CARDS = ('skills/review/references/assigned-reviewer.md',
         'skills/review/references/implementation-participant.md',
         'skills/ocr/references/ocr-watcher.md')
CARD_WORDS = 600
CATALOG_START = '<!-- skill-catalog:start -->'
CATALOG_END = '<!-- skill-catalog:end -->'
DOC_REVIEW = re.compile(r'<!-- skills-review: ([^\s]+) -->')
# Every description loads on every turn, so it stays short and reads as a selection rule.
DESCRIPTION_WORDS = 40
DESCRIPTION_CHARS = 250
# Quoted user phrases may use person words; an apostrophe inside a word does not end a quote.
QUOTED = re.compile(r'(?<!\w)".*?"(?!\w)|(?<!\w)\'.*?\'(?!\w)')
PERSON = re.compile(r'\b(?:I|you|your|this skill)\b', re.I)
SEQUENCE = re.compile(r'\bthen\b', re.I)
TRIGGER = re.compile(r'\bUse (?:when|for|at)\b|\bwhen (?:asked|the user)\b', re.I)
USER_INVOKED = re.compile(r'^disable-model-invocation: true$', re.M)
# A link in an entry says when to follow it; this list is the fixed test for that.
CONDITION = re.compile(r'\b(?:when|whenever|before|after|if|unless|during|once|while|for|to)\b',
                       re.I)
EVALS = 'references/trigger-evals.md'
EVAL_PROMPTS = 5
FENCE_OPEN = re.compile(r'[ \t]*(`{3,}|~{3,})')
# A paragraph, list item, table row or heading is one block; sentences never span blocks.
BLOCK = re.compile(r'\n[ \t]*\n|\n(?=[ \t]*(?:[-*+]|\d+[.)]|\||#+)[ \t])')


def strip_fences(text):
    """Drop fenced code. A fence closes on a bare run of its own character, at least as long."""
    kept, fence = [], None
    for line in text.split('\n'):
        match = FENCE_OPEN.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
            else:
                kept.append(line)
        elif (match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence)
              and not line[match.end():].strip()):
            fence = None
    return '\n'.join(kept)


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


def description_errors(name, description, user_invoked):
    """A description is a short selection rule, not a summary of the procedure."""
    errors = []
    if len(description.split()) > DESCRIPTION_WORDS:
        errors.append(f'{name}: description exceeds {DESCRIPTION_WORDS} words')
    if len(description) > DESCRIPTION_CHARS:
        errors.append(f'{name}: description exceeds {DESCRIPTION_CHARS} characters')
    words = {m.group(0).lower() for m in PERSON.finditer(QUOTED.sub('', description))}
    words |= {m.group(0).lower() for m in SEQUENCE.finditer(description)}
    for word in sorted(words):
        errors.append(f'{name}: description uses "{word}"')
    if not user_invoked and not TRIGGER.search(description):
        errors.append(f'{name}: model-invoked description lacks a trigger clause')
    return errors


def link_condition_errors(name, body):
    """Each local link in an entry sits in a sentence that says when to read it."""
    errors = []
    text = re.sub(r'^([ \t]*#+[ \t].*)$', r'\1\n', strip_fences(body), flags=re.M)
    for block in BLOCK.split(text):
        targets = []

        def hold(match):
            targets.append(match.group(1))
            return f'\0{len(targets) - 1}\0'

        # Swap links for placeholders first so link text cannot split a sentence.
        flat = LINK.sub(hold, re.sub(r'\s+', ' ', block))
        for sentence in re.split(r'(?<=[.!?])\s+', flat):
            local = [targets[int(i)] for i in re.findall(r'\0(\d+)\0', sentence)
                     if not urlsplit(targets[int(i)]).scheme]
            if local and not CONDITION.search(re.sub(r'\0\d+\0', ' ', sentence)):
                errors.extend(f'{name}: link without a reading condition: {t}' for t in local)
    return errors


def eval_errors(name, folder, names):
    """Model-invoked skills record prompts that should and should not select them."""
    path = folder / EVALS
    if not path.is_file():
        return [f'{name}: missing {EVALS}']
    sections = re.split(r'^## ', strip_fences(path.read_text(encoding='utf-8')), flags=re.M)[1:]
    headings = [section.split('\n', 1)[0].strip() for section in sections]
    errors = []
    for heading in ('Should fire', 'Should not fire'):
        if headings.count(heading) != 1:
            errors.append(f'{name}: {EVALS} needs one "{heading}" section')
            continue
        section = sections[headings.index(heading)]
        items = [item.strip() for item in re.findall(r'^\d+\. (.*)$', section, re.M)]
        if len(items) != EVAL_PROMPTS or not all(items):
            errors.append(f'{name}: {EVALS} needs {EVAL_PROMPTS} "{heading}" prompts')
            continue
        if heading == 'Should fire':
            continue
        for item in items:
            match = re.fullmatch(r'(.*\S) \(expect: ([\w:-]+)\)', item)
            if not match:
                errors.append(f'{name}: {EVALS} "{heading}" prompts must end with '
                              '(expect: <skill|none>)')
                break
            if match.group(2) == name:
                errors.append(f'{name}: {EVALS} near miss expects the skill under test')
            elif match.group(2) not in names and match.group(2) != 'none':
                errors.append(f'{name}: {EVALS} expects unknown skill: {match.group(2)}')
    return errors


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


def heading_anchors(text):
    """Return GitHub-style anchors for the library's Markdown headings."""
    anchors = set()
    for heading in re.findall(r'^#{1,6} (.+)$', text, re.M):
        slug = re.sub(r'[^\w -]', '', heading.lower()).replace(' ', '-')
        suffix = 0
        anchor = slug
        while anchor in anchors:
            suffix += 1
            anchor = f'{slug}-{suffix}'
        anchors.add(anchor)
    return anchors


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
    anchors = heading_anchors(text)
    for target in LINK.findall(text):
        if target.startswith('#') and unquote(target[1:]) not in anchors:
            errors.append(f'README.md: broken heading link: {target}')
    if (update or acknowledge) and not errors:
        readme.write_text(text, encoding='utf-8')
    return errors


def site_contract(root):
    """Keep the Pages catalog, install commands and source links in step with SKILLS."""
    page = root / 'site' / 'index.html'
    if not page.is_file():
        return ['site/index.html: missing Pages site']
    text = page.read_text(encoding='utf-8')
    rows = re.findall(r'<li class="skill" id="skill-([a-z0-9-]+)"[^>]*>(.*?)</li>',
                      text, re.S)
    listed = [name for name, _ in rows]
    errors = [f'site/index.html: duplicate skill: {name}'
              for name in sorted({n for n in listed if listed.count(n) > 1})]
    errors += [f'site/index.html: missing skill: {name}'
               for name in sorted(set(SKILLS) - set(listed))]
    errors += [f'site/index.html: unknown skill: {name}'
               for name in sorted(set(listed) - set(SKILLS))]
    for name, row in rows:
        hrefs = re.findall(r'<a\b[^>]*\bhref="([^"]+)"', row)
        definition = f'https://github.com/seankoji-com/.agents/blob/main/skills/{name}/SKILL.md'
        if definition not in hrefs:
            errors.append(f'site/index.html: missing GitHub definition link: {name}')
        if f'#install-{name}' not in hrefs or f'id="install-{name}"' not in row:
            errors.append(f'site/index.html: missing install link or target: {name}')
        command = re.search(r'<pre class="cmd"[^>]*>(.*?)</pre>', row, re.S)
        expected = f'npx skills add seankoji-com/.agents --skill {name}'
        if not command or html.unescape(re.sub(r'<[^>]+>', '', command[1])) != expected:
            errors.append(f'site/index.html: incorrect install command: {name}')
    for name in re.findall(r'--skill ([a-z0-9-]+)', text):
        if name not in SKILLS:
            errors.append(f'site/index.html: install command names unknown skill: {name}')
    for name in sorted(set(re.findall(r'href="#skill-([a-z0-9-]+)"', text)) - set(SKILLS)):
        errors.append(f'site/index.html: unknown related skill: {name}')
    # Every catalogued skill belongs to exactly one host-support tier.
    tiered = re.findall(r'<p class="chips">(.*?)</p>', text, re.S)
    grouped = [name for group in tiered
               for name in re.findall(r'href="#skill-([a-z0-9-]+)"', group)]
    errors += [f'site/index.html: skill in more than one tier: {name}'
               for name in sorted({n for n in grouped if grouped.count(n) > 1})]
    errors += [f'site/index.html: skill missing from a tier: {name}'
               for name in sorted(set(SKILLS) - set(grouped))]
    guide = root / 'site' / 'workflows.html'
    if not guide.is_file():
        return errors + ['site/workflows.html: missing workflow guide']
    text = guide.read_text(encoding='utf-8')
    for section in ('outcome', 'backlog', 'implement', 'issues'):
        body = re.search(rf'<section id="{section}"[^>]*>(.*?)</section>', text, re.S)
        if not body or '<figure class="workflow-map">' not in body[1]:
            errors.append(f'site/workflows.html: missing workflow diagram: {section}')
    linked = re.findall(r'/skills/([a-z0-9-]+)/|href="\./#skill-([a-z0-9-]+)"', text)
    for name in sorted({path or fragment for path, fragment in linked} - set(SKILLS)):
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
    entries = {path.parent.name for path in paths
               if path.name == 'SKILL.md' and path.parent.parent == root / 'skills'}
    for name in sorted(entries - set(SKILLS)):
        errors.append(f'unregistered skill: {name}; add it to SKILLS and update the README')
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
        user_invoked = bool(USER_INVOKED.search(metadata))
        if name in descriptions:
            errors.extend(description_errors(name, descriptions[name], user_invoked))
        if front:
            errors.extend(link_condition_errors(name, text[front.end():]))
        if not user_invoked:
            errors.extend(eval_errors(name, folder, SKILLS))
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
                elif parsed.fragment and dest.suffix == '.md' and dest.is_file():
                    anchors = heading_anchors(dest.read_text(encoding='utf-8'))
                    if unquote(parsed.fragment) not in anchors:
                        errors.append(f'{relative}: broken heading link: {target}')
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
