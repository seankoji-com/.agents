#!/usr/bin/env python3
"""Hidden behaviour and quality checks for the bench-v2 five-stage engineering fixture.

The run agent never sees this file, its datasets or the reference solution: the
workspace is prepared only from fixtures/five_stage/workspace. Every check runs the
workspace's own CLI or tests in a temporary copy, so the evaluated tree is never
written. Required checks gate a counted start; informational checks are reported only.

Usage: python3 bench/v2/checks/five_stage.py WORKSPACE [--json] [--review-context PATH]
Exit status: 0 when every required check passes, 1 otherwise, 2 on bad usage.
Executes untrusted code from WORKSPACE. Run it only inside the isolated S1b container.
main(), check() and Sandbox refuse to execute workspace code elsewhere; only offline
tests over repository-owned synthetic fixtures pass trusted_synthetic_fixture=True.
"""
from __future__ import annotations

import argparse
import ast
import csv
import difflib
from decimal import Decimal
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import model_policy

FIXTURE = Path(__file__).resolve().parent.parent / 'fixtures' / 'five_stage' / 'workspace'
TIMEOUT = 120
# The two supported audit Fix sentences disclosed in the fixture prompt (C12).
FORMULA_FIX = re.compile(r'(?i)(?:`[\w.]+`\s+)?prefix(?:es)?\s+dangerous\s+(?:text\s+)?cells\s+with\s+an\s+apostrophe\.?')
OVERWRITE_FIX = re.compile(r'(?i)(?:`[\w.]+`\s+)?(?:checks?|compares?)\s+(?:paths\s+with\s+)?`os\.path\.samefile`'
                           r'\s+and\s+refuses?\s+the\s+output(?:\s+before\s+opening\s+it)?\.?')
HEADER = 'date,account,description,amount\n'
AMOUNTS_CSV = HEADER + ''.join(f'{d},{a},{x},{m}\n' for d, a, x, m in [
    ('2026-03-01', 'food', 'a', '1.15'), ('2026-03-02', 'food', 'b', '2.20'), ('2026-03-05', 'food', 'c', '0.29'),
    ('2026-03-09', 'fees', 'd', '-0.05'), ('2026-04-01', 'fees', 'e', '4.35'), ('2026-04-02', 'food', 'f', '19.99'),
    ('2026-04-20', 'rent', 'g', '1200'), ('2026-05-30', 'food', 'h', '0.57')])
TOTALS = ['fees\t4.30', 'food\t24.20', 'rent\t1200.00']
MONTHS = ['2026-03\tfees\t-0.05', '2026-03\tfood\t3.64', '2026-04\tfees\t4.35', '2026-04\tfood\t19.99',
          '2026-04\trent\t1200.00', '2026-05\tfood\t0.57']
SAMPLE_TOTALS = ['groceries\t64.00', 'rent\t2400.00', 'transport\t44.50']
BAD_AMOUNTS = ['1.234', '1e3', 'abc', '', '--1', '1,000']
BAD_DATES = ['2026-02-30', '2026-13-01', '2026/03/01', '20260301']
DANGEROUS = ['=HYPERLINK("https://example.invalid","x")', '+SUM(A1)', '-2+3', '@cmd', '\tTabbed', '\rReturn']
FORMULA_START = ('=', '+', '-', '@', '\t', '\r')


def write_csv(path: Path, rows) -> Path:
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['date', 'account', 'description', 'amount'])
        writer.writerows(rows)
    return path


ISOLATION_MARKER = Path('/.dockerenv')


class HostExecutionRefused(RuntimeError):
    """Raised before candidate code would run outside the isolated grader."""


def isolated_grader_environment(environ=None, marker=None) -> bool:
    """True only inside a container that declares itself the isolated grader.

    This prevents accidental host execution of candidate code; it is not a
    defence against a host user who forges both signals.
    """
    environ = os.environ if environ is None else environ
    marker = ISOLATION_MARKER if marker is None else marker
    return environ.get('T3_BENCH_ISOLATED_GRADER') == '1' and marker.is_file()


