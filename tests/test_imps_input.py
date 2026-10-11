import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/imps/scripts/input.py'
spec = importlib.util.spec_from_file_location('imps_input', SCRIPT)
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


class ImpsInput(unittest.TestCase):
    def test_modes_and_legacy_operations(self):
        cases = {'': 'doctor', 'fix the parser': 'run', 'run fix the parser': 'run',
                 '42 #43 51': 'issues', 'discussion #284': 'discussion',
                 '/imps:imp-agency security': 'audit', 'issue-mode 42': 'issues',
                 'blast-radius HEAD~1': 'blast-radius', 'resume run-42': 'resume'}
        for request, mode in cases.items():
            with self.subTest(request=request):
                self.assertEqual(inputs.route(request)['operation'], mode)
        self.assertEqual(inputs.route("fix the parser's whitespace")['arguments'],
                         "fix the parser's whitespace")
        panel = inputs.route('run --personas 42 43')
        self.assertTrue(panel['personas'])
        self.assertEqual(panel['issues'], [42, 43])
        for request in ('run', '$t3-imps run', '/imps:imps', 'run --personas'):
            value = inputs.route(request)
            self.assertEqual(value['operation'], 'doctor')
            self.assertEqual(value['arguments'], '')
        self.assertTrue(inputs.route('run --personas')['personas'])

    def test_discussion_url_normalization_and_wrong_hosts(self):
        url = 'https://github.com/example/project/discussions/284?x=y#discussioncomment-1'
        result = inputs.route(url)
        self.assertEqual(result['discussion'], {'repository': 'example/project', 'number': 284,
                         'url': 'https://github.com/example/project/discussions/284'})
        for wrong in ('https://github.com.evil/example/project/discussions/284',
                      'https://github.com/example/project/issues/284', 'discussion 0'):
            self.assertIsNone(inputs.discussion(wrong))
        with self.assertRaises(ValueError):
            inputs.route('discussion zero')

    def test_issue_handoff_validation_and_cap(self):
        result = inputs.route('issues {"issues": [42,43,42], "holdingBranch": "audit/example"}')
        self.assertEqual(result['issues'], [42, 43])
        self.assertEqual(result['holding_branch'], 'audit/example')
        for value in ({'issues': []}, {'issues': [True]}, {'issues': [0]},
                      {'issues': [42], 'holdingBranch': []},
                      {'issues': list(range(1, 202))}, {'issues': [42], 'publish': True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inputs.route('issues ' + json.dumps(value))

    def test_skill_invocations_preserve_issue_and_checklist_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'audit.md'
            path.write_text('- [ ] passes\n  Verify: python3 check.py\n  Done when: exit zero\n')
            for prefix in ('$t3-imps', '/t3-imps', 't3-imps'):
                result = inputs.route(prefix + ' --personas 42 43')
                self.assertEqual(result['operation'], 'issues')
                self.assertEqual(result['issues'], [42, 43])
                self.assertTrue(result['personas'])
                result = inputs.route(prefix + ' checklist ' + str(path))
                self.assertEqual(result['operation'], 'checklist')
                self.assertEqual(len(result['checklist']['items']), 1)
            path.write_text('# No checklist here\n')
            self.assertEqual(inputs.route(str(path))['checklist']['warnings'], ['no checklist items found'])

    def test_checklist_is_data_and_malformed_items_are_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'must not exist'
            checklist = Path(temp) / 'audit with spaces.md'
            checklist.write_text('- [ ] correct parser\n  Verify: touch ' + str(target) + '\n'
                                 '  Done when: output is correct\n'
                                 '- [x] previous claim\n'
                                 '- [ ] missing criterion\n  Verify: python3 check.py\n'
                                 '- [ ] duplicate command\n  Verify: first\n  Verify: second\n'
                                 '  Done when: passed\n'
                                 '```markdown\n- [ ] example\n  Verify: fake\n```\n')
            result = inputs.route(str(checklist))
            self.assertEqual(result['operation'], 'checklist')
            items = result['checklist']['items']
            self.assertEqual(len(items), 4)
            self.assertEqual([item['actionable'] for item in items], [True, False, False, False])
            self.assertEqual(items[2]['warnings'], ['missing done_when'])
            self.assertIn('duplicate Verify', items[3]['warnings'])
            self.assertFalse(target.exists())

    def test_cli_rejects_bad_inputs_and_missing_explicit_checklist(self):
        with tempfile.TemporaryDirectory() as temp:
            request = Path(temp) / 'request.json'
            for value in ([], {'text': 1}, {'text': 'checklist /does/not/exist'}):
                request.write_text(json.dumps(value))
                result = subprocess.run([sys.executable, str(SCRIPT), '--input', str(request)],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertFalse(json.loads(result.stdout)['ok'])
                self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
