"""Explicit compact transport. Authority and full pins remain coordinator-owned.

This module neither dispatches nor accepts jobs. Version 1 remains the default.
The reviewed retention map is an integrity anchor, not a renewable approval: a
changed map requires a new semantic assessment and an explicit protocol update.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path
import re

from core.jobs.store import JobError, _regular, _retain, canonical, digest, strict_load
from core.schema import errors

LEGACY = 'worker-brief-v1'
COMPACT = 'worker-brief-compact-v2'
MAP_HASH = '2b39b761de80b34dcce93de117980b05bd7184cebcc4be1640e4bde07e9b2596'
MAP_SCHEMA_HASH = 'e317cf397ab51acef93d39469280370e1f5676bcf2dcfe08d0c32e4db635f29f'
MANIFEST_CONTRACT_HASHES = {
    # Automated releases may change only this validated metadata value. Hashing
    # exact bytes around it keeps every other manifest byte pinned.
    'agent-tuneup': '5ae9bc712f93aa2d8e45ca2b5bb5782ab3610b10dc3e308678580f2ef2690244',
    'ape': '636a5a04b9fcf2935882109da716098450bffca7c0e62a9d77a5d5653c88fcab',
    'babysitter': '583be3a411e535a7caff59afca7fcfc69f6972dbda457ad153c5e531b57b656d',
    'elephant-goldfish': '23f3094a7b81ef8810e9485e53ea7bcf43bd408fb370d29c30173b7781ce028b',
    'focus-group': '0b37f21dd5957110c6dabc767e0a4b953a035d5ced96f7e7151c4741ac28f87e',
    'imps': 'a3b6727aad6e1d71d27fd9304317498cee999b389eb36e6d9963981fb679912f',
    'ralph': '9fa48ebf654ee2c0024c267aba65e5368fef27a5bea9a6f08fb7a72c49969b60',
    'plan': '847f34f77676037f40f52cd7c3bb505b946a16c38430272d4cad4039a9413e80',
    'tests-omg': 'a1fb7b45dc1ebec77de2fad9996b29255737a717db14bad16b2c9766a0673135',
}
MANIFEST_VERSION = re.compile(
    rb'(?m)^(  "version"[ \t]*:[ \t]*)("[0-9]+\.[0-9]+\.[0-9]+")(?=[ \t]*,?[ \t]*\r?$)')
RUBRICS = {
    'agent-tuneup/config-verifier': ['references/adopter-review-rubric.md'],
    'ape/synthesizer': ['references/plan-review-rubric.md'],
    'babysitter/pr-reviewer': ['references/adopter-review-rubric.md'],
    'elephant-goldfish/plan-reviewer': ['references/plan-review-rubric.md', 'references/adopter-review-rubric.md'],
    'focus-group/plan-reviewer': ['references/adopter-review-rubric.md'],
    'imps/reviewer': ['references/plan-review-rubric.md'],
    'plan/plan-reviewer': ['references/plan-review-rubric.md'],
    'ralph/strategy-reviewer': ['references/adopter-review-rubric.md'],
}
INSTRUCTIONS = (
    'Procedure/result schemas inline. Load no omitted contracts. '
    'Return worker-result-v1 with schema_version=1, overriding the procedure copy rule. '
    'Brief version: 2. Copy other correlation fields/revision; binding=snapshot. '
    'Dispatch SHA-256 covers exact bytes.'
)
MAGIC = b'T3-COMPACT-BRIEF/2\n'
BODY = b'\nINLINE PROCEDURE (UTF-8)\n'


def serialize(view):
    """Versioned framing keeps approved procedure bytes literal, without escapes."""
    if view.get('schema_version') == 1:
        return canonical(view)
    if view.get('schema_version') != 2 or view.get('transport') != COMPACT:
        raise JobError('brief_transport_unsupported_or_mixed')
    header = copy.deepcopy(view)
    body = header.pop('definition').encode('utf-8')
    header['definition'] = {'encoding': 'inline-utf-8', 'sha256': digest(body), 'bytes': len(body)}
    return MAGIC + canonical(header) + BODY + body


def deserialize(raw):
    """Strict version dispatch; JSON v2 and unrecognized frames never fall back."""
    if not raw.startswith(MAGIC):
        value = strict_load(raw)
        if not isinstance(value, dict) or value.get('schema_version') != 1 or 'transport' in value:
            raise JobError('brief_transport_unsupported_or_mixed')
        return value
    header, separator, rest = raw[len(MAGIC):].partition(b'\n')
    if not separator or not rest.startswith(BODY):
        raise JobError('compact_frame_malformed')
    value = strict_load(header)
    if not isinstance(value, dict) or value.get('schema_version') != 2 or value.get('transport') != COMPACT:
        raise JobError('brief_transport_unsupported_or_mixed')
    body = rest[len(BODY):]
    if value.get('definition') != {'encoding': 'inline-utf-8', 'sha256': digest(body), 'bytes': len(body)}:
        raise JobError('compact_inline_definition_bytes_changed')
    try:
        value['definition'] = body.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise JobError('compact_inline_definition_invalid_utf8') from exc
    return value


def transport(job):
    value = job.get('policy', {}).get('worker_brief_transport', LEGACY)
    if value not in (LEGACY, COMPACT):
        raise JobError('brief_transport_unsupported: explicit supported transport required')
    return value


def _read(package, relative):
    from shared.worker_registry import package_file
    try:
        return _regular(package_file(package, relative))
    except (OSError, ValueError) as exc:
        raise JobError('retention_package_file_invalid: ' + relative) from exc


def validate_retention_rules(profile):
    for rule in profile.get('rules', []):
        disposition = rule.get('disposition')
        if ((disposition == 'inline' and (not isinstance(rule.get('inline_text'), str)
                                          or not rule['inline_text']))
                or (disposition != 'inline' and 'inline_text' in rule)):
            raise JobError('retention_rule_invalid')


def read_required_rubric(descriptor, allowed_hashes, allowed_descriptors=None):
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get('path'), str):
        raise JobError('compact_required_rubric_descriptor_invalid')
    path = Path(descriptor['path'])
    try:
        canonical_path = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise JobError('compact_required_rubric_descriptor_invalid') from exc
    if (not path.is_absolute() or str(path) != str(canonical_path)
            or isinstance(descriptor.get('bytes'), bool)
            or not isinstance(descriptor.get('bytes'), int) or descriptor['bytes'] < 0
            or not isinstance(descriptor.get('sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', descriptor['sha256'])):
        raise JobError('compact_required_rubric_descriptor_invalid')
    if descriptor['sha256'] not in allowed_hashes:
        raise JobError('compact_required_rubric_not_frozen')
    if allowed_descriptors is not None and allowed_descriptors.get(str(canonical_path)) != (
            descriptor['bytes'], descriptor['sha256']):
        raise JobError('compact_required_rubric_not_frozen')
    try:
        raw = _regular(path)
    except (OSError, ValueError) as exc:
        raise JobError('compact_required_rubric_descriptor_invalid') from exc
    if digest(raw) != descriptor['sha256'] or len(raw) != descriptor['bytes']:
        raise JobError('compact_required_rubric_bytes_changed')
    return raw


def _manifest_contract_hash(raw, plugin):
    """Pin plugin.json byte-for-byte except for its validated release version."""
    meta = strict_load(raw)
    matches = list(MANIFEST_VERSION.finditer(raw))
    if (not isinstance(meta, dict) or meta.get('name') != plugin or
            not isinstance(meta.get('version'), str) or
            not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', meta['version']) or
            len(matches) != 1 or matches[0].group(2)[1:-1].decode() != meta['version']):
        raise JobError('retention_manifest_source_changed')
    match = matches[0]
    major_minor = '.'.join(meta['version'].split('.')[:2]).encode()
    normalized = raw[:match.start(2)] + b'"' + major_minor + b'.<patch>"' + raw[match.end(2):]
    return digest(normalized)


def retained_definition(pin, worker_id):
    """Verify approved source/procedure/schema bytes on every installed call.

    Full procedures, schema text and lexical prose stay unchanged.
    No reference authorizes reading the manifest, package, registry or full job.
    """
    package = Path(pin['package_dir'])
    raw = _read(package, 'shared/agents/worker-retention.json')
    schema_raw = _read(package, 'shared/agents/worker-retention.schema.json')
    if digest(raw) != MAP_HASH or digest(schema_raw) != MAP_SCHEMA_HASH:
        raise JobError('retention_approval_changed: scoped semantic reassessment required')
    manifest = strict_load(raw)
    if errors(manifest, strict_load(schema_raw)):
        raise JobError('retention_schema_invalid')
    profile = next((p for p in manifest['profiles'] if p['id'] == worker_id), None)
    if profile is None or profile['worker_ids'] != [worker_id]:
        raise JobError('retention_worker_missing')
    procedure = profile['procedure']
    if digest(procedure['text'].encode()) != procedure['sha256'] or len(procedure['text'].encode()) != procedure['bytes']:
        raise JobError('retention_procedure_changed')
    sources = {row['source_id']: row for row in manifest['sources']}
    plugin = worker_id.partition('/')[0]
    meta_raw = _read(package, 'plugin.json')
    if _manifest_contract_hash(meta_raw, plugin) != MANIFEST_CONTRACT_HASHES[plugin]:
        raise JobError('retention_manifest_source_changed')
    # Approval binds the original source set, including unselected ORIGINAL
    # workers in this package. New unrelated files are not normative sources.
    for row in manifest['sources']:
        if row['kind'] == 'specialized-definition' and row['path'].startswith('plugins/' + plugin + '/'):
            wid = plugin + '/' + Path(row['path']).stem
            source = pin['workers'][wid]['bytes'].encode()
            if digest(source) != row['sha256'] or len(source) != row['bytes']:
                raise JobError('retention_source_changed: ' + row['source_id'])
    checked = set()
    validate_retention_rules(profile)
    for rule in profile['rules']:
        source_id = rule['source_id']
        if source_id in checked:
            continue
        checked.add(source_id)
        row = sources[source_id]
        if row['kind'] == 'specialized-definition':
            source = pin['workers'][worker_id]['bytes'].encode()
        elif row['kind'] == 'composer-framing':
            module = _read(package, 'shared/worker_registry.py').decode()
            node = next(n for n in ast.parse(module).body if isinstance(n, ast.FunctionDef) and n.name == 'compose_worker')
            source = ast.get_source_segment(module, node).encode()
        else:
            source = _read(package, row['path'])
            pinned = pin['shared'].get(Path(row['path']).name)
            if pinned is None or pinned['bytes'].encode() != source:
                raise JobError('retention_source_pin_changed: ' + source_id)
        if digest(source) != row['sha256'] or len(source) != row['bytes']:
            raise JobError('retention_source_changed: ' + source_id)
        for clause in row['clauses']:
            if digest(source[clause['start_byte']:clause['end_byte']]) != clause['sha256']:
                raise JobError('retention_clause_changed: ' + source_id)
    expected_shared = {Path(s).name for s in checked if s.startswith('shared/agents/')}
    if set(pin['shared']) != expected_shared:
        raise JobError('retention_shared_set_changed')
    meta = strict_load(meta_raw)
    if set(meta.get('worker_shared', [])) != expected_shared:
        raise JobError('retention_worker_shared_changed')
    if meta.get('planning_review', {}).get('worker_id') != next(
            (wid for wid in RUBRICS if wid.partition('/')[0] == worker_id.partition('/')[0]), None):
        raise JobError('retention_planning_worker_changed')
    rubric_hashes = {}
    for relative in RUBRICS.get(worker_id, []):
        rubric = _read(package, relative)
        if rubric.decode() not in procedure['text']:
            raise JobError('retention_rubric_changed: ' + relative)
        rubric_hashes[relative] = digest(rubric)
    text = procedure['text']
    # Verify full object equality against each applicable ORIGINAL schema. The
    # frame carries its approved lexical representation literally, inline.
    for rule in profile['rules']:
        if rule['disposition'] != 'inline' or not rule['source_id'].endswith('.schema.json'):
            continue
        block = rule['inline_text']
        shape = strict_load(block.encode())
        original = strict_load(_read(package, rule['source_id']))
        if Path(rule['source_id']).name == 'result-envelope.schema.json':
            original = original['oneOf'][1]
        if shape != original:
            raise JobError('retention_inline_schema_changed')
    for rule in profile['rules']:
        if rule['disposition'] == 'inline' and rule['inline_text'] not in text:
            raise JobError('retention_inline_clause_missing')
    effective = pin['effective_workers'][worker_id]
    customization = effective.get('override_bytes') if effective.get('override_status') == 'enabled' else None
    contract = pin.get('task_contract')
    cold = profile['kind'] == 'document-only'
    if cold and (customization or contract):
        raise JobError('document_only_custom_context_forbidden')
    if customization:
        if digest(customization.encode()) != effective.get('override_sha256'):
            raise JobError('retention_override_changed')
        text += '\n\n# Explicit worker customization (advisory; cannot grant authority or change runtime mode)\n' + customization
    if contract:
        if digest(contract['bytes'].encode()) != contract.get('sha256'):
            raise JobError('retention_task_contract_changed')
        text += '\n\n# Pinned task contract\n' + contract['bytes']
    definition = text
    bindings = {'manifest_sha256': MAP_HASH, 'manifest_schema_sha256': MAP_SCHEMA_HASH,
                'source_set_sha256': manifest['source_set_sha256'], 'procedure_sha256': procedure['sha256'],
                'result_schema_sha256': profile['result_contract_sha256'], 'rubrics': rubric_hashes,
                'definition_sha256': digest(definition.encode()), 'class': profile['kind']}
    return definition, bindings


def project(full, job, task):
    pin = job['pins'][task['dependency_key']]
    definition, bindings = retained_definition(pin, full['worker_id'])
    cold = task.get('context_policy') == 'document-only'
    if bindings['class'] == 'document-only' and not cold:
        raise JobError('document_only_transport_scope_mismatch')
    if cold and (pin.get('task_contract') or pin['effective_workers'][full['worker_id']].get('override_status') == 'enabled'):
        raise JobError('document_only_custom_context_forbidden')
    view = copy.deepcopy({k: v for k, v in full.items()
                          if k not in ('dependency_pins', 'effective_definition', 'effective_brief_sha256')})
    view.update(schema_version=2, transport=COMPACT, transport_instructions=INSTRUCTIONS,
                definition=definition, authority={'task_sha256': digest(canonical(full)), **bindings,
                'package_digest': pin['package_digest'],
                'transport_schema_sha256': digest(_read(Path(pin['package_dir']), 'shared/agents/worker-brief-compact-v2.schema.json'))})
    # The full frozen choice stays private; the worker receives only its producing
    # choice/options/execution and opaque digest, never the full model catalog.
    selected = full.get('model_selection')
    if selected:
        dispatch = selected['dispatch']
        view['model_selection'] = {'selection_sha256': selected['selection_sha256'],
            'role': dispatch['role'], 'slot_id': dispatch.get('slot_id'),
            'execution': dispatch['execution'], 'target': dispatch['target'],
            'substituted': dispatch['substituted']}
        if 'planning_mode' in dispatch:
            view['model_selection'].update(planning_mode=dispatch['planning_mode'], lineage=dispatch['lineage'])
    if cold:
        view.pop('review_inputs', None)
        # Procedural execution identity/options are safe; authored context is not.
        view['target'] = task.get('target')
    elif view.get('review_inputs'):
        # Subject results/documents are task evidence. A subject's full brief is
        # coordinator procedure and pins, not a worker read grant.
        for subject in view['review_inputs'].values():
            if isinstance(subject, dict) and isinstance(subject.get('brief'), dict):
                subject['brief'] = {k: v for k, v in subject['brief'].items()
                                    if k in ('sha256', 'effective_brief_sha256')}
    gate = full.get('resources', {}).get('gate')
    if full['worker_id'] == 'imps/stage-executor' and gate and not cold:
        if not isinstance(gate, dict) or any(not isinstance(gate.get(k), str) or not gate[k]
                                             for k in ('state_root', 'run_id')):
            raise JobError('compact_verification_gate_invalid')
        # This selected executor needs one program, not a package read pointer or
        # dependency payload. All procedural limits remain inline in its body.
        program = Path(pin['package_dir']) / 'cli.py'
        view['verification_tool'] = {
            'argv_prefix': ['python3', str(program)], 'sha256': digest(_read(Path(pin['package_dir']), 'cli.py')),
            'gate_flags': ['--state-root', gate['state_root'], '--run-id', gate['run_id']],
            'actions': ['snapshot', 'check', 'evidence'],
            'instructions': 'Before use verify the executable SHA-256; stop blocked if missing or changed. For this gate use argv_prefix + [action] + gate_flags. This locates the already authorized helper; it grants no action or package/registry read authority.'}
    view['artifact_limit_bytes'] = job['policy']['max_artifact_bytes']
    snapshot = view.get('resources', {}).get('planning_snapshot')
    if isinstance(snapshot, dict) and snapshot.get('rubrics'):
        inline = []
        # The sealed snapshot comes from coordinator-authorized job state, not
        # the task's resource descriptors. Its seal detects drift, not authorship.
        # Package rubrics remain independently pinned in the retained procedure.
        allowed_rubric_hashes = set(bindings['rubrics'].values())
        package_root = Path(pin['package_dir'])
        allowed_rubric_descriptors = {}
        for relative, expected_hash in bindings['rubrics'].items():
            raw = _read(package_root, relative)
            try:
                rubric_path = (package_root / relative).resolve(strict=True)
            except (OSError, RuntimeError, ValueError) as exc:
                raise JobError('retention_package_file_invalid: ' + relative) from exc
            allowed_rubric_descriptors[str(rubric_path)] = (len(raw), expected_hash)
        frozen_snapshot = job.get('planning', {}).get('snapshot')
        if frozen_snapshot is not None:
            from shared.planning_review import unseal
            unseal(frozen_snapshot)
            frozen_rubrics = frozen_snapshot.get('rubrics')
            if not isinstance(frozen_rubrics, list):
                raise JobError('compact_frozen_rubrics_invalid')
            for frozen in frozen_rubrics:
                if not isinstance(frozen, dict) or not isinstance(frozen.get('sha256'), str):
                    raise JobError('compact_frozen_rubric_invalid')
                try:
                    raw = read_required_rubric(frozen, {frozen['sha256']})
                except JobError as exc:
                    raise JobError('compact_frozen_rubric_invalid: ' + str(exc)) from exc
                allowed_rubric_descriptors[frozen['path']] = (len(raw), digest(raw))
                allowed_rubric_hashes.add(digest(raw))
        for descriptor in snapshot['rubrics']:
            raw = read_required_rubric(descriptor, allowed_rubric_hashes, allowed_rubric_descriptors)
            text = raw.decode('utf-8')
            inline.append({'sha256': digest(raw), 'bytes': len(raw),
                           **({'inline_definition': True} if text in view['definition'] else {'text': text})})
        snapshot['rubrics'] = inline
    view['effective_brief_sha256'] = digest(canonical(view))
    schema = strict_load(_read(Path(pin['package_dir']), 'shared/agents/worker-brief-compact-v2.schema.json'))
    problems = errors(view, schema)
    if problems:
        raise JobError('compact_brief_schema: ' + '; '.join(problems[:4]))
    return view


def prepare_projection(store, job, task, full):
    if transport(job) == LEGACY:
        return full
    view = project(full, job, task)
    raw = canonical(full)
    request = full['request_id']
    path = store.path / 'brief-authority' / (task['task_id'] + '-' + digest(request.encode()) + '.json')
    _retain(path, raw, 'coordinator brief authority is immutable')
    reference = {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw),
                 'transport_sha256': digest(serialize(view)), 'transport_bytes': len(serialize(view))}
    previous = task.setdefault('brief_authorities', {}).get(request)
    if previous is not None and previous != reference:
        raise JobError('compact_authority_rebinding_refused')
    task['brief_authorities'][request] = reference
    return view


def authoritative_full(store, job, task, request):
    reference = task.get('brief_authorities', {}).get(request)
    path = store.path / 'brief-authority' / (task['task_id'] + '-' + digest(request.encode()) + '.json')
    if not isinstance(reference, dict) or reference.get('path') != str(path):
        raise JobError('compact_authority_link_missing')
    raw = _regular(path)
    if digest(raw) != reference['sha256'] or len(raw) != reference['bytes']:
        raise JobError('compact_authority_bytes_changed')
    full = strict_load(raw)
    if full['task_id'] != task['task_id'] or full['request_id'] != request or full['job_id'] != job['job_id']:
        raise JobError('compact_authority_task_mismatch')
    if request == task['request_id']:
        selection = full.get('model_selection')
        if (task.get('selection_binding') and
                (not isinstance(selection, dict) or
                 selection.get('binding') != task['selection_binding'])):
            raise JobError('compact_authority_current_state_mismatch')
        from core.jobs import build_brief
        frozen_task = copy.deepcopy(task)
        # Revalidate against the exact selection bound when the immutable brief
        # was prepared. Recomputing dispatch here can change its evidence after
        # handles settle, even though the producing choice remains unchanged.
        frozen_task['attempt'] = full['attempt']
        stage = next(s for s in job['stages'] if s['id'] == task['stage_id'])
        expected = build_brief(job, frozen_task, stage, full['target_reason'])
        if full.get('followup_of'):
            expected['followup_of'] = full['followup_of']
        if canonical(expected) != raw:
            raise JobError('compact_authority_current_state_mismatch')
    return full


def verify_transmitted(store, job, task, request, raw, reference):
    assigned = deserialize(raw)
    version = assigned.get('schema_version')
    if version == 1:
        if transport(job) != LEGACY or 'transport' in assigned:
            raise JobError('mixed_brief_transport_versions')
        return assigned
    if version != 2 or assigned.get('transport') != COMPACT or transport(job) != COMPACT:
        raise JobError('brief_transport_unsupported_or_mixed')
    full = authoritative_full(store, job, task, request)
    if request == task['request_id'] and task.get('role') == 'review' and not job.get('planning'):
        from shared.job_acceptance import review_inputs
        if full.get('review_inputs') != review_inputs(store, job, task):
            raise JobError('compact_review_evidence_changed')
    authority = task['brief_authorities'][request]
    if digest(raw) != authority['transport_sha256'] or len(raw) != authority['transport_bytes']:
        raise JobError('compact_transmitted_bytes_changed')
    expected = project(full, job, task)
    if raw != serialize(expected):
        raise JobError('compact_projection_authority_mismatch')
    return assigned


def producer_authority(store, job, task, request, raw):
    """Planning provenance consumes private producing choices, never a projection."""
    view = verify_transmitted(store, job, task, request, raw, {})
    return authoritative_full(store, job, task, request) if view['schema_version'] == 2 else view


def inspect_definition(agents_root, plugin, worker, prefix, config_path=None):
    """Public inspection uses the same verified installed pins as preparation."""
    from shared.worker_registry import snapshot_pins
    import tempfile
    with tempfile.TemporaryDirectory(prefix='compact-inspection-') as directory:
        path = Path(directory) / 'job.json'
        path.write_bytes(canonical({'schema_version': 1, 'dependencies': [{'key': plugin, 'plugin': plugin}]}))
        pin = snapshot_pins(path, {plugin: plugin}, prefix, agents_root, config_path)['pins'][plugin]
        definition, bindings = retained_definition(pin, plugin + '/' + worker)
    return {'transport': COMPACT, 'definition': definition, 'definition_sha256': digest(definition.encode()),
            'definition_bytes': len(definition.encode()), 'retention': bindings}
