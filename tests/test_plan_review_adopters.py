"""Public SOURCE and INSTALLED adopter acceptance and real refusal paths."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from shared import model_selection as models, planning_review as planning
from tests.upfront_fixtures import approved_selection
from tests.adopter_plan_review_fixtures import AdopterFixture
from tests.test_rebuild_installed import Sandbox,ROOT


class AdoptersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.box=Sandbox(Path(cls.temp.name))
        cls.packages={p:cls.box.install(p) for p in ('agent-tuneup','elephant-goldfish','babysitter','ralph')}

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def fixture(self,plugin='agent-tuneup',**kw):
        package,manifest=self.packages[plugin]
        return AdopterFixture(self.box,package,manifest,plugin=plugin,**kw)

    def test_source_installed_no_change_conclusions_bootstrap_and_written_strategies(self):
        for installed in (False,True):
            for plugin,op,kind in [('agent-tuneup','tuneup','conclusions'),('agent-tuneup','align','conclusions'),('agent-tuneup','audit','conclusions'),
                ('agent-tuneup','audit','bootstrap'),('babysitter','pr','strategy'),('babysitter','repo','strategy'),
                ('babysitter','org','strategy'),('ralph','run','strategy')]:
                with self.subTest(installed=installed,plugin=plugin,op=op,kind=kind):
                    f=self.fixture(plugin,op=op,kind=kind,installed=installed)
                    f.ape('validate',{'descriptor':f.descriptor},ok=False)
                    f.approve();r=f.ape('validate',{'descriptor':f.descriptor})
                    self.assertEqual(r['passes'][0]['mode'],'cross-lineage');self.assertEqual(r['rounds_used'],1)
                    self.assertFalse(r['execution_authorized']);self.assertEqual(f.prepare()['snapshot'],f.snapshot)
                    state=json.loads(Path(r['subject_file']).read_text());self.assertEqual(state['rounds_used'],1)

    def test_selection_admission_dispatch_exact_options_missing_answers_and_direct_helpers(self):
        for plugin,op in [('agent-tuneup','tuneup'),('agent-tuneup','align'),('agent-tuneup','audit'),('agent-tuneup','apply'),
            ('elephant-goldfish','check'),('elephant-goldfish','elephant'),('ralph','run'),
            ('babysitter','pr'),('babysitter','repo'),('babysitter','org')]:
            for installed in (False,True):
                f=self.fixture(plugin,op=op,installed=installed)
                for key in ('selection','selection_sha256'):
                    d=deepcopy(f.admission_input);d.pop(key)
                    f.ape('admit',d,ok=False)
                d=deepcopy(f.admission_input);d['selection']['source']['answer']='tampered'
                f.ape('admit',d,ok=False)
                chosen=f.ape('dispatch',{'admission':f.admission,'role':'workhorse'})
                self.assertEqual(chosen['target']['options'],{'reasoningEffort':'high'})
                self.assertEqual(chosen['target']['model'],f.selection['work']['workhorse']['model'])
                for direct_op in ('doctor','status','list','raw-audit','bootstrap-template'):
                    self.assertEqual(f.ape('admit',{'operation':direct_op}),{'allowed':True,'chooser':False,'dispatch':False})

    def test_missing_tampered_stale_borrowed_and_adverse_receipts(self):
        for plugin in ('agent-tuneup','babysitter','ralph'):
            f=self.fixture(plugin,op='align' if plugin=='agent-tuneup' else 'run' if plugin=='ralph' else 'pr')
            f.approve();original=deepcopy(f.descriptor)
            for ref in (None,{}, {'path':str(f.base/'absent'),'sha256':'0'*64,'bytes':1}):
                f.descriptor['planning_review']=ref;f.ape('validate',{'descriptor':f.descriptor},ok=False)
            f.descriptor=original
            for path in (f.metadata,Path(f.receipt['path']),f.answer,f.request,f.local):
                raw=path.read_bytes();path.write_bytes(raw+b'\n')
                f.ape('validate',{'descriptor':f.descriptor},ok=False);path.write_bytes(raw)
            f.ape('validate',{'descriptor':f.descriptor})
            f.descriptor['requirements']['REQ-ONE']='Different criterion';f.ape('validate',{'descriptor':f.descriptor},ok=False)
        for partial in (False,True):
            f=self.fixture();f.begin_review();r=f.review_pass(adverse=not partial,malformed=partial)
            self.assertEqual(r['outcome'],'incomplete' if partial else 'adverse')
            self.assertFalse(f.finish(attach=False)['accepted'])
            f.ape('attach',{'descriptor':f.descriptor,'metadata_file':str(f.metadata),'receipt':f.receipt['path']},ok=False)

    def test_private_proposal_review_before_owner_approval_and_actual_apply(self):
        for installed in (False,True):
            f=self.fixture(installed=installed);f.proposal();original=f.target.read_bytes()
            f.owner_approve(ok=False)
            p=self.box.run([sys.executable,f.plugin/'scripts/align.py','apply','--plan',f.plan_file,
                '--approval',f.plan['approval_digest'],'--backup',f.base/'missing-context-backup'],check=False)
            self.assertEqual(p.returncode,2);self.assertEqual(f.target.read_bytes(),original)
            f.approve();approval=f.owner_approve();context=f.apply_context(approval)
            bad=deepcopy(context);bad['approval']['owner']['plan_digest']='0'*64
            f.ape('apply-ready',{'context':bad,'document':f.plan},ok=False)
            self.assertTrue(f.ape('apply-ready',{'context':context,'document':f.plan})['ready'])
            raw=f.candidate.read_bytes();f.candidate.write_bytes(raw+b' ')
            f.ape('apply-ready',{'context':context,'document':f.plan},ok=False);f.candidate.write_bytes(raw)
            backup=f.base/'new-backup';p=self.box.run([sys.executable,f.plugin/'scripts/align.py','apply',
                '--plan',f.plan_file,'--approval',f.plan['approval_digest'],'--backup',backup,
                '--context',self.box.payload(context)])
            self.assertEqual(json.loads(p.stdout)['writes'],1);self.assertEqual(backup.read_bytes(),original)
            self.assertEqual(f.target.read_bytes(),f.candidate.read_bytes())
            # Immutable before snapshot lets post-apply parse/load/enforcement keep
            # consuming the pre-execution review, without reviewing the write again.
            self.assertTrue(f.ape('apply-ready',{'context':context,'document':f.plan})['ready'])

    def test_private_authority_is_not_implied_by_selection(self):
        f=self.fixture(private=False);f.proposal();f.begin_review()
        out=f.review('next',{'slot_id':'review'})
        self.assertIsNone(out)
        # No permitted confidential recipient and no authorised self-review.
        f.review('direct',{'observation':{}},ok=False);f.ape('validate',{'descriptor':f.descriptor},ok=False)

    def test_default_tuneup_applies_approved_proposal_with_the_original_admission(self):
        f = self.fixture(op='tuneup', installed=True)
        f.proposal()
        before = f.target.read_bytes()
        f.owner_approve(ok=False)
        f.approve()
        approval = f.owner_approve()
        context = {'admission': f.admission, 'approval': approval}
        self.assertTrue(f.ape('apply-ready', {'context': context, 'document': f.plan})['ready'])
        other = self.fixture(op='tuneup', installed=True)
        f.ape('apply-ready', {'context': {**context, 'admission': other.admission},
                             'document': f.plan}, ok=False)
        backup = f.base / 'default-workflow-backup'
        result = self.box.run([sys.executable, f.plugin / 'scripts/align.py', 'apply',
            '--plan', f.plan_file, '--approval', f.plan['approval_digest'], '--backup', backup,
            '--context', self.box.payload(context)])
        self.assertEqual(json.loads(result.stdout)['writes'], 1)
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(f.target.read_bytes(), f.candidate.read_bytes())

    def test_alias_wakes_new_invocations_and_pinned_resume(self):
        for plugin,op in [('agent-tuneup','align'),('elephant-goldfish','check'),('babysitter','pr'),('ralph','run')]:
            f=self.fixture(plugin,op=op)
            for event in ('wake','repair','compaction'):
                self.assertEqual(f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'event':event}),f.admission)
            once=f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'forward':True})
            f.ape('continue',{'admission':once,'invocation_id':f.id,'forward':True},ok=False)
            f.ape('continue',{'admission':f.admission,'invocation_id':'new-invocation'},ok=False)
            if plugin=='ralph':
                for retain in (None,False):
                    self.assertEqual(f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'event':'resume','retain':retain}),f.admission)
                self.assertEqual(f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'event':'resume','retain':True}),f.admission)

    def test_elephant_factual_truth_then_design_adequacy_then_readability(self):
        for installed in (False,True):
            f=self.fixture('elephant-goldfish',op='elephant',installed=installed)
            f.elephant_job()
            f.ape('prepare',{'descriptor':f.descriptor,'inputs':f.inputs,'metadata_file':str(f.metadata)},ok=False)
            refused=self.box.job(f.package,'prepare',f.job_id,{'caller':f.caller,'task_id':'cold'},check=False)
            self.assertNotEqual(refused.returncode,0)
            f.complete_document_slot('facts');f.accept_document('facts')
            f.approve();f.install_design()
            state=self.box.state_of(f.job_id)
            self.assertEqual(state['decisions'],[], 'publishing evidence does not reopen unchanged owner scope')
            locator=Path(next(s for s in state['stages'] if s['id']=='cold')['resources']['adopter_design_file'])
            raw_locator=locator.read_bytes();locator.write_text('{}')
            refused=self.box.job(f.package,'prepare',f.job_id,{'caller':f.caller,'task_id':'cold'},check=False)
            self.assertNotEqual(refused.returncode,0);locator.write_bytes(raw_locator)
            wrong=deepcopy(f.descriptor);wrong['document']['path']=str(f.request)
            locator.write_text(json.dumps(wrong))
            refused=self.box.job(f.package,'prepare',f.job_id,{'caller':f.caller,'task_id':'cold'},check=False)
            self.assertNotEqual(refused.returncode,0);self.assertIn('another cold-read document',refused.stderr)
            locator.write_bytes(raw_locator)
            f.complete_document_slot('cold');f.accept_document('cold')
            # An unchanged plan assessment never grants factual/cold fallback.
            raw=f.answer.read_bytes();f.answer.write_bytes(raw+b'Changed design.')
            f.ape('validate',{'descriptor':f.descriptor},ok=False);f.answer.write_bytes(raw)
        f=self.fixture('elephant-goldfish',op='elephant');f.elephant_job()
        f.complete_document_slot('facts');f.accept_document('facts',outcome='refuted')
        f.ape('prepare',{'descriptor':f.descriptor,'inputs':f.inputs,'metadata_file':str(f.metadata)},ok=False)

    def test_ralph_public_init_resume_next_and_strategy_preserve_pins(self):
        for installed in (False,True):
            f=self.fixture('ralph',op='run',installed=installed)
            caps=deepcopy(f.selection['capabilities']);caps['features']={'appOwnedSubagents':True}
            data={'goal':'Fixture goal','brief':'Bounded local work','worktree':str(f.project),'capabilities':caps,
                'implementer':{**f.selection['work']['workhorse'],'lineage':'openai','lineageSource':'fixture:catalog'},
                'evaluator':{**f.selection['review_panel'][0]['target'],'lineage':'anthropic','lineageSource':'fixture:catalog'}}
            state=f.base/'ralph.json'
            def run(command,payload=None,ok=True):
                argv=[sys.executable,f.plugin/'cli.py',command,'--state',state]
                if payload is not None:argv+=['--input',self.box.payload(payload)]
                p=self.box.run(argv,check=False)
                self.assertEqual(p.returncode==0,ok,p.stdout+p.stderr)
                return json.loads(p.stdout)
            run('init',data,ok=False);self.assertFalse(state.exists())
            d=deepcopy(f.selection_data);d['work']['workhorse']['execution']='current-context'
            selected=approved_selection(d)
            direct_admission=f.ape('admit',{**f.admission_input,'selection':selected,'selection_sha256':selected['selection_sha256']})
            run('init',{**data,'admission':direct_admission},ok=False);self.assertFalse(state.exists())
            data['admission']=f.admission;run('init',data)
            run('resume',{'admission':f.admission,'retain':False})
            run('resume',{'admission':f.admission,'retain':True})
            run('strategy',{'descriptor':f.descriptor},ok=False);f.approve()
            run('strategy',{'descriptor':f.descriptor})
            issued=run('next');self.assertEqual(issued['dispatch']['target']['options'],{'reasoningEffort':'high'})
            old=json.loads(state.read_text());self.assertEqual(old['attempt'],1)
            run('strategy',{'descriptor':f.descriptor},ok=False)
            f.answer.write_text('Changed strategy.');run('next',ok=False)
            run('status');run('stop')

    def test_parent_job_acceptance_and_ordinary_maintenance_exemption(self):
        for installed in (False,True):
            f=self.fixture(installed=installed);f.integrated_job();f.accept_integrated(ok=False)
            # Failed domain acceptance does not consume planning rounds; review the actual output.
            f.approve()
            # A zero-slot retry is an existing charged domain acceptance, not a planning duplicate.
            f.accept_integrated();self.assertEqual(json.loads(Path(json.loads(f.metadata.read_text())['subject_file']).read_text())['rounds_used'],1)
            f=self.fixture('babysitter',op='pr',installed=installed);f.integrated_job();f.accept_integrated()
            self.assertFalse(f.metadata.exists())
            # Missing chooser blocks an ordinary babysitter job even though it has no plan artifact.
            job=deepcopy(f.job);job['job_id']+='-missing';job.pop('adopter_admission')
            p=self.box.job(f.package,'create',job['job_id'],job,check=False,
                extra=('--prefix',self.box.prefix,'--agents-root',self.box.agents))
            self.assertNotEqual(p.returncode,0)

    def test_published_tuneup_conclusions_must_equal_reviewed_findings_and_changes(self):
        for installed in (False, True):
            for op in ('tuneup', 'audit', 'align'):
                f = self.fixture(op=op, installed=installed)
                f.integrated_job(); f.accept_integrated(ok=False)
                f.approve(); f.accept_integrated()
                original = deepcopy(f.domain_data)
                for field, value in (('findings', [{'code': 'NEW', 'location': 'fixture:unreviewed'}]),
                                     ('changes', [{'id': 'unreviewed'}])):
                    f.domain_data = deepcopy(original); f.domain_data[field] = value
                    f.accept_integrated(ok=False)
                f.domain_data = original
                f.accept_integrated()

    def test_scheduled_reuse_revalidates_authority_and_catalog(self):
        f=self.fixture('babysitter',op='repo')
        from tests.model_selection_fixtures import answer
        d=deepcopy(f.selection_data);d['schedule']={'schedule_id':'fixture-schedule','source':answer('Reuse these choices for this schedule.')}
        selected=approved_selection(d)
        admission=f.ape('admit',{**f.admission_input,'selection':selected,'selection_sha256':selected['selection_sha256']})
        args={'admission':admission,'invocation_id':f.id,'event':'schedule','schedule_id':'fixture-schedule',
            'capabilities':selected['capabilities'],'policy_digests':{k:selected[k] for k in ('routing_sha256','profiles_sha256')}}
        self.assertEqual(f.ape('continue',args),admission)
        bad=deepcopy(args);bad['schedule_id']='another';f.ape('continue',bad,ok=False)
        bad=deepcopy(args);bad['capabilities']['providers']=[];f.ape('continue',bad,ok=False)
        f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'event':'schedule','schedule_id':'fixture-schedule'},ok=False)

    def test_authorised_self_review_consumes_real_receipt_for_each_output_domain(self):
        for plugin,op in [('agent-tuneup','audit'),('babysitter','pr'),('ralph','run')]:
            for installed in (False,True):
                f=self.fixture(plugin,op=op,installed=installed,direct=True)
                f.approve();r=f.ape('validate',{'descriptor':f.descriptor})
                self.assertEqual([p['mode'] for p in r['passes']],['self-review'])
                self.assertTrue(r['degraded_panel']);self.assertEqual(r['rounds_used'],1)

    def test_elephant_design_self_review_does_not_replace_factual_or_cold_read(self):
        f=self.fixture('elephant-goldfish',op='elephant',direct=True)
        f.elephant_job();f.complete_document_slot('facts');f.accept_document('facts')
        f.approve();self.assertEqual(f.ape('validate',{'descriptor':f.descriptor})['passes'][0]['mode'],'self-review')
        f.install_design();f.complete_document_slot('cold');f.accept_document('cold')
        state=self.box.state_of(f.job_id)
        self.assertEqual(len(state['tasks']),2)
        self.assertTrue(all(t['handles'][0]['observed_identity']['status']=='verified' for t in state['tasks']))

    def test_manifest_matrix_covers_every_public_operation(self):
        from shared.worker_registry import load_manifest,RegistryError
        matrix=json.loads((ROOT/'shared/operation-matrix.json').read_text())['plugins']
        for p in (ROOT/'plugins').iterdir():
            if not (p/'plugin.json').exists():continue
            m=load_manifest(p);self.assertEqual(set(matrix[m['name']]),set(m['operations']))
            self.assertTrue(all(r['reason'] for r in matrix[m['name']].values()))
        def mutate(p):
            path=p/'plugin.json';m=json.loads(path.read_text());m['operation_review'].pop('tuneup');path.write_text(json.dumps(m))
        copied=self.box.source_copy('agent-tuneup',mutate=mutate)
        with self.assertRaises(RegistryError):load_manifest(copied/'plugins/agent-tuneup')
