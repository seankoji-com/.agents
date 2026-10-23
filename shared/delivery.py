"""Endpoint-specific observed evidence, separate from local source readiness.

No network calls. The coordinator supplies actual host/GitHub observations; fake
observations in offline tests prove rejection behavior, never remote delivery.
"""
from copy import deepcopy
import re
from urllib.parse import urlparse

from shared import execution_agreement as agreements
from shared.model_selection import digest, require, validate, dispatch, correlate, completion_authors


def _url(value, repository=None, kind=None):
    require(isinstance(value, str) and urlparse(value).scheme == 'https' and bool(urlparse(value).netloc),
            'real remote HTTPS identity required')
    if repository and kind:
        require(re.fullmatch(r'https://github\.com/' + re.escape(repository) + '/' + kind + r'/[1-9][0-9]*', value),
                'remote URL belongs to wrong repository/type')


def _checks(row, head, names, label):
    require(isinstance(row, dict) and row.get('head') == head, 'stale/wrong-head ' + label)
    require(all(row.get('checks', {}).get(name) == 'passed' for name in names), label + ' missing/failed/queued')
    require(row.get('reference'), label + ' needs original observation/log reference')


def _review(selection, evidence, author_lineages=()):
    rows = evidence.get('reviews', [evidence.get('review', {})])
    slots = [s for s in selection['review_panel'] if s['required']]
    require(slots and isinstance(rows, list), 'required independent review slots missing')
    # Alternate representations and additional rows cannot erase objections.
    for row in [evidence.get('review', {}), *rows]:
        require(isinstance(row, dict), 'review evidence must be an object')
        require(not any(f.get('severity') in ('blocker', 'major') and
                        (f.get('disposition') not in ('fixed', 'rejected') or not f.get('evidence'))
                        for f in row.get('findings', [])), 'unresolved adverse review findings')
    authors = completion_authors(selection, author_lineages, evidence.get('author_lineages', ()))
    executions = set()
    for slot in slots:
        matches = [r for r in rows if r.get('slot_id') == slot['slot_id']]
        require(len(matches) == 1 and slot.get('independent', True), 'required independent review slot missing')
        row = matches[0]
        require(row.get('head') == evidence.get('revision') and row.get('status') == 'approved' and
                row.get('reference') and isinstance(row.get('execution_id'), str) and
                row['execution_id'].strip() and row['execution_id'] not in executions,
                'current-head distinct required review missing/adverse')
        executions.add(row['execution_id'])
        plan = dispatch(selection, role=slot['role'], slot_id=slot['slot_id'],
                        target=row.get('target'), unavailable=row.get('unavailable'),
                        author_lineages=list(authors) + row.get('author_lineages', []))
        correlate(plan, row.get('observed', {}))


def _pr(agreement, evidence, head, *, markdown=False, merged=False):
    policy = agreement['verification']
    _checks(evidence.get('local'), head, policy['local_checks'], 'local checks')
    review = evidence.get('review', {})
    require(review.get('head') == head and review.get('status') == 'approved' and review.get('reference'),
            'current-head required review missing/adverse')
    _checks(evidence.get('ci'), head, policy['ci_checks'], 'required CI')
    pr = evidence.get('pr', {})
    scope = agreement['scope']
    _url(pr.get('url'), scope['repository'], 'pull')
    require(type(pr.get('id')) is int and pr['id'] > 0 and
            pr['url'].endswith('/' + str(pr['id'])) and pr.get('repository') == scope['repository'] and
            pr.get('head') == (evidence.get('source_head', head) if merged else head) and pr.get('base') == scope['base'] and
            pr.get('state') == ('merged' if merged else 'open') and pr.get('linked') is True and pr.get('thread_id'),
            'real linked intended-base/current-head PR required')
    if markdown:
        require(pr.get('files') and set(pr['files']) <= set(scope['paths']) and
                all(p.endswith('.md') for p in pr['files']), 'Markdown PR contains unapproved/non-Markdown content')


