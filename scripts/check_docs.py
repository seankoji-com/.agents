#!/usr/bin/env python3
"""Check local Markdown links, catalog coverage, and portable entry budgets."""
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent


def check(root=ROOT):
    errors = []
    pages = [*root.glob('*.md'), *(root / 'docs').rglob('*.md')]
    for path in pages:
        text = re.sub(r'```[^\n]*\n.*?```', '', path.read_text(), flags=re.S)
        for target in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)', text):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = path.parent / unquote(parsed.path)
            if not resolved.exists():
                errors.append(f'{path.relative_to(root)}: missing link {target}')
    for manifest in (root / 'plugins').glob('*/plugin.json'):
        meta = json.loads(manifest.read_text())
        name = meta['name']
        if not (root / 'docs/plugins' / f'{name}.md').is_file():
            errors.append(f'{name}: missing user guide')
        entry = manifest.parent / meta['entry']
        if len(entry.read_text().split()) >= 1500:
            errors.append(f'{name}: entry exceeds 1,500-word budget')
    return errors


if __name__ == '__main__':
    errors = check()
    print('\n'.join(errors) if errors else 'Documentation links, catalog coverage, and entry budgets pass.')
    raise SystemExit(bool(errors))
