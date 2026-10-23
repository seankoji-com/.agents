"""Invented capture packs for the focus-group tests: small real PNGs, page text and manifests.

Everything here is invented. Packs are written into a test's temporary directory and validated
through `plugins/focus-group/scripts/evidence.py pack`, the same entry point the coordinator uses.
"""
import hashlib
import json
import struct
import zlib
from pathlib import Path

PROFILE = {'label': 'phone', 'viewport': {'width': 390, 'height': 844}, 'extra_views': ['recipe detail', 'shopping list']}
CAPTURED_AT = '2029-05-31T23:00:00Z'
PAGE_TEXT = ('Pantry Planner (invented prototype)\nPlan three dinners in a few taps.\n'
             'Browse recipes, add them to a plan and open the shopping list.\n')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)


def with_chunk(data, kind, body):
    """`data` (a PNG from `png`) with one more chunk straight after IHDR."""
    return data[:33] + chunk(kind, body) + data[33:]


def png(width, height, bands=((240, 240, 236), (32, 96, 64)), text_chunks=()):
    """An RGB PNG with horizontal colour bands (one band means a blank image). Rows use filter 0."""
    band = max(1, height // len(bands))
    rows = b''.join(b'\0' + bytes(bands[min(y // band, len(bands) - 1)]) * width for y in range(height))
    out = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    for key, value in text_chunks:
        out += chunk(b'tEXt', key.encode() + b'\0' + value.encode())
    return out + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b'')


def inspection(names, **flags):
    row = {'viewed': True, 'blank': False, 'error_page': False, 'secrets_visible': False, 'personal_data_visible': False}
    return {'inspector': 'coordinator', 'inspected_at': '2029-05-31T23:10:00Z',
            'files': {name: dict(row, **flags.get(name, {})) for name in names}}


def write_pack(folder: Path, prefix='', text=PAGE_TEXT, initial=None, profile=PROFILE):
    """Write an initial viewport, two extra views and page text; return manifest file rows."""
    folder.mkdir(parents=True, exist_ok=True)
    vw, vh = profile['viewport']['width'], profile['viewport']['height']
    files = [(f'{prefix}initial-viewport.png', 'initial-viewport', None, initial or png(vw, vh), 'image/png'),
             (f'{prefix}recipe-detail.png', 'view', 'recipe detail', png(vw, vh, ((250, 250, 250), (180, 40, 40))),
              'image/png'),
             (f'{prefix}shopping-list.png', 'view', 'shopping list', png(vw, vh, ((20, 20, 20), (200, 200, 90))),
              'image/png'),
             (f'{prefix}welcome.txt', 'text', None, text.encode(), 'text/plain')]
    rows = []
    for name, role, view, data, media in files:
        path = folder / name
        path.write_bytes(data)
        rows.append({'name': name, 'role': role, 'view': view, 'path': str(path), 'sha256': sha(data),
                     'bytes': len(data), 'media_type': media})
    return rows


def manifest(files, url='https://staging.pantry-planner.example/welcome', **changes):
    """A capture manifest from a verified fresh anonymous host context."""
    value = {
        'schema_version': 1, 'kind': 'capture', 'attempt': {'number': 1, 'previous_manifest_sha256': None},
        'context': {'class': 'fresh-anonymous', 'reference': 'fixture-host-capture-context-1',
                    'freshness': {'verified': True, 'method': 'fixture: new host context with empty storage',
                                  'observed_at': '2029-05-31T22:59:00Z'},
                    'pre_existing_state': {'cookies': [], 'storage': [], 'onboarding': 'none'}, 'user_state': 'new',
                    'approval': None},
        'request': {'requested_url': url, 'final_url': url, 'http_status': 200}, 'supplied': None,
        'captured_at': CAPTURED_AT, 'profile': json.loads(json.dumps(PROFILE)),
        'readiness': {'state': 'ready', 'signal': 'fixture: main heading visible', 'observed_at': CAPTURED_AT},
        'files': files, 'limits': {'max_files': 8, 'max_file_bytes': 4 * 1024 * 1024},
        'device_access_not_exercised': ['screen reader', 'switch access', 'slow network'],
        'inspection': inspection([f['name'] for f in files]), 'derived_from': None}
    value.update(changes)
    return value

# Real planning acceptance for the original domain fixtures. Only the host result
# is synthetic. No validator, receipt or independence check is mocked.
_POLICY_INSTALL = {}


def policy_install(helper):
    import atexit
    import tempfile
    from tests.test_rebuild_installed import Sandbox
    package = helper.parent.parent
    if (package / 'install-manifest.json').exists():
        meta = json.loads((package / 'install-manifest.json').read_text())
        return package, meta, package.parents[1], Path(meta['agents_root'])
    if not _POLICY_INSTALL:
        tmp = tempfile.TemporaryDirectory()
        atexit.register(tmp.cleanup)
        box = Sandbox(Path(tmp.name))
        installed, meta = box.install('focus-group')
        _POLICY_INSTALL.update(tmp=tmp, box=box, package=installed, meta=meta)
    box = _POLICY_INSTALL['box']
    return _POLICY_INSTALL['package'], _POLICY_INSTALL['meta'], box.prefix, box.agents


def policy_selection(ws, draft, caps=None, operation='plan'):
    from copy import deepcopy
    from shared import model_selection as models, adopter_planning as adopter, planning_review as planning
    from shared.lineage import lineage
    from tests.model_selection_fixtures import answer
    catalog = deepcopy(caps or json.loads(ws.caps.read_text()))
    catalog['runtimeMode'] = 'auto'
    for provider in catalog['providers']:
        provider['canRunCrossProviderChildTask'] = True
        if provider['providerInstanceId'] == 'fixture-c':provider['driverKind'] = 'antigravity'
        if provider['providerInstanceId'] == 'fixture-b':provider['driverKind'] = 'claudeAgent'
        for model in provider['models']:
            for option in model.get('options', []):
                if option.get('type') == 'select' and not (isinstance(option.get('options'), list) and
                        all(isinstance(v, dict) and isinstance(v.get('id'), str) for v in option['options'])):
                    option['options'] = []
    def target(value):
        if not value or any(value.get('providerInstanceId') == p['providerInstanceId'] and
            (not p.get('canRunChildTask') or not any(m['id'] == value.get('model') for m in p['models']))
            for p in catalog['providers']) or not any(p['providerInstanceId'] == value.get('providerInstanceId') for p in catalog['providers']):
            value = {'providerInstanceId':'fixture-a','model':'alpha-swift','options':{}}
        value = deepcopy(value)
        # Invalid draft options are exercised by the domain catalog check, before role matching.
        try:
            models.validate_target(value, catalog)
        except ValueError:
            value['options'] = {}
        return value
    catalog['providers'].append({'providerInstanceId':'fixture-coordinator','driverKind':'codex',
        'canRunChildTask':True,'canRunCrossProviderChildTask':True,'models':[{'id':'gpt-fixture','options':[]}]})
    planner = {'providerInstanceId':'fixture-coordinator','model':'gpt-fixture','options':{}}
    catalog.update(parentThreadId='fixture-actual-parent', inheritedProviderInstanceId=planner['providerInstanceId'],
                   inheritedModel=planner['model'])
    work = {'workhorse':planner, 'analysis':target(draft.get('analysis'))}
    work.update({f'participant-{n:02d}':target(t) for n,t in enumerate(draft['participant_models'],1)})
    reviewer = target(draft.get('review'))
    rows = {models.key(t):t for t in [*work.values(),reviewer]}
    profiles = {'roles':{role:{'minimum':2,'judgement':True} if role in ('workhorse','analysis') else {'minimum':1}
                         for role in work}, 'models':[]}
    profiles['roles']['reviewer'] = {'minimum':2,'judgement':True}
    for t in rows.values():
        provider = next(p for p in catalog['providers'] if p['providerInstanceId'] == t['providerInstanceId'])
        profiles['models'].append({'target':t, 'quality':2, 'judgement':True,
            'reason':'Invented bounded study fixture suitability.', 'fixed_effort_reason':'Invented fixed-effort study fixture.',
            'lineage':lineage(provider['driverKind'],t['model']), 'lineage_source':'fixture:catalog'})
    reference = 'fixture:focus-request:' + str(ws.base)
    output = draft['study_id'] + '/study-plan'
    family = lambda t: next(r['lineage'] for r in profiles['models'] if models.key(r['target']) == models.key(t))
    # Deliberately invalid domain tests retain their supplied model and are refused by choices().
    independent = family(reviewer) not in {family(t) for role,t in work.items() if not role.startswith('participant-')}
    data = {'project_id':'focus-fixture-'+sha(str(ws.base).encode())[:16], 'operation':'focus-group/'+operation,
        'invocation_id':'focus-'+draft['study_id']+'-'+operation, 'scope_id':planning.logical_output_id(reference,output),
        'source':answer('Use these exact invented per-cell, analyst and fidelity targets for this invocation.'),
        'routing_scope':'invocation-only',
        'coordinator':dict(planner,lineage=family(planner),observed_options={}), 'capabilities':catalog,
        'routing':None,'profiles':profiles,'work':work,
        'review_panel':[{'slot_id':'fidelity','role':'reviewer','coverage':['FG-PLAN','FG-AUTHORITY','FG-REVIEW'],
                         'required':True,'independent':independent,'target':reviewer}],
        'work_replacements':[],'review_replacements':[]}
    selected = models.freeze(data)
    return adopter.admit('focus-group',{'operation':operation,'request_reference':reference,'output_name':output,
        'invocation_id':data['invocation_id'],'selection':selected,'selection_sha256':selected['selection_sha256']})


def policy_review(ws, view, *, adverse=False, attach=True):
    """Use the same pinned separate planning lifecycle as public CLI, without spawning each deterministic step."""
    import os
    import subprocess
    from copy import deepcopy
    from unittest.mock import patch
    from shared import adopter_planning as adopter, planning_review as planning
    from shared.job_coordinator import pinned_store
    from tests.test_rebuild_installed import worker_result
    package, manifest, prefix, agents = policy_install(ws.helper)
    directory = ws.root / view['study_id'] / 'focus-group'
    descriptor_file = directory / 'planning' / view['revision'] / 'descriptor.json'
    desc = json.loads(descriptor_file.read_text())
    metadata = ws.inputs / ('planning-'+view['revision']+'.json')
    project = ws.base / 'policy-project'
    if not project.exists():
        project.mkdir()
        for argv in (['git','init','-q',str(project)],['git','-C',str(project),'-c','user.name=Fixture',
                '-c','user.email=fixture@example.invalid','commit','--allow-empty','-qm','fixture']):
            p = subprocess.run(argv, capture_output=True,text=True)
            assert p.returncode == 0,p.stderr
    request = ws.inputs / 'policy-request.txt'
    if not request.exists():request.write_text('Assess the invented study protocol, authority and independent review before panel work.')
    inputs = {'requests':[{'path':str(request),'reference':desc['admission']['request_reference'],
        'clauses':[{'start':0,'end':len(request.read_text()),'requirement':'FG-PLAN'}]}],
        'decisions':[],'requirements':desc['requirements'],'load_bearing_decisions':[],
        'repository_root':str(project),'evidence_paths':list(getattr(ws,'policy_evidence',[]))}
    with patch.dict(os.environ, ws.policy_env):
        # Use installed policy bytes for installed fixtures; the same source adapter for source fixtures.
        executing = ws.helper.parent.parent
        if not (executing / 'plugin.json').exists():raise AssertionError(executing)
        prepared = adopter.prepare(desc,inputs,str(metadata),executing)
        if json.loads(metadata.read_text()).get('reference'):
            return
        snap = prepared['snapshot']
        job_id = 'plan-'+view['revision'][:24]
        made = planning.create({'job_id':job_id,'installation_id':manifest['installation_id'],'plugin':'focus-group',
            'project_id':desc['admission']['selection']['project_id'],'owner':'fixture-owner',
            'invocation_id':desc['admission']['invocation_id'],'scope_id':desc['admission']['scope_id'],
            'selection':desc['admission']['selection'],'snapshot':snap},ws.root,prefix,agents)
        store=pinned_store(ws.root,job_id);caller=made['caller']
        planning.begin(store,caller)
        launched=planning.launch(store,caller,'fidelity',job_id+'-review')
        planning.host_event(store,caller,launched['task_id'],{'kind':'accepted','request_id':launched['request_id'],
            'host_task_id':'host-'+job_id,'child_thread_id':'child-'+job_id,'status':'completed',
            'work_state':'result_available','has_pending_child_runs':False,'status_identity':launched['target']})
        brief=json.loads(Path(launched['path']).read_text());result=json.loads(worker_result(brief))
        result['requirements']=[{'id':r,'status':'passed','evidence':'fixture:request-protocol-failure-recovery'} for r in desc['requirements']]
        result['planning_review']={'coverage':[{'id':r,'outcome':'supported','evidence':'fixture:request-protocol-failure-recovery'}
            for r in desc['requirements']],'inspected_paths':snap['declared_paths'],'responses':[]}
        result['review_verdict']='adverse' if adverse else 'approve'
        if adverse:result['findings']=[{'id':'FG-ADVERSE','severity':'major','scenario':'Protocol recovery omitted.',
            'source_evidence':'fixture:protocol','smallest_correction':'Define recovery.'}]
        planning.ingest(store,caller,launched['task_id'],json.dumps(result).encode(),'done-'+job_id)
        finished=planning.finish_round(store,caller)
        planning.release(store,caller)
        ws.planning_receipt=finished['reference'];ws.planning_metadata=metadata
        if attach:
            attached=adopter.attach(desc,metadata,finished['reference']['path'],executing)
            desc['planning_review']=attached['metadata']
            descriptor_file.write_text(json.dumps(desc))
    return finished


def policy_run(ws, draft):
    from unittest.mock import patch
    import os
    from shared import model_selection as models, adopter_planning as adopter
    from copy import deepcopy
    data = deepcopy(ws.plan_admission)
    selected = deepcopy(data['selection']);selected['operation']='focus-group/run'
    selected['invocation_id'] += '-run';selected=models.freeze(selected)
    record=adopter.admit('focus-group',{'operation':'run','request_reference':data['request_reference'],
        'output_name':data['output_name'],'invocation_id':selected['invocation_id'],
        'selection':selected,'selection_sha256':selected['selection_sha256']})
    directory=ws.root / draft['study_id'] / 'focus-group'
    revision=json.loads((directory/'current.json').read_text())['revision']
    path=directory/'planning'/revision/'run.json';path.write_text(json.dumps(record))
    return record
