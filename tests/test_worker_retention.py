"""Preservation checkpoint, deliberately independent of compact composition.

The immutable fixture predates this manifest. Exact source slices and independently
assembled retained procedures reject semantic removals even when an attacker recomputes
all candidate hashes. These tests do not replace full-source semantic review.
"""
from __future__ import annotations

import ast
import copy
from functools import lru_cache
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from core.schema import errors
from shared import worker_registry as registry

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / 'tests/fixtures/worker-retention-baseline.json'
EXTENSION = ROOT / 'tests/fixtures/worker-retention-extension.json'
EXTENSION_V2 = ROOT / 'tests/fixtures/worker-retention-extension-v2.json'
MANIFEST = ROOT / 'shared/agents/worker-retention.json'
SCHEMA = ROOT / 'shared/agents/worker-retention.schema.json'
BASELINE_HASH = '0115949c68616695abfd48302d3463510c6b25ebc4322670353f057fb641f9d5'
EXTENSION_HASH = '719946041e9bdda30f81e51d0f5d83457333fe3e23ac6560958ba42a88c8c12a'
EXTENSION_REVISION = '1bc352ec059a80799bc9881dcb2f222d910fffe3'
EXTENSION_SOURCE_PATHS = {
    'plugins/babysitter/agents/pr-maintainer.md',
    'plugins/focus-group/agents/participant.md',
    'plugins/focus-group/agents/plan-reviewer.md',
    'plugins/ralph/agents/strategy-reviewer.md',
    'shared/agents/job.schema.json', 'shared/agents/jobs-contract.md',
    'shared/agents/model-selection.schema.json', 'shared/agents/reviewer-standard.md',
    'plugins/plan/agents/plan-reviewer.md', 'plugins/tests-omg/agents/reviewer.md',
}
EXTENSION_PACKAGE_PATHS = {
    'shared/tests_omg_review.py', 'shared/execution_agreement.py',
    'shared/legacy_author_provenance.py', 'shared/execution_agreement_cli.py',
    'shared/delivery.py', 'shared/upfront-agreement.md',
}
EXTENSION_V2_HASH = '02ec743cba8b153f2a64e3fc7041b8b0e771df80130b71cba0e2a75f776faddc'
EXTENSION_V2_REVISION = '32bf69d9d5a2db7cb87be3e196110ead32214835'
EXTENSION_V2_PARENT = '1bc352ec059a80799bc9881dcb2f222d910fffe3'
EXTENSION_V2_SOURCE_PATHS = {'shared/agents/reviewer-standard.md'}
EXTENSION_V2_PACKAGE_PATHS = {'shared/workflow-recovery.md'}
SCHEMA_HASH = 'e317cf397ab51acef93d39469280370e1f5676bcf2dcfe08d0c32e4db635f29f'
PACKAGE_ADDITIONS = {'shared/agents/worker-retention.json',
                     'shared/agents/worker-retention.schema.json',
                     # Explicit issue96 compact delivery file-set delta. Neither
                     # enters worker_shared or the full canonical v1 definition.
                     'shared/compact_briefs.py',
                     'shared/agents/worker-brief-compact-v2.schema.json'}
# Accepted delivery 1 additions, separate from this preservation checkpoint.
INVENTORY_ADDITIONS = {
    'scripts/agent_inventory.py', 'references/native-agent-formats-v1.json',
    'fixtures/agent-inventory-v1.json', 'fixtures/agent-inventory-v2.json',
}
KINDS = {
    'agent-tuneup/config-researcher': 'configuration',
    'agent-tuneup/config-verifier': 'configuration',
    'babysitter/pr-reviewer': 'code-review',
    'imps/reviewer': 'code-review',
    'focus-group/fidelity-reviewer': 'code-review',
    'elephant-goldfish/cold-reader': 'document-only',
    'elephant-goldfish/plan-reviewer': 'planning',
    'focus-group/plan-reviewer': 'planning',
    'plan/plan-reviewer': 'planning',
    'tests-omg/reviewer': 'code-review',
    'ralph/strategy-reviewer': 'planning',
}
RUBRICS = {
    'agent-tuneup/config-verifier': ['plugins/agent-tuneup/references/adopter-review-rubric.md'],
    'ape/synthesizer': ['plugins/ape/references/plan-review-rubric.md'],
    'babysitter/pr-reviewer': ['plugins/babysitter/references/adopter-review-rubric.md'],
    'elephant-goldfish/plan-reviewer': [
        'plugins/elephant-goldfish/references/plan-review-rubric.md',
        'plugins/elephant-goldfish/references/adopter-review-rubric.md'],
    'focus-group/plan-reviewer': ['plugins/focus-group/references/adopter-review-rubric.md'],
    'imps/reviewer': ['plugins/imps/references/plan-review-rubric.md'],
    'ralph/strategy-reviewer': ['plugins/ralph/references/adopter-review-rubric.md'],
    'plan/plan-reviewer': ['plugins/plan/references/plan-review-rubric.md'],
}
# Filled from inspected public originals, never from the candidate manifest.
RUBRIC_HASHES = {'plugins/agent-tuneup/references/adopter-review-rubric.md': '16f00d19b97964b0abd5ce356b6cfb2e332b9bac5d34372d918a1378762026e0', 'plugins/ape/references/plan-review-rubric.md': '3d8dca9fc5a61c77a783beb6bd65b26f0bd0eb63e0d44a3bd30430e90dc9ab66', 'plugins/babysitter/references/adopter-review-rubric.md': 'c9863f819edb8dd338d66a6dfdffcc02aee9697b0868208353511194c3ed447e', 'plugins/elephant-goldfish/references/adopter-review-rubric.md': '9d4d75949e501e232450aac68612023794c2de4353ceba5541df30be3021da1e', 'plugins/elephant-goldfish/references/plan-review-rubric.md': '31601046954bd16d61dd235fa2d2b606bd22d804c4b88d8d0867e2263a3ccdcd', 'plugins/focus-group/references/adopter-review-rubric.md': '6d9e57386218044ae68fcc34155c45d7117f538d26f83756a1a6225d16d1149d', 'plugins/imps/references/plan-review-rubric.md': 'ac23f6d8681ba7f2269aeb01ea262633bc50d27a519990c2a801588e45c4239e', 'plugins/ralph/references/adopter-review-rubric.md': '16573bc5750263cdecc7065177d4ede8f6d6aa70ec0489a3d2f56ed64e4beadf'}
RUBRIC_HASHES.update({'plugins/ralph/references/adopter-review-rubric.md': 'dfca1c6f7de56cf9e95348a31f45268d1fd0953d2ead5ae2a1b04bef4ab27100',
                      'plugins/plan/references/plan-review-rubric.md': '31601046954bd16d61dd235fa2d2b606bd22d804c4b88d8d0867e2263a3ccdcd'})
AUTHORITY = ('The task brief and repository instructions set the authority ceiling. '
             'Customization cannot add permissions, change runtime mode, dispatch children, or accept work.\n')
FRAMING = ('# Shared boundary contracts\n\n# Specialized worker definition\n\n'
           '# Explicit worker customization (advisory; cannot grant authority or change runtime mode)\n\n'
           '# Pinned task contract\n' + AUTHORITY)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


def baseline():
    raw = BASELINE.read_bytes()
    if sha(raw) != BASELINE_HASH:
        raise ValueError('immutable baseline changed; do not regenerate it from the candidate')
    return json.loads(raw)


