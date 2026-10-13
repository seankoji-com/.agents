"""Pass 21 Stage 3 regressions for R20-stage3-shard-4-01 and R20-stage3-shard-2-01.

Synthetic data only, no live models. An imps final plan whose stage rows repeat an ID,
omit one or name an invalid one must be refused before any snapshot or stage validator
runs, both by the final gate itself and by the generic acceptance adapter that binds it.
Unsafe job IDs given to the installed job CLI are invalid input (exit 2), not a crash.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.job_acceptance import AcceptanceError, _adapter

FINAL = ROOT / 'plugins/imps/scripts/validate_stage.py'


def load_final_gate():
    spec = importlib.util.spec_from_file_location('pass21_imps_validate_stage', FINAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob('*')) if p.is_file()}


class Pass21FinalPlanIdentityTests(unittest.TestCase):
    """R20-stage3-shard-4-01: every declared final gate runs exactly once, or none runs."""

    def setUp(self):
        self.gate = load_final_gate()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.stage_hash = hashlib.sha256(FINAL.read_bytes()).hexdigest()

    def row(self, sid, run_id, **extra):
        return {'id': sid, 'state_subdir': run_id, 'run_id': run_id, 'stage_sha256': self.stage_hash, **extra}

    def run_gate(self, stages, required):
        """Run validate_final with recorded synthetic subprocesses; return (exit, result, snapshots, validated)."""
        state_root = str(self.base / 'state')
        plan = self.base / 'final-plan.json'
        plan.write_text(json.dumps({'state_root': state_root, 'package_root': str(FINAL.parents[1]),
                                    'required_stages': required, 'stages': stages}))
        snapshots, validated = [], []

        def fake_run(argv, **_):
            run_id = argv[argv.index('--run-id') + 1]
            if 'snapshot' in argv:
                snapshots.append(run_id)
                return subprocess.CompletedProcess(argv, 0, json.dumps({'data': {'run': run_id}}), '')
            validated.append(run_id)
            accepted = run_id.startswith('good')
            return subprocess.CompletedProcess(argv, 0 if accepted else 1, json.dumps({'accepted': accepted}), '')

        out = mock.MagicMock()
        with mock.patch.object(self.gate.subprocess, 'run', side_effect=fake_run), \
                mock.patch.object(self.gate, 'print', out, create=True):
            code = self.gate.validate_final(plan, state_root)
        return code, json.loads(out.call_args[0][0]), snapshots, validated

    def assert_refused(self, stages, required):
        code, result, snapshots, validated = self.run_gate(stages, required)
        self.assertEqual(code, 1)
        self.assertIs(result['accepted'], False)
        self.assertEqual(list(result['requirement_outcomes']), ['imps-final-gate'])
        self.assertEqual((snapshots, validated), ([], []), 'an invalid final plan launched a gate')

    def test_duplicate_stage_ids_launch_no_gate_in_either_order(self):
        for runs in (('good', 'bad'), ('bad', 'good'), ('good', 'good-2')):
            with self.subTest(runs=runs):
                self.assert_refused([self.row('s', runs[0]), self.row('s', runs[1])], ['s'])
                self.assert_refused([self.row('s', runs[0]), self.row('s', runs[1]), self.row('t', 'good-t')], ['s', 't'])

    def test_missing_extra_and_invalid_stage_identities_launch_no_gate(self):
        good_s, good_t = self.row('s', 'good-s'), self.row('t', 'good-t')
        cases = {
            'missing declaration': ([good_s], ['s', 't']),
            'extra declaration': ([good_s, good_t], ['s']),
            'duplicate requirement': ([good_s, good_t], ['s', 's', 't']),
            'null id': ([self.row(None, 'good-n')], [None]),
            'empty id': ([self.row('', 'good-e')], ['']),
            'numeric id': ([self.row(7, 'good-7')], [7]),
            'missing id': ([{k: v for k, v in good_s.items() if k != 'id'}], [None]),
            'list id': ([self.row(['s'], 'good-l')], [['s']]),
            'non-object row': ([good_s, 't'], ['s', 't']),
            'stages not a list': ({'s': good_s}, ['s']),
            'required not a list': ([good_s], 's'),
            'empty plan': ([], []),
            'later row escapes state root': ([good_s, self.row('t', 'good-t', state_subdir='../escape')], ['s', 't']),
            'later row selects a package': ([good_s, self.row('t', 'good-t', plugin_root='/other')], ['s', 't']),
            'later row lacks a run id': ([good_s, {**good_t, 'run_id': 9}], ['s', 't']),
            'later row unbound validator': ([good_s, {**good_t, 'stage_sha256': 'x'}], ['s', 't']),
        }
        for name, (stages, required) in cases.items():
            with self.subTest(name):
                self.assert_refused(stages, required)

    def test_unique_stage_gates_are_all_observed(self):
        code, result, snapshots, validated = self.run_gate([self.row('s', 'good-s'), self.row('t', 'good-t')], ['s', 't'])
        self.assertEqual((code, result['accepted']), (0, True))
        self.assertEqual(validated, ['good-s', 'good-t'])
        # Pass 22: every binding is reserved before any gate and rechecked after the last one.
        self.assertEqual(snapshots, ['good-s', 'good-t', 'good-s', 'good-s', 'good-t', 'good-t', 'good-s', 'good-t'])
        self.assertEqual(sorted(result['requirement_outcomes']), ['imps-stage-s', 'imps-stage-t'])
        for runs in (('good', 'bad'), ('bad', 'good')):
            with self.subTest(runs=runs):
                code, result, _, validated = self.run_gate([self.row('s', runs[0]), self.row('t', runs[1])], ['s', 't'])
                self.assertEqual((code, result['accepted']), (1, False))
                self.assertEqual(validated, list(runs))
                self.assertEqual({sid: row['status'] for sid, row in result['requirement_outcomes'].items()},
                                 {'imps-stage-s': 'passed' if runs[0] == 'good' else 'failed',
                                  'imps-stage-t': 'passed' if runs[1] == 'good' else 'failed'})
        # Required order chooses execution order; every declared gate still runs once.
        _, _, _, validated = self.run_gate([self.row('s', 'good-s'), self.row('t', 'good-t')], ['t', 's'])
        self.assertEqual(validated, ['good-t', 'good-s'])

    def test_state_and_package_binding_still_refuse_before_any_gate(self):
        self.assertEqual(self.run_gate([self.row('s', 'good-s')], ['s'])[0], 0)
        plan = self.base / 'final-plan.json'
        with mock.patch.object(self.gate.subprocess, 'run', side_effect=AssertionError('gate launched')), \
                mock.patch.object(self.gate, 'print', create=True):
            self.assertEqual(self.gate.validate_final(plan, str(self.base / 'other-state')), 1)
            data = json.loads(plan.read_text()); data['package_root'] = str(self.base)
            plan.write_text(json.dumps(data))
            self.assertEqual(self.gate.validate_final(plan, data['state_root']), 1)


class Pass21AdapterFinalPlanTests(unittest.TestCase):
    """R20-stage3-shard-4-01: the generic adapter refuses an ambiguous declared final plan."""

    def setUp(self):
        from tests.test_jobs_review import JobReviewTests
        self.fx = JobReviewTests()

    def test_adapter_refuses_duplicate_and_invalid_final_stage_identities(self):
        """Exact coverage is the final gate's own pre-launch check (Pass21FinalPlanIdentityTests)."""
        from shared.job_coordinator import create_pinned_job, pinned_store, publish_observation
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            version, manifest, prefix, agents, state = self.fx.install(root, 'imps')
            stage_hash = hashlib.sha256((version / 'scripts/validate_stage.py').read_bytes()).hexdigest()
            row = lambda sid, run: {'id': sid, 'state_subdir': run, 'run_id': run, 'stage_sha256': stage_hash}
            gates, plan, descriptor = str(root / 'gates'), root / 'final-plan.json', root / 'descriptor.json'
            descriptor.write_text(json.dumps({'state_root': gates, 'final_plan': str(plan)}))
            caller = {'installation_id': manifest['installation_id'], 'package_digest': manifest['package_digest'],
                      'actor': 'coordinator'}
            argv = [str(version / 'scripts/validate_stage.py'), '--state-root', gates, '--final-plan', str(plan)]

            def adapt(job_id, declared):
                plan.write_text(json.dumps({'state_root': gates, 'package_root': str(version), **declared}))
                job = self.fx.base_job(job_id)
                job.update(installation_id=manifest['installation_id'], pins={}, tasks=[],
                           dependencies=[{'key': 'imps', 'plugin': 'imps'}])
                job['stages'][0].update(execution_mode='direct', validator_dependency='imps',
                                        validator_contract={'final_plan': declared})
                create_pinned_job(job, state, prefix, agents, root / 'config/workers.json')
                store = pinned_store(state, job_id)
                ref = publish_observation(store, dict(caller, workflow=job['workflow']), 's0', str(descriptor))
                return _adapter(store.load(), store.load()['stages'][0], argv, ref['path'])

            program, _, binding = adapt('final-unique', {'required_stages': ['s', 't'],
                                                         'stages': [row('s', 'good'), row('t', 'bad')]})
            self.assertEqual(os.path.realpath(program), os.path.realpath(Path(argv[0])))
            self.assertEqual(binding['expected_outcome_ids'], ['imps-stage-s', 'imps-stage-t'])
            refused = {
                'final-duplicate': {'required_stages': ['s'], 'stages': [row('s', 'good'), row('s', 'bad')]},
                'final-duplicate-reversed': {'required_stages': ['s'], 'stages': [row('s', 'bad'), row('s', 'good')]},
                'final-duplicate-required': {'required_stages': ['s', 's'], 'stages': [row('s', 'good'), row('t', 'bad')]},
                'final-null-id': {'required_stages': [None], 'stages': [row(None, 'good')]},
                'final-numeric-id': {'required_stages': ['s', 7], 'stages': [row('s', 'good'), row(7, 'bad')]},
                'final-empty-id': {'required_stages': [''], 'stages': [row('', 'good')]},
                'final-non-object': {'required_stages': ['s'], 'stages': [row('s', 'good'), 'bad']},
            }
            for job_id, declared in refused.items():
                with self.subTest(job_id), \
                        mock.patch('shared.job_acceptance._invoke', side_effect=AssertionError('validator ran')):
                    with self.assertRaisesRegex(AcceptanceError, 'final-plan stage identities'):
                        adapt(job_id, declared)


