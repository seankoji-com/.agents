"""Synthetic older package identity upgrade and owner-bound authorization, all offline."""
import copy,json,tempfile,unittest
from pathlib import Path
from tests.focus_group_install_fixtures import RecoveryInstallation,module_deadline

def setUpModule():module_deadline()


def full_revision(h,s,kind,patch):
    """Public preflight/finalizer on the complete candidate before proof creation."""
    import authority as a
    from shared.job_coordinator import selection_plan_revision
    from shared.document_authors import refresh_new_task_authors
    current=h.job_state();new=a.candidate_scope(current);new.update(copy.deepcopy(patch))
    new['model_selection_history']=copy.deepcopy(new.get('model_selection_history') or {})
    new['model_selection_history'][current['model_selection_sha256']]=current['model_selection']
    selection_plan_revision(copy.deepcopy(current),new)
    refresh_new_task_authors(copy.deepcopy(current),new)
    inputs=a.revision_inputs(s,current,h.view['revision'],kind,new)
    h.job_ok('decision',inputs['decision_input']);h.job_ok('plan-revision',inputs['plan_revision_input'])
    return inputs


def report_and_final(h,s,owner,grant,revoke=True):
    import authority as a
    from core.jobs.store import JobError
    from shared.job_coordinator import pinned_store
    code,out=h.accept('first-impression');assert code==0 and out['accepted'],out
    # Full supported revision inputs preserve normalized author data and actual
    # accepted plan receipts. No partial proof is retrospectively relabelled.
    out=h.rp_ok(*h.study('analysis-inputs'),'--capabilities',h.catalog(),'--now','2029-06-01T00:00:00Z')
    full_revision(h,s,'analysis-full',out['plan_revision_input']['new_plan'])
    record=s.read('report/inputs/'+out['inputs_sha256']+'.json')
    synthesis={'schema':'focus-group/synthesis','schema_version':1,'study_revision':h.view['revision'],
        'inputs_sha256':out['inputs_sha256'],'observations':[],'findings':[],'backlog':[],
        'decision':{'answer':'inconclusive','summary':'Invented capture-only records establish no feature recommendation.',
            'finding_ids':[],'uncertainty':'Synthetic fixture evidence, no completed browser journeys.'}}
    code,out=h.run_analysis(synthesis);assert code==0,out
    code,out=h.accept('analysis');assert code==0 and out['accepted'],out
    code,out=h.render();assert code==0,out
    bundle=Path(out['data']['bundle'])
    out=h.rp_ok(*h.study('review-slot'),'--bundle',bundle,'--capabilities',h.catalog(),'--now','2029-06-01T00:00:00Z')
    full_revision(h,s,'fidelity-full',out['plan_revision_input']['new_plan'])
    h.run_review(identity=copy.deepcopy(s.plan(h.view['revision'])['plan']['review']))
    code,out=h.accept('review');assert code==0 and out['accepted'],out
    from shared import job_acceptance as acceptance
    from unittest.mock import patch
    store=pinned_store(h.root,s.id);accepted=h.job_state()
    receipts={row['id']:json.loads(Path(row['acceptance']['path']).read_text()) for row in accepted['stages']}
    inputs={sid:receipt['input_file'] for sid,receipt in receipts.items()}
    argvs={row['id']:[str(h.package/'scripts/validate_study.py'),'--input',inputs[row['id']]] for row in accepted['stages']}
    ledger_before=s.ledger();passes=accepted.get('final_passes',0)
    with patch('shared.adopter_planning.transaction_guard',return_value=None):
        try:acceptance.validate_final(store,h.caller,argvs,inputs)
        except JobError as exc:assert 'required transaction guard missing' in str(exc)
        else:raise AssertionError('Missing final guard must refuse before reserve')
    assert h.job_state().get('final_passes',0)==passes
    positive=acceptance.validate_final(store,h.caller,argvs,inputs);assert positive['accepted'],positive
    assert h.job_state()['final_passes']==passes+1 and s.ledger()==ledger_before
    if not revoke:return {'positive':True,'negative_refused':None,'invocations':None}
    invoke=acceptance._invoke;count=[0];last_stage_calls=[0];last=accepted['stages'][-1]['id']
    def revoke_after_last_validator(*args,**kwargs):
        result=invoke(*args,**kwargs);count[0]+=1
        if args[1]['id']==last:last_stage_calls[0]+=1
        if args[1]['id']==last and last_stage_calls[0]==2:
            a.revoke(s,{'grant_id':grant['id'],'owner':owner,'reason':'Fixture revoke before final validator returns'})
        return result
    with patch.object(acceptance,'_invoke',side_effect=revoke_after_last_validator):
        negative=acceptance.validate_final(store,h.caller,argvs,inputs)
    assert last_stage_calls[0]==2 and not negative['accepted'],negative
    assert 'revoked' in negative['reason'] and h.job_state()['final_passes']==passes+2
    assert s.ledger()==ledger_before and h.job_state()['policy']['max_repair_cycles']==22
    return {'positive':True,'negative_refused':not negative['accepted'],'invocations':count[0]}


