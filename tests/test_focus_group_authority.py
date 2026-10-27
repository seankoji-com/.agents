"""Stage1 boundary probes, using invented offline authority and job records only.

The race is an intentionally red prerequisite test. The accepted plugin-only plan
requires authority to be rechecked at generic plan application. No live study,
receipt, model, or human approval is represented by these synthetic fixtures.
"""
import copy
import contextlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.jobs import decision, revise_plan
from core.jobs.store import JobError, Store, canonical, digest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'authority_boundary_study', ROOT / 'plugins/focus-group/scripts/study.py')
study = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = study
SPEC.loader.exec_module(study)
sys.path.insert(0, str(ROOT / 'plugins/focus-group/scripts'))


def lock_process(root, job_id, caller, entered, release, finished, reverse=False):
    """Two real processes, event barriers and the production flock objects. No sleeps."""
    import study as fg
    s = fg.Study(root, job_id)
    if reverse:  # Revocation owns only study.lock, never job.lock.
        with s.locked():
            entered.set()
            if not release.wait(10): raise RuntimeError('barrier timeout')
        finished.set(); return
    @contextlib.contextmanager
    def guard(before, operation, context):
        with s.locked():
            entered.set()
            if not release.wait(10): raise RuntimeError('barrier timeout')
            yield lambda before, proposed, context: None
    Store(root, job_id).transact(caller, lambda j: None, 'acceptance', commit_guard=guard)
    finished.set()


def domain_process(root, study_id, caller, owner, mode, entered, release, started, result):
    import authority
    s=authority.fg.Study(root,study_id); original=s.locked
    @contextlib.contextmanager
    def barrier_lock():
        with original():
            entered.set()
            if not release.wait(15): raise RuntimeError('barrier timeout')
            yield
    started.set()
    try:
        with patch.object(s,'locked',side_effect=barrier_lock):
            if mode=='revoke':authority.revoke(s,{'grant_id':'fixture-grant','owner':owner,'reason':'concurrent fixture revoke'})
            else:
                store=Store(root,study_id,verify_pins=lambda job:None)
                store.transact(caller,lambda j:None,'acceptance',commit_guard=authority.commit_guard(s,caller=caller))
        result.put({'ok':True})
    except Exception as exc:result.put({'ok':False,'error':str(exc)})


class RevisionBoundaryStore(Store):
    """Place a deterministic revocation after validation, before the job lock.

    The production transaction, source verification, owner decision and revision
    code remain unchanged. This hook controls only the concurrency interleaving.
    """
    before_plan_lock = None

    def transact(self, caller, fn, operation='mutate', **kwargs):
        if operation == 'plan-revision' and self.before_plan_lock:
            hook, self.before_plan_lock = self.before_plan_lock, None
            hook()
        return super().transact(caller, fn, operation, **kwargs)


class AuthorityApplicationBoundaryTests(unittest.TestCase):
    def fixture(self, base):
        store = RevisionBoundaryStore(base / 'jobs', 'authority-boundary')
        job = {
            'schema_version': 1, 'job_id': 'authority-boundary',
            'installation_id': 'fixture-install', 'workflow': 'focus-group/run',
            'owner': 'invented-owner', 'requirements': {'R1': 'Preserve bounded authority'},
            'authorization': {'actions': ['read']}, 'constraints': ['Synthetic offline fixture only'],
            'dependencies': [{'key': 'focus-group', 'plugin': 'focus-group'}],
            'pins': {'focus-group': {'package_digest': 'a' * 64}},
            'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 1000000, 'max_live_workers': 2},
            'stages': [{'id': 'scope', 'depends_on': [], 'requirements': ['R1'],
                        'status': 'pending', 'execution_mode': 'direct'}],
            'tasks': [], 'decisions': [], 'history': [], 'metrics': {},
            'result_contract': {'schema_version': 1}}
        store.create(job)
        caller = {'actor': 'coordinator', 'installation_id': job['installation_id'],
                  'workflow': job['workflow'], 'package_digest': 'a' * 64}
        source = base / 'invented-authority-source.txt'
        source.write_text('Invented owner permits this bounded fixture revision.\n')
        decision(store, caller, {
            'id': 'fixture-decision', 'scope': 'plan:fixture-revision',
            'quote': source.read_text().strip(), 'source': str(source),
            'source_sha256': digest(source.read_bytes())})
        return store, caller, source

    def test_contextual_owner_answer_cannot_be_faked_as_direct_exact_approval(self):
        expected = 'Approve this invented exact revision and ceiling'
        contextual = b'Question: permit bounded recovery?\nAnswer: Permit bounded recovery.\n'
        with self.assertRaises(study.StudyError) as caught:
            study.affirmative('Permit bounded recovery.', contextual, expected)
        self.assertEqual(caught.exception.code, 'approval_scope_mismatch')
        # Existing literal, per-revision direct semantics remain a valid control.
        study.affirmative(expected, ('Answer: ' + expected + '\n').encode(), expected)

    def test_source_revoked_before_validation_refuses_without_job_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            store, caller, source = self.fixture(Path(directory))
            before = canonical(store.load())
            source.write_text('Revoked invented authority.\n')
            with self.assertRaisesRegex(JobError, 'owner decision required'):
                revise_plan(store, caller,
                            {'id': 'fixture-revision', 'owner_decision_id': 'fixture-decision'},
                            {'policy': dict(store.load()['policy'], max_live_workers=3)})
            self.assertEqual(canonical(store.load()), before)

    def test_source_revoked_after_validation_must_refuse_at_application(self):
        with tempfile.TemporaryDirectory() as directory:
            store, caller, source = self.fixture(Path(directory))
            before = copy.deepcopy(store.load())
            store.before_plan_lock = lambda: source.write_text('Revoked invented authority.\n')
            error = None
            try:
                revise_plan(store, caller,
                            {'id': 'fixture-revision', 'owner_decision_id': 'fixture-decision'},
                            {'policy': dict(before['policy'], max_live_workers=3)})
            except JobError as exc:
                error = str(exc)
            after = store.load()
            self.assertIsNotNone(
                error,
                'Application persisted a plan revision after its source was revoked: '
                f'max_live_workers={after["policy"]["max_live_workers"]}, '
                f'revisions={len(after.get("plan_revisions", []))}, '
                f'source_current={digest(source.read_bytes()) == before["decisions"][0]["source_sha256"]}')
            self.assertEqual(canonical(after), canonical(before))


