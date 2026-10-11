"""scripts/run_tests.py runs modules side by side and fails if any module fails."""
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('run_tests_script', ROOT / 'scripts' / 'run_tests.py')
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

PASSING = 'import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n    def test_b(self): pass\n'
FAILING = 'import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.fail("planted")\n'
EMPTY = 'import unittest\n'


class RunTestsTest(unittest.TestCase):
    def suite(self, **modules):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tests = Path(tmp.name)
        for name, body in modules.items():
            (tests / f'{name}.py').write_text(body)
        patcher = patch.object(runner, 'TESTS', tests)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = runner.main(['-j', '2', *argv])
        return code, out.getvalue(), err.getvalue()

    def test_counts_every_module_and_passes(self):
        self.suite(test_one=PASSING, test_two=PASSING, helper=FAILING)
        code, out, _ = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn('4 tests in 2 modules', out)

    def test_a_failing_module_fails_the_run_and_prints_its_output(self):
        self.suite(test_one=PASSING, test_bad=FAILING)
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('FAIL test_bad', out)
        self.assertIn('planted', err)

    def test_a_module_that_runs_nothing_is_a_failure(self):
        self.suite(test_empty=EMPTY)
        code, out, _ = self.run_main()
        self.assertEqual(code, 1, out)

    def test_patterns_select_modules(self):
        self.suite(test_one=PASSING, test_bad=FAILING)
        code, out, _ = self.run_main('test_one')
        self.assertEqual(code, 0, out)
        self.assertNotIn('test_bad', out)
        with self.assertRaises(SystemExit):
            self.run_main('test_nothing_matches')


if __name__ == '__main__':
    unittest.main()