def extension():
    raw = EXTENSION.read_bytes()
    if sha(raw) != EXTENSION_HASH:
        raise ValueError('retention extension changed; reassess the exact base revision')
    value = json.loads(raw)
    if (value.get('source_revision') != EXTENSION_REVISION
            or value.get('parent_source_revision') != baseline()['source_revision']):
        raise ValueError('retention extension revision chain changed')
    return value


def extension_v2():
    raw = EXTENSION_V2.read_bytes()
    if sha(raw) != EXTENSION_V2_HASH:
        raise ValueError('second retention extension changed; reassess the exact base revision')
    value = json.loads(raw)
    if (value.get('source_revision') != EXTENSION_V2_REVISION
            or value.get('parent_source_revision') != EXTENSION_V2_PARENT):
        raise ValueError('second retention extension revision chain changed')
    return value


def git_source(revision, row):
    raw = git_blob(revision, row['path'])
    if row['kind'] == 'composer-framing':
        node = next(n for n in ast.parse(raw.decode()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'compose_worker')
        raw = ast.get_source_segment(raw.decode(), node).encode()
    return raw


def version_neutral_manifest(raw):
    meta = json.loads(raw)
    version = meta.get('version')
    if (not isinstance(version, str) or
            not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)):
        raise ValueError('plugin manifest version is invalid')
    field = f'"version": "{version}"'.encode()
    if raw.count(field) != 1:
        raise ValueError('plugin manifest version field is ambiguous')
    return raw.replace(field, b'"version": "<version>"', 1)


@lru_cache(maxsize=None)
def git_blob(revision, path):
    return subprocess.run(['git', 'show', revision + ':' + path], cwd=ROOT,
                          check=True, capture_output=True).stdout


@lru_cache(maxsize=None)
def changed_paths(before, after):
    return frozenset(subprocess.run(['git', 'diff', '--name-only', before, after], cwd=ROOT,
                                    check=True, capture_output=True, text=True).stdout.splitlines())


def current_generation():
    frozen = baseline()
    addenda = [extension(), extension_v2()]
    source_paths = [EXTENSION_SOURCE_PATHS, EXTENSION_V2_SOURCE_PATHS]
    package_paths = [EXTENSION_PACKAGE_PATHS, EXTENSION_V2_PACKAGE_PATHS]
    source_map = {row['source_id']: row for row in frozen['sources']}
    changed = {}
    covered = set()
    parent_revision = frozen['source_revision']
    for addendum, expected_sources, expected_packages in zip(addenda, source_paths, package_paths):
        if (addendum.get('parent_source_revision') != parent_revision
                or {row['path'] for row in addendum['sources']} != expected_sources
                or {row['path'] for row in addendum['package_additions']} != expected_packages):
            raise ValueError('retention extension scope or revision chain changed')
        for row in addendum['package_additions']:
            committed = git_blob(addendum['source_revision'], row['path'])
            if sha(committed) != row['sha256'] or len(committed) != row['bytes']:
                raise ValueError('package extension source changed: ' + row['path'])
        for row in addendum['sources']:
            committed = git_source(addendum['source_revision'], row)
            if sha(committed) != row['sha256'] or len(committed) != row['bytes']:
                raise ValueError('extension source differs from pinned base: ' + row['source_id'])
            source_map[row['source_id']] = row
            covered.add(row['path'])
        changed.update({row['path']: row['sha256'] for row in addendum['manifests']})
        parent_revision = addendum['source_revision']
    old_manifests = {row['path']: row for row in frozen['manifests']}
    manifests, workers, shared_assets = [], [], set()
    plugin_paths = sorted((ROOT / 'plugins').glob('*/plugin.json'))
    for path in plugin_paths:
        relative = path.relative_to(ROOT).as_posix()
        raw = path.read_bytes()
        old = old_manifests.get(relative)
        expected = changed.get(relative, old['sha256'] if old else None)
        if expected is None:
            continue
        committed = git_blob(parent_revision, relative)
        if sha(committed) != expected or version_neutral_manifest(raw) != version_neutral_manifest(committed):
            raise ValueError('manifest differs from pinned base: ' + relative)
        meta = json.loads(raw)
        shared_names = list(meta.get('worker_shared', []))
        shared = ['shared/agents/' + name for name in shared_names]
        shared_assets.update(shared)
        manifests.append({'path': relative, 'sha256': expected, 'worker_shared': shared_names})
        plugin = meta['name']
        for worker in meta.get('workers', []):
            definition = 'plugins/' + plugin + '/' + worker['path']
            definition_row = source_map.get(definition)
            workers.append({'worker_id': worker['id'], 'plugin': plugin,
                            'definition_path': definition,
                            'definition_sha256': definition_row['sha256'] if definition_row else '',
                            'worker_shared': shared, 'role': worker['role'],
                            'allowed_scope': worker['allowed_scope'],
                            'output_contract': worker['output_contract']})
    changed_source_paths = changed_paths(frozen['source_revision'], parent_revision)
    for row in frozen['sources']:
        if row['path'] not in changed_source_paths or row['path'] in covered:
            continue
        if git_source(frozen['source_revision'], row) != git_source(addendum['source_revision'], row):
            raise ValueError('base source drift lacks an explicit extension: ' + row['source_id'])
    return {'source_revision': parent_revision,
            'sources': [source_map[key] for key in sorted(source_map)],
            'manifests': sorted(manifests, key=lambda row: row['path']),
            'workers': sorted(workers, key=lambda row: row['worker_id']),
            'shared_assets': sorted(shared_assets),
            'required_profiles': frozen['required_profiles']}


def source_bytes(row):
    raw = (ROOT / row['path']).read_bytes()
    if row['kind'] == 'composer-framing':
        node = next(n for n in ast.parse(raw).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'compose_worker')
        raw = ast.get_source_segment(raw.decode(), node).encode()
    return raw


def original_definition(worker, customization='', task_contract=None):
    """Independent v1 layout, not a call to the composer under test."""
    shared = sorted((f'shared/{Path(path).name}', subprocess.check_output(
        ['git', 'show', baseline()['source_revision'] + ':' + path], cwd=ROOT).decode())
                    for path in worker['worker_shared'])
    text = ('# Shared boundary contracts\n' + '\n'.join(data for _, data in shared) +
            '\n\n# Specialized worker definition\n' +
            subprocess.check_output(['git', 'show', baseline()['source_revision'] + ':' +
                                     worker['definition_path'],], cwd=ROOT).decode())
    if customization:
        text += ('\n\n# Explicit worker customization (advisory; cannot grant authority or change runtime mode)\n'
                 + customization)
    return (text + '\n\n# Pinned task contract\n' + AUTHORITY +
            (task_contract if task_contract else 'No additional task contract was supplied.'))


def current_definition(worker):
    shared = sorted((f'shared/{Path(path).name}', (ROOT / path).read_text())
                    for path in worker['worker_shared'])
    return ('# Shared boundary contracts\n' + '\n'.join(data for _, data in shared) +
            '\n\n# Specialized worker definition\n' +
            (ROOT / worker['definition_path']).read_text() +
            '\n\n# Pinned task contract\n' + AUTHORITY +
            'No additional task contract was supplied.')


