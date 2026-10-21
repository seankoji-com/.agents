#!/usr/bin/env python3
"""Ape acceptance authority over one frozen coordinator report descriptor.

Every verdict is derived from actual bytes: the report, the current-project fingerprint,
each pinned source snapshot, each consumed accepted report and each coordinator
inspection receipt is re-read and re-hashed. The checks are operation-specific
structure, revision/provenance, requirement and candidate coverage, and coordinator
inspection receipts. Sources are `ape-source-snapshot/1` JSON documents whose framing
file content cannot forge; consequential sections follow a strict finding-block grammar
so every claim maps to one descriptor finding and receipt. These checks establish
provenance, coverage and declared criteria, not the truth of the report's prose.
Exit 0 accepted, 1 rejected, 2 usage.
"""
import argparse, hashlib, json, re, sys
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents
                            if (p / 'shared/ape_planning.py').is_file())))
from shared.validator_observations import read_object
from core.jobs.store import _regular, strict_load

MAX_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES = 5
SHA256 = re.compile(r'[0-9a-f]{64}')
REVISION = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')  # a resolved commit, never a branch or tag
HEX_TOKEN = re.compile(r'(?<![0-9A-Za-z])[0-9A-Fa-f]{40,}(?![0-9A-Za-z])')
URL = re.compile(r'https?://[^\s<>()\[\]"\'`]+')
CITATION = re.compile(r'(https?://[^/\s]+/[^/\s]+/[^/\s]+)/(blob|tree)/([^/#?\s]+)(\S*)')
LINE_RANGE = re.compile(r'L(\d+)(?:-L(\d+))?')
SNAPSHOT_FORMAT = 'ape-source-snapshot/1'
BLOCK_ID = r'[A-Za-z0-9][A-Za-z0-9._-]*'
BLOCK_CITATION = re.compile(r'Citation: (\S+)')
PROPOSAL = re.compile(r'Proposal: \S.*')
FENCE = re.compile(r'^\s{0,3}(`{3,}|~{3,})')
HEADING = re.compile(r'^\s{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$')
RESEARCH = {'sections': ('provenance', 'overlap', 'adopt', 'adapt', 'reject', 'command case'),
            'inspect': ('adopt', 'adapt'), 'sources': (1, 1), 'max_words': 900, 'consumes': False,
            'cites': True}
OPERATIONS = {
    'study': {**RESEARCH, 'fingerprint_words': 150},
    'forage-research': RESEARCH,
    'forage-synthesis': {'sections': ('provenance', 'overlap', 'conflicts', 'recommended experiment', 'rejected'),
                         'inspect': ('conflicts', 'recommended experiment'), 'sources': (1, MAX_CANDIDATES),
                         'max_words': None, 'consumes': True, 'cites': False},
}
KEYS = {'operation', 'sources', 'requirements', 'fingerprint', 'report', 'findings', 'inspections', 'criteria',
        'consumed_reports', 'planning_review'}
CRITERIA = ('source-provenance', 'finding-source-coverage')


class Reject(ValueError):
    def __init__(self, check, reason):
        super().__init__(f'{check}: {reason}')
        self.check = check


def norm(text):
    """Whitespace- and blockquote-insensitive text, so a reflowed quote still matches."""
    return ' '.join(re.sub(r'(?m)^\s*(?:>\s*)+', '', text).split())


def heading(text):
    return ' '.join(text.strip().rstrip(':').split()).lower()


def pinned_text(check, row, label):
    """UTF-8 text of a {path, sha256} pin whose actual bytes match it."""
    if not isinstance(row, dict) or not isinstance(row.get('path'), str) or not Path(row['path']).is_absolute():
        raise Reject(check, f'{label} needs an absolute path')
    if not isinstance(row.get('sha256'), str) or not SHA256.fullmatch(row['sha256']):
        raise Reject(check, f'{label} needs a lowercase hex SHA-256')
    try:
        raw = _regular(Path(row['path']), max_bytes=MAX_BYTES)
    except (OSError, ValueError) as exc:
        raise Reject(check, f'{label} is not a readable regular file within 16 MiB: {exc}') from None
    if hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise Reject(check, f'actual bytes of {label} differ from its SHA-256 pin')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        raise Reject(check, f'{label} is not UTF-8') from None


