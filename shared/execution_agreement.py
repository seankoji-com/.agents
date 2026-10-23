"""Scoped invocation agreements. Pure admission, never a scheduler or permission UI.

Inputs are coordinator observations and quoted authority, not authenticated proof.
The selection/brief retains this digest separately from mutable workflow state.
"""
from copy import deepcopy
import json
from pathlib import Path

from shared.model_selection import SelectionError, digest, require, source

ENGINEERING = ('Open PR', 'Tagged Version', 'Verified in Prod')
THINKING = ('Issue with subissues', 'Discussion post', 'Markdown PR')
ENGINEERING_OPS = {'imps/run', 'imps/issues', 'imps/checklist', 'imps/discussion', 'ralph/run'}
THINKING_OPS = {'elephant-goldfish/thinking', 'elephant-goldfish/elephant'}
INSPECTIONS = {'request', 'instructions', 'authority', 'state'}
MODEL_FIELDS = ('work', 'review_panel', 'work_replacements', 'review_replacements', 'sharing')
# Installed helper compatibility only. Current public tuneup exposes one workflow;
# its internal stages and older explicit helper clients still require admission.
INTERNAL_OPS = {'agent-tuneup/audit': 'substantive', 'agent-tuneup/align': 'substantive',
                'agent-tuneup/apply': 'continuation'}


def inventory(root=None):
    rows = json.loads(Path(__file__).with_name('operation-matrix.json').read_text())['plugins']
    result = []
    for plugin, operations in rows.items():
        if root is not None:
            manifest = json.loads((Path(root) / 'plugins' / plugin / 'plugin.json').read_text())
            require(set(manifest['operations']) == set(operations), 'unclassified manifest operation: ' + plugin)
        for op, row in operations.items():
            result.append({'operation': plugin + '/' + op, 'classification': row['classification'],
                           'entry': 'plugins/' + plugin + '/entry.md',
                           'route': 'plugins/' + plugin + '/' + row['route'],
                           'completion_evidence': row['completion_evidence']})
    if root is not None:
        require({p.parent.name for p in (Path(root) / 'plugins').glob('*/plugin.json')} == set(rows),
                'unclassified plugin manifest')
    return result


def classify(operation):
    if operation in INTERNAL_OPS:
        return INTERNAL_OPS[operation]
    if operation == 'imps/investigation':
        return 'substantive'  # Internal read-only run mode, not another catalog operation.
    if operation.endswith('/planning-review') and operation.split('/')[0] in json.loads(
            Path(__file__).with_name('operation-matrix.json').read_text())['plugins']:
        return 'continuation'
    row = next((r for r in inventory() if r['operation'] == operation), None)
    require(row is not None, 'unknown public operation: ' + operation)
    return row['classification']


def model_contract(selection):
    return digest({name: selection.get(name, [] if name != 'work' else {}) for name in MODEL_FIELDS})


def inspect(data):
    """Combine already inspected facts and supplied choices; batch only missing decisions.

    The adapter names consequential required fields. Routine assumptions do not
    become questions, and no answer or authority is manufactured by this helper.
    """
    observations = data.get('inspected', {})
    require(isinstance(observations, dict) and INSPECTIONS <= set(observations) and
            all(isinstance(observations[k], str) and observations[k].strip() for k in INSPECTIONS),
            'inspect request/instructions/authority/state before asking')
    facts = deepcopy(data.get('context', {}))
    facts.update(deepcopy(data.get('supplied', {})))
    missing = [k for k in data.get('required', []) if facts.get(k) in (None, '', [])]
    questions = [{'field': k, 'recommendation': data.get('recommendations', {}).get(k)} for k in missing]
    return {'facts': facts, 'assumptions': deepcopy(data.get('assumptions', [])),
            'questions': questions, 'question_batches': int(bool(questions)),
            'choices': list(ENGINEERING if data.get('operation') in ENGINEERING_OPS else
                            THINKING if data.get('operation') in THINKING_OPS else ())}


