"""Ape acceptance authority: validate_report.py and the snapshot_source.py pinning helper.

The module-level builders write synthetic pinned sources, fingerprints, reports and
coordinator inspection receipts; other ape tests reuse them. Each negative case breaks
one property of an otherwise valid descriptor and checks the precise rejection. No
network, model or GitHub access.
"""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.support import git  # noqa: E402

INSTALL = {}  # the installed, pinned package under test; see setUpModule
CRITERIA = [{'id': 'provenance', 'kind': 'source-provenance'},
            {'id': 'coverage', 'kind': 'finding-source-coverage', 'minimum_findings': 1}]
SOURCE_TEXT = '==> lib/retry.py <==\ndef retry(call):\n    """Bounded retry with jitter."""\n    return call()\n'
OVERLAP_QUOTE = 'def retry(call):'
ADOPT_QUOTE = 'Bounded retry with jitter.'
INSPECTED = {'adopt', 'adapt', 'conflicts', 'recommended experiment'}


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def revision(sid):
    return hashlib.sha1(('revision-' + sid).encode()).hexdigest()


def write_pin(path, text):
    """Write a file and return its {path, sha256} pin."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {'path': str(path), 'sha256': sha(path.read_bytes())}


def pin_source(base, sid, text=SOURCE_TEXT):
    rev = revision(sid)
    return {'id': sid, 'url': f'https://github.com/example/{sid}/tree/{rev}', 'revision': rev,
            **write_pin(Path(base) / 'workspace' / 'sources' / f'{sid}.txt', text)}


def blob(pin, line):
    return pin['url'].replace('/tree/', '/blob/', 1) + f'/lib/retry.py#L{line}'


def research_markdown(pin, adopt=True):
    """A research report with every required section; Adapt and Reject are empty."""
    adopt_body = (f'### Bounded retry\n\n> {ADOPT_QUOTE}\n\nCited at {blob(pin, 2)}. Targets `core/net.py`; '
                  'effort small; tradeoff added latency; counterargument: callers already retry; simpler '
                  'alternative: document the limit; experiment baseline 3 flaky failures, success 0, abandon '
                  'after 2 runs.\n') if adopt else 'None.\n'
    return (f'# Study of example/{pin["id"]}\n\n## Provenance\n\n- {pin["id"]}: {pin["url"]} at revision '
            f'{pin["revision"]}, snapshot sha256 {pin["sha256"]}\n\n## Overlap\n\nBoth define '
            f'`{OVERLAP_QUOTE}` ([source]({blob(pin, 1)})).\n\n## Adopt\n\n{adopt_body}\n## Adapt\n\nNone.\n\n'
            '## Reject\n\nNone.\n\n## Command case\n\n```sh\n# not a section heading\npython3 -m unittest\n```\n')


def research_findings(pin, adopt=True):
    rows = [{'id': f'{pin["id"]}-overlap', 'section': 'Overlap', 'source_id': pin['id'], 'quote': OVERLAP_QUOTE}]
    if adopt:
        rows.append({'id': f'{pin["id"]}-adopt', 'section': 'Adopt', 'source_id': pin['id'], 'quote': ADOPT_QUOTE})
    return rows


def synthesis_markdown(pins, consumed):
    reports = ', '.join(f'{row["id"]} sha256 {row["sha256"]}' for row in consumed)
    sources = '\n'.join(f'- {p["id"]}: {p["url"]} at {p["revision"]}, snapshot sha256 {p["sha256"]}' for p in pins)
    return (f'# Synthesis\n\n## Provenance\n\n{sources}\n- accepted reports: {reports}\n\n## Overlap\n\n'
            f'Every candidate defines `{OVERLAP_QUOTE}`.\n\n## Conflicts\n\n{consumed[0]["id"]} quotes '
            f'"{ADOPT_QUOTE}"; the others never bound retries.\n\n## Recommended experiment\n\nAdopt '
            f'"{ADOPT_QUOTE}" in `core/net.py`; baseline 3 flaky failures, success 0, abandon after 2 runs.\n\n'
            '## Rejected\n\nNone.\n')


def synthesis_findings(pins, consumed):
    by_source = {row['source_id']: row['id'] for row in consumed}
    rows = [{'id': f'{p["id"]}-overlap', 'section': 'Overlap', 'source_id': p['id'], 'quote': OVERLAP_QUOTE,
             'report_id': by_source[p['id']]} for p in pins]
    first = pins[0]['id']
    for name, section in (('conflict', 'Conflicts'), ('experiment', 'Recommended experiment')):
        rows.append({'id': f'{first}-{name}', 'section': section, 'source_id': first, 'quote': ADOPT_QUOTE,
                     'report_id': by_source[first]})
    return rows


def receipts_for(report, pins, findings, consumed=()):
    """What the coordinator records: the report, then each consequential finding's cited source."""
    paths = {p['id']: p for p in pins}
    rows = [{'category': 'report', 'path': report['path'], 'sha256': report['sha256'],
             'inspected': 'all sections, Provenance and every citation'}]
    for finding in findings:
        section = ' '.join(finding['section'].lower().split())
        if section in INSPECTED:
            source = paths[finding['source_id']]
            rows.append({'category': section, 'path': source['path'], 'sha256': source['sha256'],
                         'finding_ids': [finding['id']], 'inspected': 'opened the cited lines'})
    return rows