def engineering(selection, evidence, revision, *, author_lineages=()):
    validate(selection)
    agreement = agreements.validate(selection.get('agreement'), selection)
    target = agreement['target']['label']
    require(target in agreements.ENGINEERING, 'not an engineering endpoint')
    require(evidence.get('agreement_sha256') == agreement['agreement_sha256'] and
            evidence.get('revision') == revision, 'completion producing agreement/revision differs')
    require(evidence.get('no_change') is not True, 'no-change outcome requires endpoint resolution, never an empty PR/tag')
    external = evidence.get('external_approvals', [])
    for action in (['pr'] if target == 'Open PR' else ['pr', 'merge', 'release'] +
                   (['deploy'] if target == 'Verified in Prod' else [])):
        agreements.admit(selection, action=action, external=external)
    _pr(agreement, evidence, revision, merged=target != 'Open PR')
    _review(selection, evidence, author_lineages)
    if target != 'Open PR':
        release = evidence.get('release', {})
        policy = agreement['destinations']['release']
        require(release.get('procedure') == policy['procedure'] and release.get('revision') == revision and
                release.get('version'), 'release procedure/revision/version differs')
        publication = release.get('publication', {})
        require(publication.get('id') and publication.get('status') == 'published' and
                publication.get('revision') == revision and publication.get('version') == release['version'] and
                publication.get('reference'), 'actual release publication missing/draft/stale')
        _url(publication.get('url'))
        merge = release.get('merge', {})
        require(merge.get('head') == evidence.get('source_head', revision) and merge.get('revision') == revision and
                merge.get('status') == 'merged' and merge.get('url') == evidence['pr']['url'],
                'accepted merge revision/source PR missing')
        _url(merge.get('url'), agreement['scope']['repository'], 'pull')
        tag = release.get('tag', {})
        require(tag.get('remote') is True and tag.get('revision') == revision and tag.get('name') and
                tag.get('version', release['version']) == release['version'], 'intended remote tag at wrong revision/version')
        intended_tag = agreement['target'].get('tag')
        require(tag['name'] == intended_tag if intended_tag else tag['name'] in (release['version'], 'v' + release['version']),
                'remote tag is not the intended version tag')
        intended = agreement['target'].get('version')
        require(intended is None or intended == release['version'], 'wrong selected release version')
        _url(tag.get('url'))
        for group in ('artifacts', 'distribution'):
            for item in policy[group]:
                name = item if isinstance(item, str) else item['name']
                status = 'published' if isinstance(item, str) else item['status']
                row = release.get(group, {}).get(name, {})
                require(row.get('revision') == revision and row.get('version') == release['version'] and
                        row.get('status') == status, 'required release ' + group + ' missing: ' + name)
                _url(row.get('url'))
    if target == 'Verified in Prod':
        prod = evidence.get('production', {})
        policy = agreement['destinations']['production']
        require(prod.get('destination') == policy['destination'] and prod.get('procedure') == policy['procedure'] and
                prod.get('revision') == revision and prod.get('version') == evidence['release']['version'] and
                prod.get('status') == 'deployed' and prod.get('deployment_id'),
                'agreed production revision/version not actually deployed')
        require(all(prod.get('preparations', {}).get(k, {}).get('status') == 'passed' and
                    prod['preparations'][k].get('reference') for k in policy['preparations']),
                'required backup/migration/rollback preparations missing')
        for name in policy['checks']:
            check = prod.get('checks', {}).get(name, {})
            require(check.get('status') == 'passed' and check.get('reference') and
                    all(check.get(k) == prod[k] for k in ('revision', 'version', 'deployment_id')),
                    'named live production observation missing/stale: ' + name)
    return {'complete': True, 'target': target, 'revision': revision,
            'agreement_sha256': agreement['agreement_sha256'], 'live_compatibility_claim': False}


def start(selection, content_sha256, subissues=()):
    validate(selection)
    agreement = agreements.validate(selection.get('agreement'), selection)
    label = agreement['target']['label']
    require(label in agreements.THINKING, 'thinking delivery target required')
    require(re.fullmatch('[0-9a-f]{64}', content_sha256 or ''), 'accepted complete content hash required')
    plan = deepcopy(list(subissues))
    if label == 'Issue with subissues':
        require(plan and len({p.get('key') for p in plan}) == len(plan), 'distinct actionable native subissue plan required')
        keys = {p['key'] for p in plan}
        for p in plan:
            require(isinstance(p.get('key'), str) and p['key'] and p.get('acceptance') and
                    isinstance(p.get('content_sha256'), str) and re.fullmatch('[0-9a-f]{64}', p['content_sha256']) and
                    isinstance(p.get('depends_on'), list) and len(set(p['depends_on'])) == len(p['depends_on']) and
                    set(p['depends_on']) <= keys - {p['key']},
                    'subissue needs content hash, dependencies and acceptance evidence')
        def visit(key, stack):
            require(key not in stack, 'cyclic subissue dependencies')
            for dep in next(p for p in plan if p['key'] == key)['depends_on']:
                visit(dep, stack | {key})
        for key in keys:
            visit(key, set())
    state = {'schema_version': 1, 'agreement_sha256': agreement['agreement_sha256'],
             'target': label, 'content_sha256': content_sha256, 'subissues': plan,
             'observations': {}, 'requests': {}, 'history': [], 'execution_authorized': False}
    return _seal(state)


def _seal(state):
    state = deepcopy(state)
    state.pop('sha256', None)
    state['sha256'] = digest(state)
    return state