def require_isolated_execution(trusted_synthetic_fixture=False):
    """Guard every path that executes workspace code.

    Only offline tests over repository-owned synthetic fixtures may pass
    trusted_synthetic_fixture=True; candidate workspaces never may.
    """
    if trusted_synthetic_fixture is not True and not isolated_grader_environment():
        raise HostExecutionRefused('five_stage.py executes untrusted workspace code; run it only in the isolated '
                                   'grader container with T3_BENCH_ISOLATED_GRADER=1')


class Sandbox:
    """A disposable copy of the workspace with a scrubbed environment."""

    def __init__(self, workspace: Path, root: Path, trusted_synthetic_fixture=False):
        require_isolated_execution(trusted_synthetic_fixture)
        self.trusted_synthetic_fixture = trusted_synthetic_fixture is True
        self.dir = root / 'ws'
        shutil.copytree(workspace, self.dir, ignore=shutil.ignore_patterns('.git', '__pycache__', '.bench-state'),
                        symlinks=True)
        self.data = root / 'data'
        self.data.mkdir()
        self.env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(root),
                    'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}

    def run(self, *args, cwd=None):
        require_isolated_execution(self.trusted_synthetic_fixture)
        try:
            return subprocess.run([sys.executable, '-E', '-s', *args], cwd=cwd or self.dir, env=self.env,
                                  capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, -1, '', 'timeout')

    def ledger(self, *args):
        return self.run('-m', 'ledger', *args)

    def file(self, name: str, text: str) -> Path:
        path = self.data / name
        path.write_text(text, encoding='utf-8')
        return path


def lines(result) -> list:
    return [line for line in result.stdout.splitlines() if line.strip()]


def error_contract(result) -> bool:
    return result.returncode == 2 and result.stdout.strip() == '' and result.stderr.lstrip().startswith('error:')


def read_text(workspace: Path, rel: str) -> str:
    path = workspace / rel
    try:
        return path.read_text(encoding='utf-8') if path.is_file() and not path.is_symlink() else ''
    except (OSError, UnicodeDecodeError):
        return ''


def unreleased(changelog: str) -> str:
    match = re.search(r'^## Unreleased[^\n]*\n(.*?)(?=^## |\Z)', changelog, re.M | re.S)
    return match.group(1) if match else ''


def defect_lines() -> set:
    source = (FIXTURE / 'ledger' / 'model.py').read_text().splitlines()
    return {n for n, line in enumerate(source, 1) if 'float(text)' in line or 'int(value * 100)' in line}


def numeric_reproducer(value, actual, expected):
    try:
        amount = Decimal(value)
        old = Decimal(int(float(value) * 100)) / 100
        return old != amount and Decimal(actual) == old and Decimal(expected) == amount
    except (ValueError, ArithmeticError, OverflowError):
        return False