# Explicit policy over immutable clause IDs, not the candidate's dispositions.
# Source markers below select literal worker duties from mixed clauses. The
# complement remains explicitly accounted coordinator procedure, never a lookup.
COORDINATOR_SCHEMAS = {
    'acceptance.schema.json', 'job.schema.json', 'manifest.schema.json',
    'model-authority.schema.json', 'model-selection.schema.json',
    'planning-direct.schema.json', 'planning-job.schema.json',
    'planning-policy.schema.json', 'planning-subject.schema.json',
    'stage.schema.json', 'worker-brief.schema.json', 'workers-config.schema.json',
}
PLANNING_WORKERS = {
    'agent-tuneup/config-verifier', 'ape/synthesizer', 'babysitter/pr-reviewer',
    'elephant-goldfish/plan-reviewer', 'focus-group/plan-reviewer',
    'imps/reviewer', 'ralph/strategy-reviewer', 'plan/plan-reviewer',
}
WORKER_SLICES = {
    9: [('Mutation input includes', 'Shared library callers')],
    10: [('Normal briefs carry', ' Plan revisions')],
    11: [('Each attempt brief', 'It may also declare')],
    12: [('The complete bytes pass', None)],
    13: [('Initial pass 0', '\nFailed slots'),
         ('Original briefs, results', 'Cancellation/discard')],
    14: [('Host identity is separate', None)],
    15: [('Review and document-only slots refuse', ' If a forbidden'),
         ('Acceptance never', None)],
    16: [('A pre-check semantic generation', ' Execution and acceptance'),
         ('Hand-edited accepted flags', ' The complete')],
    17: [('They\nestablish record provenance', ' Imps final plans'),
         ('Live provider fidelity remains', None)],
    18: [('These input contracts cannot', None)],
    20: [('A finding ID reused', '; pass'),
         ('Identical re-reports share one row.', ' It verifies'),
         ('Deferred blocker/major findings', ' Removed logical slots'),
         ('A follow-up brief takes', ' Only a fresh preparation')],
    22: [('result transport remains', '\nPersisted job state')],
    25: [('Result transports, briefs', None)],
    28: [('Required reviews compare', None)],
    29: [('A review slot', '`reviewed_documents`'),
         ('A document-only\nreview names', ' Both forms'),
         ('Preparation and acceptance re-hash', ' For document subjects'),
         ('The\nreviewer lineage', ' A factual slot'),
         ('A factual slot', None)],
    30: [('Author-independent jobs require', ' `create` imports'),
         ('Without a matching record', '\n`plan-revision`'),
         ('A direct cold-read', ' Re-recording'),
         ('Once enabled,', None)],
    33: [('Observed identity may use', ' Stage acceptance'),
         ('The handle stays', ' Any later reading'),
         ('It never covers review', ' A redelivered completion')],
    35: [('A task can declare', ' Validators must')],
    36: [('Waiver decisions name', ' Settings apply'),
         ('Host actor', None)],
}
# Reasons cover the excluded portions of each frozen jobs-contract block, in
# addition to the precise UTF-8 spans computed below. These are policy authored
# from the original protocol, not candidate-generated expected dispositions.
JOBS_COORDINATOR = {
    1: 'Title of the coordinator state protocol; no worker instruction.',
    2: 'Coordinator state-root, CLI invocation, pinned recovery and adapter invocation.',
    3: 'Coordinator job creation, dependencies, graph and frozen policy construction.',
    4: 'Heading for coordinator resume and capacity operations.',
    5: 'Coordinator paginated overview/status cursors and freshness bookkeeping.',
    6: 'Coordinator admission/capacity reservations and owner-bound cap revisions.',
    7: 'Coordinator host-refusal and owned-completion retry accounting.',
    8: 'Coordinator derived metrics, notification deduplication and decision timing.',
    9: 'Coordinator mutation caller construction and library pin-verifier plumbing; worker evidence scope retained.',
    10: 'Coordinator command catalog, owner-source authentication limits, plan/adoption revisions and staleness propagation; task-scoped decisions retained.',
    11: 'Coordinator prepare invocation/output and context-file admission/rehashing; immutable task and isolated-context content retained without granting a new read.',
    12: 'Coordinator completion transport wrapper; strict whole-result, waiver, metric and no-reset rules retained.',
    13: 'Coordinator per-pass charging, reservations, host observations, retry/follow-up launch and cancellation reconciliation; shared allowance and immutable evidence retained.',
    14: 'No excluded text: actual identity evidence, target separation and sticky mismatch remain inline.',
    15: 'Coordinator quarantine ingestion, handle reconciliation and charged retry; follow-up refusal and no quarantine acceptance retained.',
    16: 'Coordinator acceptance APIs, descriptor construction, receipt/pass accounting, commit-generation rechecks, validator limits and process-group handling; precheck binding and ready-result conditions retained.',
    17: 'Coordinator observation canonicalization, final-plan coverage and reopen accounting; provenance limits and no inferred live fidelity retained.',
    18: 'Coordinator adopter contract declaration, sequence observations, final-plan graph/snapshot validation and apply criteria; returned results cannot weaken contracts.',
    19: 'Coordinator observation publishing and direct-versus-worker stage membership checks.',
    20: 'Coordinator disposition API, evidence freezing, removed-slot budgets, host reconciliation and stale preparation; finding variants, unresolved deferrals, no job edits and unchanged follow-up authority retained.',
    21: 'Coordinator cross-workflow adapter input declarations and validators; only the assigned workflow evidence obligations are retained.',
    22: 'Coordinator bounded state/status reads, validator process groups, conflicting pin policy and overview fields; worker transport limit retained.',
    23: 'Coordinator criterion/validator-contract revision decision.',
    24: 'Coordinator runtime-owned revision fields, immutable decisions and handle settlement.',
    25: 'Coordinator historical ID reservations, completion deduplication, slot removal and brief-path allocation; create-exclusive evidence and no rebinding retained.',
    26: 'Coordinator/owner physical-path enforcement and privileged-actor trust limits.',
    27: 'Coordinator outer request correlation, late-result ingestion and malformed-completion charging.',
    28: 'No excluded text: required-review target and lineage restrictions remain inline.',
    29: 'Coordinator document file admission and author-record construction; exact review subjects, immutable hashes, author lineage, unknown-author refusal and observed identity restrictions remain inline.',
    30: 'Coordinator author sidecars, import/union/revision and direct-execution/waiver APIs; missing-author limits, no direct cold fallback and non-disableable independence retained.',
    31: 'Coordinator sidecar ordering, copy/move provenance and forged-record trust limits.',
    32: 'Coordinator document-revision capabilities, authorship propagation, retry and direct factual execution APIs.',
    33: 'Coordinator identity-exception decision construction, observation redelivery and reconciliation; observed sources, sticky mismatch, review exception prohibition, target separation and verification conditions remain inline.',
    34: 'Coordinator conflicting-host quarantine, uncertainty reconciliation, owner-source revalidation and bounded state reads.',
    35: 'Coordinator partial-policy revision, exact adapter criterion IDs and integrated coverage; required-review adverse/unavailable block retained.',
    36: 'Coordinator settings-apply observation/adoption recording; worker waiver restrictions and enforcement evidence limits retained.',
}
REVIEW_SLICES = {
    4: [('Bind declared evidence', None)],
    5: [("Consume the coordinator's frozen choices", ' under `shared/model-selection.md`'),
        ('; do not\nask a nested chooser', 'Recommend judgement-capable'),
        ('Requested settings', None)],
    7: [('Retain attempts, failures', None)],
}
REVIEW_COORDINATOR = {
    4: 'Coordinator constructs the frozen source/request/selection/authority snapshot. Worker evidence binding, unexpected-read reconciliation and cold isolation remain literal.',
    5: 'Coordinator recommends and selects target capabilities/options; worker consumes the frozen choice and cannot choose again. Requested settings and observed identity remain distinct.',
    7: 'Coordinator fresh-worker selection and authorised availability-chain dispatch; worker retains actual attempts/mode and stronger lineage restrictions without replacement authority.',
}
# Cold clauses are source excerpts. These independent boundary markers identify
# worker duties while excluding state commands, jobs-history and owner records.
COLD_SLICES = {
    9: [('Coordinators alone prepare', 'Shared library callers')],
    10: [('Document-only\nbriefs retain', ' Plan revisions')],
    11: [('A `document-only` task supplies', 'It may also declare')],
    12: [('The complete bytes pass', 'Duplicate completions')],
    13: [('Original briefs, results', 'Cancellation/discard')],
    14: [('Host identity is separate', 'Redelivered completion')],
    15: [('Review and document-only slots refuse', ' If a forbidden')],
    16: [('Changed input during checks', ' Execution and acceptance')],
    17: [('Live provider fidelity remains', None)],
    18: [('These input contracts cannot', None)],
    20: [('Deferred blocker/major findings', ' Removed logical slots')],
    22: [('result transport remains', '\nPersisted job state')],
    25: [('Result transports, briefs', ' An owner plan decision')],
    28: [('Required reviews compare', None)],
    29: [('A document-only\nreview names', ' Both forms'),
         ('The\nreviewer lineage', ' A factual slot'),
         ('New jobs require verified', ' Approval still'),
         ('Approval still', None)],
    30: [('A direct cold-read', ' Re-recording'),
         ('Once enabled,', None)],
    33: [('Observed identity may use', ' Stage acceptance'),
         ('It never covers review', None)],
    35: [('A task can declare', ' Validators must')],
    36: [('Waiver decisions name', ' Settings apply')],
}


