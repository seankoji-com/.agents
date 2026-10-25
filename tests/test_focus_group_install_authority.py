"""Relocated procedural context and the real existing-direct-job enable boundary.

Every scenario child imports the installed artifact, with an independent checkout
read audit. All owner messages, host responses and targets are invented fixtures.
"""
import copy,json,tempfile,unittest
from pathlib import Path
from tests.focus_group_install_fixtures import RecoveryInstallation,module_deadline

def setUpModule():module_deadline()


def owner_grant(h):
    import authority as a
    s=a.fg.Study(h.root,h.view['study_id']);plan=s.plan(h.view['revision'])['plan']
    source=h.base/'invented-owner-context.txt'
    source.write_text('Question: permit this bounded synthetic recovery?\nOwner: permit the fixture delegate within the stated limits.\n')
    native=h.base/'invented-native-observation.json'
    native.write_text(json.dumps({'messageId':'fixture-native-owner','creationSource':'server','createdBy':'user',
                                  'text':source.read_text()}))
    owner={'id':'fixture-owner','message_ref':'fixture:native-owner','source':a.descriptor(source),
           'context':source.read_text(),'quote':'permit the fixture delegate within the stated limits.',
           'native_observation':a.descriptor(native),
           'native_messages':[{'messageId':'fixture-native-owner','creationSource':'server'}]}
    pin=h.job_state()['pins']['focus-group']
    data={'id':'fixture-recovery-grant','owner':owner,'delegate':{'id':'fixture-delegate','caller':h.caller},
          'constraints':{'product_writes':False,'modes':['combined','capture-only'],'max_tasks':53,
              'max_concurrency':4,'max_attempts_per_slot':5,'max_repair_cycles':22,
              'deadline':'2030-01-01T00:00:00Z'},'expires_at':'2029-12-31T23:00:00Z',
          'review':plan['review'],'package':{'dependency_key':'focus-group',
              **{k:pin[k] for k in ('installation_id','package_digest','bundle_digest')}}}
    grant=a.grant(s,data);approval=a.approve_delegated(s,{'revision':h.view['revision'],
        'grant_id':grant['id'],'delegate':grant['delegate']})
    assert approval['derived'] and approval['statement'] not in owner['context']
    return s,owner,grant


def enable(h,s):
    import authority as a
    from core.jobs import revise_plan
    from core.jobs.store import Store,JobError
    from shared.job_coordinator import pinned_store
    job=h.job_state();new=a.candidate_scope(job)
    new['model_selection_history']=copy.deepcopy(job.get('model_selection_history') or {})
    new['model_selection_history'][job['model_selection_sha256']]=job['model_selection']
    # Public CLI normalization is deterministic. Freeze the complete candidate,
    # including producing history, rather than certifying a partial patch that
    # the adapter must expand after its digest was computed.
    inp=a.revision_inputs(s,job,h.view['revision'],'installed-enable',new)
    h.job_ok('decision',inp['decision_input']);before=(s.job_dir/'job.json').read_bytes()
    try:revise_plan(pinned_store(h.root,s.id),**inp['plan_revision_input'])
    except JobError as e:assert 'required transaction guard missing' in str(e)
    else:raise AssertionError('Enabling a previously unmarked job without a hook must refuse')
    assert (s.job_dir/'job.json').read_bytes()==before
    for defect in ('changed-candidate','stripped-marker'):
        bad=copy.deepcopy(inp['plan_revision_input'])
        if defect=='changed-candidate':bad['new_plan']['policy']['max_live_workers']=3
        else:
            bad['new_plan']['authorization'].pop('delegated_authority')
            bad['new_plan']['policy']['transaction_guard_required']=[]
        code,out=h.job('plan-revision',bad)
        assert code!=0 and (s.job_dir/'job.json').read_bytes()==before,(defect,out)
    h.job_ok('plan-revision',inp['plan_revision_input'])
    assert set(h.job_state()['policy']['transaction_guard_required'])==set(a.OPERATIONS)
    assert a.check_live(s,h.job_state(),h.caller)['derived']
    return inp


