"""Fail-closed parsing and secret-safe, read-only settings audit receipts."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/agent-tuneup/scripts/audit.py'
spec = importlib.util.spec_from_file_location('settings_audit', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTest(unittest.TestCase):
    def test_claude_exact_duplicates_and_broad_rules(self):
        findings = audit.inspect('claude', {'permissions': {'allow': ['Bash(python3 *)', 'Read(file)', 'Read(file)', 'Bash(git status)']}})
        self.assertEqual([f['code'] for f in findings], ['broad_execution_allow', 'duplicate_rule'])

    def test_quote_variants_are_not_deduplicated(self):
        self.assertEqual(audit.inspect('claude', {'permissions': {'allow': ['Bash(cat "x")', "Bash(cat 'x')"]}}), [])

    def test_opencode_jsonc_preserves_strings_and_reports_global_allow(self):
        raw = '{/* comment */"url":"https://example.com/a,}","permission":{"*":"allow",},// comment\n}'
        data = json.loads(audit.jsonc(raw))
        self.assertEqual(data['url'], 'https://example.com/a,}')
        self.assertEqual(audit.inspect('opencode', data)[0]['code'], 'all_tools_allowed')

    def test_codex_profiles_are_audited_without_exposing_names(self):
        findings = audit.inspect('codex', {'profiles': {'private-project': {'sandbox_mode': 'danger-full-access'}}})
        self.assertEqual(findings, [{'code': 'sandbox_disabled', 'location': 'profiles[0].sandbox_mode'}])

    def test_cli_never_writes_or_echoes_secrets_even_on_parse_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            for content, code in [('{"apiKey":"secret-fixture","permissions":{"allow":["Bash(*)"]}}', 1),
                                  ('{"secret-fixture": invalid}', 2), ('[]', 2)]:
                path.write_text(content)
                result = subprocess.run([sys.executable, str(SCRIPT), '--provider', 'claude', '--settings', str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, code)
                self.assertNotIn('secret-fixture', result.stdout + result.stderr)
                self.assertEqual(path.read_text(), content)

    def test_malformed_types_fail(self):
        for data in ({'permissions': []}, {'permissions': {'allow': '*'}}):
            with self.assertRaises(ValueError):
                audit.inspect('claude', data)


if __name__ == '__main__':
    unittest.main()
