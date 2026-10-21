"""Pass 23 regressions for R22-stage3-shard-1-01 and R22-container-shard-1-01.

Synthetic data only, no live models, containers or network. Acceptance publishes a stage
only when the adapter's commit-time reading equals the binding reserved before the validator
ran; a run, plan or other bound input that changed in between, or that cannot be reread,
stales the stage and keeps the charged receipt in history. Changes after that commit-time
observation are outside what acceptance can see. The container test module, run directly as
a script, reaches its unittest entrypoint only after every test class is defined.
"""
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import shared.job_acceptance as job_acceptance  # noqa: E402
from shared.job_acceptance import AcceptanceError, accept_stage, validate_stage  # noqa: E402
from shared.job_coordinator import create_pinned_job, publish_observation  # noqa: E402
from core.jobs.store import Store, strict_load  # noqa: E402

CONTAINER_TESTS = ROOT / 'tests' / 'test_bench_container.py'


class Pass23AcceptanceCommitBindingTests(unittest.TestCase):
    """A pinned direct imps stage accepted through the public lifecycle, with real installed gates."""

    def _install(self, base):
        home = base / 'home'; home.mkdir(exist_ok=True)
        env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(base / 'config'), 'XDG_STATE_HOME': str(base / 'state')}
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'imps', '--prefix', str(base / 'prefix'),
                               '--agents-root', str(base / 'agents')], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        version = Path(json.loads(proc.stdout)['data']['version_dir'])
        self.install_env = env
        return version, json.loads((version / 'install-manifest.json').read_text())

    def _run(self, state_root, version, manifest):
        from tests.support import CoreTestCase
        case = CoreTestCase(methodName='runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        case.state_root = state_root
        repo = case.make_repo()
        from tests.imps_plan_review_fixtures import admitted_gate
        run = admitted_gate(case, version, manifest, self.install_env, case.plan(repo,
            policy={'review': {'required': True, 'role': 'reviewer'}, 'checks': [
            {'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], 'cwd': str(repo)}]}))
        for req in run.state['brief']['requirements']:
            run.evidence(req['id'], run.scratch(f'{req["id"]}.txt', 'verified fixture evidence\n'))
        self.assertEqual(case.run_check(run)['result']['status'], 'passed')
        review_log = run.scratch('review.txt', 'reviewed current fixture binding; no findings\n')
        run.child(task_id='reviewer-s', status='completed')
        run.submit('review', {'binding': run.binding(), 'task_id': 'reviewer-s', 'perspective_id': 'default',
                              'verdict': 'approve', 'findings': [], 'artifacts': [str(review_log)]})
        self.assertTrue(run.validate().get('ready'))
        return run

    def test_input_changed_after_validator_before_commit_is_never_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            version, manifest = self._install(base)
            gate = version / 'scripts/validate_stage.py'
            stage_root = base / 'stage-state' / 's'
            run = self._run(stage_root, version, manifest)
            run_file = run.run_dir / 'run.json'
            original_run = run_file.read_bytes()
            requirement_ids = [r['id'] for r in run.state['brief']['requirements']]
            job_state = base / 'job-state'
            caller = {'installation_id': manifest['installation_id'], 'workflow': 'imps/issue',
                      'package_digest': manifest['package_digest'], 'actor': 'coordinator'}

            def job(name, contract):
                return {'schema_version': 1, 'job_id': name, 'installation_id': manifest['installation_id'], 'workflow': 'imps/issue',
                        'owner': {'id': 'owner'}, 'objective': 'accept one current stage gate', 'requirements': {'R1': 'stage gate current'},
                        'authorization': {'actions': ['read']}, 'constraints': ['offline fixture only'],
                        'dependencies': [{'key': 'imps', 'plugin': 'imps'}], 'pins': {},
                        'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
                        'stages': [{'id': 'stage', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                                    'execution_mode': 'direct', 'validator_dependency': 'imps', 'revision': 'r1',
                                    'validator_contract': contract}],
                        'tasks': [], 'decisions': [], 'history': [], 'metrics': {}, 'result_contract': {'schema_version': 1}}

            def accept(name, change=None, final_plan=None):
                """Accept through the public API; ``change`` runs after the validator returns, before the commit."""
                if final_plan is None:
                    contract = {'state_root': str(stage_root), 'run_id': run.run_id}
                    descriptor = {'state_root': str(stage_root), 'run_id': run.run_id}
                    argv = [str(gate), '--state-root', str(stage_root), '--run-id', run.run_id]
                else:
                    contract = {'final_plan': json.loads(final_plan.read_text())}
                    descriptor = {'state_root': str(stage_root.parent), 'final_plan': str(final_plan)}
                    argv = [str(gate), '--state-root', str(stage_root.parent), '--final-plan', str(final_plan)]
                create_pinned_job(job(name, contract), job_state, base / 'prefix', base / 'agents', base / 'config/workers.json')
                store = Store(job_state, name)
                source = base / f'{name}-invocation.json'; source.write_text(json.dumps(descriptor))
                observation = publish_observation(store, caller, 'stage', str(source))['path']
                real_invoke, invoked = job_acceptance._invoke, []

                def invoke(*args, **kwargs):
                    result = real_invoke(*args, **kwargs)  # the real pinned gate subprocess
                    invoked.append(result[1])
                    if change:
                        change()
                    return result
                with mock.patch.object(job_acceptance, '_invoke', invoke):
                    try:
                        outcome = accept_stage(store, caller, 'stage', argv, observation, 'r1')
                    except AcceptanceError as exc:
                        outcome = exc
                self.assertEqual(invoked, [True], name)  # the validator itself accepted the reserved inputs
                return outcome, store

            def stage_of(store):
                return next(s for s in store.load()['stages'] if s['id'] == 'stage')

            def assert_refused(name, outcome, store, message):
                self.assertIsInstance(outcome, AcceptanceError, name)
                self.assertIn(message, str(outcome), name)
                stage = stage_of(store)
                self.assertEqual((stage['status'], stage['acceptance']), ('stale', None), name)
                self.assertEqual(stage['acceptance_runs'], 1, name)  # the pass stays charged
                [entry] = stage['acceptance_history']
                receipt = strict_load(Path(entry['path']).read_bytes())  # immutable evidence is retained
                self.assertEqual(receipt['receipt_sha256'], entry['sha256'], name)
                local = validate_stage(store, 'stage', run_validator=False)
                self.assertFalse(local['accepted'], name)
                self.assertIn('lacks a current receipt', local['reason'], name)
                return receipt

            def restore():
                run_file.write_bytes(original_run)

            # Stable control: the reserved run bytes are still current at commit.
            receipt, store = accept('stable')
            self.assertTrue(receipt['accepted'], receipt)
            reserved = receipt['binding']
            self.assertEqual(reserved['extra_inputs'], {str(run_file): hashlib.sha256(original_run).hexdigest()})
            self.assertEqual(stage_of(store)['status'], 'accepted-at-snapshot')
            self.assertTrue(validate_stage(store, 'stage', run_validator=False)['accepted'])
            self.assertTrue(validate_stage(store, 'stage')['accepted'])

            # An ordinary imps state update lands after the validator returns and before the commit.
            def external_update():
                run.child(task_id='late-observer', status='completed')
            outcome, store = accept('run-updated', external_update)
            updated = run_file.read_bytes()
            self.assertNotEqual(updated, original_run)
            self.assertEqual([r['id'] for r in json.loads(updated)['brief']['requirements']], requirement_ids)
            kept = assert_refused('run-updated', outcome, store, 'changed before acceptance commit')
            # The receipt names the run bytes validated, never the new ones.
            self.assertEqual(kept['binding']['extra_inputs'], reserved['extra_inputs'])
            self.assertTrue(kept['accepted'])  # what the validator said about the reserved bytes, not current acceptance
            restore()

            # Unavailable and malformed commit-time readings fail closed as well.
            def missing():
                run_file.rename(run_file.with_name('run.json.moved'))
            outcome, store = accept('run-missing', missing)
            run_file.with_name('run.json.moved').rename(run_file)
            assert_refused('run-missing', outcome, store, 'lost its reserved state generation or evidence')

            outcome, store = accept('run-malformed', lambda: run_file.write_bytes(b'{not json'))
            assert_refused('run-malformed', outcome, store, 'lost its reserved state generation or evidence')
            restore()

            # Another adapter input: final-plan bytes that still satisfy the declared contract but changed.
            plan = base / 'final-plan.json'
            plan.write_text(json.dumps({'state_root': str(stage_root.parent), 'package_root': str(version),
                                        'required_stages': ['s'], 'stages': [{'id': 's', 'state_subdir': 's', 'run_id': run.run_id,
                                        'stage_sha256': hashlib.sha256(gate.read_bytes()).hexdigest()}]}))
            receipt, store = accept('plan-stable', final_plan=plan)
            self.assertTrue(receipt['accepted'], receipt)
            plan_bytes = plan.read_bytes()
            outcome, store = accept('plan-rewritten', lambda: plan.write_bytes(plan_bytes + b'\n'), final_plan=plan)
            assert_refused('plan-rewritten', outcome, store, 'changed before acceptance commit')
            plan.write_bytes(plan_bytes)

            # With the reserved bytes restored, the same lifecycle accepts again.
            receipt, store = accept('restored')
            self.assertTrue(receipt['accepted'], receipt)
            self.assertEqual(receipt['binding']['extra_inputs'], reserved['extra_inputs'])
            self.assertTrue(validate_stage(store, 'stage', run_validator=False)['accepted'])


def _stub_entrypoint_module(source):
    """The test module's top-level shape only: TestCase classes with empty test methods and its entrypoint.

    Order is preserved, so a script run reaches unittest.main exactly where the real module would.
    No production module is imported and no test body runs.
    """
    lines = ['import unittest', '']
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and any(ast.unparse(b) == 'unittest.TestCase' for b in node.bases):
            tests = [f.name for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name.startswith('test')]
            lines += [f'class {node.name}(unittest.TestCase):'] + [f'    def {name}(self):\n        pass' for name in tests]
            lines += ['    pass'] if not tests else []
        elif isinstance(node, ast.If) and ast.unparse(node.test) == "__name__ == '__main__'":
            lines.append(ast.unparse(node))
    return '\n'.join(lines) + '\n'


class Pass23ContainerDirectRunTests(unittest.TestCase):
    def _direct(self, source, *selected):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'test_bench_container.py'
            script.write_text(_stub_entrypoint_module(source))
            env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
            return subprocess.run([sys.executable, str(script), *selected], capture_output=True, text=True, env=env, timeout=120)

    def test_entrypoint_is_the_last_statement_after_every_class(self):
        tree = ast.parse(CONTAINER_TESTS.read_text())
        entrypoints = [i for i, node in enumerate(tree.body)
                       if isinstance(node, ast.If) and ast.unparse(node.test) == "__name__ == '__main__'"]
        self.assertEqual(entrypoints, [len(tree.body) - 1])
        self.assertFalse([node.name for node in tree.body[entrypoints[0] + 1:] if isinstance(node, ast.ClassDef)])

    def test_direct_script_run_sees_every_test_module_discovery_sees(self):
        source = CONTAINER_TESTS.read_text()
        tree = ast.parse(source)
        classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)
                   and any(ast.unparse(b) == 'unittest.TestCase' for b in node.bases)]
        # Module discovery (what scripts/run_tests.py uses) imports the complete file: the control.
        discovered = unittest.defaultTestLoader.loadTestsFromName('tests.test_bench_container').countTestCases()
        proc = self._direct(source)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ran = int(re.search(r'^Ran (\d+) tests?', proc.stderr, re.M).group(1))
        self.assertEqual(ran, discovered)
        # A class defined last can be selected by name when the file runs as a script.
        late = self._direct(source, classes[-1], '-v')
        self.assertEqual(late.returncode, 0, late.stderr)
        self.assertRegex(late.stderr, rf'\((__main__\.)?{classes[-1]}[.)]')
        late_tests = sum(isinstance(f, ast.FunctionDef) and f.name.startswith('test')
                         for f in next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classes[-1]).body)
        self.assertRegex(late.stderr, rf'(?m)^Ran {late_tests} tests?')


if __name__ == '__main__':
    unittest.main()