def installed_authority(config):
    from tests.focus_group_install_fixtures import RecoveryHost
    import authority as a
    import evidence as ev
    base=Path(config['base'])/'authority-case';base.mkdir()
    h=RecoveryHost(base,Path(config['package']));h.shared_cap=22
    target={'providerInstanceId':'claudeAgent','model':'claude-fixture-swift','options':{}}
    instruction=base/'fixture-procedure.md';instruction.write_text('Use plain words and check spelling.\n')
    source=base/'fixture-harness-requirement.md';source.write_text('This harness requires the exact writing instruction.\n')
    entry={'target':target,'harness':'claudeAgent','path':str(instruction),'sha256':a.digest(instruction.read_bytes()),
       'purpose':'Writing procedure','applicability':'Every answer from this harness',
       'mandatory_instruction':{'path':str(source),'sha256':a.digest(source.read_bytes()),'quote':'requires the exact writing instruction'},
       'sharing':{'providerInstanceId':'claudeAgent','consumer':'participant','material_class':'procedural-instruction'},
       'inspection':{'inspector':'fixture-coordinator','reviewed_at':'2026-10-24T00:00:00Z','verdict':'cleared',
           'sha256':a.digest(instruction.read_bytes()),'source_sha256':a.digest(source.read_bytes())}}
    h.policy_evidence=[str(instruction),str(source)];h.trace_harness='claudeAgent'
    h.start(personas=1,mode='capture-only',procedural_context=[entry])
    s,owner,grant=owner_grant(h);enable(h,s)
    plan=s.plan(h.view['revision'])['plan'];before=s.ledger();original=instruction.read_bytes()
    instruction.write_bytes(original+b'changed')
    code,out=h.admit_slot(0,'first-impression','invalid-procedural-r0')
    assert code!=0 and out['error']['code']=='procedural_context_changed',out
    assert s.ledger()==before
    instruction.write_bytes(original)
    run=h.begin(0);assert h.trace(run)[0]==0
    assert run['brief']['context_files']==ev.material_context_files(plan,target)
    assert str(source) not in run['brief']['authorization']['read']
    run['payload']=h.fi_payload(0,'Invented isolated authority impression with distinct wording.')
    assert h.finish(run)[1][0]==0
    other=h.begin(1);assert h.trace(other)[0]==0
    other['payload']=h.fi_payload(1,'Another invented authority impression with separate wording.')
    assert h.finish(other)[1][0]==0
    from tests.test_focus_group_install_recovery import report_and_final
    final=report_and_final(h,s,owner,grant)
    assert final['negative_refused']
    # A sibling read is a real contaminated trace; a later exact read cannot clear it.
    sibling=instruction.with_name('sibling.md');sibling.write_text('Unapproved sibling instruction.\n')
    assert h.trace(run,[{'tool':'read','path':str(sibling)}])[0]!=0
    assert h.trace(run)[0]!=0
    assert ev.trace_compliance(s,run['request'])[0]=='contaminated'
    original_view=h.view;limits=dict(plan['limits'],max_attempts_per_slot=5)
    h.view=h.plan(h.draft(mode='capture-only',personas=[plan['personas'][0]],limits=limits,procedural_context=[entry]))
    mapping=h.ok('carry','--state-root',h.root,'--study',s.id)
    contaminated=run['payload']['cell_id']
    assert all(e['status']!='carried' for e in mapping['entries'] if e['cell_id']==contaminated)
    assert any(e['status']=='carried' for e in mapping['entries'] if e['cell_id']!=contaminated)
    h.view=original_view
    assert h.trace(run)[0]!=0 and ev.trace_compliance(s,run['request'])[0]=='contaminated'
    old=copy.deepcopy(plan);old.pop('procedural_context')
    scope={'approved':{ev.real(f['path']) for f in ev.material_context_files(old)},
           'own':s.job_dir/'artifacts/tasks/old','tasks':s.job_dir/'artifacts/tasks'}
    assert ev.path_problem(0,str(instruction),scope)
    for path in (instruction.parent,source,sibling,instruction/'nested.md'):
        assert ev.path_problem(0,str(path),{'approved':{ev.real(instruction)},'own':scope['own'],'tasks':scope['tasks']})
    return {'existing_direct_then_guarded_enable':True,'missing_hook_enable_refused':True,
            'procedural_exact_read':True,'source_and_siblings_excluded':True,'invalid_input_zero_charge':True,
            'historical_scope_not_enlarged':True,'sticky_contamination':True,'charged':sum(s.ledger()['charged'].values()),
            'native_context_retained':grant['owner']['context']==owner['context'],
            'real_final_validators_then_revocation_refused':True,'final_validator_invocations':final['invocations']}


class InstalledAuthorityTests(unittest.TestCase):
    def test_relocated_exact_context_and_previously_unmarked_enable_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            install=RecoveryInstallation(Path(directory)/'authority')
            result=install.run(__name__,'installed_authority')
            self.assertTrue(result['scenario']['sticky_contamination'])
            self.assertTrue(result['scenario']['missing_hook_enable_refused'])


if __name__=='__main__':unittest.main()