def excerpt(text, spans):
    parts = []
    for start, end in spans:
        part = text[text.index(start):]
        parts.append(part[:part.index(end)] if end else part.rstrip())
    return '\n'.join(parts)


def compact_schema(value):
    """Whitespace-only representation; no schema key or constraint is removed."""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def job_spans(worker, number):
    if worker['worker_id'] == 'elephant-goldfish/cold-reader':
        return COLD_SLICES.get(number, [])
    if number == 21:
        plugin = worker['plugin']
        return {
            'ape': [('Ape criteria declare', '\nBabysitter contracts')],
            'babysitter': [('Babysitter contracts declare', '\nDocument contracts')],
            'elephant-goldfish': [('Document contracts declare', ' Imps contracts')],
            'imps': [('Imps contracts bind', None)],
        }.get(plugin, [])
    return WORKER_SLICES.get(number, [])


def reviewer_extension(worker, text, include_recovery=False):
    if worker['worker_id'] not in {
            'babysitter/pr-reviewer', 'elephant-goldfish/plan-reviewer',
            'focus-group/plan-reviewer', 'imps/reviewer', 'ralph/strategy-reviewer',
            'plan/plan-reviewer', 'tests-omg/reviewer'}:
        return None
    parts = [excerpt(text, [('The coordinator marks a review `final`', 'Keep full required coverage'),
                            ('Keep full required coverage', 'For each blocking finding'),
                            ('Failed required checks', 'The final round does not begin')]),
             excerpt(text, [('Record safely deferrable improvements as minor/note',
                             'Preserve every original')]),
             excerpt(text, [('Re-review keeps full required coverage', 'Reuse unchanged evidence')])]
    if include_recovery:
        parts.append(excerpt(text, [('Apply [workflow recovery]', 'The coordinator batches supported repairs')]))
    return '\n'.join(parts)


def rule_justification(worker, row, clause, retained, source=None):
    """Exact per-worker source policy, including every excluded byte interval."""
    wid = worker['worker_id']
    name = Path(row['path']).name
    review_excerpt = (name == 'reviewer-standard.md' and retained is not None and
                      worker['worker_id'] != 'elephant-goldfish/cold-reader')
    if name != 'jobs-contract.md' and not review_excerpt:
        return None
    raw = source_bytes(row) if source is None else source
    text = raw[clause['start_byte']:clause['end_byte']].decode()
    if clause['id'].startswith('extension-'):
        if name == 'jobs-contract.md':
            return (wid + ': ' + clause['id'] + ' source=' + row['sha256'] +
                    '; upstream author-provenance and commit-guard operations are coordinator-owned; worker authority is unchanged.')
        if name == 'reviewer-standard.md':
            if clause['id'] == 'extension-v2':
                return (wid + ': extension-v2 source=' + row['sha256'] +
                        ('; preserve workflow recovery checkpoints and the task-artifact/stage boundary when reviewing PR maintenance.'
                         if wid == 'babysitter/pr-reviewer' else
                         '; recovery counters, state and dispatch are coordinator-owned; this reviewer role does not operate the workflow.'))
            return (wid + ': ' + clause['id'] + ' source=' + row['sha256'] +
                    '; retain only the source-bound reviewer triage excerpt applicable to this role; coordinator retry, filing and operator procedures stay coordinator-only.')
    number = int(clause['id'].split('-')[-1])
    if review_excerpt and number not in REVIEW_SLICES:
        return None
    intervals = []
    spans = REVIEW_SLICES[number] if review_excerpt else job_spans(worker, number)
    for start, end in spans:
        lo = text.index(start)
        hi = text.index(end, lo) if end else len(text.rstrip())
        intervals.append((len(text[:lo].encode()), len(text[:hi].encode())))
    # Ranges are absolute half-open UTF-8 byte offsets into the hash-bound source.
    included, excluded, cursor = [], [], 0
    for lo, hi in sorted(intervals):
        if lo < cursor:
            raise ValueError('overlapping worker policy spans')
        if lo > cursor:
            excluded.append([clause['start_byte'] + cursor, clause['start_byte'] + lo])
        included.append([clause['start_byte'] + lo, clause['start_byte'] + hi])
        cursor = hi
    if cursor < len(text.encode()):
        excluded.append([clause['start_byte'] + cursor, clause['end_byte']])
    cold = wid == 'elephant-goldfish/cold-reader'
    reason = (('Document-only policy excludes coordinator commands, job/history reads, '
               'repository work, ordinary prior objections and artifact writes. ')
              if cold else '') + (REVIEW_COORDINATOR[number] if review_excerpt else JOBS_COORDINATOR[number])
    if number == 21 and not cold:
        reason += ' Assigned workflow: ' + worker['plugin'] + '; other workflow declarations are unassigned.'
    return (wid + ': ' + clause['id'] + ' source=' + row['sha256'] +
            '; literal retained UTF-8 spans=' + json.dumps(included, separators=(',', ':')) +
            '; excluded coordinator/unassigned spans=' + json.dumps(excluded, separators=(',', ':')) +
            '. ' + reason + ' No omitted-source lookup is permitted.')