def sections(text, names):
    """Body of each required heading, ignoring fenced code; each must appear exactly once."""
    heads, fenced, lines = [], None, text.splitlines()
    for number, line in enumerate(lines):
        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)[0]
            fenced = None if fenced == marker else fenced or marker
            continue
        match = None if fenced else HEADING.match(line)
        if match:
            heads.append((number, len(match.group(1)), heading(match.group(2))))
    bodies, levels, top, inside = {}, {}, min((lvl for _, lvl, name in heads if name in names), default=1), None
    for index, (number, level, name) in enumerate(heads):
        if name not in names:
            # Only a title above the sections, or a subheading inside one, may stand outside the
            # required set; otherwise a claim could hide in a section no receipt rule covers.
            if not (inside is None and level < top or inside is not None and level > inside):
                raise Reject('structure', f'report has unexpected section {name!r}; nest it inside a required one')
            continue
        inside = level
        if name in bodies:
            raise Reject('structure', f'report repeats the {name!r} section')
        end = next((n for n, lvl, _ in heads[index + 1:] if lvl <= level), len(lines))
        bodies[name] = '\n'.join(lines[number + 1:end])
        levels[name] = level
    missing = [name for name in names if name not in bodies]
    if missing:
        raise Reject('structure', f'report lacks required section(s): {", ".join(missing)}')
    return bodies, levels


def check_sources(data, spec):
    sources = data.get('sources')
    low, high = spec['sources']
    if not isinstance(sources, list) or not low <= len(sources) <= high:
        raise Reject('structure', f'{data["operation"]} pins {low}-{high} source snapshot(s), at most '
                     f'{MAX_CANDIDATES} candidates')
    texts, bases = {}, {}
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('id'), str) or not source['id'] \
                or source['id'] in texts:
            raise Reject('provenance', 'every source needs a unique non-empty id')
        sid, revision, url = source['id'], source.get('revision'), source.get('url')
        if not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise Reject('provenance', f'source {sid} revision must be a resolved 40- or 64-hex commit')
        match = CITATION.fullmatch(url) if isinstance(url, str) else None
        if not match or not url.startswith('https://') or match.group(3) != revision:
            raise Reject('provenance', f'source {sid} url must be an https tree/blob URL pinned at {revision}')
        texts[sid] = snapshot_files(sid, revision, pinned_text('provenance', source, f'source snapshot {sid}'))
        bases[sid] = match.group(1)
    return sources, texts, bases


def snapshot_files(sid, revision, text):
    """Lines of each file in an `ape-source-snapshot/1` JSON snapshot (snapshot_source.py).

    JSON string framing cannot be forged by file content, and every entry's own hash and
    size are verified, so a source file that contains snapshot-like text stays one file."""
    try:
        snapshot = strict_load(text.encode('utf-8'))
    except ValueError as exc:
        raise Reject('provenance', f'source snapshot {sid} is not an {SNAPSHOT_FORMAT} JSON document: {exc}') from None
    if not isinstance(snapshot, dict) or set(snapshot) != {'format', 'revision', 'files'} \
            or snapshot['format'] != SNAPSHOT_FORMAT or not isinstance(snapshot['files'], list):
        raise Reject('provenance', f'source snapshot {sid} is not an {SNAPSHOT_FORMAT} document')
    if snapshot['revision'] != revision:
        raise Reject('provenance', f'source snapshot {sid} was taken at {snapshot["revision"]}, not {revision}')
    files = {}
    for entry in snapshot['files']:
        path = entry.get('path') if isinstance(entry, dict) else None
        if not isinstance(path, str) or not path or path.startswith('/') or '..' in path.split('/') \
                or path in files or set(entry) != {'path', 'sha256', 'bytes', 'text'} or not isinstance(entry['text'], str):
            raise Reject('provenance', f'source snapshot {sid} has a malformed or duplicate file entry')
        raw = entry['text'].encode('utf-8')
        if hashlib.sha256(raw).hexdigest() != entry['sha256'] or len(raw) != entry['bytes']:
            raise Reject('provenance', f'source snapshot {sid} file {path} differs from its own hash or size')
        lines = entry['text'].split('\n')
        if entry['text'].endswith('\n'):
            lines.pop()
        files[path] = lines
    return files


