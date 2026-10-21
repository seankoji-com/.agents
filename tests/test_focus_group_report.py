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
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
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
    fg3.setUpModule()


def tearDownModule():
    for key in ('tmp',):
        if key in STATE:
            STATE[key].cleanup()
    fg3.tearDownModule()


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
                              cwd=self.base, env=env or {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
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
                              capture_output=True, text=True, env=fg3.INSTALL['env'], timeout=120)
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
        for tool in ('gh', 'git', 't3-plugins', 'imps', 'curl'):
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


class EvidenceTest(ReportCase):
    def test_quotes_pointers_attribution_capture_and_pack_contradictions_are_checked(self):
        h = self.h
        _, record = h.bind_analysis()
        good = synthesis_for(h, record)
        self.assertEqual(self.check(record, good)[0], 0)

        def variant(change):
            value = copy.deepcopy(good)
            change(value)
            return self.problems(self.check(record, value))

        def obs(value, ref):
            return next(o for o in value['observations'] if o['ref'] == ref)

        def finding(value, fid):
            return next(f for f in value['findings'] if f['id'] == fid)

        cases = {
            'quote_mismatch': lambda v: obs(v, 'dense').update(quote='Too much on the first screen.'),
            'pointer_unresolved': lambda v: obs(v, 'dense').update(pointer='/walkthrough/9/reaction'),
            'pointer_outside_evidence': lambda v: obs(v, 'dense').update(pointer='/brief_sha256'),
            'foreign_attribution': lambda v: obs(v, 'dense').update(cell_id=h.cell(1)),
            'stage_or_revision_mismatch': lambda v: obs(v, 'dense').update(revision='0' * 64),
            'source_unknown': lambda v: obs(v, 'dense').update(source_id='S-000000000000'),
            'unsupported_capture': lambda v: obs(v, 'dense').update(capture=[{'pack': 'shopping-list.png'}]),
            'capture_missing': lambda v: obs(v, 'cost').update(capture=[]),
            'claim_contradicted_by_pack': lambda v: finding(v, 'F-add-to-plan-hidden').update(friction_type='product-absence'),
            'feature_not_in_pack': lambda v: finding(v, 'F-add-to-plan-hidden').update(feature_terms=['voice ordering']),
            'contradiction_unsupported': lambda v: finding(v, 'F-shopping-list-claim').update(
                contradiction={'file': 'welcome-clean.txt', 'excerpt': 'no shopping list'}),
            'environment_unsupported': lambda v: finding(v, 'F-preview-tool').update(observation_refs=['fold']),
            'unverified_as_observed': lambda v: finding(v, 'F-price-badge').update(verification='observed'),
            'idea_unsupported': lambda v: finding(v, 'F-sort-by-cost').pop('supporting_frustration'),
        }
        for code, change in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, variant(change))
        # A screenshot cannot support a source without a verified image basis; an unbound journey file cannot either.
        self.assertIn('unsupported_capture', variant(lambda v: obs(v, 'add').update(capture=[{'material': '1' * 64}])))
        # An inference alone cannot be presented as an observed finding.
        inferred = copy.deepcopy(good)
        inferred['findings'].append({'id': 'F-guess', 'category': 'preserve', 'title': 'A guess', 'statement': 'Guess.',
                                     'observation_refs': ['outcome'], 'verification': 'unverified-suggestion'})
        self.assertIn('unverified_as_observed', self.problems(self.check(record, inferred)))
        # A synthesis that is altered after it was recorded is never rendered or accepted.
        code, out = h.run_analysis(good)
        self.assertEqual(code, 0, out)
        path = h.root / h.view['study_id'] / 'artifacts' / 'tasks' / 'analysis' / 'synthesis.json'
        path.write_bytes(path.read_bytes().replace(b'feels dense', b'is broken'))
        self.refused(h.render(), 'hash_mismatch')

    def test_journey_files_stay_bound_to_their_goal_through_synthesis_render_and_export(self):
        h = self.h
        _, record = h.bind_analysis()
        good = synthesis_for(h, record)

        def without(refs):
            value = copy.deepcopy(good)
            for o in value['observations']:
                if o['ref'] in refs:
                    o['capture'] = []
            return value
        # Dropping the add-to-plan goal's only bound file from every observation of that goal is refused, by the
        # advisory check and by the actual synthesis ingestion, so it can never reach the report or the export.
        dropped = without({'add', 'fold', 'outcome'})
        self.assertEqual(self.problems(self.check(record, dropped)), {'capture_missing'})
        self.assertEqual(self.problems(self.check(record, without({'add'}))), {'capture_missing'})
        self.assertEqual(self.problems(h.run_analysis(dropped)), {'capture_missing'})
        self.refused(h.render(), 'synthesis_missing')
        # Another goal's file can never stand in for this goal's support, and a gap binds no file: the pure validator
        # on the recorded inputs, with the notes file rebound to a second goal of the same journey and a gap added.
        report_module = load_report_module()
        inputs = copy.deepcopy(record['inputs'])
        journey = next(s for s in inputs['evidence']['sources'] if (s['cell_id'], s['stage']) == (h.cell(0), 'journey'))
        journey['payload']['goals'].append(copy.deepcopy(journey['payload']['goals'][0]))
        journey['payload']['goals'][0]['evidence'] = []
        journey['payload']['gaps'] = [{'journey_id': 'plan-three-dinners', 'reason': 'out-of-scope', 'detail': 'Skipped.'}]
        journey['material'][0]['goals'] = [1]
        moved = copy.deepcopy(good)
        moved['inputs_sha256'] = report_module.sha(inputs)
        _, problems = report_module.validate_synthesis(inputs, moved)
        self.assertEqual({(p['code'], p['location']) for p in problems},
                         {('unsupported_capture', f'observations[{n}].capture[0]') for n in (9, 10, 11)})
        moved['observations'].append({'ref': 'skipped', 'source_id': journey['source_id'], 'pointer': '/gaps/0/detail',
                                      'quote': 'Skipped.', 'cell_id': h.cell(0), 'stage': 'journey',
                                      'revision': journey['revision'], 'capture': [{'material': journey['material'][0]['sha256']}]})
        next(f for f in moved['findings'] if f['id'] == 'F-preview-tool')['observation_refs'].append('skipped')
        _, problems = report_module.validate_synthesis(inputs, moved)
        self.assertIn(('unsupported_capture', 'observations[14].capture[0]'), {(p['code'], p['location']) for p in problems})
        moved['observations'][-1]['capture'] = []  # a gap with no file is valid and needs none
        _, problems = report_module.validate_synthesis(inputs, moved)
        self.assertFalse([p for p in problems if p['location'].startswith('observations[14]')], problems)

    def test_a_fresh_capture_carries_no_test_state_caveat(self):
        """Control for NonFreshStateTest: a verified fresh anonymous pack adds no state and claims no caveat."""
        record, _ = self.analysed()
        self.assertEqual({s.get('test_state') for s in record['inputs']['evidence']['sources']}, {None})
        code, out = self.h.render()
        self.assertEqual(code, 0, out)
        report = (Path(out['data']['bundle']) / 'report.md').read_text()
        self.assertNotIn('non-fresh', report.lower())
        self.assertNotIn('shown beside', report)

    def test_a_planted_marker_or_machine_path_in_analyst_text_is_refused_without_its_value(self):
        h = self.h
        _, record = h.bind_analysis()
        value = synthesis_for(h, record)
        value['findings'][0]['statement'] += ' ' + MARKER
        value['backlog'][0]['rationale'] = 'See /' + 'home/someone/notes for details.'
        code, out = self.check(record, value)
        self.assertEqual(code, 1)
        self.assertEqual({'suspected_secret', 'absolute_path'} & {p['code'] for p in out['data']['problems']},
                         {'suspected_secret', 'absolute_path'})
        self.assertNotIn(MARKER, json.dumps(out))