def fingerprint(base):
    return write_pin(Path(base) / 'workspace' / 'fingerprint.md', 'Python stdlib CLI; gap: no retry policy.\n')


def descriptor(operation, pins, requirements, finger, report, findings, consumed=None, criteria=CRITERIA):
    data = {'operation': operation, 'sources': pins, 'requirements': requirements, 'fingerprint': finger,
            'report': report, 'findings': findings, 'criteria': copy.deepcopy(criteria),
            'inspections': receipts_for(report, pins, findings)}
    if consumed is not None:
        data['consumed_reports'] = consumed
    return data


def research_descriptor(base, operation='study', sid='src-1', adopt=True):
    pin = pin_source(base, sid)
    report = write_pin(Path(base) / 'artifacts' / sid / 'report.md', research_markdown(pin, adopt))
    return descriptor(operation, [pin], [{'id': 'R-SRC-1', 'source_ids': [sid]}], fingerprint(base), report,
                      research_findings(pin, adopt))


def study_descriptor(base, pin, requirement_ids, criteria=CRITERIA):
    """A complete valid study descriptor over an existing pin_source() pin, for acceptance-machinery tests."""
    report = write_pin(Path(base) / 'ape-reports' / f'{pin["id"]}.md', research_markdown(pin))
    return descriptor('study', [pin], [{'id': rid, 'source_ids': [pin['id']]} for rid in requirement_ids],
                      fingerprint(base), report, research_findings(pin), criteria=criteria)


def synthesis_descriptor(base, count=2):
    pins = [pin_source(base, f'src-{n}') for n in range(1, count + 1)]
    consumed = [{'id': f'rep-{p["id"]}', 'source_id': p['id'],
                 **write_pin(Path(base) / 'artifacts' / p['id'] / 'report.md', research_markdown(p))} for p in pins]
    report = write_pin(Path(base) / 'artifacts' / 'synth' / 'report.md', synthesis_markdown(pins, consumed))
    return descriptor('forage-synthesis', pins, [{'id': 'R-SYNTH', 'source_ids': [p['id'] for p in pins]}],
                      fingerprint(base), report, synthesis_findings(pins, consumed), consumed)


def setUpModule():
    """Test the installed artifact: the scripts import the package's pinned shared helpers."""
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    env = {**os.environ, 'HOME': str(base / 'home'), 'XDG_CONFIG_HOME': str(base / 'config'),
           'XDG_STATE_HOME': str(base / 'state')}
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'install.py'), '--plugin', 'ape', '--prefix',
                           str(base / 'prefix'), '--agents-root', str(base / 'agents')],
                          capture_output=True, text=True, env=env, timeout=120)
    if proc.returncode != 0:
        tmp.cleanup()
        raise RuntimeError(proc.stdout + proc.stderr)
    scripts = Path(json.loads(proc.stdout)['data']['version_dir']) / 'scripts'
    INSTALL.update(tmp=tmp, validator=scripts / 'validate_report.py', snapshot=scripts / 'snapshot_source.py')