def finding_blocks(name, level, body):
    """The strict grammar of a consequential section: exactly `None.`, or only finding blocks of
    `<level+1 #> <id>: <title>`, one `Citation: <blob URL>#Lx[-Ly]` line, one `> quote` block and
    one `Proposal:` line. Anything else could carry an uninspected claim, so it rejects."""
    lines = body.split('\n')
    if [line.strip() for line in lines if line.strip()] == ['None.']:
        return {}
    head = re.compile(rf'#{{{level + 1}}} ({BLOCK_ID}): (\S.*)')

    def bad(why):
        raise Reject('structure', f'report {name!r} section may hold only `None.` or finding blocks '
                     f'(heading `<id>: <title>`, Citation:, > quote, Proposal:); {why}')

    def skip(i):
        while i < len(lines) and not lines[i].strip():
            i += 1
        return i

    blocks, i = {}, skip(0)
    if i == len(lines):
        bad('it is empty')
    while i < len(lines):
        match = head.fullmatch(lines[i].strip())
        if not match:
            bad(f'unexpected line {lines[i].strip()[:80]!r}')
        bid = match.group(1)
        if bid in blocks:
            bad(f'block {bid} repeats')
        i = skip(i + 1)
        citation = BLOCK_CITATION.fullmatch(lines[i].strip()) if i < len(lines) else None
        if not citation:
            raise Reject('coverage', f'report {name!r} section makes claims without a line-numbered citation: '
                         f'block {bid} needs exactly one Citation: line after its heading')
        i = skip(i + 1)
        quote = []
        while i < len(lines) and lines[i].lstrip().startswith('>'):
            quote.append(lines[i].lstrip()[1:].strip())
            i += 1
        if not ' '.join(quote).strip():
            bad(f'block {bid} needs one > quote after its Citation line')
        i = skip(i)
        if i < len(lines) and lines[i].lstrip().startswith('>'):
            bad(f'block {bid} has a second quote')
        if i >= len(lines) or not PROPOSAL.fullmatch(lines[i].strip()):
            bad(f'block {bid} needs one Proposal: line after its quote')
        blocks[bid] = {'citation': citation.group(1), 'quote': '\n'.join(quote)}
        i = skip(i + 1)
    return blocks


def resolve(url, sources, bases, files):
    """Source id and cited text of one blob citation, which must name real lines of the pinned snapshot."""
    base, kind, ref, rest = CITATION.match(url).groups()
    pins = [s for s in sources if bases[s['id']] == base]
    if not pins:
        raise Reject('coverage', f'report cites {base}, which is not an assigned pinned source')
    pins = [s for s in pins if s['revision'] == ref]
    if not pins:
        raise Reject('provenance', f'report cites {base} at {ref}, not at its pinned revision')
    if kind != 'blob':
        return None, None
    path, _, fragment = rest.lstrip('/').partition('#')
    lines = LINE_RANGE.fullmatch(fragment)
    if not lines:
        raise Reject('provenance', f'citation {url} lacks line numbers')
    start, end = int(lines.group(1)), int(lines.group(2) or lines.group(1))
    for pin in pins:
        content = files[pin['id']].get(unquote(path))
        if content is not None:
            if not 1 <= start <= end <= len(content):
                raise Reject('provenance', f'citation {url} names lines outside {path} ({len(content)} lines) '
                             f'in snapshot {pin["id"]}')
            return pin['id'], '\n'.join(content[start - 1:end])
    raise Reject('provenance', f'citation {url} names {path}, which is not in the pinned snapshot')


def citations(text):
    return [url.rstrip('.,;:') for url in URL.findall(text) if CITATION.match(url.rstrip('.,;:'))]


def check_consumed(data, spec, sources):
    consumed = data.get('consumed_reports')
    if not spec['consumes']:
        if consumed not in (None, []):
            raise Reject('structure', f'{data["operation"]} consumes no accepted reports')
        return {}
    if not isinstance(consumed, list):
        raise Reject('structure', 'synthesis must list the accepted research report for every candidate')
    reports, by_source = {}, {}
    for row in consumed:
        rid = row.get('id') if isinstance(row, dict) else None
        if not isinstance(rid, str) or not rid or rid in reports:
            raise Reject('provenance', 'every consumed report needs a unique non-empty id')
        sid = row.get('source_id')
        if sid not in {s['id'] for s in sources} or sid in by_source:
            raise Reject('coverage', f'consumed report {rid} must rest on exactly one distinct pinned candidate')
        reports[rid] = {**row, 'text': pinned_text('provenance', row, f'consumed report {rid}')}
        by_source[sid] = rid
    for source in sources:
        if source['id'] not in by_source:
            raise Reject('coverage', f'candidate {source["id"]} has no accepted research report')
    return reports


