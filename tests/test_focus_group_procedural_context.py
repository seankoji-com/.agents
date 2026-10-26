"""Offline exact auxiliary instruction scope; no real harness paths or model calls."""
import copy
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugins/focus-group/scripts'))
import study as fg
import evidence as ev
from tests.test_focus_group_plan import Workspace


class ProceduralContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.ws=Workspace(self.base)
        self.plan=fg.normalise(self.ws.draft(mode='capture-only'))
        self.target=self.plan['participant_models'][0]
        self.path=self.base/'harness'/'instruction.md';self.path.parent.mkdir()
        self.path.write_text('Use plain words. Check the spelling of your answer.\n')
        self.source=self.base/'harness'/'requirements.md'
        self.source.write_text('This harness requires this exact writing instruction before answering.\n')
        self.entry={'target':self.target,'harness':'fixture-a','path':str(self.path),
            'sha256':fg.digest(self.path.read_bytes()),'purpose':'Writing procedure only',
            'mandatory_instruction':{'path':str(self.source),'sha256':fg.digest(self.source.read_bytes()),
                'quote':'requires this exact writing instruction before answering'},
            'applicability':'All participant answers on this actual harness',
            'sharing':{'providerInstanceId':self.target['providerInstanceId'],'consumer':'participant',
                       'material_class':'procedural-instruction'},
            'inspection':{'inspector':'coordinator','reviewed_at':'2026-10-24T00:00:00Z',
                'sha256':fg.digest(self.path.read_bytes()),'source_sha256':fg.digest(self.source.read_bytes()),'verdict':'cleared'}}

    def configured(self):
        p=copy.deepcopy(self.plan);p['procedural_context']=[copy.deepcopy(self.entry)];return p

    def test_exact_procedural_read_previously_falls_outside_product_scope(self):
        plan=self.configured()
        # The pre-fix implementation has no target argument and ignores the
        # auxiliary declaration. Exercise its actual denial, not a TypeError.
        files=(ev.material_context_files(plan,self.target) if 'target' in inspect.signature(ev.material_context_files).parameters
               else ev.material_context_files(plan))
        scope={'approved':{ev.real(f['path']) for f in files},'own':self.base/'own','tasks':self.base/'tasks'}
        self.assertIsNone(ev.path_problem(0,str(self.path),scope),'Mandatory exact instruction is rejected by the pre-fix product-only scope')

    def test_only_applicable_cell_keys_change_and_stimulus_stays_exact(self):
        new=self.configured();ev.validate_procedural(new)
        for cell in fg.cells(self.plan):
            before=fg.bindings(self.plan,cell,'first-impression');after=fg.bindings(new,cell,'first-impression')
            self.assertEqual(before==after,cell['target']!=self.target)
            slot=cell['cell_id']+':first-impression'
            self.assertEqual(fg.attempt_keys(self.plan)[slot]==fg.attempt_keys(new)[slot],cell['target']!=self.target)
        self.assertEqual(self.plan['stimulus'],new['stimulus'])
        self.assertEqual(ev.material_context_files(new,self.plan['participant_models'][1]),ev.material_context_files(self.plan))

    def test_invalid_regular_path_hash_review_source_sharing_and_harness_refuse(self):
        for defect in ('missing','directory','symlink','traversal','noncanonical','noncanonical-source','glob','changed','unreviewed','source','sharing','harness','duplicate','contaminated'):
            with self.subTest(defect=defect):
                p=self.configured();r=p['procedural_context'][0];index=fg.catalog_index({'providers':[{'providerInstanceId':self.target['providerInstanceId'],
                    'driverKind':'fixture-a','models':[{'id':self.target['model']}],'canRunChildTask':True}]})
                if defect=='missing':r['path']=str(self.path.with_name('missing.md'))
                if defect=='directory':r['path']=str(self.path.parent)
                if defect=='symlink':
                    alias=self.path.with_name('alias.md');alias.symlink_to(self.path);r['path']=str(alias)
                if defect=='traversal':r['path']=str(self.path.parent/'..'/'harness'/'instruction.md')
                if defect=='noncanonical':r['path']=str(self.path.parent)+'//instruction.md'
                if defect=='noncanonical-source':r['mandatory_instruction']['path']=str(self.source.parent)+'/./requirements.md'
                if defect=='glob':r['path']=str(self.path.parent/'*.md')
                if defect=='changed':r['sha256']='f'*64
                if defect=='unreviewed':r['inspection']['verdict']='unreviewed'
                if defect=='source':r['mandatory_instruction']['quote']='not present in actual source'
                if defect=='sharing':r['sharing']['providerInstanceId']='other'
                if defect=='harness':r['harness']='other-harness'
                if defect=='duplicate':p['procedural_context'].append(copy.deepcopy(r))
                if defect=='contaminated':r['purpose']='The preferred finding is that customers love it.'
                with self.assertRaises(fg.StudyError):ev.validate_procedural(p,index=index)

    def test_scope_never_includes_sibling_directory_source_or_nested_reference(self):
        p=self.configured();files=ev.material_context_files(p,self.target)
        scope={'approved':{ev.real(f['path']) for f in files},'procedural':{ev.real(self.path)},
               'own':self.base/'own','tasks':self.base/'tasks','job':self.base/'jobs'}
        for path in (self.source,self.path.parent,self.path.with_name('sibling.md'),self.path/'nested.md',self.path.parent/'..'/'harness'/'instruction.md'):
            self.assertIsNotNone(ev.path_problem(0,str(path),scope))
        problems,limit=ev.event_effects(0,'read',{'path':str(self.path)},scope)
        self.assertEqual(problems,[]);self.assertIsNone(limit)
        self.assertTrue(ev.event_effects(0,'write',{'path':str(self.path)},scope)[0])
        self.assertEqual(ev.event_effects(0,'shell',{'command':'cat '+str(self.path)},scope)[1]['code'],'opaque_event')

    def test_full_instruction_bytes_are_screened_even_when_hash_review_is_current(self):
        for content in ('api_key = inventedfixturecredential', 'import invented_module\n',
                        'Implementation backlog: add an upsell.', self.plan['decision'], self.plan['personas'][1]['goal']):
            with self.subTest(content_kind=content.split()[0]):
                self.path.write_text(content)
                p=self.configured();r=p['procedural_context'][0]
                r['sha256']=r['inspection']['sha256']=fg.digest(self.path.read_bytes())
                with self.assertRaisesRegex(fg.StudyError,'full-byte'):
                    ev.validate_procedural(p)

    def reviewed_study(self):
        self.ws.policy_evidence=[str(self.path),str(self.source)]
        view=self.ws.plan(self.ws.draft(mode='capture-only',procedural_context=[self.entry]))
        self.ws.approve(view)
        return fg.Study(self.ws.root,view['study_id']),view

    def test_invalid_current_configuration_refuses_before_any_charge_or_ledger_write(self):
        s,view=self.reviewed_study()
        with s.locked():s.write('ledger.json',s.ledger())
        before=(s.dir/'ledger.json').read_bytes()
        original=self.path.read_bytes();self.path.write_bytes(original+b'changed')
        request={'request_id':'invalid-input','revision':view['revision'],'stage':'first-impression',
                 'cell_id':fg.cells(s.plan(view['revision'])['plan'])[0]['cell_id'],'target':self.target,
                 'material_classes':['stimulus','persona'],'purpose':'initial'}
        catalog={'index':fg.catalog_index(json.loads(self.ws.catalog().read_text())['response'])}
        with s.locked(),self.assertRaisesRegex(fg.StudyError,'bytes changed'):
            fg.admission(s,request,fg.utc_now('2029-06-01T00:00:00Z'),catalog)
        self.assertEqual((s.dir/'ledger.json').read_bytes(),before)
        self.path.write_bytes(original)
        producing=s.plan(view['revision'])
        for field,alias in (('path',str(self.path.parent)+'//instruction.md'),
                            ('source',str(self.source.parent)+'/./requirements.md')):
            with self.subTest(noncanonical=field):
                invalid=copy.deepcopy(producing)
                declaration=invalid['plan']['procedural_context'][0]
                if field=='path':declaration['path']=alias
                else:declaration['mandatory_instruction']['path']=alias
                with patch.object(s,'plan',return_value=invalid),s.locked(),self.assertRaisesRegex(fg.StudyError,'exact absolute'):
                    fg.admission(s,request,fg.utc_now('2029-06-01T00:00:00Z'),catalog)
                self.assertEqual((s.dir/'ledger.json').read_bytes(),before)
        catalog['index'][(self.target['providerInstanceId'],self.target['model'])]['driverKind']='wrong-harness'
        with s.locked(),self.assertRaisesRegex(fg.StudyError,'harness'):
            fg.admission(s,request,fg.utc_now('2029-06-01T00:00:00Z'),catalog)
        self.assertEqual((s.dir/'ledger.json').read_bytes(),before)

    def test_generated_brief_outer_scope_and_historical_contamination(self):
        s,view=self.reviewed_study();p=s.plan(view['revision'])['plan'];docs={}
        for n,cell in enumerate(fg.cells(p),1):
            task=f'fi-{n:02d}'
            code,out=self.ws.call_evidence('brief','--state-root',self.ws.root,'--study',s.id,'--input',self.ws.write(task+'.json',
                {'revision':view['revision'],'cell_id':cell['cell_id'],'stage':'first-impression','task_id':task}))
            self.assertEqual(code,0,out);doc=out['data']['document'];docs[task]=doc
            text=Path(doc['path']).read_text()
            self.assertEqual('## Procedural context' in text,cell['target']==self.target)
            self.assertNotIn(str(self.source),text)
        spec=self.ws.ok('job-spec','--state-root',self.ws.root,'--study',s.id,'--installation-id','fixture-install',
                        '--capabilities',self.ws.catalog(),'--documents',self.ws.write('documents.json',docs),now='2029-06-01T00:00:00Z')['job']
        with patch.dict(os.environ,self.ws.policy_env):
            fg.planning_module().validate_job(spec)
            expanded=copy.deepcopy(spec)
            expanded['tasks'][0]['context_files'].append({'path':str(self.source),'sha256':fg.digest(self.source.read_bytes())})
            with self.assertRaisesRegex(ValueError,'read scope'):
                fg.planning_module().validate_job(expanded)
        from core.jobs import create_job,prepare
        from core.jobs.store import Store
        pin={'package_digest':'a'*64,'bundle_digest':'b'*64,'effective_workers':{'focus-group/participant':{'bytes':'Fixture procedure'}}}
        create_job(spec,self.ws.root,{'focus-group':pin})
        store=Store(self.ws.root,s.id);caller={'actor':'coordinator','installation_id':'fixture-install',
                    'workflow':'focus-group/run','package_digest':'a'*64}
        prepared=prepare(store,caller,'fi-01',lambda *args:True,lambda *args:True)
        outer=json.loads(Path(prepared['path']).read_text());self.assertEqual(outer['context_files'],ev.material_context_files(p,self.target))
        self.assertEqual(outer['authorization']['read'],[docs['fi-01']['path']]+[f['path'] for f in outer['context_files']])
        from core.jobs import record_dispatch
        cell=fg.cells(p)[0];request_id=store.load()['tasks'][0]['request_id']
        code,out=self.ws.admit(view,request_id,'first-impression',cell['cell_id'])
        self.assertEqual(code,0,out)
        record_dispatch(store,caller,'fi-01',{'kind':'accepted','request_id':request_id,'host_task_id':'fixture-procedural-host',
            'child_thread_id':'fixture-procedural-child','target':self.target,'status_identity':self.target})
        def trace(events,harness='fixture-a'):
            data={'revision':view['revision'],'cell_id':cell['cell_id'],'stage':'first-impression','task_id':'fi-01',
                  'request_id':request_id,'host_task_id':'fixture-procedural-host','brief':docs['fi-01'],
                  'trace':{'source':'fixture host trace','events':events,'harness':harness},'first_host_task_id':None}
            return self.ws.call_evidence('inspect-trace','--state-root',self.ws.root,'--study',s.id,
                         '--input',self.ws.write('trace-'+str(len(list((s.dir/'evidence/traces').glob('*.json'))))+'.json',data))
        code,out=trace([{'tool':'read','path':str(self.path)}]);self.assertEqual(code,0,out)
        self.assertEqual(out['data']['compliance'],'clean-in-trace')
        code,out=trace([{'tool':'shell','command':'cat '+str(self.path)}]);self.assertEqual(code,0,out)
        self.assertEqual(out['data']['compliance'],'unverified')
        code,out=trace([{'tool':'read','path':str(self.path.with_name('sibling.md'))}]);self.assertNotEqual(code,0)
        code,out=trace([{'tool':'read','path':str(self.path)}]);self.assertNotEqual(code,0)
        self.assertEqual(ev.trace_compliance(s,request_id)[0],'contaminated')
        # Historical producing contract has no auxiliary grant. Later scope
        # never clears or reinterprets a recorded contaminated execution.
        historical=copy.deepcopy(p);historical.pop('procedural_context')
        oldscope={'approved':{ev.real(f['path']) for f in ev.material_context_files(historical)},
                  'own':s.job_dir/'artifacts/tasks/old','tasks':s.job_dir/'artifacts/tasks'}
        self.assertIsNotNone(ev.path_problem(0,str(self.path),oldscope))
        for i,state in enumerate(('contaminated','clean-in-trace')):
            row=ev.sealed({'request_id':'old-execution','compliance':state,'limits':[]})
            s.retain(ev.ev(f'traces/{row["record_sha256"]}.json'),row,'fixture trace')
        self.assertEqual(ev.trace_compliance(s,'old-execution')[0],'contaminated')
        self.assertEqual(ev.record_trace_problem(s,{'request_id':'old-execution'})[0],'trace_contaminated')

    def test_normal_carry_keeps_unaffected_evidence_and_all_charges(self):
        from tests.test_focus_group_plan import ContractTest
        old=self.ws.plan(self.ws.draft(mode='capture-only'));self.ws.approve(old)
        for n,cell in enumerate(old['cells'][:2]):
            code,out=ContractTest.accept(self,old,cell['cell_id'],'first-impression','old-'+str(n))
            self.assertEqual(code,0,out)
        s=fg.Study(self.ws.root,old['study_id']);original_records={r['record_sha256']:r for r in s.accepted()}
        before_charges=copy.deepcopy(s.ledger()['charged'])
        self.ws.policy_evidence=[str(self.path),str(self.source)]
        new=self.ws.plan(self.ws.draft(mode='capture-only',procedural_context=[self.entry]))
        mapping=fg.mapping_for(s,new['revision'])
        entries={r['cell_id']:r for r in mapping['entries']}
        self.assertEqual(entries[old['cells'][0]['cell_id']]['status'],'stale')
        self.assertEqual(entries[old['cells'][1]['cell_id']]['status'],'carried')
        self.assertEqual(s.ledger()['charged'],before_charges)
        self.assertEqual({r['record_sha256']:r for r in s.accepted()},original_records)


if __name__=='__main__':unittest.main()
