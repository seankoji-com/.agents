import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ledger import io, report
from ledger.model import format_cents, parse_amount

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / 'data' / 'sample.csv'


class AmountTest(unittest.TestCase):
    def test_whole_and_two_place_amounts(self):
        self.assertEqual(parse_amount('12.50'), 1250)
        self.assertEqual(parse_amount('3'), 300)

    def test_format(self):
        self.assertEqual(format_cents(1250), '12.50')
        self.assertEqual(format_cents(-5), '-0.05')


class ReportTest(unittest.TestCase):
    def test_totals_by_account(self):
        result = report.totals(io.read_csv(SAMPLE))
        self.assertEqual(list(result), sorted(result))
        self.assertEqual(result['groceries'], 6400)


class CliTest(unittest.TestCase):
    def test_total_command(self):
        out = subprocess.run([sys.executable, '-m', 'ledger', 'total', str(SAMPLE)], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        self.assertIn('groceries\t64.00', out.splitlines())

    def test_export_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.csv'
            subprocess.run([sys.executable, '-m', 'ledger', 'export', str(SAMPLE), str(out)], cwd=ROOT, check=True)
            self.assertEqual(io.read_csv(out), io.read_csv(SAMPLE))


if __name__ == '__main__':
    unittest.main()