def check_report(data, spec, sources, bases, files, consumed):
    text = pinned_text('structure', data.get('report'), 'report')
    if spec['max_words'] is not None and len(text.split()) > spec['max_words']:
        raise Reject('structure', f'report exceeds {spec["max_words"]} words')
    bodies, levels = sections(text, spec['sections'])
    provenance = bodies['provenance']
    declared = {s['revision'] for s in sources} | {s['sha256'] for s in sources} | \
        {r['sha256'] for r in consumed.values()}
    for token in HEX_TOKEN.findall(provenance):
        if token not in declared:
            raise Reject('provenance', f'report Provenance declares {token}, which is not a pinned revision or hash')
    for source in sources:
        for field in ('revision', 'sha256'):
            if source[field] not in provenance:
                raise Reject('provenance', f'report Provenance omits the pinned {field} of {source["id"]}')
    for rid, row in consumed.items():
        if row['sha256'] not in provenance:
            raise Reject('provenance', f'report Provenance omits the SHA-256 of accepted report {rid}')
    resolved = {}
    for url in citations(text):
        sid, cited_text = resolve(url, sources, bases, files)
        if sid is not None:
            resolved[url] = (sid, cited_text)
    if spec['cites']:
        for source in sources:
            if source['id'] not in {sid for sid, _ in resolved.values()}:
                raise Reject('coverage', f'report has no line-numbered citation of {source["id"]} at its pinned revision')
    # Consequential claims come from the report text itself, in a strict block grammar: every
    # block is a claim the descriptor must list and the coordinator must inspect.
    claims = {}
    for name in spec['inspect']:
        claims[name] = finding_blocks(name, levels[name], bodies[name])
        for bid, block in claims[name].items():
            if block['citation'] not in resolved:
                raise Reject('provenance', f'report {name} block {bid} Citation must be one bare line-numbered '
                             'blob URL at a pinned revision')
            if norm(block['quote']) not in norm(resolved[block['citation']][1]):
                raise Reject('provenance', f'report {name} block {bid} quote is not in its own cited lines '
                             f'{block["citation"]}')
    return bodies, resolved, claims


def check_findings(data, spec, bodies, resolved, claims, consumed):
    findings = data.get('findings')
    if not isinstance(findings, list):
        raise Reject('structure', 'findings must be a list')
    allowed = [name for name in spec['sections'] if name != 'provenance']
    rows = {}
    for finding in findings:
        fid = finding.get('id') if isinstance(finding, dict) else None
        if not isinstance(fid, str) or not fid or fid in rows:
            raise Reject('structure', 'every finding needs a unique non-empty id')
        section = heading(finding['section']) if isinstance(finding.get('section'), str) else None
        if section not in allowed:
            raise Reject('structure', f'finding {fid} section must be one of: {", ".join(allowed)}')
        sid, quote, url = finding.get('source_id'), finding.get('quote'), finding.get('citation')
        if not isinstance(quote, str) or not quote.strip() or not isinstance(url, str):
            raise Reject('provenance', f'finding {fid} needs a quote and a blob citation')
        if url not in citations(bodies[section]) or url not in resolved:
            raise Reject('structure', f'finding {fid} citation is not a line-numbered citation in the report '
                         f'{section!r} section')
        if resolved[url][0] != sid:
            raise Reject('provenance', f'finding {fid} citation is not of its source {sid}')
        if norm(quote) not in norm(resolved[url][1]):
            raise Reject('provenance', f'finding {fid} quote is not in the cited lines {url}')
        if norm(quote) not in norm(bodies[section]):
            raise Reject('structure', f'finding {fid} quote does not appear in the report {section!r} section')
        rid = finding.get('report_id')
        if spec['consumes']:
            if rid not in consumed or consumed[rid]['source_id'] != sid:
                raise Reject('provenance', f'finding {fid} must rest on the accepted report for {sid}')
            if url not in consumed[rid]['text'] or norm(quote) not in norm(consumed[rid]['text']):
                raise Reject('provenance', f'finding {fid} quote and citation are not ones accepted report {rid} cited')
        elif rid is not None:
            raise Reject('structure', f'finding {fid} names a consumed report outside synthesis')
        if section in claims:
            block = claims[section].get(fid)
            if block is None:
                raise Reject('coverage', f'finding {fid} has no `{fid}:` block in the report {section!r} section')
            if block['citation'] != url or norm(block['quote']) != norm(quote):
                raise Reject('provenance', f'finding {fid} citation or quote differs from its report block')
        rows[fid] = {**finding, 'section': section}
    seen_blocks = set()
    for name, blocks in claims.items():
        for bid, block in blocks.items():
            if bid in seen_blocks:
                raise Reject('structure', f'block id {bid} appears in more than one consequential section')
            seen_blocks.add(bid)
            if bid not in rows or rows[bid]['section'] != name:
                raise Reject('coverage', f'report {name} claim citing {block["citation"]} has no descriptor finding '
                             f'in that section (block {bid}, and so no inspection receipt)')
    return rows


