"""The Homebrew formula template must pass the tap's `brew audit --strict`."""
import ast
import io
import re
import tokenize
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / 'packaging' / 't3-plugins.rb.tmpl').read_text()
WORKFLOW = (ROOT / '.github' / 'workflows' / 'release.yml').read_text()


class FormulaTemplateTest(unittest.TestCase):
    def condition(self, expression, *, ref, existing_tag, result, cancelled=False):
        values = {'github.ref': ref, 'github.event.inputs.existing_tag': existing_tag,
                  'needs.test.result': result, 'always()': True, 'cancelled()': cancelled}
        for key, value in values.items():
            expression = expression.replace(key, repr(value))
        expression = expression.replace('&&', ' and ').replace('||', ' or ')
        expression = re.sub(r'!(?!=)', 'not ', expression)
        self.assertFalse(any(token.type == tokenize.COMMENT for token in
                             tokenize.generate_tokens(io.StringIO(expression).readline)),
                         'comments are not valid inside a GitHub condition scalar')

        def value(node):
            # Interpret only the boolean/comparison subset used by these gates.
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
                operands = [value(item) for item in node.values]
                return all(operands) if isinstance(node.op, ast.And) else any(operands)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                return not value(node.operand)
            if isinstance(node, ast.Compare) and len(node.ops) == 1:
                left, right = value(node.left), value(node.comparators[0])
                if isinstance(node.ops[0], ast.Eq):
                    return left == right
                if isinstance(node.ops[0], ast.NotEq):
                    return left != right
            self.fail('unsupported release condition node: ' + ast.dump(node))

        return value(ast.parse(expression.strip(), mode='eval').body)

    def test_publication_requires_all_shards_or_an_explicit_existing_tag_retry(self):
        tests, release = WORKFLOW.split('\n  release:\n', 1)
        self.assertIn('    needs: test\n', release)
        gate = re.search(r'    if: >-\n((?:      .*\n)+)', release).group(1)
        self.assertIn('always()', gate, 'skipped test job must not suppress an existing-tag retry')
        gate = ' '.join(gate.split())
        test_gate = re.search(r'(?m)^    if: (.+)$', tests).group(1)
        for ref in ('refs/heads/master', 'refs/heads/feature'):
            for tag in ('', 'v0.10.0'):
                for result in ('success', 'failure', 'cancelled', 'skipped'):
                    for cancelled in (False, True):
                        with self.subTest(ref=ref, tag=tag, result=result, cancelled=cancelled):
                            args = dict(ref=ref, existing_tag=tag, result=result, cancelled=cancelled)
                            self.assertEqual(self.condition(test_gate, **args),
                                             ref == 'refs/heads/master' and not tag)
                            self.assertEqual(self.condition(gate, **args),
                                not cancelled and ref == 'refs/heads/master' and
                                (result == 'success' or bool(tag) and result == 'skipped'))

    def test_truth_table_rejects_a_missing_workflow_cancellation_guard(self):
        mutated = WORKFLOW.replace(' && !cancelled()', '')
        self.assertNotEqual(mutated, WORKFLOW)
        # Run the real contract test so this proves its cancelled=True cases fail.
        with patch.dict(globals(), WORKFLOW=mutated):
            result = unittest.TestResult()
            FormulaTemplateTest('test_publication_requires_all_shards_or_an_explicit_existing_tag_retry').run(result)
        self.assertFalse(result.wasSuccessful())
        self.assertTrue(result.failures)
        self.assertFalse(result.errors)
        self.assertTrue(any('cancelled=True' in str(case) for case, _ in result.failures))

    def test_condition_rejects_comments_instead_of_silently_ignoring_clauses(self):
        args = dict(ref='refs/heads/master', existing_tag='', result='success')
        for expression in ('True # always()', 'True # && !cancelled()'):
            with self.subTest(expression=expression), self.assertRaisesRegex(AssertionError, 'comments'):
                self.condition(expression, **args)
        self.assertTrue(self.condition("'#' == '#'", **args))

    def test_truth_table_rejects_disabled_retry_and_bypassed_guards_with_tokens_retained(self):
        for replacement in ('always() && !always() && !cancelled()',
                            'always() || !cancelled()'):
            with self.subTest(replacement=replacement):
                mutated = WORKFLOW.replace('always() && !cancelled()', replacement)
                self.assertNotEqual(mutated, WORKFLOW)
                with patch.dict(globals(), WORKFLOW=mutated):
                    result = unittest.TestResult()
                    FormulaTemplateTest('test_publication_requires_all_shards_or_an_explicit_existing_tag_retry').run(result)
                self.assertTrue(result.failures)
                self.assertFalse(result.errors)
                if '!always()' in replacement:
                    self.assertTrue(any("tag='v0.10.0'" in str(case) and
                                        "result='skipped'" in str(case) and
                                        'cancelled=False' in str(case)
                                        for case, _ in result.failures))

    def test_no_version_stanza_because_the_url_carries_it(self):
        # brew audit --strict: "`version` is redundant with version scanned from URL".
        self.assertIsNone(re.search(r'^\s*version\s', TEMPLATE, re.MULTILINE))
        self.assertIn('url "__URL__"', TEMPLATE)

    def test_every_placeholder_is_filled_by_the_release_workflow(self):
        placeholders = set(re.findall(r'__[A-Z0-9]+__', TEMPLATE))
        filled = set(re.findall(r's\|(__[A-Z0-9]+__)\|', WORKFLOW))
        self.assertEqual(placeholders, filled)

    def test_tap_branch_is_namespaced_to_this_formula(self):
        # The tap is shared: a bare release-vX.Y.Z collided with frugalbar's branch.
        self.assertIn('BRANCH="t3-plugins-release-${TAG}"', WORKFLOW)


if __name__ == '__main__':
    unittest.main()
