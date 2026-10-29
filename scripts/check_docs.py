#!/usr/bin/env python3
"""Check local Markdown links, catalog coverage, and portable entry budgets."""
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent

# A closing fence uses the opening character at least as many times (CommonMark).
FENCE = re.compile(r'^[ \t]*((`){3,}|(~){3,})[^\n]*\n.*?^[ \t]*\1(?:\2|\3)*[ \t]*$', re.S | re.M)
CODE_SPAN = re.compile(r'(`+)[^`]*?\1')
LIST_ITEM = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s')
IMAGE = re.compile(r'!\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)')
LINK = re.compile(r'\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)')
HTML_TARGET = re.compile(r'<(?:a|img)\b[^>]*?\b(?:href|src)=["\']([^"\']+)["\']', re.I)
REFERENCE = re.compile(r'^ {0,3}\[[^\]]+\]:[ \t]*<?(\S+?)>?(?:[ \t]+["\'(].*)?$', re.M)
ATX_HEADING = re.compile(r'^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$', re.M)
SETEXT_HEADING = re.compile(r'^ {0,3}(\S[^\n]*)\n {0,3}(?:=+|-+)[ \t]*$', re.M)
HTML_ID = re.compile(r'<[a-zA-Z][^>]*?\b(?:id|name)=["\']([^"\']+)["\']', re.I)
ATTR_ID = re.compile(r'\{:?\s*#([^\s}]+)[^}]*\}\s*$')


def strip_code(text: str) -> str:
    """Drop fenced blocks, indented code blocks, and inline code spans."""
    text = FENCE.sub('', text)
    lines, kept, previous_blank, in_block, before = text.split('\n'), [], True, False, ''
    for line in lines:
        indented = line.startswith(('    ', '\t'))
        if in_block and (indented or not line.strip()):
            continue
        in_block = False
        if indented and previous_blank and not LIST_ITEM.match(before):
            in_block = True
            continue
        if line.strip():
            previous_blank, before = False, line
        else:
            previous_blank = True
        kept.append(line)
    return CODE_SPAN.sub('', '\n'.join(kept))


def slugify(value: str) -> str:
    """python-markdown's toc slug: ASCII fold, drop non-word characters, hyphenate spaces."""
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    return re.sub(r'[-\s]+', '-', value)


def heading_text(raw: str) -> str:
    raw = CODE_SPAN.sub(lambda m: m.group(0).strip('`'), raw)
    raw = IMAGE.sub('', raw)
    raw = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', raw)
    raw = re.sub(r'<[^>]+>', '', raw)
    return raw.replace('*', '')


def anchors(text: str) -> set:
    """Every fragment a Markdown page answers to: heading slugs (with python-markdown's
    `_n` suffix for repeats), attr_list ids, and raw HTML id/name attributes."""
    found, seen = set(), {}
    stripped = FENCE.sub('', text)
    headings = [m.group(1) for m in ATX_HEADING.finditer(stripped)]
    headings += [m.group(1) for m in SETEXT_HEADING.finditer(stripped) if not LIST_ITEM.match(m.group(1))]
    for raw in headings:
        explicit = ATTR_ID.search(raw)
        if explicit:
            found.add(explicit.group(1))
            raw = raw[:explicit.start()]
        slug = slugify(heading_text(raw))
        if slug in seen:
            seen[slug] += 1
            slug = f'{slug}_{seen[slug]}'
        else:
            seen[slug] = 0
        found.add(slug)
    found.update(HTML_ID.findall(strip_code(text)))  # an id shown in a code sample is not an anchor
    return found


def link_targets(text: str) -> list:
    """Every local-looking target in a page, from Markdown, badges, raw HTML, and reference definitions."""
    body = strip_code(text)
    targets = IMAGE.findall(body)
    body = IMAGE.sub('img', body)  # keeps [![badge](x)](target) checkable as a plain link
    targets += LINK.findall(body)
    targets += HTML_TARGET.findall(body)
    targets += REFERENCE.findall(body)
    return targets


def check_page(path: Path, root: Path, anchor_cache: dict) -> list:
    errors = []
    text = path.read_text()
    for target in link_targets(text):
        if target.startswith('PKG/'):
            continue  # a plugin's installed-snapshot placeholder, not a file in the tree
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or target.startswith(('{{', '<')):
            continue
        if not parsed.path and not parsed.fragment:
            continue
        resolved = (path if not parsed.path else path.parent / unquote(parsed.path)).resolve()
        if not resolved.is_relative_to(root.resolve()):
            errors.append(f'{path.relative_to(root)}: link leaves the repository {target}')
            continue
        if not resolved.exists():
            errors.append(f'{path.relative_to(root)}: missing link {target}')
            continue
        if parsed.fragment and resolved.suffix == '.md':
            if resolved not in anchor_cache:
                anchor_cache[resolved] = anchors(resolved.read_text())
            if unquote(parsed.fragment) not in anchor_cache[resolved]:
                errors.append(f'{path.relative_to(root)}: missing anchor {target}')
    return errors


def check(root=ROOT):
    errors = []
    # Direct skill roots own their references; nested vendor stores are independent.
    skill_pages = [page for entry in (root / 'skills').glob('*/SKILL.md')
                   for page in entry.parent.rglob('*.md')]
    pages = [*root.glob('*.md'), *(root / 'docs').rglob('*.md'), *(root / 'plugins').rglob('*.md'),
             *skill_pages, *(root / 'roles').rglob('*.md'), *(root / 'references').rglob('*.md')]
    anchor_cache = {}
    for path in sorted(pages):
        errors.extend(check_page(path, root, anchor_cache))
    for manifest in (root / 'plugins').glob('*/plugin.json'):
        meta = json.loads(manifest.read_text())
        name = meta['name']
        if not (root / 'docs/plugins' / f'{name}.md').is_file():
            errors.append(f'{name}: missing user guide')
        entry = root / 'skills' / name / 'SKILL.md'
        if not entry.is_file():
            entry = manifest.parent / meta['entry']
        if len(entry.read_text().split()) >= 1500:
            errors.append(f'{name}: entry exceeds 1,500-word budget')
    return errors


if __name__ == '__main__':
    errors = check()
    print('\n'.join(errors) if errors else 'Documentation links, catalog coverage, and entry budgets pass.')
    raise SystemExit(bool(errors))
