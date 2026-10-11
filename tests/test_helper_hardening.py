"""Regression tests for the helper-script findings fixed in the portfolio review.

Each test names the behavior a reviewer could reproduce before the fix. The Codex
TOML audit must not hide its Python 3.11 requirement behind a generic receipt.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / 'plugins/agent-tuneup/scripts/audit.py'


class CodexTomlRequirementTest(unittest.TestCase):
    def test_missing_tomllib_is_reported_as_the_python_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            shadow = Path(tmp) / 'shadow'
            shadow.mkdir()
            (shadow / 'tomllib.py').write_text('raise ImportError("simulated Python 3.10")\n')
            settings = Path(tmp) / 'config.toml'
            settings.write_text('[sandbox]\nmode = "workspace-write"\n')
            env = {**os.environ, 'PYTHONPATH': str(shadow)}
            proc = subprocess.run([sys.executable, str(AUDIT), '--provider', 'codex', '--settings', str(settings)],
                                  capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        receipt = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(receipt['error'], 'python_3_11_required')
        self.assertNotIn('settings_unreadable_or_invalid', proc.stdout)


if __name__ == '__main__':
    unittest.main()
