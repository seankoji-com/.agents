"""Public installed/relocated agreements with synthetic host/remote observations."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from shared import execution_agreement as agreements, model_selection as models, planning_review
from tests.model_selection_fixtures import selection_input, replacement
from tests.upfront_fixtures import agree, chosen, engineering
from tests.test_rebuild_installed import Sandbox, ROOT

spec = importlib.util.spec_from_file_location('upfront_ralph', ROOT / 'plugins/ralph/cli.py')
ralph = importlib.util.module_from_spec(spec); spec.loader.exec_module(ralph)


class InstalledAgreementTests(unittest.TestCase):
    def test_relocated_imps_source_gate_requires_actual_current_endpoint_observations(self):
        from tests.imps_plan_review_fixtures import ImpsPlanFixture
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp)); package, manifest = box.install('imps')
            moved = box.base / 'relocated-imps'
            shutil.copytree(package, moved)
            f = ImpsPlanFixture(box, moved, manifest, op='run', write=True, code_review=True)
            f.approve(); f.init()
            box.run(['git', '-C', f.project, 'add', 'source.py'])
            box.run(['git', '-C', f.project, '-c', 'user.name=Fixture', '-c',
                     'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture implementation'])
            f.evidence()
            binding = f.gate('snapshot')['data']
            artifact = f.gates / 'runs' / f.run_id / 'scratch' / 'actual-review.txt'
            artifact.parent.mkdir(exist_ok=True); artifact.write_text('Reviewed fixture source.\n')
            f.gate('child', {'task_id': 'fixture-code-review', 'client_request_id': 'fixture-review-request',
                'parent_thread_id': 'fixture-parent', 'status': 'completed', 'has_pending_child_runs': False})
            f.gate('review', {'binding': binding, 'task_id': 'fixture-code-review', 'perspective_id': 'default',
                'verdict': 'approve', 'findings': [], 'artifacts': [str(artifact)]})
            source = f.gate('validate')['data']
            self.assertTrue(source['source_ready']); self.assertFalse(source['endpoint_complete'])
            evidence = engineering(f.selection, binding['snapshot']['head'])
            for field in ('head', 'base'):
                bad = deepcopy(evidence); bad['pr'][field] = 'wrong'
                f.gate('delivery', bad, ok=False)
            bad = deepcopy(evidence); bad['review']['observed']['options'] = {}
            f.gate('delivery', bad, ok=False)
            f.gate('delivery', evidence)
            self.assertTrue(f.gate('validate')['data']['endpoint_complete'])
            f.local.write_text('VALUE = 2\n')
            self.assertFalse(f.gate('validate')['data']['endpoint_complete'])

    def test_every_catalog_operation_uses_relocated_shared_public_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp))
            for plugin in sorted({r['operation'].split('/')[0] for r in agreements.inventory()}):
                package, _ = box.install(plugin)
                relocated = box.base / ('relocated-' + plugin)
                shutil.copytree(package, relocated)
                self.assertIn('upfront-agreement.md', (relocated / 'entry.md').read_text())
                cli = relocated / 'shared/execution_agreement_cli.py'
                rows = json.loads(box.run([sys.executable, cli, 'inventory', '--input', box.payload({})]).stdout)
                self.assertEqual(len(rows), 44)
                for row in rows:
                    if row['operation'].split('/')[0] != plugin:
                        continue
                    op = row['operation']
                    if row['classification'] == 'direct':
                        payload = {'operation': op, 'action': 'deterministic'}
                        direct = chosen(op, 'Reviewed fixture output')
                        denied = box.run([sys.executable, cli, 'admit', '--input', box.payload({
                            'selection': direct, 'operation': op, 'action': 'dispatch'})], check=False)
                        self.assertEqual(denied.returncode, 2)
                    else:
                        endpoint = 'Open PR' if op in agreements.ENGINEERING_OPS else (
                            'Issue with subissues' if op in agreements.THINKING_OPS else 'Reviewed fixture output')
                        record = chosen(op, endpoint)
                        payload = {'selection': record, 'operation': op}
                        missing = box.run([sys.executable, cli, 'admit', '--input', box.payload({'operation': op})], check=False)
                        self.assertEqual(missing.returncode, 2)
                    result = box.run([sys.executable, cli, 'admit', '--input', box.payload(payload)], check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(json.loads(result.stdout)['chooser'])
                record = chosen(); evidence = engineering(record)
                args = {'selection': record, 'evidence': evidence, 'revision': 'revision-one'}
                self.assertEqual(box.run([sys.executable, cli, 'complete', '--input', box.payload(args)], check=False).returncode, 0)
                evidence['ci']['head'] = 'stale'
                self.assertEqual(box.run([sys.executable, cli, 'complete', '--input', box.payload(args)], check=False).returncode, 2)

    def test_ralph_failed_work_backup_invalidates_primary_review_without_losing_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp)); repo = box.base / 'repo'; repo.mkdir()
            box.run(['git', 'init', '-q', repo])
            box.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                     '-C', repo, 'commit', '--allow-empty', '-qm', 'fixture'])
            raw = selection_input(); raw['operation'] = 'ralph/run'
            raw['scope_id'] = planning_review.logical_output_id('fixture:ralph-backup', 'fixture-output')
            backup = deepcopy(raw['review_panel'][0]['target']); spare = deepcopy(raw['profiles']['models'][2]['target'])
            raw['work_replacements'] = [replacement(raw, backup)]
            raw['review_replacements'] = [replacement(raw, spare, review=True)]
            raw['capabilities']['features'] = {'appOwnedSubagents': True}
            agree(raw); selected = models.freeze(raw)
            from shared.adopter_planning import admit
            admitted = admit('ralph', {'operation': 'run', 'request_reference': 'fixture:ralph-backup',
                'output_name': 'fixture-output', 'invocation_id': selected['invocation_id'], 'selection': selected,
                'selection_sha256': selected['selection_sha256']})
            data = {'goal': 'Fixture goal', 'brief': 'Only fixture source', 'worktree': str(repo),
                'maxAttempts': 4, 'capabilities': raw['capabilities'], 'admission': admitted,
                'implementer': {**selected['work']['workhorse'], 'lineage': 'alpha', 'lineageSource': 'fixture:catalog'},
                'evaluator': {**selected['review_panel'][0]['target'], 'lineage': 'beta', 'lineageSource': 'fixture:catalog'}}
            state = ralph.initialize(data, box.base / 'ralph.json')
            ralph.selection_ready(state)
            dispatch = ralph.advance(state)['dispatch']
            self.assertEqual(ralph.advance(state)['dispatch']['clientRequestId'], dispatch['clientRequestId'])
            failure = {'kind': 'technical', 'reference': 'fixture:provider-outage', 'reconciled': [{
                'target': selected['work']['workhorse'], 'request_id': dispatch['clientRequestId'],
                'host_task_id': 'original-host', 'owned': True, 'has_pending_child_runs': False,
                'status': 'failed', 'reason': 'technical', 'reference': 'fixture:host-terminal'}]}
            with self.assertRaises(Exception): ralph.replace_target(state, {'role': 'implementer', 'target': backup, 'unavailable': failure})
            ralph.attach(state, {'clientRequestId': dispatch['clientRequestId'], 'taskId': 'original-host'})
            ralph.observe(state, {'taskId': 'original-host', 'status': 'failed', 'workState': 'result_available',
                'hasPendingChildRuns': False, **dispatch['target'], 'summary': 'Fixture provider unavailable'})
            self.assertEqual(state['phase'], 'blocked')
            ralph.replace_target(state, {'role': 'implementer', 'target': backup, 'unavailable': failure})
            self.assertEqual(state['attempt'], 2)
            self.assertEqual(state['evaluator']['model'], spare['model'])
            self.assertEqual(state['tasks'][0]['taskId'], 'original-host')
            self.assertEqual(state['modelAdmission'], admitted)
            ralph.selection_ready(state); ralph.validate_checkpoint(state)
            next_work = ralph.advance(state)['dispatch']
            self.assertEqual(next_work['target'], backup)
            self.assertIn('alpha', state['authorLineages'])
            self.assertIn('beta', state['authorLineages'])

    def test_ralph_current_full_review_source_is_distinct_from_endpoint_completion(self):
        from tests.test_ralph import RalphTest
        case = RalphTest('runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        (case.repo / 'owned.py').write_text('VALUE = 2\n')
        case.git('add', 'owned.py'); case.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                                             'commit', '-qm', 'fixture change')
        case.implementation(); case.review()
        self.assertTrue(ralph.publication_verified(case.state))
        selected = case.state['modelAdmission']['selection']
        head = case.git('rev-parse', 'HEAD'); evidence = engineering(selected, head)
        failed = deepcopy(evidence); failed['ci']['checks']['required'] = 'failed'
        with self.assertRaises(ValueError): ralph.complete_endpoint(case.state, failed)
        self.assertNotIn('delivery', case.state)
        self.assertTrue(ralph.complete_endpoint(case.state, evidence)['complete'])
        self.assertEqual(case.state['attempt'], 1)
        broken = deepcopy(case.state); broken['tasks'][0]['dispatch']['target']['options'] = {}
        with self.assertRaises(Exception): ralph.validate_checkpoint(broken)

    def test_installed_ralph_retains_bad_receipts_and_reconciles_absent_requests(self):
        from tests.test_ralph import RalphTest
        case = RalphTest('runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        box = Sandbox(case.base / 'installed-routes'); package, _ = box.install('ralph')
        for scenario in ('mismatch', 'absent', 'options'):
            state_path = case.base / (scenario + '.json')
            def call(command, payload=None):
                argv = [sys.executable, package / 'cli.py', command, '--state', state_path]
                if payload is not None:
                    argv += ['--input', box.payload(payload)]
                return json.loads(box.run(argv).stdout)
            call('init', case.init); issued = call('next')['dispatch']
            if scenario == 'absent':
                proof = {'status': 'absent', 'clientRequestId': issued['clientRequestId'], 'target': issued['target'],
                         'hasPendingChildRuns': False, 'reference': 'fixture:host-absence'}
                held = call('absent', proof)['state']
                self.assertTrue(held['tasks'][0]['consumed']); self.assertEqual(held['attempt'], 1)
                resumed = call('recover', {'reason': 'Original launch is absent; retry inside the same agreement'})['state']
                self.assertEqual(resumed['attempt'], 2)
                self.assertNotEqual(call('next')['dispatch']['clientRequestId'], issued['clientRequestId'])
                continue
            chosen = issued['target']
            options = [{'id': k, 'value': v} for k, v in chosen['options'].items()]
            receipt = {'clientRequestId': issued['clientRequestId'], 'taskId': 'owned-' + scenario,
                       **chosen, 'options': options}
            if scenario == 'mismatch': receipt['providerInstanceId'] = 'wrong-provider'
            attached = call('attach', receipt)['state']
            self.assertEqual(attached['tasks'][0]['taskId'], 'owned-' + scenario)
            observed = call('observe', {'taskId': 'owned-' + scenario, **chosen, 'options': options,
                'status': 'completed', 'workState': 'result_available', 'hasPendingChildRuns': False,
                'summary': 'Fixture source outcome'})['state']
            self.assertEqual(observed['phase'], 'blocked' if scenario == 'mismatch' else 'evaluate')
            self.assertEqual(observed['tasks'][0]['observation']['identityVerified'], scenario == 'options')

    def test_nested_installed_admission_reuses_the_same_output_scope_and_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp))
            request, output = 'fixture:nested-upfront', 'docs/nested-brief.md'
            for outer, inner in (('imps/run', 'ape/forage'), ('ape/forage', 'imps/run')):
                raw = selection_input(); raw.update(operation=outer,
                    scope_id=planning_review.logical_output_id(request, output))
                raw['work']['judgement'] = deepcopy(raw['work']['workhorse'])
                agree(raw, 'Open PR', [outer, inner]); selected = models.freeze(raw)
                plugin, operation = inner.split('/')
                package, _ = box.install(plugin)
                data = {'operation': operation, 'request_reference': request, 'output_name': output,
                        'invocation_id': selected['invocation_id'], 'selection': selected,
                        'selection_sha256': selected['selection_sha256']}
                result = box.run([sys.executable, package / 'scripts/plan_review.py', 'admit',
                                  '--input', box.payload(data)], check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                admitted = json.loads(result.stdout)
                self.assertEqual(admitted['selection_sha256'], selected['selection_sha256'])
                self.assertEqual(admitted['scope_id'], selected['scope_id'])
                self.assertEqual(admitted['selection']['agreement'], selected['agreement'])
                if outer == 'imps/run':
                    resumed = box.run([sys.executable, package / 'shared/execution_agreement_cli.py', 'inherit',
                        '--input', box.payload({'selection': selected, 'operation': 'imps/resume'})])
                    self.assertEqual(json.loads(resumed.stdout)['agreement_sha256'], selected['agreement']['agreement_sha256'])

    def test_installed_thinking_keeps_local_source_partial_until_native_issue_delivery(self):
        from tests.test_thinking_plan_review import TestThinkingPlanReviewInstalled
        case = TestThinkingPlanReviewInstalled('runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        case.approve(); case.render()
        before = case.state('resolve')
        self.assertFalse(before.get('endpoint_complete', False))
        case.state('gate', '--require', 'discovery,spec,handoff,delivery', ok=False)
        content = before['artifacts']['handoff.md']['sha256']
        specs = [{'key': 'work', 'content_sha256': 'b' * 64, 'depends_on': [], 'acceptance': ['observable behavior']}]
        case.state('delivery', 'start', '--input', case.fixture.box.payload({'subissues': specs}))
        parent = {'id': 1, 'url': 'https://github.com/example/project/issues/1', 'repository': 'example/project',
            'content_sha256': content, 'status': 'published', 'reference': 'fixture:actual-parent', 'native_subissue_ids': [2]}
        child = {'id': 2, 'url': 'https://github.com/example/project/issues/2', 'repository': 'example/project',
            'content_sha256': 'b' * 64, 'status': 'published', 'reference': 'fixture:actual-child',
            'parent_id': 1, 'native_subissue': True, 'depends_on_ids': [], 'acceptance': ['observable behavior']}
        case.state('delivery', 'observe', '--input', case.fixture.box.payload({'key': 'parent', 'observation': parent}))
        case.state('delivery', 'complete', ok=False)
        old = case.state('delivery', 'status')
        self.assertEqual(old['observations']['parent']['id'], 1)
        case.state('delivery', 'start', '--input', case.fixture.box.payload({'subissues': specs}))
        self.assertEqual(case.state('delivery', 'status')['observations'], old['observations'])
        case.state('delivery', 'observe', '--input', case.fixture.box.payload({'key': 'work', 'observation': child}))
        done = case.state('delivery', 'complete')
        self.assertTrue(done['complete']); self.assertFalse(done['execution_authorized'])
        case.state('gate', '--require', 'discovery,spec,handoff,delivery')
        self.assertEqual(case.state('resolve')['next_phase'], 'complete')


if __name__ == '__main__':
    unittest.main()