def tearDownModule():
    INSTALL.pop('tmp').cleanup()


def run_validator(path, validator=None):
    proc = subprocess.run([sys.executable, str(validator or INSTALL['validator']), '--input', str(path)],
                          capture_output=True, text=True, timeout=60)
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None), proc.stderr


class ValidatorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def run_on(self, data):
        self.seq += 1
        path = self.base / f'descriptor-{self.seq}.json'
        path.write_text(json.dumps(data))
        return run_validator(path)

    def accepts(self, data):
        code, verdict, err = self.run_on(data)
        self.assertEqual((code, verdict and verdict['accepted']), (0, True), (verdict, err))
        return verdict

    def rejects(self, data, check, reason):
        code, verdict, err = self.run_on(data)
        self.assertEqual(code, 1, (verdict, err))
        self.assertFalse(verdict['accepted'])
        evidence = verdict['requirement_outcomes']['report-acceptance']['evidence']
        self.assertEqual(evidence['check'], check, evidence)
        self.assertIn(reason, evidence['reason'])
        return evidence['reason']

    def rewrite(self, data, key, text):
        """Replace a pinned file's bytes and re-pin it, as if the coordinator froze the new bytes."""
        row = data[key] if isinstance(key, str) else key
        row.update(write_pin(row['path'], text))
        for receipt in data['inspections']:
            if receipt['path'] == row['path']:
                receipt['sha256'] = row['sha256']


