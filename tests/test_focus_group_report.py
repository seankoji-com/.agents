"""focus-group FG-4: faithful synthesis, prioritised backlog, fidelity review and local export.

One invented Pantry Planner study (two personas on two model lineages, four combined cells, a sanitised
capture pack whose quarantined parent carried a planted marker) is driven once through the real entry
points: `study.py`, `evidence.py`, `lifecycle.py` and `report.py` from the source plugin, and the generic
job helpers `shared/job_cli.py`, `shared/job_acceptance_cli.py` and the pinned `scripts/validate_study.py`
from a package installed into a temporary prefix. Each test restores that state and continues it. The
T3 host is invented: the tests transcribe the observations and complete worker results a coordinator
would record. Nothing calls a model, a browser, T3, imps or GitHub; nothing here says anything about live
provider compatibility, and fixture scanning shows only the tested refusal paths.
"""
import copy
import contextlib
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import focus_group_fixtures as fixtures  # noqa: E402
from tests import test_focus_group_lifecycle as fg3  # noqa: E402
from tests.test_focus_group_plan import BEFORE, FIXTURE_ORIGIN, provider, sha, target  # noqa: E402

REPORT = fg3.PLUGIN / 'scripts' / 'report.py'
CAPS = {'providers': [provider('claudeAgent', ['claude-fixture-swift']), provider('codex', ['gpt-fixture-one']),
                      provider('antigravity', ['gemini-fixture-pro'])]}
CLAUDE, GPT, GEMINI = (target('claudeAgent', 'claude-fixture-swift'), target('codex', 'gpt-fixture-one'),
                       target('antigravity', 'gemini-fixture-pro'))
ALL_CLASSES = ['stimulus', 'persona', 'participant-response', 'journey-evidence', 'analysis-report']
CLEAN_TEXT = fixtures.PAGE_TEXT
MARKER = 'api_key=PLANTEDFIXTURE0001'  # invented; it proves only the tested refusal path
STICKY = 'current task evidence is invalid: current execution has a sticky observed host identity mismatch'
PASS_SPENT = 'next acceptance pass requires charged worker repair'
STATE = {}


def setUpModule():
    STATE.clear()
    fg3.setUpModule()


def tearDownModule():
    for key in ('tmp',):
        if key in STATE:
            STATE[key].cleanup()
    fg3.tearDownModule()
    STATE.clear()


def ident(t):
    return {k: t[k] for k in ('providerInstanceId', 'model')}


