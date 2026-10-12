#!/usr/bin/env python3
"""Hidden behaviour and quality checks for the bench-v2 five-stage engineering fixture.

The run agent never sees this file, its datasets or the reference solution: the
workspace is prepared only from fixtures/five_stage/workspace. Every check runs the
workspace's own CLI or tests in a temporary copy, so the evaluated tree is never
written. Required checks gate a counted start; informational checks are reported only.

Usage: python3 bench/v2/checks/five_stage.py WORKSPACE [--json]
Exit status: 0 when every required check passes, 1 otherwise, 2 on bad usage.
Executes code from WORKSPACE. Run it only on a disposable copy or isolated clone.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / 'fixtures' / 'five_stage' / 'workspace'
TIMEOUT = 120
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


class Sandbox:
    """A disposable copy of the workspace with a scrubbed environment."""

    def __init__(self, workspace: Path, root: Path):
        self.dir = root / 'ws'
        shutil.copytree(workspace, self.dir, ignore=shutil.ignore_patterns('.git', '__pycache__', '.bench-state'),
                        symlinks=True)
        self.data = root / 'data'
        self.data.mkdir()
        self.env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(root),
                    'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}

    def run(self, *args, cwd=None):
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


def check(workspace: Path) -> list:
    results = []

    def record(check_id, required, passed, detail=''):
        results.append({'id': check_id, 'required': required, 'passed': bool(passed), 'detail': detail})

    investigation = read_text(workspace, 'notes/investigation.md')
    cited = {int(n) for n in re.findall(r'(?:ledger/)?model\.py:(\d+)', investigation)}
    record('C1-investigation-cites-defect', True,
           cited & defect_lines() and re.search(r'(?i)float|binary|truncat', investigation),
           f'cited lines {sorted(cited)}; defect lines {sorted(defect_lines())}')

    with tempfile.TemporaryDirectory(prefix='bench-v2-') as tmp:
        box = Sandbox(workspace, Path(tmp))
        amounts = box.file('amounts.csv', AMOUNTS_CSV)
        total = box.ledger('total', str(amounts))
        record('C2-exact-cent-totals', True, total.returncode == 0 and lines(total) == TOTALS,
               f'exit {total.returncode}: {lines(total)[:5]}')

        bad = []
        for value in BAD_AMOUNTS:
            path = write_csv(box.data / 'bad-amount.csv', [['2026-03-01', 'food', 'x', value]])
            for command in (['total', str(path)], ['export', str(path), str(box.data / 'bad-out.csv')]):
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
                exported = list(csv.reader(handle))[1:]
            if len(exported) != len(rows):
                problems.append(f'{len(exported)} rows exported, expected {len(rows)}')
            for original, written in zip(rows, exported):
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
        record('C8-workspace-tests-pass', True, suite.returncode == 0, ' '.join(suite.stderr.strip().splitlines()[-1:]))

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
    wanted = {'amounts': r'(?i)cent|rounding|amount', 'month': r'(?i)month',
              'formula': r'(?i)formula|spreadsheet|injection', 'overwrite': r'(?i)overwrit|same file|own input|input file'}
    missing = [name for name, pattern in wanted.items() if not re.search(pattern, entries)]
    record('C11-changelog-unreleased-complete', True, not missing, f'missing: {missing}')
    audit = read_text(workspace, 'notes/audit.md')
    severities = re.findall(r'(?i)\b(high|medium|low)\b', audit)
    record('C12-audit-findings-with-severity', True,
           len(severities) >= 2 and re.search(r'(?i)formula', audit)
           and re.search(r'(?i)overwrit|same file|own input|destroy|truncat', audit), f'{len(severities)} severities')
    review = read_text(workspace, 'notes/review.md')
    record('C13-review-verdict-recorded', True,
           re.search(r'(?i)\b(approve[sd]?|adverse|changes requested|rejected?)\b', review), '')

    if (workspace / '.git').exists():
        log = subprocess.run(['git', '-C', str(workspace), 'log', '--format=%s'], capture_output=True, text=True)
        stages = sorted({int(m) for m in re.findall(r'^stage-([1-5]):', log.stdout, re.M)})
        record('I2-stage-commits', False, stages == [1, 2, 3, 4, 5], f'stages committed: {stages}')
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if not args.workspace.is_dir():
        parser.error(f'{args.workspace} is not a directory')
    results = check(args.workspace.resolve())
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
