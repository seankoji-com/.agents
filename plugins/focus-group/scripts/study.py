#!/usr/bin/env python3
"""Deterministic focus-group study contract: panel, plan revisions, approval, limits,
dispatch admission and accepted-result carry-forward.

Nothing here calls a model, a browser, T3 or GitHub, schedules work or waits. The
coordinator supplies host evidence (a saved `orchestrator_capabilities` response and
optional schema observations) and acts on each JSON verdict. Study records live under
the private job root beside the generic job: `ROOT/<study>/focus-group/`.

Exit codes: 0 the operation succeeded, 1 a refusal or hold (nothing was dispatched or
charged), 2 invalid input or unsafe state. Every run prints one JSON object.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import json
import os
import re
import stat
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
# An installed package carries core/ and shared/ beside the plugin; a source checkout two levels up.
RUNTIME = next((base for base in (PKG, PKG.parents[1]) if (base / 'core').is_dir()), PKG)
sys.path.insert(0, str(RUNTIME))
from core.jobs.store import (JobError, _atomic, _regular, _reject_symlink_components,  # noqa: E402
                             _retain, canonical, digest, strict_load)
from shared.lineage import lineage as catalog_lineage  # noqa: E402

try:
    import fcntl
except ImportError:  # pragma: no cover - reported when a mutation needs the lock
    fcntl = None

SCHEMA_VERSION = 1
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
SUGGESTED_PERSONAS = 4
SUGGESTED_LINEAGES = 2
MODES = ('combined', 'capture-only')
ENVIRONMENTS = ('fixture', 'staging', 'live')
CONSUMERS = ('participant', 'analysis', 'review')
MATERIAL_CLASSES = ('stimulus', 'persona', 'participant-response', 'journey-evidence', 'analysis-report')
STAGES = ('first-impression', 'journey', 'analysis', 'review')
STAGE_KIND = {'first-impression': 'participant', 'journey': 'participant', 'analysis': 'analysis', 'review': 'review'}
POOLS = {'participant': 'participant_repairs', 'analysis': 'analysis_repairs', 'review': 'review_repairs'}
FACTS = ('image_delivery', 'browser_tools', 'isolation', 'hard_stop')
LIMIT_BOUNDS = {'max_concurrency': (1, 64), 'max_attempts_per_slot': (1, 10), 'participant_repairs': (0, 500),
                'analysis_repairs': (0, 20), 'review_repairs': (0, 20)}
# A journey runs in a fresh anonymous context, or in one approved, host-preauthenticated test context.
CONTEXT_CLASSES = ('fresh-anonymous', 'preauthenticated-test')
# A pre-dispatch catalog observation older than this, or older than one already recorded, is stale.
CATALOG_MAX_AGE = dt.timedelta(minutes=15)
CLOCK_SKEW = dt.timedelta(minutes=1)
HEX64 = re.compile(r'[0-9a-f]{64}')
# A persona is one invented individual. This lint catches a few common phrasings of a whole group's
# preference ("all parents want", "parents always prefer", a clause opening "Parents want"). It is not
# semantic detection; the coordinator still reads every persona.
_PREFERENCE = r'(?:want|need|prefer|like|love|hate|dislike|value|expect|care|choose|avoid)\b'
GROUP_CLAIM = re.compile(
    r"\b(?:all|every|most|no)\s+(?:[a-z-]+\s+)?[a-z-]+s\s+(?:always\s+|never\s+|really\s+)?" + _PREFERENCE +
    r"|\b[a-z-]+s\s+(?:always|never|all|usually|generally)\s+" + _PREFERENCE +
    r"|(?:^|[.;:!?]\s+)[a-z-]+s\s+" + _PREFERENCE,
    re.IGNORECASE)


def evidence_module():
    """The FG-2 evidence helper beside this script, sharing this module's error types."""
    sys.modules.setdefault('study', sys.modules[__name__])
    import evidence
    return evidence


def lifecycle_module():
    """The FG-3 lifecycle helper beside this script: pilot gates, host-backed ingestion and recovery."""
    evidence_module()
    import lifecycle
    return lifecycle


def report_module():
    """The FG-4 report helper beside this script: analysis inputs, synthesis, review binding and export."""
    lifecycle_module()
    import report
    return report


class StudyError(ValueError):
    def __init__(self, code, message, exit_code=2, data=None):
        super().__init__(message)
        self.code, self.exit_code, self.data = code, exit_code, data


def refuse(code, message, data=None):
    """A refusal or hold: valid input, but the requested action is not permitted now."""
    raise StudyError(code, message, 1, data)


def invalid(code, message):
    raise StudyError(code, message, 2)


def sha(value) -> str:
    return digest(canonical(value))


def load_json(path, label):
    try:
        return strict_load(_regular(Path(path)))
    except (OSError, JobError, ValueError) as exc:
        invalid('unreadable_input', f'{label} is not a readable JSON regular file: {exc}')


def parse_time(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?Z', value):
        invalid('invalid_time', f'{label} must be an ISO 8601 UTC time ending in Z')
    return dt.datetime.fromisoformat(value[:-1]).replace(tzinfo=dt.timezone.utc)


def utc_now(value=None):
    if value is not None:
        return parse_time(value, '--now')
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def text(value, label, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        invalid('invalid_plan', f'{label} must be a nonempty string')
    return value


def strings(value, label, minimum=0):
    if not isinstance(value, list) or len(value) < minimum or any(not isinstance(v, str) or not v.strip() for v in value):
        invalid('invalid_plan', f'{label} must be a list of at least {minimum} nonempty strings')
    return value


def safe_id(value, label):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        invalid('invalid_id', f'{label} must match {SAFE_ID.pattern}')
    return value


# ----------------------------------------------------------------------------- catalog


def catalog_index(capabilities):
    """Runnable (provider, model) entries from a saved orchestrator_capabilities response."""
    if isinstance(capabilities, dict) and isinstance(capabilities.get('response'), dict):
        capabilities = capabilities['response']
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get('providers'), list):
        invalid('capabilities_invalid', 'capabilities need a providers list from orchestrator_capabilities')
    index = {}
    for provider in capabilities['providers']:
        if not isinstance(provider, dict) or not isinstance(provider.get('providerInstanceId'), str):
            continue
        runnable = provider.get('canRunChildTask') is True
        for model in provider.get('models') or []:
            if not isinstance(model, dict) or not isinstance(model.get('id'), str):
                continue
            options = {}
            for option in model.get('options') if isinstance(model.get('options'), list) else []:
                if isinstance(option, dict) and isinstance(option.get('id'), str):
                    options[option['id']] = option_domain(option)
            index[(provider['providerInstanceId'], model['id'])] = {
                'providerInstanceId': provider['providerInstanceId'], 'model': model['id'],
                'driverKind': provider.get('driverKind', ''), 'runnable': runnable, 'options': options,
                'lineage': catalog_lineage(str(provider.get('driverKind', '')), model['id'])}
    return index


def option_domain(option):
    """{type, values} for one catalog option. `values` is None when the advertised domain is
    unusable: a select with no, empty or malformed choices, or a type this helper does not know."""
    kind = option.get('type')
    if kind == 'boolean':
        return {'type': kind, 'values': [False, True]}
    choices = option.get('options')
    if (kind == 'select' and isinstance(choices, list) and choices
            and all(isinstance(c, dict) and isinstance(c.get('id'), str) and c['id'] for c in choices)):
        return {'type': kind, 'values': sorted({c['id'] for c in choices})}
    return {'type': kind if isinstance(kind, str) else None, 'values': None}


def target_problem(target, index):
    """Why a requested target cannot run as written, or None. Never substitutes another target."""
    entry = index.get((target['providerInstanceId'], target['model']))
    if entry is None:
        return 'model_unavailable'
    if not entry['runnable']:
        return 'provider_unavailable'
    for key, value in target['options'].items():
        domain = entry['options'].get(key)
        if domain is None:
            return 'unsupported_option'
        if domain['values'] is None:
            return 'option_domain_unavailable'
        # A select takes one advertised string ID; a boolean takes JSON true or false.
        if (type(value) is not (bool if domain['type'] == 'boolean' else str)) or value not in domain['values']:
            return 'unsupported_option'
    return None


def normal_target(value, label):
    if not isinstance(value, dict) or set(value) - {'providerInstanceId', 'model', 'options'}:
        invalid('invalid_plan', f'{label} needs providerInstanceId, model and optional options only')
    options = value.get('options', {})
    if not isinstance(options, dict) or any(not isinstance(k, str) or not isinstance(v, (str, bool))
                                            for k, v in options.items()):
        invalid('invalid_plan', f'{label}.options must map option IDs to string (select) or boolean values')
    return {'providerInstanceId': text(value.get('providerInstanceId'), f'{label}.providerInstanceId'),
            'model': text(value.get('model'), f'{label}.model'), 'options': dict(sorted(options.items()))}


def target_key(target):
    return sha([target['providerInstanceId'], target['model'], target['options']])[:10]


def load_observations(path):
    """Coordinator-transcribed schema/catalog observations. They can say a capability is
    visible or absent before dispatch; only a pilot can verify it, so `verified` is refused."""
    if path is None:
        return []
    return observation_rows(load_json(path, 'observations'))


def observation_rows(rows):
    if not isinstance(rows, list):
        invalid('observations_invalid', 'observations must be a list')
    for row in rows:
        if (not isinstance(row, dict) or row.get('fact') not in FACTS or row.get('state') not in ('available', 'unavailable')
                or not isinstance(row.get('source'), str) or not row['source'].strip()
                or not isinstance(row.get('providerInstanceId'), (str, type(None)))):
            if isinstance(row, dict) and row.get('state') in ('verified', 'passed'):
                invalid('pilot_claim_before_pilot', 'a capability can only be verified by a pilot, not asserted in plan')
            invalid('observations_invalid', 'each observation needs fact, state available|unavailable, source and providerInstanceId')
    return rows


def fresh_catalog(path, now):
    """A pre-dispatch host observation: `{schema_version: 1, observed_at, source, response,
    observations?}`, where `response` is a freshly saved orchestrator_capabilities response and
    `observations` are schema facts read at the same time. run, resume, admission and job-spec
    recheck the approved plan against it; the coordinator (later, the host producer) supplies it."""
    raw = load_json(path, 'catalog observation')
    if (not isinstance(raw, dict) or raw.get('schema_version') != 1
            or set(raw) - {'schema_version', 'observed_at', 'source', 'response', 'observations'}
            or 'response' not in raw):
        invalid('observation_invalid', 'a catalog observation is {schema_version: 1, observed_at, source, response, '
                                       'observations?}')
    observed = parse_time(raw.get('observed_at'), 'observed_at')
    text(raw.get('source'), 'catalog observation source')
    if observed > now + CLOCK_SKEW:
        invalid('observation_invalid', 'the catalog observation is dated in the future')
    if now - observed > CATALOG_MAX_AGE:
        refuse('stale_observation', f'the catalog observation is older than {CATALOG_MAX_AGE}; save a fresh '
                                    'orchestrator_capabilities response', {'observed_at': stamp(observed)})
    return {'observed_at': stamp(observed), 'sha256': sha(raw), 'index': catalog_index(raw['response']),
            'observations': observation_rows(raw.get('observations', []))}


def fact_state(fact, provider, observations):
    rows = [r for r in observations if r['fact'] == fact and r.get('providerInstanceId') in (provider, None)]
    if any(r['state'] == 'unavailable' for r in rows):
        return {'state': 'unavailable', 'source': next(r['source'] for r in rows if r['state'] == 'unavailable')}
    if rows:
        return {'state': 'observed-before-pilot', 'source': rows[0]['source'], 'verified': False}
    return {'state': 'unknown-until-pilot', 'source': 'not observable in the catalog or tool schema', 'verified': False}


# ----------------------------------------------------------------------------- plan


def lint_persona(persona):
    for field in ('label', 'goal', 'experience'):
        if GROUP_CLAIM.search(persona[field]):
            return field
    for field in ('priorities', 'constraints'):
        if any(GROUP_CLAIM.search(item) for item in persona[field]):
            return field
    return None


def normalise(draft):
    """Validate an operator-editable draft and return its canonical material-bearing form."""
    if not isinstance(draft, dict) or draft.get('schema_version') != SCHEMA_VERSION:
        invalid('invalid_plan', 'draft must be an object with schema_version 1')
    allowed = {'schema_version', 'study_id', 'audience', 'decision', 'target', 'journeys', 'exclusions', 'personas',
               'participant_models', 'analysis', 'review', 'mode', 'capture_profile', 'prompts', 'stimulus',
               'sharing', 'limits', 'coverage_policy', 'journey_context'}
    if set(draft) - allowed:
        invalid('invalid_plan', f'unknown draft fields: {sorted(set(draft) - allowed)}')
    plan = {'schema_version': SCHEMA_VERSION, 'study_id': safe_id(draft.get('study_id'), 'study_id'),
            'audience': text(draft.get('audience'), 'audience'), 'decision': text(draft.get('decision'), 'decision')}
    target = draft.get('target')
    if not isinstance(target, dict) or target.get('kind') not in ('url', 'pack') or target.get('environment') not in ENVIRONMENTS:
        invalid('invalid_plan', f'target needs kind url|pack and environment {"|".join(ENVIRONMENTS)}')
    if target['kind'] == 'url' and not re.fullmatch(r'https?://\S+', str(target.get('url', ''))):
        invalid('invalid_plan', 'a url target needs an http(s) url')
    plan['target'] = {k: target[k] for k in ('kind', 'url', 'environment', 'label') if k in target}
    mode = draft.get('mode')
    if mode not in MODES:
        invalid('invalid_plan', f'mode must be one of {MODES}')
    if mode == 'combined' and target['kind'] != 'url':
        invalid('invalid_plan', 'combined mode requires a URL target; use capture-only for a supplied pack')
    plan['mode'] = mode
    journeys = draft.get('journeys', [])
    if not isinstance(journeys, list) or (mode == 'combined' and not journeys):
        invalid('invalid_plan', 'combined mode needs at least one journey')
    plan['journeys'] = []
    for i, journey in enumerate(journeys):
        if not isinstance(journey, dict) or set(journey) - {'id', 'goal', 'permitted_actions', 'excluded_actions'}:
            invalid('invalid_plan', f'journeys[{i}] needs id, goal, permitted_actions and optional excluded_actions')
        plan['journeys'].append({'id': safe_id(journey.get('id'), f'journeys[{i}].id'),
                                 'goal': text(journey.get('goal'), f'journeys[{i}].goal'),
                                 'permitted_actions': strings(journey.get('permitted_actions'), f'journeys[{i}].permitted_actions', 1),
                                 'excluded_actions': strings(journey.get('excluded_actions', []), f'journeys[{i}].excluded_actions')})
    if len({j['id'] for j in plan['journeys']}) != len(plan['journeys']):
        invalid('invalid_plan', 'journey IDs must be unique')
    plan['exclusions'] = strings(draft.get('exclusions', []), 'exclusions')
    plan['journey_context'] = normal_context(draft.get('journey_context'), mode)
    personas = draft.get('personas')
    if not isinstance(personas, list) or not personas:
        invalid('invalid_plan', 'at least one persona is required')
    plan['personas'] = []
    for i, persona in enumerate(personas):
        keys = {'id', 'label', 'goal', 'priorities', 'experience', 'constraints', 'invented'}
        if not isinstance(persona, dict) or set(persona) != keys:
            invalid('invalid_persona', f'personas[{i}] needs exactly {sorted(keys)}')
        if persona['invented'] is not True:
            invalid('invalid_persona', f'personas[{i}] must be marked invented: true; personas are not real people')
        row = {'id': safe_id(persona['id'], f'personas[{i}].id'), 'label': text(persona['label'], f'personas[{i}].label'),
               'goal': text(persona['goal'], f'personas[{i}].goal'),
               'priorities': strings(persona['priorities'], f'personas[{i}].priorities', 1),
               'experience': text(persona['experience'], f'personas[{i}].experience'),
               'constraints': strings(persona['constraints'], f'personas[{i}].constraints'), 'invented': True}
        field = lint_persona(row)
        if field:
            invalid('population_claim', f'personas[{i}].{field} generalises a preference to a whole group; '
                                        'describe one invented individual instead')
        plan['personas'].append(row)
    if len({p['id'] for p in plan['personas']}) != len(plan['personas']):
        invalid('invalid_persona', 'persona IDs must be unique')
    models = draft.get('participant_models')
    if not isinstance(models, list):
        invalid('invalid_plan', 'participant_models must be a list of targets')
    plan['participant_models'] = [normal_target(m, f'participant_models[{i}]') for i, m in enumerate(models)]
    if len({canonical(m) for m in plan['participant_models']}) != len(plan['participant_models']):
        invalid('invalid_plan', 'participant models must be distinct')
    if len({m['model'] for m in plan['participant_models']}) < 2:
        invalid('not_multi_model', 'a focus group needs at least two distinct catalog model IDs')
    for role in ('analysis', 'review'):
        plan[role] = normal_target(draft.get(role), role)
    profile = draft.get('capture_profile')
    viewport = profile.get('viewport') if isinstance(profile, dict) else None
    if (not isinstance(viewport, dict) or any(type(viewport.get(k)) is not int or not 0 < viewport[k] <= 10000
                                              for k in ('width', 'height'))):
        invalid('invalid_plan', 'capture_profile.viewport needs positive integer width and height')
    plan['capture_profile'] = {'label': text(profile.get('label', 'phone'), 'capture_profile.label'),
                               'viewport': {'width': viewport['width'], 'height': viewport['height']},
                               'extra_views': strings(profile.get('extra_views', []), 'capture_profile.extra_views')}
    prompts = draft.get('prompts')
    if not isinstance(prompts, dict):
        invalid('invalid_plan', 'prompts must be an object')
    plan['prompts'] = {'first_impression': text(prompts.get('first_impression'), 'prompts.first_impression')}
    if mode == 'combined':
        plan['prompts']['journey'] = text(prompts.get('journey'), 'prompts.journey')
    plan['stimulus'] = normal_stimulus(draft.get('stimulus'))
    plan['sharing'] = normal_sharing(draft.get('sharing'))
    plan['limits'] = normal_limits(draft.get('limits'))
    coverage = draft.get('coverage_policy', {'journey_gaps': 'report', 'capture_only_completes_combined': False})
    if (not isinstance(coverage, dict) or coverage.get('journey_gaps') != 'report'
            or coverage.get('capture_only_completes_combined') is not False):
        invalid('invalid_plan', 'coverage_policy reports journey gaps and never lets capture-only complete combined scope')
    plan['coverage_policy'] = {'journey_gaps': 'report', 'capture_only_completes_combined': False}
    return plan


def normal_stimulus(value):
    if not isinstance(value, dict) or not isinstance(value.get('files'), list) or not value['files']:
        invalid('invalid_plan', 'stimulus needs a nonempty files list')
    files = []
    for i, row in enumerate(value['files']):
        if (not isinstance(row, dict) or not isinstance(row.get('path'), str) or not Path(row['path']).is_absolute()
                or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('sha256', '')))):
            invalid('invalid_plan', f'stimulus.files[{i}] needs an absolute path and sha256')
        files.append({'name': text(row.get('name', Path(row['path']).name), f'stimulus.files[{i}].name'),
                      'path': row['path'], 'sha256': row['sha256']})
    if len({f['name'] for f in files}) != len(files):
        invalid('invalid_plan', 'stimulus file names must be unique')
    inspected = value.get('coordinator_inspected')
    if not isinstance(inspected, bool):
        invalid('invalid_plan', 'stimulus.coordinator_inspected must be true or false')
    out = {'files': sorted(files, key=lambda f: f['name']), 'coordinator_inspected': inspected}
    unknown = set(value) - {'files', 'coordinator_inspected', 'manifest_sha256', 'provenance'}
    if unknown:
        invalid('invalid_plan', f'unknown stimulus fields: {sorted(unknown)}')
    if 'manifest_sha256' in value:
        if not HEX64.fullmatch(str(value['manifest_sha256'])):
            invalid('invalid_plan', 'stimulus.manifest_sha256 must be a SHA-256')
        out['manifest_sha256'] = value['manifest_sha256']
    if 'provenance' in value:
        # Immutable capture provenance (context class and reference, freshness, requested/final URL,
        # status, timestamp...). The capture validator populates it; here it is opaque and hash-bound.
        if not isinstance(value['provenance'], dict) or not value['provenance']:
            invalid('invalid_plan', 'stimulus.provenance must be a nonempty object')
        out['provenance'] = value['provenance']
    return out