def legacy_recovery(config):
    from tests.focus_group_install_fixtures import RecoveryHost,save_recovery_host,recovery_role_contract
    from tests.test_focus_group_plan import provider,target
    base=Path(config['base'])/'recovery-case';base.mkdir()
    h=RecoveryHost(base,Path(config['package']));h.shared_cap=22
    caps=json.loads(h.caps.read_text())
    caps['runtimeMode']='full-access'
    caps['providers'].append(provider('opencode',['deepseek-fixture-flash'],options=[
        {'id':'variant','type':'select','options':[{'id':'high'}]}]))
    caps['providers'][-1]['runtimeModes']=['full-access']
    draft=h.draft();limits=dict(draft['limits'],max_attempts_per_slot=5,participant_repairs=22)
    targets=[target('claudeAgent','claude-fixture-swift'),target('opencode','deepseek-fixture-flash',variant='high'),
             target('codex','gpt-fixture-one')]
    targets[1]['runtimeMode']='full-access'
    sharing=copy.deepcopy(draft['sharing'])
    sharing.append({'providerInstanceId':'opencode','consumers':['participant','analysis','review'],
                    'material_classes':['stimulus','persona','participant-response','journey-evidence','analysis-report']})
    # Choose reuse before the first plan/job. No producing choice or receipt is
    # rewritten: the old and upgraded fixtures start with these exact roles.
    role_choices={'analysis':copy.deepcopy(targets[2]),'review':copy.deepcopy(targets[1])}
    used={(t['providerInstanceId'],t['model']) for t in targets}
    for p in caps['providers']:
        p['models']=[m for m in p['models'] if (p['providerInstanceId'],m['id']) in used]
    caps['providers']=[p for p in caps['providers'] if p['models']]
    h.caps=h.write('recovery-catalog.json',caps);h.reuse_panel_roles=True
    h.start(personas=4,participant_models=targets,sharing=sharing,limits=limits,**role_choices)
    assert len(h.view['cells'])==12 and h.job_state()['policy']['max_repair_cycles']==22
    h.original_draft=h.draft(participant_models=targets,sharing=sharing,limits=limits,**role_choices)
    def rejected(n,stage='first-impression',request=None):
        run=h.begin(n,stage=stage,request=request);assert h.trace(run)[0]==0
        def invalid(result):result['artifacts'][0]['size']=result['artifacts'][0].pop('bytes')
        _,out=h.finish(run,invalid);assert out[0]!=0,out
        return run
    # Four genuinely accepted DSF first impressions, no manufactured record/ledger.
    for n in (1,4,7,10):
        run=h.begin(n);assert h.trace(run)[0]==0
        run['payload']=h.fi_payload(n,'Invented solitary impression '+str(n)+' with distinct fixture wording.')
        assert h.finish(run)[1][0]==0
    for n in (0,2):
        request=None
        for attempt in range(4):
            run=rejected(n,request=request)
            if attempt<3:
                h.job_ok('retry',{'caller':h.caller,'task_id':run['task'],'reason':'Invented rejected transport repair'})
                request=next(t['request_id'] for t in h.job_state()['tasks'] if t['task_id']==run['task'])
    h.journey_documents={'jr-02':h.journey_ready(1)};request=None
    for attempt in range(4):
        run=rejected(1,'journey',request)
        if attempt<3:
            h.job_ok('retry',{'caller':h.caller,'task_id':run['task'],'reason':'Invented rejected journey repair'})
            request=next(t['request_id'] for t in h.job_state()['tasks'] if t['task_id']==run['task'])
    import study as fg
    s=fg.Study(h.root,h.view['study_id']);assert len(s.accepted())==4
    ledger=s.ledger();assert sum(ledger['charged'].values())==16,ledger['charged']
    h.before_ledger=ledger;h.old_revision=h.view['revision'];h.old_plan=s.plan(h.old_revision)['plan']
    h.original_records=s.accepted();h.original_selection=h.job_state()['model_selection']
    h.original_role_contract=recovery_role_contract(h.old_plan,h.original_selection)
    assert all(h.original_draft[k]==h.old_plan[k] for k in ('participant_models','analysis','review'))
    assert h.original_draft['sharing']==sharing
    assert len(h.original_selection['profiles']['models'])==3
    assert sum(len(p['models']) for p in h.original_selection['capabilities']['providers'])==3
    h.retained={str(p.relative_to(s.job_dir)):fg.digest(p.read_bytes()) for folder in
                ('briefs','results','focus-group/sessions','focus-group/evidence','focus-group/accepted','focus-group/approvals')
                for p in (s.job_dir/folder).rglob('*') if p.is_file()}
    h.old_stages=copy.deepcopy(h.job_state()['stages']);h.old_tasks=copy.deepcopy(h.job_state()['tasks'])
    save_recovery_host(h,Path(config['base'])/'host.json')
    return {'cells':12,'accepted_records':4,'retained_charges':16,'shared_cap':22,
            'rejected_transports':12,'old_package':config['package'],
            'role_contract':h.original_role_contract,'selected_profiles':3,'catalog_entries':3}


