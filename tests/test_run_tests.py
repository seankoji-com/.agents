"""scripts/run_tests.py runs modules side by side and fails if any module fails."""
import contextlib
import importlib.util
import io
import json
import re
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
HANGING = 'import time, unittest\nclass T(unittest.TestCase):\n    def test_a(self): time.sleep(30)\n'


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
        hints = patch.object(runner, 'DURATIONS', tests / 'durations.json')
        hints.start()
        self.addCleanup(hints.stop)
        return tests

    def test_measured_long_modules_precede_tiny_modules_without_omissions(self):
        tests = self.suite(test_tiny=PASSING, test_new=PASSING + '# padding\n' * 100,
                           test_review_perspectives=PASSING, test_task_b_grader=PASSING,
                           test_review_regressions=PASSING, test_tasks=PASSING)
        names = ['test_review_perspectives', 'test_task_b_grader', 'test_review_regressions', 'test_tasks']
        runner.DURATIONS.write_text(json.dumps({f'{name}.py': 40 - i for i, name in enumerate(names)}))
        expected = [tests / f'{name}.py' for name in names] + [tests / 'test_new.py', tests / 'test_tiny.py']
        self.assertEqual(runner.modules([]), expected)
        self.assertEqual(runner.modules(['test_review*']), [expected[0], expected[2]])
        code, out, _ = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn('12 tests in 6 modules', out)

    def test_missing_or_invalid_hints_use_size_and_name_fallback(self):
        tests = self.suite(test_b=PASSING, test_a=PASSING, test_large=PASSING + '# padding\n')
        expected = [tests / 'test_large.py', tests / 'test_a.py', tests / 'test_b.py']
        self.assertEqual(runner.modules([]), expected)
        for data in ('{', '[]', 'null', '{"test_b.py": "slow"}',
                     '{"test_b.py": true}', '{"test_b.py": -5}',
                     '{"test_b.py": 0}', '{"test_b.py": NaN}', '{"test_b.py": Infinity}'):
            with self.subTest(data=data):
                runner.DURATIONS.write_text(data)
                self.assertEqual(runner.modules([]), expected)

    def test_stale_hints_never_add_modules_or_hide_new_modules(self):
        tests = self.suite(test_new=PASSING, test_known=PASSING)
        runner.DURATIONS.write_text(json.dumps({'test_deleted.py': 1000, 'test_known.py': 20}))
        self.assertEqual(runner.modules([]), [tests / 'test_known.py', tests / 'test_new.py'])

    def test_scheduled_real_failure_empty_and_hang_still_run_every_module(self):
        self.suite(test_pass=PASSING, test_fail=FAILING, test_empty=EMPTY, test_hang=HANGING)
        runner.DURATIONS.write_text(json.dumps({'test_hang.py': 100, 'test_empty.py': 90, 'test_fail.py': 80}))
        code, out, err = self.run_main('--timeout', '1')
        self.assertEqual(code, 1, out)
        self.assertIn('3 tests in 4 modules', out)
        self.assertIn('3 module(s) failed', out)
        for name in ('test_fail', 'test_empty', 'test_hang'):
            self.assertIn(f'FAIL {name}', out)
            self.assertIn(f'===== {name} =====', err)
        self.assertIn('planted', err)
        self.assertIn('stopped after 1s', err)

    def test_modules_keep_separate_interpreter_state(self):
        body = ('import builtins, unittest\nclass T(unittest.TestCase):\n'
                '    def test_state(self):\n'
                '        self.assertFalse(hasattr(builtins, "scheduler_fixture"))\n'
                '        builtins.scheduler_fixture = True\n')
        self.suite(test_one=body, test_two=body)
        code, out, _ = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn('2 tests in 2 modules', out)

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

    def test_a_module_past_the_timeout_is_stopped_and_fails(self):
        self.suite(test_one=PASSING, test_hang=HANGING)
        code, out, err = self.run_main('--timeout', '2')
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL test_hang', out)
        self.assertIn('stopped after 2s', err)
        self.assertIn('2 tests in 2 modules', out)

    def test_patterns_select_modules(self):
        self.suite(test_one=PASSING, test_bad=FAILING)
        code, out, _ = self.run_main('test_one')
        self.assertEqual(code, 0, out)
        self.assertNotIn('test_bad', out)
        with self.assertRaises(SystemExit):
            self.run_main('test_nothing_matches')

    def test_shards_run_every_filtered_module_once_and_keep_failures(self):
        self.suite(test_selected_one=PASSING, test_selected_two=PASSING,
                   test_selected_bad=FAILING, test_selected_empty=EMPTY,
                   test_selected_hang=HANGING, test_omitted=FAILING)
        expected = runner.modules(['test_selected*'])
        executed, failures, total = [], [], 0
        for index in range(3):
            with patch.object(runner, 'run', wraps=runner.run) as run:
                code, out, err = self.run_main('--shard-index', str(index), '--shard-count', '3',
                                               '--timeout', '1', 'test_selected*')
            paths = [call.args[0] for call in run.call_args_list]
            self.assertCountEqual(paths, expected[index::3])
            executed.extend(paths)
            total += int(out.split(' tests in ')[0].splitlines()[-1])
            if code:
                failures.append(err)
        self.assertCountEqual(executed, expected)
        self.assertEqual(len(executed), len(set(executed)))
        self.assertEqual(total, 5)
        self.assertIn('planted', '\n'.join(failures))
        self.assertIn('===== test_selected_empty =====', '\n'.join(failures))
        self.assertIn('stopped after 1s', '\n'.join(failures))

    def test_invalid_or_empty_shards_fail_before_running_tests(self):
        self.suite(test_one=PASSING)
        for flags in (('--shard-count', '0'), ('--shard-index', '-1'),
                      ('--shard-index', '1'), ('--shard-index', '2', '--shard-count', '2'),
                      ('--shard-index', '1', '--shard-count', '2')):
            with self.subTest(flags=flags), patch.object(runner, 'run') as run:
                with self.assertRaises(SystemExit) as raised:
                    self.run_main(*flags)
                self.assertEqual(raised.exception.code, 2)
                run.assert_not_called()

    def test_ci_matrix_covers_every_shard_consumed_by_the_test_command(self):
        def check(text):
            matrix = re.search(r'(?m)^        shard: (\[[^\n]+\])$', text)
            command = re.search(r'(?m)^        run: python3 scripts/run_tests.py '
                                r'--shard-index "\$TEST_SHARD_INDEX" --shard-count (\d+)$', text)
            self.assertIsNotNone(matrix, 'CI must declare every shard index')
            self.assertIsNotNone(command, 'CI must run the full shard without test filters')
            self.assertIn('TEST_SHARD_INDEX: ${{ matrix.shard }}', text)
            self.assertEqual(sorted(json.loads(matrix.group(1))), list(range(int(command.group(1)))))

        for name in ('test.yml', 'release.yml'):
            with self.subTest(workflow=name):
                workflow = (ROOT / '.github' / 'workflows' / name).read_text()
                check(workflow)
                # Removing the highest shard leaves every remaining index valid to the
                # runner, but silently omits tests unless the workflow contract catches it.
                indices = re.search(r'(?m)^        shard: (\[[^\n]+\])$', workflow).group(1)
                with self.assertRaises(AssertionError):
                    check(workflow.replace(indices, json.dumps(json.loads(indices)[:-1])))


if __name__ == '__main__':
    unittest.main()