class ReportHost(fg3.Host):
    """The FG-3 host with catalog-canonical lineages, a sanitised pack and FG-4 report entry points."""

    def __init__(self, base):
        super().__init__(base)
        self.caps = self.write('caps-report.json', CAPS)

    def catalog(self, now=BEFORE, caps=None, observations=None, observed_at=None):
        return super().catalog(now, caps or CAPS, observations, observed_at)

    def stimulus(self, study_id):
        """A sanitised derivative pack: its parent's page text carried a planted marker and was quarantined."""
        if study_id not in self.stimuli:
            folder = self.base / 'capture'
            parent_files = fixtures.write_pack(folder, text=CLEAN_TEXT + MARKER + '\n')
            parent = self.write('parent-manifest.json', fixtures.manifest(parent_files))
            code, out = self.call_evidence('pack', '--state-root', self.root, '--study', study_id, '--input', parent)
            assert (code, out['error']['code']) == (1, 'pack_quarantined'), out
            assert MARKER not in json.dumps(out), 'a refusal never prints the suspected value'
            clean = folder / 'welcome-clean.txt'
            clean.write_bytes(CLEAN_TEXT.encode())
            files = [f for f in parent_files if f['role'] != 'text'] + [
                {'name': clean.name, 'role': 'text', 'view': None, 'path': str(clean), 'sha256': sha(clean.read_bytes()),
                 'bytes': clean.stat().st_size, 'media_type': 'text/plain'}]
            derived = fixtures.manifest(files, derived_from={
                'manifest_sha256': out['data']['manifest_sha256'],
                'sanitisation': {'method': 'fixture: removed the planted line', 'performed_at': '2029-05-31T23:20:00Z'}})
            code, out = self.call_evidence('pack', '--state-root', self.root, '--study', study_id, '--input',
                                           self.write('derived-manifest.json', derived))
            assert code == 0, out
            self.parent_manifest = derived['derived_from']['manifest_sha256']
            self.stimuli[study_id] = dict(out['data']['stimulus'], coordinator_inspected=True)
        return copy.deepcopy(self.stimuli[study_id])

    def draft(self, **changes):
        draft = super().draft(**changes)
        draft.update(participant_models=[CLAUDE, GPT], analysis=GPT, review=GEMINI,
                     sharing=[{'providerInstanceId': t['providerInstanceId'], 'consumers': ['participant', 'analysis', 'review'],
                               'material_classes': ALL_CLASSES} for t in (CLAUDE, GPT, GEMINI)])
        draft.update(changes)
        return draft

    # --- invented participant evidence

    def fi_payload(self, n, initial, observed=(), walk=(), claims=()):
        return {'schema': 'focus-group/first-impression', 'schema_version': 1, 'cell_id': self.cell(n),
                'study_revision': self.view['revision'], 'brief_sha256': self.documents[f'fi-{n + 1:02d}']['sha256'],
                'image_use': {'saw_images': True, 'basis': 'image-and-text'},
                'initial_viewport': {'file': 'initial-viewport.png', 'reaction': initial, 'observed': list(observed),
                                     'inferred': []},
                'walkthrough': [{'file': f, 'reaction': r, 'observed': [], 'inferred': []} for f, r in walk],
                'claims': [{'id': f'c{k}', 'kind': 'textual', 'statement': s, 'files': ['welcome-clean.txt']}
                           for k, s in enumerate(claims)], 'simulated': True}

    def declare_journeys(self):
        """Every journey slot in one recorded plan revision, before any journey runs: adding a slot to a stage
        later stales that stage's executed slots under the shared plan-revision rules."""
        for n in range(len(self.view['cells'])):
            self.bound_context(self.view, self.cell(n))
        self.journey_documents = {f'jr-{n + 1:02d}': self.document(n, 'journey', f'jr-{n + 1:02d}')
                                  for n in range(len(self.view['cells']))}
        out = self.lc_ok(*self.study('journey-slots'), '--documents', self.write('journey-docs.json',
                                                                                 self.journey_documents))
        self.job_ok('decision', out['decision_input'])
        self.job_ok('plan-revision', out['plan_revision_input'])

    def journey_with(self, n, goal=None, gaps=(), notes=None):
        task = f'jr-{n + 1:02d}'
        request = f'{task}-r0'
        document = self.journey_documents[task]
        code, out = self.admit_slot(n, 'journey', request)
        assert code == 0, out
        brief = self.prepare(task)
        host = self.launch(task, request, 'default', n)
        context = self.bound_context(self.view, self.cell(n))
        payload = self.journey_payload(self.view, self.cell(n), document['sha256'], context)
        if goal is not None:
            if notes is not None:
                folder = self.root / self.view['study_id'] / 'artifacts' / 'tasks' / task
                folder.mkdir(parents=True, exist_ok=True)
                (folder / 'notes.txt').write_text(notes)
                goal['evidence'] = [{'kind': 'text', 'path': str(folder / 'notes.txt'),
                                     'sha256': sha((folder / 'notes.txt').read_bytes())}]
            payload['goals'] = [dict(payload['goals'][0], **goal)]
        else:
            payload['goals'] = []
        payload['gaps'] = list(gaps)
        item = self.payload_file(task, payload)
        path = self.transport(self.worker_result(brief, [item]))
        assert self.complete(task, request, host, f'done-{request}')[0] == 0
        assert self.deliver(task, request, f'done-{request}', path)[0] == 0
        outcome = self.ingest(task, request, f'done-{request}', path, context={'class': 'fresh-anonymous', **context})
        assert outcome[0] == 0, outcome
        self.reconcile()

    # --- report entry points

    def rp(self, *args, env=None):
        proc = subprocess.run([sys.executable, str(REPORT), *map(str, args)], capture_output=True, text=True, timeout=120,
                              cwd=self.base, env={**(env or os.environ), **self.policy_env, 'PYTHONDONTWRITEBYTECODE': '1'})
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, (proc.stdout, proc.stderr)
        return proc.returncode, json.loads(lines[0])

    def rp_ok(self, *args, **kw):
        code, out = self.rp(*args, **kw)
        assert code == 0, out
        return out['data']

    def bind_analysis(self):
        out = self.rp_ok(*self.study('analysis-inputs'), '--capabilities', self.catalog(), '--now', BEFORE)
        if out['changed']:
            self.job_ok('decision', out['decision_input'])
            self.job_ok('plan-revision', out['plan_revision_input'])
        record = json.loads((self.root / self.view['study_id'] / 'focus-group' / 'report' / 'inputs' /
                             f'{out["inputs_sha256"]}.json').read_text())
        return out, record

    def run_analysis(self, synthesis, request='analysis-r0', identity=None, deliver=True):
        code, out = self.admit(self.view, request, 'analysis')
        assert code == 0, out
        brief = self.prepare('analysis')
        host = self.launch('analysis', request, ident(GPT) if identity is None else identity)
        item = self.payload_file('analysis', synthesis, name='synthesis.json')
        path = self.transport(self.worker_result(brief, [item], conclusion='Invented analyst fixture synthesis.'))
        assert self.complete('analysis', request, host, f'done-{request}')[0] == 0
        if deliver:
            assert self.deliver('analysis', request, f'done-{request}', path)[0] == 0
        self.reconcile()
        return self.rp(*self.study('synthesis'), '--input', self.write(f'syn-{request}-{self.counter}.json', {
            'task_id': 'analysis', 'request_id': request, 'completion_id': f'done-{request}'}))

    def render(self, name='bundle'):
        out = self.base / name
        return self.rp(*self.study('render'), '--out', out)

    def bind_review(self, bundle):
        out = self.rp_ok(*self.study('review-slot'), '--bundle', bundle, '--capabilities', self.catalog(), '--now', BEFORE)
        if out['changed']:
            self.job_ok('decision', out['decision_input'])
            self.job_ok('plan-revision', out['plan_revision_input'])
        return out

    def run_review(self, verdict='approve', findings=(), request='review-r0', identity=None, status='passed',
                   purpose='initial'):
        code, out = self.admit(self.view, request, 'review', purpose=purpose)
        assert code == 0, out
        brief = self.prepare('review')
        host = self.launch('review', request, ident(GEMINI) if identity is None else identity)
        result = self.worker_result(brief, [], conclusion='Invented fidelity review fixture.', review_verdict=verdict,
                                    findings=list(findings),
                                    requirements=[{'id': r['id'], 'status': status, 'evidence': 'bundle checked'}
                                                  for r in brief['requirements']])
        path = self.transport(result)
        assert self.complete('review', request, host, f'done-{request}')[0] == 0
        delivered = self.deliver('review', request, f'done-{request}', path)
        self.reconcile()
        return brief, delivered

    def accept(self, stage):
        observation = self.rp_ok(*self.study('observation'), '--stage', stage)['observation']
        frozen = self.job_ok('observation', {'caller': self.caller, 'stage_id': stage,
                                             'input_file': str(self.write(f'obs-{stage}-{self.counter}.json', observation))})
        revision = next(s for s in self.job_state()['stages'] if s['id'] == stage)['revision']
        request = self.write(f'accept-{stage}-{self.counter}.json', {
            'caller': self.caller, 'stage_id': stage, 'input_file': frozen['path'], 'revision': revision,
            'validator_argv': [str(fg3.INSTALL['package'] / 'scripts' / 'validate_study.py'), '--input', frozen['path']]})
        return self.acceptance('accept-stage', request)

    def acceptance(self, action, request):
        proc = subprocess.run([sys.executable, str(fg3.INSTALL['package'] / 'shared' / 'job_acceptance_cli.py'), action,
                               '--state-root', str(self.root), '--job', self.view['study_id'], '--input', str(request)],
                              capture_output=True, text=True, env={**fg3.INSTALL['env'], **self.policy_env}, timeout=120)
        return proc.returncode, json.loads(proc.stdout or proc.stderr or '{}')

    def validate(self, stage):
        return self.acceptance('validate', self.write(f'validate-{stage}-{self.counter}.json', {'stage_id': stage}))

    def dispose(self, request, finding, disposition, response):
        evidence_file = self.base / 'owner' / f'response-{finding["id"]}-{self.counter}.md'
        evidence_file.parent.mkdir(parents=True, exist_ok=True)
        evidence_file.write_text(response)
        data = evidence_file.read_bytes()
        return self.job_ok('finding-disposition', {
            'caller': self.caller, 'task_id': 'review', 'finding_id': finding['id'], 'disposition': disposition,
            'evidence': {'path': str(evidence_file), 'sha256': sha(data), 'bytes': len(data)}})

    def coordinator_caps(self, provider_id='claudeAgent', model='claude-fixture-swift'):
        return self.write(f'coordinator-{self.counter}.json', {'inheritedProviderInstanceId': provider_id,
                                                               'inheritedModel': model, 'parentThreadId': 'thread-coord',
                                                               **CAPS})