class OperationStructureTests(ValidatorCase):
    def test_valid_study_accepts_with_outcomes_bound_to_actual_bytes(self):
        data = research_descriptor(self.base)
        verdict = self.accepts(data)
        self.assertEqual(set(verdict['requirement_outcomes']), {'provenance', 'coverage'})
        evidence = verdict['requirement_outcomes']['coverage']['evidence']
        self.assertEqual(evidence['report_sha256'], data['report']['sha256'])
        self.assertEqual(evidence['source_revision'], {'src-1': revision('src-1')})
        self.assertEqual((evidence['operation'], evidence['finding_count'], evidence['inspection_receipts']),
                         ('study', 2, 2))

    def test_forage_research_and_empty_adopt_adapt_are_valid(self):
        self.accepts(research_descriptor(self.base, 'forage-research'))
        self.accepts(research_descriptor(self.base / 'empty', adopt=False))

    def test_synthesis_accepts_five_candidates_and_rejects_six(self):
        self.accepts(synthesis_descriptor(self.base, 5))
        self.rejects(synthesis_descriptor(self.base / 'six', 6), 'structure', 'at most 5 candidates')

    def test_research_operations_pin_exactly_one_candidate(self):
        data = research_descriptor(self.base)
        data['sources'].append(pin_source(self.base, 'src-2'))
        self.rejects(data, 'structure', 'study pins 1-1 source')

    def test_missing_or_repeated_sections_reject(self):
        data = research_descriptor(self.base)
        text = Path(data['report']['path']).read_text()
        self.rewrite(data, 'report', text.replace('## Command case', '## Commands'))
        self.rejects(data, 'structure', 'lacks required section(s): command case')
        self.rewrite(data, 'report', text + '\n## Adapt\n\nAgain.\n')
        self.rejects(data, 'structure', "repeats the 'adapt' section")

    def test_synthesis_needs_its_own_sections(self):
        data = synthesis_descriptor(self.base)
        self.rewrite(data, 'report', Path(data['report']['path']).read_text().replace('## Conflicts', '## Adapt'))
        self.rejects(data, 'structure', 'lacks required section(s): conflicts')

    def test_heading_inside_code_fence_is_not_a_section(self):
        data = research_descriptor(self.base)
        text = Path(data['report']['path']).read_text().replace('## Reject\n', '```\n## Reject\n```\n')
        self.rewrite(data, 'report', text)
        self.rejects(data, 'structure', 'lacks required section(s): reject')

    def test_operation_fields_and_finding_sections_are_closed(self):
        data = research_descriptor(self.base)
        self.rejects({**data, 'operation': 'forage'}, 'structure', 'operation must be one of')
        self.rejects({**data, 'notes': 'x'}, 'structure', 'unknown descriptor field(s): notes')
        wrong = copy.deepcopy(data)
        wrong['findings'][0]['section'] = 'Conflicts'
        self.rejects(wrong, 'structure', 'section must be one of')
        self.rejects({**data, 'consumed_reports': [{'id': 'x'}]}, 'structure', 'consumes no accepted reports')

    def test_finding_quote_must_appear_in_its_report_section(self):
        data = research_descriptor(self.base)
        data['findings'][1]['section'] = 'Reject'
        self.rejects(data, 'structure', "src-1-adopt quote does not appear in the report 'reject' section")

    def test_word_budgets(self):
        data = research_descriptor(self.base)
        self.rewrite(data, 'report', Path(data['report']['path']).read_text() + 'word ' * 900)
        self.rejects(data, 'structure', 'exceeds 900 words')
        data = research_descriptor(self.base / 'finger')
        self.rewrite(data, 'fingerprint', 'stack ' * 151)
        self.rejects(data, 'structure', 'fingerprint exceeds 150 words')

    def test_criteria_cannot_carry_statuses(self):
        data = research_descriptor(self.base)
        data['criteria'][0]['status'] = 'passed'
        self.rejects(data, 'criteria', 'result statuses cannot be supplied')

    def test_minimum_findings_criterion_fails_its_outcome(self):
        data = research_descriptor(self.base, adopt=False)
        data['criteria'][1]['minimum_findings'] = 2
        code, verdict, _ = self.run_on(data)
        self.assertEqual((code, verdict['accepted']), (1, False))
        self.assertEqual(verdict['requirement_outcomes']['coverage']['status'], 'failed')
        self.assertEqual(verdict['requirement_outcomes']['provenance']['status'], 'passed')

    def test_usage_error_exits_two(self):
        proc = subprocess.run([sys.executable, str(INSTALL['validator'])], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)