# ----------------------------------------------------------------------------- REQ-COUNTS


class CountsTest(ReportCase):
    def test_complete_displayed_collection_is_compared_and_tampering_is_refused(self):
        h = self.h
        self.analysed()
        bundle = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'bundle')['bundle'])
        self.assertEqual(h.rp(*h.study('verify-bundle'), '--bundle', bundle)[0], 0)
        original = {p: p.read_bytes() for p in bundle.rglob('*') if p.is_file()}

        def tamper(change):
            for p, data in original.items():
                p.write_bytes(data)
            data = json.loads((bundle / 'findings.json').read_text())
            change(data)
            (bundle / 'findings.json').write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
            return self.problems(h.rp(*h.study('verify-bundle'), '--bundle', bundle))

        self.assertIn('displayed_findings_mismatch', tamper(lambda d: d['findings'].pop()))
        self.assertIn('displayed_findings_mismatch', tamper(lambda d: d['findings'].append(
            dict(d['findings'][0], id='F-invented'))))
        self.assertIn('duplicate_identity', tamper(lambda d: d['findings'].append(d['findings'][0])))
        self.assertIn('displayed_counts_mismatch', tamper(lambda d: d['findings'][0]['support'].update(cells=4)))
        self.assertIn('zero_denominator', tamper(
            lambda d: next(f for f in d['findings'] if f['id'] == 'F-add-to-plan-hidden')['support']['journey'].update(of=0)))
        # A count changed in the rendered Markdown alone is refused too: the whole collection is compared.
        for p, data in original.items():
            p.write_bytes(data)
        report = bundle / 'report.md'
        report.write_text(report.read_text().replace('3 of 4 declared cells', '4 of 4 declared cells', 1))
        self.assertIn('displayed_collection_mismatch', self.problems(h.rp(*h.study('verify-bundle'), '--bundle', bundle)))
        (bundle / 'extra.md').write_text('An extra finding.\n')
        self.assertIn('unexpected_file', self.problems(h.rp(*h.study('verify-bundle'), '--bundle', bundle)))

    def test_duplicate_identities_and_claimed_counts_are_refused(self):
        h = self.h
        _, record = h.bind_analysis()
        good = synthesis_for(h, record)
        twice = copy.deepcopy(good)
        twice['findings'].append(dict(twice['findings'][0]))
        self.assertIn('duplicate_identity', self.problems(self.check(record, twice)))
        repeated = copy.deepcopy(good)
        repeated['observations'].append(dict(repeated['observations'][0], ref='dense-again'))
        repeated['findings'][0]['observation_refs'].append('dense-again')
        self.assertIn('duplicate_identity', self.problems(self.check(record, repeated)))
        claimed = copy.deepcopy(good)
        claimed['findings'][2]['support'] = {'cells': 4}
        self.assertIn('support_mismatch', self.problems(self.check(record, claimed)))
        # Two quotes from one cell are one cell of support.
        same_cell = copy.deepcopy(good)
        same_cell['findings'][0]['observation_refs'] = ['dense', 'three']
        self.assertEqual(self.check(record, same_cell)[0], 0)
        code, out = h.run_analysis(same_cell)
        self.assertEqual(code, 0, out)
        bundle = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'same-cell')['bundle'])
        shown = json.loads((bundle / 'findings.json').read_text())
        self.assertEqual(next(f for f in shown['findings'] if f['id'] == 'F-dense-first-screen')['support']['cells'], 1)