def build_study(h):
    """Four combined cells with deliberately varied, invented evidence, accepted through FG-3 ingestion."""
    h.start()
    payloads = {
        0: h.fi_payload(0, 'Too much on the first screen; I want dinners, not a tour.',
                        observed=['a long paragraph above the button'],
                        walk=[('welcome-clean.txt', 'I like that it says three dinners.'),
                              ('recipe-detail.png', 'The green button colour feels dull.')]),
        1: h.fi_payload(1, 'The detailed recipe cards look trustworthy.',
                        walk=[('recipe-detail.png', 'The green button colour feels dull.')]),
        2: h.fi_payload(2, 'Clean, but I cannot see prices.',
                        walk=[('welcome-clean.txt', 'I wish I could sort recipes by cost per serving.')],
                        claims=['The app never mentions a shopping list.']),
        3: h.fi_payload(3, 'The green button colour feels dull.', walk=[('welcome-clean.txt', 'Short and clear.')]),
    }
    for n in (0, 1, 2):
        out = h.first(n, payload=payloads[n])
        assert out['code'] == 0, out['out']
    # Cell 3's first attempt carries a planted marker: it is quarantined, never accepted, and a charged retry
    # supplies the cell's only accepted first impression. The rejected attempt contributes no support.
    planted = h.fi_payload(3, 'The green button colour feels dull. ' + MARKER, walk=[('welcome-clean.txt', 'Short.')])
    refused = h.first(3, payload=planted)
    assert (refused['code'], refused['out']['error']['code']) == (1, 'payload_quarantined'), refused['out']
    h.reconcile()
    h.job_ok('retry', {'caller': h.caller, 'task_id': 'fi-04', 'reason': 'quarantined result'})
    retry = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'fi-04')['request_id']
    out = h.first(3, request=retry, payload=payloads[3])
    assert out['code'] == 0, out['out']
    h.declare_journeys()
    step = {'at': '2029-06-01T00:06:00Z', 'kind': 'tap', 'permitted_action': 'browse recipes',
            'description': 'opened recipes', 'url': FIXTURE_ORIGIN + '/recipes', 'field': None}
    h.journey_with(0, {'outcome': 'not-achieved', 'steps': [step],
                       'reactions': ['I could not find where to add a recipe to my plan.'],
                       'observed_events': ['the add button sat below the fold'], 'inferences': []},
                   notes='Scrolled the recipe page twice; no add control was visible above the fold.\n')
    h.journey_with(1, {'outcome': 'achieved', 'steps': [step], 'reactions': ['Planning three dinners took two minutes.'],
                       'observed_events': ['three recipes were added to the plan'], 'inferences': []})
    h.journey_with(2, {'outcome': 'partial', 'steps': [step], 'reactions': ['Quick, but I lost my place once.'],
                       'observed_events': ['the recipe list loaded'], 'inferences': []})
    h.journey_with(3, gaps=[{'journey_id': 'plan-three-dinners', 'reason': 'browser-unavailable',
                             'detail': 'The preview tool did not open the page.'}])
    for stage in ('first-impression', 'journey'):
        code, out = h.accept(stage)
        assert code == 0 and out['accepted'], out


def load_report_module():
    """The source report.py imported in process, for pure validator checks on recorded inputs."""
    import importlib
    sys.path.insert(0, str(fg3.PLUGIN / 'scripts'))
    try:
        return importlib.import_module('report')
    finally:
        sys.path.remove(str(fg3.PLUGIN / 'scripts'))


def sources(record):
    return {(s['cell_id'], s['stage']): s for s in record['inputs']['evidence']['sources']}