class Pass21JobCliUnsafeIdTests(unittest.TestCase):
    """R20-stage3-shard-2-01: unsafe job IDs exit 2 through the structured CLI error path."""

    def setUp(self):
        from tests.test_jobs_review import JobReviewTests
        self.fx = JobReviewTests()

    def test_installed_cli_rejects_unsafe_job_ids_without_traceback_or_state_access(self):
        from shared.job_coordinator import create_pinned_job
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            version, manifest, prefix, agents, state = self.fx.install(root, 'ape')
            job = self.fx.base_job('cli-safe-id')
            job['installation_id'] = manifest['installation_id']
            job['pins'] = {}
            create_pinned_job(job, state, prefix, agents, root / 'config' / 'workers.json')
            descriptor = root / 'input.json'; descriptor.write_text('{}')
            script = str(version / 'shared' / 'job_cli.py')
            cli = lambda *args: subprocess.run([sys.executable, script, *args], capture_output=True, text=True)
            before = tree(root)
            control = cli('status', '--state-root', str(state), '--job', job['job_id'])
            self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
            self.assertEqual(json.loads(control.stdout)['job_id'], job['job_id'])
            self.assertEqual(tree(root), before)
            for unsafe in ('../bad', '../' + job['job_id'], 'a/b', '.hidden', '', 'x' * 129, 'bad id'):
                for command in (('status',), ('overview',), ('decision', '--input', str(descriptor)),
                                ('create', '--prefix', str(prefix), '--agents-root', str(agents), '--input', str(descriptor))):
                    with self.subTest(job=unsafe, command=command[0]):
                        proc = cli(command[0], '--state-root', str(state), '--job', unsafe, *command[1:])
                        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (2, '', 'job_error: unsafe job id\n'))
                        self.assertEqual(tree(root), before)
            # A safe but unknown ID still reaches the store and is refused as invalid input.
            missing = cli('status', '--state-root', str(state), '--job', 'absent-job')
            self.assertEqual(missing.returncode, 2)
            self.assertTrue(missing.stderr.startswith('job_error: '), missing.stderr)
            self.assertNotIn('Traceback', missing.stderr)
            self.assertEqual(tree(root), before)


if __name__ == '__main__':
    unittest.main()
