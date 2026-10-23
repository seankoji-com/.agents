"""Offline scoped agreements and remote observations. All identities are synthetic."""
from copy import deepcopy
from tests.model_selection_fixtures import answer, selection_input
from shared import execution_agreement as agreements


def agree(data, endpoint=None, operations=None):
    op = data['operation']
    endpoint = endpoint or ('Open PR' if op in agreements.ENGINEERING_OPS else
                            'Issue with subissues' if op in agreements.THINKING_OPS else 'Reviewed output')
    agreement = {'invocation_id': data['invocation_id'], 'scope_id': data['scope_id'],
        'operations': operations or [op], 'model_contract_sha256': agreements.model_contract(data),
        'inspected': {k: 'fixture:inspected-' + k for k in agreements.INSPECTIONS},
        'source': answer('Approve the displayed scoped path, exact chains, options and limits.'),
        'scope': {'repository': 'example/project', 'base': 'trunk', 'paths': ['src/', 'docs/brief.md']},
        'target': {'label': endpoint}, 'destinations': {'category_id': 'category-fixture',
            'release': {'procedure': 'docs/releasing.md', 'artifacts': ['archive'], 'distribution': ['package-index']},
            'production': {'destination': 'fixture-production', 'procedure': 'docs/deploy.md',
                           'checks': ['health', 'user-flow'], 'preparations': ['backup', 'rollback']}},
        'verification': {'local_checks': ['unit'], 'ci_checks': ['required'], 'review_required': True},
        'limits': {'max_repair_cycles': 3, 'max_launch_retries': 2, 'max_cost': 1},
        'authority': [{'actions': ['inspect', 'edit', 'test', 'dispatch', 'pr', 'merge', 'release', 'deploy',
                                   'publish-issues', 'publish-discussion'], 'source': answer()}],
        'external_gates': []}
    data['agreement'] = agreements.freeze(agreement, data)
    return data


def chosen(operation='imps/run', endpoint='Open PR'):
    data = selection_input()
    data['operation'] = operation
    agree(data, endpoint)
    from shared import model_selection
    return model_selection.freeze(data)


def approved_selection(data):
    """Explicit synthetic owner answer for existing public-domain gate fixtures."""
    from shared import model_selection
    raw = deepcopy(data)
    if raw['operation'] in {r['operation'] for r in agreements.inventory()} | {'imps/investigation'}:
        agree(raw)
        raw['agreement']['limits']['max_repair_cycles'] = 20
        raw['agreement'] = agreements.freeze(raw['agreement'], raw)
    elif raw.get('agreement'):
        raw.pop('agreement')  # Format-neutral internal fixture operations exercise their original contract.
    return model_selection.freeze(raw)


def engineering(record, head='revision-one'):
    binding = record['agreement']['agreement_sha256']
    return {'agreement_sha256': binding, 'revision': head,
        'local': {'head': head, 'checks': {'unit': 'passed'}, 'reference': 'fixture:actual-check-log'},
        'review': {'head': head, 'status': 'approved', 'reference': 'fixture:independent-review',
                   'execution_id': 'fixture-review-execution',
                   'slot_id': next(s['slot_id'] for s in record['review_panel'] if s['required']),
                   'observed': deepcopy(next(s['target'] for s in record['review_panel'] if s['required']))},
        'ci': {'head': head, 'checks': {'required': 'passed'}, 'reference': 'fixture:actual-current-ci'},
        'pr': {'id': 12, 'url': 'https://github.com/example/project/pull/12', 'repository': 'example/project',
               'base': 'trunk', 'head': head, 'state': 'open', 'linked': True, 'thread_id': 'fixture-thread'},
        'release': {'revision': head, 'version': '1.2.3', 'procedure': 'docs/releasing.md',
            'publication': {'id': 'fixture-release', 'status': 'published', 'revision': head, 'version': '1.2.3',
                            'url': 'https://github.com/example/project/releases/tag/v1.2.3', 'reference': 'fixture:actual-release'},
            'merge': {'head': head, 'revision': head, 'status': 'merged', 'url': 'https://github.com/example/project/pull/12'},
            'tag': {'name': 'v1.2.3', 'revision': head, 'remote': True,
                    'url': 'https://github.com/example/project/releases/tag/v1.2.3'},
            'artifacts': {'archive': {'revision': head, 'version': '1.2.3', 'status': 'published', 'url': 'https://example.test/archive'}},
            'distribution': {'package-index': {'revision': head, 'version': '1.2.3', 'status': 'published', 'url': 'https://example.test/package'}}},
        'production': {'revision': head, 'version': '1.2.3', 'destination': 'fixture-production',
            'procedure': 'docs/deploy.md', 'deployment_id': 'deployment-fixture', 'status': 'deployed',
            'preparations': {k: {'status': 'passed', 'reference': 'fixture:actual-' + k} for k in ('backup', 'rollback')},
            'checks': {k: {'revision': head, 'version': '1.2.3', 'deployment_id': 'deployment-fixture',
                          'status': 'passed', 'reference': 'fixture:live-' + k} for k in ('health', 'user-flow')}}}
