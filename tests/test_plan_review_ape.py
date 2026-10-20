"""S-APE public source/installed acceptance with real shared planning jobs."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.jobs.store import canonical, digest
from shared import model_selection as models, planning_review as planning
from tests.ape_plan_review_fixtures import ApePlanFixture
from tests import ape_plan_review_fixtures as fixtures
from tests.test_ape_validate_report import research_markdown, research_findings
from tests.test_rebuild_installed import Sandbox


class ApePlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.box=Sandbox(Path(cls.temp.name));cls.package,cls.manifest=cls.box.install('ape')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def fixture(self, **kwargs):return ApePlanFixture(self.box,self.package,self.manifest,**kwargs)

    def test_final_forage_cannot_use_valid_intermediate_research_to_bypass_review(self):
        f = self.fixture(op='forage')
        original = fixtures.descriptor
        def research_descriptor(operation, sources, requirements, fingerprint, report, findings, consumed=None):
            if operation == 'forage-synthesis':
                return original('forage-research', sources, requirements, fingerprint, report, findings)
            return original(operation, sources, requirements, fingerprint, report, findings, consumed)
        # The final worker succeeds with a real, correctly pinned research report.
        # Its domain validity must not let it replace the admitted synthesis output.
        with patch.object(fixtures, 'synthesis_markdown', lambda sources, consumed: research_markdown(sources[0])), \
             patch.object(fixtures, 'synthesis_findings', lambda sources, consumed: research_findings(sources[0])), \
             patch.object(fixtures, 'descriptor', research_descriptor):
            f.work()
        self.assertNotIn('planning_review', f.descriptor)
        self.assertTrue(f.validate_report()['accepted'])
        obs = self.box.publish(f.package, f.job_id, f.caller, f.final_stage, f.descriptor)
        proc = self.box.accept(f.package, 'accept-stage', f.job_id, {
            'caller': f.caller, 'stage_id': f.final_stage, 'revision': f.source['revision'],
            'validator_argv': [str(f.package / 'scripts/validate_report.py'), '--input', obs], 'input_file': obs})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('operation differs', proc.stdout + proc.stderr)

    def test_direct_synthesis_marker_cannot_downgrade_a_child_or_work_role(self):
        f = self.fixture(op='forage')
        stage = f.job['stages'][-1]
        stage['resources'] = {'ape_output_type':'forage-synthesis'}
        self.assertIn('direct judgement', f.create_work(ok=False))
        f.job['tasks'] = f.job['tasks'][:1]
        stage.update(execution_mode='direct', selection_binding={
            'role':'workhorse', 'selection_sha256':f.selection['selection_sha256']})
        self.assertIn('direct judgement', f.create_work(ok=False))

    def test_source_and_installed_study_and_forage_delegated_and_direct(self):
        for installed in (False,True):
            for op in ('study','forage'):
                for direct in (False,True):
                    with self.subTest(installed=installed,op=op,direct=direct):
                        f=self.fixture(op=op,installed=installed,direct=direct);f.work()
                        f.validate_report(ok=False);f.accept(ok=False)
                        f.approve();f.validate_report();f.accept();f.validate_final()
                        result=f.ape('validate',{'descriptor':f.descriptor})
                        self.assertEqual(result['modes'],['self-review' if direct else 'cross-lineage'])
                        self.assertFalse(result['execution_authorized'])
                        self.assertEqual(result['rounds_used'],1)
                        self.assertEqual(json.loads(f.metadata.read_text())['subject_file'],result['subject_file'])

    def test_missing_choices_refuse_admission_and_job_creation_before_work(self):
        f=self.fixture()
        for key in ('selection','selection_sha256'):
            data=deepcopy(f.admission_input);data.pop(key)
            self.assertIn('ape_planning_error',f.ape('admit',data,ok=False))
        for key in ('ape_admission','model_selection'):
            job=deepcopy(f.job);job.pop(key)
            self.assertTrue(f.create_work(ok=False,job=job))
            self.assertFalse(f.job_file.exists())
        f.create_work()
        # A task cannot dispatch after its producing selection is tampered with.
        state=json.loads(f.job_file.read_text());state['model_selection']['source']['answer']='tampered'
        f.job_file.write_text(json.dumps(state))
        proc=self.box.job(f.package,'prepare',f.job_id,{'caller':f.caller,'task_id':'research'},check=False)
        self.assertNotEqual(proc.returncode,0)
        self.assertFalse((f.job_file.parent/'briefs').exists() and list((f.job_file.parent/'briefs').iterdir()))

    def test_empty_no_adoption_study_and_forage_still_need_actual_receipt(self):
        for op in ('study','forage'):
            f=self.fixture(op=op,adopt=False);f.work();f.prepare()
            self.assertIn('None.',Path(f.descriptor['report']['path']).read_text())
            f.validate_report(ok=False);f.approve();f.accept()
            # Empty review findings are valid only with complete coverage.
            receipt=json.loads(Path(f.receipt['path']).read_text())
            self.assertEqual(receipt['findings'],{})
            self.assertEqual(len(receipt['passes']),1)

    def test_missing_malformed_tampered_and_stale_receipts(self):
        f=self.fixture();f.work();f.approve();f.accept()
        baseline=deepcopy(f.descriptor)
        for reference in (None,{}, {'path':str(f.base/'absent.json'),'sha256':'0'*64,'bytes':1}):
            f.descriptor['planning_review']=reference;f.validate_report(ok=False)
        f.descriptor=deepcopy(baseline)
        raw=f.metadata.read_bytes();f.metadata.write_text('{}')
        f.validate_report(ok=False);f.metadata.write_bytes(raw)
        receipt=Path(f.receipt['path']);original=receipt.read_bytes();receipt.write_text('{}')
        f.validate_report(ok=False);receipt.write_bytes(original)
        f.validate_report()
        # Changing actual reviewed content plus refreshing ordinary pins cannot reuse acceptance.
        report=Path(f.descriptor['report']['path']);report.write_text(report.read_text().replace('None.','None.\n',1))
        f.descriptor['report']['sha256']=digest(report.read_bytes())
        for row in f.descriptor['inspections']:
            if row['category']=='report':row['sha256']=f.descriptor['report']['sha256']
        f.validate_report(ok=False)

    def test_unchanged_report_can_restart_after_superseded_review(self):
        for installed in (False, True):
            for replacement in (False, True):
                with self.subTest(installed=installed, replacement=replacement):
                    f = self.fixture(installed=installed)
                    f.work(); f.approve()
                    original_snapshot = deepcopy(f.snapshot)
                    subject = json.loads(f.metadata.read_text())['subject_file']
                    if replacement:
                        f.review('release')
                        f.review_id += '-second-opinion'
                        made = f.review('create', {'job_id': f.review_id,
                            'installation_id': f.manifest['installation_id'], 'plugin': 'ape',
                            'project_id': f.selection['project_id'], 'owner': 'fixture-owner',
                            'invocation_id': f.id, 'scope_id': f.scope, 'selection': f.selection,
                            'snapshot': f.snapshot})
                        f.review_caller = made['caller']
                    f.review('begin', {'requested_rereview': True})
                    attempt = f.review('launch', {'slot_id': 'review',
                        'request_id': f.review_id + '-minor-rereview'})
                    f.review('host-event', {'task_id': attempt['task_id'], 'event': {
                        'kind': 'accepted', 'request_id': attempt['request_id'],
                        'host_task_id': 'host-' + attempt['request_id'],
                        'child_thread_id': 'child-' + attempt['request_id'], 'status': 'completed',
                        'work_state': 'result_available', 'has_pending_child_runs': False,
                        'status_identity': {k: attempt['target'][k] for k in ('providerInstanceId', 'model', 'options')}}})
                    brief = json.loads(Path(attempt['path']).read_text())
                    result = json.loads(fixtures.worker_result(brief))
                    result.update(review_verdict='adverse', planning_review=f.assessment(), findings=[{
                        'id': 'M1', 'severity': 'minor', 'scenario': 'The report caveat needs explanation.',
                        'source_evidence': 'fixture:report', 'smallest_correction': 'Explain the caveat.'}])
                    f.review('result', {'task_id': attempt['task_id'],
                        'result_file': str(self.box.payload(result)), 'completion_id': 'done-' + attempt['request_id']})
                    self.assertFalse(f.review('finish')['accepted'])
                    f.review('release'); f.validate_report(ok=False)
                    prepared = f.prepare()
                    self.assertEqual(prepared['snapshot'], original_snapshot)
                    metadata = json.loads(f.metadata.read_text())
                    self.assertIsNone(metadata['reference'])
                    self.assertEqual(metadata['subject_file'], subject)
                    f.validate_report(ok=False)
                    f.review_id += '-recovery'
                    f.begin_review(); f.review_pass(); f.finish()
                    receipt = json.loads(Path(f.receipt['path']).read_text())
                    self.assertEqual(receipt['rounds_used'], 3)
                    self.assertIn('anthropic:M1', receipt['findings'])
                    f.validate_report(); f.accept()

    def test_relevant_source_request_criteria_and_author_drift_invalidate(self):
        for kind in ('source','request','criteria','coordinator','synthesizer','producing-selection','rubric'):
            with self.subTest(kind=kind):
                f=self.fixture(op='forage');f.work();f.approve()
                if kind=='source':f.local.write_text('VALUE = 2\n')
                elif kind=='request':f.request.write_text('Different question.')
                elif kind=='criteria':f.descriptor['criteria'][1]['minimum_findings']=0
                elif kind=='rubric':
                    rubric=f.package/'references/plan-review-rubric.md'
                    before=rubric.read_bytes()
                    try:
                        rubric.chmod(0o644);rubric.write_bytes(before+b'\nChanged domain criterion.\n')
                        f.validate_report(ok=False)
                        refused=self.box.job(f.package,'observation',f.job_id,{'caller':f.caller,
                            'stage_id':f.final_stage,'input_file':str(self.box.payload(f.descriptor))},check=False)
                        self.assertNotEqual(refused.returncode,0)
                    finally:rubric.write_bytes(before)
                    continue
                else:
                    job=json.loads(f.job_file.read_text())
                    if kind=='producing-selection':job['model_selection']['source']['answer']='tampered producing choice'
                    elif kind=='coordinator':job['ape_admission']['selection']['coordinator']['model']='changed'
                    else:job['tasks'][-1]['handles'][0]['observed_identity']['status']='unreported'
                    f.job_file.write_text(json.dumps(job))
                f.validate_report(ok=False);f.accept(ok=False)

    def test_adverse_and_partial_reviews_cannot_be_consumed_or_reclassified(self):
        for partial in (False,True):
            f=self.fixture();f.work();f.begin_review()
            result=f.review_pass(adverse=not partial,malformed=partial)
            self.assertIn(result['outcome'],('adverse','incomplete'))
            finished=f.finish(attach=False)
            self.assertFalse(finished['accepted'])
            self.assertIn('no accepted planning review',f.ape('attach',{'descriptor':f.descriptor,
                'metadata_file':str(f.metadata),'receipt':f.receipt['path']},ok=False))
            f.validate_report(ok=False)

    def test_actual_synthesizer_and_coordinator_lineages_are_included(self):
        f=self.fixture(op='forage',synth_author=True,coordinator_spare=True);f.work();f.begin_review()
        self.assertEqual({a['lineage'] for a in f.snapshot['authors']},{'openai','anthropic','google'})
        launched=f.review('launch',{'slot_id':'review','request_id':f.review_id+'-actual-author'})
        self.assertEqual(launched['mode'],'same-lineage')
        self.assertEqual(launched['target']['model'],'claude-fixture')
        # A strict selected panel refuses that actual-author collision.
        strict=self.fixture(op='forage',synth_author=True);strict.work();strict.prepare()
        strict.selection_data['review_panel'][0]['independent']=True
        strict.selection_data['author_lineages']=['anthropic']
        with self.assertRaises(models.SelectionError):models.freeze(strict.selection_data)

    def test_superseded_actual_research_authors_are_retained(self):
        f=self.fixture();f.work()
        job=json.loads(f.job_file.read_text())
        prior=deepcopy(job['tasks'][0])
        prior['task_id']='retired-source'
        def rekey(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('request_id','original_request_id','completion_id') and isinstance(item,str):
                        value[key]=item+'-retired'
                    else:rekey(item)
            elif isinstance(value,list):
                for item in value:rekey(item)
        rekey(prior)
        target=f.selection_data['profiles']['models'][2]['target']
        prior['target']=target
        prior['handles'][0]['target']=target
        prior['handles'][0]['observed_identity'].update(providerInstanceId=target['providerInstanceId'],model=target['model'],
            sources={'status':{'providerInstanceId':target['providerInstanceId'],'model':target['model']}})
        job['history'].append({'kind':'superseded-plan','tasks':[prior]})
        f.job_file.write_text(json.dumps(job))
        f.prepare()
        self.assertEqual({a['lineage'] for a in f.snapshot['authors']},{'openai','google'})

    def test_primary_panel_is_not_a_replacement_pool(self):
        f=self.fixture(panel=True);f.work();f.begin_review();f.review_pass()
        finished=f.finish(attach=False)
        self.assertFalse(finished['accepted'])
        self.assertEqual(len(json.loads(Path(f.receipt['path']).read_text())['requested_panel']),2)
        f.validate_report(ok=False)

    def test_stable_subject_invocation_lifetime_alias_once_and_unchanged_reuse(self):
        f=self.fixture();f.work();f.approve();f.accept()
        first=json.loads(f.metadata.read_text());scope=first['scope_id']
        for event in ('wake','repair','compaction'):
            result=f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'event':event})
            self.assertEqual(result,f.admission)
        forwarded=f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'forward':True})
        self.assertTrue(forwarded['forwarded'])
        self.assertIn('already forwarded',f.ape('continue',{'admission':forwarded,'invocation_id':f.id,'forward':True},ok=False))
        self.assertIn('new qualifying invocation',f.ape('continue',{'admission':f.admission,'invocation_id':'new-command'},ok=False))
        new=deepcopy(f.selection_data);new['invocation_id']='new-command'
        new_selection=models.freeze(new)
        data={**f.admission_input,'selection':new_selection,'selection_sha256':new_selection['selection_sha256'],
              'invocation_id':'new-command','operation':'https://github.com/example/repo'}
        fresh=f.ape('admit',data);self.assertEqual(fresh['scope_id'],scope);self.assertTrue(fresh['forwarded'])
        # New preferences do not relabel the old report or force a fresh pass.
        f.validate_report()
        retained=f.prepare();self.assertEqual(retained['metadata'],f.descriptor['planning_review'])
        state=json.loads(Path(first['subject_file']).read_text());self.assertEqual(state['rounds_used'],1)
        f.review('begin',ok=False)
        f.local.with_name('unrelated.py').write_text('OTHER = 1\n')
        self.box.run(['git','-C',f.project,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                      'commit','-qm','unrelated','--allow-empty'])
        result=f.ape('validate',{'descriptor':f.descriptor});self.assertTrue(result['head_observation']['changed'])
        self.assertEqual(result['rounds_used'],1)

    def test_forage_cannot_omit_final_synthesis_or_borrow_other_job_metadata(self):
        f=self.fixture(op='forage');job=deepcopy(f.job)
        job['stages']=job['stages'][:1];job['tasks']=job['tasks'][:1]
        job['requirements']={'R-SRC':'Compare pinned source'}
        self.assertIn('final synthesis',f.create_work(ok=False,job=job))
        a=self.fixture();a.work();a.approve()
        b=self.fixture();b.work()
        b.descriptor['planning_review']=a.descriptor['planning_review']
        self.assertIn('another producing job',b.accept(ok=False).stderr)

    def test_confidential_repeated_evidence_cannot_be_downgraded(self):
        f=self.fixture();f.work()
        f.inputs['evidence_paths']=[{'path':str(f.local),'data_class':'private-settings'},
                                   {'path':str(f.local),'data_class':'topic'}]
        f.prepare()
        row=next(r for r in f.snapshot['evidence_paths'] if r['path']==str(f.local))
        self.assertEqual(row['data_class'],'private-settings')
        f.begin_review()
        self.assertTrue(f.review('launch',{'slot_id':'review','request_id':f.review_id+'-private'},ok=False))

    def test_deterministic_fetch_and_cleanup_helpers_have_no_planning_pass(self):
        # No network/source code execution: invalid fetch input stops in deterministic URL validation.
        proc=self.box.run(['bash',self.package/'scripts/study-repo.sh','not-a-url'],check=False)
        self.assertNotEqual(proc.returncode,0)
        self.assertNotIn('selection',proc.stderr.lower())
        # Intermediate forage report reached real acceptance in every forage work() above.
        f=self.fixture(op='forage');f.work()
        research=self.box.state_of(f.job_id)['stages'][0]
        self.assertEqual(research['status'],'accepted-at-snapshot')
        self.assertFalse(f.metadata.exists())


if __name__=='__main__':unittest.main()