def allowed_rule(worker, row, clause, source=None):
    """Independent source-based semantic oracle; no candidate values are inputs."""
    raw = source_bytes(row) if source is None else source
    text = raw[clause['start_byte']:clause['end_byte']].decode()
    wid = worker['worker_id']
    cold = wid == 'elephant-goldfish/cold-reader'
    number = int(clause['id'].split('-')[-1]) if clause['id'].startswith('block-') else 0
    name = Path(row['path']).name
    if row['kind'] == 'composer-framing':
        return FRAMING
    if row['kind'] == 'specialized-definition' or name == 'boundaries.md':
        return text
    if row['kind'] == 'shared-schema':
        if name in COORDINATOR_SCHEMAS:
            return None
        if name == 'planning-assessment.schema.json':
            return compact_schema(json.loads(text)) if wid in PLANNING_WORKERS else None
        if name == 'result-envelope.schema.json':
            # Keep the actual envelope shape; the duplicated full result is already
            # inline. Cold readers cannot write the artifact an envelope needs.
            return None if cold else compact_schema(json.loads(text)['oneOf'][1])
        if name == 'worker-result.schema.json':
            return compact_schema(json.loads(text))
        raise ValueError('unclassified schema')
    if name == 'jobs-contract.md':
        if clause['id'].startswith('extension-'):
            return None
        spans = job_spans(worker, number)
        if not spans:
            return None
        if cold:
            retained = excerpt(text, COLD_SLICES[number])
            if number == 33:
                retained = retained.replace('It never covers review',
                                            'An identity-exception decision never covers review')
            return retained
        return excerpt(text, spans)
    if name == 'reviewer-standard.md':
        definition = (ROOT / worker['definition_path']).read_text()
        applies = 'reviewer-standard.md' in definition or wid in PLANNING_WORKERS
        if not applies:
            return None
        if clause['id'].startswith('extension-'):
            if clause['id'] == 'extension-v2':
                return (excerpt(text, [('Apply [workflow recovery]', None)])
                        if wid == 'babysitter/pr-reviewer' else None)
            return reviewer_extension(worker, text)
        if not cold:
            if number == 5:
                # The frozen choice is consumed inline; model-selection.md is not
                # a required external instruction load in this procedure.
                return excerpt(text, REVIEW_SLICES[number])
            if number in REVIEW_SLICES:
                return excerpt(text, REVIEW_SLICES[number])
            return text
        if number == 1:
            return text
        if number == 4:
            return excerpt(text, [('Cold readers remain', None)])
        if number == 5:
            return excerpt(text, REVIEW_SLICES[number])
        if number == 6:
            return excerpt(text, [('Use strict result/correlation', 'Repairs need')])
        if number == 7:
            return excerpt(text, [('Same-lineage and self-review', None)])
        if number == 9:
            return excerpt(text, [('Keep plan review', None)])
        # Ordinary prior-objection, report-history and repository-review duties
        # are coordinator-only for this isolated role, never optional reads.
        return None
    raise ValueError('unclassified source')


def procedure(worker, rules):
    # All allowed instruction text is present literally. No descriptor authorizes
    # loading omitted material. The role-specific definition narrows shared rules.
    text = ('# Proposed retained procedure\n'
            'The specialized definition narrows shared instructions.\n')
    if worker['worker_id'] == 'elephant-goldfish/cold-reader':
        text += ('The cold-reader role reads only its supplied document and explicitly declared context; '
                 'it receives no history or prior objections and never writes files.\n')
    text += '\n'
    # Preserve the full original specialized definition as contiguous literal
    # text. Other identical blocks may share one physical copy, while every
    # source rule and binding remains independently present in the manifest.
    definition = (ROOT / worker['definition_path']).read_text()
    text += definition
    seen = set()
    for rule in rules:
        if rule['disposition'] != 'inline' or rule['source_id'] == worker['definition_path']:
            continue
        block = rule['inline_text']
        if block in seen:
            continue
        seen.add(block)
        text += '\n\n' + block
    text += ('\n\nUse only assigned requirements, constraints, authority, paths, stop conditions and '
             'artifacts in the immutable brief. Stop on missing input or binding mismatch. '
             'Never load omitted contracts. '
             'Copy schema_version, job_id, stage_id, logical_slot_id, request_id, worker_id, '
             'effective_brief_sha256 and revision exactly; binding is the brief snapshot. '
             'Keep the exact model-selection digest/options and execution identity distinct '
             'from requested targets. Redact secrets, credentials, private hostnames and '
             'transcripts. Inline result transport is at most 32768 bytes; use only a '
             'declared artifact destination and its pinned byte limit, default 16 MiB. '
             'Document-only no-write rules dominate artifact transport.\n')
    for path in RUBRICS.get(worker['worker_id'], []):
        raw = (ROOT / path).read_bytes()
        if sha(raw) != RUBRIC_HASHES[path]:
            raise ValueError('domain rubric source changed: ' + path)
        text += ('\n\n# Domain rubric for the separate planning-review mode\n'
                 'Apply only when the immutable brief assigns that mode, within this worker scope.\n' +
                 raw.decode())
    return text


def applicable_sources(worker, frozen):
    wanted = {worker['definition_path'], *worker['worker_shared'],
              'shared/worker_registry.py::compose_worker'}
    return [row for row in frozen['sources'] if row['source_id'] in wanted]


def source_binding(frozen):
    return sha(canonical({'sources': frozen['sources'], 'manifests': frozen['manifests'],
                          'domain_rubrics': RUBRIC_HASHES}))


