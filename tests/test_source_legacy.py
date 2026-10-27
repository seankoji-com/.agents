"""Brew-independent old-format job resolution through retained catalog code."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from support import CoreTestCase, ROOT

sys.path.insert(0,str(ROOT/'scripts'))
from source_runtime import bootstrap, legacy, pins
from source_runtime.io import Paths, SourceError, canonical, git, load, read, write_json


class LegacyTest(CoreTestCase):
    def setUp(self):
        super().setUp()
        self.home = self.tmp/'home'
        self.home.mkdir()
        env = patch.dict(os.environ,{'HOME':str(self.home),'PATH':os.environ.get('PATH',os.defpath)},clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.paths = Paths(self.home)
        self.brew = self.home/'brew-keg/libexec'
        # Build the historical four-directory package shape from this checkout.
        # Actual old installed versions receive a separate host resume check.
        for name in ('core','shared','scripts','plugins'):
            shutil.copytree(ROOT/name,self.brew/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        from manifest_data import load as metadata
        for file in (self.brew/'plugins').glob('*/plugin.json'):
            canonical = ROOT/'skills'/file.parent.name/'SKILL.md'
            if canonical.exists():
                (file.parent/'entry.md').write_bytes(canonical.read_bytes())
                value = metadata(ROOT/'plugins'/file.parent.name/'plugin.json')
                file.write_text(json.dumps(value))
        prefix = self.home/'retained-workflows'
        self.registry = self.home/'legacy-registry'
        installed = subprocess.run([sys.executable,str(self.brew/'scripts/install.py'),'--plugin','imps',
            '--prefix',str(prefix),'--agents-root',str(self.registry)],capture_output=True,text=True)
        self.assertEqual(installed.returncode,0,installed.stdout+installed.stderr)
        self.package = Path(json.loads(installed.stdout)['data']['version_dir'])
        receipt = load(self.package/'install-manifest.json')
        self.state = self.home/'old-jobs'
        self.job = self.state/'existing/job.json'
        self.record = {'schema_version':1,'job_id':'existing','status':'active','tasks':[],
            'dependencies':[{'key':'workflow','plugin':'imps'}], 'pins':{'workflow':{
                'installation_id':receipt['installation_id'],'package_dir':str(self.package),
                'package_digest':receipt['package_digest'],'bundle_dir':receipt['bundle_dir'],
                'bundle_digest':receipt['bundle_digest'],
                'compatible_pinned_argv':['t3-plugins','--job',str(self.job),'path','imps']}}}
        write_json(self.job,self.record)
        write_json(self.registry/'job-index.json',{'schema_version':1,'jobs':{
            'existing':{'state_root':str(self.state),'job_id':'existing','status':'live'},
            'missing':{'state_root':str(self.state),'job_id':'missing','status':'live'}}})
        bootstrap.self_install(ROOT,self.paths,source=ROOT)

    def inventory(self):
        return legacy.inventory(self.paths,[self.registry])

    def test_inventory_preserves_missing_jobs_claims_and_verbatim_recovery_commands(self):
        result = self.inventory()
        self.assertEqual(result['classifications'],{'resumable':1,'missing/unknown':1})
        report = load(self.paths.control/'legacy-inventory.json')
        self.assertEqual(report['jobs'][str(self.job)]['pins'],self.record['pins'])
        self.assertEqual(report['jobs'][str(self.job)]['stored_commands'][0]['value'],
            self.record['pins']['workflow']['compatible_pinned_argv'])
        self.assertGreater(result['claims_preserved'],0)
        self.assertTrue(all(row['classification'] == 'missing/unknown' for row in report['claims']))
        self.assertFalse((self.state/'missing').exists())

    def test_real_old_pin_and_core_status_work_after_brew_runtime_removal(self):
        self.inventory()
        installed = legacy.install_bridge(self.paths,self.brew)
        # Existing workflow packages are retained at their original absolute paths.
        shutil.rmtree(self.brew.parent)
        resolved = subprocess.run([installed['bridge'],'--job',str(self.job),'path','imps'],capture_output=True,text=True)
        self.assertEqual(resolved.returncode,0,resolved.stdout+resolved.stderr)
        self.assertEqual(resolved.stdout.strip(),str(self.package/'entry.md'))
        repo = self.make_repo()
        plan = self.plan(repo)
        state = self.home/'old-gate'
        initial = subprocess.run([sys.executable,str(self.package/'core/cli.py'),'init','--state-root',str(state),
            '--json',json.dumps(plan)],capture_output=True,text=True)
        self.assertEqual(initial.returncode,0,initial.stdout+initial.stderr)
        run_id = json.loads(initial.stdout)['run_id']
        status = subprocess.run([sys.executable,str(self.package/'core/cli.py'),'status','--state-root',str(state),
            '--run-id',run_id],capture_output=True,text=True)
        self.assertEqual(status.returncode,0,status.stdout+status.stderr)
        self.assertEqual(json.loads(status.stdout)['run_id'],run_id)

    def dispatched(self,*argv):
        """The command the bridge would run for this inventoried job, without running it."""
        with patch.object(legacy.subprocess,'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(legacy.dispatch(self.paths,['--job',str(self.job),*argv]),0)
        return run.call_args.args[0]

    def test_old_job_helpers_verify_the_pinned_install_receipt(self):
        self.inventory()
        legacy.install_bridge(self.paths,self.brew)
        helpers = {'selection':'model_selection_cli.py','agreement':'execution_agreement_cli.py',
                   'planning-review':'planning_review_cli.py'}
        for action,helper in helpers.items():
            with self.subTest(action=action):
                command = self.dispatched(action,'load-authority','--input','input.json')
                self.assertIn(str(self.package/'shared'/helper),command)
        tampered = self.package/'shared/model_selection_cli.py'
        tampered.chmod(0o644)
        tampered.write_text('raise SystemExit("must not run")\n')
        with self.assertRaises(Exception):
            self.dispatched('selection','load-authority','--input','input.json')

    def test_old_job_helpers_never_load_unreceipted_bytecode(self):
        import py_compile
        self.inventory()
        installed = legacy.install_bridge(self.paths,self.brew)
        shared = self.package/'shared'
        shared.chmod(0o755)
        source = self.tmp/'model_selection.py'
        source.write_text('raise SystemExit("UNRECEIPTED_BYTECODE_LOADED")\n')
        request = self.tmp/'input.json'
        request.write_text('{}')
        name = 'model_selection.'+sys.implementation.cache_tag+'.pyc'
        for linked in (False,True):
            with self.subTest(linked=linked):
                cache = shared/'__pycache__'
                if cache.is_symlink():
                    cache.unlink()
                else:
                    shutil.rmtree(cache,ignore_errors=True)
                target = self.tmp/('linked-cache' if linked else 'unused')
                if linked:
                    target.mkdir(exist_ok=True)
                    cache.symlink_to(target,target_is_directory=True)
                else:
                    cache.mkdir()
                py_compile.compile(str(source),cfile=str(cache/name),
                    invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
                # Without isolation the interpreter would load it: the fixture is live.
                direct = subprocess.run([sys.executable,'-I','-B',str(shared/'model_selection_cli.py'),
                    'load-authority','--input',str(request)],capture_output=True,text=True)
                self.assertIn('UNRECEIPTED_BYTECODE_LOADED',direct.stdout+direct.stderr)
                bridged = subprocess.run([installed['bridge'],'--job',str(self.job),'selection','load-authority',
                    '--input',str(request)],capture_output=True,text=True)
                self.assertNotIn('UNRECEIPTED_BYTECODE_LOADED',bridged.stdout+bridged.stderr)

    def test_bridge_install_and_catalog_commands_ignore_inherited_python_paths(self):
        outside = self.tmp/'inherited'
        outside.mkdir()
        marker = self.tmp/'inherited-module-ran'
        (outside/'subprocess.py').write_text('import pathlib\npathlib.Path('+repr(str(marker))+').write_text("ran")\n')
        self.inventory()
        with patch.dict(os.environ,{'PYTHONPATH':str(outside)}):
            installed = legacy.install_bridge(self.paths,self.brew)
            resolved = subprocess.run([installed['bridge'],'--job',str(self.job),'path','imps'],
                capture_output=True,text=True)
        self.assertEqual(resolved.returncode,0,resolved.stdout+resolved.stderr)
        self.assertFalse(marker.exists())
        # A non-isolated run of the same catalog does pick the module up: the fixture is live.
        catalog = Path(installed['retained_runtime'])/'scripts/catalog.py'
        subprocess.run([sys.executable,'-B',str(catalog),'--help'],capture_output=True,
            env={**os.environ,'PYTHONPATH':str(outside)})
        self.assertTrue(marker.exists())

    def test_bridge_resolve_matches_the_retained_catalog(self):
        from tests.model_selection_fixtures import selection_input
        data = selection_input()
        caps = self.tmp/'caps.json'
        caps.write_text(json.dumps(data['capabilities']))
        profiles = self.tmp/'profiles.json'
        profiles.write_text(json.dumps(data['profiles']))
        self.inventory()
        installed = legacy.install_bridge(self.paths,self.brew)
        args = ['resolve','reviewer','--repo',str(self.tmp),'--profiles',str(profiles),'--capabilities',str(caps)]
        env = {**os.environ,'XDG_CONFIG_HOME':str(self.tmp/'config')}
        bridged = subprocess.run([installed['bridge'],'--job',str(self.job),*args],capture_output=True,text=True,env=env)
        catalog = Path(installed['retained_runtime'])/'scripts/catalog.py'
        direct = subprocess.run([sys.executable,'-B',str(catalog),*args],capture_output=True,text=True,env=env)
        self.assertEqual(direct.returncode,0,direct.stderr)
        self.assertEqual((bridged.returncode,json.loads(bridged.stdout)),(0,json.loads(direct.stdout)))

    def test_doctor_refuses_a_current_version_other_than_the_pin(self):
        self.inventory()
        legacy.install_bridge(self.paths,self.brew)
        self.assertIn('doctor',self.dispatched('doctor','imps'))
        current = self.package.parent/'current'
        other = self.package.parent/'0.0.1-other'
        other.mkdir()
        current.unlink()
        current.symlink_to(other.name)
        with self.assertRaisesRegex(SourceError,"differs from this job's pin"):
            legacy.dispatch(self.paths,['--job',str(self.job),'doctor','imps'])
        self.assertIn('list',self.dispatched('agents','list','imps'))

    def test_worker_show_renders_the_job_frozen_worker_not_live_overrides(self):
        import registry
        worker = 'imps/stage-executor'
        config = self.home/'.config/agents/workers.json'
        override = registry.override_path(self.registry,worker)
        override.parent.mkdir(parents=True)
        override.write_text('worker_id: '+worker+'\nJOB_FROZEN_CUSTOM\n')
        bundle_digest = self.record['pins']['workflow']['bundle_digest']
        registry.set_override(self.registry,worker,bundle_digest,True,config)
        pins = registry.snapshot_pins(self.job,{'workflow':'imps'},self.package.parent.parent,self.registry,config)['pins']
        self.record = {**self.record,'pins':pins}
        write_json(self.job,self.record)
        self.inventory()
        legacy.install_bridge(self.paths,self.brew)
        registry.set_override(self.registry,worker,bundle_digest,False,config)
        # current still names the pinned package, so only the override changed.
        self.assertEqual((self.package.parent/'current').resolve(),self.package.resolve())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(legacy.dispatch(self.paths,['--job',str(self.job),'agents','show','imps','stage-executor']),0)
        shown = json.loads(output.getvalue())
        self.assertIn('JOB_FROZEN_CUSTOM',shown['definition'])
        self.assertEqual(shown['provenance']['override_status'],'enabled')
        self.assertEqual(shown['definition'],pins['workflow']['effective_workers'][worker]['bytes'])
        with self.assertRaisesRegex(SourceError,'not pinned'):
            legacy.dispatch(self.paths,['--job',str(self.job),'agents','show','imps','nobody'])

    def test_bridge_refuses_new_work_changed_pins_unknown_jobs_and_runtime_tampering(self):
        self.inventory()
        installed = legacy.install_bridge(self.paths,self.brew)
        for argv in (['setup'],['--job',str(self.job),'install','imps'],
            ['--job',str(self.state/'missing/job.json'),'path','imps'],
            ['--job',str(self.job),'selection','freeze','--input','unused.json']):
            with self.subTest(argv=argv):
                result = subprocess.run([installed['bridge'],*argv],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
        write_json(self.job,{**self.record,'pins':{}})
        with self.assertRaisesRegex(SourceError,'pins changed'):
            legacy.dispatch(self.paths,['--job',str(self.job),'path','imps'])
        write_json(self.job,self.record)
        target = Path(installed['retained_runtime'])/'scripts/catalog.py'
        target.chmod(0o644)
        target.write_text('raise RuntimeError("must not run")\n')
        with self.assertRaisesRegex(SourceError,'integrity failure'):
            legacy.dispatch(self.paths,['--job',str(self.job),'path','imps'])