def freeze(data, selection):
    record = deepcopy(data)
    record.pop('agreement_sha256', None)
    record['schema_version'] = 1
    for name in ('invocation_id', 'scope_id'):
        require(record.get(name) == selection.get(name) and bool(record.get(name)), 'agreement ' + name + ' differs')
    require(record.get('model_contract_sha256') == model_contract(selection), 'agreement model chains/options differ')
    operations = record.get('operations')
    require(isinstance(operations, list) and operations and len(set(operations)) == len(operations),
            'finite agreed operation scope required')
    for operation in operations:
        classify(operation)
    inspections = record.get('inspected', {})
    require(INSPECTIONS <= set(inspections) and all(isinstance(inspections[k], str) and inspections[k].strip()
            for k in INSPECTIONS), 'agreement requires completed context inspection')
    source(record.get('source'))
    scope = record.get('scope', {})
    require(all(isinstance(scope.get(k), str) and scope[k].strip() for k in ('repository', 'base')),
            'agreed repository and intended base required')
    require(isinstance(scope.get('paths'), list) and scope['paths'], 'bounded content/work scope required')
    target = record.get('target', {})
    require(isinstance(target.get('label'), str) and target['label'].strip(), 'observable completion target required')
    if set(operations) & ENGINEERING_OPS:
        require(target['label'] in ENGINEERING, 'choose Open PR, Tagged Version or Verified in Prod')
        require(target.get('no_change') is not True, 'resolve incompatible no-change engineering endpoint before execution')
    if set(operations) & THINKING_OPS:
        require(target['label'] in THINKING, 'choose Issue with subissues, Discussion post or Markdown PR')
    require(isinstance(record.get('destinations'), dict), 'applicable destinations must be recorded')
    checks = record.get('verification', {})
    require(isinstance(checks, dict) and isinstance(checks.get('local_checks'), list) and
            isinstance(checks.get('ci_checks'), list), 'named local and required CI checks required')
    if target['label'] in ENGINEERING + ('Markdown PR',):
        require(checks['local_checks'] and checks.get('review_required') is True,
                'engineering/Markdown endpoint requires local checks and review')
    if target['label'] in ENGINEERING[1:]:
        release = record['destinations'].get('release', {})
        require(all(release.get(k) for k in ('procedure', 'artifacts', 'distribution')),
                'repository release procedure, artifacts and distribution obligations required')
        for group in ('artifacts', 'distribution'):
            require(isinstance(release[group], list) and all(isinstance(item, str) and item or
                    isinstance(item, dict) and item.get('name') and item.get('status') in ('published', 'merged', 'available')
                    for item in release[group]), 'named repository release obligations required')
    if target['label'] == 'Verified in Prod':
        prod = record['destinations'].get('production', {})
        require(all(prod.get(k) for k in ('destination', 'procedure', 'checks', 'preparations')),
                'production destination, procedure, named checks and preparations required')
    if target['label'] == 'Discussion post':
        require(record['destinations'].get('category_id'), 'intended existing Discussion category required')
    limits = record.get('limits', {})
    require(type(limits.get('max_repair_cycles')) is int and limits['max_repair_cycles'] >= 0 and
            type(limits.get('max_launch_retries')) is int and 0 <= limits['max_launch_retries'] <= 2 and
            type(limits.get('max_cost')) in (int, float) and 0 <= limits['max_cost'] < float('inf'),
            'finite retry/cost limits required')
    for grant in record.get('authority', []):
        source(grant.get('source'))
        require(isinstance(grant.get('actions'), list) and grant['actions'], 'scoped action grant required')
    require(isinstance(record.get('external_gates', []), list), 'external approval gates must be listed')
    record['agreement_sha256'] = digest(record)
    return record


def validate(record, selection, expected=None):
    require(isinstance(record, dict), 'upfront agreement missing; legacy state retains its pinned contract, restart for new endpoints')
    require(record.get('agreement_sha256') == digest({k: v for k, v in record.items() if k != 'agreement_sha256'}) and
            (expected is None or record['agreement_sha256'] == expected), 'agreement tampered or producing binding differs')
    require(freeze(record, selection) == record, 'agreement is not canonical')
    return record


def admit(selection=None, *, operation=None, action='inspect', expected=None, boundary=None, external=()):
    if operation and classify(operation) == 'direct':
        require(action in ('inspect', 'deterministic'),
                'direct control cannot author, dispatch or publish; admit the substantive operation at that transition')
        return {'allowed': True, 'chooser': False, 'dispatch': False}
    require(isinstance(selection, dict), 'upfront agreement selection missing')
    from shared.model_selection import validate as validate_selection
    validate_selection(selection)
    record = validate(selection.get('agreement'), selection, expected)
    op = operation or selection['operation']
    classification = classify(op)
    if classification == 'direct':
        require(action in ('inspect', 'deterministic'),
                'direct control cannot author, dispatch or publish; admit the substantive operation at that transition')
        return {'allowed': True, 'chooser': False, 'dispatch': False}
    continuing = classification == 'continuation' and op.split('/')[0] == selection['operation'].split('/')[0] and \
                 selection['operation'] in record['operations']
    require(op in record['operations'] or continuing, 'new operation outside agreement; scoped decision required')
    if boundary:
        for name, value in boundary.items():
            agreed = record.get(name)
            require(agreed == value, 'new material boundary: ' + name + '; hold only dependent action')
    grants = {a for grant in record.get('authority', []) for a in grant['actions']}
    require(action in grants, 'missing scoped action authority: ' + action)
    required = [g for g in record.get('external_gates', []) if action in g.get('actions', [])]
    require(all(any(e.get('id') == g['id'] and e.get('status') == 'approved' and e.get('reference')
                    for e in external) for g in required), 'required external human approval missing')
    return {'allowed': True, 'chooser': False, 'agreement_sha256': record['agreement_sha256'],
            'target': deepcopy(record['target'])}


def inherit(selection, operation, action='inspect'):
    """Nested calls consume the same binding; they do not refreeze authority or budgets."""
    return admit(selection, operation=operation, action=action)