def relevant_changed_line(workspace, line):
    source = read_text(workspace, 'ledger/model.py')
    try:
        function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'parse_amount')
    except (SyntaxError, StopIteration):
        return False
    original = (FIXTURE / 'ledger/model.py').read_text().splitlines()
    current = source.splitlines()
    changed = {n + 1 for tag, _, _, start, end in difflib.SequenceMatcher(a=original, b=current, autojunk=False).get_opcodes()
               if tag in {'replace', 'insert'} for n in range(start, end)}
    statements = [n for n in ast.walk(function) if isinstance(n, ast.stmt) and not isinstance(n, ast.FunctionDef)
                  and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    return line in changed and any(n.lineno == line and any(isinstance(v, ast.Name) and v.id in
        {'text', 'cents', 'whole', 'fraction', 'value', 'match', 'AMOUNT', 'Decimal', 'int', 'float'} for v in ast.walk(n)) for n in statements)


# The combined change the review must cover. notes/review.md carries the review
# itself, so binding it would make the receipt self-referential.
REVIEWED_DOCUMENTS = ('README.md', 'CHANGELOG.md', 'notes/audit.md')


def reviewed_source_hash(workspace):
    files = {str(p.relative_to(workspace)): hashlib.sha256(p.read_bytes()).hexdigest()
             for directory in ('ledger', 'tests') for p in sorted((workspace / directory).rglob('*.py')) if p.is_file()}
    for rel in REVIEWED_DOCUMENTS:
        path = workspace / rel
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def target_lineage(catalog, target, role):
    """Return (provider, model, lineage) of an allowed target; unknown lineage raises.

    Mirrors shared/job_acceptance._lineage: lineage comes from the cheap-family policy
    for the validated provider, and a recorded lineage must agree with it.
    """
    selected = model_policy.validate_target(catalog, target, role=role)
    family = model_policy.FAMILIES[selected['providerInstanceId']]
    if 'lineage' in target and target['lineage'] != family:
        raise ValueError('recorded target lineage disagrees with its model family')
    return selected['providerInstanceId'], selected['model'], family


def independent_review_matches(workspace, context_path, review):
    """Check retained host transport; filesystem ownership is the host's boundary."""
    try:
        path = Path(context_path)
        if path.resolve().is_relative_to(workspace.resolve()):
            return False
        context = json.loads(path.read_text())
        target = model_policy.validate_target(context['catalog'], context['target'], role='reviewer')
        # The reviewer needs a known lineage different from the implementing parent's:
        # a different provider/model target and a different model family.
        reviewer = target_lineage(context['catalog'], context['target'], 'reviewer')
        implementer = target_lineage(context['catalog'], context['parent_target'], 'parent')
        if reviewer[:2] == implementer[:2] or reviewer[2] == implementer[2]:
            return False
        task_id = context['task_id']
        launches = [r for r in context['tool_records'] if r['toolName'] == 't3-code.delegate_task' and r['output'].get('taskId') == task_id]
        statuses = [r for r in context['tool_records'] if r['toolName'] == 't3-code.task_status' and r['input'].get('taskId') == task_id]
        launch, status = launches[0], statuses[-1]
        marker = 'ISSUE28_REVIEW_SOURCE_SHA256=' + reviewed_source_hash(workspace)
        out = status['output']
        return (len(launches) == 1 and isinstance(task_id, str) and bool(task_id) and
                launch.get('threadId') == status.get('threadId') == context['parent_thread_id'] and
                launch['input'].get('role') == 'review' and launch['input'].get('target') == target and
                marker in launch['input'].get('task', '').splitlines() and out.get('taskId') == task_id and
                out.get('providerInstanceId') == target['providerInstanceId'] and out.get('model') == target['model'] and
                out.get('status') == 'completed' and out.get('workState') == 'result_available' and
                out.get('hasPendingChildRuns') is False and out.get('summary') == review)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError):
        return False