class GenericCommitGuardTests(AuthorityApplicationBoundaryTests):
    def test_create_and_prepare_optional_api_and_required_hook(self):
        from core.jobs import create_job, prepare
        with tempfile.TemporaryDirectory() as directory:
            store,caller,_=self.fixture(Path(directory)); job=store.load()
            job['job_id']='guarded-create'
            job['policy']['transaction_guard_required']=['create','prepare']
            job['tasks']=[{'task_id':'fixture-task','stage_id':'scope','logical_slot_id':'slot','request_id':'fixture-request',
                          'worker_id':'fixture/worker','dependency_key':'focus-group'}]
            pins=copy.deepcopy(job['pins']);pins['focus-group']['effective_workers']={'fixture/worker':{'bytes':'Fixture procedural definition'}}
            @contextlib.contextmanager
            def guard(*args):yield lambda *args:None
            with self.assertRaisesRegex(JobError,'required transaction guard missing'):
                create_job(job,store.root,pins)
            create_job(job,store.root,pins,commit_guard=guard)
            target=Store(store.root,job['job_id'])
            with self.assertRaisesRegex(JobError,'required transaction guard missing'):
                prepare(target,caller,'fixture-task',lambda *args:True,lambda *args:True)
            self.assertFalse((target.path/'briefs').exists())
            result=prepare(target,caller,'fixture-task',lambda *args:True,lambda *args:True,commit_guard=guard)
            self.assertEqual(digest(Path(result['path']).read_bytes()),result['sha256'])

    def test_all_five_acceptance_transactions_and_final_success_use_guard(self):
        from shared import job_acceptance as accept
        import subprocess
        for route in ('stage','reopen','record','success'):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as directory:
                store,caller,_=self.fixture(Path(directory)); calls=[]
                @contextlib.contextmanager
                def guard(*args):
                    yield lambda *args:calls.append('final')
                with patch('shared.adopter_planning.transaction_guard',return_value=guard), \
                     patch.object(accept,'verify_all_pins',side_effect=lambda store,caller=None:store.load()), \
                     patch.object(accept,'_ready_slots'),patch.object(accept,'_pending',return_value=False), \
                     patch.object(accept,'_semantic_binding',return_value='s'), \
                     patch.object(accept,'_adapter',return_value=(Path('fixture'),{'package_digest':'a'*64},{'validator_sha256':'v'})), \
                     patch.object(accept,'_invoke',return_value=(subprocess.CompletedProcess([],0,b'fixture',b''),True,{})), \
                     patch.object(accept,'validate_stage',return_value={'accepted':route!='reopen'}), \
                     patch.object(store,'transact',wraps=store.transact) as transactions:
                    if route=='stage':
                        self.assertTrue(accept.accept_stage(store,caller,'scope',[],'fixture')['accepted'])
                    else:
                        manager=patch.object(accept,'_unchanged',side_effect=JobError('drift')) if route=='record' else patch.object(accept,'_unchanged',side_effect=lambda *args:store.load())
                        with manager:out=accept.validate_final(store,caller,{'scope':[]},{'scope':'fixture'})
                        self.assertEqual(out['accepted'],route=='success')
                        self.assertEqual(store.load()['final_passes'],1)
                    names=[c.args[1].__name__ for c in transactions.call_args_list]
                    self.assertEqual(names,{'stage':['reserve','commit'],'reopen':['reserve','reopen'],
                                            'record':['reserve','success','record'],'success':['reserve','success']}[route])
                    self.assertTrue(all(c.kwargs['commit_guard'] is guard for c in transactions.call_args_list))
                    self.assertEqual(len(calls),2)

    def test_public_upgrade_is_supported_only_before_guard_enablement(self):
        from shared.job_upgrade import upgrade_package
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                base = Path(directory); store, caller, source = self.fixture(base)
                job = store.load(); job['pins']['focus-group'].update(package_dir=str(base/'old'),installation_id='fixture-install')
                job['metrics']['retained_finance_charges'] = 16
                if enabled: job['policy']['transaction_guard_required'] = ['plan-revision']
                # Synthetic fixture construction, not a supported policy bypass.
                from core.jobs.store import _atomic
                _atomic(store.file,canonical(job)); store.verify_pins = lambda j:None
                decision(store,caller,{'id':'upgrade','scope':'plan:upgrade','quote':source.read_text().strip(),
                                      'source':str(source),'source_sha256':digest(source.read_bytes())})
                before=store.file.read_bytes(); newpin=dict(job['pins']['focus-group'],package_dir=str(base/'new'),package_digest='c'*64)
                with patch('shared.job_upgrade.verify_all_pins',side_effect=lambda store,caller:store.load()), \
                     patch('shared.job_upgrade.adopt_pins',return_value={'focus-group':newpin}) as adopt, \
                     patch('shared.job_upgrade.record_job_root') as registry, \
                     patch('shared.job_upgrade.job_agents_roots',return_value=[]):
                    args=(store,caller,{'id':'upgrade','owner_decision_id':'upgrade','reason':'fixture approved upgrade'},
                          'focus-group',digest(before),'c'*64,base/'new',base/'prefix',base/'agents')
                    if enabled:
                        with self.assertRaisesRegex(JobError,'required transaction guard missing'): upgrade_package(*args)
                        adopt.assert_not_called(); registry.assert_not_called()
                        self.assertEqual(store.file.read_bytes(),before)
                        self.assertFalse((store.path/'migrations').exists())
                    else:
                        result=upgrade_package(*args); adopt.assert_called_once(); registry.assert_called_once()
                        self.assertEqual(Path(result['previous_state']['path']).read_bytes(),before)
                        self.assertEqual(store.load()['metrics']['retained_finance_charges'],16)
                        self.assertEqual(store.load()['pins']['focus-group'],newpin)

    def test_noop_runs_entry_final_and_exit_under_job_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            store, caller, _ = self.fixture(Path(directory)); before = store.file.read_bytes(); seen = []
            @contextlib.contextmanager
            def guard(old, operation, context):
                self.assertEqual(operation, 'acceptance'); seen.append('entry')
                yield lambda old, new, context: seen.append('final')
                seen.append('exit')
            store.transact(caller, lambda j: seen.append('body'), 'acceptance', commit_guard=guard)
            self.assertEqual(seen, ['entry', 'body', 'final', 'exit']); self.assertEqual(store.file.read_bytes(), before)

    def test_entry_final_and_write_failures_release_locks_without_pre_replace_mutation(self):
        for failure in ('entry', 'final', 'write'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                store, caller, _ = self.fixture(Path(directory)); before = store.file.read_bytes(); exits = []
                @contextlib.contextmanager
                def guard(old, operation, context):
                    try:
                        if failure == 'entry': raise JobError('entry refusal')
                        def final(*args):
                            if failure == 'final': raise JobError('final refusal')
                        yield final
                    finally: exits.append(True)
                def mutate(j): j['metrics']['fixture'] = 1
                manager = patch('core.jobs.store._atomic', side_effect=OSError('write refusal')) if failure == 'write' else contextlib.nullcontext()
                with manager, self.assertRaises((JobError, OSError)):
                    store.transact(caller, mutate, 'acceptance', commit_guard=guard)
                self.assertEqual(store.file.read_bytes(), before); self.assertEqual(exits, [True])
                store.transact(caller, lambda j: None, 'acceptance')  # Lock really released.

    def test_guard_required_enabling_refuses_before_adoption(self):
        with tempfile.TemporaryDirectory() as directory:
            store, caller, _ = self.fixture(Path(directory)); before = store.file.read_bytes(); adopted = []
            with self.assertRaisesRegex(JobError, 'required transaction guard missing'):
                revise_plan(store, caller, {'id':'enable','adopt_keys':['focus-group']},
                    {'policy':dict(store.load()['policy'],transaction_guard_required=['plan-revision'])},
                    lambda *args: adopted.append(True))
            self.assertEqual(adopted, []); self.assertEqual(store.file.read_bytes(), before)

    def test_required_guard_cannot_be_removed_or_bypassed_by_mutate(self):
        with tempfile.TemporaryDirectory() as directory:
            store, caller, _ = self.fixture(Path(directory))
            @contextlib.contextmanager
            def guard(*args): yield lambda *args: None
            store.transact(caller, lambda j:j['policy'].update(transaction_guard_required=['prepare','plan-revision']),
                           'plan-revision', commit_guard=guard)
            before = store.file.read_bytes()
            for operation in ('prepare','plan-revision'):
                with self.assertRaisesRegex(JobError, 'required transaction guard missing'):
                    store.transact(caller, lambda j:None, operation)
            with self.assertRaisesRegex(JobError, 'explicit transaction operation'):
                store.mutate(caller, lambda j:j['policy'].pop('transaction_guard_required'))
            with self.assertRaisesRegex(JobError, 'cannot be removed'):
                store.transact(caller, lambda j:j['policy'].update(transaction_guard_required=[]),'plan-revision',commit_guard=guard)
            with self.assertRaisesRegex(JobError, 'plan-revision'):
                store.transact(caller, lambda j:j['authorization'].update(actions=['write products']),'result')
            self.assertEqual(store.file.read_bytes(), before)
            # Reconciliation and cancellation retain the existing unguarded API.
            store.transact(caller, lambda j:j['metrics'].update(reconciled=True), 'task-observation')

    def test_two_process_opposite_arrivals_finish_without_inverse_lock(self):
        context = multiprocessing.get_context('spawn')
        for first_is_revoke in (False, True):
            with self.subTest(first_is_revoke=first_is_revoke), tempfile.TemporaryDirectory() as directory:
                store, caller, _ = self.fixture(Path(directory))
                events = [context.Event() for _ in range(6)]
                entered1, release1, done1, entered2, release2, done2 = events
                processes = [context.Process(target=lock_process,args=(str(store.root),store.path.name,caller,entered1,release1,done1,first_is_revoke)),
                             context.Process(target=lock_process,args=(str(store.root),store.path.name,caller,entered2,release2,done2,not first_is_revoke))]
                try:
                    processes[0].start(); self.assertTrue(entered1.wait(10))
                    processes[1].start()
                    release1.set(); self.assertTrue(done1.wait(10)); self.assertTrue(entered2.wait(10))
                    release2.set(); self.assertTrue(done2.wait(10))
                    for process in processes: process.join(10); self.assertEqual(process.exitcode, 0)
                finally:
                    release1.set(); release2.set()
                    for process in processes:
                        if process.pid is not None:
                            process.join(2)
                            if process.is_alive(): process.terminate(); process.join(2)


class OptionalAdapterCompatibilityTests(unittest.TestCase):
    def test_minimal_unmarked_store_prepares_without_invented_file(self):
        from shared.job_coordinator import prepare_task
        class FixtureStore:
            def load(self): return {'workflow':'fixture/plan','policy':{},'dependencies':[]}
        store=FixtureStore()
        with patch('core.jobs.prepare',return_value={'fixture':'brief'}) as prepare:
            self.assertEqual(prepare_task(store,{},'fixture-task',lambda *a:True,lambda *a:True),{'fixture':'brief'})
            self.assertIsNone(prepare.call_args.kwargs['commit_guard'])

    def test_required_guard_missing_store_identity_refuses_before_prepare(self):
        from shared.job_coordinator import prepare_task
        class FixtureStore:
            def load(self): return {'workflow':'fixture/plan','policy':{},'dependencies':[]}
        with patch('shared.adopter_planning.transaction_guard',return_value=lambda *a:None), \
             patch('core.jobs.prepare') as prepare:
            with self.assertRaisesRegex(JobError,'job identity'):
                prepare_task(FixtureStore(),{},'fixture-task',lambda *a:True,lambda *a:True)
            prepare.assert_not_called()

    def test_optional_direct_create_and_required_cross_job_binding(self):
        import plan_review
        class Study:
            job_dir=Path('/invented/fixture-jobs/study')
            def exists(self):return True
            def require(self):return {'revision':'fixture'}
            def approvals(self,revision):return self.records
        direct=Study();direct.records=[{'kind':'approval'}]
        delegated=Study();delegated.records=[{'kind':'delegated-approval'}]
        job={'job_id':'study','workflow':'focus-group/run','policy':{},'authorization':{}}
        wrong=Path('/invented/other-jobs/study/job.json')
        with patch.object(plan_review,'authority_study',return_value=direct):
            self.assertIsNone(plan_review.transaction_guard(job,'create',job_file=wrong))
            for field in ('previous','proposed','typed'):
                old=copy.deepcopy(job);new=copy.deepcopy(job)
                if field=='typed':new['authorization']['delegated_authority']={'grant_id':'fixture'}
                else:(old if field=='previous' else new)['policy']['transaction_guard_required']=['prepare']
                with self.subTest(field=field),self.assertRaisesRegex(ValueError,'another generic job'):
                    plan_review.transaction_guard(old,'create',proposed=new,job_file=wrong)
        # Even a proposed unmarked/direct descriptor cannot strip current delegation.
        with patch.object(plan_review,'authority_study',side_effect=[delegated,direct]), \
             self.assertRaisesRegex(ValueError,'another generic job'):
            plan_review.transaction_guard(job,'create',proposed=copy.deepcopy(job),job_file=wrong)


class DelegatedAuthorityTests(unittest.TestCase):
    def setUp(self):
        import authority
        self.authority = authority
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        from tests.test_focus_group_plan import Workspace
        from shared import planning_review
        original = planning_review.host_event
        def observed(store, caller, task, event, *args, **kw):
            event = copy.deepcopy(event)
            if isinstance(event.get('status_identity'), dict):
                event['status_identity']['options'] = event['status_identity'].get('options', {})
            return original(store, caller, task, event, *args, **kw)
        self.ws = Workspace(self.base)
        env = patch.dict(os.environ, self.ws.policy_env)
        env.start(); self.addCleanup(env.stop)
        with patch.object(planning_review, 'host_event', side_effect=observed):
            self.view = self.ws.plan(self.ws.draft(mode='capture-only'))
        self.s = authority.fg.Study(self.ws.root, self.view['study_id'])
        plan = self.s.plan(self.view['revision'])['plan']
        source = self.base / 'owner-context.txt'
        source.write_text('Question: bounded recovery?\nOwner answer: permit the fixture delegate within these exact limits.\n')
        native = self.base / 'native.json'
        native.write_text(json.dumps({'messages':[{'messageId':'fixture-owner-native','creationSource':'web-user','content':source.read_text()}]}))
        self.owner = {'id':'fixture-owner','message_ref':'fixture:native-owner-message',
            'source':authority.descriptor(source),'context':source.read_text(),
            'quote':'permit the fixture delegate within these exact limits.',
            'native_observation':authority.descriptor(native),
            'native_messages':[{'messageId':'fixture-owner-native','creationSource':'web-user'}]}
        self.caller = {'actor':'coordinator','installation_id':'fixture-install','workflow':'focus-group/run','package_digest':'a'*64}
        self.data = {'id':'fixture-grant','owner':self.owner,'delegate':{'id':'fixture-delegate','caller':self.caller},
            'constraints':{'product_writes':False,'modes':['capture-only','combined'],'max_tasks':100,
                'max_concurrency':4,'max_attempts_per_slot':5,'max_repair_cycles':22,'deadline':'2030-01-01T00:00:00Z'},
            'expires_at':'2029-12-31T00:00:00Z','review':plan['review'],
            'package':{'dependency_key':'focus-group','installation_id':'fixture-install','package_digest':'a'*64,'bundle_digest':'b'*64}}

    def approve(self):
        a = self.authority
        grant = a.grant(self.s, self.data)
        approval = a.approve_delegated(self.s, {'revision':self.view['revision'], 'grant_id':grant['id'],'delegate':grant['delegate']})
        return grant, approval

    def job(self):
        a=self.authority; plan=self.s.plan(self.view['revision'])['plan']
        requirements,stages=a.fg.job_contract(plan,self.view['revision'])
        for s in stages:s.update(status='pending',execution_mode='direct')
        job={'schema_version':1,'job_id':self.s.id,'installation_id':'fixture-install','workflow':'focus-group/run',
             'owner':'fixture-owner','requirements':requirements,'authorization':{'actions':['dispatch approved study tasks'],
             'study_revision':self.view['revision'],'sharing':plan['sharing']},'constraints':['Synthetic fixture only'],
             'dependencies':[{'key':'focus-group','plugin':'focus-group'}],
             'pins':{'focus-group':{'package_digest':'a'*64,'bundle_digest':'b'*64,'installation_id':'fixture-install',
                                   'package_dir':str(ROOT/'plugins/focus-group')}},
             'policy':{'max_repair_cycles':22,'max_live_workers':4,'max_artifact_bytes':16777216},
             'stages':stages,'tasks':[],'decisions':[],'history':[],'metrics':{},'result_contract':{'schema_version':1}}
        job['focus_group_plan']=a.fg.planning_module().descriptor(self.s,self.view['revision'])
        a.fg.planning_module().bind_job(job,plan,self.s.read(f'planning/{self.view["revision"]}/run.json'))
        store=Store(self.ws.root,self.s.id,verify_pins=lambda j:None); store.create(job)
        return store

    def enable(self):
        self.approve(); store=self.job(); a=self.authority
        inputs=a.revision_inputs(self.s,store.load(),self.view['revision'],'fixture',{'policy':store.load()['policy']})
        decision(store,**inputs['decision_input'])
        inp=inputs['plan_revision_input']; guard=a.commit_guard(self.s,caller=self.caller)
        revise_plan(store,**inp,commit_guard=guard)
        return store,inputs

    def test_actual_guard_enables_once_and_rejects_candidate_proof_stripping(self):
        self.approve(); store=self.job(); a=self.authority
        inputs=a.revision_inputs(self.s,store.load(),self.view['revision'],'fixture',{'policy':store.load()['policy']})
        decision(store,**inputs['decision_input']); before=store.file.read_bytes()
        inp=inputs['plan_revision_input']; guard=a.commit_guard(self.s,caller=self.caller)
        for defect in ('candidate','proof','caller','grant','marker','generation','normalized'):
            with self.subTest(defect=defect):
                changed=copy.deepcopy(inp)
                if defect=='candidate':changed['new_plan']['policy']['max_live_workers']=3
                if defect=='proof':changed['revision'].pop('authority_proof')
                if defect=='caller':changed['caller']['actor']='worker'
                if defect=='grant':changed['new_plan']['authorization']['delegated_authority']['grant_id']='other'
                if defect=='marker':changed['new_plan']['authorization'].pop('delegated_authority')
                if defect=='generation':
                    store.transact(self.caller,lambda j:j['metrics'].update(changed=True),'task-observation')
                original=store.transact
                def normalized(caller,fn,operation='mutate',**kw):
                    def apply(job):
                        result=fn(job);job['constraints'].append('Unrequested normalized scope mutation');return result
                    return original(caller,apply,operation,**kw)
                manager=patch.object(store,'transact',side_effect=normalized) if defect=='normalized' else contextlib.nullcontext()
                with manager,self.assertRaises((JobError,a.fg.StudyError,KeyError,TypeError)):
                    revise_plan(store,**changed,commit_guard=guard)
                if defect=='generation':
                    from core.jobs.store import _atomic
                    _atomic(store.file,before)  # Restore only the invented fixture state.
                self.assertEqual(store.file.read_bytes(),before)
        revise_plan(store,**inp,commit_guard=guard)
        self.assertEqual(len(store.load()['plan_revisions']),1)
        self.assertTrue(store.load()['authorization']['delegated_authority'])
        with self.assertRaises(JobError):revise_plan(store,**inp,commit_guard=guard)

    def test_resume_transition_uses_proposed_dependency_and_pin(self):
        from shared import adopter_planning as adopter
        from unittest.mock import Mock
        current_dep = {'key': 'current', 'plugin': 'focus-group'}
        proposed_dep = {'key': 'proposed', 'plugin': 'focus-group'}
        current_pin = {'package_dir': '/synthetic/current'}
        proposed_pin = {'package_dir': '/synthetic/proposed'}
        current = {'workflow': 'focus-group/run', 'dependencies': [current_dep],
                   'pins': {'current': current_pin}, 'policy': {'transaction_guard_required': ['plan-revision']}}
        proposed = {'workflow': 'focus-group/resume', 'dependencies': [proposed_dep],
                    'pins': {'proposed': proposed_pin}, 'policy': current['policy']}
        expected_guard = lambda *args: None
        adapter = Mock(transaction_guard=Mock(return_value=expected_guard))
        with patch('shared.job_coordinator.verify_pinned_dependency', return_value=True) as verify:
            with patch.object(adopter, 'focus_group_adapter', return_value=adapter) as factory:
                self.assertIs(adopter.transaction_guard(current, 'plan-revision', proposed=proposed,
                                                       caller=self.caller), expected_guard)
                verify.assert_called_once_with(proposed_dep, proposed_pin)
                factory.assert_called_once_with(Path(proposed_pin['package_dir']))
                adapter.transaction_guard.assert_called_once_with(proposed, 'plan-revision', proposed=proposed,
                                                                  caller=self.caller, job_file=None)
            with patch.object(adopter, 'focus_group_adapter', return_value=object()):
                with self.assertRaisesRegex(JobError, 'capability missing'):
                    adopter.transaction_guard(current, 'plan-revision', proposed=proposed, caller=self.caller)

    def test_pinned_resolver_compares_proposed_marker_and_refuses_missing_capability(self):
        from shared import adopter_planning as adopter
        self.approve(); store=self.job(); a=self.authority
        inputs=a.revision_inputs(self.s,store.load(),self.view['revision'],'resolver',{'policy':store.load()['policy']})
        decision(store,**inputs['decision_input']); inp=inputs['plan_revision_input']
        prospective={**store.load(),**inp['new_plan']}
        with patch('shared.job_coordinator.verify_pinned_dependency',return_value=True):
            guard=adopter.transaction_guard(store.load(),'plan-revision',proposed=prospective,caller=self.caller,job_file=store.file)
            self.assertTrue(callable(guard))
            with patch.object(adopter,'focus_group_adapter',return_value=object()):
                with self.assertRaisesRegex(JobError,'capability missing'):
                    adopter.transaction_guard(store.load(),'plan-revision',proposed=prospective,caller=self.caller,job_file=store.file)
        before=store.file.read_bytes()
        wrong=copy.deepcopy(inp);wrong['caller']['unbound_extra_identity']='other'
        with self.assertRaisesRegex(a.fg.StudyError,'actual transaction caller'):
            revise_plan(store,**wrong,commit_guard=guard)
        self.assertEqual(store.file.read_bytes(),before)
        revise_plan(store,**inp,commit_guard=guard)
        stripped=copy.deepcopy(store.load());stripped['policy']['transaction_guard_required']=[]
        stripped['authorization'].pop('delegated_authority')
        with self.assertRaisesRegex(a.fg.StudyError,'marker missing'):
            a.fg.planning_module().validate_job(stripped)

    def test_live_revoke_refuses_guard_and_preserves_intake(self):
        store,_=self.enable(); a=self.authority
        a.revoke(self.s,{'grant_id':'fixture-grant','owner':self.owner,'reason':'revoke before prepare'})
        before=store.file.read_bytes()
        with self.assertRaisesRegex(a.fg.StudyError,'revoked'):
            store.transact(self.caller,lambda j:j['metrics'].update(unauthorized=True),'prepare',commit_guard=a.commit_guard(self.s,caller=self.caller))
        self.assertEqual(store.file.read_bytes(),before)
        store.transact(self.caller,lambda j:j['metrics'].update(raw_result_retained=True),'result')
        store.transact(self.caller,lambda j:j['metrics'].update(reconciled=True),'task-observation')

    def test_native_receipt_package_revision_and_final_expiry_are_live_inputs(self):
        store,_=self.enable();a=self.authority
        approval=self.s.approvals(self.view['revision'])[-1]
        paths=[Path(self.owner['native_observation']['path']),Path(approval['review']['receipt']['path'])]
        for path in paths:
            with self.subTest(path=path.name):
                original=path.read_bytes();before=store.file.read_bytes()
                try:
                    path.write_bytes(original+b' ')
                    with self.assertRaises((a.fg.StudyError,JobError)):
                        store.transact(self.caller,lambda j:None,'acceptance',commit_guard=a.commit_guard(self.s,caller=self.caller))
                    self.assertEqual(store.file.read_bytes(),before)
                finally:path.write_bytes(original)
        from core.jobs.store import _atomic
        before=store.file.read_bytes();bad=store.load();bad['pins']['focus-group']['bundle_digest']='c'*64
        _atomic(store.file,canonical(bad))
        try:
            with self.assertRaisesRegex(a.fg.StudyError,'package/adoption'):
                store.transact(self.caller,lambda j:None,'prepare',commit_guard=a.commit_guard(self.s,caller=self.caller))
        finally:_atomic(store.file,before)
        current=self.s.read('current.json')
        with self.s.locked():self.s.write('current.json',dict(current,revision='f'*64))
        try:
            with self.assertRaises(a.fg.StudyError):
                store.transact(self.caller,lambda j:None,'prepare',commit_guard=a.commit_guard(self.s,caller=self.caller))
        finally:
            with self.s.locked():self.s.write('current.json',current)
        original_now=a.fg.utc_now;expired=[False]
        def clock(value=None):return original_now('2030-01-01T00:00:01Z') if expired[0] else original_now(value)
        def apply(job):job['metrics']['not_persisted']=True;expired[0]=True
        with patch.object(a.fg,'utc_now',side_effect=clock),self.assertRaisesRegex(a.fg.StudyError,'expired'):
            store.transact(self.caller,apply,'prepare',commit_guard=a.commit_guard(self.s,caller=self.caller))
        self.assertEqual(store.file.read_bytes(),before)

    def test_final_success_rechecks_live_authority_after_validator_without_extra_pass(self):
        from shared import job_acceptance as accept
        store,_=self.enable(); a=self.authority
        for revoked in (False,True):
            if revoked:
                # A subsequent existing pass, not a hidden extra reserve.
                pass
            calls=[]
            def invoke(*args):
                calls.append('validator')
                if revoked and len(calls)==1:
                    a.revoke(self.s,{'grant_id':'fixture-grant','owner':self.owner,'reason':'revoke during final validator'})
                import subprocess
                return subprocess.CompletedProcess([],0,b'fixture',b''),True,{}
            def verify(store,caller=None):return store.load()
            guard=a.commit_guard(self.s,caller=self.caller)
            before=store.load().get('final_passes',0)
            # Unit controls isolate the actual transaction/reservation/live domain
            # guard. Installed authoritative validator/receipt coverage is Stage3.
            with patch('shared.adopter_planning.transaction_guard',return_value=guard), \
                 patch.object(accept,'verify_all_pins',side_effect=verify), \
                 patch.object(accept,'validate_stage',return_value={'accepted':True}), \
                 patch.object(accept,'_adapter',return_value=(Path('fixture'),{'package_digest':'a'*64},{})), \
                 patch.object(accept,'_invoke',side_effect=invoke), \
                 patch.object(accept,'_ready_slots'),patch.object(accept,'_pending',return_value=False):
                result=accept.validate_final(store,self.caller,{s['id']:[] for s in store.load()['stages']},
                                              {s['id']:'fixture' for s in store.load()['stages']})
            self.assertEqual(result['accepted'],not revoked,result)
            self.assertEqual(store.load()['final_passes'],before+1)
            self.assertEqual(self.s.ledger()['charged'],{})

    def concurrent_order(self,first):
        store,_=self.enable(); before=store.file.read_bytes()
        ctx=multiprocessing.get_context('spawn'); records={}; processes=[]; results={}
        try:
            for mode in (first, 'revoke' if first=='apply' else 'apply'):
                entered,release,started=ctx.Event(),ctx.Event(),ctx.Event(); queue=ctx.Queue()
                process=ctx.Process(target=domain_process,args=(str(self.ws.root),self.s.id,self.caller,self.owner,mode,entered,release,started,queue))
                records[mode]=(entered,release,started,queue); processes.append(process)
                process.start(); self.assertTrue(started.wait(15))
                if mode==first:self.assertTrue(entered.wait(15))
            records[first][1].set()
            second='revoke' if first=='apply' else 'apply'
            self.assertTrue(records[second][0].wait(15)); records[second][1].set()
            for mode,(_,_,_,queue) in records.items():results[mode]=queue.get(timeout=20)
            for process in processes:process.join(15);self.assertEqual(process.exitcode,0)
            self.assertTrue(results['revoke']['ok'],results)
            self.assertEqual(results['apply']['ok'],first=='apply',results)
            if first=='revoke':self.assertIn('revoked',results['apply']['error'])
            self.assertEqual(store.file.read_bytes(),before)
        finally:
            for _,release,_,queue in records.values():release.set()
            for process in processes:
                process.join(2)
                if process.is_alive():process.terminate();process.join(2)

    def test_real_domain_apply_first_serializes_revocation_until_after_check(self):
        self.concurrent_order('apply')

    def test_real_domain_revoke_first_refuses_apply_without_deadlock(self):
        self.concurrent_order('revoke')

    def test_new_genuine_direct_answer_can_replace_delegation_without_weakening_guard(self):
        store,_=self.enable(); a=self.authority
        request=self.ws.approval(self.view)
        from argparse import Namespace
        a.fg.op_approve(Namespace(state_root=str(self.ws.root),study=self.s.id,input=str(request)))
        approval=self.s.approvals(self.view['revision'])[-1]
        self.assertNotEqual(approval['kind'],'delegated-approval')
        path=Path(approval['source']); self.assertEqual(path.read_text().strip(),'Selected option: '+approval['statement'])
        decision(store,self.caller,{'id':'direct-replacement','scope':'plan:direct-replacement','source':str(path),
                    'source_sha256':approval['source_sha256'],'quote':approval['statement']})
        auth=copy.deepcopy(store.load()['authorization']);auth.pop('delegated_authority')
        revise_plan(store,self.caller,{'id':'direct-replacement','owner_decision_id':'direct-replacement'},
            {'authorization':auth},commit_guard=a.commit_guard(self.s,caller=self.caller))
        self.assertEqual(set(store.load()['policy']['transaction_guard_required']),set(a.OPERATIONS))

    def test_real_independent_receipt_and_full_context_derive_without_fake_owner_answer(self):
        grant, approval = self.approve()
        self.assertEqual(self.authority.check_live(self.s)['record_sha256'],approval['record_sha256'])
        self.assertTrue(approval['derived']); self.assertNotIn(approval['statement'], self.owner['context'])
        self.assertEqual(grant['owner']['context'],self.owner['context'])
        self.assertTrue(self.authority.fg.approval_state(self.s.approvals(self.view['revision']),self.view['revision'],
                        self.authority.fg.ceiling(self.s.plan(self.view['revision'])['plan'],self.s.ledger()))['derived'])
        with self.assertRaises(self.authority.fg.StudyError):
            self.authority.fg.affirmative(approval['statement'], self.owner['context'].encode(),approval['statement'])

    def test_revoke_source_change_expiry_limits_and_revision_refuse(self):
        grant, approval = self.approve(); a = self.authority
        a.revoke(self.s, {'grant_id':grant['id'],'owner':self.owner,'reason':'fixture revoke'})
        with self.assertRaisesRegex(a.fg.StudyError, 'revoked'): a.check_live(self.s)
        self.assertEqual(len(self.s.approvals(self.view['revision'])),1)
        # Revocation preserves raw evidence and all charge counters.
        self.assertEqual(self.s.ledger()['charged'],{})

    def test_source_change_and_expiry_and_dynamic_bounds(self):
        _, _ = self.approve(); a = self.authority
        with self.assertRaisesRegex(a.fg.StudyError, 'expired'):
            a.check_live(self.s, now='2030-01-01T00:00:01Z')
        ledger = self.s.ledger(); ledger['slots']['invented-input'] = 6
        with self.s.locked(): self.s.write('ledger.json',ledger)
        with self.assertRaisesRegex(a.fg.StudyError, 'attempts'): a.check_live(self.s)
        ledger['slots'] = {}
        with self.s.locked(): self.s.write('ledger.json',ledger)
        Path(self.owner['source']['path']).write_text('Revoked fixture authority')
        with self.assertRaisesRegex(a.fg.StudyError, 'bytes changed'): a.check_live(self.s)

    def test_owner_amendment_is_reopened_and_ceiling_growth_needs_exact_amendment(self):
        a=self.authority; amendment=self.base/'owner-amendment.txt'
        amendment.write_text('Actual invented owner amendment: use the fixture independent reviewer.\n')
        self.owner['amendments']=[{'source':a.descriptor(amendment),'context':amendment.read_text(),
                                  'quote':'use the fixture independent reviewer.'}]
        self.data['review_source']=self.owner['amendments'][0]['source']
        grant,approval=self.approve();original=amendment.read_bytes()
        amendment.write_bytes(original+b'changed')
        with self.assertRaisesRegex(a.fg.StudyError,'bytes changed'):a.check_live(self.s)
        amendment.write_bytes(original)
        ledger=self.s.ledger();ledger['charged']['first']=1  # Earlier revision's retained charge, no current slot filled.
        with self.s.locked():self.s.write('ledger.json',ledger)
        with self.assertRaisesRegex(a.fg.StudyError,'ceiling is insufficient'):a.check_live(self.s)
        amended=a.approve_delegated(self.s,{'revision':self.view['revision'],'grant_id':grant['id'],'delegate':grant['delegate']})
        self.assertEqual(amended['scope']['max_tasks'],approval['scope']['max_tasks']+1)
        self.assertEqual(amended['previous_record_sha256'],approval['record_sha256'])
        self.assertEqual(a.check_live(self.s)['record_sha256'],amended['record_sha256'])

    def test_invalid_grant_does_not_leave_an_authority_record(self):
        self.data['constraints']['max_tasks'] = 1
        with self.assertRaisesRegex(self.authority.fg.StudyError, 'ceiling'): self.authority.grant(self.s,self.data)
        self.assertEqual(self.authority.chain(self.s,'authority/grants'),[])


class CoreRefactorContractTests(unittest.TestCase):
    """Public source APIs, real job files and published schema refusals."""

    def fixture(self, base):
        prior, caller, _ = AuthorityApplicationBoundaryTests.fixture(self, base)
        return Store(prior.root, prior.path.name), caller

    def test_mutate_replacement_preserves_return_and_callback_object_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store, caller = self.fixture(Path(directory)); captured = {}
            def replace(job):
                captured['input'] = job
                job['metrics']['callback'] = 'retained only on input object'
                result = copy.deepcopy(job)
                result['metrics'] = {'replacement': 'persist this distinct object'}
                captured['output'] = result
                return result
            result = store.mutate(caller, replace)
            self.assertIs(result, captured['output'])
            self.assertIsNot(result, captured['input'])
            self.assertEqual(captured['input']['metrics'], {'callback': 'retained only on input object'})
            self.assertEqual(store.load(), result)
            self.assertEqual(digest(store.file.read_bytes()), digest(canonical(result)))

    def test_mutate_falsy_returns_noop_refusals_and_direct_transaction_result(self):
        for returned in (None, False, 0, {}):
            with self.subTest(returned=returned), tempfile.TemporaryDirectory() as directory:
                store, caller = self.fixture(Path(directory)); captured = {}
                def edit(job):
                    captured['input'] = job; job['metrics']['edit'] = 1
                    return returned
                result = store.mutate(caller, edit)
                self.assertIs(result, captured['input']); self.assertEqual(result, store.load())
                before = store.file.read_bytes()
                self.assertIs(store.transact(caller, lambda job: False), False)
                self.assertEqual(store.file.read_bytes(), before)
                self.assertEqual(store.mutate(caller, lambda job: None), store.load())
                self.assertEqual(store.file.read_bytes(), before)
                def enable(job):
                    out = copy.deepcopy(job); out['policy']['transaction_guard_required'] = ['prepare']
                    return out
                with self.assertRaisesRegex(JobError, 'required transaction guard missing'):
                    store.mutate(caller, enable)
                self.assertEqual(store.file.read_bytes(), before)
                def fail(job):
                    job['metrics']['unpersisted'] = True
                    raise ValueError('fixture callback refusal')
                with self.assertRaisesRegex(ValueError, 'fixture callback refusal'):
                    store.mutate(caller, fail)
                self.assertEqual(store.file.read_bytes(), before)

    def test_published_graph_validation_retains_order_independent_refusals(self):
        from tests.test_jobs_stage3 import JobStateTests
        from core.jobs.store import validate
        job = JobStateTests().base()
        job['stages'].reverse()
        self.assertIs(validate(job), job)
        for defect, message in (('stage', 'duplicate stage'), ('unknown', 'unknown stage dependency'),
                                ('cycle', 'cyclic stage'), ('task', 'duplicate task or request'),
                                ('request', 'duplicate task or request'), ('slot', 'duplicate logical'),
                                ('task-stage', 'task references unknown stage')):
            with self.subTest(defect=defect):
                bad = copy.deepcopy(job)
                if defect == 'stage': bad['stages'].append(copy.deepcopy(bad['stages'][0]))
                elif defect == 'unknown': bad['stages'][0]['depends_on'] = ['missing']
                elif defect == 'cycle': next(s for s in bad['stages'] if s['id'] == 's0')['depends_on'] = ['s4']
                elif defect == 'task-stage': bad['tasks'][0]['stage_id'] = 'missing'
                else:
                    new = copy.deepcopy(bad['tasks'][0])
                    if defect != 'task': new['task_id'] = 'second'
                    if defect != 'request': new['request_id'] = 'second-request'
                    if defect != 'slot': new['logical_slot_id'] = 'second-slot'
                    bad['tasks'].append(new)
                with self.assertRaisesRegex(JobError, message): validate(bad)

    def test_schema_constraints_local_refs_and_malformed_schema_refusals(self):
        from core import schema
        from core.errors import InvalidInput
        contract = {'type':'object', 'required':['count','names'], 'additionalProperties':False,
            'properties':{'count':{'type':'integer','minimum':1,'maximum':2},
                'names':{'type':'array','minItems':1,'maxItems':2,'uniqueItems':True,
                    'items':{'$ref':'#/$defs/name'}}},
            '$defs':{'name':{'type':'string','minLength':2,'maxLength':3,'pattern':'^[a-z]+$'}}}
        schema.check_keywords(contract)
        self.assertEqual(schema.errors({'count':1,'names':['ab','cd']},contract), [])
        for value in ({'count':True,'names':['ab']}, {'count':0,'names':['ab']}, {'count':3,'names':['ab']},
                      {'count':1,'names':[]}, {'count':1,'names':['ab','cd','ef']}, {'count':1,'names':['ab','ab']},
                      {'count':1,'names':['a']}, {'count':1,'names':['abcd']}, {'count':1,'names':['AB']},
                      {'count':1}, {'count':1,'names':['ab'],'extra':1}):
            with self.subTest(value=value): self.assertTrue(schema.errors(value,contract))
        self.assertTrue(schema.errors(True, {'type':'number'}))
        self.assertEqual(schema.errors(1.5, {'type':'number','minimum':1,'maximum':2}), [])
        self.assertTrue(schema.errors({'a':'bad'}, {'type':'object','additionalProperties':{'type':'integer'}}))
        self.assertEqual(schema.errors({'a':2}, {'type':'object','additionalProperties':{'type':'integer'}}), [])
        self.assertTrue(schema.errors(1, {'oneOf':[{'type':'number'},{'type':'integer'}]}))
        self.assertTrue(schema.errors(None, {'anyOf':[{'type':'number'},{'type':'string'}]}))
        for malformed in ({'items':[{'type':'string'}]}, {'propertyNames':False},
                          {'properties':{'x':{'unknown-keyword':True}}},
                          {'$defs':{'x':{'unknown-keyword':True}}},
                          {'anyOf':[{'unknown-keyword':True}]}, {'oneOf':[{'unknown-keyword':True}]}):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'invented.schema.json'; path.write_text(json.dumps(malformed))
                with self.assertRaises(InvalidInput): schema.load_schema_file(path)
        with self.assertRaises(InvalidInput): schema.errors(1, {'$ref':'https://example.invalid/schema'})
        with self.assertRaises(KeyError): schema.errors(1, {'$ref':'#/$defs/missing','$defs':{}})


if __name__ == '__main__':
    unittest.main()
