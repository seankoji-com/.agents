"""scripts/conformance.py refuses operator arguments that would write outside conformance/results."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('conformance_script', ROOT / 'scripts' / 'conformance.py')
conformance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conformance)


class CollectArgumentTest(unittest.TestCase):
    def collect(self, **overrides):
        argv = {'run-id': 'run-0001', 'provider': 'provider-a', 'model': 'm', 'case': 'bugfix', 'repeat': '1',
                't3-version': '1.2.3+build.7', 'thread-id': 't'}
        argv.update(overrides)
        return conformance.main(['collect', *(f'--{k}={v}' for k, v in argv.items())])

    def test_path_arguments_are_rejected_before_anything_is_read_or_written(self):
        for name, value in (('t3-version', '../../escape'), ('t3-version', '/abs'), ('provider', 'a/b'),
                            ('case', '..'), ('run-id', '.hidden'), ('t3-version', ''), ('repeat', '-1')):
            with self.subTest(name=name, value=value):
                with self.assertRaises(SystemExit) as caught:
                    self.collect(**{name: value})
                self.assertIn('not a safe path segment', str(caught.exception))

    def test_counts_must_be_positive_or_zero(self):
        for overrides in ({'repeat': '0'}, {'interventions': '-1'}, {'elapsed': '-2.5'}):
            with self.subTest(**overrides):
                with self.assertRaises(SystemExit) as caught:
                    self.collect(**overrides)
                self.assertIn('counts from 1', str(caught.exception))

    def test_safe_version_passes_validation_and_fails_later_on_the_missing_run(self):
        with self.assertRaises((SystemExit, FileNotFoundError)) as caught:
            self.collect(**{'run-id': 'no-such-run-for-this-test'})
        self.assertNotIn('not a safe path segment', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
