"""Coordinator-owned model choices. Pure validation; no model clients or dispatch.

Catalogs, profiles, answers and host observations are transcribed evidence, not
authenticated attestations. Callers retain the producing selection digest outside
the mutable record (in an immutable brief/receipt). Workers consume it, never ask.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from shared.lineage import lineage, FAMILY_LINEAGE, DRIVER_LINEAGE

MODES = ('approval-required', 'auto-accept-edits', 'auto', 'full-access')
CONTINUATIONS = {'wake', 'repair', 'compaction', 'forward'}
PREFLIGHT = {'operation', 'capabilities', 'identity', 'resumable-scope'}
ORDINARY = {'repository', 'topic', 'public'}


class SelectionError(ValueError):
    """A choice, correction or authority is missing. Never silently substitute."""


def require(ok, message):
    if not ok:
        raise SelectionError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def source(value):
    require(isinstance(value, dict) and all(isinstance(value.get(k), str) and value[k].strip()
            for k in ('reference', 'answer')), 'actual user answer and source reference required')
    require(value.get('sha256') == digest(value['answer']), 'answer source digest mismatch')
    return deepcopy(value)


def key(target):
    require(isinstance(target, dict), 'target must be an exact provider/model object')
    require(all(isinstance(target.get(k), str) and target[k] for k in ('providerInstanceId', 'model')),
            'exact providerInstanceId and model required; labels are not identities')
    return target['providerInstanceId'], target['model']


def model_entry(capabilities, target, child=True):
    require(isinstance(capabilities, dict) and isinstance(capabilities.get('providers'), list),
            'live capabilities missing')
    pid, mid = key(target)
    providers = [p for p in capabilities['providers'] if isinstance(p, dict) and p.get('providerInstanceId') == pid]
    require(len(providers) == 1, 'provider absent or ambiguous')
    provider = providers[0]
    models = [m for m in provider.get('models', []) if isinstance(m, dict) and m.get('id') == mid]
    require(len(models) == 1, 'model absent or ambiguous')
    if child:
        require(provider.get('canRunChildTask') is True, 'provider cannot run child tasks')
        if pid != capabilities.get('inheritedProviderInstanceId'):
            require(provider.get('canRunCrossProviderChildTask') is True, 'cross-provider task unavailable')
    return provider, models[0]


def option_descriptors(model):
    """Accept both host catalog descriptors without renaming option IDs or values."""
    advertised = model.get('options') or []
    require(isinstance(advertised, list), 'malformed model options')
    result = []
    for raw in advertised:
        require(isinstance(raw, dict) and isinstance(raw.get('id'), str), 'malformed model option descriptor')
        option = deepcopy(raw)
        if 'values' in option and 'type' not in option:
            values = option['values']
            require(isinstance(values, list) and values and all(type(v) in (str, bool) for v in values),
                    'malformed option values')
            if all(type(v) is bool for v in values):
                option['type'] = 'boolean'; option['allowed_booleans'] = values
            else:
                require(all(isinstance(v, str) for v in values), 'mixed option value types')
                option.update(type='select', options=[{'id': v} for v in values])
        result.append(option)
    return result


def observed_options(value):
    if value is None:
        return None
    if isinstance(value, dict):
        require(all(isinstance(k, str) and type(v) in (str, bool) for k, v in value.items()),
                'malformed observed options')
        return deepcopy(value)
    require(isinstance(value, list) and all(isinstance(v, dict) and isinstance(v.get('id'), str) and
            type(v.get('value')) in (str, bool) for v in value), 'malformed observed option list')
    require(len({v['id'] for v in value}) == len(value), 'duplicate observed option ID')
    return {v['id']: v['value'] for v in value}


def validate_target(target, capabilities, child=True):
    provider, model = model_entry(capabilities, target, child)
    require(set(target) <= {'providerInstanceId', 'model', 'options', 'runtimeMode', 'execution',
                           'accept_actual_settings'}, 'unsupported target fields')
    require(target.get('execution', 'child') in ('child', 'current-context'), 'invalid target execution')
    options = target.get('options', {})
    require(isinstance(options, dict), 'options must be an object')
    advertised = option_descriptors(model)
    for name, value in options.items():
        matches = [o for o in advertised if isinstance(o, dict) and o.get('id') == name]
        require(len(matches) == 1, 'unsupported or ambiguous option: ' + name)
        option = matches[0]
        if option.get('type') == 'boolean':
            require(type(value) is bool, name + ' requires boolean')
            require(value in option.get('allowed_booleans', [True, False]), 'unsupported value for ' + name)
        else:
            require(option.get('type') == 'select' and isinstance(value, str) and
                    value in [o.get('id') for o in option.get('options', []) if isinstance(o, dict)],
                    'unsupported value for ' + name)
    mode = target.get('runtimeMode')
    if child:
        if provider.get('driverKind') == 'opencode':
            require(mode == 'full-access', 'OpenCode requires explicit full-access')
            require(isinstance(provider.get('runtimeModes'), list) and 'full-access' in provider['runtimeModes'],
                    'OpenCode full-access support must be advertised')
        if mode is not None:
            require(mode in MODES and capabilities.get('runtimeMode') in MODES and
                    MODES.index(mode) <= MODES.index(capabilities['runtimeMode']), 'runtime mode exceeds parent')
            require(provider.get('runtimeModes') is None or mode in provider['runtimeModes'], 'unsupported runtime mode')
    return dict(deepcopy(target), options=deepcopy(options))


def _profile_floor(profiles, role, *, context='; ', default=None):
    """Validate policy containers before either discovery or suitability reads them."""
    require(isinstance(profiles, dict), 'suitability profile missing' + context +
            'provide a profiles object containing the recorded role/model evidence.')
    roles = profiles.get('roles', {})
    require(isinstance(roles, dict), 'configuration gap: role profiles malformed' + context +
            'provide profiles.roles as an object.')
    floor = roles.get(role, default)
    if isinstance(floor, dict):
        require(isinstance(floor.get('required_options', {}), dict),
                f'configuration gap: profiles.roles.{role}.required_options must be an object')
        require(floor.get('source') is None or isinstance(floor['source'], str),
                f'configuration gap: profiles.roles.{role}.source must be a policy path/clause string or null')
    return floor


def suitability(target, role, profiles, capabilities, endorsement=None, configured=None):
    identity = '/'.join(key(target))
    context = ' for ' + role + ' ' + identity + '; '
    # The answer is an accepted source for ordinary configured work, with a
    # defined quality of 1. Never manufacture a score meeting an arbitrary floor.
    endorsed = role == 'workhorse' and endorsement is not None and configured is not None
    if endorsed:
        source(endorsement)
        require(key(configured) == key(target), 'endorsement target differs from configured workhorse')
    floor = _profile_floor(profiles, role, context=context, default={'minimum': 1} if endorsed else None)
    require(isinstance(floor, dict) and type(floor.get('minimum')) is int and floor['minimum'] >= 0,
            'role floor missing' + context + 'provide profiles.roles.' + role + '.minimum from the role policy.')
    rows = profiles.get('models', [])
    require(isinstance(rows, list), 'model profiles malformed' + context + 'provide profiles.models as an array.')
    matches = [m for m in rows if isinstance(m, dict) and key(m.get('target')) == key(target)]
    require(len(matches) <= 1, 'model suitability ambiguous' + context +
            'retain one profiles.models entry for this exact provider/model.')
    ordinary = endorsed and not floor.get('judgement') and not floor.get('source')
    require(matches or ordinary, 'model suitability missing' + context +
            'provide one profiles.models entry for this exact provider/model from the role policy' +
            (' at ' + str(floor['source']) if floor.get('source') else '') + '.')
    profile = deepcopy(matches[0]) if matches else {}
    lineage_field = 'profiles.models.lineage'
    provider, model = model_entry(capabilities, target, target.get('execution') != 'current-context')
    known_lineages = set(FAMILY_LINEAGE.values()) | set(DRIVER_LINEAGE.values())
    actual_lineage = lineage(provider.get('driverKind', ''), target['model'])
    if actual_lineage not in known_lineages:
        actual_lineage = 'unknown'  # A custom model's basename is not verified lineage.
    if ordinary:
        profile.setdefault('quality', 1)
        if not profile.get('reason'):
            profile['reason'] = endorsement['answer']
        # Setup also writes custom basenames here. Those inferred labels cannot
        # establish independence; an explicit custom family needs a sourced profile.
        if (not profile.get('lineage') and configured.get('lineage') and
                (actual_lineage != 'unknown' or configured['lineage'] in known_lineages)):
            profile.update(lineage=configured['lineage'], lineage_source='routing.roles.workhorse')
            lineage_field = 'routing.roles.workhorse.lineage'
    effort = [o for o in option_descriptors(model) if o.get('type') == 'select']
    require(not floor.get('judgement') or profile.get('judgement') is True,
            'judgement-capable model required by role floor' + context +
            'provide profiles.models.judgement evidence required by profiles.roles.' + role + '.judgement.')
    if floor.get('judgement') and not effort:
        require(isinstance(profile.get('fixed_effort_reason'), str) and profile['fixed_effort_reason'].strip(),
                'fixed-effort review needs a suitability reason' + context +
                'provide profiles.models.fixed_effort_reason explaining how this target meets the judgement floor.')
    require(isinstance(profile.get('reason'), str) and profile['reason'].strip(),
            'suitability needs evidence/reason' + context +
            'provide profiles.models.reason explaining how this target meets profiles.roles.' + role +
            (' from ' + str(floor['source']) if floor.get('source') else '') + '.')
    require(type(profile.get('quality')) is int and profile['quality'] >= floor['minimum'],
            'model below role floor' + context + 'provide sourced profiles.models.quality >= ' +
            str(floor['minimum']) + ' required by profiles.roles.' + role + '.minimum' +
            (' from ' + str(floor['source']) if floor.get('source') else '') + '.')
    required_options = floor.get('required_options', {})
    require(all(target.get('options', {}).get(k) == v for k, v in required_options.items()),
            'selected options below role floor' + context +
            'choose the advertised options required by profiles.roles.' + role +
            '.required_options: ' + json.dumps(required_options, sort_keys=True))
    declared = profile.get('lineage')
    if declared:
        require(bool(profile.get('lineage_source')), 'declared lineage needs a source')
        require(actual_lineage in ('unknown', declared),
                'declared lineage contradicts canonical model family' + context +
                'set ' + lineage_field + ' to ' + actual_lineage +
                ' or omit that field to use the canonical lineage.')
        actual_lineage = declared
    return actual_lineage


def routing_preference(routing):
    """An explicit saved workhorse identity, never inferred from tier/list order."""
    if routing is None:
        return None
    require(isinstance(routing, dict), 'configuration gap: malformed routing')
    if 'preferred_workhorse' not in routing:
        return None
    preferred = routing['preferred_workhorse']
    require(isinstance(preferred, dict) and set(preferred) == {'providerInstanceId', 'model'},
            'preferred_workhorse must contain only providerInstanceId and model')
    identity = key(preferred)
    roles = routing.get('roles')
    require(isinstance(roles, dict), 'preferred_workhorse requires a roles object')
    pool = roles.get('workhorse', [])
    require(isinstance(pool, list) and sum(key(entry) == identity for entry in pool) == 1,
            'preferred_workhorse must match exactly one roles.workhorse entry')
    return identity


def prefer_workhorse(result, routing, role):
    """Mark a saved preference, including a visible refusal, without selecting it."""
    preferred = routing_preference(routing)
    if preferred is None or role != 'workhorse':
        return result
    available = False
    for candidate in result['candidates']:
        if key(candidate.get('target', candidate)) == preferred:
            candidate['preferred'] = True
            available = True
        else:
            candidate.pop('preferred', None)
    rank = {True: 0, None: 1, False: 2}
    result['candidates'].sort(key=lambda c: (rank[c['independent']] if 'independent' in c else 0,
                                            not c.get('preferred', False)))
    result['preferred_workhorse'] = dict(zip(('providerInstanceId', 'model'), preferred))
    result['preference_status'] = 'available' if available else 'unavailable'
    return result


def discover(capabilities, profiles, routing=None, role='workhorse'):
    """Recommendations only. No config writes, tier/first-model quality inference."""
    require(isinstance(capabilities, dict) and isinstance(capabilities.get('providers'), list), 'live capabilities missing')
    floor = _profile_floor(profiles, role, default={})
    routing_preference(routing)
    configured = None
    if routing is not None:
        require(isinstance(routing, dict) and isinstance(routing.get('roles'), dict), 'configuration gap: malformed routing')
        configured = routing['roles'].get(role)
        require(isinstance(configured, list) and configured, 'configuration gap: empty/missing role pool')
        require(all(isinstance(t, dict) for t in configured), 'configuration gap: malformed pool')
        for index, entry in enumerate(configured):
            require('options' not in entry or isinstance(entry['options'], dict),
                    f'configuration gap: roles.{role}[{index}].options must be an object')
        configured = {key(t): t for t in configured}
    candidates, excluded = [], []
    for provider in capabilities['providers']:
        for model in provider.get('models', []):
            target = {'providerInstanceId': provider['providerInstanceId'], 'model': model['id'], 'options': {}}
            # High is a recommendation using the real option ID. currentValue is never execution evidence.
            for option in option_descriptors(model):
                if option.get('type') == 'select' and any(c.get('id') == 'high' for c in option.get('options', [])):
                    target['options'][option['id']] = 'high'
            # Configured options and role requirements outrank recommendation
            # defaults. Discovery never diagnoses an owner's answer using high.
            entry = (configured or {}).get(key(target), {})
            target['options'].update(entry.get('options', {}))
            if isinstance(floor, dict):
                for name, value in floor.get('required_options', {}).items():
                    if name not in entry.get('options', {}):
                        target['options'][name] = value
            settings = (routing or {}).get('providers', {}).get(provider['providerInstanceId'], {})
            if settings.get('runtimeMode'):
                target['runtimeMode'] = settings['runtimeMode']
            elif provider.get('driverKind') == 'opencode':
                target['runtimeMode'] = 'full-access'
            try:
                require(configured is None or key(target) in configured, 'policy-excluded (not technical unavailability)')
                validate_target(target, capabilities)
                family = suitability(target, role, profiles, capabilities)
                candidates.append({'target': target, 'lineage': family, 'recommendation_only': True})
            except SelectionError as exc:
                excluded.append({'target': target, 'reason': str(exc)})
    # A configured preferred model absent from the live catalog still needs an
    # exact exclusion; other candidates do not silently replace that preference.
    preferred = routing_preference(routing)
    if role == 'workhorse' and preferred and not any(
            key(row['target']) == preferred for row in candidates + excluded):
        excluded.append({'target': dict(zip(('providerInstanceId', 'model'), preferred)),
                         'reason': 'preferred workhorse absent from live capabilities; retain the choice and refresh capabilities'})
    return prefer_workhorse({'candidates': candidates, 'excluded': excluded,
                             'configured': configured is not None}, routing, role)


def recommend(capabilities, profiles, preferences, *, routing=None, authors=(), maximum=3):
    """Resolve operator preferences from the live catalog, then apply sourced role floors.

    Preferences are labels supplied by the request or project, never baked-in model
    IDs. Profiles may provide `preference_names` for a configured custom alias.
    Missing/ambiguous names are visible gaps, not silent defaults.
    """
    require(isinstance(preferences, list) and preferences and all(isinstance(p, str) and p for p in preferences),
            'operator model preferences required')
    require(type(maximum) is int and 1 <= maximum <= 20, 'finite recommendation chain required')
    resolved, gaps = [], []
    normalize = lambda s: re.sub(r'[^a-z0-9]', '', s.casefold())
    for preference in preferences:
        matches = []
        for provider in capabilities.get('providers', []):
            for model in provider.get('models', []):
                target = {'providerInstanceId': provider['providerInstanceId'], 'model': model['id']}
                profile = next((p for p in profiles.get('models', []) if key(p['target']) == key(target)), {})
                names = [model['id'], model.get('name', ''), model.get('label', ''), *profile.get('preference_names', [])]
                if normalize(preference) in {normalize(n) for n in names}:
                    matches.append(key(target))
        if len(matches) != 1:
            gaps.append({'preference': preference, 'reason': 'missing' if not matches else 'ambiguous'}); continue
        if matches[0] not in resolved:
            resolved.append(matches[0])
    result = {}
    for role in ('workhorse', 'reviewer'):
        pool = discover(capabilities, profiles, routing, role)
        candidates = [r for identity in resolved for r in pool['candidates'] if key(r['target']) == identity]
        if role == 'reviewer':
            candidates = [r for r in candidates if r['lineage'] != 'unknown' and
                          'unknown' not in authors and r['lineage'] not in authors]
        result[role] = candidates[:maximum]
        gaps.extend({'role': role, **r} for r in pool['excluded'] if key(r['target']) in resolved)
        if not result[role]:
            gaps.append({'role': role, 'reason': 'no suitable approved-preference candidate'})
    return {'chains': result, 'gaps': gaps, 'recommendation_only': True}


def _eligible(target, role, record):
    target = validate_target(target, record['capabilities'], target.get('execution') != 'current-context')
    # Validate the answer itself, never recommendation defaults.
    routing = record['routing']
    configured = None
    if routing is not None:
        require(isinstance(routing, dict) and isinstance(routing.get('roles'), dict),
                'configuration gap: malformed routing')
        entries = routing['roles'].get(role)
        require(isinstance(entries, list) and entries and all(isinstance(e, dict) for e in entries),
                'configuration gap: empty/malformed role pool: ' + role)
        require(key(target) in {key(e) for e in entries},
                'chosen target policy-excluded by routing.roles.' + role + ': ' + '/'.join(key(target)))
        chosen = record['work'].get(role)
        if role == 'workhorse' and chosen and target == dict(chosen, options=chosen.get('options', {})):
            configured = next(e for e in entries if key(e) == key(target))
    settings = (record['routing'] or {}).get('providers', {}).get(target['providerInstanceId'], {})
    if settings.get('requireRuntimeMode'):
        require(target.get('runtimeMode') == settings.get('runtimeMode'), 'required configured runtime mode changed/dropped')
    return target, suitability(target, role, record['profiles'], record['capabilities'],
                               record['source'] if configured is not None else None, configured)


def _authority(value):
    require(isinstance(value, dict), 'replacement authority missing; choose invocation-only or standing-project')
    source(value.get('source'))
    require(value.get('scope') in ('invocation-only', 'standing-project'), 'explicit authority scope required')
    require(isinstance(value.get('data_classes'), list) and value['data_classes'], 'authority data classes required')
    return value


def _authority_target(value, target, record):
    _authority(value)
    if value['scope'] == 'invocation-only':
        require(value.get('invocation_id') == record['invocation_id'], 'replacement grant belongs to another invocation')
    else:
        require(value.get('project_id') and value['project_id'] == record.get('project_id'), 'replacement project scope mismatch')
    recipients = value.get('recipients', [])
    require(any(isinstance(r, dict) and r.get('providerInstanceId') == target['providerInstanceId'] and
                (r.get('model') == target['model'] or r.get('model_class') == 'suitable-live-catalog')
                for r in recipients), 'replacement recipient outside authority')
    limits = value.get('limits', {})
    require(type(limits.get('max_cost')) in (int, float) and limits['max_cost'] >= 0 and
            isinstance(limits.get('options'), dict) and all(isinstance(v, list) for v in limits['options'].values()),
            'record granted cost and effort limits')
    require(all(k in limits['options'] and v in limits['options'][k] for k, v in target.get('options', {}).items()),
            'replacement option/effort exceeds authority')


def _actual_context(target, coordinator):
    if target.get('execution') != 'current-context':
        return
    require(key(target) == key(coordinator), 'different work model requires a child')
    observed = coordinator.get('observed_options')
    require((observed is not None and observed == target['options']) or
            (target.get('accept_actual_settings') is True and target['options'] == {}),
            'current-context settings differ/unknown: choose same-model child or explicitly accept actual settings')


def _subject_author_role(record, role):
    # Persona cells supply isolated raw evidence. The planner and analyst author
    # the reviewed protocol/synthesis; explicit contributors always remain below.
    return not (record.get('operation') in ('focus-group/plan', 'focus-group/run', 'focus-group/resume') and
                re.fullmatch(r'participant-[0-9]{2,}', role))


def _prospective_authors(record):
    authors = {record['coordinator'].get('lineage', 'unknown')} | set(record.get('author_lineages', []))
    choices = list(record['work'].items())
    if record.get('operation') in ('focus-group/plan', 'focus-group/run', 'focus-group/resume'):
        choices += [(r['role'], r['target']) for r in record.get('work_replacements', [])]
    authors.update(_eligible(target, role, record)[1]
                   for role, target in choices if _subject_author_role(record, role))
    return authors


def completion_authors(record, author_lineages=(), evidence_lineages=()):
    """Require actual work history when approved alternatives can change authors.

    Completion observations, like host identities, are transcribed evidence.
    Approved but unused backups are possibilities, not revision producers.
    """
    authors = set()
    for group in (author_lineages, evidence_lineages):
        require(isinstance(group, (list, tuple, set, frozenset)) and
                all(isinstance(value, str) and value.strip() == value and value and
                    value.casefold() not in ('unknown', 'unverified', 'inferred') for value in group),
                'actual work-author lineages missing/unknown')
        authors.update(group)
    require(not any(_subject_author_role(record, row['role']) for row in record.get('work_replacements', [])) or authors,
            'actual work-author lineages required with approved work replacements')
    return authors | _prospective_authors(record)


def freeze(data):
    """Validate an explicit answer, freeze its evidence and return a sealed record."""
    return _freeze(data)


def _freeze(data, *, legacy=False):
    require(isinstance(data, dict), 'selection input must be an object')
    record = deepcopy(data)
    record.pop('selection_sha256', None)
    record['schema_version'] = 1
    for name in ('invocation_id', 'scope_id', 'operation'):
        require(isinstance(record.get(name), str) and record[name], name + ' required')
    source(record.get('source'))
    if 'routing_scope' in record:
        require(record['routing_scope'] in ('invocation-only', 'global'),
                'routing_scope must be invocation-only or global; never silently narrow the owner choice')
    require(isinstance(record.get('coordinator'), dict) and all(record['coordinator'].get(k)
            for k in ('providerInstanceId', 'model')), 'coordinator actual identity required')
    for name in ('capabilities', 'routing', 'profiles'):
        require(name in record, name + ' snapshot required')
        record[name + '_sha256'] = digest(record[name])
    require(isinstance(record.get('work'), dict) and record['work'], 'work choices required')
    require(legacy or 'workhorse' not in record['work'] or 'routing_scope' in record,
            'workhorse routing scope missing; record routing_scope as global or invocation-only from the owner answer. '
            'If unanswered, ask only which scope applies; never silently narrow the owner choice.')
    authors = {record['coordinator'].get('lineage', 'unknown')}
    for role, chosen in record['work'].items():
        target, family = _eligible(chosen, role, record)
        record['work'][role] = target
        if _subject_author_role(record, role):
            authors.add(family)
        _actual_context(target, record['coordinator'])
    authors.update(record.get('author_lineages', []))
    panel = record.get('review_panel')
    require(isinstance(panel, list) and panel, 'review choices required, including unused preferences')
    ids = set()
    for slot in panel:
        require(isinstance(slot, dict) and isinstance(slot.get('slot_id'), str) and slot['slot_id'] and
                slot['slot_id'] not in ids, 'unique named panel slot required')
        ids.add(slot['slot_id'])
        require(isinstance(slot.get('coverage'), list) and slot['coverage'], 'panel coverage required')
        require(type(slot.get('required')) is bool, 'declare review stage applicability')
        target, family = _eligible(slot['target'], slot['role'], record)
        require(target.get('execution') != 'current-context', 'primary reviewers must be child executions')
        slot['target'] = target
        if slot.get('independent', True) and slot['required']:
            require('unknown' not in authors and family != 'unknown' and family not in authors,
                    'reviewer must be independent of every actual/prospective author')
    for field in ('work_replacements', 'review_replacements'):
        replacements = record.setdefault(field, [])
        require(isinstance(replacements, list), 'finite replacement list required')
        for replacement in replacements:
            _authority(replacement.get('authority'))
            require(replacement.get('execution', 'child') in ('child', 'current-context', 'self-review'), 'invalid replacement execution')
            if replacement.get('execution') == 'self-review':
                require(field == 'review_replacements', 'self-review is not work authority')
                _authority_target(replacement['authority'], record['coordinator'], record)
            else:
                target, _ = _eligible(replacement['target'], replacement['role'], record)
                _actual_context(target, record['coordinator'])
                _authority_target(replacement['authority'], target, record)
                require(replacement['target'] == target, 'replacement must carry explicit options')
    if record.get('agreement') is not None:
        from shared.execution_agreement import validate as validate_agreement
        validate_agreement(record['agreement'], record)
    record['selection_sha256'] = digest(record)
    return record


def validate(record, expected=None):
    require(isinstance(record, dict), 'model selection missing; collect upfront choices')
    raw = {k: v for k, v in record.items() if k != 'selection_sha256'}
    actual = digest(raw)
    require(record.get('selection_sha256') == actual and (expected is None or expected == actual),
            'selection tampered or producing selection digest mismatch')
    for name in ('capabilities', 'routing', 'profiles'):
        require(record.get(name + '_sha256') == digest(record.get(name)), 'selection snapshot digest mismatch')
    # Existing sealed records predate explicit routing scope. Only validation
    # retains their invocation default; freezing a new answer requires the field.
    require(_freeze(record, legacy=True) == record, 'selection not canonical or invalid')
    return record


def gate(record, *, invocation_id, scope_id, event='new', action='dispatch', expected=None,
         pinned=False, retain=None, schedule_id=None, capabilities=None, policy_digests=None):
    """Admission before investigation/drafting/dispatch. Deterministic paths stay direct.

    The operation adapter supplies deterministic/preflight classification from its
    command contract, not from user prose. No children are created by this helper.
    """
    if action in PREFLIGHT or action == 'deterministic':
        return {'allowed': True, 'chooser': False, 'dispatch': False}
    record = validate(record, expected)
    require(record['scope_id'] == scope_id, 'selection belongs to another scope')
    require(record['invocation_id'] == invocation_id, 'new qualifying invocation needs new choices')
    require(event in CONTINUATIONS | {'new', 'resume', 'schedule'}, 'unknown invocation event')
    if pinned and event == 'resume' and not record.get('agreement'):
        require(retain is True, 'pinned resume requires retain-or-stop; rotation refused')
    from shared.execution_agreement import inventory, admit
    if record['operation'] in {r['operation'] for r in inventory()}:
        admit(record, action='inspect')
    if event == 'schedule':
        schedule = record.get('schedule') or {}
        source(schedule.get('source'))
        require(schedule.get('schedule_id') == schedule_id and bool(schedule_id), 'schedule-bound reuse authority missing')
        require(capabilities is not None, 'scheduled fire needs fresh capability revalidation')
        require(policy_digests == {name: record[name] for name in ('routing_sha256', 'profiles_sha256')},
                'scheduled fire needs current routing/profile digests; changed policy needs correction')
        fresh = dict(record, capabilities=capabilities)
        for role, target in record['work'].items():
            _eligible(target, role, fresh)
        for slot in record['review_panel']:
            _eligible(slot['target'], slot['role'], fresh)
    return {'allowed': True, 'chooser': False, 'selection_sha256': record['selection_sha256']}


def dispatch(record, *, role, slot_id=None, target=None, data_classes=('repository',),
             unavailable=None, live_tasks=(), expected=None, author_lineages=()):
    """Return exact tool target only after choice, quality, sharing and fallback checks.

    `unavailable` is a host failure reference, never an adverse verdict. Planning
    acceptance later recomputes the complete candidate chain; this is an admission
    check, not a review receipt or proof of technical unavailability.
    """
    record = validate(record, expected)
    if record.get('agreement'):
        from shared.execution_agreement import admit
        admit(record, action='dispatch')
    review = slot_id is not None
    if review:
        slots = [s for s in record['review_panel'] if s['slot_id'] == slot_id]
        require(len(slots) == 1 and slots[0]['role'] == role, 'unknown panel role/slot')
        slot = slots[0]
        require(slot['required'], 'unused review preference does not enable optional review')
        primary = slot['target']
    else:
        require(role in record['work'], 'work role was not chosen')
        primary = record['work'][role]
    target = deepcopy(primary if target is None else target)
    authority = None
    if target != primary:
        require(not live_tasks, 'reconcile live/uncertain tasks before replacement')
        require(isinstance(unavailable, dict) and unavailable.get('kind') in
                ('technical', 'capacity', 'permission', 'privacy', 'capability') and
                unavailable.get('reference'), 'replacement needs host failure evidence; adverse is not unavailability')
        matches = [r for r in record['review_replacements' if review else 'work_replacements']
                   if r.get('role') == role and r.get('target') == target and
                   (not review or r.get('slot_id') == slot_id)]
        require(len(matches) == 1, 'target/options change not authorised by chosen replacement chain')
        if record.get('agreement'):
            if unavailable.get('cause') == 'author-independence':
                require(review and suitability(primary, role, record['profiles'], record['capabilities']) in
                        (_prospective_authors(record) | set(author_lineages)), 'primary reviewer is still eligible')
                require(unavailable.get('original_not_launched') is True,
                        'reconcile launched reviewer before independence replacement')
            else:
                reconcile_replacement(record, role, slot_id, target, unavailable)
        authority = _authority(matches[0]['authority'])
        _authority_target(authority, target, record)
    if review and slot.get('independent', True):
        family = suitability(target, role, record['profiles'], record['capabilities'])
        authors = _prospective_authors(record) | set(author_lineages)
        require('unknown' not in authors and family != 'unknown' and family not in authors,
                'stronger independent slot refuses author/reviewer collision')
    if authority:
        require(set(data_classes) <= set(authority['data_classes']), 'replacement data scope exceeded')
    confidential = set(data_classes) - ORDINARY
    if confidential:
        grants = record.get('sharing', [])
        require(any(key(g['target']) == key(target) and confidential <= set(g['data_classes']) and
                    source(g['source']) for g in grants), 'confidential-class sharing authority missing')
    # A selected exact primary recipient permits only ordinary material for this invocation.
    return {'target': {k: deepcopy(v) for k, v in target.items() if k in
                       ('providerInstanceId', 'model', 'options', 'runtimeMode')},
            'execution': target.get('execution', 'child'), 'selection_sha256': record['selection_sha256'],
            'invocation_id': record['invocation_id'], 'scope_id': record['scope_id'],
            'routing_scope': record.get('routing_scope', 'invocation-only')
                             if role == 'workhorse' and not review and target == primary else 'invocation-only',
            'slot_id': slot_id, 'role': role, 'substituted': target != primary,
            **({'agreement_sha256': record['agreement']['agreement_sha256']} if record.get('agreement') else {})}


def correlate(plan, observed):
    """Do not fill unreported effort from requested options or catalog defaults."""
    target = plan['target']
    require(key(observed) == key(target), 'observed provider/model mismatch')
    reported = observed_options(observed.get('options'))
    if reported is None:
        require(not plan.get('agreement_sha256'), 'observed exact options unreported; reconcile retained task')
        return {'identity': 'matched', 'options': 'unreported', 'requested_options': target.get('options', {})}
    require(reported == target.get('options', {}), 'observed/requested options mismatch')
    return {'identity': 'matched', 'options': 'matched'}


def reconcile_replacement(record, role, slot_id, target, unavailable):
    """Require owned original request observations and ordered finite chain exhaustion."""
    require(unavailable.get('verdict') not in ('approve', 'adverse') and not unavailable.get('findings'),
            'completed review is not an outage; retain adverse findings and repair')
    chain = [r for r in record['review_replacements' if slot_id else 'work_replacements']
             if r['role'] == role and (not slot_id or r.get('slot_id') == slot_id)]
    index = next(i for i, r in enumerate(chain) if r['target'] == target)
    reconciled = unavailable.get('reconciled', [])
    require(isinstance(reconciled, list) and len(reconciled) == index + 1,
            'every earlier approved target needs unavailable/reconciled evidence')
    primary = next(s['target'] for s in record['review_panel'] if s['slot_id'] == slot_id) if slot_id else record['work'][role]
    prior = [primary] + [r['target'] for r in chain[:index]]
    for row, chosen in zip(reconciled, prior):
        require(row.get('target') == chosen and row.get('request_id') and row.get('reference') and
                row.get('owned') is True and row.get('has_pending_child_runs') is False and
                row.get('status') in ('failed', 'cancelled', 'interrupted', 'absent') and
                row.get('reason') in ('technical', 'capacity', 'permission', 'privacy', 'capability'),
                'reconcile owned original launch under original request ID before replacement')
        require(not row.get('findings') and row.get('verdict') not in ('approve', 'adverse'),
                'healthy review result cannot trigger fallback')


def panel_report(record, passes):
    """Coverage accounting only; a later domain validator decides acceptance."""
    validate(record)
    require(len({p['execution_id'] for p in passes}) == len(passes), 'one execution cannot count as several panel members')
    covered = {p.get('slot_id') for p in passes if p.get('mode') != 'self-review'}
    required = {s['slot_id'] for s in record['review_panel'] if s['required']}
    return {'requested': sorted(required), 'covered': sorted(covered & required),
            'missing': sorted(required - covered), 'degraded': bool(required - covered),
            'actual_passes': len(passes), 'unused': [s['slot_id'] for s in record['review_panel'] if not s['required']]}


def prospective(previous, current, state, *, requested_rereview=False):
    """Keep historical evidence, findings and counters under their producing choices."""
    validate(previous); validate(current)
    require(previous['scope_id'] == current['scope_id'], 'prospective change belongs to another scope')
    require(not state.get('live_tasks'), 'reconcile live tasks before prospective change')
    result = deepcopy(state)
    result['pending_selection_sha256'] = current['selection_sha256']
    if requested_rereview:
        require(type(result.get('rounds_used')) is int and type(result.get('round_limit')) is int and
                result['rounds_used'] < result['round_limit'], 'retained review budget exhausted')
        result['rounds_used'] += 1
    return result


def authority_path(project_id, environ=None):
    require(isinstance(project_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', project_id)
            and project_id not in ('.', '..'), 'invalid project authority ID')
    env = os.environ if environ is None else environ
    base = env.get('XDG_STATE_HOME')
    root = Path(base) if base and Path(base).is_absolute() else Path(env.get('HOME') or Path.home()) / '.local/state'
    return root / 't3-plugins/authorities' / project_id / 'model-policy.json'


def save_authority(project_id, grant, environ=None):
    """Only an explicit standing answer persists; invocation-only leaves no file."""
    _authority(grant)
    require(grant.get('project_id') == project_id, 'authority project mismatch')
    if grant['scope'] == 'invocation-only':
        return {'persisted': False}
    require(isinstance(grant.get('recipients'), list) and grant['recipients'] and
            isinstance(grant.get('limits'), dict), 'standing authority needs recipient/classes and effort/cost/data limits')
    # Reuse the repository's private locked/atomic storage discipline.
    from core.jobs.store import _directory_fd, _atomic, canonical
    import fcntl, stat
    path = authority_path(project_id, environ)
    os.close(_directory_fd(path.parent, create=True))
    require(stat.S_IMODE(path.parent.stat().st_mode) & 0o077 == 0, 'authority directory must be private')
    parent = _directory_fd(path.parent)
    try:
        fd = os.open('model-policy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'authority lock must be a regular file')
        fcntl.flock(fd, fcntl.LOCK_EX)
        require(not path.is_symlink(), 'authority file cannot be a symlink')
        _atomic(path, canonical({'schema_version': 1, 'project_id': project_id, 'grant': deepcopy(grant), 'sha256': digest(grant)}))
    finally:
        os.close(fd)
    return {'persisted': True, 'path': str(path)}


def load_authority(project_id, environ=None):
    from core.jobs.store import _regular, strict_load
    path = authority_path(project_id, environ)
    if not path.exists():
        return None
    record = strict_load(_regular(path, max_bytes=1024 * 1024))
    require(record.get('project_id') == project_id and record.get('sha256') == digest(record.get('grant')),
            'standing authority record changed')
    _authority(record['grant'])
    return record


def applicable_authority(project_id, target, record, data_classes, environ=None):
    """Return an existing in-scope grant; None means batch the missing decision."""
    stored = load_authority(project_id, environ)
    if stored is None:
        return None
    grant = stored['grant']
    try:
        _authority_target(grant, target, record)
        require(set(data_classes) <= set(grant['data_classes']), 'standing data scope exceeded')
    except SelectionError:
        return None
    return deepcopy(grant)


def dispute_slots(record, findings):
    """Expose original-lineage obligations; changing a panel cannot clear them."""
    validate(record)
    obligations = []
    for finding in findings:
        if finding.get('severity') not in ('blocker', 'major') or finding.get('disposition') != 'rejected':
            continue
        family = finding.get('reviewer_lineage', 'unknown')
        candidates = [s['slot_id'] for s in record['review_panel'] if
                      suitability(s['target'], s['role'], record['profiles'], record['capabilities']) == family
                      and family != 'unknown']
        obligations.append({'finding_id': finding['id'], 'original_lineage': family,
                            'dispute_only_slots': candidates,
                            'alternatives': ['content repair', 'scoped owner decision'],
                            'cleared': False})
    return obligations