def normal_context(value, mode):
    """The browser context class every journey must run in. Recorded journeys bind to it. A
    capture-only revision has no journeys, so it records none (a supplied one is still checked)."""
    value = {'class': 'fresh-anonymous', 'reference': None} if value is None else value
    if not isinstance(value, dict) or set(value) != {'class', 'reference'} or value['class'] not in CONTEXT_CLASSES:
        invalid('invalid_plan', f'journey_context needs class {"|".join(CONTEXT_CLASSES)} and reference')
    if value['class'] == 'fresh-anonymous' and value['reference'] is not None:
        invalid('invalid_plan', 'a fresh-anonymous journey context has no shared reference')
    if value['class'] == 'preauthenticated-test':
        text(value['reference'], 'journey_context.reference')
    return {'class': value['class'], 'reference': value['reference']} if mode == 'combined' else None


def normal_sharing(value):
    if not isinstance(value, list):
        invalid('invalid_plan', 'sharing must list provider-instance grants')
    grants = []
    for i, row in enumerate(value):
        if (not isinstance(row, dict) or set(row) != {'providerInstanceId', 'consumers', 'material_classes'}
                or not isinstance(row['consumers'], list) or not set(row['consumers']) <= set(CONSUMERS)
                or not isinstance(row['material_classes'], list) or not set(row['material_classes']) <= set(MATERIAL_CLASSES)):
            invalid('invalid_sharing', f'sharing[{i}] needs providerInstanceId, consumers {CONSUMERS} and material_classes {MATERIAL_CLASSES}')
        grants.append({'providerInstanceId': text(row['providerInstanceId'], f'sharing[{i}].providerInstanceId'),
                       'consumers': sorted(set(row['consumers'])), 'material_classes': sorted(set(row['material_classes']))})
    return sorted(grants, key=canonical)


def normal_limits(value):
    if not isinstance(value, dict):
        invalid('invalid_limits', 'limits must be an object')
    out = {}
    for key, (low, high) in LIMIT_BOUNDS.items():
        if type(value.get(key)) is not int or not low <= value[key] <= high:
            invalid('invalid_limits', f'limits.{key} must be an integer from {low} to {high}')
        out[key] = value[key]
    out['deadline'] = value.get('deadline')
    parse_time(out['deadline'], 'limits.deadline')
    if type(value.get('hard_stop_required')) is not bool:
        invalid('invalid_limits', 'limits.hard_stop_required must be true or false')
    out['hard_stop_required'] = value['hard_stop_required']
    if set(value) - set(out):
        invalid('invalid_limits', f'unknown limits: {sorted(set(value) - set(out))}')
    return out


def cells(plan):
    """One cell is one persona/model assignment. The first cell of each model is its pilot."""
    out, piloted = [], set()
    for persona in plan['personas']:
        for target in plan['participant_models']:
            key = target_key(target)
            out.append({'cell_id': f"{persona['id']}--{key}", 'persona_id': persona['id'], 'target': target,
                        'pilot': key not in piloted})
            piloted.add(key)
    return out


def stages_for(mode):
    return ['first-impression', 'journey'] if mode == 'combined' else ['first-impression']


def required_classes(stage, mode):
    if stage == 'first-impression':
        return {'stimulus', 'persona'}
    if stage == 'journey':
        return {'stimulus', 'persona', 'participant-response'}
    base = {'stimulus', 'persona', 'participant-response'} | ({'journey-evidence'} if mode == 'combined' else set())
    return base | ({'analysis-report'} if stage == 'review' else set())


def granted(plan, provider, consumer):
    return set().union(*[set(g['material_classes']) for g in plan['sharing']
                         if g['providerInstanceId'] == provider and consumer in g['consumers']])


def sharing_gaps(plan):
    gaps = []
    needs = [(c['target']['providerInstanceId'], 'participant', stage) for c in cells(plan) for stage in stages_for(plan['mode'])]
    needs += [(plan['analysis']['providerInstanceId'], 'analysis', 'analysis'),
              (plan['review']['providerInstanceId'], 'review', 'review')]
    for provider, consumer, stage in sorted(set(needs)):
        missing = sorted(required_classes(stage, plan['mode']) - granted(plan, provider, consumer))
        if missing:
            gaps.append({'providerInstanceId': provider, 'consumer': consumer, 'stage': stage, 'missing': missing})
    return gaps


def arithmetic(plan):
    """Complete first-attempt and maximum task counts for the declared stage plan."""
    n = len(plan['personas']) * len(plan['participant_models'])
    participant_first = n * len(stages_for(plan['mode']))
    limits = plan['limits']
    first = participant_first + 2
    maximum = first + limits['participant_repairs'] + limits['analysis_repairs'] + limits['review_repairs']
    return {'cells': n, 'pilots': len(plan['participant_models']), 'pilots_included_in_cells': True,
            'participant_first_attempts': participant_first, 'analysis_first_attempts': 1, 'review_first_attempts': 1,
            'first_attempt_tasks': first, 'repair_pools': {k: limits[k] for k in POOLS.values()},
            'max_tasks': maximum,
            'unknown_dependent_tasks': n if plan['mode'] == 'combined' else 0,
            'capture_only_first_attempt_tasks': n + 2,
            'notes': ['A task ceiling is not a dollar cap; dollar cost is unavailable without fresh host evidence.',
                      'Counts are synthetic tasks, not a human sample size or independent model families.']}