def synthesis_for(h, record):
    """A faithful invented synthesis of the fixture evidence: a minority task blocker, a majority cosmetic
    preference, conflicting first impressions, a single-persona idea, an unverified suggestion, things to
    preserve, an environment failure and a contradicted model claim."""
    s = sources(record)
    c = [h.cell(n) for n in range(4)]
    notes = next(m['sha256'] for m in s[(c[0], 'journey')]['material'])

    def obs(ref, n, stage, pointer, capture=()):
        src = s[(c[n], stage)]
        value = src['payload']
        for part in pointer[1:].split('/'):
            value = value[int(part)] if isinstance(value, list) else value[part]
        return {'ref': ref, 'source_id': src['source_id'], 'pointer': pointer, 'quote': value, 'cell_id': c[n],
                'stage': stage, 'revision': src['revision'], 'capture': list(capture)}

    fi, jr = 'first-impression', 'journey'
    observations = [
        obs('dense', 0, fi, '/initial_viewport/reaction', [{'pack': 'initial-viewport.png'}]),
        obs('detail', 1, fi, '/initial_viewport/reaction', [{'pack': 'initial-viewport.png'}]),
        obs('three', 0, fi, '/walkthrough/0/reaction', [{'pack': 'welcome-clean.txt'}]),
        obs('dull-0', 0, fi, '/walkthrough/1/reaction', [{'pack': 'recipe-detail.png'}]),
        obs('dull-1', 1, fi, '/walkthrough/0/reaction', [{'pack': 'recipe-detail.png'}]),
        obs('dull-3', 3, fi, '/initial_viewport/reaction', [{'pack': 'initial-viewport.png'}]),
        obs('price', 2, fi, '/initial_viewport/reaction', [{'pack': 'initial-viewport.png'}]),
        obs('cost', 2, fi, '/walkthrough/0/reaction', [{'pack': 'welcome-clean.txt'}]),
        obs('claim', 2, fi, '/claims/0/statement', [{'pack': 'welcome-clean.txt'}]),
        # Every field of the add-to-plan goal cites the notes file the accepted journey bound to that goal.
        obs('add', 0, jr, '/goals/0/reactions/0', [{'material': notes}]),
        obs('fold', 0, jr, '/goals/0/observed_events/0', [{'material': notes}]),
        obs('outcome', 0, jr, '/goals/0/outcome', [{'material': notes}]),
        obs('fast', 1, jr, '/goals/0/reactions/0'),
        obs('gap', 3, jr, '/gaps/0/detail'),
    ]
    findings = [
        {'id': 'F-dense-first-screen', 'category': 'first-impression', 'title': 'The first screen feels dense',
         'statement': 'A time-poor parent wanted dinners straight away and found the opening text long.',
         'observation_refs': ['dense'], 'verification': 'observed', 'conflicts_with': ['F-detail-trusted']},
        {'id': 'F-detail-trusted', 'category': 'dissent', 'title': 'Detail reads as trustworthy to another persona',
         'statement': 'The same detail that felt dense to one cell made another trust the recipes.',
         'observation_refs': ['detail'], 'verification': 'observed', 'conflicts_with': ['F-dense-first-screen']},
        {'id': 'F-button-colour', 'category': 'first-impression', 'title': 'The green button colour feels dull',
         'statement': 'Three cells described the main button colour as dull.',
         'observation_refs': ['dull-0', 'dull-1', 'dull-3'], 'verification': 'observed'},
        {'id': 'F-add-to-plan-hidden', 'category': 'friction', 'title': 'Adding a recipe to the plan was not found',
         'statement': 'One persona could not find the add-to-plan control and did not reach the goal.',
         'observation_refs': ['add', 'fold', 'outcome'], 'verification': 'observed',
         'friction_type': 'feature-not-found', 'feature_terms': ['add them to a plan']},
        {'id': 'F-sort-by-cost', 'category': 'feature-opportunity', 'title': 'Sort recipes by cost per serving',
         'statement': 'One budget-focused persona asked to sort by cost after missing prices.',
         'observation_refs': ['cost', 'price'], 'verification': 'observed', 'idea_origin': 'persona-requested',
         'supporting_frustration': ['price']},
        {'id': 'F-price-badge', 'category': 'feature-opportunity', 'title': 'Show a price badge on each recipe',
         'statement': 'The analyst infers that a visible price could answer the missing-price frustration.',
         'observation_refs': ['price'], 'verification': 'unverified-suggestion', 'idea_origin': 'analyst-inferred',
         'supporting_frustration': ['price']},
        {'id': 'F-three-dinners', 'category': 'preserve', 'title': 'Keep the three-dinner promise',
         'statement': 'The promise was liked and one persona planned three dinners quickly.',
         'observation_refs': ['three', 'fast'], 'verification': 'observed'},
        {'id': 'F-preview-tool', 'category': 'environment-limitation', 'title': 'The preview tool did not open',
         'statement': 'One journey could not start; this is a test-environment failure.',
         'observation_refs': ['gap'], 'verification': 'observed', 'friction_type': 'environment-failure'},
        {'id': 'F-shopping-list-claim', 'category': 'model-error', 'title': 'A claim that no shopping list exists',
         'statement': 'One participant said the app never mentions a shopping list; the page text does.',
         'observation_refs': ['claim'], 'verification': 'observed', 'friction_type': 'contradicted-claim',
         'contradiction': {'file': 'welcome-clean.txt', 'excerpt': 'open the shopping list'}},
    ]
    backlog = [
        {'id': 'B-show-add-to-plan', 'title': 'Make adding a recipe to the plan visible', 'finding_ids': ['F-add-to-plan-hidden'],
         'user_impact': 'task-blocker', 'impact_reason': 'The persona could not finish planning dinners at all.',
         'evidence_strength': 'direct-observation', 'uncertainty': 'One cell; the control may simply need scrolling.',
         'rank_reason': 'A blocked goal outranks preferences that leave the goal reachable.',
         'proposed_change': 'Show the add-to-plan control on each recipe card without scrolling.',
         'change_origin': 'analyst-proposed', 'rationale': 'The goal failed where the control sat below the fold.',
         'verification': 'A fresh persona adds three recipes to a plan without scrolling.',
         'unresolved_decision': None, 'effort': {'state': 'unknown'}},
        {'id': 'B-lighter-first-screen', 'title': 'Offer a shorter first screen', 'finding_ids': ['F-dense-first-screen', 'F-detail-trusted'],
         'user_impact': 'major', 'impact_reason': 'A time-poor persona considered leaving before seeing dinners.',
         'evidence_strength': 'participant-report', 'uncertainty': 'Conflicting reactions: detail also built trust.',
         'rank_reason': 'Abandonment risk on arrival, below the blocked goal.',
         'proposed_change': 'Progressive disclosure: dinners first, detail one tap away.',
         'change_origin': 'analyst-proposed', 'rationale': 'Keeps detail for those who trust it while shortening arrival.',
         'verification': 'Both personas reach a dinner suggestion and still find recipe detail.',
         'unresolved_decision': 'How much detail stays on the first screen?', 'effort': {'state': 'unknown'}},
        {'id': 'B-button-colour', 'title': 'Revisit the main button colour', 'finding_ids': ['F-button-colour'],
         'user_impact': 'cosmetic', 'impact_reason': 'A colour preference that leaves every goal reachable.',
         'evidence_strength': 'participant-report', 'uncertainty': 'Taste; no goal was affected.',
         'rank_reason': 'Cosmetic, so it ranks below goal and arrival problems.',
         'proposed_change': 'Try a higher-contrast button colour.', 'change_origin': 'persona-requested',
         'rationale': 'Several cells found the colour dull.', 'verification': 'A fresh persona describes the button neutrally.',
         'unresolved_decision': None, 'effort': {'state': 'unknown'}},
        {'id': 'B-sort-by-cost', 'title': 'Sort recipes by cost', 'finding_ids': ['F-sort-by-cost'], 'user_impact': 'minor',
         'impact_reason': 'Budget-focused cooking is harder without prices.',
         'evidence_strength': 'participant-report', 'uncertainty': 'A single persona asked for it.',
         'rank_reason': 'A useful idea with limited support and no blocked goal.',
         'proposed_change': 'Add a sort-by-cost option.', 'change_origin': 'persona-requested',
         'rationale': 'The persona asked for it after missing prices.',
         'verification': 'A budget persona finds the cheapest three dinners.',
         'unresolved_decision': 'Is pricing data in scope?', 'effort': {'state': 'unknown'}},
    ]
    return {'schema': 'focus-group/synthesis', 'schema_version': 1, 'study_revision': h.view['revision'],
            'inputs_sha256': record['inputs_sha256'],
            'decision': {'answer': 'inconclusive', 'summary': 'Two personas split on the dense first screen; asking for '
                                                              'dietary needs first was not tested directly.',
                         'finding_ids': ['F-dense-first-screen', 'F-detail-trusted'],
                         'uncertainty': 'Four synthetic cells on one invented prototype.'},
            'observations': observations, 'findings': findings, 'backlog': backlog}


