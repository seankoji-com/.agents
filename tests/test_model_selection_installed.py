"""Exercise the installed/relocated selection and immutable job-brief paths."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared import model_selection as models
from shared import planning_review as planning
from tests.upfront_fixtures import approved_selection
from tests.model_selection_fixtures import selection_input, answer
from tests.test_rebuild_installed import Sandbox


class InstalledSelectionTests(unittest.TestCase):
    def test_relocated_package_cli_missing_answer_then_exact_targets_reach_real_brief(self):
        with tempfile.TemporaryDirectory() as temporary:
            box = Sandbox(Path(temporary))
            package, manifest = box.install('ape')
            # Selection helpers are relocatable and carry no external package pins.
            relocated = box.base / 'relocated'
            shutil.copytree(package, relocated)
            for action, data, expected in [
                ('gate', {'record': None, 'invocation_id': 'new', 'scope_id': 'output'}, 2),
                ('freeze', selection_input(), 0),
            ]:
                proc = box.run([sys.executable, relocated/'shared/model_selection_cli.py', action,
                                '--input', box.payload(data)], check=False)
                self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
            request_reference = 'fixture:installed-selection-request'
            output_name = 'selection-installed/final-report.md'
            selected = selection_input()
            selected.update(operation='ape/study', scope_id=planning.logical_output_id(request_reference, output_name))
            record = approved_selection(selected)
            admission = json.loads(box.run([sys.executable, relocated/'scripts/plan_review.py', 'admit',
                '--input', box.payload({'operation': 'study', 'request_reference': request_reference,
                    'output_name': output_name, 'invocation_id': record['invocation_id'],
                    'selection': record, 'selection_sha256': record['selection_sha256']})]).stdout)
            target = {**record['work']['workhorse'], 'lineage': 'alpha'}
            binding = {'selection_sha256': record['selection_sha256'], 'role': 'workhorse'}
            job = {'schema_version': 1, 'job_id': 'selection-installed', 'installation_id': manifest['installation_id'],
                   'workflow': 'ape/study', 'owner': 'fixture-coordinator', 'objective': 'Fixture bounded research',
                   'requirements': {'R1': 'Inspect fixture only'}, 'authorization': {'actions': ['read']},
                   'constraints': ['No live calls'], 'dependencies': [{'key': 'ape', 'plugin': 'ape'}], 'pins': {},
                   'policy': {'max_repair_cycles': 3}, 'stages': [{'id': 'research', 'depends_on': [],
                       'requirements': ['R1'], 'status': 'pending', 'validator_dependency': 'ape'}],
                   'tasks': [{'task_id': 'research', 'stage_id': 'research', 'logical_slot_id': 'primary',
                              'worker_id': 'ape/source-researcher', 'dependency_key': 'ape', 'role': 'worker',
                              'request_id': 'fixture-request', 'target': target, 'selection_binding': binding,
                              'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/research'}}],
                   'decisions': [], 'history': [], 'metrics': {}, 'result_contract': {'schema_version': 1},
                   'ape_admission': admission,
                   'model_selection': record, 'model_selection_sha256': record['selection_sha256'],
                   'invocation_id': record['invocation_id'], 'scope_id': record['scope_id']}
            broken = deepcopy(job); broken['tasks'][0]['target']['options'] = {}
            proc = box.job(package, 'create', job['job_id'], broken, check=False,
                           extra=('--prefix', box.prefix, '--agents-root', box.agents))
            self.assertEqual(proc.returncode, 2); self.assertIn('target/options differ', proc.stderr)
            box.create(package, job)
            caller = box.caller(manifest, 'ape/study')
            locator = box.job(package, 'prepare', job['job_id'], {'caller': caller, 'task_id': 'research'})
            brief = json.loads(Path(locator['path']).read_text())
            self.assertEqual(brief['target']['options'], {'reasoningEffort': 'high'})
            self.assertEqual(brief['model_selection']['dispatch']['target'], record['work']['workhorse'])
            self.assertEqual(brief['model_selection']['selection_sha256'], record['selection_sha256'])
            self.assertIn('reviewer-standard.md', brief['dependency_pins']['ape']['shared'])
            # A real task-observation records the exact target under an owned host handle.
            box.job(package, 'task-observation', job['job_id'], {'caller': caller, 'task_id': 'research', 'event': {
                'kind': 'accepted', 'request_id': 'fixture-request', 'host_task_id': 'fixture-host',
                'child_thread_id': 'fixture-child', 'status': 'running', 'work_state': 'working',
                'has_pending_child_runs': False}})
            state = box.state_of(job['job_id'])
            self.assertEqual(state['tasks'][0]['handles'][0]['target']['options'], {'reasoningEffort': 'high'})

    def test_supplemental_class_and_named_consent_still_require_existing_price_data_isolation_checks(self):
        from datetime import datetime, timezone
        from shared import supplemental_reviews as extras
        from tests.test_supplemental_reviews import fixture
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        data = fixture(now)
        self.assertEqual(len(extras.select(data, now)[0]), 3)
        data.pop('model_selection')
        self.assertEqual(extras.select(data, now)[1], [{'reason': 'no-supplemental-consent'}])
        data = fixture(now); raw = selection_input()
        raw['supplemental'] = {'kind': 'named', 'options': {}, 'maximum': 1, 'providers': ['gateway'],
                               'data_classes': ['public'], 'targets': [{'providerInstanceId': 'gateway',
                                   'model': 'opencode/sample-a-free'}], 'source': answer('Permit exactly this fixture extra.')}
        data['model_selection'] = approved_selection(raw); data['selection_sha256'] = data['model_selection']['selection_sha256']
        picked = extras.select(data, now)[0]
        self.assertEqual([row['target']['model'] for row in picked], ['opencode/sample-a-free'])
        data['pricing'][0]['costs']['input'] = 1
        self.assertEqual(extras.select(data, now)[0], [])


if __name__ == '__main__':
    unittest.main()