def check_coverage(data, sources, findings):
    requirements = data.get('requirements')
    ids = {s['id'] for s in sources}
    if not isinstance(requirements, list) or not requirements:
        raise Reject('coverage', 'report must list the stage requirements it covers')
    assigned, seen = set(), set()
    for row in requirements:
        rid = row.get('id') if isinstance(row, dict) else None
        if not isinstance(rid, str) or not rid or rid in seen:
            raise Reject('coverage', 'every requirement needs a unique non-empty id')
        seen.add(rid)
        sids = row.get('source_ids')
        if not isinstance(sids, list) or not sids or len(set(sids)) != len(sids) or not set(sids) <= ids:
            raise Reject('coverage', f'requirement {rid} must name distinct pinned source ids')
        if not any(f['source_id'] in sids for f in findings.values()):
            raise Reject('coverage', f'requirement {rid} has no finding')
        assigned |= set(sids)
    if ids - assigned:
        raise Reject('coverage', f'source {min(ids - assigned)} is not assigned to any requirement')
    uncovered = ids - {f['source_id'] for f in findings.values()}
    if uncovered:
        raise Reject('coverage', f'candidate {min(uncovered)} has no finding')
    return sorted(seen)


def check_receipts(data, spec, sources, findings, consumed):
    receipts = data.get('inspections')
    if not isinstance(receipts, list):
        raise Reject('inspection', 'coordinator inspection receipts must be a list')
    categories = ('report', *spec['inspect'])
    report, paths = data['report'], {s['id']: s['path'] for s in sources}
    covered, report_seen = set(), False
    for number, receipt in enumerate(receipts, 1):
        category = receipt.get('category') if isinstance(receipt, dict) else None
        if category not in categories:
            raise Reject('inspection', f'receipt {number} category must be one of: {", ".join(categories)}')
        if not isinstance(receipt.get('inspected'), str) or not receipt['inspected'].strip():
            raise Reject('inspection', f'receipt {number} must say what the coordinator inspected')
        pinned_text('inspection', receipt, f'inspection receipt {number} ({category})')
        if category == 'report':
            if (receipt['path'], receipt['sha256']) != (report['path'], report['sha256']):
                raise Reject('inspection', f'receipt {number} does not name the pinned report bytes')
            report_seen = True
            continue
        fids = receipt.get('finding_ids')
        if not isinstance(fids, list) or not fids:
            raise Reject('inspection', f'receipt {number} ({category}) must name the findings it inspected')
        for fid in fids:
            finding = findings.get(fid)
            if finding is None or finding['section'] != category:
                raise Reject('inspection', f'receipt {number} names {fid!r}, which is not a {category} finding')
            allowed = {paths[finding['source_id']]}
            if finding.get('report_id') in consumed:
                allowed.add(consumed[finding['report_id']]['path'])
            if receipt['path'] not in allowed:
                raise Reject('inspection', f'receipt {number} for {fid} names {receipt["path"]}, not the cited '
                             f'source or report')
            covered.add(fid)
    if not report_seen:
        raise Reject('inspection', 'missing coordinator inspection receipt for category report (sections and '
                     'citations of the pinned report)')
    for fid, finding in findings.items():
        if finding['section'] in spec['inspect'] and fid not in covered:
            raise Reject('inspection', f'missing coordinator inspection receipt for {finding["section"]} finding '
                         f'{fid} (source {finding["source_id"]})')
    return len(receipts)