def assess(plan, index, observations):
    """Catalog checks, diversity, independence, capability facts and the expected mode."""
    problems, limitations = [], []
    for label, target in ([(f'participant {t["model"]}', t) for t in plan['participant_models']] +
                          [('analysis', plan['analysis']), ('review', plan['review'])]):
        problem = target_problem(target, index)
        if problem:
            problems.append({'target': label, 'providerInstanceId': target['providerInstanceId'], 'model': target['model'],
                             'problem': problem})
    lineage_of = lambda t: (index.get((t['providerInstanceId'], t['model'])) or {}).get('lineage', 'unknown')
    lineages = sorted({lineage_of(t) for t in plan['participant_models']})
    if 'unknown' in lineages:
        diversity = 'lineage-unknown'
        limitations.append('At least one participant model has an unknown lineage; diversity is unverified.')
    elif len(lineages) == 1:
        diversity = 'single-lineage'
        limitations.append(f'Reduced diversity: every participant model is from the {lineages[0]} lineage. '
                           'These are different models, not independent model families.')
    else:
        diversity = 'multi-lineage'
    authors = sorted({lineage_of(plan['analysis'])})
    reviewer = lineage_of(plan['review'])
    if reviewer == 'unknown' or 'unknown' in authors:
        independence = 'unknown'
    elif reviewer in authors:
        independence = 'same-lineage'
    else:
        independence = 'distinct'
    if independence != 'distinct':
        limitations.append(f'Fidelity reviewer independence is {independence}; required review cannot be dispatched.')
    facts = {}
    for target in plan['participant_models']:
        provider = target['providerInstanceId']
        facts[target_key(target)] = {f: fact_state(f, provider, observations) for f in ('image_delivery', 'browser_tools', 'isolation')}
    hard_stop = fact_state('hard_stop', None, observations)
    gaps = sharing_gaps(plan)
    if problems or independence != 'distinct' or gaps:
        expected = 'blocked'
    elif plan['mode'] == 'capture-only':
        expected = 'capture-only'
    elif all('unavailable' in (row['browser_tools']['state'], row['isolation']['state']) for row in facts.values()):
        expected = 'capture-only'
        limitations.append('Journeys are unavailable for every model; only capture results are possible.')
    else:
        expected = 'combined'
        if any(row[f]['state'] != 'observed-before-pilot' for row in facts.values() for f in ('browser_tools', 'isolation')):
            limitations.append('Journey capability is unknown until each model pilot; journey tasks may become unavailable.')
    if any(row['image_delivery']['state'] != 'observed-before-pilot' for row in facts.values()):
        limitations.append('Image delivery is not catalog-observable; visual claims wait for pilot evidence.')
    if plan['limits']['hard_stop_required'] and hard_stop['state'] != 'observed-before-pilot':
        limitations.append('A hard runtime stop was requested but host support is not established; work needing it is held.')
    if not plan['stimulus']['coordinator_inspected']:
        limitations.append('The coordinator has not inspected the shared material; this revision cannot be approved.')
    return {'catalog_problems': problems, 'participant_lineages': lineages, 'diversity': diversity,
            'synthesis_author_lineages': authors, 'reviewer_lineage': reviewer, 'reviewer_independence': independence,
            'capabilities': facts, 'hard_stop': hard_stop, 'sharing_gaps': gaps, 'expected_mode': expected,
            'limitations': limitations,
            'dollar_cost': {'state': 'unavailable', 'reason': 'no fresh host cost evidence; a task cap is not a dollar cap'}}


def rehash_stimulus(plan):
    changed = []
    for row in plan['stimulus']['files']:
        try:
            actual = digest(_regular(Path(row['path'])))
        except (OSError, JobError):
            actual = None
        if actual != row['sha256']:
            changed.append({'name': row['name'], 'expected': row['sha256'], 'actual': actual})
    return changed


# ----------------------------------------------------------------------------- state


