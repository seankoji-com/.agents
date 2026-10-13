"""Terminal captures run real commands in a throwaway home and never write private strings."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
# Built from parts so this file never contains a literal machine path (test_contract checks).
HOME, USERS = '/' + 'home/', '/' + 'Users/'
sys.path.insert(0, str(ROOT / 'scripts'))
import capture_terminal  # noqa: E402


class RedactionTest(unittest.TestCase):
    def test_machine_paths_become_placeholders(self):
        pairs = capture_terminal.machine_strings('/tmp/t3-capture-abc/hm')
        text = ('{"entry": "/tmp/t3-capture-abc/hm/.local/share/t3-plugins/imps/current/entry.md"} '
                f'{capture_terminal.ROOT}/bin/t3-plugins')
        out = capture_terminal.redact(text, pairs)
        self.assertIn('"~/.local/share/t3-plugins/imps/current/entry.md"', out)
        self.assertIn('<checkout>/bin/t3-plugins', out)
        self.assertNotIn('/tmp/', out)

    def test_longer_paths_are_replaced_before_their_prefixes(self):
        out = capture_terminal.redact('/a/b/c and /a/b', [('/a/b', 'X'), ('/a/b/c', 'Y')])
        self.assertEqual(out, 'X/c and X')  # caller order is kept; machine_strings sorts
        pairs = sorted([('/a/b', 'X'), ('/a/b/c', 'Y')], key=lambda p: -len(p[0]))
        self.assertEqual(capture_terminal.redact('/a/b/c and /a/b', pairs), 'Y and X')

    def test_leaks_are_found(self):
        cases = {
            'mail me at someone@example.org': 'email',
            'token ghp_' + 'a' * 36: 'token',
            f'see {HOME}alice/src': 'home directory',
            f'see {USERS}bob/src': 'home directory',
            'scratch at /tmp/xyz/file': 'temporary path',
            'build host box42 failed': 'host name',
            'owner /srv/alice/repo': 'user name',
        }
        for text, label in cases.items():
            found = capture_terminal.leaks(text, user='alice', host='box42')
            self.assertTrue(any(f.startswith(label) for f in found), (text, found))

    def test_placeholders_and_public_slugs_are_not_leaks(self):
        text = ('Read ~/.local/share/t3-plugins/imps/current/entry.md and run: doctor\n'
                '<home>/project <checkout>/bin https://github.com/alice-com/t3-plugins')
        self.assertEqual(capture_terminal.leaks(text, user='alice', host='box42'), [])

    def test_a_leak_writes_nothing(self):
        session = {'name': 'x', 'summary': 's', 'recorded': '2026-10-13', 'commit': 'abc',
                   'environment': {'os': 'Linux', 'python': '3.12', 'home': 'h'},
                   'steps': [{'command': 'echo', 'exit': 0, 'seconds': 0.0,
                              'lines': [[0.0, f'oops {HOME}carol/secret']]}]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'rec'
            with self.assertRaisesRegex(capture_terminal.LeakError, 'home directory'):
                capture_terminal.write({'x': session}, out)
            self.assertFalse(out.exists())


class RecordTest(unittest.TestCase):
    def test_commands_run_in_a_fresh_home_and_output_is_redacted(self):
        sessions = {'probe': ('Probe.', ['echo "$HOME"', 'pwd', 't3-plugins list', ('exit 3', 3)])}
        with mock.patch.object(capture_terminal.dt, 'date') as date:
            date.today.return_value.isoformat.return_value = '2026-10-13'
            result = capture_terminal.record(sessions)['probe']
        steps = {s['command']: s for s in result['steps']}
        self.assertEqual(steps['echo "$HOME"']['lines'][0][1], '~')
        self.assertEqual(steps['pwd']['lines'][0][1], '~/project')
        names = [text.split()[0] for _, text in steps['t3-plugins list']['lines']]
        manifests = sorted(p.parent.name for p in (ROOT / 'plugins').glob('*/plugin.json'))
        self.assertEqual(names, manifests)
        self.assertEqual(steps['exit 3']['exit'], 3)
        self.assertEqual(steps['exit 3']['expected_exit'], 3)
        self.assertEqual(result['recorded'], '2026-10-13')
        for step in result['steps']:
            offsets = [t for t, _ in step['lines']]
            self.assertEqual(offsets, sorted(offsets))
            self.assertTrue(all(0 <= t <= step['seconds'] for t in offsets))
        self.assertEqual(capture_terminal.leaks(json.dumps(result)), [])

    def test_transcript_text_is_complete(self):
        session = {'name': 'n', 'summary': 's', 'recorded': '2026-10-13', 'commit': 'abc',
                   'environment': {'os': 'Linux', 'python': '3.12', 'home': 'empty'},
                   'steps': [{'command': 'echo hi', 'exit': 0, 'seconds': 0.01, 'lines': [[0.0, 'hi']]}]}
        text = capture_terminal.transcript_text(session)
        self.assertIn('$ echo hi\nhi\n# exit 0 after 0.01s\n', text)


if __name__ == '__main__':
    unittest.main()
