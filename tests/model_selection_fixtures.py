"""Synthetic catalog/owner answers, never task-local provider IDs or settings."""
from shared import model_selection as models


def answer(text='Use the displayed work and review targets for this invocation.'):
    return {'reference': 'fixture:owner-answer', 'answer': text, 'sha256': models.digest(text)}


def selection_input():
    def provider(pid, mid, effort):
        return {'providerInstanceId': pid, 'driverKind': 'fixture', 'canRunChildTask': True,
                'canRunCrossProviderChildTask': True, 'runtimeModes': ['auto'],
                'models': [{'id': mid, 'name': 'Duplicate label', 'options': [
                    {'id': effort, 'type': 'select', 'currentValue': 'low',
                     'options': [{'id': v} for v in ('low', 'high')]}]}]}
    work = {'providerInstanceId': 'fixture-work', 'model': 'alpha-work', 'options': {'reasoningEffort': 'high'}}
    review = {'providerInstanceId': 'fixture-review', 'model': 'beta-review', 'options': {'effort': 'high'}}
    spare = {'providerInstanceId': 'fixture-spare', 'model': 'gamma-spare', 'options': {'effort': 'high'}}
    profiles = {'roles': {'workhorse': {'minimum': 1}, 'judgement': {'minimum': 2, 'judgement': True},
                          'reviewer': {'minimum': 2, 'judgement': True}},
                'models': [{'target': t, 'quality': 2, 'judgement': True,
                            'reason': 'Synthetic declared suitability for bounded fixture tasks.',
                            'lineage': family, 'lineage_source': 'fixture:catalog-family'}
                           for t, family in [(work, 'alpha'), (review, 'beta'), (spare, 'gamma')]]}
    return {'invocation_id': 'fixture-invocation', 'scope_id': 'fixture-output', 'operation': 'fixture/plan',
            'project_id': 'fixture-project', 'source': answer(), 'routing_scope': 'invocation-only',
            'coordinator': {**work, 'lineage': 'alpha', 'observed_options': {'reasoningEffort': 'high'}},
            'capabilities': {'inheritedProviderInstanceId': 'fixture-work', 'inheritedModel': 'alpha-work',
                             'runtimeMode': 'auto', 'providers': [
                                 provider('fixture-work', 'alpha-work', 'reasoningEffort'),
                                 provider('fixture-review', 'beta-review', 'effort'),
                                 provider('fixture-spare', 'gamma-spare', 'effort')]},
            'routing': None, 'profiles': profiles, 'work': {'workhorse': work},
            'review_panel': [{'slot_id': 'review', 'role': 'reviewer', 'coverage': ['REQ-ONE'],
                              'required': True, 'target': review}],
            'work_replacements': [], 'review_replacements': []}


def canonical_selection_input():
    """Synthetic model IDs with authoritative single-lineage driver metadata."""
    data = selection_input()
    data['capabilities']['providers'][0]['driverKind'] = 'codex'
    data['capabilities']['providers'][1]['driverKind'] = 'claudeAgent'
    data['coordinator']['lineage'] = 'openai'
    data['profiles']['models'][0]['lineage'] = 'openai'
    data['profiles']['models'][1]['lineage'] = 'anthropic'
    return data


def replacement(data, target, review=False):
    role = 'reviewer' if review else 'workhorse'
    authority = {'scope': 'invocation-only', 'invocation_id': data['invocation_id'],
                 'project_id': data['project_id'], 'source': answer('Permit this exact replacement, options and data boundary.'),
                 'recipients': [{'providerInstanceId': target['providerInstanceId'], 'model': target['model']}],
                 'data_classes': ['repository', 'topic'], 'limits': {'max_cost': 1,
                     'options': {k: [v] for k, v in target.get('options', {}).items()}}}
    result = {'role': role, 'target': target, 'authority': authority}
    if review:
        result['slot_id'] = 'review'
    return result


