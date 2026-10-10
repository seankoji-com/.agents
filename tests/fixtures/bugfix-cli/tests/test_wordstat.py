import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / 'wordstat.py'


def run(text):
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as handle:
        handle.write(text)
    result = subprocess.run([sys.executable, str(CLI), 'count', handle.name], capture_output=True, text=True)
    Path(handle.name).unlink()
    return result


class WordstatTest(unittest.TestCase):
    def test_single_line(self):
        self.assertEqual(run('alpha beta gamma').stdout.strip(), '3')

    def test_usage(self):
        self.assertEqual(subprocess.run([sys.executable, str(CLI)], capture_output=True).returncode, 2)


if __name__ == '__main__':
    unittest.main()
