import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ledger.model import parse_amount

ROOT = Path(__file__).resolve().parent.parent


def ledger(*args):
    return subprocess.run([sys.executable, '-m', 'ledger', *args], cwd=ROOT, capture_output=True, text=True)


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, rows):
        path = self.tmp / 'in.csv'
        with open(path, 'w', newline='') as handle:
            csv.writer(handle).writerows([['date', 'account', 'description', 'amount'], *rows])
        return path

    def test_amounts_are_exact(self):
        self.assertEqual(parse_amount('1.15'), 115)
        self.assertEqual(parse_amount('-0.05'), -5)
        self.assertEqual(parse_amount('2.5'), 250)

    def test_invalid_amounts(self):
        for value in ('1e3', '1.234', ''):
            path = str(self.write([['2026-01-01', 'a', 'x', value]]))
            for command in (['total', path], ['report', path, '--by', 'month'],
                            ['export', path, str(self.tmp / 'out.csv')]):
                result = ledger(*command)
                self.assertEqual((result.returncode, result.stdout), (2, ''), (command[0], value))
                self.assertTrue(result.stderr.startswith('error:'), (command[0], value))

    def test_month_report(self):
        path = self.write([['2026-01-31', 'a', 'x', '1.15'], ['2026-02-01', 'a', 'y', '0.29']])
        self.assertEqual(ledger('report', str(path), '--by', 'month').stdout, '2026-01\ta\t1.15\n2026-02\ta\t0.29\n')
        bad = self.write([['2026-02-30', 'a', 'x', '1.00']])
        self.assertEqual(ledger('report', str(bad), '--by', 'month').returncode, 2)

    def test_export_neutralises_formulas_and_refuses_its_input(self):
        path = self.write([['2026-01-01', 'a', '=1+1', '-5.00']])
        out = self.tmp / 'out.csv'
        self.assertEqual(ledger('export', str(path), str(out)).returncode, 0)
        row = list(csv.reader(out.open(newline='')))[1]
        self.assertEqual(row[2:], ["'=1+1", '-5.00'])
        before = path.read_bytes()
        self.assertEqual(ledger('export', str(path), str(path)).returncode, 2)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