class ReportCase(unittest.TestCase):
    """Restores the built fixture study before each test so every scenario continues the same real state."""

    @classmethod
    def setUpClass(cls):
        if 'backup' not in STATE:
            STATE['tmp'] = tempfile.TemporaryDirectory()
            base = Path(STATE['tmp'].name).resolve() / 'study'
            base.mkdir()
            host = ReportHost(base)
            build_study(host)
            backup = base.parent / 'backup'
            shutil.copytree(base, backup, symlinks=True)
            STATE.update(base=base, backup=backup, host=copy.deepcopy(host.__dict__))

    def setUp(self):
        base = STATE['base']
        shutil.rmtree(base)
        shutil.copytree(STATE['backup'], base, symlinks=True)
        self.h = ReportHost.__new__(ReportHost)
        self.h.__dict__ = copy.deepcopy(STATE['host'])

    def refused(self, outcome, code):
        self.assertEqual((outcome[0], outcome[1]['error']['code']), (1, code), outcome[1])
        return outcome[1]

    def problems(self, outcome):
        self.assertEqual(outcome[0], 1, outcome[1])
        return {p['code'] for p in outcome[1]['data']['problems']}

    def analysed(self, synthesis=None):
        """Bind, dispatch and freeze the analyst synthesis, then accept the analysis stage through the pinned
        validator: the review slot can be prepared only once its predecessor stage is accepted."""
        _, record = self.h.bind_analysis()
        code, out = self.h.run_analysis(synthesis or synthesis_for(self.h, record))
        self.assertEqual(code, 0, out)
        code, accepted = self.h.accept('analysis')
        self.assertEqual((code, accepted.get('accepted')), (0, True), accepted)
        return record, out['data']

    def reviewed(self, synthesis=None):
        record, synthesised = self.analysed(synthesis)
        code, out = self.h.render()
        self.assertEqual(code, 0, out)
        bundle = Path(out['data']['bundle'])
        self.h.bind_review(bundle)
        self.h.run_review()
        return record, bundle

    def check(self, record, synthesis):
        return self.h.rp(*self.h.study('check-synthesis'), '--input', self.h.write(
            f'check-{self.h.counter}.json', {'inputs_sha256': record['inputs_sha256'], 'synthesis': synthesis}))


# ----------------------------------------------------------------------------- REQ-REPORT, REQ-PRIORITY, REQ-EXPORT