def check_criteria(data):
    criteria = data.get('criteria')
    if not isinstance(criteria, list) or not criteria:
        raise Reject('criteria', 'report must declare at least one criterion')
    seen = set()
    for criterion in criteria:
        if not isinstance(criterion, dict) or 'status' in criterion or not isinstance(criterion.get('id'), str) \
                or not criterion['id'] or criterion['id'] in seen:
            raise Reject('criteria', 'criteria declare checks; result statuses cannot be supplied')
        if criterion.get('kind') not in CRITERIA:
            raise Reject('criteria', 'unsupported provenance criterion')
        minimum = criterion.get('minimum_findings', 0)
        if type(minimum) is not int or minimum < 0:
            raise Reject('criteria', 'minimum finding coverage must be a nonnegative integer')
        seen.add(criterion['id'])
    return criteria


def check_domain(path):
    data, descriptor_sha = read_object(path)
    unknown = sorted(set(data) - KEYS)
    if unknown:
        raise Reject('structure', f'unknown descriptor field(s): {", ".join(unknown)}')
    spec = OPERATIONS.get(data.get('operation'))
    if spec is None:
        raise Reject('structure', f'operation must be one of: {", ".join(OPERATIONS)}')
    criteria = check_criteria(data)
    sources, texts, bases = check_sources(data, spec)
    fingerprint = pinned_text('provenance', data.get('fingerprint'), 'project fingerprint')
    if not fingerprint.strip():
        raise Reject('provenance', 'project fingerprint is empty')
    if 'fingerprint_words' in spec and len(fingerprint.split()) > spec['fingerprint_words']:
        raise Reject('structure', f'project fingerprint exceeds {spec["fingerprint_words"]} words')
    consumed = check_consumed(data, spec, sources)
    bodies, resolved, claims = check_report(data, spec, sources, bases, texts, consumed)
    findings = check_findings(data, spec, bodies, resolved, claims, consumed)
    requirements = check_coverage(data, sources, findings)
    receipts = check_receipts(data, spec, sources, findings, consumed)
    outcomes = {}
    for criterion in criteria:
        passed = criterion['kind'] == 'source-provenance' or len(findings) >= criterion.get('minimum_findings', 0)
        outcomes[criterion['id']] = {'status': 'passed' if passed else 'failed', 'evidence': {
            'input': path, 'sha256': descriptor_sha, 'operation': data['operation'], 'check': criterion['kind'],
            'report_sha256': data['report']['sha256'], 'fingerprint_sha256': data['fingerprint']['sha256'],
            'source_sha256': {s['id']: s['sha256'] for s in sources},
            'source_revision': {s['id']: s['revision'] for s in sources},
            'consumed_report_sha256': {rid: row['sha256'] for rid, row in consumed.items()},
            'requirements': requirements, 'finding_count': len(findings), 'inspection_receipts': receipts}}
    return data, outcomes


def evaluate(path):
    data, outcomes = check_domain(path)
    accepted = all(row['status'] == 'passed' for row in outcomes.values())
    if accepted and data['operation'] in ('study', 'forage-synthesis'):
        from shared.ape_planning import validate
        evidence = validate(data, Path(__file__).resolve().parents[1] / 'references/plan-review-rubric.md')
        for row in outcomes.values():
            row['evidence']['planning_review'] = evidence
    return {'accepted': accepted, 'requirement_outcomes': outcomes}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--input', required=True, help='frozen coordinator report descriptor (JSON)')
    args = parser.parse_args()
    try:
        result = evaluate(args.input)
    except Exception as exc:  # any malformed input is a rejection with a reason, never a crash
        check = getattr(exc, 'check', 'input')
        result = {'accepted': False, 'requirement_outcomes': {'report-acceptance': {
            'status': 'failed', 'evidence': {'check': check, 'reason': str(exc)}}}}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['accepted'] else 1


if __name__ == '__main__':
    sys.exit(main())