def attach_selection(job, coordinator=None):
    """Supply explicit synthetic choices to pre-selection integration fixtures.

    These tests exercise domain gates, including deliberately invalid lineage
    labels. Keep those labels on tasks so the specialised gate still refuses them;
    the chooser uses canonical catalog families and does not waive domain checks.
    New missing-choice tests intentionally do not call this fixture adapter.
    """
    if job.get('model_selection'):
        return job
    from copy import deepcopy
    from shared.lineage import lineage
    fallback = {'providerInstanceId': 'fixture-provider', 'model': 'fixture-worker', 'options': {}}
    if coordinator:
        fallback = {'providerInstanceId': coordinator['providerInstanceId'], 'model': coordinator['model'], 'options': {}}
    data = selection_input()
    data.update(invocation_id='fixture-' + job['job_id'], scope_id=job['job_id'],
                operation=job['workflow'], work={}, review_panel=[],
                profiles={'roles': {}, 'models': []}, routing=None)
    data['coordinator'] = {**fallback, 'lineage': lineage('fixture', fallback['model']), 'observed_options': None}
    catalog = {}
    def register(target, role):
        pid, mid = models.key(target)
        provider = catalog.setdefault(pid, {'providerInstanceId': pid, 'driverKind': 'fixture',
            'canRunChildTask': True, 'canRunCrossProviderChildTask': True,
            'runtimeModes': list(models.MODES), 'models': []})
        model = next((m for m in provider['models'] if m['id'] == mid), None)
        if model is None:
            model = {'id': mid, 'options': []}; provider['models'].append(model)
            data['profiles']['models'].append({'target': deepcopy(target), 'quality': 2,
                'judgement': True, 'reason': 'Synthetic domain-gate fixture choice, not a production recommendation.',
                'fixed_effort_reason': 'Synthetic fixed-effort execution for domain boundary fixtures.',
                'lineage': lineage('fixture', mid), 'lineage_source': 'fixture:catalog'})
        for k, v in target['options'].items():
            option = next((o for o in model['options'] if o['id'] == k), None)
            if option is None:
                option = {'id': k, 'type': 'boolean' if type(v) is bool else 'select', 'options': []}
                model['options'].append(option)
            if type(v) is str and {'id': v} not in option['options']: option['options'].append({'id': v})
        data['profiles']['roles'][role] = {'minimum': 0}
    for task in job['tasks']:
        if not task.get('target'):
            task['target'] = dict(deepcopy(fallback), lineage='fixture')
        task['target'].setdefault('options', {})  # Explicit synthetic host echo, including no overrides.
        target = {k: deepcopy(v) for k, v in task['target'].items()
                  if k in ('providerInstanceId', 'model', 'options', 'runtimeMode')}
        target.setdefault('options', {})
        role = 'fixture-' + task['task_id']
        register(target, role)
        if task.get('role') == 'review':
            data['review_panel'].append({'slot_id': task['task_id'], 'role': role,
                'coverage': task.get('requirements') or ['fixture-domain-gate'], 'required': True,
                'independent': False, 'target': target})
            task['selection_binding'] = {'role': role, 'slot_id': task['task_id']}
        else:
            data['work'][role] = target
            task['selection_binding'] = {'role': role}
    if not data['work']:
        register(fallback, 'workhorse'); data['work']['workhorse'] = deepcopy(fallback)
    for stage in job['stages']:
        if stage.get('execution_mode') == 'direct' and not any(t['stage_id'] == stage['id'] for t in job['tasks']):
            role = 'fixture-direct-' + stage['id']
            target = {**deepcopy(fallback), 'execution': 'current-context', 'accept_actual_settings': True}
            register(target, role); data['work'][role] = target
            stage['selection_binding'] = {'role': role}
    if not data['review_panel']:
        register(fallback, 'reviewer')
        data['review_panel'] = [{'slot_id': 'unused', 'role': 'reviewer', 'coverage': ['unused preference'],
                                 'required': False, 'independent': False, 'target': deepcopy(fallback)}]
    adopter = job['workflow'].partition('/')[0] in ('agent-tuneup','babysitter') or job['workflow'] in ('elephant-goldfish/elephant','elephant-goldfish/check')
    if adopter:
        from shared.planning_review import logical_output_id
        data['scope_id'] = logical_output_id('fixture:request:' + job['job_id'], job['job_id'] + '/output')
        if 'workhorse' not in data['work']:
            chosen = deepcopy(next(iter(data['work'].values())))
            register(chosen,'workhorse'); data['work']['workhorse'] = chosen
        if job['workflow'].startswith('agent-tuneup/'):
            data['sharing'] = [{'target':deepcopy(fallback),'data_classes':['private-settings'],
                'source':answer('Permit this synthetic private-settings review inside the isolated fixture.')} ]
        if job['workflow'] == 'elephant-goldfish/elephant':
            factual = {'providerInstanceId':'fixture-factual', 'model':'gpt-fixture', 'options':{}}
            register(factual, 'fixture-factual')
            data['work']['fixture-factual'] = factual
        if job['workflow'] in ('agent-tuneup/align','agent-tuneup/audit','elephant-goldfish/elephant'):
            chosen = deepcopy(fallback)
            register(chosen,'reviewer')
            data['profiles']['roles']['reviewer'] = {'minimum':2,'judgement':True}
            data['review_panel'].append({'slot_id':'planning','role':'reviewer','coverage':list(job['requirements']),
                'required':True,'independent':False,'target':chosen})
    data['capabilities'] = {'providers': list(catalog.values()), 'runtimeMode': 'full-access',
                            'inheritedProviderInstanceId': 'fixture-provider'}
    data['source'] = answer('Explicit synthetic targets for domain fixture: ' + models.digest(data['work']))
    from tests.upfront_fixtures import approved_selection
    selected = approved_selection(data)
    job.update(model_selection=selected, model_selection_sha256=selected['selection_sha256'],
               invocation_id=selected['invocation_id'], scope_id=selected['scope_id'])
    for task in job['tasks']:
        task['selection_binding']['selection_sha256'] = selected['selection_sha256']
    for stage in job['stages']:
        if stage.get('selection_binding'):
            stage['selection_binding']['selection_sha256'] = selected['selection_sha256']
    if adopter:
        from shared.adopter_planning import admit
        job['adopter_admission'] = admit(job['workflow'].partition('/')[0], {
            'operation':job['workflow'],'request_reference':'fixture:request:' + job['job_id'],
            'output_name':job['job_id']+'/output','invocation_id':selected['invocation_id'],
            'selection':selected,'selection_sha256':selected['selection_sha256']})
    return job