def check(workspace: Path, review_context=None, *, trusted_synthetic_fixture=False) -> list:
    require_isolated_execution(trusted_synthetic_fixture)
    results = []

    def record(check_id, required, passed, detail=''):
        results.append({'id': check_id, 'required': required, 'passed': bool(passed), 'detail': detail})

    investigation = read_text(workspace, 'notes/investigation.md')
    citations = re.findall(r'(?:ledger/)?model\.py:(\d+)', investigation)
    cited = {int(n) for n in citations}
    input_value = re.search(r'(?im)^Input: `?(-?\d+\.\d{1,2})`?$', investigation)
    actual_value = re.search(r'(?im)^Actual: `?(-?\d+\.\d{2})`?$', investigation)
    expected_value = re.search(r'(?im)^Expected: `?(-?\d+\.\d{2})`?$', investigation)
    numeric_repro = bool(input_value and actual_value and expected_value and
                         numeric_reproducer(input_value.group(1), actual_value.group(1), expected_value.group(1)))
    record('C1-investigation-cites-defect', True,
           bool(cited & defect_lines()) and numeric_repro and re.search(r'(?i)float|binary|truncat', investigation),
           f'cited lines {sorted(cited)}; defect lines {sorted(defect_lines())}')

    with tempfile.TemporaryDirectory(prefix='bench-v2-') as tmp:
        box = Sandbox(workspace, Path(tmp), trusted_synthetic_fixture)
        amounts = box.file('amounts.csv', AMOUNTS_CSV)
        total = box.ledger('total', str(amounts))
        record('C2-exact-cent-totals', True, total.returncode == 0 and lines(total) == TOTALS,
               f'exit {total.returncode}: {lines(total)[:5]}')

        bad = []
        for value in BAD_AMOUNTS:
            path = write_csv(box.data / 'bad-amount.csv', [['2026-03-01', 'food', 'x', value]])
            for command in (['total', str(path)], ['report', str(path), '--by', 'month'],
                            ['export', str(path), str(box.data / 'bad-out.csv')]):
                if not error_contract(box.ledger(*command)):
                    bad.append(f'{command[0]} {value!r}')
        record('C3-invalid-amounts-rejected', True, not bad, ', '.join(bad))

        month = box.ledger('report', str(amounts), '--by', 'month')
        record('C4-month-report-exact', True, month.returncode == 0 and lines(month) == MONTHS,
               f'exit {month.returncode}: {lines(month)[:8]}')

        bad = []
        for value in BAD_DATES:
            path = write_csv(box.data / 'bad-date.csv', [[value, 'food', 'x', '1.00']])
            if not error_contract(box.ledger('report', str(path), '--by', 'month')):
                bad.append(value)
        record('C5-invalid-dates-rejected', True, not bad, ', '.join(bad))

        rows = [['2026-03-01', 'food', text, '-5.00'] for text in DANGEROUS]
        rows += [['2026-03-02', '=acct', 'plain', '3.10'], ['2026-03-03', 'food', 'plain', '-0.05']]
        source = write_csv(box.data / 'formula.csv', rows)
        out = box.data / 'formula-out.csv'
        result = box.ledger('export', str(source), str(out))
        problems = []
        if result.returncode != 0 or not out.is_file():
            problems.append(f'export exit {result.returncode}')
        else:
            with open(out, newline='', encoding='utf-8') as handle:
                all_rows = list(csv.reader(handle))
                exported = all_rows[1:]
            if not all_rows or all_rows[0] != ['date', 'account', 'description', 'amount']:
                problems.append('export header differs from required columns')
            if any(len(row) != 4 for row in exported):
                problems.append('export rows must have exactly four columns')
            if len(exported) != len(rows):
                problems.append(f'{len(exported)} rows exported, expected {len(rows)}')
            for original, written in zip(rows, exported):
                if len(written) != 4:
                    continue
                for column in range(3):
                    if written[column].startswith(FORMULA_START) or original[column] not in written[column]:
                        problems.append(f'cell {original[column]!r} written as {written[column]!r}')
                if written[3] != original[3]:
                    problems.append(f'amount {original[3]!r} written as {written[3]!r}')
        record('C6-export-neutralises-formulas-keeps-numbers', True, not problems, '; '.join(problems[:6]))

        problems = []
        victim = write_csv(box.data / 'victim.csv', [['2026-03-01', 'food', 'keep me', '1.00']])
        (box.data / 'sub').mkdir()
        spellings = [str(victim), str(box.data / 'sub' / '..' / 'victim.csv')]
        link = box.data / 'alias.csv'
        try:
            link.symlink_to(victim)
            spellings.append(str(link))
        except OSError:
            pass
        for spelling in spellings:
            before = victim.read_bytes()
            result = box.ledger('export', str(victim), spelling)
            if result.returncode == 0 or victim.read_bytes() != before:
                problems.append(f'export onto {Path(spelling).name} via {spelling.count("..") and ".." or "path"}: '
                                f'exit {result.returncode}, input changed {victim.read_bytes() != before}')
        record('C7-export-refuses-its-own-input', True, not problems, '; '.join(problems))

        suite = box.run('-m', 'unittest', 'discover', '-s', 'tests')
        hidden_path = Path(__file__).resolve().parent / 'reference/tests/test_stages.py'
        hidden = box.run('-c', 'import pathlib,sys,unittest; p=pathlib.Path(sys.argv[1]); '
            'ns={"__name__":"bench_reference","__file__":str(p)}; '
            'exec(compile(p.read_bytes(),str(p),"exec"),ns); ns["ROOT"]=pathlib.Path.cwd(); '
            'r=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(ns["StageTests"])); '
            'sys.exit(0 if r.wasSuccessful() else 1)', str(hidden_path))
        record('C8-workspace-tests-pass', True, suite.returncode == 0 and hidden.returncode == 0,
               'workspace: ' + ' '.join(suite.stderr.strip().splitlines()[-1:]) +
               '; frozen reference: ' + ' '.join(hidden.stderr.strip().splitlines()[-1:]))

        sample = box.ledger('total', str(box.dir / 'data' / 'sample.csv'))
        record('C9-total-output-unchanged', True, sample.returncode == 0 and lines(sample) == SAMPLE_TOTALS,
               f'{lines(sample)}')

        original = Path(tmp) / 'original'
        shutil.copytree(FIXTURE, original)
        shutil.rmtree(original / 'tests')
        shutil.copytree(box.dir / 'tests', original / 'tests')
        regression = box.run('-m', 'unittest', 'discover', '-s', 'tests', cwd=original)
        record('I1-new-tests-fail-on-original-code', False, regression.returncode != 0,
               'informational: an ImportError of new code also counts as failure')

    readme = read_text(workspace, 'README.md')
    record('C10-readme-documents-changes', True,
           '--by month' in readme and re.search(r'(?i)formula|spreadsheet', readme), '')
    entries = unreleased(read_text(workspace, 'CHANGELOG.md'))
    wanted = {
        'amounts': r'(?i)amounts?\s+are\s+parsed\s+exactly|round(?:ing|ed)?\s+(?:amounts?|values?)\s+to\s+cents',
        'month': r'(?i)(?:report\s+FILE\s+--by\s+month|month(?:ly)?\s+(?:totals?|reports?))',
        'formula': r'(?i)neutralis(?:e|es|ed|ing)\s+spreadsheet\s+formula\s+cells?',
        'overwrite': r'(?i)(?:refus(?:e|es|ed|ing)\s+to\s+overwrite\s+its\s+input|export\s+.{0,40}refuses?\s+to\s+overwrite\s+its\s+input)',
    }
    missing = [name for name, pattern in wanted.items() if not re.search(pattern, entries)]
    record('C11-changelog-unreleased-complete', True, not missing and not re.search(r'(?i)\b(not approved|never approved|approval denied)\b', entries), f'missing: {missing}')
    audit = read_text(workspace, 'notes/audit.md')
    finding_blocks = [block for block in re.split(r'\n\s*\n', audit) if re.search(r'(?im)^Finding:', block)]
    seeded = {'io': {24}, 'cli': {31}}
    def concrete_audit_block(block):
        cites = re.findall(r'(?:ledger/)?(io|cli)\.py:(\d+)', block)
        locations = {(file, int(line)) for file, line in cites}
        severity = bool(re.search(r'(?im)^Severity: (high|medium|low)$', block))
        repro = re.search(r'(?im)^Reproducer: (.+)$', block)
        # Split the block into labelled fields; an unlabelled line continues the field
        # above it. Each required field must appear exactly once, so a second or
        # continued Fix cannot contradict the accepted one.
        fields = {}
        for line in block.splitlines():
            label = re.match(r'(?i)(Finding|Severity|Evidence|Reproducer|Fix|Status|Disposition):\s?(.*)$', line.strip())
            if label:
                fields.setdefault(label.group(1).lower(), []).append(label.group(2).strip())
            elif fields and line.strip():
                last = list(fields)[-1]
                fields[last][-1] = (fields[last][-1] + ' ' + line.strip()).strip()
        once = all(len(fields.get(name, [])) == 1 for name in ('finding', 'severity', 'evidence', 'reproducer', 'fix'))
        fix = fields['fix'][0] if once else None
        seeded_citations = locations & {(file, line) for file, lines in seeded.items() for line in lines}
        formula = (severity and ('io', 24) in seeded_citations and re.search(r'(?im)^Evidence: .*io\.py:24\b', block) and repro is not None and
                   bool(re.search(r'=[A-Z]+\(', repro.group(1))))
        overwrite = (severity and ('cli', 31) in seeded_citations and re.search(r'(?im)^Evidence: .*cli\.py:31\b', block) and repro is not None and
                     bool(re.search(r'(?i)export\s+data\.csv\s+data\.csv', repro.group(1))))
        # Each fix must be the one affirmative corrective sentence the prompt discloses
        # for its own defect. The whole field must match, so negated, opposite, swapped
        # or extra clauses fail closed; this checks the stated claim, not behaviour.
        fix_text = fix or ''
        formula_fix = bool(FORMULA_FIX.fullmatch(fix_text))
        overwrite_fix = bool(OVERWRITE_FIX.fullmatch(fix_text))
        valid = once and severity and repro is not None
        # A block citing both seeded defects is a combined finding and counts for neither.
        single_defect = len(seeded_citations) == 1
        formula_ok = bool(valid and single_defect and formula and formula_fix)
        overwrite_ok = bool(valid and single_defect and overwrite and overwrite_fix)
        return 'formula' if formula_ok else 'overwrite' if overwrite_ok else 'not-concrete'
    kinds = [concrete_audit_block(block) for block in finding_blocks]
    # Every finding block must be concrete: exactly one formula-only block and exactly
    # one overwrite-only block, so filler cannot make up the count.
    good_audit = sorted(kinds) == ['formula', 'overwrite']
    record('C12-audit-findings-with-severity', True,
           good_audit,
           f'{len(finding_blocks)} findings classified {kinds}; need one formula-only io.py:24 and one '
           'same-file-only cli.py:31 block, each with reproducer, severity and fix')

    review = read_text(workspace, 'notes/review.md')
    verdict = re.search(r'^Verdict: (approve|adverse|unavailable)$', review, re.M)
    finding = re.search(r'(?im)^Finding: .+\nChanged: ledger/model\.py:(\d+)\nSeeded: ledger/model\.py:(\d+), input (-?\d+\.\d{1,2}), actual (-?\d+\.\d{2}), expected (-?\d+\.\d{2})\nEvidence: .*C2-exact-cent-totals PASS.*\nDisposition: fixed\b', review)
    negated = re.search(r'(?i)\b(not approved|did not approve|never approved|approval denied)\b', review)
    changed_line = int(finding.group(1)) if finding else 0
    changed_code = relevant_changed_line(workspace, changed_line)
    current_checks = {item['id']: item['passed'] for item in results}
    record('C13-review-verdict-recorded', True, bool(verdict and finding and changed_code and
           int(finding.group(2)) in defect_lines() and numeric_reproducer(*finding.group(3, 4, 5)) and verdict.group(1) == 'approve' and not negated and
           current_checks.get('C2-exact-cent-totals') is True and current_checks.get('C8-workspace-tests-pass') is True and
           independent_review_matches(workspace, review_context, review)), 'independent host review transport required')

    if (workspace / '.git').exists():
        require_isolated_execution(trusted_synthetic_fixture)
        log = subprocess.run(['git', '-C', str(workspace), 'log', '--format=%s'], capture_output=True, text=True)
        stages = sorted({int(m) for m in re.findall(r'^stage-([1-5]):', log.stdout, re.M)})
        record('I2-stage-commits', False, stages == [1, 2, 3, 4, 5], f'stages committed: {stages}')
    return results


def main(argv=None) -> int:
    try:
        require_isolated_execution()
    except HostExecutionRefused as exc:
        print(exc, file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--review-context', type=Path, help='coordinator-owned captured review transport outside workspace')
    args = parser.parse_args(argv)
    if not args.workspace.is_dir():
        parser.error(f'{args.workspace} is not a directory')
    results = check(args.workspace.resolve(), args.review_context)
    passed = all(r['passed'] for r in results if r['required'])
    if args.json:
        print(json.dumps({'schema_version': 1, 'protocol': 'bench-v2', 'fixture': 'five_stage',
                          'required_passed': passed, 'checks': results}, indent=2))
    else:
        for r in results:
            print(f"{'PASS' if r['passed'] else 'FAIL'} {'required' if r['required'] else 'info    '} {r['id']} {r['detail']}")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