# ----------------------------------------------------------------------------- REQ-PRIORITY


class PriorityTest(ReportCase):
    def test_frequency_cannot_set_severity_and_effort_needs_a_cited_authorised_assessment(self):
        h = self.h
        _, record = h.bind_analysis()
        good = synthesis_for(h, record)
        frequency = copy.deepcopy(good)
        frequency['backlog'][2].update(user_impact='major', impact_reason='Three of four cells mentioned it.')
        self.assertIn('impact_frequency_only', self.problems(self.check(record, frequency)))
        overstated = copy.deepcopy(good)
        overstated['backlog'][2]['evidence_strength'] = 'direct-observation'
        self.assertIn('evidence_strength_overstated', self.problems(self.check(record, overstated)))
        effort = copy.deepcopy(good)
        effort['backlog'][0]['effort'] = {'state': 'assessed', 'assessment_id': 'eng-estimate'}
        self.assertIn('effort_unsupported', self.problems(self.check(record, effort)))
        effort['backlog'][0]['effort'] = {'state': 'small'}
        self.assertIn('effort_unsupported', self.problems(self.check(record, effort)))
        missing = copy.deepcopy(good)
        missing['backlog'][0]['uncertainty'] = ''
        self.assertIn('priority_incomplete', self.problems(self.check(record, missing)))


# ----------------------------------------------------------------------------- REQ-FIDELITY