def check_state(selection, state):
    validate(selection)
    agreement = agreements.validate(selection.get('agreement'), selection)
    require(isinstance(state, dict) and _seal(state) == state, 'delivery ledger tampered')
    require(state['agreement_sha256'] == agreement['agreement_sha256'] and
            state['target'] == agreement['target']['label'], 'delivery agreement/target changed')
    require(state.get('execution_authorized') is False, 'published thinking never grants implementation')
    return agreement


def reconcile(selection, state, key, observation=None, request_id=None, external=()):
    """Retain partial remote identities and stable pending requests before retries.

    A lost create response returns a reconcile action for its original request.
    Only an explicit host `absent` observation clears that uncertain request.
    """
    agreement = check_state(selection, state)
    allowed = {'parent', *(p['key'] for p in state['subissues'])} if state['target'] == 'Issue with subissues' else {'delivery'}
    require(key in allowed, 'unknown delivery item')
    action = {'Issue with subissues': 'publish-issues', 'Discussion post': 'publish-discussion', 'Markdown PR': 'pr'}[state['target']]
    approvals = list(external) or state.get('external_approvals', [])
    agreements.admit(selection, action=action, external=approvals)
    result = deepcopy(state)
    result['external_approvals'] = deepcopy(approvals)
    old = result['observations'].get(key, {})
    pending = result['requests'].get(key)
    if observation is not None:
        require(isinstance(observation, dict) and observation.get('reference'), 'actual publication/reconciliation observation required')
        if pending:
            require(observation.get('request_id') == pending, 'reconcile original publication request ID')
        for identity in ('id', 'url'):
            require(not old.get(identity) or observation.get(identity) == old[identity],
                    'remote identity changed; reconcile duplicate instead of replacing')
        if observation.get('status') == 'absent':
            require(not old.get('id') and not old.get('url'), 'cannot erase partial remote identity')
            result['requests'].pop(key, None)
        else:
            for other, row in result['observations'].items():
                require(other == key or not observation.get('id') or row.get('id') != observation['id'],
                        'duplicate remote object assigned to multiple delivery items')
            result['observations'][key] = deepcopy(observation)
        result['history'].append({'key': key, 'observation': deepcopy(observation)})
    elif old.get('id') or old.get('url'):
        return {'state': state, 'action': 'inspect-existing', 'observation': old}
    elif pending:
        return {'state': state, 'action': 'reconcile', 'request_id': pending}
    else:
        require(isinstance(request_id, str) and request_id, 'stable publication request ID required')
        require(request_id not in result['requests'].values(), 'publication request belongs to another item')
        result['requests'][key] = request_id
    return {'state': _seal(result), 'action': 'observed' if observation is not None else 'create',
            'repository': agreement['scope']['repository']}


def thinking(selection, state, content_sha256, *, source_ready, revision=None):
    agreement = check_state(selection, state)
    require(source_ready is True and state['content_sha256'] == content_sha256,
            'current accepted discovery/spec/handoff provenance required')
    label = state['target']; observations = state['observations']; repo = agreement['scope']['repository']
    action = {'Issue with subissues': 'publish-issues', 'Discussion post': 'publish-discussion', 'Markdown PR': 'pr'}[label]
    agreements.admit(selection, action=action, external=state.get('external_approvals', []))
    def published(row, content, kind):
        require(row.get('status') == 'published' and row.get('id') and row.get('reference') and
                row.get('content_sha256') == content and row.get('repository') == repo,
                'complete accepted remote content missing/draft/stale')
        _url(row.get('url'), repo, kind)
        number = row.get('number', row['id'])
        require(type(number) is int and number > 0 and row['url'].endswith('/' + str(number)),
                'remote published identity/number differs from URL')
    if label == 'Issue with subissues':
        parent = observations.get('parent', {})
        published(parent, content_sha256, 'issues')
        for spec in state['subissues']:
            row = observations.get(spec['key'], {})
            published(row, spec['content_sha256'], 'issues')
            require(row.get('parent_id') == parent['id'] and row.get('native_subissue') is True and
                    row.get('id') in parent.get('native_subissue_ids', []) and
                    row.get('acceptance') == spec['acceptance'] and
                    row.get('depends_on_ids') == [observations.get(k, {}).get('id') for k in spec['depends_on']],
                    'native actionable subissue relationship/dependencies missing')
    elif label == 'Discussion post':
        row = observations.get('delivery', {})
        published(row, content_sha256, 'discussions')
        require(row.get('category_id') == agreement['destinations']['category_id'] and
                row.get('is_draft') is False, 'actual published Discussion category/identity required')
    else:
        row = observations.get('delivery', {})
        require(row.get('content_sha256') == content_sha256 and row.get('revision') == revision,
                'Markdown PR content/head differs')
        _pr(agreement, row, revision, markdown=True)
        _review(selection, row)
    return {'complete': True, 'target': label, 'urls': [o.get('url', o.get('pr', {}).get('url'))
            for o in observations.values()], 'execution_authorized': False,
            'agreement_sha256': agreement['agreement_sha256']}
