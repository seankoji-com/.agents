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

    def test_muse_profiles_are_audited_without_exposing_names(self):
        # Shapes and values verified against the Muse 1.4.7 binary: flat
        # settings.json, permissions.profiles with approval/filesystem/
        # network/reviewer dimensions.
        findings = audit.inspect('muse', {'permissions': {'schema_version': 1, 'profiles': {
            'private-profile': {'approval': 'allow_all', 'filesystem': 'unrestricted',
                                'network': {'mode': 'enabled'}, 'reviewer': 'none'}}}})
        self.assertEqual(findings, [
            {'code': 'approvals_disabled', 'location': 'permissions.profiles[0].approval'},
            {'code': 'sandbox_disabled', 'location': 'permissions.profiles[0].filesystem'},
            {'code': 'network_unrestricted', 'location': 'permissions.profiles[0].network.mode'},
        ])

    def test_muse_restrictive_profile_and_absent_permissions_are_clean(self):
        self.assertEqual(audit.inspect('muse', {'model': 'synthetic'}), [])
        self.assertEqual(audit.inspect('muse', {'permissions': {'schema_version': 1, 'profiles': {
            'safe': {'approval': 'on_request', 'filesystem': {'allow': []},
                     'network': {'mode': 'proxy_only'}, 'reviewer': 'human'}}}}), [])

    def test_muse_malformed_types_fail(self):
        for data in ({'permissions': []}, {'permissions': {'profiles': []}},
                     {'permissions': {'profiles': {'p': []}}},
                     {'permissions': {'profiles': {'p': {'approval': 1}}}},
                     {'permissions': {'profiles': {'p': {'network': {'mode': 1}}}}},
                     {'permissions': {'profiles': {'p': {'filesystem': 1}}}}):
            with self.assertRaises(ValueError):
                audit.inspect('muse', data)

    def test_muse_cli_exit_codes_and_adapter_listing(self):
        listed = subprocess.run([sys.executable, str(SCRIPT), '--list-adapters'], capture_output=True, text=True)
        self.assertEqual(json.loads(listed.stdout)['muse'], 'JSON')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'permissions': {'schema_version': 1, 'profiles': {
                'p': {'approval': 'allow_all'}}}}))
            result = subprocess.run([sys.executable, str(SCRIPT), '--provider', 'muse', '--settings', str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['findings'][0]['code'], 'approvals_disabled')


if __name__ == '__main__':
    unittest.main()
