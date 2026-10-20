"""Pass 22 Stage 3 regressions for R21-stage3-shard-2-01, -3-01 and -4-01 (one case).

Synthetic data only, no live models. The imps final gate reserves every declared stage
binding before any stage gate runs, runs each gate at its reserved binding, and rechecks
the whole set after the last gate. An earlier stage that changes while a later gate runs,
a shared change between stage windows, or an unavailable or malformed final snapshot is
refused and names the affected stage. Changes after the final observation are outside
what the gate can see.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import shared.job_acceptance as job_acceptance  # noqa: E402
from shared.job_acceptance import accept_stage, validate_stage  # noqa: E402
from shared.job_coordinator import create_pinned_job, publish_observation  # noqa: E402
from core.jobs.store import Store  # noqa: E402

FINAL = ROOT / 'plugins/imps/scripts/validate_stage.py'


def load_gate(path, name='pass22_imps_validate_stage'):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, 'path', list(sys.path)):
        spec.loader.exec_module(module)
    return module


class Pass22FinalFreshnessTests(unittest.TestCase):
    """validate_final with recorded synthetic snapshot and stage-gate subprocesses."""

    def setUp(self):
        self.gate = load_gate(FINAL)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.stage_hash = hashlib.sha256(FINAL.read_bytes()).hexdigest()

    def row(self, sid):
        return {'id': sid, 'state_subdir': sid, 'run_id': 'run-' + sid, 'stage_sha256': self.stage_hash}

    def run_gate(self, required=('s', 't'), on_call=None, snapshot=None, bad=()):
        """Return (exit, result, calls). ``on_call(kind, sid, phase_index, generations)`` mutates state."""
        state_root = str(self.base / 'state')
        plan = self.base / 'final-plan.json'
        plan.write_text(json.dumps({'state_root': state_root, 'package_root': str(FINAL.parents[1]),
                                    'required_stages': list(required), 'stages': [self.row(s) for s in sorted(required)]}))
        generations = {sid: 0 for sid in required}
        generations['shared'] = 0
        calls = []

        def fake_run(argv, **_):
            sid = argv[argv.index('--run-id') + 1][len('run-'):]
            kind = 'snapshot' if 'snapshot' in argv else 'validate'
            index = sum(1 for k, s in calls if (k, s) == (kind, sid))
            calls.append((kind, sid))
            if on_call:
                on_call(kind, sid, index, generations)
            if kind == 'snapshot':
                if snapshot:
                    replaced = snapshot(sid, index, generations)
                    if replaced is not None:
                        return subprocess.CompletedProcess(argv, *replaced)
                data = {'run': sid, 'generation': generations[sid], 'shared': generations['shared']}
                return subprocess.CompletedProcess(argv, 0, json.dumps({'data': data}), '')
            accepted = sid not in bad
            return subprocess.CompletedProcess(argv, 0 if accepted else 1, json.dumps({'accepted': accepted}), '')

        out = mock.MagicMock()
        with mock.patch.object(self.gate.subprocess, 'run', side_effect=fake_run), \
                mock.patch.object(self.gate, 'print', out, create=True):
            code = self.gate.validate_final(plan, state_root)
        return code, json.loads(out.call_args[0][0]), calls

    def statuses(self, result):
        return {sid: row['status'] for sid, row in result['requirement_outcomes'].items()}

    def test_stable_gates_reserve_every_binding_first_and_recheck_all_last(self):
        for required in (('s', 't'), ('t', 's')):
            with self.subTest(required=required):
                code, result, calls = self.run_gate(required)
                first, second = required
                self.assertEqual((code, result['accepted']), (0, True))
                self.assertEqual(calls, [('snapshot', first), ('snapshot', second),
                                         ('snapshot', first), ('validate', first), ('snapshot', first),
                                         ('snapshot', second), ('validate', second), ('snapshot', second),
                                         ('snapshot', first), ('snapshot', second)])
                self.assertEqual(self.statuses(result), {'imps-stage-s': 'passed', 'imps-stage-t': 'passed'})
                self.assertEqual(result['final_binding'], {'s': 'current', 't': 'current'})
                self.assertEqual([r['stage_id'] for r in result['current_gate']], list(required))

    def test_earlier_stage_changed_during_later_gate_is_refused_in_either_order(self):
        for required in (('s', 't'), ('t', 's')):
            earlier, later = required
            def change_earlier(kind, sid, index, generations):
                if (kind, sid) == ('validate', later):
                    generations[earlier] += 1
            with self.subTest(required=required):
                code, result, calls = self.run_gate(required, change_earlier)
                self.assertEqual((code, result['accepted']), (1, False))
                self.assertEqual(self.statuses(result), {'imps-stage-' + earlier: 'failed', 'imps-stage-' + later: 'passed'})
                evidence = result['requirement_outcomes']['imps-stage-' + earlier]['evidence']
                self.assertEqual(evidence['final_binding'], 'changed after its gate')
                self.assertEqual(evidence['stage_id'], earlier)  # the gate's own evidence is retained
                self.assertEqual(result['final_binding'], {earlier: 'changed after its gate', later: 'current'})
                self.assertEqual(calls[-2:], [('snapshot', earlier), ('snapshot', later)])

    def test_shared_generation_change_between_stage_windows_is_refused(self):
        # After s's post-check and before t's pre-check every binding moves; t's fresh pre-check
        # no longer equals its reservation, so t never runs on unreserved inputs.
        def shared_change(kind, sid, index, generations):
            if (kind, sid, index) == ('snapshot', 't', 1):
                generations['shared'] += 1
        code, result, calls = self.run_gate(('s', 't'), shared_change)
        self.assertEqual((code, result['accepted']), (1, False))
        self.assertEqual(list(result['requirement_outcomes']), ['imps-final-gate'])
        self.assertIn('before its gate for t', result['requirement_outcomes']['imps-final-gate']['evidence'])
        self.assertNotIn(('validate', 't'), calls)
        # A change between reservations and the first gate is refused the same way.
        def early_change(kind, sid, index, generations):
            if (kind, sid, index) == ('snapshot', 't', 0):
                generations['s'] += 1
        code, result, calls = self.run_gate(('s', 't'), early_change)
        self.assertEqual((code, result['accepted']), (1, False))
        self.assertIn('before its gate for s', result['requirement_outcomes']['imps-final-gate']['evidence'])
        self.assertEqual([c for c in calls if c[0] == 'validate'], [])

    def test_change_during_own_gate_is_refused(self):
        for target in ('s', 't'):
            def own_change(kind, sid, index, generations):
                if (kind, sid) == ('validate', target):
                    generations[target] += 1
            with self.subTest(target=target):
                code, result, _ = self.run_gate(('s', 't'), own_change)
                self.assertEqual((code, result['accepted']), (1, False))
                self.assertIn('changed during final gate for ' + target,
                              result['requirement_outcomes']['imps-final-gate']['evidence'])

    def test_missing_malformed_or_unavailable_final_snapshot_fails_that_stage(self):
        variants = {
            'unavailable': (1, '', 'snapshot failed'),
            'not json': (0, 'not json', ''),
            'no data': (0, json.dumps({'ok': True}), ''),
            'data not an object': (0, json.dumps({'data': ['s']}), ''),
            'empty data': (0, json.dumps({'data': {}}), ''),
            'not an object': (0, json.dumps(['data']), ''),
        }
        for name, reply in variants.items():
            for target in ('s', 't'):
                with self.subTest(name, target=target):
                    final_only = lambda sid, index, _g: reply if (sid, index) == (target, 3) else None
                    code, result, _ = self.run_gate(('s', 't'), snapshot=final_only)
                    other = 't' if target == 's' else 's'
                    self.assertEqual((code, result['accepted']), (1, False))
                    self.assertEqual(self.statuses(result), {'imps-stage-' + target: 'failed', 'imps-stage-' + other: 'passed'})
                    reason = result['final_binding'][target]
                    self.assertTrue(reason.startswith('final binding ') and ('for ' + target) in reason, reason)
                    self.assertEqual(result['final_binding'][other], 'current')
        # Reservation, pre-check and post-check snapshots fail closed and name their stage too.
        for index, phase in ((0, 'reserved'), (1, 'pre-check'), (2, 'post-check')):
            for name, reply in variants.items():
                with self.subTest(name, phase=phase):
                    code, result, _ = self.run_gate(('s', 't'), snapshot=lambda sid, i, _g: reply if (sid, i) == ('t', index) else None)
                    self.assertEqual((code, result['accepted']), (1, False))
                    self.assertIn(phase + ' binding', result['requirement_outcomes']['imps-final-gate']['evidence'])
                    self.assertIn('for t', result['requirement_outcomes']['imps-final-gate']['evidence'])

    def test_honest_and_failing_gate_evidence_is_retained_with_fresh_bindings(self):
        for bad in (('s',), ('t',), ('s', 't')):
            with self.subTest(bad=bad):
                code, result, _ = self.run_gate(('s', 't'), bad=bad)
                self.assertEqual((code, result['accepted']), (1, False))
                self.assertEqual(self.statuses(result), {'imps-stage-' + sid: 'failed' if sid in bad else 'passed' for sid in 'st'})
                self.assertEqual(result['final_binding'], {'s': 'current', 't': 'current'})
                self.assertEqual([r['stage_id'] for r in result['current_gate']], ['s', 't'])

    def test_validator_bytes_changed_after_gate_fail_every_stage(self):
        def swap_hash(kind, sid, index, generations):
            if (kind, sid, index) == ('snapshot', 's', 3):
                self.gate.hashlib = types.SimpleNamespace(sha256=lambda _b: hashlib.sha256(b'other'))
        self.addCleanup(setattr, self.gate, 'hashlib', hashlib)
        code, result, _ = self.run_gate(('s', 't'), swap_hash)
        self.assertEqual((code, result['accepted']), (1, False))
        self.assertEqual(result['final_binding'], {'s': 'stage validator bytes changed after its gate',
                                                   't': 'stage validator bytes changed after its gate'})

    def test_duplicate_identity_still_refuses_before_any_snapshot(self):
        plan = self.base / 'final-plan.json'
        state_root = str(self.base / 'state')
        plan.write_text(json.dumps({'state_root': state_root, 'package_root': str(FINAL.parents[1]),
                                    'required_stages': ['s'], 'stages': [self.row('s'), self.row('s')]}))
        out = mock.MagicMock()
        with mock.patch.object(self.gate.subprocess, 'run', side_effect=AssertionError('gate launched')), \
                mock.patch.object(self.gate, 'print', out, create=True):
            self.assertEqual(self.gate.validate_final(plan, state_root), 1)
        self.assertEqual(list(json.loads(out.call_args[0][0])['requirement_outcomes']), ['imps-final-gate'])


class Pass22AdapterToPinnedFinalGateTests(unittest.TestCase):
    """The generic adapter runs the installed final gate over real imps runs; a race is refused."""

    def _install(self, base):
        home = base / 'home'; home.mkdir(exist_ok=True)
        env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(base / 'config'), 'XDG_STATE_HOME': str(base / 'state')}
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'imps', '--prefix', str(base / 'prefix'),
                               '--agents-root', str(base / 'agents')], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        version = Path(json.loads(proc.stdout)['data']['version_dir'])
        return version, json.loads((version / 'install-manifest.json').read_text())

    def _run(self, state_root, sid, version, manifest, env):
        from tests.support import CoreTestCase
        case = CoreTestCase(methodName='runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        case.state_root = state_root / sid
        repo = case.make_repo()
        from tests.imps_plan_review_fixtures import admitted_gate
        run = admitted_gate(case, version, manifest, env, case.plan(repo, policy={'review': {'required': True, 'role': 'reviewer'}, 'checks': [
            {'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], 'cwd': str(repo)}]}))
        for req in run.state['brief']['requirements']:
            run.evidence(req['id'], run.scratch(f'{sid}-{req["id"]}.txt', 'verified fixture evidence\n'))
        self.assertEqual(case.run_check(run)['result']['status'], 'passed')
        review_log = run.scratch(f'{sid}-review.txt', 'reviewed current fixture binding; no findings\n')
        run.child(task_id='reviewer-' + sid, status='completed')
        run.submit('review', {'binding': run.binding(), 'task_id': 'reviewer-' + sid, 'perspective_id': 'default',
                              'verdict': 'approve', 'findings': [], 'artifacts': [str(review_log)]})
        self.assertTrue(run.validate().get('ready'))
        return run, repo

    def test_adapter_refuses_earlier_stage_changed_during_later_pinned_gate(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            version, manifest = self._install(base)
            state_root = base / 'stage-state'; state_root.mkdir()
            final = version / 'scripts/validate_stage.py'
            stage_hash = hashlib.sha256(final.read_bytes()).hexdigest()
            env = {**os.environ, 'HOME': str(base / 'home'), 'XDG_CONFIG_HOME': str(base / 'config'), 'XDG_STATE_HOME': str(base / 'state')}
            runs = {sid: self._run(state_root, sid, version, manifest, env) for sid in ('s', 't')}
            rows = [{'id': sid, 'state_subdir': sid, 'run_id': runs[sid][0].run_id, 'stage_sha256': stage_hash} for sid in ('s', 't')]
            job_state = base / 'job-state'
            caller = {'installation_id': manifest['installation_id'], 'workflow': 'imps/issue',
                      'package_digest': manifest['package_digest'], 'actor': 'coordinator'}

            def accept(name, required, mutate=None):
                """Accept one integrated stage through the generic adapter; optionally change a run mid-gate."""
                plan = base / f'{name}-plan.json'
                plan.write_text(json.dumps({'state_root': str(state_root), 'package_root': str(version),
                                            'required_stages': list(required), 'stages': rows}))
                job = {'schema_version': 1, 'job_id': name, 'installation_id': manifest['installation_id'], 'workflow': 'imps/issue',
                       'owner': {'id': 'owner'}, 'objective': 'integrate current stage gates', 'requirements': {'R1': 'all gates current'},
                       'authorization': {'actions': ['read']}, 'constraints': ['offline fixture only'],
                       'dependencies': [{'key': 'imps', 'plugin': 'imps'}], 'pins': {},
                       'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
                       'stages': [{'id': 'integrated', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                                   'execution_mode': 'direct', 'validator_dependency': 'imps', 'revision': 'r1',
                                   'validator_contract': {'final_plan': json.loads(plan.read_text())}}],
                       'tasks': [], 'decisions': [], 'history': [], 'metrics': {}, 'result_contract': {'schema_version': 1}}
                create_pinned_job(job, job_state, base / 'prefix', base / 'agents', base / 'config/workers.json')
                store = Store(job_state, name)
                descriptor = base / f'{name}-invocation.json'
                descriptor.write_text(json.dumps({'state_root': str(state_root), 'final_plan': str(plan)}))
                descriptor = publish_observation(store, caller, 'integrated', str(descriptor))['path']
                argv = [str(final), '--state-root', str(state_root), '--final-plan', str(plan)]
                calls = []

                def pinned_in_process(command, cwd, limits):
                    # The exact installed gate bytes run in-process so a change can be placed inside
                    # a later stage's window; its snapshot and stage gates are real subprocesses.
                    self.assertEqual(command, argv)
                    gate = load_gate(final, 'pass22_installed_final_gate')
                    def run(cmd, **kwargs):
                        proc = subprocess.run(cmd, **kwargs)
                        kind = 'validate' if cmd[1].endswith('validate_stage.py') else cmd[2]
                        sid = next(r['id'] for r in rows if r['run_id'] == cmd[cmd.index('--run-id') + 1])
                        calls.append((kind, sid))
                        if mutate and (kind, sid) == mutate[0]:
                            mutate[1]()
                        return proc
                    gate.subprocess = types.SimpleNamespace(run=run)
                    out = io.StringIO()
                    with mock.patch.object(sys, 'argv', command), contextlib.redirect_stdout(out):
                        code = gate.main()
                    return subprocess.CompletedProcess(command, code, out.getvalue().encode(), b'')

                with mock.patch.object(job_acceptance, '_bounded_run', pinned_in_process):
                    receipt = accept_stage(store, caller, 'integrated', argv, descriptor, 'r1')
                return receipt, calls, store

            def edit(sid):
                path = runs[sid][1] / 'wordstat.py'
                original = path.read_bytes()
                self.addCleanup(path.write_bytes, original)
                return lambda: path.write_bytes(original + b'\n# concurrent edit during a later gate\n')

            receipt, stable_calls, store = accept('pass22-stable', ('s', 't'))
            self.assertTrue(receipt['accepted'], receipt)
            self.assertTrue(validate_stage(store, 'integrated')['accepted'])
            for name, required in (('pass22-race-st', ('s', 't')), ('pass22-race-ts', ('t', 's'))):
                earlier, later = required
                restore = runs[earlier][1] / 'wordstat.py'
                original = restore.read_bytes()
                with self.subTest(required=required):
                    receipt, calls, store = accept(name, required, (('validate', later), edit(earlier)))
                    self.assertFalse(receipt['accepted'], receipt)
                    outcomes = receipt['outcomes']
                    self.assertEqual(outcomes['imps-stage-' + later]['status'], 'passed')
                    self.assertEqual(outcomes['imps-stage-' + earlier]['status'], 'failed')
                    self.assertEqual(outcomes['imps-stage-' + earlier]['evidence']['final_binding'], 'changed after its gate')
                    self.assertFalse(validate_stage(store, 'integrated')['accepted'])
                restore.write_bytes(original)
            # With the edit undone, the same bytes are current again and acceptance is honest.
            receipt, _, _ = accept('pass22-restored', ('t', 's'))
            self.assertTrue(receipt['accepted'], receipt)
            # Every binding was reserved before the first gate and rechecked after the last.
            self.assertEqual(stable_calls, [('snapshot', 's'), ('snapshot', 't'), ('snapshot', 's'), ('validate', 's'), ('snapshot', 's'),
                                            ('snapshot', 't'), ('validate', 't'), ('snapshot', 't'), ('snapshot', 's'), ('snapshot', 't')])


if __name__ == '__main__':
    unittest.main()