class FidelityTest(ReportCase):
    def test_a_coordinator_edit_joins_the_authors_and_a_reviewer_of_its_lineage_is_refused_before_dispatch(self):
        h = self.h
        record, synthesised = self.analysed()
        edited = synthesis_for(h, record)
        edited['findings'][0]['title'] = 'The first screen feels long'
        out = h.rp_ok(*h.study('edit'), '--input', h.write('edit.json', {
            'base_record_sha256': synthesised['record_sha256'], 'synthesis': edited, 'reason': 'clearer title'}),
            '--capabilities', h.coordinator_caps('antigravity', 'gemini-fixture-pro'))
        self.assertEqual(sorted(a['role'] for a in out['authors']), ['analyst', 'coordinator'])
        bundle = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'edited')['bundle'])
        self.assertIn('coordinator (google lineage', (bundle / 'report.md').read_text())
        charged = h.charged()
        self.refused(h.rp(*h.study('review-slot'), '--bundle', bundle, '--capabilities', h.catalog(), '--now', BEFORE),
                     'reviewer_same_lineage')
        self.assertEqual(h.charged(), charged, 'nothing was dispatched or charged')
        # Pure re-rendering of unchanged structured inputs adds no author.
        again = h.rp_ok(*h.study('render'), '--out', h.base / 'edited-again')
        self.assertEqual(sorted(a['role'] for a in again['authors']), ['analyst', 'coordinator'])

    def test_a_coordinator_edit_after_approval_stales_the_review_and_needs_a_new_round(self):
        record, bundle = self.reviewed()
        h = self.h
        self.assertEqual(h.accept('review')[0], 0)
        synthesis_sha = h.rp_ok(*h.study('status'))['synthesis_record_sha256']
        edited = synthesis_for(h, record)
        edited['decision']['summary'] = 'Two personas split on the dense first screen; the dietary question stays open.'
        h.rp_ok(*h.study('edit'), '--input', h.write('edit.json', {'base_record_sha256': synthesis_sha,
                                                                   'synthesis': edited, 'reason': 'clearer summary'}),
                '--capabilities', h.coordinator_caps())
        self.assertNotEqual(h.validate('review')[0], 0)
        self.assertEqual(h.rp_ok(*h.study('status'))['review_status'], 'review-stale')
        # A new round on the old report bytes is held before any charge.
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'review', 'reason': 'report edited', 'category': 'review'})
        request = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'review')['request_id']
        charged = h.charged()
        self.refused(h.admit(h.view, request, 'review', purpose='repair'), 'review_slot_stale')
        self.assertEqual(h.charged(), charged)
        bundle2 = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'bundle-2')['bundle'])
        bound = h.bind_review(bundle2)
        self.assertEqual((bound['round'], sorted(a['lineage'] for a in bound['authors'])), (2, ['anthropic', 'openai']))

    def test_reviewer_availability_and_observed_authors_are_checked_before_any_review_dispatch(self):
        h = self.h
        self.analysed()
        bundle = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'bundle')['bundle'])
        charged = h.charged()
        missing = {'providers': [p for p in CAPS['providers'] if p['providerInstanceId'] != 'antigravity']}
        self.refused(h.rp(*h.study('review-slot'), '--bundle', bundle, '--capabilities', h.catalog(caps=missing),
                          '--now', BEFORE), 'reviewer_unavailable')
        # A later host source for the analyst's own request names another model: the recorded author lineage is no
        # longer observed, so review binding refuses until it is reconciled; nothing is dispatched or charged.
        host = next(x for x in h.job_state()['tasks'] if x['task_id'] == 'analysis')['handles'][0]['task_id']
        code, out = h.observe('analysis', kind='reconciled', request_id='analysis-r0', host_task_id=host,
                              status='completed', work_state='result_available', has_pending_child_runs=False,
                              status_identity=ident(CLAUDE))
        self.assertEqual(code, 0, out)
        self.refused(h.rp(*h.study('review-slot'), '--bundle', bundle, '--capabilities', h.catalog(), '--now', BEFORE),
                     'author_identity_unverified')
        self.assertEqual(h.charged(), charged)

    def test_an_approval_that_leaves_a_criterion_unpassed_stays_adverse(self):
        h = self.h
        self.analysed()
        bundle = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'bundle')['bundle'])
        h.bind_review(bundle)
        h.run_review(verdict='approve', status='failed')
        code, out = h.accept('review')
        self.assertNotEqual(code, 0)
        self.assertFalse(out.get('accepted'))
        # The shared gate refuses first; the pinned study validator, run on the same frozen observation, agrees.
        frozen = sorted((h.root / h.view['study_id'] / 'observations').glob('review-*.json'))[-1]
        proc = subprocess.run([sys.executable, str(fg3.INSTALL['package'] / 'scripts' / 'validate_study.py'),
                               '--input', str(frozen)], capture_output=True, text=True, timeout=120)
        verdict = json.loads(proc.stdout)
        self.assertEqual((proc.returncode, verdict['accepted']), (1, False))
        problems = verdict['requirement_outcomes']['STUDY-REVIEW']['evidence']['problems']
        # The shared strict parser refuses an approval with a failed criterion, so the round has no ingested approval.
        execution = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'review')['execution_history'][-1]
        self.assertTrue(execution.get('malformed'), execution)
        self.assertIn('review_not_ingested', {p['code'] for p in problems})

    def test_a_reviewer_without_a_verified_observed_lineage_never_accepts(self):
        h = self.h
        self.analysed()
        bundle = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'bundle')['bundle'])
        h.bind_review(bundle)
        h.run_review(identity={'providerInstanceId': 'antigravity'})  # the host reported no model
        code, out = h.accept('review')
        self.assertNotEqual(code, 0)
        self.assertFalse(out.get('accepted'))
        self.assertEqual(h.rp_ok(*h.study('status'))['review_status'], 'unreviewed')

    def test_a_contested_finding_is_carried_into_the_next_round_and_budgets_block_further_rounds(self):
        h = self.h
        self.analysed()
        bundle = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'bundle')['bundle'])
        h.bind_review(bundle)
        finding = {'id': 'R1-hidden-dissent', 'severity': 'blocker', 'scenario': 'The dissent looks hidden.',
                   'source_evidence': 'report.md Dissent section'}
        h.run_review(verdict='adverse', findings=[finding])
        code, out = h.accept('review')
        self.assertNotEqual(code, 0)
        # The next round is refused until the coordinator disposes of the earlier finding.
        self.refused(h.rp(*h.study('review-slot'), '--bundle', bundle, '--capabilities', h.catalog(), '--now', BEFORE),
                     'prior_findings_undisposed')
        h.dispose('review-r0', finding, 'rejected', 'Contested: the Dissent section shows F-detail-trusted with its support.\n')
        bound = h.bind_review(bundle)
        self.assertEqual(bound['round'], 2)
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'review', 'reason': 'contested review round',
                           'category': 'review'})
        request = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'review')['request_id']
        brief, _ = h.run_review(request=request, purpose='repair')
        prior = brief['resources']['focus_group_review']['prior_rounds']
        self.assertEqual([(r['verdict'], [f['finding']['id'] for f in r['findings']], [f['disposition'] for f in r['findings']])
                          for r in prior], [('adverse', ['R1-hidden-dissent'], ['rejected'])])
        code, out = h.accept('review')
        self.assertEqual((code, out.get('accepted')), (0, True), out)
        # The shared review repair pool is spent: a third round is blocked, not launched.
        self.refused(h.rp(*h.study('review-slot'), '--bundle', bundle, '--capabilities', h.catalog(), '--now', BEFORE),
                     'review_budget_exhausted')

    def test_a_completion_the_shared_parser_never_recorded_is_not_a_synthesis(self):
        h = self.h
        _, record = h.bind_analysis()
        # The analyst wrote its synthesis and reported done, but the shared parser never recorded the result.
        self.refused(h.run_analysis(synthesis_for(h, record), deliver=False), 'not_ingested_by_job')
        self.refused(h.render(), 'synthesis_missing')
        code, out = h.rp(*h.study('observation'), '--stage', 'analysis')
        self.assertEqual((code, out['error']['code']), (1, 'synthesis_missing'))

    def test_a_quote_changed_after_approval_stales_the_review_and_blocks_export(self):
        record, bundle = self.reviewed()
        h = self.h
        self.assertEqual(h.accept('review')[0], 0)
        self.assertEqual(h.validate('review')[0], 0)
        findings = bundle / 'findings.json'
        findings.write_bytes(findings.read_bytes().replace(b'I could not find where to add a recipe to my plan.',
                                                           b'I could never find where to add a recipe to my plan.'))
        code, out = h.validate('review')
        self.assertNotEqual(code, 0)
        self.assertFalse(out.get('accepted'))
        self.refused(h.rp(*h.study('export'), '--bundle', bundle, '--out', h.base / 'export'), 'bundle_mismatch')
        self.assertEqual(h.rp_ok(*h.study('status'))['review_status'], 'review-stale')

    def test_changed_accepted_evidence_stales_analysis_inputs_and_holds_the_analyst(self):
        h = self.h
        _, record = h.bind_analysis()
        notes = h.root / h.view['study_id'] / 'artifacts' / 'tasks' / 'jr-01' / 'notes.txt'
        notes.write_text('changed after acceptance\n')
        code, out = h.admit(h.view, 'analysis-r0', 'analysis')
        self.assertEqual((code, out['error']['code']), (1, 'analysis_inputs_stale'), out)
        self.assertEqual(h.charged().get('analysis_repairs'), None)

    def test_a_changed_delivered_context_file_holds_the_analyst_before_any_charge(self):
        h = self.h
        _, record = h.bind_analysis()
        delivered = Path(record['files'][0]['path'])
        delivered.write_bytes(delivered.read_bytes() + b'drift')
        charged = h.charged()
        self.refused(h.admit(h.view, 'analysis-r0', 'analysis'), 'inputs_changed')
        self.assertEqual(h.charged(), charged)
        code, out = h.job('prepare', {'caller': h.caller, 'task_id': 'analysis'})
        self.assertNotEqual(code, 0)
        self.assertIn('context file bytes differ', out)


