"""Brew-independent old-format job resolution through retained catalog code."""
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