def validate_manifest(candidate):
    """Fail closed against declarations, frozen source bytes and literal procedures."""
    historical = baseline()
    frozen = current_generation()
    if sha(SCHEMA.read_bytes()) != SCHEMA_HASH:
        raise ValueError('reviewed schema changed')
    failures = errors(candidate, json.loads(SCHEMA.read_text()))
    if failures:
        raise ValueError('schema: ' + str(failures[:3]))
    actual_workers, actual_assets = [], set()
    for path in sorted((ROOT / 'plugins').glob('*/plugin.json')):
        meta = registry.load_manifest(path.parent)
        for worker in meta.get('workers', []):
            actual_workers.append(worker['id'])
            actual_assets.update('shared/agents/' + x for x in meta['worker_shared'])
    if sorted(actual_workers) != sorted(w['worker_id'] for w in frozen['workers']):
        raise ValueError('declared worker set changed')
    if actual_assets != set(frozen['shared_assets']):
        raise ValueError('declared shared asset set changed')
    for row in historical['manifests']:
        raw = git_blob(historical['source_revision'], row['path'])
        if sha(raw) != row['sha256'] or json.loads(raw)['worker_shared'] != row['worker_shared']:
            raise ValueError('immutable historical manifest changed: ' + row['path'])
    for row in frozen['manifests']:
        raw = (ROOT / row['path']).read_bytes()
        pinned = git_blob(frozen['source_revision'], row['path'])
        if (sha(pinned) != row['sha256'] or
                version_neutral_manifest(raw) != version_neutral_manifest(pinned) or
                json.loads(raw)['worker_shared'] != row['worker_shared']):
            raise ValueError('base manifest/worker_shared changed')
    original_sources = {}
    for row in historical['sources']:
        raw = git_source(historical['source_revision'], row)
        if sha(raw) != row['sha256'] or len(raw) != row['bytes']:
            raise ValueError('immutable historical source changed: ' + row['source_id'])
        for clause in row['clauses']:
            if sha(raw[clause['start_byte']:clause['end_byte']]) != clause['sha256']:
                raise ValueError('immutable historical clause changed')
    for row in frozen['sources']:
        raw = source_bytes(row)
        if sha(raw) != row['sha256'] or len(raw) != row['bytes']:
            raise ValueError('current source changed: ' + row['source_id'])
        for clause in row['clauses']:
            if sha(raw[clause['start_byte']:clause['end_byte']]) != clause['sha256']:
                raise ValueError('current source clause changed: ' + row['source_id'])
        original_sources[row['source_id']] = raw
    if candidate['sources'] != frozen['sources']:
        raise ValueError('source or clause set/binding differs from reviewed source extension')
    if candidate['source_set_sha256'] != source_binding(frozen):
        raise ValueError('source set binding differs')
    profiles = candidate['profiles']
    if sorted(p['id'] for p in profiles) != sorted(actual_workers):
        raise ValueError('missing, extra or duplicate worker profile')
    if {p['kind'] for p in profiles} != set(frozen['required_profiles']):
        raise ValueError('missing or extra class')
    for worker in frozen['workers']:
        wid = worker['worker_id']
        profile = next(p for p in profiles if p['id'] == wid)
        if profile['worker_ids'] != [wid] or profile['kind'] != KINDS.get(wid, 'ordinary'):
            raise ValueError('worker/class association changed')
        expected = {}
        for row in applicable_sources(worker, frozen):
            raw = original_sources[row['source_id']]
            for clause in row['clauses']:
                expected[(row['source_id'], clause['id'])] = allowed_rule(worker, row, clause, source=raw)
        rules = profile['rules']
        keys = [(r['source_id'], r['clause_id']) for r in rules]
        if len(keys) != len(set(keys)) or set(keys) != set(expected):
            raise ValueError('missing/extra asset or clause disposition')
        for rule in rules:
            allowed = expected[(rule['source_id'], rule['clause_id'])]
            if rule['disposition'] != ('inline' if allowed is not None else 'coordinator-only'):
                raise ValueError('essential or coordinator-only disposition differs from explicit policy')
            if not rule['justification'].startswith(wid + ': '):
                raise ValueError('missing per-profile justification')
            row = next(r for r in frozen['sources'] if r['source_id'] == rule['source_id'])
            clause = next(c for c in row['clauses'] if c['id'] == rule['clause_id'])
            reason = rule_justification(worker, row, clause, allowed,
                                        source=original_sources[row['source_id']])
            if reason is not None and rule['justification'] != reason:
                raise ValueError('mixed clause exclusion policy/spans differ')
            if row['kind'] == 'shared-schema' and allowed is not None:
                # Independent object equality over the actual frozen source,
                # including every keyword, bound, enum, ref and output field.
                original = json.loads(original_sources[row['source_id']])
                if Path(row['path']).name == 'result-envelope.schema.json':
                    original = original['oneOf'][1]
                if json.loads(rule.get('inline_text', 'null')) != original:
                    raise ValueError('inline schema changes original constraints')
            if rule.get('inline_text') != allowed:
                raise ValueError('required text weakened or replaced with a descriptor')
        delivered = profile['procedure']
        # Literal equality rejects added read authority and history/provenance leaks,
        # including attacks that preserve lengths and recompute candidate hashes.
        if delivered['text'] != procedure(worker, rules):
            raise ValueError('procedure differs from retained rules and applicable inline rubric')
        raw = delivered['text'].encode()
        if delivered['sha256'] != sha(raw) or delivered['bytes'] != len(raw):
            raise ValueError('procedure binding differs')
        contract = ROOT / 'shared/agents' / worker['output_contract']
        if profile['result_contract_sha256'] != sha(contract.read_bytes()):
            raise ValueError('result contract binding differs')
    return frozen


class WorkerRetentionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidate = json.loads(MANIFEST.read_text())

    def test_complete_public_source_and_procedure_mapping(self):
        frozen = validate_manifest(self.candidate)
        historical = baseline()
        self.assertEqual(len(historical['workers']), 18)
        self.assertEqual(len(historical['sources']), 37)
        self.assertEqual(sum(len(s['clauses']) for s in historical['sources']), 295)
        self.assertEqual(len(frozen['workers']), 20)
        self.assertEqual(len(frozen['sources']), 39)
        self.assertEqual(sum(len(s['clauses']) for s in frozen['sources']), 261)
        self.assertEqual(len(frozen['shared_assets']), 18)
        self.assertEqual(sum(s['kind'] == 'shared-schema' for s in frozen['sources']), 15)
        prior = git_blob(extension()['source_revision'], 'shared/agents/reviewer-standard.md')
        current = git_blob(extension_v2()['source_revision'], 'shared/agents/reviewer-standard.md')
        row = next(s for s in frozen['sources'] if s['source_id'] == 'shared/agents/reviewer-standard.md')
        added = next(c for c in row['clauses'] if c['id'] == 'extension-v2')
        self.assertEqual(current[:added['start_byte']] + current[added['end_byte']:], prior)
        self.assertEqual(sha(current[added['start_byte']:added['end_byte']]), added['sha256'])
        retained_profiles = {profile['id']: profile for profile in self.candidate['profiles']}
        reviewers = [profile for profile in retained_profiles.values()
                     if any(rule['source_id'] == row['source_id']
                            and rule['clause_id'] == 'extension-v2'
                            for rule in profile['rules'])]
        self.assertTrue(reviewers)
        for profile in reviewers:
            rule = next(rule for rule in profile['rules']
                        if rule['source_id'] == row['source_id']
                        and rule['clause_id'] == 'extension-v2')
            self.assertEqual(rule['disposition'],
                             'inline' if profile['id'] == 'babysitter/pr-reviewer'
                             else 'coordinator-only')
            self.assertEqual('Apply [workflow recovery]' in profile['procedure']['text'],
                             profile['id'] == 'babysitter/pr-reviewer')
        self.assertTrue({w['worker_id'] for w in historical['workers']}.issubset(
            {w['worker_id'] for w in frozen['workers']}))
        for path in (BASELINE, EXTENSION, EXTENSION_V2, MANIFEST, SCHEMA):
            self.assertNotIn('/' + 'home/', path.read_text())
            self.assertNotIn('/scratch/', path.read_text())

    def reject(self, mutate):
        candidate = copy.deepcopy(self.candidate)
        mutate(candidate)
        with self.assertRaises(ValueError):
            validate_manifest(candidate)

    def test_missing_extra_and_duplicate_source_and_clause(self):
        for key in ('sources',):
            self.reject(lambda c: c[key].pop())
            self.reject(lambda c: c[key].append(copy.deepcopy(c[key][0])))
        self.reject(lambda c: c['sources'][0]['clauses'].pop())
        self.reject(lambda c: c['sources'][0]['clauses'].append(copy.deepcopy(c['sources'][0]['clauses'][0])))
        self.reject(lambda c: c['sources'][0].update(sha256='0' * 64))
        self.reject(lambda c: c['sources'][0].update(path='shared/agents/boundaries.md'))
        self.reject(lambda c: c.update(source_set_sha256='0' * 64))

    def test_missing_extra_worker_class_and_asset(self):
        self.reject(lambda c: c['profiles'].pop())
        self.reject(lambda c: c['profiles'].append(copy.deepcopy(c['profiles'][0])))
        self.reject(lambda c: c['profiles'][0]['worker_ids'].append('imps/nonexistent'))
        self.reject(lambda c: c['profiles'][0].update(kind='ordinary'))
        self.reject(lambda c: c['profiles'][0].update(id='extra/worker'))
        for source in baseline()['shared_assets']:
            def remove(c):
                c['profiles'][0]['rules'] = [r for r in c['profiles'][0]['rules'] if r['source_id'] != source]
            self.reject(remove)
        self.reject(lambda c: c['profiles'][0]['rules'].append(copy.deepcopy(c['profiles'][0]['rules'][0])))

    def test_every_rule_requires_reviewed_disposition_and_content(self):
        # Exercise every current source clause while the immutable predecessor is
        # checked separately against all 295 original source clauses above.
        for source in current_generation()['sources']:
            for clause in source['clauses']:
                def change(c):
                    rule = next(r for p in c['profiles'] for r in p['rules']
                                if (r['source_id'], r['clause_id']) == (source['source_id'], clause['id']))
                    if rule['disposition'] == 'inline':
                        rule['inline_text'] = 'See immutable source descriptor.'
                    else:
                        rule.update(disposition='optional-reference',
                                    inline_text='Load the source to perform this task.')
                self.reject(change)
        for profile_index in range(len(self.candidate['profiles'])):
            self.reject(lambda c: c['profiles'][profile_index]['rules'].pop())
        for disposition in ('coordinator-only', 'optional-reference'):
            self.reject(lambda c: c['profiles'][0]['rules'][0].update(disposition=disposition))

    def test_rehashed_authority_domain_descriptor_and_cold_leaks_fail(self):
        attacks = {
            'imps/stage-executor': [('cannot add permissions', 'can add permissions'),
                                    ('Do not dispatch children', 'You may dispatch children')],
            'agent-tuneup/config-verifier': [('Never apply, restore, edit', 'You may apply, restore, edit')],
            'focus-group/fidelity-reviewer': [('a hidden dissent', 'an omitted detail')],
            'elephant-goldfish/cold-reader': [
                ('You receive no job', 'You may read the job'),
                ('Do not open the repository', 'You may open the repository'),
                ('Quote only the document.', 'Read prior objections in the job history.'),
                ('Do not write files.', 'See the full job and registry for required instructions.')],
        }
        for wid, replacements in attacks.items():
            for old, new in replacements:
                def change(c):
                    p = next(p for p in c['profiles'] if p['id'] == wid)['procedure']
                    self.assertIn(old, p['text'])
                    p['text'] = p['text'].replace(old, new)
                    p.update(sha256=sha(p['text'].encode()), bytes=len(p['text'].encode()))
                self.reject(change)
        self.reject(lambda c: c['profiles'][0]['procedure'].update(sha256='0' * 64))
        self.reject(lambda c: c['profiles'][0].update(result_contract_sha256='0' * 64))

    def test_actual_planning_assignments_and_all_domain_obligations(self):
        assigned = set()
        for path in (ROOT / 'plugins').glob('*/plugin.json'):
            meta = json.loads(path.read_text())
            if meta.get('planning_review'):
                assigned.add(meta['planning_review']['worker_id'])
        self.assertEqual(assigned, PLANNING_WORKERS)
        self.assertNotIn('imps/auditor', RUBRICS)
        for wid, paths in RUBRICS.items():
            for path in paths:
                def remove(c):
                    p = next(p for p in c['profiles'] if p['id'] == wid)['procedure']
                    text = (ROOT / path).read_text()
                    self.assertIn(text, p['text'])
                    p['text'] = p['text'].replace(text, 'See the rubric descriptor.')
                    p.update(sha256=sha(p['text'].encode()), bytes=len(p['text'].encode()))
                self.reject(remove)

    def test_forged_coordinator_essential_and_unassigned_schema_refuse(self):
        for index, profile in enumerate(self.candidate['profiles']):
            for source in ('shared/agents/boundaries.md', 'shared/agents/worker-result.schema.json',
                           'shared/worker_registry.py::compose_worker'):
                def forge(c):
                    rule = next(r for r in c['profiles'][index]['rules'] if r['source_id'] == source)
                    rule.update(disposition='coordinator-only', justification=profile['id'] + ': coordinator owns this')
                    rule.pop('inline_text', None)
                self.reject(forge)
        cold = next(p for p in self.candidate['profiles'] if p['kind'] == 'document-only')
        self.assertFalse(any(r['disposition'] == 'optional-reference' for r in cold['rules']))
        for name in ('job.schema.json', 'workers-config.schema.json', 'planning-subject.schema.json'):
            self.assertNotIn((ROOT / 'shared/agents' / name).read_text(), cold['procedure']['text'])

    def test_mixed_worker_duties_cannot_be_reclassified_or_hidden(self):
        for index, profile in enumerate(self.candidate['profiles']):
            for rule_index, rule in enumerate(profile['rules']):
                if rule['source_id'] != 'shared/agents/jobs-contract.md':
                    continue
                if rule['disposition'] == 'inline':
                    def forge(c):
                        r = c['profiles'][index]['rules'][rule_index]
                        r.update(disposition='coordinator-only',
                                 justification=profile['id'] + ': coordinator owns all of this')
                        r.pop('inline_text')
                        p = c['profiles'][index]['procedure']
                        p['text'] = p['text'].replace(rule['inline_text'], '')
                        p.update(bytes=len(p['text'].encode()), sha256=sha(p['text'].encode()))
                    self.reject(forge)
                self.reject(lambda c: c['profiles'][index]['rules'][rule_index].update(
                    justification=profile['id'] + ': required duties summarized elsewhere'))

    def test_rehashed_real_schema_constraint_removal_and_weakening_refuse(self):
        # These edits alter real constraints, never whitespace or length alone.
        changes = [
            ('worker-result.schema.json', lambda s: s['required'].remove('binding')),
            ('worker-result.schema.json', lambda s: s['properties']['status']['enum'].append('approved')),
            ('worker-result.schema.json', lambda s: s.update(additionalProperties=True)),
            ('worker-result.schema.json', lambda s: s['properties']['effective_brief_sha256'].pop('pattern')),
            ('worker-result.schema.json', lambda s: s['properties']['metrics']['additionalProperties']['oneOf'][1]['properties']['reason'].pop('minLength')),
            ('planning-assessment.schema.json', lambda s: s['properties']['coverage']['items']['required'].remove('evidence')),
            ('result-envelope.schema.json', lambda s: s['properties']['artifact']['properties']['finding_count'].pop('minimum')),
            ('result-envelope.schema.json', lambda s: s['properties']['artifact']['required'].remove('sha256')),
        ]
        for name, mutation in changes:
            def attack(c):
                p = next(p for p in c['profiles'] if any(
                    r['source_id'] == 'shared/agents/' + name and r['disposition'] == 'inline'
                    for r in p['rules']))
                r = next(r for r in p['rules'] if r['source_id'] == 'shared/agents/' + name)
                old = r['inline_text']
                shape = json.loads(old)
                mutation(shape)
                r['inline_text'] = compact_schema(shape)
                p['procedure']['text'] = p['procedure']['text'].replace(old, r['inline_text'])
                raw = p['procedure']['text'].encode()
                p['procedure'].update(bytes=len(raw), sha256=sha(raw))
            self.reject(attack)

    def test_frozen_sources_schema_and_binding_tamper_refuse(self):
        original = source_bytes
        for source in current_generation()['sources']:
            def changed(row):
                raw = original(row)
                return raw + b'changed' if row['source_id'] == source['source_id'] else raw
            with mock.patch(__name__ + '.source_bytes', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'extension source differs from pinned base|current source changed'):
                    validate_manifest(self.candidate)
        reader = Path.read_bytes
        for target, diagnostic in ((SCHEMA, 'reviewed schema changed'),
                                   (BASELINE, 'immutable baseline changed'),
                                   (EXTENSION, 'retention extension changed')):
            with mock.patch.object(Path, 'read_bytes', lambda p: reader(p) + b' ' if p == target else reader(p)):
                with self.assertRaisesRegex(ValueError, diagnostic):
                    validate_manifest(self.candidate)

    def test_declared_inline_shapes_have_no_unresolved_refs(self):
        def walk(value, root):
            if isinstance(value, dict):
                if '$ref' in value:
                    ref = value['$ref']
                    self.assertTrue(ref.startswith('#/'), 'external required schema reference')
                    resolved = root
                    for key in ref[2:].split('/'):
                        resolved = resolved[key.replace('~1', '/').replace('~0', '~')]
                for child in value.values():
                    walk(child, root)
            elif isinstance(value, list):
                for child in value:
                    walk(child, root)
        for profile in self.candidate['profiles']:
            for rule in profile['rules']:
                if rule['disposition'] == 'inline' and rule['source_id'].endswith('.schema.json'):
                    value = json.loads(rule['inline_text'])
                    walk(value, value)

    def test_declared_procedures_keep_full_definitions_rules_and_header_headroom(self):
        # Design-fitness metadata only. No serialized compact brief/A5 acceptance.
        for worker in current_generation()['workers']:
            profile = next(p for p in self.candidate['profiles'] if p['id'] == worker['worker_id'])
            text = profile['procedure']['text']
            self.assertIn((ROOT / worker['definition_path']).read_text(), text)
            for rule in profile['rules']:
                if rule['disposition'] == 'inline':
                    self.assertIn(rule['inline_text'], text)
            self.assertLessEqual(profile['procedure']['bytes'], 24576 - 512)

    def test_original_composition_byte_identity_including_customization_and_contract(self):
        for worker in baseline()['workers']:
            shared = [(f'shared/{Path(p).name}', subprocess.check_output(
                ['git', 'show', baseline()['source_revision'] + ':' + p], cwd=ROOT))
                      for p in worker['worker_shared']]
            for custom, contract in [('', None), ('Advisory expertise only.', 'Task authority is read-only.\n')]:
                definition = subprocess.check_output(
                    ['git', 'show', baseline()['source_revision'] + ':' + worker['definition_path']], cwd=ROOT)
                actual = registry.compose_worker(shared, definition,
                                                 custom, contract.encode() if contract else None)
                self.assertEqual(actual.encode(), original_definition(worker, custom, contract).encode())
                self.assertFalse(any(name in actual for name in PACKAGE_ADDITIONS))

    def test_installed_public_v1_inspection_exact_package_delta_and_pins(self):
        # Original mapping derives from the frozen revision, never source_files or
        # the retention manifest under test. Delivery 1's four additions are explicit.
        historical = baseline()
        frozen = current_generation()
        tracked = subprocess.run(['git', 'ls-tree', '-r', '--name-only', historical['source_revision']],
                                 cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
        current_tracked = subprocess.run(['git', 'ls-tree', '-r', '--name-only', frozen['source_revision']],
                                         cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
        with tempfile.TemporaryDirectory(prefix='worker-retention-') as td:
            temp = Path(td)
            foreign = temp / 'foreign'; foreign.mkdir()
            env = dict(os.environ, HOME=str(temp / 'home'), XDG_CONFIG_HOME=str(temp / 'config'),
                       XDG_STATE_HOME=str(temp / 'state'), PYTHONDONTWRITEBYTECODE='1')
            for meta_path in sorted((ROOT / 'plugins').glob('*/plugin.json')):
                plugin = meta_path.parent.name
                prefix, agents = temp / plugin / 'prefix', temp / plugin / 'agents'
                command = [sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', plugin,
                           '--prefix', str(prefix), '--agents-root', str(agents)]
                result = subprocess.run(command, cwd=foreign, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                package = Path(json.loads(result.stdout)['data']['version_dir'])
                receipt = json.loads((package / 'install-manifest.json').read_text())
                expected = {p for p in set(tracked) | set(current_tracked)
                            if p.startswith(('core/', 'shared/'))}
                expected.update(p[len('plugins/' + plugin + '/'):] for p in set(tracked) | set(current_tracked)
                                if p.startswith('plugins/' + plugin + '/'))
                if plugin == 'agent-tuneup':
                    expected.update(INVENTORY_ADDITIONS)
                files = {r['path']: r for r in receipt['files']}
                self.assertEqual(set(files) - expected, PACKAGE_ADDITIONS)
                self.assertEqual(expected - set(files), set())
                registry.verify_package_files(package, receipt)
                for path in PACKAGE_ADDITIONS:
                    self.assertEqual(files[path]['sha256'], sha((ROOT / path).read_bytes()))
                    self.assertEqual((package / path).read_bytes(), (ROOT / path).read_bytes())
                workers = [w for w in frozen['workers'] if w['plugin'] == plugin]
                if not workers:
                    continue
                bundle = json.loads((Path(receipt['bundle_dir']) / 'manifest.json').read_text())
                self.assertEqual({a['path'] for a in bundle['assets'] if a['path'].startswith('shared/')},
                                 {'shared/' + Path(p).name for p in workers[0]['worker_shared']})
                config = temp / plugin / 'workers.json'
                for worker in workers:
                    shown_result = subprocess.run(
                        [sys.executable, str(ROOT / 'scripts/catalog.py'), '--prefix', str(prefix),
                         '--agents-root', str(agents), 'agents', 'show', plugin,
                         worker['worker_id'].split('/')[1]],
                        cwd=foreign, env=env, capture_output=True, text=True)
                    self.assertEqual(shown_result.returncode, 0, shown_result.stdout + shown_result.stderr)
                    shown = json.loads(shown_result.stdout)
                    self.assertEqual(shown['definition'].encode(), current_definition(worker).encode())
                # Public job pinning must not transmit coordinator-only additions.
                job = temp / plugin / 'job.json'
                job.write_text(json.dumps({'schema_version': 1, 'dependencies': [{'key': 'stage', 'plugin': plugin}]}))
                pins = registry.snapshot_pins(job, {'stage': plugin}, prefix, agents, config)['pins']['stage']
                self.assertEqual(set(pins['shared']), {Path(p).name for p in workers[0]['worker_shared']})
                for worker in workers:
                    self.assertEqual(pins['effective_workers'][worker['worker_id']]['bytes'].encode(),
                                     current_definition(worker).encode())
                # Run a shipped helper from a foreign cwd; no source imports required.
                moved = temp / plugin / 'relocated-package'
                shutil.move(str(package), moved)
                result = subprocess.run([sys.executable, str(moved / 'shared/job_cli.py'), '--help'],
                                        cwd=foreign, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