# ----------------------------------------------------------------------------- REQ-EXPORT


class ExportTest(ReportCase):
    def test_unreviewed_export_is_labelled_and_tampered_or_broken_bundles_are_refused(self):
        h = self.h
        self.analysed()
        bundle = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'bundle')['bundle'])
        out = h.rp_ok(*h.study('export'), '--bundle', bundle, '--out', h.base / 'export')
        self.assertEqual(out['review_status'], 'unreviewed')
        self.assertIn('Unreviewed', (h.base / 'export' / 'review-status.md').read_text())
        # The bundle is never exported once any byte differs from the deterministic render.
        report = bundle / 'report.md'
        original = report.read_bytes()
        report.write_bytes(original + b'\n[missing](evidence/none.png)\n')
        self.refused(h.rp(*h.study('export'), '--bundle', bundle, '--out', h.base / 'export-2'), 'bundle_mismatch')
        report.write_bytes(original)
        # A relocated export that gains a planted marker, a machine path or a broken link fails verification.
        moved = h.base / 'moved'
        shutil.copytree(h.base / 'export', moved)
        for addition, code in ((MARKER, 'suspected_secret'), ('/' + 'home/someone/file.png', 'absolute_path'),
                               ('[gone](evidence/nothing.png)', 'broken_link')):
            with self.subTest(code=code):
                shutil.rmtree(moved)
                shutil.copytree(h.base / 'export', moved)
                target_file = moved / 'issues' / 'B-sort-by-cost.md'
                target_file.write_text(target_file.read_text() + addition + '\n')
                manifest = json.loads((moved / 'export.json').read_text())
                data = target_file.read_bytes()
                manifest['files']['issues/B-sort-by-cost.md'] = {'sha256': sha(data), 'bytes': len(data)}
                (moved / 'export.json').write_text(json.dumps(manifest))
                verdict = h.rp('verify-export', '--bundle', moved)
                self.assertIn(code, self.problems(verdict))
                self.assertNotIn(MARKER, json.dumps(verdict[1]))
        # A relocated export whose source projections no longer back its observations fails verification, read from the
        # export's own bytes: a missing source, a foreign record, a changed source quote, an unresolvable pointer, a
        # copied payload that no longer hashes to the accepted payload, and a missing capture file.
        findings = json.loads((h.base / 'export' / 'findings.json').read_text())
        add = next(o for o in findings['observations'] if o['pointer'] == '/goals/0/reactions/0' and o['cell_id'] == h.cell(0))
        first = next(o for o in findings['observations'] if o['stage'] == 'first-impression')
        first_body = json.loads((h.base / 'export' / first['source_file']).read_text())

        def edit_json(name, change):
            def apply(root):
                value = json.loads((root / name).read_text())
                change(value)
                return {name: (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()}
            return apply

        def drop(name):
            return lambda root: {name: None}

        def set_quote(value):
            value['payload']['goals'][0]['reactions'][0] = 'I found it at once.'

        def set_pointer(value):
            next(o for o in value['observations'] if o['id'] == add['id'])['pointer'] = '/goals/0/reactions/7'
        cases = {'source_missing': drop(add['source_file']),
                 'source_mismatch': edit_json(add['source_file'], lambda v: v.update(record_sha256='0' * 64)),
                 'quote_mismatch': edit_json(add['source_file'], set_quote),
                 'pointer_unresolved': edit_json('findings.json', set_pointer),
                 'source_hash_mismatch': lambda root: {first_body['payload_file']:
                                                       (root / first_body['payload_file']).read_bytes() + b' '},
                 'capture_missing': drop(next(e['path'] for e in json.loads((h.base / 'export' / 'bundle.json')
                                                                             .read_text())['evidence']
                                              if e['name'] == 'notes.txt'))}
        for code, change in cases.items():
            with self.subTest(code=code):
                shutil.rmtree(moved)
                shutil.copytree(h.base / 'export', moved)
                manifest = json.loads((moved / 'export.json').read_text())
                for name, data in change(moved).items():
                    if data is None:
                        (moved / name).unlink()
                        manifest['files'].pop(name)
                    else:
                        (moved / name).write_bytes(data)
                        manifest['files'][name] = {'sha256': sha(data), 'bytes': len(data)}
                (moved / 'export.json').write_text(json.dumps(manifest))
                self.assertIn(code, self.problems(h.rp('verify-export', '--bundle', moved)))
        # Changed accepted journey material blocks export disclosure.
        (h.root / h.view['study_id'] / 'artifacts' / 'tasks' / 'jr-01' / 'notes.txt').write_text('changed\n')
        code, out = h.rp(*h.study('export'), '--bundle', bundle, '--out', h.base / 'export-3')
        self.assertEqual((code, out['error']['code']), (1, 'inputs_changed'), out)
        self.assertNotIn('export-3', [p.name for p in h.base.iterdir()])


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


class NonFreshStateTest(unittest.TestCase):
    """An approved returning-user test context reaches the analyst, the fidelity reviewer and the portable sources,
    and its caveat is rendered beside every first-impression finding and quote from the frozen source itself, even
    though the analyst never mentions it. Journey evidence, recorded in its own live cell context, carries none."""

    def test_returning_user_state_sits_beside_every_first_impression_finding_and_quote(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve() / 'study'
        base.mkdir()
        h = NonFreshHost(base)
        h.start(personas=1)
        for n, reaction in ((0, 'Calm and familiar; I know where everything is.'), (1, 'Clear enough to start.')):
            out = h.first(n, payload=h.fi_payload(n, reaction, walk=[('welcome-clean.txt', 'Short.')]))
            self.assertEqual(out['code'], 0, out['out'])
        for n in (0, 1):
            self.assertEqual(h.journey(n)[0], 0)
        for stage in ('first-impression', 'journey'):
            code, out = h.accept(stage)
            self.assertEqual((code, out.get('accepted')), (0, True), out)
        study_dir = h.root / h.view['study_id']
        raw = sorted(p for p in (study_dir / 'focus-group' / 'evidence').rglob('*.json')
                     if p.parent.name in ('first', 'packs', 'journeys'))
        raw += sorted((study_dir / 'artifacts' / 'tasks').rglob('*'))
        raw_before = {str(p): sha(p.read_bytes()) for p in raw if p.is_file()}

        def participant_requests():
            return {r: row for r, row in json.loads(h.ledger_bytes())['requests'].items()
                    if not str(row.get('slot', '')).startswith(('analysis:', 'review:'))}
        charged = participant_requests()

        _, record = h.bind_analysis()
        s, c = sources(record), [h.cell(0), h.cell(1)]
        with self.subTest('analyst inputs'):
            for view in (record['inputs']['evidence'], delivered_inputs(record)['evidence']):
                states = {(r['cell_id'], r['stage']): r.get('test_state') for r in view['sources']}
                self.assertEqual(states, {(c[0], 'first-impression'): TEST_STATE, (c[1], 'first-impression'): TEST_STATE,
                                          (c[0], 'journey'): None, (c[1], 'journey'): None})

        bound = [{'material': m['sha256']} for m in s[(c[0], 'journey')]['material'] if 0 in m['goals']]

        def obs(ref, n, stage, pointer, capture):
            src = s[(c[n], stage)]
            value = src['payload']
            for part in pointer[1:].split('/'):
                value = value[int(part)] if isinstance(value, list) else value[part]
            return {'ref': ref, 'source_id': src['source_id'], 'pointer': pointer, 'quote': value, 'cell_id': c[n],
                    'stage': stage, 'revision': src['revision'], 'capture': capture}
        synthesis = {
            'schema': 'focus-group/synthesis', 'schema_version': 1, 'study_revision': h.view['revision'],
            'inputs_sha256': record['inputs_sha256'],
            'decision': {'answer': 'inconclusive', 'summary': 'Two synthetic cells only.', 'finding_ids': [],
                         'uncertainty': 'One persona.'},
            'observations': [
                obs('calm', 0, 'first-impression', '/initial_viewport/reaction', [{'pack': 'initial-viewport.png'}]),
                obs('short', 1, 'first-impression', '/walkthrough/0/reaction', [{'pack': 'welcome-clean.txt'}]),
                obs('quick', 0, 'journey', '/goals/0/reactions/0', bound)],
            # The analyst never mentions the test state: the caveat comes from the frozen sources alone.
            'findings': [{'id': 'F-calm', 'category': 'first-impression', 'title': 'The first screen feels calm',
                          'statement': 'One cell found the first screen calm and familiar.', 'observation_refs': ['calm'],
                          'verification': 'observed'},
                         {'id': 'F-mixed', 'category': 'preserve', 'title': 'Short and quick',
                          'statement': 'The text read as short and the journey felt quick.',
                          'observation_refs': ['short', 'quick'], 'verification': 'observed'},
                         {'id': 'F-journey', 'category': 'preserve', 'title': 'Planning felt quick',
                          'statement': 'One journey felt quick.', 'observation_refs': ['quick'],
                          'verification': 'observed'}],
            'backlog': []}
        code, out = h.run_analysis(synthesis)
        self.assertEqual(code, 0, out)
        self.assertEqual(h.accept('analysis')[0], 0)
        code, out = h.render()
        self.assertEqual(code, 0, out)
        bundle = Path(out['data']['bundle'])
        h.bind_review(bundle)
        review = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'review')
        reviewed = {Path(d['path']).name: Path(d['path']).read_text() for d in review['reviewed_documents']}
        for name, text in (('bundle', (bundle / 'report.md').read_text()), ('reviewer', reviewed['report.md'])):
            with self.subTest('rendered caveat', copy=name):
                sections = finding_sections(text)
                quotes = {ref: [line for section in sections.values() for line in section.splitlines()
                                if f'"{q}"' in line]
                          for ref, q in (('calm', 'Calm and familiar; I know where everything is.'), ('short', 'Short.'),
                                         ('quick', 'Quick, but I lost my place once.'))}
                self.assertEqual([len(quotes[ref]) for ref in ('calm', 'short', 'quick')], [1, 1, 2])
                for line in (sections['F-calm'], sections['F-mixed'], *quotes['calm'], *quotes['short']):
                    for phrase in ('Non-fresh test state', 'returning test user', 'onboarding completed',
                                   'session_marker', 'tour_seen'):
                        self.assertIn(phrase, line)
                for line in (sections['F-journey'], *quotes['quick']):
                    self.assertNotIn('Non-fresh', line)
            with self.subTest('coverage claim', copy=name):
                coverage = text.split('## Coverage and identity', 1)[1].split('\n## ', 1)[0]
                self.assertIn('2 of 2 usable first impressions captured in non-fresh test state', coverage)
        with self.subTest('portable sources and findings'):
            observations = {o['ref']: o for o in json.loads((bundle / 'findings.json').read_text())['observations']}
            self.assertEqual({ref: o.get('test_state') for ref, o in observations.items()},
                             {'calm': TEST_STATE, 'short': TEST_STATE, 'quick': None})
            for ref in ('calm', 'short', 'quick'):
                projected = json.loads((bundle / observations[ref]['source_file']).read_text())
                self.assertEqual(projected.get('test_state'), observations[ref].get('test_state'))
            self.assertNotIn('fixture-test-account-7', ''.join(reviewed.values()))
        # Raw captures, frozen records, accepted payloads and participant charges are untouched.
        self.assertEqual({str(p): sha(Path(p).read_bytes()) for p in raw_before}, raw_before)
        self.assertEqual(participant_requests(), charged)


# ----------------------------------------------------------------------------- incremental journeys (REQ-FIDELITY)


class IncrementalJourneyTest(unittest.TestCase):
    """One cell's journey runs before the next journey slot exists (a pilot or per-cell order). Adding the later slot
    stales only the stage's acceptance: the executed journey keeps its request, result, charge and acceptance
    eligibility, and the study reaches an accepted analysis and fidelity review without re-running it."""

    def test_a_later_journey_slot_never_strands_an_executed_journey(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve() / 'study'
        base.mkdir()
        h = ReportHost(base)
        h.start(personas=1)  # one persona on two model lineages: two combined cells
        for n in (0, 1):
            out = h.first(n, payload=h.fi_payload(n, 'Clear enough to start.', walk=[('welcome-clean.txt', 'Short.')]))
            self.assertEqual(out['code'], 0, out['out'])
        self.assertEqual(h.journey(0)[0], 0)

        def jr01():
            return next(t for t in h.job_state()['tasks'] if t['task_id'] == 'jr-01')
        executed = jr01()
        self.assertEqual((executed['status'], executed.get('inputs_stale')), ('awaiting-acceptance', None))
        charged = h.charged()
        self.assertEqual(h.journey(1)[0], 0)  # adds jr-02 through journey-slots and a recorded plan revision
        kept = jr01()
        self.assertEqual((kept['status'], kept.get('inputs_stale'), kept['request_id'], kept['attempt'],
                          kept['execution_history'], kept['handles'], kept['brief']),
                         ('awaiting-acceptance', None, 'jr-01-r0', executed['attempt'], executed['execution_history'],
                          executed['handles'], executed['brief']))
        self.assertEqual(sum(h.charged().values()), sum(charged.values()) + 1, 'only the new journey was charged')
        resumed = {s['slot']: s['state'] for s in h.resume()['slots']}
        self.assertEqual({resumed[f'{h.cell(n)}:journey'] for n in (0, 1)}, {'accepted'})
        for stage in ('first-impression', 'journey'):
            code, out = h.accept(stage)
            self.assertEqual((code, out.get('accepted')), (0, True), out)
        # The analysis and fidelity review reach current acceptance on the incrementally built journey stage.
        _, record = h.bind_analysis()
        src = sources(record)[(h.cell(0), 'first-impression')]
        synthesis = {'schema': 'focus-group/synthesis', 'schema_version': 1, 'study_revision': h.view['revision'],
                     'inputs_sha256': record['inputs_sha256'],
                     'decision': {'answer': 'inconclusive', 'summary': 'Two synthetic cells only.', 'finding_ids': [],
                                  'uncertainty': 'One persona.'},
                     'observations': [{'ref': 'clear', 'source_id': src['source_id'], 'pointer': '/initial_viewport/reaction',
                                       'quote': 'Clear enough to start.', 'cell_id': h.cell(0), 'stage': 'first-impression',
                                       'revision': src['revision'], 'capture': [{'pack': 'initial-viewport.png'}]}],
                     'findings': [{'id': 'F-clear-start', 'category': 'preserve', 'title': 'A clear start',
                                   'statement': 'One cell found the start clear.', 'observation_refs': ['clear'],
                                   'verification': 'observed'}], 'backlog': []}
        code, out = h.run_analysis(synthesis)
        self.assertEqual(code, 0, out)
        self.assertEqual(h.accept('analysis')[0], 0)
        bundle = Path(h.render()[1]['data']['bundle'])
        h.bind_review(bundle)
        h.run_review()
        code, out = h.accept('review')
        self.assertEqual((code, out.get('accepted')), (0, True), out)
        final = jr01()
        self.assertEqual((final['request_id'], final['attempt'], len(final['execution_history'])),
                         ('jr-01-r0', executed['attempt'], 1))


if __name__ == '__main__':
    unittest.main()