def attach_revision(payload, current):
    """An explicit fixture answer for newly proposed targets, never an auto fallback."""
    from copy import deepcopy
    proposed = payload['new_plan']
    # Only test a new answer when targets/bindings actually change. An unchanged
    # source rebind continues under the original producing record.
    tasks = proposed.get('tasks', current['tasks'])
    old = {t['task_id']: t for t in current['tasks']}
    if not any(t['task_id'] not in old or t.get('target') != old[t['task_id']].get('target') or
               not t.get('selection_binding') for t in tasks):
        return
    candidate = deepcopy({**current, **proposed})
    candidate.pop('model_selection', None)
    attach_selection(candidate, current.get('model_selection', {}).get('coordinator'))
    chosen = candidate['model_selection']
    chosen.update(scope_id=current['scope_id'], invocation_id=current['invocation_id'])
    from tests.upfront_fixtures import approved_selection
    chosen = approved_selection(chosen)
    candidate.update(model_selection=chosen, model_selection_sha256=chosen['selection_sha256'])
    for task in candidate['tasks']:
        task['selection_binding']['selection_sha256'] = chosen['selection_sha256']
    for stage in candidate['stages']:
        if stage.get('selection_binding'):
            stage['selection_binding']['selection_sha256'] = chosen['selection_sha256']
    for name in ('model_selection', 'model_selection_sha256', 'tasks', 'stages'):
        proposed[name] = candidate[name]