def migrated_recovery(config):
    import study as fg
    import authority as a
    import lifecycle as lc
    from core.jobs.store import Store,JobError,digest,canonical
    from core.jobs import revise_plan
    from shared import model_selection as models
    from tests.focus_group_install_fixtures import load_recovery_host,fixture_phase,recovery_role_contract
    fixture_phase(config,'migrated-start')
    from tests.test_focus_group_install_authority import owner_grant,enable
    h=load_recovery_host(Path(config['base'])/'host.json',config['package'])
    s=fg.Study(h.root,h.view['study_id'])
    # Public owner-bound upgrade from a synthetic older identity, while unmarked.
    pin=h.job_state()['pins']['focus-group'];old_digest=pin['package_digest']
    source=h.base/'fixture-upgrade-owner.txt';source.write_text('Approve this exact synthetic package upgrade.\n')
    code,out=h.job('decision',{'caller':h.caller,'decision':{'id':'fixture-upgrade','scope':'plan:fixture-upgrade',
        'quote':source.read_text().strip(),'source':str(source),'source_sha256':digest(source.read_bytes())}},
        package=Path(config['old_package']))
    assert code==0,out
    before=(s.job_dir/'job.json').read_bytes();manifest=json.loads((Path(config['package'])/'install-manifest.json').read_text())
    upgrade=h.job_ok('upgrade-package',{'caller':h.caller,'revision':{'id':'fixture-upgrade',
        'owner_decision_id':'fixture-upgrade','reason':'Reviewed invented upgrade before delegated enablement'},
        'dependency_key':'focus-group','expected_state_sha256':digest(before),'expected_package_digest':manifest['package_digest']})
    assert Path(upgrade['previous_state']['path']).read_bytes()==before
    assert h.job_state()['pins']['focus-group']['package_digest']!=old_digest
    assert h.job_state()['pins']['focus-group']['installation_id']==manifest['installation_id']
    assert s.ledger()==h.before_ledger and s.accepted()==h.original_records
    fixture_phase(config,'upgrade-done')
    draft=copy.deepcopy(h.original_draft);draft['mode']='capture-only';draft['limits']['max_attempts_per_slot']=5
    h.view=h.plan(draft)
    new_plan=s.plan(h.view['revision'])['plan']
    current_roles=recovery_role_contract(new_plan,h.plan_admission['selection'])
    assert current_roles==h.original_role_contract
    assert all(draft[k]==h.original_draft[k] for k in ('participant_models','analysis','review','sharing'))
    for cell in fg.cells(h.old_plan):assert fg.bindings(h.old_plan,cell,'first-impression')==fg.bindings(new_plan,cell,'first-impression')
    mapping=h.ok('carry','--state-root',h.root,'--study',s.id,'--write')
    carried=[e for e in mapping['entries'] if e['status']=='carried']
    assert len(carried)==4 and {e['record_sha256'] for e in carried}=={r['record_sha256'] for r in h.original_records}
    fixture_phase(config,'carry-done')
    # Full explicit route: retire only settled carried/superseded slots. Do not
    # call owner_inputs on historical unbound tasks or the cap-clobber helper.
    job=h.job_state();req,stages=fg.job_contract(new_plan,h.view['revision'])
    record=s.read(f'planning/{h.view["revision"]}/run.json');selected=copy.deepcopy(record['selection'])
    # Retain the already approved shared cap22 in the current run agreement.
    from shared import execution_agreement as agreements,adopter_planning as adopter
    selected['agreement']['limits']['max_repair_cycles']=22
    selected['agreement']=agreements.freeze(selected['agreement'],selected);selected=models.freeze(selected)
    record=adopter.admit('focus-group',{'operation':'run','request_reference':record['request_reference'],
        'output_name':record['output_name'],'invocation_id':selected['invocation_id'],
        'selection':selected,'selection_sha256':selected['selection_sha256']})
    # This is the synthetic new run admission before its first execution, not a
    # runtime job or charge rewrite. The domain plan receipt remains its own.
    with s.locked():s.write(f'planning/{h.view["revision"]}/run.json',record)
    s,owner,grant=owner_grant(h)
    fixture_phase(config,'grant-done')
    tasks=[];documents={};carried_cells={e['cell_id'] for e in carried}
    authored=a.candidate_scope(job);old_tasks={t['task_id']:t for t in authored['tasks']}
    for n,cell in enumerate(fg.cells(new_plan)):
        if cell['cell_id'] in carried_cells:continue
        task=f'fi-{n+1:02d}';doc=h.document(n,'first-impression',task);documents[task]=doc
        candidate=copy.deepcopy(old_tasks[task]);candidate.update(document=doc,
            context_files=fg.evidence_module().material_context_files(new_plan,cell['target']))
        tasks.append(candidate)
    tasks += [copy.deepcopy(old_tasks[t]) for t in ('analysis','review')]
    old_stages={stage['id']:stage for stage in job['stages']}
    for stage in stages:
        old=old_stages[stage['id']]
        stage.update({k:copy.deepcopy(v) for k,v in old.items() if k not in
            ('id','depends_on','requirements','criteria','revision','validator_contract')})
        stage.setdefault('resources',{}).update(focus_group_plan=fg.planning_module().descriptor(s,h.view['revision']),focus_group_admission=record)
    # The explicitly approved capture-only scope removes the journey obligation;
    # its old stage/requirement and rejected transports remain in superseded
    # history. It must never claim the original combined study completed.
    new={**authored,'requirements':req,'stages':stages,'tasks':tasks,
         'policy':dict(job['policy'],max_repair_cycles=22),'authorization':dict(job['authorization'],study_revision=h.view['revision'],sharing=new_plan['sharing']),
         'model_selection':selected,'model_selection_sha256':selected['selection_sha256'],
         'invocation_id':record['invocation_id'],'scope_id':record['scope_id']}
    new['model_selection_history']=copy.deepcopy(job.get('model_selection_history') or {})
    new['model_selection_history'][job['model_selection_sha256']]=job['model_selection']
    inputs=a.revision_inputs(s,job,h.view['revision'],'capture-recovery',new)
    fixture_phase(config,'revision-inputs-done')
    h.job_ok('decision',inputs['decision_input'])
    from shared.job_coordinator import pinned_store
    before=(s.job_dir/'job.json').read_bytes()
    try:revise_plan(pinned_store(h.root,s.id),**inputs['plan_revision_input'])
    except JobError as e:assert 'required transaction guard missing' in str(e)
    else:raise AssertionError('Full enabling revision without a hook must refuse')
    assert (s.job_dir/'job.json').read_bytes()==before
    h.job_ok('plan-revision',inputs['plan_revision_input']);h.documents.update(documents)
    fixture_phase(config,'revision-applied')
    assert h.job_state()['policy']['max_repair_cycles']==22
    assert s.ledger()==h.before_ledger and s.accepted()==h.original_records
    for name,sha in h.retained.items():assert fg.digest((s.job_dir/name).read_bytes())==sha,name
    history=h.job_state()['history'];assert any(r.get('tasks') for r in history)
    assert h.original_selection['selection_sha256'] in h.job_state()['model_selection_history']
    code,out=h.admit_slot(1,'first-impression','duplicate-carried-r0');assert code!=0,out
    assert sum(s.ledger()['charged'].values())==16
    # A distinct future source build executes the unchanged guarded core. Even
    # with genuine scoped owner evidence, unguarded package upgrade is refused
    # before dependency adoption, backup or registry writes.
    future=Path(config['future_package']);future_meta=json.loads((future/'install-manifest.json').read_text())
    source=h.base/'fixture-refused-upgrade.txt';source.write_text('Approve this invented future package upgrade.\n')
    h.job_ok('decision',{'caller':h.caller,'decision':{'id':'refused-upgrade','scope':'plan:refused-upgrade',
        'quote':source.read_text().strip(),'source':str(source),'source_sha256':digest(source.read_bytes())}})
    before=(s.job_dir/'job.json').read_bytes();pins=copy.deepcopy(h.job_state()['pins'])
    migration_before={p.name:p.read_bytes() for p in (s.job_dir/'migrations').glob('*')}
    registry=Path(config['agents']);registry_before={str(p):p.read_bytes() for p in registry.rglob('*') if p.is_file() and not p.is_symlink()}
    code,out=h.job('upgrade-package',{'caller':h.caller,'revision':{'id':'refused-upgrade','owner_decision_id':'refused-upgrade','reason':'negative'},
        'dependency_key':'focus-group','expected_state_sha256':digest(before),'expected_package_digest':future_meta['package_digest']},package=future)
    assert code!=0 and 'required transaction guard missing' in str(out),out
    assert (s.job_dir/'job.json').read_bytes()==before and h.job_state()['pins']==pins
    assert {p.name:p.read_bytes() for p in (s.job_dir/'migrations').glob('*')}==migration_before
    assert {str(p):p.read_bytes() for p in registry.rglob('*') if p.is_file() and not p.is_symlink()}==registry_before
    assert s.ledger()==h.before_ledger
    fixture_phase(config,'upgrade-negative-done')
    # Retirement of an actual owned running slot is refused, not hidden by an
    # adapter exemption. Finish that same execution afterward; no extra launch.
    row=next(t for t in h.job_state()['tasks'] if t['task_id']=='fi-01')
    h.job_ok('retry',{'caller':h.caller,'task_id':'fi-01','reason':'Current-input repair retains four prior failed attempts'})
    row=next(t for t in h.job_state()['tasks'] if t['task_id']=='fi-01')
    running=h.begin(0,request=row['request_id']);assert h.trace(running)[0]==0
    current=h.job_state();bad=a.candidate_scope(current)
    bad['tasks']=[t for t in bad['tasks'] if t['task_id']!='fi-01']
    bad['model_selection_history']=copy.deepcopy(current.get('model_selection_history') or {})
    bad['model_selection_history'][current['model_selection_sha256']]=current['model_selection']
    negative_inputs=a.revision_inputs(s,current,h.view['revision'],'forbidden-live-retirement',bad)
    h.job_ok('decision',negative_inputs['decision_input']);before=(s.job_dir/'job.json').read_bytes()
    code,out=h.job('plan-revision',negative_inputs['plan_revision_input'])
    assert code!=0 and (s.job_dir/'job.json').read_bytes()==before,out
    running['payload']=h.fi_payload(0,'Invented fresh capture impression zero with separate fixture wording.')
    assert h.finish(running)[1][0]==0
    fixture_phase(config,'live-retirement-negative-and-first-cell-done')
    # Execute every missing cell once, using charged retry for old performed
    # slots. Carried DSF records receive no request or execution.
    for n,cell in enumerate(fg.cells(new_plan)):
        if cell['cell_id'] in carried_cells or n==0:continue
        task=f'fi-{n+1:02d}';row=next(t for t in h.job_state()['tasks'] if t['task_id']==task)
        if row.get('attempt'):
            h.job_ok('retry',{'caller':h.caller,'task_id':task,'reason':'Current capture-only revalidation retains spent attempts'})
            row=next(t for t in h.job_state()['tasks'] if t['task_id']==task)
        run=h.begin(n,request=row['request_id']);assert h.trace(run)[0]==0
        run['payload']=h.fi_payload(n,'Invented fresh capture impression '+str(n)+' with separate fixture wording.')
        assert h.finish(run)[1][0]==0
        fixture_phase(config,'missing-cell-'+str(n)+'-done')
    assert len(s.accepted())==12 and sum(s.ledger()['charged'].values())==24
    assert {r['record_sha256'] for r in s.accepted() if r['revision']==h.old_revision}=={r['record_sha256'] for r in h.original_records}
    for name,sha in h.retained.items():assert fg.digest((s.job_dir/name).read_bytes())==sha,name
    final=report_and_final(h,s,owner,grant,revoke=False)
    fixture_phase(config,'migrated-final-done')
    return {'cells':12,'carried_exactly':4,'retained_charges':16,'shared_cap':22,'upgrade_before_enablement':True,
        'upgrade_after_enablement_refused_before_side_effects':True,'old_bytes_retained':len(h.retained),
        'full_owner_bound_revision':True,'retired_settled_tasks':5,'final_accepted_capture_only_fixture':True,
        'final_charge_total':sum(s.ledger()['charged'].values()),'missing_final_guard_refused':True,
        'positive_final_pinned_validators':True,'revoke_control_in_authority_module':True,'final_pass_increment_each_call':1,
        'owned_live_retirement_refused':True,'final_validator_invocations':final['invocations'],
        'combined_scope_complete':False,'role_contract':current_roles,
        'old_new_role_options_sharing_parent_equal':True,'selected_profiles':3,'catalog_entries':3,
        'synthetic_older_identity_upgrade':config['synthetic_older_identity'],
        'retained_finance_pin_cross_code_compatibility':False}


class InstalledRecoveryTests(unittest.TestCase):
    def test_synthetic_older_identity_upgrade_and_exact_capture_carry_without_refund(self):
        with tempfile.TemporaryDirectory() as directory:
            inst=RecoveryInstallation(Path(directory)/'recovery')
            initial=inst.run(__name__,'legacy_recovery',inst.old)
            self.assertEqual(initial['scenario']['retained_charges'],16)
            actual=inst.run(__name__,'migrated_recovery')
            self.assertEqual(actual['scenario']['carried_exactly'],4)


if __name__=='__main__':unittest.main()