class RevisionProvenanceTests(ValidatorCase):
    def test_revision_must_be_a_resolved_commit_in_a_pinned_url(self):
        data = research_descriptor(self.base)
        data['sources'][0]['revision'] = 'main'
        self.rejects(data, 'provenance', 'resolved 40- or 64-hex commit')
        data = research_descriptor(self.base / 'url')
        data['sources'][0]['url'] = 'https://github.com/example/src-1'
        self.rejects(data, 'provenance', 'url must be an https tree/blob URL pinned at')

    def test_changed_source_report_or_fingerprint_bytes_reject(self):
        for key, check in (('report', 'structure'), ('fingerprint', 'provenance')):
            data = research_descriptor(self.base / key)
            Path(data[key]['path']).write_text('changed\n')
            self.rejects(data, check, 'differ from its SHA-256 pin')
        data = research_descriptor(self.base / 'source')
        Path(data['sources'][0]['path']).write_text('changed\n')
        self.rejects(data, 'provenance', 'source snapshot src-1 differ from its SHA-256 pin')

    def test_report_must_declare_exactly_the_pinned_revision_and_hash(self):
        data = research_descriptor(self.base)
        text = Path(data['report']['path']).read_text()
        self.rewrite(data, 'report', text.replace(data['sources'][0]['sha256'], 'unknown'))
        self.rejects(data, 'provenance', 'omits the pinned sha256 of src-1')
        other = 'b' * 40
        self.rewrite(data, 'report', text.replace('## Overlap', f'- also studied {other}\n\n## Overlap'))
        self.rejects(data, 'provenance', f'declares {other}, which is not a pinned revision')

    def test_citations_must_be_at_the_pinned_revision_with_lines(self):
        data = research_descriptor(self.base)
        pin = data['sources'][0]
        text = Path(data['report']['path']).read_text()
        self.rewrite(data, 'report', text.replace(blob(pin, 1), blob(pin, 1).replace(pin['revision'], 'c' * 40)))
        self.rejects(data, 'provenance', 'not at its pinned revision')
        self.rewrite(data, 'report', text.replace(blob(pin, 1), blob(pin, 1).split('#')[0]))
        self.rejects(data, 'provenance', 'lacks line numbers')

    def test_finding_quote_must_be_in_the_actual_source_bytes(self):
        data = research_descriptor(self.base)
        data['findings'][0]['quote'] = 'Both define'
        self.rejects(data, 'provenance', 'src-1-overlap quote is not in the actual bytes of source src-1')

    def test_synthesis_findings_rest_on_the_accepted_report_text(self):
        data = synthesis_descriptor(self.base)
        data['findings'][0]['report_id'] = 'rep-src-2'
        self.rejects(data, 'provenance', 'must rest on the accepted report for src-1')
        data = synthesis_descriptor(self.base / 'text')
        self.rewrite(data, data['consumed_reports'][0], 'An accepted report that never quoted the source.\n')
        text = Path(data['report']['path']).read_text()
        self.rewrite(data, 'report', text.replace(
            'accepted reports: rep-src-1 sha256 ' + text.split('rep-src-1 sha256 ')[1].split(',')[0],
            'accepted reports: rep-src-1 sha256 ' + data['consumed_reports'][0]['sha256']))
        self.rejects(data, 'provenance', 'quote is not text accepted report rep-src-1 cited')

    def test_synthesis_provenance_lists_accepted_report_hashes(self):
        data = synthesis_descriptor(self.base)
        text = Path(data['report']['path']).read_text()
        self.rewrite(data, 'report', text.replace(data['consumed_reports'][1]['sha256'], 'omitted'))
        self.rejects(data, 'provenance', 'omits the SHA-256 of accepted report rep-src-2')


class CoverageTests(ValidatorCase):
    def test_every_candidate_needs_a_finding(self):
        data = synthesis_descriptor(self.base)
        data['findings'] = [f for f in data['findings'] if f['source_id'] != 'src-2']
        data['inspections'] = receipts_for(data['report'], data['sources'], data['findings'])
        self.rejects(data, 'coverage', 'candidate src-2 has no finding')

    def test_every_requirement_is_covered_and_every_source_assigned(self):
        data = synthesis_descriptor(self.base)
        data['requirements'] = [{'id': 'R-SRC-1', 'source_ids': ['src-1']}]
        self.rejects(data, 'coverage', 'source src-2 is not assigned to any requirement')
        data['requirements'] = [{'id': 'R-SYNTH', 'source_ids': ['src-1', 'src-9']}]
        self.rejects(data, 'coverage', 'requirement R-SYNTH must name distinct pinned source ids')
        data['requirements'] = []
        self.rejects(data, 'coverage', 'must list the stage requirements')

    def test_requirement_without_finding_rejects(self):
        data = synthesis_descriptor(self.base)
        data['requirements'] = [{'id': 'R-A', 'source_ids': ['src-1', 'src-2']}, {'id': 'R-B', 'source_ids': ['src-2']}]
        data['findings'] = [f for f in data['findings'] if f['source_id'] == 'src-1']
        data['inspections'] = receipts_for(data['report'], data['sources'], data['findings'])
        self.rejects(data, 'coverage', 'requirement R-B has no finding')

    def test_unassigned_cited_source_and_uncited_candidate_reject(self):
        data = research_descriptor(self.base)
        text = Path(data['report']['path']).read_text()
        stray = 'https://github.com/example/other/blob/' + 'd' * 40 + '/x.py#L1'
        self.rewrite(data, 'report', text.replace('## Reject\n', f'## Reject\n\nSee {stray}.\n'))
        self.rejects(data, 'coverage', 'cites https://github.com/example/other, which is not an assigned')
        pin = data['sources'][0]
        self.rewrite(data, 'report', text.replace(blob(pin, 1), 'local').replace(blob(pin, 2), 'local'))
        self.rejects(data, 'coverage', 'no line-numbered citation of src-1')

    def test_synthesis_needs_one_accepted_report_per_candidate(self):
        data = synthesis_descriptor(self.base)
        data['consumed_reports'] = data['consumed_reports'][:1]
        self.rejects(data, 'coverage', 'candidate src-2 has no accepted research report')
        data = synthesis_descriptor(self.base / 'dup')
        data['consumed_reports'][1]['source_id'] = 'src-1'
        self.rejects(data, 'coverage', 'consumed report rep-src-2 must rest on exactly one distinct')


