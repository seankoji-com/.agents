"""MkDocs hook: build the field guide from the same files the installer and ledger use.

The homepage, the plugin pages, and the sightings table read ``plugins/*/plugin.json``,
``docs/field-guide.json``, and ``conformance/compatibility.json`` at build time. Nothing
on the site is a hand-copied number. Standard library only, so the tests can import it
without the documentation dependencies.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIGHTINGS_MARKER = '<!-- sightings-matrix -->'
INLINE_SVG = re.compile(r'<!-- inline-svg: (assets/[A-Za-z0-9_./-]+\.svg) -->')
ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
CASE_LABELS = {
    'bugfix': 'bug fix',
    'missing-capability': 'missing capability',
    'adverse-review': 'adverse review',
    'pending-task': 'pending task',
    'provider-switch': 'provider switch',
}


class FieldGuideError(ValueError):
    """The guide and the catalog disagree; the build must fail loudly."""


def load_guide(root: Path = ROOT) -> list[dict]:
    """Merge each plugin manifest with its field-guide entry, ordered by plate number."""
    guide = json.loads((root / 'docs' / 'field-guide.json').read_text())
    guide.pop('$comment', None)
    manifests = {}
    for path in sorted((root / 'plugins').glob('*/plugin.json')):
        meta = json.loads(path.read_text())
        manifests[meta['name']] = meta
    missing = sorted(set(manifests) - set(guide))
    extra = sorted(set(guide) - set(manifests))
    if missing or extra:
        raise FieldGuideError(f'field guide out of sync: missing={missing} extra={extra}')
    specimens = []
    for name, entry in guide.items():
        plate = entry['plate']
        if plate not in ROMAN:
            raise FieldGuideError(f'{name}: unknown plate numeral {plate!r}')
        mark = root / 'docs' / 'assets' / 'specimens' / f'{name}.svg'
        if not mark.is_file():
            raise FieldGuideError(f'{name}: missing specimen mark {mark.relative_to(root)}')
        meta = manifests[name]
        specimens.append({
            'name': name,
            'plate': plate,
            'order': ROMAN[plate],
            'binomial': entry['binomial'],
            'summary': entry['summary'],
            'habitat': entry['habitat'],
            'diet': entry['diet'],
            'field_marks': entry['field_marks'],
            'description': meta['description'],
            'version': meta['version'],
            'operations': list(meta['operations']),
            'compatibility': meta['compatibility'],
            'mark_svg': mark.read_text(),
            'page': f'plugins/{name}.md',
            'url': f'plugins/{name}/',
        })
    specimens.sort(key=lambda s: s['order'])
    orders = [s['order'] for s in specimens]
    if orders != list(range(1, len(specimens) + 1)):
        raise FieldGuideError(f'plate numerals must run I..{len(specimens)} without gaps: {orders}')
    return specimens


def load_sightings(root: Path = ROOT) -> dict:
    """Summarise the live conformance ledger per provider and case."""
    ledger = json.loads((root / 'conformance' / 'compatibility.json').read_text())
    cases = list(ledger['critical_cases'])
    for row in ledger['providers']:
        for case in row.get('cases', {}):
            if case not in cases:
                cases.append(case)
    providers = []
    for row in ledger['providers']:
        tallies = {}
        for case in cases:
            repeats = row.get('cases', {}).get(case, [])
            tallies[case] = {
                'passed': sum(1 for r in repeats if r.get('passed')),
                'repeats': len(repeats),
                'notes': [r['note'] for r in repeats if r.get('note') and not r.get('passed')],
            }
        providers.append({
            'provider': row['provider_instance_id'],
            'model': row.get('model_id') or None,
            'status': row['status'],
            'summary': row.get('summary', ''),
            'interventions': sum(r.get('interventions', 0) for rs in row.get('cases', {}).values() for r in rs),
            'tallies': tallies,
        })
    return {
        't3_version': ledger['t3_version'],
        'plugin_version': ledger['plugin_version'],
        'cases': cases,
        'providers': providers,
        'observed': sum(1 for p in providers if any(t['repeats'] for t in p['tallies'].values())),
    }


def dots(passed: int, repeats: int) -> str:
    """Render a tally as filled and empty marks, with the numbers for screen readers."""
    if repeats == 0:
        return '<span class="sighting sighting--none" title="not run">not run</span>'
    marks = '●' * passed + '○' * (repeats - passed)
    state = 'clean' if passed == repeats else ('mixed' if passed else 'failed')
    return (f'<span class="sighting sighting--{state}" aria-label="{passed} of {repeats} passed">'
            f'<span aria-hidden="true">{marks}</span> {passed}/{repeats}</span>')


def render_sightings(sightings: dict) -> str:
    """HTML table of the ledger: one row per provider, one column per case."""
    cases = sightings['cases']
    head = ''.join(f'<th scope="col">{html.escape(CASE_LABELS.get(c, c))}</th>' for c in cases)
    rows = []
    for p in sightings['providers']:
        cells = ''.join(f'<td>{dots(p["tallies"][c]["passed"], p["tallies"][c]["repeats"])}</td>' for c in cases)
        model = html.escape(p['model']) if p['model'] else '<span class="sighting--none">not available</span>'
        rows.append(
            f'<tr><th scope="row"><code>{html.escape(p["provider"])}</code></th>'
            f'<td class="sightings__model">{model}</td>{cells}'
            f'<td><span class="status status--{html.escape(p["status"])}">{html.escape(p["status"])}</span></td></tr>')
    caption = (f'imps on T3 Code {html.escape(sightings["t3_version"])}, plugin '
               f'{html.escape(sightings["plugin_version"])}. Passes over repeats; a provider is '
               f'verified only at 3/3 on every critical case with no intervention.')
    return (f'<div class="sightings" markdown="0"><table class="sightings__table">'
            f'<caption>{caption}</caption>'
            f'<thead><tr><th scope="col">Provider</th><th scope="col">Model</th>{head}'
            f'<th scope="col">Status</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def render_specimen_header(specimen: dict) -> str:
    """The plate that opens each plugin's guide page."""
    return (
        '<div class="specimen specimen--page" markdown="0">'
        f'<div class="specimen__mark">{specimen["mark_svg"]}</div>'
        '<div class="specimen__text">'
        f'<p class="specimen__plate">Plate {specimen["plate"]}</p>'
        f'<p class="specimen__binomial">{html.escape(specimen["binomial"])}</p>'
        '<dl class="specimen__facts">'
        f'<dt>Habitat</dt><dd>{html.escape(specimen["habitat"])}</dd>'
        f'<dt>Diet</dt><dd>{html.escape(specimen["diet"])}</dd>'
        f'<dt>Field marks</dt><dd>{html.escape(specimen["field_marks"])}</dd>'
        '</dl></div></div>\n\n'
    )


