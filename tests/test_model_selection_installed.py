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
from tests.upfront_fixtures import approved_selection, agree
from tests.model_selection_fixtures import selection_input, canonical_selection_input, answer
from tests.test_rebuild_installed import Sandbox


class InstalledSelectionTests(unittest.TestCase):
    def test_relocated_discovery_rejects_nonobject_options_and_retains_native_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            box = Sandbox(Path(temporary))
            for plugin in ('babysitter', 'ralph'):
                package, _ = box.install(plugin)
                relocated = box.base / (plugin + '-options-relocated')
                shutil.copytree(package, relocated)
                helper = relocated / 'shared/model_selection_cli.py'
                self.assertEqual((relocated / 'shared/model_selection.py').read_bytes(),
                                 (ROOT / 'shared/model_selection.py').read_bytes())
                data = canonical_selection_input()
                work = data['work']['workhorse']
                entry = {**work, 'tier': 'low', 'lineage': 'openai'}
                config = {'schema_version': 1, 'tiers': ['low'], 'providers': {},
                          'roles': {'workhorse': [entry]}}
                config_path = box.config / 't3-plugins/routing.json'
                config_path.parent.mkdir(parents=True, exist_ok=True)
                caps = box.payload(data['capabilities'])
                profiles = box.payload(data['profiles'])
                request = {'capabilities': data['capabilities'], 'profiles': data['profiles'],
                           'routing': config, 'role': 'workhorse'}
                for options in (None, 'high', [], [['reasoningEffort', 'low']], 1, 1.5, True, False):
                    with self.subTest(plugin=plugin, options=options):
                        entry['options'] = options
                        config_path.write_text(json.dumps(config))
                        before = config_path.read_bytes()
                        commands = [
                            [sys.executable, helper, 'discover', '--input', box.payload(request)],
                            [sys.executable, ROOT / 'bin/t3-plugins', '--prefix', box.prefix,
                             'resolve', 'workhorse', '--capabilities', caps],
                            [sys.executable, ROOT / 'bin/t3-plugins', '--prefix', box.prefix,
                             'resolve', 'workhorse', '--capabilities', caps, '--profiles', profiles],
                        ]
                        for command in commands:
                            result = box.run(command, check=False)
                            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                            self.assertIn('configuration gap: roles.workhorse[0].options must be an object',
                                          result.stderr)
                            self.assertNotIn('Traceback', result.stderr)
                            self.assertEqual(result.stdout, '')
                            self.assertEqual(config_path.read_bytes(), before)
                for options in (None, {}, {'reasoningEffort': 'low'},
                                {'effort': 'high'}, {'reasoningEffort': 'unsupported'}):
                    with self.subTest(plugin=plugin, valid_shape=options):
                        if options is None:
                            entry.pop('options')  # Omission retains recommendation defaults.
                        else:
                            entry['options'] = options
                        config_path.write_text(json.dumps(config))
                        before = config_path.read_bytes()
                        result = json.loads(box.run([sys.executable, helper, 'discover',
                                                     '--input', box.payload(request)]).stdout)
                        if options in ({'effort': 'high'}, {'reasoningEffort': 'unsupported'}):
                            self.assertEqual(result['candidates'], [])
                            reason = next(row['reason'] for row in result['excluded']
                                          if row['target']['model'] == work['model'])
                            self.assertIn('unsupported', reason)
                        else:
                            expected = options or {'reasoningEffort': 'high'}
                            self.assertEqual(result['candidates'][0]['target']['options'], expected)
                            plain = json.loads(box.t3('resolve', 'workhorse', '--capabilities', caps).stdout)
                            self.assertEqual(plain['candidates'][0].get('options'), options)
                            profiled = json.loads(box.t3('resolve', 'workhorse', '--capabilities', caps,
                                                        '--profiles', profiles).stdout)
                            self.assertEqual(profiled['candidates'][0]['target']['options'], expected)
                        self.assertEqual(config_path.read_bytes(), before)

    def test_relocated_global_preference_is_recovered_by_later_readers(self):
        with tempfile.TemporaryDirectory() as temporary:
            box = Sandbox(Path(temporary))
            data = canonical_selection_input()
            work = data['work']['workhorse']
            cheap = deepcopy(work)
            cheap['model'] = 'alpha-small'
            data['capabilities']['providers'][0]['models'].insert(0,
                {**deepcopy(data['capabilities']['providers'][0]['models'][0]), 'id': cheap['model']})
            data['profiles']['models'].append({**deepcopy(data['profiles']['models'][0]), 'target': cheap})
            config = {'schema_version': 1, 'tiers': ['low', 'high'],
                      'providers': {'fixture-work': {'runtimeMode': 'auto'}},
                      'roles': {'workhorse': [{**cheap, 'tier': 'low', 'lineage': 'openai'},
                                               {**work, 'tier': 'high', 'lineage': 'openai'}],
                                'reviewer': [{**data['review_panel'][0]['target'],
                                              'tier': 'high', 'lineage': 'anthropic'}]}}
            config_path = box.config / 't3-plugins/routing.json'
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps(config))
            caps = box.payload(data['capabilities'])
            for plugin in ('babysitter', 'ralph'):
                package, _ = box.install(plugin)
                relocated = box.base / (plugin + '-preference-relocated')
                shutil.copytree(package, relocated)
                helper = relocated / 'shared/model_selection_cli.py'
                self.assertEqual((relocated / 'shared/model_selection.py').read_bytes(),
                                 (ROOT / 'shared/model_selection.py').read_bytes())
                # A run-only selection and dispatch leave existing routing bytes intact.
                before = config_path.read_bytes()
                data.update(routing=config, routing_scope='invocation-only',
                            source=answer('Use alpha-work for this invocation'))
                record = json.loads(box.run([sys.executable, helper, 'freeze',
                                             '--input', box.payload(data)]).stdout)
                box.run([sys.executable, helper, 'dispatch', '--input', box.payload(
                    {'record': record, 'role': 'workhorse', 'expected': record['selection_sha256']})])
                self.assertEqual(config_path.read_bytes(), before)
                # The coordinator, separately authorized to write settings, stores
                # only the preference field. The chooser itself still writes nothing.
                preferred = {k: work[k] for k in ('providerInstanceId', 'model')}
                persisted = {**config, 'preferred_workhorse': preferred}
                config_path.write_text(json.dumps(persisted))
                written = config_path.read_bytes()
                later = json.loads(box.t3('resolve', 'workhorse', '--capabilities', caps).stdout)
                self.assertEqual([c['model'] for c in later['candidates']], ['alpha-work', 'alpha-small'])
                self.assertTrue(later['candidates'][0]['preferred'])
                profiled = json.loads(box.t3('resolve', 'workhorse', '--capabilities', caps,
                                            '--profiles', box.payload(data['profiles'])).stdout)
                self.assertEqual(profiled['candidates'][0]['target'], {**work, 'runtimeMode': 'auto'})
                self.assertTrue(profiled['candidates'][0]['preferred'])
                for _ in range(2):
                    request = {'capabilities': data['capabilities'], 'profiles': data['profiles'],
                               'routing': json.loads(config_path.read_text()), 'role': 'workhorse'}
                    discovered = json.loads(box.run([sys.executable, helper, 'discover',
                                                    '--input', box.payload(request)]).stdout)
                    self.assertEqual([c['target']['model'] for c in discovered['candidates']],
                                     ['alpha-work', 'alpha-small'])
                    self.assertTrue(discovered['candidates'][0]['preferred'])
                    self.assertEqual(discovered['preferred_workhorse'], preferred)
                    self.assertEqual(discovered['preference_status'], 'available')
                self.assertEqual(config_path.read_bytes(), written)
                self.assertEqual(json.loads(written)['providers'], config['providers'])
                self.assertEqual(json.loads(written)['roles'], config['roles'])
                config_path.write_text(json.dumps(config))

    def test_relocated_custom_routing_labels_preserve_independence(self):
        with tempfile.TemporaryDirectory() as temporary:
            box = Sandbox(Path(temporary))
            for plugin in ('babysitter', 'ralph'):
                package, _ = box.install(plugin)
                relocated = box.base / (plugin + '-custom-relocated')
                shutil.copytree(package, relocated)
                self.assertEqual((relocated / 'shared/model_selection.py').read_bytes(),
                                 (ROOT / 'shared/model_selection.py').read_bytes())
                for driver in ('cursor', 'opencode', 'pi'):
                    data = canonical_selection_input()
                    data['routing_scope'] = 'global'
                    data['capabilities']['runtimeMode'] = 'full-access'
                    provider = data['capabilities']['providers'][0]
                    provider['driverKind'] = driver
                    provider['runtimeModes'] = ['auto', 'full-access']
                    provider['models'][0]['id'] = 'myvendor-custom'
                    work = data['work']['workhorse']
                    work.update(model='myvendor-custom', runtimeMode='full-access')
                    entry = {**work, 'lineage': 'myvendor'}
                    data['routing'] = {'roles': {'workhorse': [entry],
                                                'reviewer': [data['review_panel'][0]['target']]}}
                    del data['profiles']['models'][0]
                    for label in ('myvendor', 'google', 'anthropic'):
                        with self.subTest(plugin=plugin, driver=driver, label=label):
                            entry['lineage'] = label
                            frozen = box.run([sys.executable, relocated/'shared/model_selection_cli.py',
                                              'freeze', '--input', box.payload(data)], check=False)
                            if label != 'google':
                                self.assertEqual(frozen.returncode, 2)
                                self.assertIn('independent of every', frozen.stderr)
                                continue
                            self.assertEqual(frozen.returncode, 0, frozen.stderr)
                            record = json.loads(frozen.stdout)
                            for role in ('workhorse', 'reviewer'):
                                request = {'record': record, 'role': role,
                                           'expected': record['selection_sha256']}
                                if role == 'reviewer':
                                    request['slot_id'] = 'review'
                                result = box.run([sys.executable, relocated/'shared/model_selection_cli.py',
                                                  'dispatch', '--input', box.payload(request)])
                                plan = json.loads(result.stdout)
                                self.assertEqual(plan['target'], work if role == 'workhorse' else
                                                 data['review_panel'][0]['target'])
                                self.assertEqual(plan['routing_scope'], 'global' if role == 'workhorse'
                                                 else 'invocation-only')
                    self.assertFalse((box.config / 't3-plugins/routing.json').exists())

    def test_installed_babysitter_and_ralph_short_rounds_and_exact_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            box = Sandbox(Path(temporary))
            for plugin in ('babysitter', 'ralph'):
                package, _ = box.install(plugin)
                relocated = box.base / (plugin + '-relocated')
                shutil.copytree(package, relocated)
                contract = (relocated / 'shared/model-selection.md').read_text()
                self.assertIn('one decision per question', contract)
                self.assertIn('Run-only never writes routing', contract)
                agreement_contract = (relocated / 'shared/upfront-agreement.md').read_text()
                self.assertIn('one decision per question', agreement_contract)
                self.assertIn('Retain supplied answers', agreement_contract)
                self.assertIn('short rounds', (relocated / 'playbooks' /
                              ('maintain.md' if plugin == 'babysitter' else 'loop.md')).read_text())
                data = canonical_selection_input()
                data['source'] = answer('Use the configured alpha-work as workhorse globally')
                del data['routing_scope']
                missing_scope = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'freeze',
                                        '--input', box.payload(data)], check=False)
                self.assertEqual(missing_scope.returncode, 2)
                self.assertIn('workhorse routing scope missing', missing_scope.stderr)
                self.assertIn('ask only which scope applies', missing_scope.stderr)
                data['routing_scope'] = 'global'
                data['routing'] = {'roles': {'workhorse': [{**data['work']['workhorse'], 'lineage': 'openai'}],
                                            'reviewer': [data['review_panel'][0]['target']]}}
                data['work']['workhorse']['options'] = {'reasoningEffort': 'low'}
                data['profiles']['roles']['workhorse']['required_options'] = {'reasoningEffort': 'low'}
                frozen = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'freeze',
                                  '--input', box.payload(data)])
                record = json.loads(frozen.stdout)
                dispatched = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'dispatch',
                    '--input', box.payload({'record': record, 'role': 'workhorse',
                                            'expected': record['selection_sha256']})])
                plan = json.loads(dispatched.stdout)
                self.assertEqual(plan['target'], data['work']['workhorse'])
                self.assertEqual(plan['routing_scope'], 'global')
                self.assertEqual(plan['scope_id'], data['scope_id'])
                self.assertFalse((box.config / 't3-plugins/routing.json').exists())
                agreed = deepcopy(data)
                agreed['operation'] = 'ralph/run'
                agree(agreed)
                agreed_frozen = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'freeze',
                                        '--input', box.payload(agreed)])
                agreed_record = json.loads(agreed_frozen.stdout)
                agreed_dispatch = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'dispatch',
                    '--input', box.payload({'record': agreed_record, 'role': 'workhorse',
                                            'expected': agreed_record['selection_sha256']})])
                agreed_plan = json.loads(agreed_dispatch.stdout)
                self.assertEqual(agreed_plan['routing_scope'], 'global')
                self.assertEqual(agreed_plan['agreement_sha256'], agreed_record['agreement']['agreement_sha256'])
                run_only = deepcopy(data)
                run_only['routing_scope'] = 'invocation-only'
                run_only['source'] = answer('Use alpha-work for this run')
                run_frozen = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'freeze',
                                     '--input', box.payload(run_only)])
                run_record = json.loads(run_frozen.stdout)
                run_dispatch = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'dispatch',
                    '--input', box.payload({'record': run_record, 'role': 'workhorse',
                                            'expected': run_record['selection_sha256']})])
                self.assertEqual(json.loads(run_dispatch.stdout)['routing_scope'], 'invocation-only')
                self.assertFalse((box.config / 't3-plugins/routing.json').exists())
                del data['profiles']['models'][0]
                endorsed = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'freeze',
                                   '--input', box.payload(data)])
                endorsed_record = json.loads(endorsed.stdout)
                exact = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'dispatch',
                    '--input', box.payload({'record': endorsed_record, 'role': 'workhorse',
                                            'expected': endorsed_record['selection_sha256']})])
                self.assertEqual(json.loads(exact.stdout)['target'], data['work']['workhorse'])
                self.assertEqual(json.loads(exact.stdout)['routing_scope'], 'global')
                data['routing']['roles']['workhorse'][0]['lineage'] = 'not-alpha'
                conflict = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'freeze',
                                    '--input', box.payload(data)], check=False)
                self.assertEqual(conflict.returncode, 2)
                self.assertIn('workhorse fixture-work/alpha-work', conflict.stderr)
                self.assertIn('set routing.roles.workhorse.lineage to openai or omit that field', conflict.stderr)
                del data['routing']['roles']['workhorse'][0]['lineage']
                corrected = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'freeze',
                                     '--input', box.payload(data)])
                corrected_record = json.loads(corrected.stdout)
                corrected_dispatch = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'dispatch',
                    '--input', box.payload({'record': corrected_record, 'role': 'workhorse',
                                            'expected': corrected_record['selection_sha256']})])
                self.assertEqual(json.loads(corrected_dispatch.stdout)['target'], data['work']['workhorse'])
                self.assertEqual(json.loads(corrected_dispatch.stdout)['routing_scope'], 'global')
                self.assertFalse((box.config / 't3-plugins/routing.json').exists())
                data['profiles']['roles']['workhorse']['source'] = 'fixture-policy.md#work'
                missing = box.run([sys.executable, relocated/'shared/model_selection_cli.py', 'freeze',
                                  '--input', box.payload(data)], check=False)
                self.assertEqual(missing.returncode, 2)
                self.assertIn('provide one profiles.models entry', missing.stderr)
                self.assertIn('fixture-policy.md#work', missing.stderr)
                self.assertNotIn('provide profiles.roles.workhorse', missing.stderr)

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