class InspectionReceiptTests(ValidatorCase):
    def test_report_receipt_is_required(self):
        data = research_descriptor(self.base)
        data['inspections'] = [r for r in data['inspections'] if r['category'] != 'report']
        self.rejects(data, 'inspection', 'missing coordinator inspection receipt for category report')

    def test_each_adopt_and_adapt_finding_needs_a_receipt(self):
        data = research_descriptor(self.base)
        data['inspections'] = [r for r in data['inspections'] if r['category'] != 'adopt']
        self.rejects(data, 'inspection', 'missing coordinator inspection receipt for adopt finding src-1-adopt '
                                         '(source src-1)')

    def test_synthesis_conflict_and_experiment_need_receipts(self):
        for category, fid in (('conflicts', 'src-1-conflict'), ('recommended experiment', 'src-1-experiment')):
            data = synthesis_descriptor(self.base / fid)
            data['inspections'] = [r for r in data['inspections'] if r['category'] != category]
            self.rejects(data, 'inspection', f'receipt for {category} finding {fid}')

    def test_synthesis_receipt_may_name_the_accepted_report(self):
        data = synthesis_descriptor(self.base)
        report = data['consumed_reports'][0]
        for receipt in data['inspections']:
            if receipt['category'] == 'conflicts':
                receipt.update(path=report['path'], sha256=report['sha256'])
        self.accepts(data)

    def test_receipt_bytes_path_and_scope_are_checked(self):
        data = research_descriptor(self.base)
        stale = copy.deepcopy(data)
        stale['inspections'][1]['sha256'] = sha('older bytes')
        self.rejects(stale, 'inspection', 'differ from its SHA-256 pin')
        wrong = copy.deepcopy(data)
        wrong['inspections'][1].update(path=data['report']['path'], sha256=data['report']['sha256'])
        self.rejects(wrong, 'inspection', 'not the cited source or report')
        other = copy.deepcopy(data)
        other['inspections'][1]['finding_ids'] = ['src-1-overlap']
        self.rejects(other, 'inspection', "'src-1-overlap', which is not a adopt finding")
        blank = copy.deepcopy(data)
        blank['inspections'][0]['inspected'] = ' '
        self.rejects(blank, 'inspection', 'must say what the coordinator inspected')
        unknown = copy.deepcopy(data)
        unknown['inspections'][0]['category'] = 'truth'
        self.rejects(unknown, 'inspection', 'category must be one of: report, adopt, adapt')
        report = copy.deepcopy(data)
        report['inspections'][0].update(path=data['sources'][0]['path'], sha256=data['sources'][0]['sha256'])
        self.rejects(report, 'inspection', 'does not name the pinned report bytes')


def make_clone(base):
    clone = base / 'clone'
    (clone / 'pkg').mkdir(parents=True)
    (clone / 'README.md').write_text('# Example\n')
    (clone / 'pkg' / 'retry.py').write_text('def retry(call):\n    """Bounded retry with jitter."""\n')
    (clone / 'pkg' / 'empty.py').write_text('')
    (clone / 'pkg' / 'blob.bin').write_bytes(b'\x00\x01\x02binary')
    (clone / 'pkg' / 'latin.txt').write_bytes('caf\xe9\n'.encode('latin-1'))
    git(base, 'init', '-q', str(clone))
    git(clone, 'add', '-A')
    git(clone, 'commit', '-q', '-m', 'fixture')
    return clone


class SnapshotSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.clone = make_clone(self.base)
        self.sources = self.base / 'workspace' / 'sources'
        self.sources.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def snap(self, *extra, output=None, expect=0):
        output = output or self.sources / 'src-1.txt'
        proc = subprocess.run([sys.executable, str(INSTALL['snapshot']), '--clone', str(self.clone), '--repo-url',
                               'https://github.com/example/src-1', '--id', 'src-1', '--output', str(output), *extra],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout) if expect == 0 else proc.stderr

    def test_pins_text_files_at_head_and_leaves_clone_untouched(self):
        head = git(self.clone, 'rev-parse', 'HEAD').stdout.strip()
        out = self.snap()
        pin = out['pin']
        self.assertEqual(pin['revision'], head)
        self.assertEqual(pin['url'], f'https://github.com/example/src-1/tree/{head}')
        raw = Path(pin['path']).read_bytes()
        self.assertEqual(pin['sha256'], sha(raw))
        text = raw.decode('utf-8')
        self.assertIn('==> pkg/retry.py <==\ndef retry(call):', text)
        self.assertIn('==> README.md <==', text)
        for excluded in ('blob.bin', 'empty.py', 'latin.txt'):
            self.assertNotIn(f'==> pkg/{excluded} <==', text)
        self.assertEqual(out['skipped'], [{'path': 'pkg/latin.txt', 'reason': 'not UTF-8'}])
        self.assertEqual(out['files'], 2)
        self.assertFalse(os.stat(pin['path']).st_mode & 0o222, 'snapshot is read-only')
        self.assertEqual(git(self.clone, 'status', '--porcelain', '--untracked-files=all').stdout, '')

    def test_scope_narrows_and_is_recorded_in_the_url(self):
        pin = self.snap('--scope', 'pkg')['pin']
        self.assertTrue(pin['url'].endswith('/pkg'))
        self.assertNotIn('README.md', Path(pin['path']).read_text())

    def test_snapshot_feeds_an_accepted_study_report(self):
        pin = self.snap()['pin']
        base = self.base / 'report'
        report = write_pin(base / 'report.md', research_markdown(pin).replace('/lib/retry.py#', '/pkg/retry.py#'))
        data = descriptor('study', [pin], [{'id': 'R-SRC-1', 'source_ids': ['src-1']}], fingerprint(base), report,
                          research_findings(pin))
        path = base / 'descriptor.json'
        path.write_text(json.dumps(data))
        code, verdict, err = run_validator(path)
        self.assertEqual((code, verdict['accepted']), (0, True), (verdict, err))

    def test_refusals(self):
        self.snap()
        self.assertIn('immutable', self.snap(expect=1))
        self.assertIn('outside the read-only clone', self.snap(output=self.clone / 'snap.txt', expect=1))
        job = self.base / 'state' / 'job-1'
        (job / 'artifacts').mkdir(parents=True)
        (job / 'job.json').write_text('{}')
        self.assertIn('artifacts', self.snap(output=job / 'artifacts' / 'snap.txt', expect=1))
        self.assertIn('narrow --scope', self.snap('--max-bytes', '10', output=self.sources / 'small.txt', expect=1))
        self.assertIn('relative path', self.snap('--scope', '../x', output=self.sources / 'up.txt', expect=1))
        (self.clone / 'README.md').write_text('# Edited\n')
        self.assertIn('local changes', self.snap(output=self.sources / 'dirty.txt', expect=1))
        self.assertFalse((self.sources / 'dirty.txt').exists())

    def test_usage_errors_exit_two(self):
        proc = subprocess.run([sys.executable, str(INSTALL['snapshot']), '--clone', str(self.clone), '--repo-url', 'git@x:y',
                               '--id', 'src-1', '--output', str(self.sources / 'x.txt')],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2, proc.stderr)


if __name__ == '__main__':
    unittest.main()