def inline_svgs(markdown: str, root: Path) -> str:
    """Replace ``<!-- inline-svg: assets/x.svg -->`` with the file so page fonts and colours apply."""
    assets = (root / 'docs' / 'assets').resolve()

    def replace(match: re.Match) -> str:
        path = (root / 'docs' / match.group(1)).resolve()
        if assets not in path.parents or not path.is_file():
            raise FieldGuideError(f'inline-svg refers outside docs/assets or to a missing file: {match.group(1)}')
        return path.read_text().strip()

    return INLINE_SVG.sub(replace, markdown)


def expand_page(markdown: str, src_path: str, root: Path = ROOT, guide: list[dict] | None = None,
                sightings: dict | None = None) -> str:
    """Pure function behind on_page_markdown, so tests can call it without MkDocs."""
    guide = load_guide(root) if guide is None else guide
    by_page = {s['page']: s for s in guide}
    if src_path in by_page:
        markdown = _insert_after_h1(markdown, render_specimen_header(by_page[src_path]))
    if SIGHTINGS_MARKER in markdown:
        sightings = load_sightings(root) if sightings is None else sightings
        markdown = markdown.replace(SIGHTINGS_MARKER, render_sightings(sightings))
    return inline_svgs(markdown, root)


def _insert_after_h1(markdown: str, block: str) -> str:
    lines = markdown.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('# '):
            return '\n'.join(lines[:i + 1] + ['', block.rstrip('\n')] + lines[i + 1:])
    return block + markdown


# MkDocs entry points -------------------------------------------------------------

def on_config(config):
    guide = load_guide()
    config.extra['field_guide'] = {'specimens': guide, 'sightings': load_sightings()}
    return config


def on_page_markdown(markdown, page, config, files):
    extra = config.extra.get('field_guide') or {}
    return expand_page(markdown, page.file.src_path, guide=extra.get('specimens'),
                       sightings=extra.get('sightings'))