class EndToEndTest(ReportCase):
    def test_analysis_inputs_rechecks_evidence_changed_before_lock_acquisition(self):
        report = load_report_module()
        study = report.Study(self.h.root, self.h.view['study_id'])
        original_lock = study.locked
        original_view = report.evidence_view(study, study.plan(study.require()['revision'])['plan'],
                                             study.require()['revision'], self.h.job_state())
        self.assertGreater(original_view['denominators']['first_impressions'], 0)
        acquired = []

        @contextlib.contextmanager
        def concurrent_change():
            with original_lock():
                acquired.append(True)
                # Another writer invalidated all native first impressions while
                # this caller was waiting for the study lock.
                for record in study.accepted():
                    if record['stage'] == 'first-impression':
                        path = Path(record['result']['path'])
                        if not path.is_absolute():
                            path = study.job_dir / path
                        path.write_bytes(b'Changed accepted fixture evidence.')
                yield

        args = argparse.Namespace(state_root=str(study.root), study=study.id,
                                  capabilities=self.h.catalog(), now=BEFORE, assessments=None)
        with patch.object(report, 'Study', return_value=study), patch.object(study, 'locked', concurrent_change):
            with patch.dict(os.environ, self.h.policy_env):
                with self.assertRaises(report.fg.StudyError) as caught:
                    report.op_analysis_inputs(args)
        self.assertEqual(acquired, [True])
        self.assertEqual(caught.exception.code, 'disclosure_blocked')
        self.assertEqual(list((report.report_dir(study) / 'inputs').glob('*.json')), [])

    def test_delegated_synthesis_reviewed_by_another_lineage_renders_accepts_and_exports_portably(self):
        h = self.h
        record, synthesised = self.analysed()
        # REQ-COUNTS: the quarantined first attempt of cell 3 is not a source; each cell has one accepted record.
        rows = record['inputs']['evidence']['sources']
        self.assertEqual(sorted((s['cell_id'], s['stage']) for s in rows),
                         sorted((h.cell(n), stage) for n in range(4) for stage in ('first-impression', 'journey')))
        self.assertNotIn(MARKER, json.dumps(record))
        self.assertEqual(record['inputs']['evidence']['denominators'],
                         {'declared_cells': 4, 'first_impressions': 4, 'journeys': 4, 'hands_on_journeys': 3})
        self.assertEqual([a['lineage'] for a in synthesised['authors']], ['openai'])
        # REQ-FIDELITY (material delivery): the document-only analyst brief declares a hash-bound copy of every cleared
        # pack file and accepted journey file as readable context files; journey text is inlined too.
        view = record['inputs']['evidence']
        notes = next(m for m in sources(record)[(h.cell(0), 'journey')]['material'])
        self.assertEqual((notes['goals'], notes['text']),
                         ([0], 'Scrolled the recipe page twice; no add control was visible above the fold.\n'))
        delivered = {f['sha256'] for f in record['files']}
        self.assertEqual(delivered, {f['sha256'] for f in view['pack']['files']} | {notes['sha256']})
        for item in record['files']:
            self.assertEqual(sha(Path(item['path']).read_bytes()), item['sha256'])
        analysis = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'analysis')
        brief = json.loads(Path(analysis['brief']['path']).read_text())
        self.assertEqual((analysis['context_files'], brief['context_files']), (record['files'], record['files']))
        self.assertEqual(brief['authorization']['read'], [record['document']['path']] + [f['path'] for f in record['files']])
        self.assertIn('context_files', Path(record['document']['path']).read_text())
        code, out = h.render()
        self.assertEqual(code, 0, out)
        bundle = Path(out['data']['bundle'])
        report = (bundle / 'report.md').read_text()
        # REQ-REPORT: summary first, every inspectable category, the synthetic interpretation and an inconclusive answer.
        headings = [line for line in report.splitlines() if line.startswith('## ')]
        self.assertEqual(headings, ['## Decision summary', '## First impressions', '## Goal outcomes and frictions',
                                    '## Feature opportunities', '## Things to preserve', '## Dissent and minority ideas',
                                    '## Environment limitations', '## Model errors', '## Coverage and identity',
                                    '## Prioritised backlog'])
        self.assertIn('not evidence of human demand, prevalence, retention or revenue', report.split('## Decision')[0])
        self.assertIn('**Answer:** inconclusive (an inconclusive answer is a valid result)', report)
        findings = json.loads((bundle / 'findings.json').read_text())
        backlog = json.loads((bundle / 'backlog.json').read_text())
        support = {f['id']: f['support'] for f in findings['findings']}
        # REQ-COUNTS: unique cells, personas and lineages; repeated quotes from one cell add nothing.
        self.assertEqual((support['F-button-colour']['cells'], support['F-button-colour']['personas'],
                          support['F-button-colour']['lineage_names']), (3, 2, ['anthropic', 'openai']))
        self.assertEqual((support['F-add-to-plan-hidden']['cells'], support['F-add-to-plan-hidden']['journey']),
                         (1, {'cells': 1, 'of': 4}))
        self.assertEqual((support['F-sort-by-cost']['cells'], support['F-sort-by-cost']['personas']), (1, 1))
        self.assertEqual(support['F-three-dinners']['cells'], 2)
        # REQ-PRIORITY: a one-cell task blocker outranks a three-cell cosmetic preference, with the reason visible;
        # conflicting preferences and the single-persona idea stay, with their actual limited support.
        self.assertEqual([i['id'] for i in backlog['items']],
                         ['B-show-add-to-plan', 'B-lighter-first-screen', 'B-button-colour', 'B-sort-by-cost'])
        self.assertEqual([i['support']['cells'] for i in backlog['items']], [1, 2, 3, 1])
        self.assertIn('1. **B-show-add-to-plan: Make adding a recipe to the plan visible**', report)
        self.assertIn('Why this rank: A blocked goal outranks preferences that leave the goal reachable.', report)
        self.assertIn('Conflicts with F-detail-trusted', report)
        self.assertIn('Idea: requested by a persona', report)
        self.assertIn('Unverified suggestion: the analyst inferred this idea', report)
        self.assertIn('Present feature not found', report)
        self.assertIn('Model error: a participant claim the approved material contradicts', report)
        self.assertIn('Environment failure: a test-environment or tool problem, not product friction', report)
        self.assertIn('Proposed change (analyst-proposed, not observed)', report)
        self.assertEqual(report.count('Effort: Unknown: no separately authorised source assessment'), 4)
        self.assertNotIn('%', report)  # no population statistics
        # Stable observation IDs are rendered with the exact quote at its pointer.
        quote = next(o for o in findings['observations'] if o['pointer'] == '/goals/0/reactions/0'
                     and o['cell_id'] == h.cell(0))
        self.assertTrue(quote['id'].startswith('O-'))
        self.assertIn(f'`{quote["id"]}`', report)
        self.assertIn('"I could not find where to add a recipe to my plan."', report)
        # REQ-EVIDENCE: a field with no bound file says why no capture applies; goal files stay cited.
        self.assertIn('"Planning three dinners took two minutes." (goal 0 bound no file)', report)
        self.assertIn('"The preview tool did not open the page." (a gap or drift record binds no file)', report)
        self.assertEqual({o['capture_scope'] for o in findings['observations'] if o['cell_id'] == h.cell(0)
                          and o['stage'] == 'journey'}, {'files bound to goal 0'})
        # REQ-EXPORT: every issue draft carries change, rationale, IDs, evidence, uncertainty, verification, decision.
        issue = (bundle / 'issues' / 'B-sort-by-cost.md').read_text()
        for heading in ('## Requested change', '## Rationale', '## Evidence', '## Uncertainty',
                        '## Suggested observable verification', '## Unresolved product decision', '## Source IDs'):
            self.assertIn(heading, issue)
        self.assertIn('Is pricing data in scope?', issue)
        self.assertIn('F-sort-by-cost', issue)
        # REQ-FIDELITY: a fresh reviewer of another known lineage, bound to the exact bundle and inputs.
        review = h.bind_review(bundle)
        self.assertEqual((review['round'], review['reviewer']['lineage']), (1, 'google'))
        stored = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'review')
        self.assertEqual([d['path'] for d in stored['reviewed_documents']],
                         [str(bundle / n) for n in ('report.md', 'findings.json', 'backlog.json', 'bundle.json')])
        self.assertEqual([a.get('lineage') for a in stored['document_authors']], ['openai'], stored['document_authors'])
        brief, delivered = h.run_review()
        context = brief['resources']['focus_group_review']
        self.assertEqual((context['inputs']['inputs_sha256'], context['prior_rounds']), (record['inputs_sha256'], []))
        # The reviewer receives every delivered file, not only the captures the analyst chose to cite.
        self.assertEqual(context['inputs']['files'], record['files'])
        self.assertEqual(delivered[0], 0, delivered)
        code, out = h.accept('review')
        self.assertEqual((code, out.get('accepted')), (0, True), out)
        status = h.rp_ok(*h.study('status'))
        self.assertEqual((status['review_status'], status['complete']), ('reviewed', False))  # one journey is a gap
        # Export: portable, relocatable, zero external actions, reviewed status from current receipts.
        stub = h.base / 'stub-bin'
        stub.mkdir()
        log = h.base / 'external-calls.log'
        for tool in ('gh', 'git', 'agents', 'imps', 'curl'):
            (stub / tool).write_text(f'#!/bin/sh\necho {tool} "$@" >> {log}\nexit 97\n')
            (stub / tool).chmod(0o755)
        before = {p: p.read_bytes() for p in (h.root / h.view['study_id']).rglob('*') if p.is_file()}
        env = {**os.environ, 'PATH': f'{stub}{os.pathsep}{os.environ["PATH"]}', 'PYTHONDONTWRITEBYTECODE': '1'}
        export = h.base / 'export'
        out = h.rp_ok(*h.study('export'), '--bundle', bundle, '--out', export, env=env)
        self.assertEqual((out['review_status'], out['external_actions']), ('reviewed', []))
        self.assertFalse(log.exists(), 'export made no GitHub, git, imps or network call')
        after = {p: p.read_bytes() for p in (h.root / h.view['study_id']).rglob('*') if p.is_file()}
        self.assertEqual(before, after, 'export changed no job or study state')
        moved = h.base / 'elsewhere' / 'relocated-export'
        moved.parent.mkdir()
        os.rename(export, moved)
        checked = h.rp_ok('verify-export', '--bundle', moved)
        self.assertEqual(checked['review_status'], 'reviewed')
        text = '\n'.join(p.read_text() for p in moved.rglob('*') if p.suffix in ('.md', '.json'))
        self.assertNotIn(str(h.base), text)
        self.assertNotIn(MARKER, text)
        for link in ('evidence/', 'issues/B-show-add-to-plan.md'):
            self.assertIn(f']({link}', (moved / 'report.md').read_text())
        manifest = json.loads((moved / 'bundle.json').read_text())
        pack = next(e for e in manifest['evidence'] if e['name'] == 'initial-viewport.png')
        self.assertEqual(pack['disclosure']['derived_from']['manifest_sha256'], h.parent_manifest)
        self.assertEqual(pack['disclosure']['decision'], 'cleared')
        material = next(e for e in manifest['evidence'] if e['name'] == 'notes.txt')
        self.assertEqual(material['disclosure']['source'], 'journey-material')
        self.assertTrue((moved / material['path']).is_file())
        # REQ-EVIDENCE/REQ-EXPORT: after relocation every observation leads to a portable projection of its accepted
        # payload, generated from the accepted record (not the analyst's quote): its pointer resolves there to the
        # exact quote, with cell/stage/revision/request provenance, parent hashes and the disclosure decision.
        moved_findings = json.loads((moved / 'findings.json').read_text())
        accepted = {s['source_id']: s for s in rows}
        self.assertEqual({o['source_file'] for o in moved_findings['observations']},
                         {f'sources/{o["source_id"]}.json' for o in moved_findings['observations']})
        for o in moved_findings['observations']:
            body = json.loads((moved / o['source_file']).read_text())
            value = body['payload']
            for part in o['pointer'][1:].split('/'):
                value = value[int(part)] if isinstance(value, list) else value[part]
            self.assertEqual(value, o['quote'])
            want = accepted[o['source_id']]
            self.assertEqual({k: body[k] for k in ('record_sha256', 'result_sha256', 'cell_id', 'stage', 'revision',
                                                   'task_id', 'request_id')},
                             {k: want[k] for k in ('record_sha256', 'result_sha256', 'cell_id', 'stage', 'revision',
                                                   'task_id', 'request_id')})
            self.assertEqual(body['disclosure']['decision'], 'cleared-at-acceptance')
            if o['stage'] == 'first-impression':  # unchanged: the accepted bytes are copied beside the projection
                self.assertEqual((body['transform'], sha((moved / body['payload_file']).read_bytes())),
                                 ([], body['result_sha256']))
            elif body['payload'].get('goals') and body['payload']['goals'][0].get('evidence'):
                self.assertEqual((body['payload_file'], body['transform'][0]['pointer']), (None, '/goals/0/evidence/0/path'))
            self.assertIn(f']({o["source_file"]})', (moved / 'report.md').read_text())
        self.assertIn('](../sources/', (moved / 'issues' / 'B-show-add-to-plan.md').read_text())
        # Stable IDs across a re-render into another directory.
        again = h.rp_ok(*h.study('render'), '--out', h.base / 'bundle-again')
        self.assertEqual((Path(again['bundle']) / 'findings.json').read_bytes(), (bundle / 'findings.json').read_bytes())

    def test_empty_categories_say_so_and_an_inconclusive_answer_with_one_finding_is_valid(self):
        h = self.h
        _, record = h.bind_analysis()
        s = sources(record)
        src = s[(h.cell(1), 'first-impression')]
        synthesis = {'schema': 'focus-group/synthesis', 'schema_version': 1, 'study_revision': h.view['revision'],
                     'inputs_sha256': record['inputs_sha256'],
                     'decision': {'answer': 'inconclusive', 'summary': 'Too little evidence to answer.',
                                  'finding_ids': [], 'uncertainty': 'One reaction only.'},
                     'observations': [{'ref': 'detail', 'source_id': src['source_id'], 'pointer': '/initial_viewport/reaction',
                                       'quote': src['payload']['initial_viewport']['reaction'], 'cell_id': h.cell(1),
                                       'stage': 'first-impression', 'revision': src['revision'],
                                       'capture': [{'pack': 'initial-viewport.png'}]}],
                     'findings': [{'id': 'F-detail', 'category': 'preserve', 'title': 'Detail builds trust',
                                   'statement': 'One persona trusted the detailed cards.', 'observation_refs': ['detail'],
                                   'verification': 'observed'}],
                     'backlog': []}
        code, out = h.run_analysis(synthesis)
        self.assertEqual(code, 0, out)
        report = (Path(h.rp_ok(*h.study('render'), '--out', h.base / 'small')['bundle']) / 'report.md').read_text()
        sections = report.split('\n## ')
        empty = [s.split('\n', 1)[0] for s in sections if '_No supported observations._' in s]
        self.assertEqual(empty, ['First impressions', 'Goal outcomes and frictions', 'Feature opportunities',
                                 'Dissent and minority ideas', 'Environment limitations', 'Model errors',
                                 'Prioritised backlog'])
        self.assertIn('**Answer:** inconclusive', report)