class Study:
    """Plugin records beside the generic job under the private job root."""

    def __init__(self, state_root, study_id):
        self.root = Path(state_root).expanduser().absolute()
        self.id = safe_id(study_id, 'study')
        self.job_dir = self.root / self.id
        self.dir = self.job_dir / 'focus-group'

    def exists(self):
        return (self.dir / 'current.json').is_file()

    def read(self, rel):
        try:
            return strict_load(_regular(self.dir / rel))
        except FileNotFoundError:
            return None
        except (OSError, JobError, ValueError) as exc:
            invalid('unsafe_state', f'study record {rel} is unreadable: {exc}')

    def require(self):
        if not self.exists():
            invalid('unknown_study', f'no focus-group study {self.id} under {self.root}')
        _reject_symlink_components(self.dir)
        return self.read('current.json')

    def plan(self, revision):
        record = self.read(f'plans/{revision}.json')
        if record is None or sha(record['plan']) != revision:
            invalid('unsafe_state', f'plan revision {revision} is missing or does not match its hash')
        return record

    def approvals(self, revision):
        """Append-only approvals of one revision: the first approval, then any amendments that
        cover a larger lifetime ceiling. Each record names its predecessor's hash."""
        folder = self.dir / 'approvals' / revision
        rows = []
        if folder.is_dir():
            for n, path in enumerate(sorted(folder.glob('*.json'))):
                record = self.read(f'approvals/{revision}/{path.name}')
                body = {k: v for k, v in record.items() if k != 'record_sha256'}
                if (path.name != f'{n:04d}.json' or record.get('record_sha256') != sha(body)
                        or record.get('sequence') != n or record.get('revision') != revision
                        or record.get('previous_record_sha256') != (rows[-1]['record_sha256'] if rows else None)):
                    invalid('unsafe_state', f'approval record {path.name} breaks the append-only approval history')
                rows.append(record)
        return rows

    def artifact_problem(self, record):
        """Reopen a result artifact now. None when it is the exact hashed regular file inside its task
        artifact scope, reached without symlinks; otherwise (code, reason)."""
        return self.artifact_bytes(record)[1]

    def artifact_bytes(self, record, max_bytes=16 * 1024 * 1024):
        """(bytes, None) for the exact hashed regular file inside the record's task artifact scope, read
        once without following symlinks; (None, (code, reason)) otherwise. Callers hash, parse and scan
        these same bytes, so nothing is checked on one read and consumed from another."""
        scope = self.job_dir / 'artifacts' / 'tasks' / record['task_id']
        path = Path(record['result']['path'])
        if not path.is_absolute():
            path = self.job_dir / path
        if not path.is_absolute() or '..' in path.parts or path == scope or not path.is_relative_to(scope):
            return None, ('out_of_scope_artifact', 'artifact is outside its task artifact scope')
        try:
            data = _regular(path, max_bytes=max_bytes)
        except FileNotFoundError:
            return None, ('missing_artifact', 'artifact is missing')
        except (OSError, JobError):
            try:
                info = os.lstat(path)
            except OSError:
                info = None
            if info is not None and stat.S_ISREG(info.st_mode) and info.st_size > max_bytes:
                return None, ('oversize_artifact', f'artifact exceeds the {max_bytes}-byte limit; it is refused '
                                                   'unscanned, never cleared')
            return None, ('out_of_scope_artifact', 'artifact is not a regular file reached without symlinks inside '
                                                   'its scope')
        if digest(data) != record['result']['sha256']:
            return None, ('hash_mismatch', 'artifact bytes do not match the accepted SHA-256')
        return data, None

    def ledger(self):
        return self.read('ledger.json') or {'schema_version': 1, 'charged': {}, 'requests': {}, 'slots': {},
                                            'cancel_requested': False, 'deadline_expired': False, 'catalog': None}

    def accepted(self):
        folder = self.dir / 'accepted'
        rows = []
        if folder.is_dir():
            for path in sorted(folder.glob('*.json')):
                record = self.read(f'accepted/{path.name}')
                body = {k: v for k, v in record.items() if k != 'record_sha256'}
                if record.get('record_sha256') != sha(body):
                    invalid('unsafe_state', f'accepted record {path.name} does not match its hash')
                rows.append(record)
        return rows

    @contextlib.contextmanager
    def locked(self):
        if fcntl is None:
            invalid('platform_unsupported', 'study mutations need fcntl file locking')
        _reject_symlink_components(self.root)
        for path in (self.root, self.job_dir, self.dir):
            path.mkdir(mode=0o700, exist_ok=True)
            if stat.S_IMODE(path.stat().st_mode) & 0o077:
                invalid('unsafe_state', f'{path} must be private (0700)')
        _reject_symlink_components(self.dir)
        fd = os.open(self.dir / 'study.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def write(self, rel, value):
        _atomic(self.dir / rel, canonical(value))

    def retain(self, rel, value, why):
        try:
            _retain(self.dir / rel, canonical(value), why)
        except JobError as exc:
            invalid('immutable_record', str(exc))


# ----------------------------------------------------------------------------- carry-forward


def bindings(plan, cell, stage, record=None):
    """Every input that a result at (cell, stage) depends on, for the given revision."""
    persona = next(p for p in plan['personas'] if p['id'] == cell['persona_id'])
    stimulus = plan['stimulus']
    # The pack binding covers the files, the capture manifest and its provenance. A first impression
    # judges those hash-bound images, so a journey-only change (target URL, environment, context)
    # leaves it valid; the capture source belongs in the provenance the capture validator records.
    base = {'stage': stage, 'cell_id': cell['cell_id'], 'persona_sha256': sha(persona),
            'prompt_sha256': sha(plan['prompts']['first_impression']),
            'pack_sha256': sha({'files': stimulus['files'], 'manifest_sha256': stimulus.get('manifest_sha256'),
                                'provenance': stimulus.get('provenance')}),
            'profile_sha256': sha(plan['capture_profile']), 'requested_target': cell['target']}
    if stage == 'journey':
        target = plan['target']
        base.update(journey_prompt_sha256=sha(plan['prompts'].get('journey')), journeys_sha256=sha(plan['journeys']),
                    action_scope_sha256=sha({'journeys': [[j['id'], j['permitted_actions'], j['excluded_actions']]
                                                          for j in plan['journeys']], 'exclusions': plan['exclusions'],
                                             'environment': target['environment']}),
                    journey_target_sha256=sha({'kind': target['kind'], 'url': target.get('url'),
                                               'environment': target['environment']}),
                    context_policy_sha256=sha(plan['journey_context']))
    return base


def attempt_keys(plan):
    """Slot -> input hash. Attempts carry across revisions only while the slot's inputs are unchanged."""
    keys = {f"{cell['cell_id']}:{stage}": sha(bindings(plan, cell, stage))
            for cell in cells(plan) for stage in stages_for(plan['mode'])}
    keys['analysis:analysis'] = sha({'target': plan['analysis'], 'prompts': plan['prompts'],
                                     'participants': sorted(keys.values())})
    keys['review:review'] = sha({'target': plan['review'], 'analysis': keys['analysis:analysis']})
    return {slot: f'{slot}@{key[:16]}' for slot, key in keys.items()}


def ceiling(plan, ledger):
    """Study-wide task ceiling for a revision: tasks already charged, first attempts this revision
    still needs and the unspent repair pools. Charging inside the revision leaves it unchanged."""
    needed = sum(1 for key in attempt_keys(plan).values() if not ledger['slots'].get(key))
    headroom = {pool: max(plan['limits'][pool] - ledger['charged'].get(pool, 0), 0) for pool in POOLS.values()}
    charged = sum(ledger['charged'].values())
    return {'charged_tasks': charged,'first_attempts_needed': needed, 'repair_headroom': headroom,
            'max_tasks': charged + needed + sum(headroom.values())}


def instruction(revision, limit):
    return f'Approve focus-group revision {revision[:12]} (ceiling {limit["max_tasks"]} tasks)'


def predecessor_record(record):
    """The accepted first-impression record a journey record was built on, or None."""
    rows = record.get('predecessor_records') or []
    return rows[0]['record_sha256'] if len(rows) == 1 else None


def record_problem(study, record, accepted=None):
    """(code, reason) when an accepted record cannot be used now: its artifact or bound material changed or no
    longer clears, a recorded tool trace shows its own execution was contaminated, or (for a journey) the exact
    first impression it was built on is missing or unusable. None otherwise. It is the shared evidence
    resolver's first problem; the record itself is never rewritten."""
    found = evidence_module().record_problems(study, record, accepted)
    return (found[0]['code'], found[0]['detail']) if found else None


def native_firsts(study, revision, accepted):
    """Cell -> (record, problem) for first impressions accepted in `revision` itself, with each
    artifact reopened and its trace state read now. A native result occupies its slot whatever its
    state; only one whose problem is None is a usable predecessor. Carry generation, validation and
    acceptance all resolve native predecessors here, so they cannot diverge."""
    return {r['cell_id']: (r, record_problem(study, r, accepted)) for r in accepted
            if (r['revision'], r['stage']) == (revision, 'first-impression')}


def mapping_for(study, target_revision):
    """Explicit carry-forward mapping from accepted prior results into a revision. A result accepted
    in the target revision itself occupies its slot first, so a prior result never carries over it,
    and a prior journey carries only when its exact predecessor is the slot's effective first
    impression in the target revision (native with a usable artifact, or carried by this mapping)."""
    plan = study.plan(target_revision)['plan']
    by_cell = {c['cell_id']: c for c in cells(plan)}
    stages = stages_for(plan['mode'])
    accepted = study.accepted()
    records = [r for r in accepted if r['revision'] != target_revision]
    native = {(r['cell_id'], r['stage']): {'record_sha256': r['record_sha256'], 'result_sha256': r['result']['sha256']}
              for r in accepted if r['revision'] == target_revision}
    for cell_id, (_, problem) in native_firsts(study, target_revision, accepted).items():
        native[(cell_id, 'first-impression')]['problem'] = problem
    lifecycle = lifecycle_module()
    job = lifecycle.load_job(study)
    entries, carried = [], dict(native)
    for record in sorted(records, key=lambda r: (STAGES.index(r['stage']), r['cell_id'], r['revision'])):
        entry = {'cell_id': record['cell_id'], 'stage': record['stage'], 'from_revision': record['revision'],
                 'result_sha256': record['result']['sha256'], 'record_sha256': record['record_sha256'], 'reasons': []}
        cell = by_cell.get(record['cell_id'])
        if record['stage'] not in ('first-impression', 'journey'):
            entry['reasons'].append('later-stage results are re-derived after any participant change')
        elif cell is None:
            entry['reasons'].append('cell is not in this revision (persona or model removed or changed)')
        elif record['stage'] not in stages:
            entry['reasons'].append('journey is outside this revision; capture-only never completes combined scope')
        else:
            problem = record_problem(study, record, accepted)
            if problem:
                entry['reasons'].append(f'accepted {problem[1]}')
            now = bindings(plan, cell, record['stage'])
            was = record['bindings']
            changed = sorted(k for k in set(now) | set(was) if k != 'predecessors' and now.get(k) != was.get(k))
            if changed:
                entry['reasons'].append('changed inputs: ' + ', '.join(changed))
            # Identity is read now, from the record's own request: a later host source naming another model
            # stops it carrying, whatever it was accepted with.
            if lifecycle.identity_state(study, record, job) != 'verified':
                entry['reasons'].append('observed model identity is not verified against the request')
            if record['stage'] == 'journey':
                prior = carried.get((record['cell_id'], 'first-impression'))
                if (not prior or record['bindings'].get('predecessors') != [prior['result_sha256']]
                        or predecessor_record(record) != prior['record_sha256']):
                    entry['reasons'].append("accepted first-impression predecessor is not this revision's effective "
                                            'first impression')
                elif prior.get('problem'):
                    entry['reasons'].append('accepted first-impression predecessor in this revision is unusable: '
                                            + prior['problem'][1])
                if not context_fits(record.get('context'), plan['journey_context']):
                    entry['reasons'].append("recorded browser context does not satisfy this revision's journey context")
            needed = {'participant-response'} | ({'journey-evidence'} if record['stage'] == 'journey' else set())
            forbidden = [c for c in ('analysis', 'review') if needed - granted(plan, plan[c]['providerInstanceId'], c)]
            if forbidden:
                entry['reasons'].append('current authority does not permit disclosure to ' + ', '.join(forbidden))
        if entry['reasons']:
            entry['status'] = 'stale'
        else:
            key = (record['cell_id'], record['stage'])
            if key in carried:
                entry['status'] = 'stale'
                entry['reasons'].append(('this revision has its own accepted result for this slot' if key in native else
                                         'another accepted result already fills this slot') + '; results are never pooled')
            else:
                entry['status'] = 'carried'
                entry['binding_sha256'] = sha(record['bindings'])
                carried[key] = entry
        entries.append(entry)
    return {'revision': target_revision, 'entries': entries,
            'filled_slots': sorted(f'{c}:{s}' for c, s in carried if (c, s) not in native),
            'combined_scope_complete': False if plan['mode'] == 'capture-only' else None}


def context_fits(recorded, policy):
    return (isinstance(recorded, dict) and isinstance(policy, dict) and recorded.get('class') == policy['class']
            and (policy['reference'] is None or recorded.get('reference') == policy['reference']))


MAPPING_KEYS = {'revision', 'entries', 'filled_slots', 'combined_scope_complete'}
ENTRY_KEYS = {'cell_id', 'stage', 'from_revision', 'result_sha256', 'record_sha256', 'reasons', 'status'}
ENTRY_IDENTITY = ('cell_id', 'stage', 'from_revision', 'result_sha256', 'record_sha256', 'status')


def validate_mapping(study, supplied):
    """Check a carry-forward mapping against freshly recomputed eligibility (which reopens every
    accepted artifact). Returns (errors, canonical mapping of the validated entries)."""
    if (not isinstance(supplied, dict) or set(supplied) != MAPPING_KEYS or not isinstance(supplied['entries'], list)
            or not isinstance(supplied['filled_slots'], list) or not isinstance(supplied['revision'], str)
            or not HEX64.fullmatch(supplied['revision'])):
        invalid('invalid_mapping', f'a mapping has exactly {sorted(MAPPING_KEYS)} with a plan revision hash')
    expected = mapping_for(study, supplied['revision'])
    want_by_record = {e['record_sha256']: e for e in expected['entries']}
    known = {r['record_sha256']: r for r in study.accepted()}
    errors, seen, valid, supplied_at = [], set(), set(), {}

    def fail(i, code, reason, **extra):
        errors.append({'entry': i, 'code': code, 'reason': reason, **extra})

    for i, entry in enumerate(supplied['entries']):
        status = entry.get('status') if isinstance(entry, dict) else None
        if (status not in ('carried', 'stale')
                or set(entry) != ENTRY_KEYS | ({'binding_sha256'} if status == 'carried' else set())
                or any(not isinstance(entry[k], str) for k in ENTRY_IDENTITY + (('binding_sha256',) if status == 'carried' else ()))
                or not isinstance(entry['reasons'], list)):
            fail(i, 'invalid_entry', 'not a carry-forward entry: unknown status or fields')
            continue
        record, want = known.get(entry['record_sha256']), want_by_record.get(entry['record_sha256'])
        slot = (entry['cell_id'], entry['stage'])
        if record is None or want is None or record['result']['sha256'] != entry['result_sha256']:
            fail(i, 'forged_completion', 'no matching accepted record')
        elif (record['cell_id'], record['stage']) != slot:
            fail(i, 'silent_pooling', 'record belongs to another cell or stage')
        elif status == 'stale':
            # A stale entry must be stale in the recomputed mapping too; otherwise the canonical mapping
            # would return it as carried without the caller having claimed it.
            if any(entry[k] != want[k] for k in ENTRY_IDENTITY):
                fail(i, 'provenance_mismatch', 'stale entry fields or status differ from the recomputed mapping')
            else:
                valid.add(entry['record_sha256'])
            continue
        elif slot in seen:
            fail(i, 'silent_pooling', 'two results map to one slot')
        elif want['status'] != 'carried':
            fail(i, 'ineligible_reuse', 'inputs changed, the artifact changed, authority forbids it or the slot is '
                                        'outside this revision', reasons=want['reasons'])
        elif entry['binding_sha256'] != want['binding_sha256']:
            fail(i, 'hash_mismatch', 'binding hash differs from the accepted record')
        elif entry != want:
            fail(i, 'provenance_mismatch', 'entry fields differ from the accepted record: '
                 + ', '.join(sorted(k for k in entry if entry[k] != want[k])))
        else:
            valid.add(entry['record_sha256'])
            supplied_at[entry['record_sha256']] = i
        seen.add(slot)
    # Predecessor closure on the returned subset: a carried journey needs its exact first impression
    # carried by this same validated mapping, or accepted in the target revision itself with a
    # usable artifact now.
    first = {cell_id: record['record_sha256'] for cell_id, (record, problem)
             in native_firsts(study, supplied['revision'], list(known.values())).items() if problem is None}
    first.update({e['cell_id']: e['record_sha256'] for e in expected['entries']
                  if e['record_sha256'] in valid and e['status'] == 'carried' and e['stage'] == 'first-impression'})
    for e in expected['entries']:
        if (e['record_sha256'] in valid and e['status'] == 'carried' and e['stage'] == 'journey'
                and predecessor_record(known[e['record_sha256']]) != first.get(e['cell_id'])):
            valid.discard(e['record_sha256'])
            fail(supplied_at[e['record_sha256']], 'predecessor_missing', 'a carried journey needs its accepted first '
                 'impression carried by this mapping or accepted in this revision')
    entries = [e for e in expected['entries'] if e['record_sha256'] in valid]
    filled = sorted(f"{e['cell_id']}:{e['stage']}" for e in entries if e['status'] == 'carried')
    if supplied['filled_slots'] != filled:
        fail(None, 'derived_mismatch', 'filled_slots differ from the validated carried entries')
    if supplied['combined_scope_complete'] is not expected['combined_scope_complete']:
        fail(None, 'derived_mismatch', 'combined_scope_complete differs from this revision')
    return errors, {'revision': supplied['revision'], 'entries': entries, 'filled_slots': filled,
                    'combined_scope_complete': expected['combined_scope_complete']}


def recorded_carry(study, revision):
    """The written carry mapping of a revision, revalidated now; None when none was written."""
    stored = study.read(f'carry/{revision}.json')
    if stored is None:
        return None
    errors, mapping = validate_mapping(study, stored)
    if errors:
        refuse('carry_invalid', 'the recorded carry-forward mapping no longer validates; plan a new revision',
               {'errors': errors})
    return mapping


def slot_filled(study, revision, slot, native=True):
    """Refuse dispatch or acceptance into a participant slot that accepted evidence already fills, so
    one slot never has two effective results. A slot an earlier revision's eligible result could fill
    is held until the revision's carry mapping is written, whichever command runs first."""
    cell_id, stage = slot.rsplit(':', 1)
    if native and any((r['revision'], r['cell_id'], r['stage']) == (revision, cell_id, stage) for r in study.accepted()):
        refuse('slot_already_filled', 'this revision already has an accepted result for this slot; it is not '
                                      'dispatched again')
    carried = recorded_carry(study, revision)
    if carried is not None:
        if slot in carried['filled_slots']:
            refuse('slot_already_filled', 'an accepted result is carried into this slot; it is not dispatched again')
    elif native and slot in mapping_for(study, revision)['filled_slots']:
        refuse('carry_unresolved', "an earlier revision's accepted result is eligible for this slot; write this "
                                   "revision's carry mapping (carry --write) before dispatch", {'slot': slot})


def effective_first(study, revision, cell_id, accepted):
    """The accepted first impression a journey in `revision` builds on: one accepted in this revision,
    or one carried into it by its validated mapping. The raw record is referenced, never copied."""
    native = native_firsts(study, revision, accepted).get(cell_id)
    rows = [(*native, 'native')] if native else []
    if not rows:
        mapping = recorded_carry(study, revision)
        known = {r['record_sha256']: r for r in accepted}
        rows = [(known[e['record_sha256']], record_problem(study, known[e['record_sha256']], accepted), 'carry')
                for e in (mapping or {}).get('entries', [])
                if e['status'] == 'carried' and (e['cell_id'], e['stage']) == (cell_id, 'first-impression')]
    out = []
    for record, problem, via in rows:
        if problem:
            # An accepted first impression without its frozen ingestion record was never frozen for use.
            refuse('first_impression_unfrozen' if problem[0] == 'evidence_record_missing' else 'predecessor_unusable',
                   f'the first impression this journey builds on is unusable: {problem[1]}')
        out.append({'revision': record['revision'], 'record_sha256': record['record_sha256'],
                    'result_sha256': record['result']['sha256'], 'via': via})
    return out


# ----------------------------------------------------------------------------- operations


# Every file the entry, playbooks and helpers name, plus the generic job runtime they run on. Worker definitions
# and shared worker contracts are added from plugin.json.
REQUIRED_FILES = (
    'plugin.json', 'entry.md', 'playbooks/plan.md', 'playbooks/run.md', 'playbooks/capture.md', 'playbooks/journeys.md',
    'references/study-contract.md', 'references/evidence-contract.md', 'references/report-contract.md',
    'scripts/study.py', 'scripts/evidence.py', 'scripts/lifecycle.py', 'scripts/report.py', 'scripts/validate_study.py',
    'templates/study-draft.example.json', 'templates/capture-manifest.example.json',
    'shared/t3-runtime.md', 'shared/delegation.md', 'shared/job-coordination.md', 'shared/job_cli.py',
    'shared/job_acceptance_cli.py', 'shared/job_acceptance.py', 'shared/lineage.py', 'shared/worker_registry.py',
    'core/jobs/__init__.py', 'core/jobs/results.py', 'core/jobs/store.py')


def package_files():
    """Whether each required file is present (and, for JSON, parses). shared/ and core/ resolve beside an
    installed package, or at the root of a source checkout."""
    try:
        meta = json.loads((PKG / 'plugin.json').read_text(encoding='utf-8'))
        extra = [w['path'] for w in meta['workers']] + [f'shared/agents/{name}' for name in meta['worker_shared']]
    except (OSError, ValueError, KeyError, TypeError):
        extra = []
    found = {}
    for rel in (*REQUIRED_FILES, *extra):
        path = (RUNTIME if rel.split('/', 1)[0] in ('shared', 'core') else PKG) / rel
        present = path.is_file() and not path.is_symlink()
        if present and rel.endswith('.json'):
            try:
                json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                present = False
        found[rel] = present
    return found


def package_integrity():
    """An installed package is checked against its install receipt: the package digest, every owned file (nothing
    missing, changed or unlisted), the external worker bundle, each declared worker in it, and this prefix's
    ownership claim. A source checkout has no receipt; its files are checked by `package_files` only."""
    receipt = PKG / 'install-manifest.json'
    if not receipt.exists():
        if RUNTIME == PKG:
            return {'state': 'failed', 'problems': ['missing install receipt for the bundled runtime']}
        return {'state': 'source-checkout', 'detail': 'no install receipt: integrity is checked on an installed package'}
    from shared import worker_registry as registry
    problems, manifest = [], {}
    try:
        loaded = json.loads(registry.read_regular(receipt, 'install receipt').decode('utf-8'))
        if not isinstance(loaded, dict) or loaded.get('plugin') != PKG.parent.name or loaded.get('version') != PKG.name:
            raise registry.RegistryError('install receipt does not name this plugin version directory')
        manifest = loaded
        if registry.package_digest(manifest) != manifest.get('package_digest'):
            problems.append('package digest does not match the install receipt')
        registry.verify_package_files(PKG, manifest)
        if not manifest.get('bundle_dir'):
            raise registry.RegistryError('worker bundle is missing from the install receipt')
        bundle = registry.verify_bundle(Path(manifest['bundle_dir']), manifest.get('installation_id'), PKG.parent.name,
                                        PKG.name, manifest.get('package_digest'))
        if bundle['bundle_digest'] != manifest.get('bundle_digest'):
            problems.append('worker bundle digest does not match the install receipt')
        workers = {a.get('id') for a in bundle['manifest']['assets'] if isinstance(a, dict)}
        declared = {w['id'] for w in json.loads((PKG / 'plugin.json').read_text(encoding='utf-8'))['workers']}
        if not declared <= workers:
            problems.append('worker bundle lacks declared workers: ' + ', '.join(sorted(declared - workers)))
        registry.assert_owned_locator(Path(manifest.get('agents_root', '')), manifest.get('installation_id'),
                                      PKG.parent.parent)
    except (registry.RegistryError, OSError, ValueError, KeyError, TypeError) as exc:
        problems.append(str(exc))
    return {'state': 'failed' if problems else 'verified', 'problems': problems,
            'package_digest': manifest.get('package_digest'), 'bundle_digest': manifest.get('bundle_digest')}


def op_doctor(args):
    report = {'python': '.'.join(map(str, sys.version_info[:3])), 'python_supported': sys.version_info >= (3, 10),
              'package_files': package_files(), 'package_integrity': package_integrity(),
              'writes': 'none: doctor reads files and creates no study, job or task',
              'dollar_cost': 'unavailable without fresh host evidence'}
    if args.capabilities is None:
        report['catalog'] = 'not supplied: save orchestrator_capabilities and pass --capabilities'
    else:
        index = catalog_index(load_json(args.capabilities, 'capabilities'))
        observations = load_observations(args.observations)
        runnable = [e for e in index.values() if e['runnable']]
        by_lineage = {}
        for entry in runnable:
            by_lineage.setdefault(entry['lineage'], []).append({'providerInstanceId': entry['providerInstanceId'],
                                                                'model': entry['model']})
        known = [k for k in by_lineage if k != 'unknown']
        report['catalog'] = {'runnable_models': len(runnable), 'lineages': by_lineage,
                             'suggested_panel_possible': len(known) >= SUGGESTED_LINEAGES,
                             'independent_reviewer_possible': len(known) >= 2,
                             'capabilities': {e['providerInstanceId']: {f: fact_state(f, e['providerInstanceId'], observations)
                                                                        for f in ('image_delivery', 'browser_tools', 'isolation')}
                                              for e in runnable},
                             'hard_stop': fact_state('hard_stop', None, observations)}
    ok = (report['python_supported'] and all(report['package_files'].values())
          and report['package_integrity']['state'] != 'failed')
    return (0 if ok else 1), report


def op_suggest(args):
    draft = load_json(args.input, 'draft')
    index = catalog_index(load_json(args.capabilities, 'capabilities'))
    if not isinstance(draft, dict):
        invalid('invalid_plan', 'draft must be an object')
    out = copy.deepcopy(draft)
    notes = []
    if not draft.get('participant_models'):
        first = {}
        for entry in index.values():
            if entry['runnable'] and entry['lineage'] != 'unknown':
                first.setdefault(entry['lineage'], entry)
        if len(first) < SUGGESTED_LINEAGES:
            refuse('insufficient_lineages', 'the catalog lists fewer than two known runnable lineages; '
                                            'choose a multi-model matrix explicitly and accept its reduced diversity',
                   {'lineages': sorted(first)})
        picked = list(first.values())[:SUGGESTED_LINEAGES]
        out['participant_models'] = [{'providerInstanceId': e['providerInstanceId'], 'model': e['model'], 'options': {}}
                                     for e in picked]
        notes.append(f'participant models: first runnable model of the first {SUGGESTED_LINEAGES} catalog lineages')
    lineage_of = lambda t: (index.get((t['providerInstanceId'], t['model'])) or {}).get('lineage', 'unknown')
    if not draft.get('analysis'):
        out['analysis'] = copy.deepcopy(out['participant_models'][0])
        notes.append('analysis: the first participant model')
    if not draft.get('review'):
        authors = lineage_of(out['analysis'])
        candidates = [e for e in index.values() if e['runnable'] and e['lineage'] not in ('unknown', authors)]
        if not candidates:
            refuse('reviewer_unavailable', 'no runnable catalog model has a known lineage distinct from the analyst',
                   {'analysis_lineage': authors})
        out['review'] = {'providerInstanceId': candidates[0]['providerInstanceId'], 'model': candidates[0]['model'],
                         'options': {}}
        notes.append('review: first runnable model of a lineage distinct from the analyst')
    if len(out.get('personas') or []) != SUGGESTED_PERSONAS:
        notes.append(f'the suggested starting panel has {SUGGESTED_PERSONAS} personas; the operator may change it')
    return 0, {'draft': out, 'notes': notes, 'writes': 'none'}


def presentation(plan, revision, assessment, ledger, approval, carry=None):
    counts = arithmetic(plan)
    limit = ceiling(plan, ledger)
    charged = sum(ledger['charged'].values())
    view = {'revision': revision, 'study_id': plan['study_id'], 'mode': plan['mode'],
            'expected_mode': assessment['expected_mode'],
            'cells': [{'cell_id': c['cell_id'], 'persona': c['persona_id'], 'pilot': c['pilot'], **c['target']}
                      for c in cells(plan)],
            'analysis': plan['analysis'], 'review': plan['review'], 'task_counts': counts, 'ceiling': limit,
            'charged_tasks': charged, 'remaining_tasks': max(limit['max_tasks'] - charged, 0),
            'limits': plan['limits'], 'sharing': plan['sharing'], 'assessment': assessment,
            'approval': approval, 'stimulus': [{'name': f['name'], 'sha256': f['sha256']} for f in plan['stimulus']['files']],
            'approval_instruction': instruction(revision, limit)}
    if carry is not None:
        view['carry_forward'] = carry
    return view


def op_plan(args):
    plan = normalise(load_json(args.input, 'draft'))
    if plan['study_id'] != args.study:
        invalid('study_mismatch', 'draft study_id differs from --study')
    changed = rehash_stimulus(plan)
    if changed:
        refuse('stimulus_changed', 'shared material differs from its declared hashes; recapture or re-inspect it',
               {'changed': changed})
    index = catalog_index(load_json(args.capabilities, 'capabilities'))
    assessment = assess(plan, index, load_observations(args.observations))
    if assessment['catalog_problems']:
        refuse('matrix_unavailable', 'a requested model, provider or option is unavailable; the matrix is never changed '
                                     'silently', {'problems': assessment['catalog_problems']})
    revision = sha(plan)
    study = Study(args.state_root, args.study)
    for problem in evidence_module().pack_gate(study, plan):
        assessment['limitations'].append(f'Shared material cannot be approved yet ({problem["code"]}): '
                                         f'{problem["detail"]}.')
    with study.locked():
        study.retain(f'plans/{revision}.json', {'schema_version': 1, 'plan': plan}, 'plan revision changed')
        study.write(f'assessments/{revision}.json', assessment)
        current = study.read('current.json') or {'schema_version': 1, 'history': []}
        previous = current.get('revision')
        if previous != revision:
            current = {'schema_version': 1, 'revision': revision,
                       'history': current['history'] + ([previous] if previous else [])}
            study.write('current.json', current)
        ledger = study.ledger()
        approval = approval_state(study.approvals(revision), revision, ceiling(plan, ledger))
        carry = mapping_for(study, revision) if current['history'] else None
        budget = None
        if previous and previous != revision:
            old = study.plan(previous)['plan']['limits']
            raised = sorted(k for k in POOLS.values() if plan['limits'][k] > old[k])
            budget = {'raised_pools': raised, 'charged_counters_retained': ledger['charged'],
                      'needs_explicit_authority': bool(raised)}
    view = presentation(plan, revision, assessment, ledger, approval, carry)
    if budget is not None:
        view['budget_change'] = budget
    view['dispatched'] = 0
    return 0, view


def approval_state(records, revision, limit):
    """The owner's authority for a revision. Every approval is retained; the latest one is in force
    and covers at most its recorded lifetime ceiling. When the study's ceiling for this revision
    has grown past it (charges made under another revision count), the approval is insufficient
    until an amendment that names the new ceiling is recorded."""
    if not records:
        return {'state': 'unapproved', 'revision': revision, 'required_max_tasks': limit['max_tasks'],
                'instruction': instruction(revision, limit)}
    last = records[-1]
    approved = last['scope']['max_tasks']
    state = 'approved' if limit['max_tasks'] <= approved else 'insufficient'
    out = {'state': state, 'revision': revision, 'message_ref': last['message_ref'], 'statement': last['statement'],
           'approved_max_tasks': approved, 'required_max_tasks': limit['max_tasks'],
           'history': [{'sequence': r['sequence'], 'kind': r['kind'], 'message_ref': r['message_ref'],
                        'max_tasks': r['scope']['max_tasks'], 'record_sha256': r['record_sha256']} for r in records]}
    if state == 'insufficient':
        out['instruction'] = instruction(revision, limit)
    return out


APPROVAL_LABEL = re.compile(r'(?:selected option|answer|reply)\s*:(.*)', re.IGNORECASE)


def affirmative(statement, raw, expected):
    """The statement must be exactly the approving instruction, and the saved owner source must be a
    single-answer record: one nonblank line that is the instruction, either alone or after a picker
    label (Selected option:, Answer:, Reply:). Any other content (a question, an option list, a second
    answer, a condition or a cancellation) is refused rather than interpreted: the helper does not
    guess which part of a longer transcript is the owner's authority."""
    if statement.strip() != expected:
        refuse('approval_scope_mismatch', 'the statement must be exactly the approving instruction for this revision '
                                          'and its task ceiling', {'expected': expected})
    lines = [line.strip() for line in raw.decode('utf-8', 'replace').splitlines() if line.strip()]
    labelled = [line for line in lines if APPROVAL_LABEL.fullmatch(line)]
    if len(labelled) > 1:
        refuse('approval_ambiguous', 'the source carries more than one labelled answer',
               {'labelled_answers': len(labelled)})
    if labelled:
        if APPROVAL_LABEL.fullmatch(labelled[0]).group(1).strip().rstrip('.') != expected:
            refuse('approval_not_affirmative', 'the selected answer is not the approving instruction; a listed '
                                               'option, rejection or qualified answer is not approval')
    elif not any(line.rstrip('.') == expected for line in lines):
        refuse('approval_not_affirmative', 'the source does not contain the instruction as an answer; a quoted, '
                                           'negated or qualified mention is not approval')
    if len(lines) != 1:
        refuse('approval_ambiguous', 'the source must be the single answer alone (the instruction, optionally after '
                                     'a Selected option:, Answer: or Reply: label); other content such as a question, '
                                     'option list, condition or cancellation is not interpreted',
               {'lines': len(lines)})


def op_approve(args):
    study = Study(args.state_root, args.study)
    current = study.require()
    request = load_json(args.input, 'approval')
    if not isinstance(request, dict) or set(request) != {'revision', 'message_ref', 'statement', 'source', 'source_sha256'}:
        invalid('invalid_approval', 'approval needs revision, message_ref, statement, source and source_sha256')
    revision = request['revision']
    if revision != current['revision']:
        refuse('stale_revision', 'approval names a revision that is not the current plan')
    plan = study.plan(revision)['plan']
    source = Path(text(request['source'], 'source'))
    if not source.is_absolute() or source.resolve().is_relative_to(study.job_dir.resolve()):
        invalid('invalid_approval', 'the owner statement source must be an absolute file outside the job directory')
    try:
        raw = _regular(source)
    except (OSError, JobError) as exc:
        invalid('invalid_approval', f'owner statement source is unreadable: {exc}')
    statement = text(request['statement'], 'statement')
    message_ref = text(request['message_ref'], 'message_ref')
    if digest(raw) != request['source_sha256'] or statement not in raw.decode('utf-8', 'replace'):
        invalid('invalid_approval', 'statement must occur verbatim in the source file with the recorded SHA-256')
    if not plan['stimulus']['coordinator_inspected']:
        refuse('stimulus_uninspected', 'the coordinator must inspect the shared material before approval')
    assessment = study.read(f'assessments/{revision}.json')
    if assessment['expected_mode'] == 'blocked':
        refuse('plan_blocked', 'this revision cannot run as planned; revise it first',
               {k: assessment[k] for k in ('catalog_problems', 'reviewer_independence', 'sharing_gaps')})
    gaps = sharing_gaps(plan)
    if gaps:
        refuse('sharing_incomplete', 'sharing authority does not cover every planned consumer', {'gaps': gaps})
    changed = rehash_stimulus(plan)
    if changed:
        refuse('stimulus_changed', 'shared material changed after planning', {'changed': changed})
    # The pack is created or validated during plan, before its hashes are approved: a recorded,
    # cleared verdict whose files, provenance and common profile match this revision exactly.
    evidence_module().require_pack(study, plan)
    with study.locked():
        ledger = study.ledger()
        limit = ceiling(plan, ledger)
        affirmative(statement, raw, instruction(revision, limit))
        records = study.approvals(revision)
        if records and approval_state(records, revision, limit)['state'] == 'approved':
            last = records[-1]
            if (last['message_ref'], last['statement'], last['source_sha256']) == (message_ref, statement,
                                                                                    request['source_sha256']):
                return 0, {'approval': approval_state(records, revision, limit), 'duplicate': True, 'dispatched': 0}
            refuse('already_approved', 'the approval in force already covers this revision and ceiling')
        record = {'schema_version': 1, 'revision': revision, 'sequence': len(records),
                  'kind': 'amendment' if records else 'approval',
                  'previous_record_sha256': records[-1]['record_sha256'] if records else None,
                  'message_ref': message_ref, 'statement': statement, 'source': str(source),
                  'source_sha256': request['source_sha256'],
                  'scope': {'actions': ['run', 'resume'], 'max_tasks': limit['max_tasks'], 'sharing': plan['sharing'],
                            'charged_at_approval': sum(ledger['charged'].values())}}
        record['record_sha256'] = sha(record)
        study.retain(f'approvals/{revision}/{len(records):04d}.json', record, 'approval history changed concurrently')
        records.append(record)
    return 0, {'approval': approval_state(records, revision, limit), 'duplicate': False, 'dispatched': 0}


def observe(study, plan, ledger, catalog):
    """Recheck the approved plan against a fresh host observation and record the verdict. An
    observation older than the newest recorded one is refused, so a failed refresh cannot be
    bypassed by replaying an earlier passing one."""
    seen = ledger.get('catalog')
    if seen and (catalog['observed_at'] < seen['observed_at']
                 or (catalog['observed_at'] == seen['observed_at'] and catalog['sha256'] != seen['sha256'])):
        refuse('stale_observation', 'a newer catalog observation is already recorded; save a fresh one',
               {'recorded_observed_at': seen['observed_at']})
    assessment = assess(plan, catalog['index'], catalog['observations'])
    ready = not assessment['catalog_problems'] and assessment['reviewer_independence'] == 'distinct'
    ledger['catalog'] = {'observed_at': catalog['observed_at'], 'sha256': catalog['sha256'], 'ready': ready,
                         'catalog_problems': assessment['catalog_problems'],
                         'reviewer_independence': assessment['reviewer_independence']}
    study.write('ledger.json', ledger)
    if not ready:
        refuse('readiness_stale', 'the fresh catalog no longer supports the approved plan exactly; revise it',
               {'catalog_problems': assessment['catalog_problems'],
                'reviewer_independence': assessment['reviewer_independence']})
    return assessment


def preflight(study, now, catalog):
    """Conditions every run, resume or dispatch must meet. The caller holds the study lock."""
    current = study.require()
    revision = current['revision']
    plan = study.plan(revision)['plan']
    ledger = study.ledger()
    if ledger['cancel_requested']:
        refuse('study_cancelled', 'cancellation was requested; no new task may start')
    approval = approval_state(study.approvals(revision), revision, ceiling(plan, ledger))
    if approval['state'] == 'unapproved':
        refuse('unapproved_revision', 'the current plan revision has no matching owner approval',
               {'revision': revision, 'instruction': approval['instruction']})
    if approval['state'] == 'insufficient':
        refuse('approval_insufficient', 'the approval in force covers fewer lifetime tasks than this revision now needs; '
                                        'record an amendment that names the new ceiling',
               {key: approval[key] for key in ('approved_max_tasks', 'required_max_tasks', 'instruction')})
    changed = rehash_stimulus(plan)
    if changed:
        refuse('inputs_changed', 'approved material changed; plan a new revision and obtain matching authority',
               {'changed': changed})
    evidence_module().require_pack(study, plan)
    if now >= parse_time(plan['limits']['deadline'], 'deadline'):
        refuse('deadline_passed', 'the study deadline has passed; no new task starts')
    # A written carry mapping is revalidated against current artifacts, native predecessors included;
    # one that no longer holds is never reported ready.
    recorded_carry(study, revision)
    assessment = observe(study, plan, ledger, catalog)
    if plan['limits']['hard_stop_required'] and assessment['hard_stop']['state'] != 'observed-before-pilot':
        refuse('hard_stop_unsupported', 'a hard runtime stop was promised but host support is not established; '
                                        'work that needs it is held')
    # Updating the study plan does not update the generic job: until its stage contracts and authority name
    # this revision, nothing is reported ready, admitted or charged.
    lifecycle = lifecycle_module()
    stale = lifecycle.job_revision_problem(lifecycle.load_job(study), revision)
    if stale:
        refuse('job_revision_stale', 'the generic job still prepares an earlier study revision; record '
                                     'lifecycle.py job-revision (job_cli.py decision and plan-revision) first', stale)
    return revision, plan, ledger, approval, assessment


def op_check_run(args):
    study = Study(args.state_root, args.study)
    now = utc_now(args.now)
    catalog = fresh_catalog(args.capabilities, now)
    with study.locked():
        revision, plan, ledger, approval, _ = preflight(study, now, catalog)
    return 0, {'revision': revision, 'ready': True, 'charged_tasks': sum(ledger['charged'].values()),
               'max_tasks': ceiling(plan, ledger)['max_tasks'], 'approved_max_tasks': approval['approved_max_tasks'],
               'catalog_observed_at': catalog['observed_at'], 'dispatched': 0}


def op_admit(args):
    """Charge one task launch inside the approved revision, matrix, sharing and budget."""
    study = Study(args.state_root, args.study)
    request = load_json(args.input, 'admission request')
    keys = {'revision', 'request_id', 'stage', 'cell_id', 'target', 'material_classes', 'purpose'}
    if not isinstance(request, dict) or set(request) != keys:
        invalid('invalid_admission', f'admission needs exactly {sorted(keys)}')
    now = utc_now(args.now)
    catalog = fresh_catalog(args.capabilities, now)
    with study.locked():
        return admission(study, request, now, catalog)


def admission(study, request, now, catalog, charge=True):
    """Every admission check, then the charge. The caller holds the study lock. `charge=False` is the dry
    run `lifecycle.py resume` uses to report which slots are dispatchable; it writes no charge."""
    revision, plan, ledger, approval, assessment = preflight(study, now, catalog)
    request_id = safe_id(request['request_id'], 'request_id')
    prior = ledger['requests'].get(request_id)
    if prior is not None and prior['request_sha256'] != sha(request):
        refuse('request_conflict', 'this request ID was admitted with different inputs')
    if request['revision'] != revision:
        if prior is not None:
            # Admitted under a revision that is no longer the approved plan: never a new launch
            # permission. Reconcile it from the host's task status and release it.
            refuse('superseded_revision', 'this request was admitted under a superseded revision; it may not be '
                                          'launched now. Reconcile it with task_status and release it',
                   {'request_id': request_id, 'request_revision': request['revision'], 'current_revision': revision,
                    'request_state': prior['state'], 'charged': False})
        refuse('unapproved_revision', 'the request names a revision other than the approved current plan')
    stage = request['stage']
    if stage not in STAGES:
        invalid('invalid_admission', f'stage must be one of {STAGES}')
    if stage == 'journey' and plan['mode'] != 'combined':
        refuse('outside_matrix', 'a capture-only revision declares no journeys')
    kind = STAGE_KIND[stage]
    target = normal_target(request['target'], 'target')
    if kind == 'participant':
        cell = next((c for c in cells(plan) if c['cell_id'] == request['cell_id']), None)
        if cell is None or cell['target'] != target:
            refuse('outside_matrix', 'the cell or its target is not in the approved matrix')
        slot = f"{cell['cell_id']}:{stage}"
    else:
        if request['cell_id'] is not None or target != plan[kind]:
            refuse('outside_matrix', f'the {kind} target differs from the approved plan')
        slot = f'{kind}:{stage}'
    if stage == 'journey':
        facts = assessment['capabilities'][target_key(target)]
        if 'unavailable' in (facts['browser_tools']['state'], facts['isolation']['state']):
            refuse('journey_unavailable', 'the fresh observation shows no browser tools or isolation for this model; '
                                          'its journeys are gaps', {'capabilities': facts})
    classes = request['material_classes']
    if not isinstance(classes, list) or not set(classes) <= set(MATERIAL_CLASSES):
        invalid('invalid_admission', f'material_classes must be drawn from {MATERIAL_CLASSES}')
    allowed = granted(plan, target['providerInstanceId'], kind)
    undisclosed = sorted((set(classes) | required_classes(stage, plan['mode'])) - allowed)
    if undisclosed:
        refuse('sharing_not_authorised', f'{target["providerInstanceId"]} may not receive {undisclosed} as {kind} input',
               {'missing': undisclosed})
    if kind == 'participant':
        slot_filled(study, revision, slot)
    if stage == 'journey':
        # A journey never launches on a first impression whose artifact is unusable now, and never
        # before its own current brief exists: an unbriefable journey is refused uncharged (FG2-F1).
        effective_first(study, revision, cell['cell_id'], study.accepted())
        lifecycle_module().require_journey_brief(study, plan, revision, cell)
    lifecycle = lifecycle_module()
    if prior is not None:
        if prior['state'] != 'open':
            refuse('request_closed', 'this request is already terminal or being cancelled; a new attempt needs a '
                                     'new request ID', {'request_id': request_id, 'request_state': prior['state']})
        # The admission charge and reservation are idempotent; permission to start is not. A request the host
        # already started is reconciled, never started again. One with no recorded host task (never prepared,
        # or prepared with a lost response) may start only while its pilot still passes and capacity is free.
        job = lifecycle.load_job(study)
        if lifecycle.host_started(job, request_id):
            return 0, {'admitted': True, 'duplicate': True, 'charged': False, 'request_id': request_id,
                       'host_started': True, 'next': 'already started: reconcile it from task_status; never '
                                                     'dispatch it again'}
        held = {'request_id': request_id, 'request_state': 'open', 'charged': False}
        if kind == 'participant':
            lifecycle.pilot_gate(study, plan, revision, cell, stage, dict(held, next=lifecycle.HELD))
        # The same occupancy as a new admission, less this request's own reservation, counted once.
        hold = lifecycle.capacity_hold(lifecycle.occupied_work(lifecycle.reconcile_view(study, plan, ledger, job, None)),
                                       plan['limits']['max_concurrency'], request_id)
        if hold:
            refuse('concurrency_limit', 'the approved concurrency limit is filled by other owned work; this request '
                                        'keeps its charge and reservation and waits for a completion',
                   dict(hold, **held, next=lifecycle.FULL))
        return 0, {'admitted': True, 'duplicate': True, 'charged': False, 'request_id': request_id,
                   'host_started': False}
    if kind == 'participant':
        # Each model's pilot cell gates that model's remaining cells, separately per stage.
        lifecycle.pilot_gate(study, plan, revision, cell, stage)
    job = lifecycle.load_job(study)
    problem = lifecycle.slot_contract_problem(study, job, revision, plan, stage, cell if kind == 'participant' else None)
    if problem:
        refuse(problem[0], problem[1], {'next': 'lifecycle.py job-revision, then job_cli.py decision and plan-revision'})
    # Occupied concurrency counts each distinct unresolved owned host task (a handle, or a retained conflicting
    # one, even for a request closed earlier) and a reservation for each live request without a host task.
    occupied = lifecycle.occupied_work(lifecycle.reconcile_view(study, plan, ledger, job, None))
    if occupied['count'] >= plan['limits']['max_concurrency']:
        refuse('concurrency_limit', 'the approved concurrency limit is reached; wait for a completion',
               {'occupied': occupied['requests'], 'occupied_count': occupied['count'],
                'occupied_work': occupied['work']})
    # Once a job records dispatch, a new request never starts beside an unsettled one for the same slot: the running
    # or cancelling attempt is reconciled from the host first, and only then can the job's charged retry replace it.
    live = sorted(rid for rid, row in ledger['requests'].items()
                  if row['slot'] == slot and row['state'] in ('open', 'cancel-requested')) if job is not None else []
    if live:
        refuse('slot_in_flight', 'this slot already has owned work that is not settled; reconcile it from task_status '
                                 'and never start a second attempt beside it', {'slot': slot, 'requests': live,
                                                                                'charged': False})
    # Attempts are counted per slot input hash: changed inputs start a fresh first attempt,
    # unchanged inputs keep their count across revisions.
    key = attempt_keys(plan)[slot]
    attempts = ledger['slots'].get(key, 0)
    if attempts >= plan['limits']['max_attempts_per_slot']:
        refuse('budget_exhausted', 'this slot has used its attempt limit', {'slot': slot})
    limit = ceiling(plan, ledger)
    pool = 'first' if attempts == 0 else POOLS[kind]
    if pool != 'first' and ledger['charged'].get(pool, 0) >= plan['limits'][pool]:
        refuse('budget_exhausted', f'the shared {pool} budget is spent; resume, replacement and repair share it',
               {'pool': pool, 'charged': ledger['charged'].get(pool, 0)})
    charged = sum(ledger['charged'].values())
    if charged >= min(limit['max_tasks'], approval['approved_max_tasks']):
        refuse('budget_exhausted', 'the approved lifetime task ceiling is reached',
               {'charged_tasks': charged, 'approved_max_tasks': approval['approved_max_tasks']})
    if request['purpose'] not in ('initial', 'repair', 'replacement', 'resume'):
        invalid('invalid_admission', 'purpose must be initial, repair, replacement or resume')
    if not charge:
        return 0, {'admitted': True, 'dry_run': True, 'charged': False, 'pool': pool, 'slot': slot,
                   'request_id': request_id}
    ledger['charged'][pool] = ledger['charged'].get(pool, 0) + 1
    ledger['slots'][key] = attempts + 1
    ledger['requests'][request_id] = {'slot': slot, 'stage': stage, 'revision': revision, 'pool': pool,
                                      'state': 'open', 'admitted_at': stamp(now), 'request_sha256': sha(request),
                                      'catalog_sha256': catalog['sha256']}
    study.write('ledger.json', ledger)
    return 0, {'admitted': True, 'duplicate': False, 'charged': True, 'pool': pool, 'request_id': request_id,
           'slot': slot, 'charged_tasks': sum(ledger['charged'].values()), 'max_tasks': limit['max_tasks'],
           'approved_max_tasks': approval['approved_max_tasks']}


def op_release(args):
    study = Study(args.state_root, args.study)
    study.require()
    request = load_json(args.input, 'release')
    if not isinstance(request, dict) or set(request) != {'request_id', 'terminal_status', 'source'}:
        invalid('invalid_release', 'release needs request_id, terminal_status and the host source')
    if (study.job_dir / 'job.json').exists():
        # Once a generic job exists, dispatch is recorded there and only its authoritative host handle can
        # close a request; a claimed terminal status or summary is not quiescence.
        refuse('reconcile_required', 'this study has a job; close requests with lifecycle.py reconcile from the '
                                     "recorded host observations, never from a claimed status")
    with study.locked():
        ledger = study.ledger()
        row = ledger['requests'].get(request['request_id'])
        if row is None:
            invalid('unknown_request', 'release names a request this study never admitted')
        if row['state'] != 'terminal':
            row.update(state='terminal', terminal_status=text(request['terminal_status'], 'terminal_status'),
                       terminal_source=text(request['source'], 'source'))
            study.write('ledger.json', ledger)
    return 0, {'request_id': request['request_id'], 'state': 'terminal', 'refunded': False}


def op_wake(args):
    """Host wake or resume: past the deadline, list every unresolved owned request for cancellation. The
    list comes from the same recorded-host view as `lifecycle.py reconcile`, so a request closed earlier
    whose later host reading shows pending work is listed again."""
    study = Study(args.state_root, args.study)
    study.require()
    now = utc_now(args.now)
    lifecycle = lifecycle_module()
    with study.locked():
        view = lifecycle.reconcile(study, now)
        ledger = study.ledger()
    expired = view['deadline_expired']
    stop = expired or ledger['cancel_requested']
    return 0, {'deadline_expired': expired, 'observed_at': stamp(now), 'cancel': view['unresolved'] if stop else [],
               'task_cancel': view['actions']['task_cancel'], 'rediscover': view['actions']['rediscover'],
               'new_tasks_permitted': not expired and not ledger['cancel_requested'],
               'cancellation_confirmed': lifecycle.cancellation_confirmed(ledger, view),
               'note': 'Cancellation starts at this wake, not at the deadline; each task stays pending until the host '
                       'reports it terminal.'}


def op_cancel(args):
    """Record cancel intent, then judge it by the same recorded-host view as `lifecycle.py reconcile`: a
    request the ledger closed earlier stays pending, and its owned handle is cancelled again, while a later
    host reading shows pending work. Neither `cancel_requested` nor a closed ledger entry confirms it."""
    study = Study(args.state_root, args.study)
    study.require()
    lifecycle = lifecycle_module()
    with study.locked():
        ledger = study.ledger()
        if not ledger['cancel_requested']:
            ledger['cancel_requested'] = True
            study.write('ledger.json', ledger)
        view = lifecycle.reconcile(study, None)
        ledger = study.ledger()
    return 0, {'cancel_requested': True, 'cancel': view['unresolved'], 'task_cancel': view['actions']['task_cancel'],
               'rediscover': view['actions']['rediscover'],
               'cancellation_confirmed': lifecycle.cancellation_confirmed(ledger, view)}


def op_record(args):
    """Ingest one participant result: the authoritative acceptance boundary for participant evidence.

    The exact result bytes are reopened inside their task scope, parsed, scanned for secrets with every
    material file they cite, and validated against their stage contract here, under the study lock. Nothing
    depends on an earlier check-payload or a success flag. Suspect material is quarantined and refused before
    any accepted record exists. A first impression is frozen and a journey's evidence bound in the same step,
    to these bytes only. This direct route serves a study without a generic job (standalone fixtures); once a
    job exists it refuses, and `lifecycle.py ingest` is the only route."""
    study = Study(args.state_root, args.study)
    study.require()
    return accept_participant(study, load_json(args.input, 'acceptance record'))


def identity_verdict(target, observed, index=None):
    """Requested versus host-observed identity. A requested target is never evidence of what ran. `observed`
    is `{providerInstanceId, model, source}` as the host reported it, or None. With a catalog index, a model
    that differs from the request is a wrong model when the catalog lists it for that provider, and ambiguous
    (an alias or unlisted ID, never resolved to the request) otherwise. Only `verified` counts as verified."""
    requested = {'providerInstanceId': target['providerInstanceId'], 'model': target['model']}
    if observed is None or not observed.get('providerInstanceId'):
        return {'state': 'unreported', 'reason': 'the host reported no provider for this execution',
                'requested': requested, 'observed': observed}
    if not observed.get('model'):
        return {'state': 'unreported', 'reason': 'the host reported a provider but no model',
                'requested': requested, 'observed': observed}
    if observed['providerInstanceId'] != target['providerInstanceId']:
        return {'state': 'mismatched', 'reason': 'the host ran another provider instance',
                'requested': requested, 'observed': observed}
    if observed['model'] == target['model']:
        return {'state': 'verified', 'reason': 'host-observed provider and model equal the request',
                'requested': requested, 'observed': observed}
    if index is not None and (observed['providerInstanceId'], observed['model']) not in index:
        requested_lineage = (index.get((target['providerInstanceId'], target['model'])) or {}).get('lineage', 'unknown')
        return {'state': 'ambiguous', 'reason': 'the observed model is not a catalog ID for this provider (an alias or '
                                                f'unlisted model; requested lineage {requested_lineage}); it is never '
                                                'resolved to the request', 'requested': requested, 'observed': observed}
    return {'state': 'mismatched', 'reason': 'the host ran a different model', 'requested': requested,
            'observed': observed}


def accept_participant(study, request, verdict=None):
    """The participant acceptance boundary shared by `record-acceptance` and host-backed `lifecycle.py ingest`.
    `verdict` is the identity verdict ingestion derived from recorded host observations."""
    keys = {'revision', 'cell_id', 'stage', 'task_id', 'request_id', 'result', 'observed', 'predecessors', 'context'}
    optional = {'image_delivery', 'material_inspection'}
    if not isinstance(request, dict) or not keys <= set(request) or set(request) - keys - optional:
        invalid('invalid_record', f'acceptance record needs exactly {sorted(keys)} and optional {sorted(optional)}')
    plan = study.plan(request['revision'])['plan']
    if request['stage'] not in stages_for(plan['mode']):
        invalid('invalid_record', 'stage is not declared by this revision')
    cell = next((c for c in cells(plan) if c['cell_id'] == request['cell_id']), None)
    if cell is None:
        invalid('invalid_record', 'cell is not in this revision')
    task_id = safe_id(request['task_id'], 'task_id')
    admitted = study.ledger()['requests'].get(request['request_id'])
    if (admitted is None or admitted['revision'] != request['revision']
            or admitted['slot'] != f"{cell['cell_id']}:{request['stage']}"):
        refuse('forged_completion', 'no admitted request of this study matches the claimed cell, stage and revision')
    result = request['result']
    if (not isinstance(result, dict) or set(result) != {'path', 'sha256'}
            or not isinstance(result['path'], str) or not isinstance(result['sha256'], str)):
        invalid('invalid_record', 'result needs path and sha256')
    observed = request['observed']
    if observed is not None and (not isinstance(observed, dict) or set(observed) != {'providerInstanceId', 'model', 'source'}
                                 or any(not isinstance(observed[k], (str, type(None))) for k in observed)):
        invalid('invalid_record', 'observed needs providerInstanceId, model and source')
    supplied = verdict is not None
    verdict = verdict or identity_verdict(cell['target'], observed)
    identity = verdict['state']
    # The browser context a journey actually ran in; it must be the context its payload reports.
    context = request['context']
    if request['stage'] == 'journey':
        if (not isinstance(context, dict) or set(context) != {'class', 'reference', 'binding_sha256'}
                or not isinstance(context['reference'], str) or not context['reference'].strip()
                or not isinstance(context['binding_sha256'], str) or not HEX64.fullmatch(context['binding_sha256'])):
            invalid('invalid_record', 'a journey records its browser context: class, reference and binding_sha256')
        if request.get('image_delivery') is not None:
            invalid('invalid_record', 'image_delivery belongs to a first impression')
    else:
        if context is not None:
            invalid('invalid_record', 'a first impression records no browser context')
        if request.get('material_inspection') is not None:
            invalid('invalid_record', 'material_inspection belongs to a journey')
    evidence = evidence_module()
    stage, slot = request['stage'], f"{cell['cell_id']}:{request['stage']}"
    with study.locked():
        try:
            if not supplied and (study.job_dir / 'job.json').exists():
                # Once a generic job exists, execution evidence is its recorded parsed result, payload descriptor,
                # settled owned host tasks and host-observed identity: only `lifecycle.py ingest` reads those. A
                # caller-supplied observation never stands in for them.
                refuse('host_ingest_required', 'this study has a job: accept participant results with job_cli.py '
                                               'result, then lifecycle.py ingest, never from a supplied record')
            data, problem = study.artifact_bytes({'task_id': task_id, 'result': result})
            if problem:
                refuse(problem[0], problem[1])
            if result['sha256'] in evidence.quarantined_hashes(study):
                refuse('result_quarantined', 'this result is quarantined as suspected secret material; it is never '
                                             'accepted')
            # A recorded trace of this execution (its admitted request) that found contamination stops
            # acceptance; a later clean trace never clears it. Without a trace, compliance is unverified.
            # Identical bytes from a distinct request are another execution, judged on its own trace.
            trace, traces = evidence.trace_compliance(study, request['request_id'])
            if trace == 'contaminated':
                refuse('attempt_contaminated', 'a recorded tool trace shows this attempt was contaminated; it is '
                                               'retained and never accepted. A distinct retry is judged on its own trace',
                       {'trace_records': [r['record_sha256'] for r in traces if r['compliance'] == 'contaminated']})
            if any(r.get('result') and r['result']['sha256'] != result['sha256'] for r in traces):
                refuse('trace_result_mismatch', "this execution's recorded trace bound a different result; one request "
                                                'returns one result')
            accepted = study.accepted()
            for row in accepted:
                if ((row['revision'], row['cell_id'], row['stage']) == (request['revision'], cell['cell_id'], stage)
                        and row['result']['sha256'] == result['sha256']):
                    return 0, {'recorded': True, 'duplicate': True, 'record_sha256': row['record_sha256']}
            # Screen the exact bytes and every file they cite before anything else is decided.
            payload, material = evidence.screen(study, task_id, stage, cell['cell_id'], result['sha256'], data,
                                                request.get('material_inspection'))
            if stage == 'journey' and not context_fits(context, plan['journey_context']):
                refuse('context_mismatch', "the recorded browser context does not satisfy this revision's journey "
                                           'context')
            predecessors = request['predecessors']
            sources = []
            if stage == 'journey':
                sources = effective_first(study, request['revision'], cell['cell_id'], accepted)
                if len(sources) != 1 or predecessors != [sources[0]['result_sha256']]:
                    refuse('foreign_predecessor', 'a journey may bind only the first impression accepted in, or '
                                                  'carried into, its own cell and revision')
            elif predecessors != []:
                refuse('foreign_predecessor', 'a first impression has no predecessor')
            if any((row['revision'], row['cell_id'], row['stage']) == (request['revision'], cell['cell_id'], stage)
                   for row in accepted):
                refuse('conflicting_acceptance', 'this slot already has a different accepted result; results are never '
                                                 'pooled')
            # The stage contract on the same bytes: brief, cell, revision, predecessor, context and scope.
            ingested = evidence.ingest(study, plan, request['revision'], cell, stage, task_id, payload, result,
                                       material, request.get('image_delivery'), request.get('material_inspection'))
            if stage == 'journey' and {k: context[k] for k in ('reference', 'binding_sha256')} != payload['context']:
                refuse('context_mismatch', 'the recorded context differs from the context the journey ran in')
            body = {'schema_version': 1, 'revision': request['revision'], 'cell_id': cell['cell_id'], 'stage': stage,
                    'task_id': task_id, 'request_id': safe_id(request['request_id'], 'request_id'),
                    'result': {'path': result['path'], 'sha256': result['sha256']}, 'observed': observed,
                    'identity': identity, 'context': context, 'predecessor_records': sources,
                    'bindings': dict(bindings(plan, cell, stage), predecessors=predecessors)}
            if supplied:
                body['identity_detail'] = {k: verdict[k] for k in ('reason', 'requested', 'observed')}
            body['record_sha256'] = sha(body)
            # A slot filled by the revision's written carry mapping takes no native result as well, even
            # from a request admitted before the mapping was written.
            slot_filled(study, request['revision'], slot, native=False)
        except StudyError as exc:
            if exc.exit_code == 1:
                evidence.retain_attempt(study, 'record', {'request': request, 'refusal': exc.code})
            raise
        # The frozen first impression or bound journey evidence is written first, keyed by this record,
        # so an accepted record never exists without it.
        evidence_record = ingested(body)
        study.retain(f"accepted/{request['revision'][:16]}.{cell['cell_id']}.{stage}.json", body,
                     'conflicting accepted record')
    return 0, {'recorded': True, 'duplicate': False, 'record_sha256': body['record_sha256'], 'identity': identity,
               'identity_reason': verdict['reason'],
               'predecessor_records': sources, 'evidence_record_sha256': evidence_record['record_sha256'],
               'ingested': stage, 'trace_compliance': evidence_record['trace_compliance_at_acceptance']}


def op_carry(args):
    study = Study(args.state_root, args.study)
    current = study.require()
    revision = args.revision or current['revision']
    if not args.write:
        return 0, mapping_for(study, revision)
    with study.locked():
        mapping = mapping_for(study, revision)
        study.retain(f'carry/{revision}.json', mapping, 'a different carry-forward mapping is recorded')
    return 0, mapping


def op_validate_carry(args):
    """Check a supplied mapping against accepted records and their current artifacts; reject forged,
    pooled, ineligible or altered entries and derived fields. Returns the canonical validated mapping."""
    study = Study(args.state_root, args.study)
    study.require()
    errors, mapping = validate_mapping(study, load_json(args.input, 'carry mapping'))
    if errors:
        refuse('carry_forward_rejected', 'the mapping claims results it cannot carry', {'errors': errors})
    return 0, {'valid': True, 'carried': mapping['filled_slots'], 'mapping': mapping, 'mapping_sha256': sha(mapping)}


def op_status(args):
    """Read-only: never creates, locks or rewrites study or job files."""
    study = Study(args.state_root, args.study)
    current = study.require()
    revision = current['revision']
    plan = study.plan(revision)['plan']
    ledger = study.ledger()
    open_requests = sorted(k for k, v in ledger['requests'].items() if v['state'] == 'open')
    pending_cancel = {k for k, v in ledger['requests'].items() if v['state'] == 'cancel-requested'}
    lifecycle = lifecycle_module()
    unresolved = lifecycle.reconcile_view(study, plan, ledger, lifecycle.load_job(study), None)['unresolved']
    if ledger['cancel_requested'] or ledger['deadline_expired']:
        pending_cancel |= set(unresolved)  # includes closed requests whose later host reading disagrees
    pending_cancel = sorted(pending_cancel)
    counts = arithmetic(plan)
    return 0, {'study_id': study.id, 'revision': revision, 'previous_revisions': current['history'], 'mode': plan['mode'],
               'approval': approval_state(study.approvals(revision), revision, ceiling(plan, ledger)),
               'catalog_observation': ledger.get('catalog'), 'stimulus_changed': rehash_stimulus(plan), 'task_counts': counts, 'ceiling': ceiling(plan, ledger),
               'charged': ledger['charged'], 'charged_tasks': sum(ledger['charged'].values()),
               'open_requests': open_requests, 'cancel_pending_confirmation': pending_cancel,
               'cancel_requested': ledger['cancel_requested'], 'deadline_expired': ledger['deadline_expired'],
               'accepted_results': len(study.accepted()),
               'unresolved_owned_work': unresolved,
               'complete': False if open_requests or pending_cancel or unresolved else None,
               'combined_scope_complete': False if plan['mode'] == 'capture-only' else None}


def job_contract(plan, revision):
    """The generic job's requirements and stage contracts for one study revision (job-spec and
    `lifecycle.py job-revision` share them)."""
    stages = stages_for(plan['mode'])
    requirements = {'STUDY-FIRST-IMPRESSION': 'Every declared cell has one accepted, hash-bound first impression or a visible gap.',
                    'STUDY-ANALYSIS': 'A delegated analyst synthesises only accepted evidence with recorded author lineage.',
                    'STUDY-REVIEW': 'A fresh reviewer of a distinct known lineage checks the exact report and inputs.'}
    if 'journey' in stages:
        requirements['STUDY-JOURNEY'] = 'Every declared cell has one accepted isolated journey or a visible journey gap.'
    job_stages = [{'id': 'first-impression', 'depends_on': [], 'requirements': ['STUDY-FIRST-IMPRESSION']}]
    if 'journey' in stages:
        # Each journey depends on its own cell's frozen first impression, enforced per cell by its brief,
        # admission and acceptance. A stage dependency would hold every journey until the whole first-impression
        # stage was accepted, so a model's pilot journey could never gate its other journeys.
        job_stages.append({'id': 'journey', 'depends_on': [], 'requirements': ['STUDY-JOURNEY']})
    job_stages.append({'id': 'analysis', 'depends_on': list(stages), 'requirements': ['STUDY-ANALYSIS']})
    job_stages.append({'id': 'review', 'depends_on': ['analysis'], 'requirements': ['STUDY-REVIEW']})
    for stage in job_stages:
        stage.update(validator_dependency='focus-group', revision=revision, execution_mode='workers',
                     validator_contract={'study_revision': revision, 'stage': stage['id']})
    return requirements, job_stages


def op_job_spec(args):
    """The generic job for the approved revision: declared stages, pinned workers, final review."""
    study = Study(args.state_root, args.study)
    now = utc_now(args.now)
    catalog = fresh_catalog(args.capabilities, now)
    with study.locked():
        revision, plan, *_ = preflight(study, now, catalog)
    documents = load_json(args.documents, 'participant documents') if args.documents else {}
    stages = stages_for(plan['mode'])
    requirements, job_stages = job_contract(plan, revision)
    for stage in job_stages:
        stage['status'] = 'pending'
    tasks = []

    def slot(task_id, stage, worker, target, **extra):
        row = {'task_id': task_id, 'stage_id': stage, 'logical_slot_id': task_id, 'request_id': f'{task_id}-r0',
               'worker_id': worker, 'dependency_key': 'focus-group', 'target': target,
               'write_scope': {'mode': 'worker-evidence', 'path': f'artifacts/tasks/{task_id}'}}
        row.update(extra)
        tasks.append(row)

    evidence = evidence_module()
    deferred = []
    for n, cell in enumerate(cells(plan), 1):
        for stage in stages:
            task_id = f"{'fi' if stage == 'first-impression' else 'jr'}-{n:02d}"
            document = documents.get(task_id)
            if document is None and stage == 'journey' and args.defer_journeys:
                # A journey brief exists only after this cell's first impression is accepted and frozen.
                deferred.append({'task_id': task_id, 'cell_id': cell['cell_id']})
                continue
            if not (isinstance(document, dict) and set(document) == {'path', 'sha256'}):
                refuse('participant_brief_missing', f'{task_id} needs a document-only participant brief (path, sha256)')
            # Only a brief the generator built for exactly this task, cell and stage, unchanged and still
            # lint-clean (and, for a journey, still on the cell's current first impression and context).
            problem = evidence.verify_brief_document(study, plan, revision, {'task_id': task_id, 'cell_id': cell['cell_id'],
                                                                             'stage': stage}, document)
            if problem:
                refuse(problem[0], f'{task_id}: {problem[1]}')
            slot(task_id, stage, 'focus-group/participant', cell['target'], context_policy='document-only',
                 document=document, max_followups=0,
                 focus_group={'cell_id': cell['cell_id'], 'persona_id': cell['persona_id'], 'pilot': cell['pilot']})
    # The analyst reads only its frozen analysis inputs (`report.py analysis-inputs` binds the document), and the
    # required review names the exact rendered report documents, their hash-bound authors and author independence
    # (`report.py review-slot`). Until each is bound through the shared plan-revision route, preparation refuses
    # it. Independence is set with the documents: the shared author refresh would record a subject-less
    # independent slot's authors as permanently unknown.
    slot('analysis', 'analysis', 'focus-group/analyst', plan['analysis'], context_policy='document-only',
         max_followups=0)
    slot('review', 'review', 'focus-group/fidelity-reviewer', plan['review'], role='review', max_followups=0)
    job = {'schema_version': 1, 'job_id': study.id, 'installation_id': text(args.installation_id, '--installation-id'),
           'workflow': 'focus-group/run', 'owner': {'id': 'study-operator'},
           'objective': f'Synthetic focus group to inform: {plan["decision"]}', 'requirements': requirements,
           'authorization': {'actions': ['dispatch approved study tasks'], 'study_revision': revision,
                             'sharing': plan['sharing']},
           'constraints': ['Results are synthetic product-use hypotheses, not evidence of human demand.',
                           'Participant briefs carry only their persona, approved material, tasks and boundaries.',
                           'No credentials, product transactions, publication or implementation.'],
           'dependencies': [{'key': 'focus-group', 'plugin': 'focus-group'}], 'pins': {},
           'policy': {'max_repair_cycles': plan['limits']['max_attempts_per_slot'] - 1, 'max_artifact_bytes': 16777216,
                      'max_live_workers': plan['limits']['max_concurrency']},
           'stages': job_stages, 'tasks': tasks, 'decisions': [], 'history': [], 'metrics': {},
           'result_contract': {'schema_version': 1}}
    out = {'job': job, 'revision': revision, 'dispatched': 0}
    if deferred:
        out['deferred_journey_tasks'] = deferred
        out['note'] = ('Journey slots are not declared yet, so the journey stage cannot be accepted. Add each slot with '
                       'its generated brief through a recorded job plan revision once its first impression is frozen; '
                       'zero workers never substitute for journey evidence.')
    return 0, out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    doctor = sub.add_parser('doctor')
    doctor.add_argument('--capabilities')
    doctor.add_argument('--observations')
    suggest = sub.add_parser('suggest')
    suggest.add_argument('--input', required=True)
    suggest.add_argument('--capabilities', required=True)
    for name in ('plan', 'approve', 'check-run', 'admit', 'release', 'wake', 'cancel', 'record-acceptance', 'carry',
                 'validate-carry', 'status', 'job-spec'):
        command = sub.add_parser(name)
        command.add_argument('--state-root', required=True)
        command.add_argument('--study', required=True)
        if name in ('plan', 'approve', 'admit', 'release', 'record-acceptance', 'validate-carry'):
            command.add_argument('--input', required=True)
        if name == 'plan':
            command.add_argument('--capabilities', required=True)
            command.add_argument('--observations')
        if name in ('check-run', 'admit', 'wake', 'job-spec'):
            command.add_argument('--now')
        if name in ('check-run', 'admit', 'job-spec'):
            command.add_argument('--capabilities', required=True,
                                 help='fresh catalog observation {schema_version, observed_at, source, response}')
        if name == 'carry':
            command.add_argument('--revision')
            command.add_argument('--write', action='store_true')
        if name == 'job-spec':
            command.add_argument('--installation-id', required=True)
            command.add_argument('--documents')
            command.add_argument('--defer-journeys', action='store_true')
    args = parser.parse_args(argv)
    handler = {'doctor': op_doctor, 'suggest': op_suggest, 'plan': op_plan, 'approve': op_approve,
               'check-run': op_check_run, 'admit': op_admit, 'release': op_release, 'wake': op_wake,
               'cancel': op_cancel, 'record-acceptance': op_record, 'carry': op_carry,
               'validate-carry': op_validate_carry, 'status': op_status, 'job-spec': op_job_spec}[args.command]
    try:
        code, data = handler(args)
        print(json.dumps({'ok': code == 0, 'op': args.command, 'data': data}, sort_keys=True))
        return code
    except StudyError as exc:
        print(json.dumps({'ok': False, 'op': args.command, 'error': {'code': exc.code, 'message': str(exc)},
                          'data': exc.data}, sort_keys=True))
        return exc.exit_code
    except JobError as exc:
        print(json.dumps({'ok': False, 'op': args.command, 'error': {'code': 'unsafe_state', 'message': str(exc)}}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