# ----------------------------------------------------------------------------- REQ-EVIDENCE




# ----------------------------------------------------------------------------- REQ-COUNTS




# ----------------------------------------------------------------------------- REQ-PRIORITY




# ----------------------------------------------------------------------------- REQ-FIDELITY




# ----------------------------------------------------------------------------- REQ-EXPORT




# ----------------------------------------------------------------------------- non-fresh test state (REQ-CAPTURE)


TEST_STATE = {'context_class': 'preauthenticated-test', 'user_state': 'returning', 'onboarding': 'completed',
              'cookies': ['session_marker'], 'storage': ['tour_seen']}


class NonFreshHost(ReportHost):
    """The report host with an owner-approved, host-preauthenticated isolated test pack: a returning test user who
    completed onboarding, with invented cookie and storage names (values are never recorded)."""

    def stimulus(self, study_id):
        if study_id not in self.stimuli:
            folder = self.base / 'capture'
            files = [f for f in fixtures.write_pack(folder) if f['role'] != 'text']
            clean = folder / 'welcome-clean.txt'
            clean.write_bytes(CLEAN_TEXT.encode())
            files.append({'name': clean.name, 'role': 'text', 'view': None, 'path': str(clean),
                          'sha256': sha(clean.read_bytes()), 'bytes': clean.stat().st_size, 'media_type': 'text/plain'})
            answer = self.base / 'owner' / 'test-context.txt'
            answer.parent.mkdir(parents=True, exist_ok=True)
            statement = 'Approve isolated test context fixture-test-account-7 for focus-group capture'
            answer.write_text(f'Selected option: {statement}\n')
            manifest = fixtures.manifest(files)
            manifest['context'] = {
                'class': 'preauthenticated-test', 'reference': 'fixture-test-account-7',
                'freshness': {'verified': False, 'method': 'seeded test account', 'observed_at': BEFORE},
                'pre_existing_state': {'cookies': ['session_marker'], 'storage': ['tour_seen'], 'onboarding': 'completed'},
                'user_state': 'returning',
                'approval': {'message_ref': 'picker-1', 'statement': statement, 'source': str(answer),
                             'source_sha256': sha(answer.read_bytes())}}
            code, out = self.call_evidence('pack', '--state-root', self.root, '--study', study_id, '--input',
                                           self.write('test-context-manifest.json', manifest))
            assert code == 0 and out['data']['disclosure']['show_beside_first_impressions'], out
            self.stimuli[study_id] = dict(out['data']['stimulus'], coordinator_inspected=True)
        return copy.deepcopy(self.stimuli[study_id])


def delivered_inputs(record):
    """The JSON data block of the analysis inputs document exactly as delivered to the analyst."""
    lines = Path(record['document']['path']).read_text().splitlines()
    start = next(n for n, line in enumerate(lines) if line.startswith('```') and line.endswith('json'))
    mark = lines[start][:-len('json')]
    end = next(n for n in range(len(lines) - 1, start, -1) if lines[n] == mark)
    return json.loads('\n'.join(lines[start + 1:end]))


def finding_sections(report):
    return {part.split(':', 1)[0]: part for part in report.split('\n### ')[1:]}




# ----------------------------------------------------------------------------- incremental journeys (REQ-FIDELITY)




if __name__ == '__main__':
    unittest.main()
