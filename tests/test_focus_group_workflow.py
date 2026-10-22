"""focus-group REQ-INTEGRATION: invented studies through every real coordinator and helper boundary together.

One Pantry Planner study (an invented prototype served by a loopback HTTP origin) goes from the suggested panel to an
edited, approved revision; a capture pack whose planted marker is quarantined before a sanitised derivative is
approved; model pilots; first impressions, one of them interrupted after dispatch and one whose dispatch response is
lost; journeys in browser contexts whose isolation is probed with conflicting cookies and storage over the loopback
origin; strict ingestion through the shared parser; a delegated synthesis; an adverse fidelity review and its
legitimate repair; native stage acceptance by the pinned validator; and a relocated portable export. A second study
covers a provider gap, a provider outage and a model whose child contexts share one browser profile, ending in a
capture-only revision. A third check declares the integration stage: every one of the 25 requirement IDs mapped to the
tests that exercise it.

The host is invented: tests transcribe the observations and complete worker results a coordinator would record. The
fake browser contexts keep cookies in real cookie jars over loopback HTTP and storage in memory, so this is fixture
evidence for the refusal and recovery paths, never live isolation. Nothing calls a model, a real browser, T3, imps or
GitHub, and nothing here says anything about live provider compatibility.
"""
import copy
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import test_focus_group_evidence as fg2  # noqa: E402
from tests import test_focus_group_lifecycle as fg3  # noqa: E402
from tests import test_focus_group_report as fg4  # noqa: E402
from tests.test_focus_group_plan import AFTER, BEFORE, FIXTURE_ORIGIN, Workspace, provider, sha  # noqa: E402

LATER = '2029-06-01T00:00:30Z'  # a provider-gap catalog reading at the controlled clock
RECOVERED = '2029-06-01T00:00:45Z'  # the next, newer reading: the provider can run tasks again
REQUIREMENTS = ('REQ-COMMAND', 'REQ-PLAN', 'REQ-PANEL', 'REQ-LIMITS', 'REQ-CONTRACT', 'REQ-CAPTURE', 'REQ-BLIND',
                'REQ-FIRST-IMPRESSION', 'REQ-ISOLATION', 'REQ-JOURNEY', 'REQ-IDENTITY', 'REQ-PILOT', 'REQ-SESSION',
                'REQ-LIFECYCLE', 'REQ-RESUME', 'REQ-REPORT', 'REQ-EVIDENCE', 'REQ-COUNTS', 'REQ-PRIORITY',
                'REQ-FIDELITY', 'REQ-EXPORT', 'REQ-ARCHITECTURE', 'REQ-INSTALL', 'REQ-DOCS', 'REQ-INTEGRATION')
COMBINED = 'tests.test_focus_group_workflow.CombinedStudyTest.test_edited_plan_to_reviewed_relocated_export'
GAPS = 'tests.test_focus_group_workflow.GapStudyTest.test_provider_gap_and_shared_profile_keep_capture_and_an_honest_scope'
# The declared integration stage: each requirement and the tests, across the focused modules, that exercise it together.
INTEGRATION_STAGE = {
    'id': 'focus-group-integration',
    'requirements': {
        'REQ-COMMAND': [COMBINED, 'tests.test_focus_group_plan.CommandTest',
                        'tests.test_focus_group_install.RelocatedInstallTest.'
                        'test_1_an_unadopted_move_is_refused_then_adoption_verifies_and_routes_to_the_moved_package'],
        'REQ-PLAN': [COMBINED, 'tests.test_focus_group_plan.PlanTest'],
        'REQ-PANEL': [COMBINED, 'tests.test_focus_group_plan.PanelTest'],
        'REQ-LIMITS': [COMBINED, GAPS, 'tests.test_focus_group_plan.LimitsTest'],
        'REQ-CONTRACT': [GAPS, 'tests.test_focus_group_plan.ContractTest'],
        'REQ-CAPTURE': [COMBINED, 'tests.test_focus_group_evidence.CaptureTest'],
        'REQ-BLIND': [COMBINED, 'tests.test_focus_group_evidence.BlindTest'],
        'REQ-FIRST-IMPRESSION': [COMBINED, 'tests.test_focus_group_evidence.FirstImpressionTest'],
        'REQ-ISOLATION': [COMBINED, GAPS, 'tests.test_focus_group_evidence.IsolationTest'],
        'REQ-JOURNEY': [COMBINED, GAPS, 'tests.test_focus_group_evidence.JourneyTest'],
        'REQ-IDENTITY': [COMBINED, 'tests.test_focus_group_lifecycle.IdentityTest',
                        'tests.test_focus_group_report_identity.IdentityProjectionTest'],
        'REQ-PILOT': [COMBINED, GAPS, 'tests.test_focus_group_lifecycle.PilotTest'],
        'REQ-SESSION': [COMBINED, GAPS, 'tests.test_focus_group_lifecycle.SessionTest'],
        'REQ-LIFECYCLE': [COMBINED, GAPS, 'tests.test_focus_group_lifecycle.LifecycleTest'],
        'REQ-RESUME': [COMBINED, GAPS, 'tests.test_focus_group_lifecycle.ResumeTest'],
        'REQ-REPORT': [COMBINED, 'tests.test_focus_group_report.EndToEndTest'],
        'REQ-EVIDENCE': [COMBINED, 'tests.test_focus_group_report_checks.EvidenceTest'],
        'REQ-COUNTS': [COMBINED, 'tests.test_focus_group_report_checks.CountsTest'],
        'REQ-PRIORITY': [COMBINED, 'tests.test_focus_group_report_checks.PriorityTest'],
        'REQ-FIDELITY': [COMBINED, 'tests.test_focus_group_report_fidelity.FidelityTest',
                         'tests.test_focus_group_report_fidelity_state.FidelityTest'],
        'REQ-EXPORT': [COMBINED, 'tests.test_focus_group_report_checks.ExportTest'],
        'REQ-ARCHITECTURE': ['tests.test_focus_group_install.ArchitectureTest'],
        'REQ-INSTALL': ['tests.test_focus_group_install.RelocatedInstallTest',
                        'tests.test_focus_group_install.DamagedPackageTest',
                        'tests.test_focus_group_install_handoff.RelocatedInstallTest',
                        'tests.test_focus_group_install_lifecycle.RelocatedInstallTest'],
        'REQ-DOCS': ['tests.test_focus_group_workflow.IntegrationStageTest.test_the_guide_covers_the_operator_decisions'],
        'REQ-INTEGRATION': [COMBINED, GAPS,
                            'tests.test_focus_group_workflow.IntegrationStageTest.'
                            'test_the_integration_stage_covers_every_requirement_with_real_tests'],
    },
}


def setUpModule():
    fg3.setUpModule()  # the generic job, acceptance and validator helpers, installed once into a temporary prefix


def tearDownModule():
    fg3.tearDownModule()


class WorkflowHost(fg4.ReportHost):
    """The FG-4 host with a loopback target. Journey contexts are bound from a real probe: every cell writes its own
    conflicting values under one shared key through its own fake browser context, then reads back what it can see.
    Optional interruptions exercise resume at the points a coordinator can be stopped."""

    def __init__(self, base, server, interrupt=True):
        super().__init__(base)
        self.server = server
        self.interrupt = interrupt
        self.events = {}
        self.probes = []
        self.isolated_cells = None  # None: bind every cell of a revision; otherwise only these cells
        self.observed_at = None  # when set, later catalog observations carry this (newer) time

    def catalog(self, now=BEFORE, caps=None, observations=None, observed_at=None):
        return super().catalog(now, caps, observations, observed_at or self.observed_at)

    def draft(self, **changes):
        draft = super().draft(**changes)
        if 'target' not in changes:
            draft['target'] = {'kind': 'url', 'url': self.server.origin + '/welcome', 'environment': 'fixture',
                               'label': 'Invented loopback Pantry Planner prototype'}
        return draft

    def loopback(self, value):
        return json.loads(json.dumps(value).replace(FIXTURE_ORIGIN, self.server.origin))

    def journey_payload(self, view, cell, brief_sha, context):
        return self.loopback(Workspace.journey_payload(view, cell, brief_sha, context))

    def journey_with(self, n, goal=None, gaps=(), notes=None):
        return super().journey_with(n, None if goal is None else self.loopback(goal), gaps, notes)

    def probe(self, view, ids, contexts):
        probe = self.evidence_ok('probe-plan', '--state-root', self.root, '--study', view['study_id'], '--input',
                                 self.write(f'probe-{len(self.probes)}.json', {'revision': view['revision'],
                                                                               'cell_ids': ids}))
        assert probe['origin'] == self.server.origin, probe
        for cid in ids:
            row = probe['cells'][cid]
            contexts[cid].write(probe['shared_key'], row['value'], row['own_key'])
        readings = {cid: contexts[cid].read(probe['shared_key'], [probe['cells'][o]['own_key'] for o in ids if o != cid])
                    for cid in ids}
        self.probes.append({'probe': probe, 'readings': readings})
        return probe, readings

    def bind(self, view, cid, probe, readings, reference):
        self.counter += 1
        return self.call_evidence('bind-context', '--state-root', self.root, '--study', view['study_id'], '--input',
                                  self.write(f'bind-{self.counter}.json', {
                                      'revision': view['revision'], 'cell_id': cid, 'child_tools': fg2.PREVIEW,
                                      'context': {'reference': reference, 'boundary': 'isolated-context'},
                                      'assignment': {'kind': 'host-enforced', 'source': 'fixture host binding receipt',
                                                     'receipt_sha256': sha(reference.encode()), 'child_ref': cid},
                                      'evidence_class': 'fixture',
                                      'probe': {'probe_id': probe['probe_id'], 'readings': readings}}))

    def bound_context(self, view, cell):
        if (view['revision'], cell) not in self.contexts:
            ids = [c['cell_id'] for c in view['cells']
                   if self.isolated_cells is None or c['cell_id'] in self.isolated_cells]
            probe, readings = self.probe(view, ids, {cid: fg2.FakeContext(self.server) for cid in ids})
            for cid in ids:
                reference = f'loopback-context-{sha(cid.encode())[:12]}'
                code, out = self.bind(view, cid, probe, readings, reference)
                assert code == 0, out
                self.contexts[(view['revision'], cid)] = {'reference': reference,
                                                          'binding_sha256': out['data']['binding_sha256']}
        return self.contexts[(view['revision'], cell)]

    # --- planning: the suggested panel, an operator edit and approval of the exact edited revision

    def start(self, personas=2, **changes):
        self.suggested = self.plan(self.draft())
        edited = self.draft(**changes)
        edited['personas'] = edited['personas'][:personas]
        edited['personas'][1]['priorities'] = ['cost per serving', 'meals that reuse leftovers']
        edited['limits']['max_concurrency'] = 3
        self.view = self.plan(edited)
        self.events['unapproved'] = self.call('check-run', '--state-root', self.root, '--study', self.view['study_id'],
                                              '--capabilities', self.catalog(), now=BEFORE)
        self.approve(self.view)
        self.events['ready'] = self.check_run(self.view)
        self.create_job()
        # Before any pilot is accepted, a model's other cell is held, not charged.
        self.events['pilot_hold'] = self.admit_slot(2, 'first-impression', 'fi-03-early')
        self.events['charged_after_hold'] = self.charged()
        return self.view

    # --- first impressions with two interruptions

    def finish_first(self, n, task, request, brief, host, payload):
        item = self.payload_file(task, payload)
        path = self.transport(self.worker_result(brief, [item]))
        completion = f'done-{request}'
        assert self.complete(task, request, host, completion)[0] == 0
        delivered = self.deliver(task, request, completion, path)
        code, out = self.ingest(task, request, completion, path)
        self.reconcile()
        return {'code': code, 'out': out, 'host': host, 'brief': brief, 'transport': path, 'completion': completion,
                'delivered': delivered, 'task': task, 'request': request}

    def first(self, n, request=None, identity='default', payload=None, result=None, admit=True):
        if not self.interrupt or n not in (1, 2) or request is not None or f'interrupted-{n}' in self.events:
            return super().first(n, request, identity, payload, result, admit)
        task, request = f'fi-{n + 1:02d}', f'fi-{n + 1:02d}-r0'
        payload = payload or self.first_payload(self.view, self.cell(n), self.documents[task]['sha256'])
        code, out = self.admit_slot(n, 'first-impression', request)
        assert code == 0, out
        brief = self.prepare(task)
        charged = self.charged()
        if n == 1:
            # Model B's pilot: delegate_task's response is lost. Resume lists the same request to dispatch again,
            # and the repeated admission is a duplicate that charges nothing.
            assert self.observe(task, kind='uncertain', request_id=request)[0] == 0
            resumed = self.resume()
            again = self.admit_slot(n, 'first-impression', request)
            self.events['interrupted-1'] = {'resume': resumed, 'again': again, 'charged': charged,
                                           'after': self.charged()}
            host = self.launch(task, request, identity, n)
        else:
            # Model A's second cell: the coordinator stops after dispatch. Resume reconciles and lists it in flight;
            # a fresh request for the same slot is refused and nothing more is charged.
            host = self.launch(task, request, identity, n)
            resumed = self.resume()
            fresh = self.admit_slot(n, 'first-impression', 'fi-03-again')
            self.events['interrupted-2'] = {'resume': resumed, 'fresh': fresh, 'charged': charged,
                                           'after': self.charged()}
        return self.finish_first(n, task, request, brief, host, payload)


def slot_states(resumed):
    return {s['slot']: s['state'] for s in resumed['slots']}


class Loopback(unittest.TestCase):
    def setUp(self):
        self.server = fg2.ProbeServer()
        self.addCleanup(self.server.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve() / 'study'
        base.mkdir()
        self.base = base

    def refused(self, outcome, code):
        self.assertEqual((outcome[0], outcome[1]['error']['code']), (1, code), outcome[1])
        return outcome[1]

    def accepted_records(self, h):
        folder = h.root / h.view['study_id'] / 'focus-group' / 'accepted'
        return {p.name: p.read_bytes() for p in folder.glob('*.json')}


# ----------------------------------------------------------------------------- the combined study


class CombinedStudyTest(Loopback):
    def test_edited_plan_to_reviewed_relocated_export(self):
        h = WorkflowHost(self.base, self.server)
        fg4.build_study(h)  # plan, edit, approve, capture, pilots, first impressions, journeys, stage acceptance
        study = h.root / h.view['study_id']

        # REQ-PLAN, REQ-PANEL, REQ-COMMAND: the suggested panel is four personas on two catalog lineages (eight cells,
        # sixteen participant attempts); planning launched nothing; the edited revision is a new hash and was refused
        # until approved.
        suggested = h.suggested
        self.assertEqual((len(suggested['cells']), suggested['task_counts']['participant_first_attempts'],
                          suggested['dispatched']), (8, 16, 0))
        self.assertEqual(len({(c['providerInstanceId']) for c in suggested['cells']}), 2)
        self.assertNotEqual(suggested['revision'], h.view['revision'])
        self.assertEqual(len(h.view['cells']), 4)
        self.assertEqual(h.view['task_counts']['participant_first_attempts'], 8)
        self.assertEqual(h.events['unapproved'][1]['error']['code'], 'unapproved_revision')
        status = h.status(h.view)
        self.assertEqual((status['approval']['state'], status['previous_revisions']), ('approved', [suggested['revision']]))
        self.assertTrue(any('unknown until each model pilot' in line for line in suggested['assessment']['limitations']))
        # REQ-CAPTURE: the planted marker quarantined the parent pack; only its sanitised, hash-bound derivative was
        # approved, and the marker appears in no study record.
        self.assertTrue(h.parent_manifest)
        self.assertNotIn(fg4.MARKER, ''.join(p.read_text(errors='replace') for p in study.rglob('*.json')))
        # REQ-PILOT: a model's other cell waited for its pilot and nothing was charged for the refusal.
        self.refused(h.events['pilot_hold'], 'pilot_pending')
        self.assertEqual(h.events['charged_after_hold'], {})
        # REQ-LIFECYCLE, REQ-RESUME: a lost dispatch response retries the same request without a charge; a dispatched
        # task interrupted mid-run is reconciled, listed in flight and never duplicated.
        lost = h.events['interrupted-1']
        self.assertEqual(lost['resume']['reconciliation']['actions']['dispatch_same_request'],
                         [{'task_id': 'fi-02', 'request_id': 'fi-02-r0'}])
        self.assertEqual((lost['again'][1]['data']['duplicate'], lost['again'][1]['data']['charged']), (True, False))
        self.assertEqual((lost['after'], lost['resume']['dispatched']), (lost['charged'], 0))
        stopped = h.events['interrupted-2']
        self.assertEqual(slot_states(stopped['resume'])[f'{h.cell(2)}:first-impression'], 'in-flight')
        self.assertIn('fi-03-r0', stopped['resume']['unresolved_owned_work'])
        self.assertEqual(self.refused(stopped['fresh'], 'slot_in_flight')['data']['requests'], ['fi-03-r0'])
        self.assertEqual(stopped['after'], stopped['charged'])
        # REQ-ISOLATION: each journey context saw only its own conflicting cookie, local and session values over the
        # loopback origin; no context saw another cell's key. Fixture evidence: never a live isolation claim.
        readings = h.probes[0]['readings']
        probe = h.probes[0]['probe']
        values = set()
        for cid, row in readings.items():
            own = probe['cells'][cid]['value']
            self.assertEqual(row['shared'], {'cookie': own, 'local': own, 'session': own})
            self.assertEqual(row['others_own_seen'], {'cookie': False, 'local': False, 'session': False})
            values.add(own)
        self.assertEqual(len(values), 4)
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        rows = {r['cell_id']: r for r in coverage['cells']}
        for n in (0, 1, 2):
            self.assertEqual((rows[h.cell(n)]['journey']['state'], rows[h.cell(n)]['journey']['evidence_class'],
                              rows[h.cell(n)]['journey']['live_isolation_claim']), ('hands-on-evidence', 'fixture', False))
        self.assertEqual(rows[h.cell(3)]['journey']['state'], 'gap')
        self.assertIs(coverage['combined_scope_complete'], False)
        # REQ-IDENTITY: requested and host-observed models are recorded apart; every accepted cell is verified.
        cells = {c['cell_id']: c for c in h.progress()['cells']}
        for n in range(4):
            row = cells[h.cell(n)]['first-impression']
            self.assertEqual((row['identity'], row['verified_coverage']), ('verified', True))
            self.assertEqual(cells[h.cell(n)]['requested']['model'], row['observed']['model'])
        # REQ-SESSION: cell 4's quarantined first attempt stays as raw private evidence, never as an accepted source.
        quarantined = [json.loads(p.read_text()) for p in (study / 'focus-group' / 'sessions' / 'fi-04-r0').glob('*.json')]
        self.assertTrue(quarantined)
        self.assertEqual(sum(1 for name in self.accepted_records(h) if name), 4 + 3 + 1)
        # REQ-BLIND, REQ-FIRST-IMPRESSION: cell 1's journey brief carries its own frozen first impression as data,
        # and no other cell's response, preferred finding or backlog.
        journey_brief = Path(h.journey_documents['jr-01']['path']).read_text()
        self.assertIn('Too much on the first screen; I want dinners, not a tour.', journey_brief)
        for foreign in ('The detailed recipe cards look trustworthy.', 'Clean, but I cannot see prices.', 'backlog'):
            self.assertNotIn(foreign, journey_brief)
        first_brief = Path(h.documents['fi-01']['path']).read_text()
        self.assertIn('Invented time-poor parent of two', first_brief)
        self.assertNotIn('Invented student cooking on a tight budget', first_brief)
        # Native stage acceptance: the pinned validator's current receipts, not a worker's say-so.
        for stage in ('first-impression', 'journey'):
            code, out = h.validate(stage)
            self.assertEqual((code, out.get('accepted')), (0, True), out)

        # REQ-FIDELITY: a delegated analyst (openai lineage) writes the synthesis; its stage is accepted natively.
        first_records = {k: v for k, v in self.accepted_records(h).items()}
        _, record = h.bind_analysis()
        code, out = h.run_analysis(fg4.synthesis_for(h, record))
        self.assertEqual(code, 0, out)
        synthesis_record = out['data']['record_sha256']
        self.assertEqual([a['lineage'] for a in out['data']['authors']], ['openai'])
        self.assertEqual(h.accept('analysis')[0], 0)
        code, out = h.render()
        self.assertEqual(code, 0, out)
        bundle = Path(out['data']['bundle'])
        # Round 1: the reviewer (google lineage) is adverse with a blocker; the review stage is not accepted and an
        # export made now is not called reviewed.
        self.assertEqual(h.bind_review(bundle)['round'], 1)
        finding = {'id': 'R1-gap-missing-from-summary', 'severity': 'blocker',
                   'scenario': 'The decision summary never says that one persona journey could not start.',
                   'source_evidence': 'report.md Decision summary; F-preview-tool'}
        h.run_review(verdict='adverse', findings=[finding])
        code, out = h.accept('review')
        self.assertNotEqual(code, 0)
        self.assertFalse(out.get('accepted'))
        early = h.rp_ok(*h.study('export'), '--bundle', bundle, '--out', h.base / 'export-adverse')
        self.assertNotEqual(early['review_status'], 'reviewed')
        self.refused(h.rp(*h.study('review-slot'), '--bundle', bundle, '--capabilities', h.catalog(), '--now', BEFORE),
                     'prior_findings_undisposed')
        # The repair: the coordinator edits the summary (joining the authors), re-renders, records the fix, and a
        # second round runs inside the review repair budget. The first round's bundle is no longer exportable.
        charged = h.charged()
        edited = fg4.synthesis_for(h, record)
        edited['decision']['summary'] = ('Two personas split on the dense first screen; one journey could not start in '
                                         'the preview tool, so asking for dietary needs first was not tested directly.')
        edit = h.rp_ok(*h.study('edit'), '--input', h.write('edit.json', {
            'base_record_sha256': synthesis_record, 'synthesis': edited, 'reason': 'review finding R1'}),
            '--capabilities', h.coordinator_caps())
        self.assertEqual(sorted(a['role'] for a in edit['authors']), ['analyst', 'coordinator'])
        self.refused(h.rp(*h.study('export'), '--bundle', bundle, '--out', h.base / 'export-stale'), 'bundle_mismatch')
        bundle2 = Path(h.rp_ok(*h.study('render'), '--out', h.base / 'bundle-2')['bundle'])
        h.dispose('review-r0', finding, 'fixed', 'The decision summary now names the journey gap (bundle-2).\n')
        bound = h.bind_review(bundle2)
        self.assertEqual((bound['round'], sorted(a['lineage'] for a in bound['authors']), bound['reviewer']['lineage']),
                         (2, ['anthropic', 'openai'], 'google'))
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'review', 'reason': 'finding R1 fixed', 'category': 'review'})
        request = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'review')['request_id']
        # Interrupted during the review: resume lists it in flight and starts nothing else.
        self.assertEqual(h.admit(h.view, request, 'review', purpose='repair')[0], 0)
        brief = h.prepare('review')
        host = h.launch('review', request, fg4.ident(fg4.GEMINI))
        resumed = h.resume()
        self.assertEqual(next(s for s in resumed['later_stages'] if s['slot'] == 'review:review')['state'], 'in-flight')
        self.assertIn(request, resumed['unresolved_owned_work'])
        self.refused(h.admit(h.view, 'review-extra', 'review', purpose='repair'), 'slot_in_flight')
        prior = brief['resources']['focus_group_review']['prior_rounds']
        self.assertEqual([(r['verdict'], [f['disposition'] for f in r['findings']]) for r in prior], [('adverse', ['fixed'])])
        result = h.worker_result(brief, [], conclusion='Invented fidelity review fixture.', review_verdict='approve',
                                 requirements=[{'id': r['id'], 'status': 'passed', 'evidence': 'bundle-2 checked'}
                                               for r in brief['requirements']])
        path = h.transport(result)
        self.assertEqual(h.complete('review', request, host, f'done-{request}')[0], 0)
        self.assertEqual(h.deliver('review', request, f'done-{request}', path)[0], 0)
        h.reconcile()
        code, out = h.accept('review')
        self.assertEqual((code, out.get('accepted')), (0, True), out)
        # The repair spent one review repair from the existing budget and nothing else; the frozen first impressions
        # and every accepted participant record are byte for byte unchanged; the analysis inputs did not move.
        after = h.charged()
        self.assertEqual(after.get('review_repairs', 0), charged.get('review_repairs', 0) + 1)
        self.assertEqual({k: v for k, v in after.items() if k != 'review_repairs'},
                         {k: v for k, v in charged.items() if k != 'review_repairs'})
        self.assertEqual(self.accepted_records(h), first_records)
        # The accepted evidence and delivered files a re-analysis would read are exactly those first analysed; only the
        # review feedback is added (computed here, not applied, so the accepted analysis stays current).
        again = h.rp_ok(*h.study('analysis-inputs'), '--capabilities', h.catalog(), '--now', BEFORE)
        record_again = json.loads((study / 'focus-group' / 'report' / 'inputs' / f'{again["inputs_sha256"]}.json')
                                  .read_text())
        self.assertEqual((record_again['inputs']['evidence'], record_again['files']),
                         (record['inputs']['evidence'], record['files']))
        feedback = record_again['inputs']['feedback']['prior_review_rounds']
        self.assertEqual([[f['finding']['id'] for f in r['findings']] for r in feedback][0], [finding['id']])
        self.assertEqual(h.validate('analysis')[0], 0)
        self.refused(h.rp(*h.study('review-slot'), '--bundle', bundle2, '--capabilities', h.catalog(), '--now', BEFORE),
                     'review_budget_exhausted')

        # REQ-REPORT, REQ-EVIDENCE, REQ-COUNTS, REQ-PRIORITY in the reviewed bundle.
        report = (bundle2 / 'report.md').read_text()
        self.assertIn('not evidence of human demand, prevalence, retention or revenue', report.split('## Decision')[0])
        self.assertIn('one journey could not start in the preview tool', report)
        self.assertIn('coordinator (anthropic lineage', report)
        backlog = json.loads((bundle2 / 'backlog.json').read_text())
        self.assertEqual([i['id'] for i in backlog['items']],
                         ['B-show-add-to-plan', 'B-lighter-first-screen', 'B-button-colour', 'B-sort-by-cost'])
        support = {f['id']: f['support'] for f in json.loads((bundle2 / 'findings.json').read_text())['findings']}
        self.assertEqual((support['F-button-colour']['cells'], support['F-add-to-plan-hidden']['journey']),
                         (3, {'cells': 1, 'of': 4}))
        # REQ-EXPORT: a reviewed export with zero external actions, relocated and verified from its own bytes.
        stub = h.base / 'stub-bin'
        stub.mkdir()
        log = h.base / 'external-calls.log'
        for tool in ('gh', 'git', 't3-plugins', 'imps', 'curl'):
            (stub / tool).write_text(f'#!/bin/sh\necho {tool} "$@" >> {log}\nexit 97\n')
            (stub / tool).chmod(0o755)
        env = {**os.environ, 'PATH': f'{stub}{os.pathsep}{os.environ["PATH"]}', 'PYTHONDONTWRITEBYTECODE': '1'}
        exported = h.rp_ok(*h.study('export'), '--bundle', bundle2, '--out', h.base / 'export', env=env)
        self.assertEqual((exported['review_status'], exported['external_actions']), ('reviewed', []))
        self.assertFalse(log.exists())
        moved = h.base / 'elsewhere' / 'relocated-export'
        moved.parent.mkdir()
        os.rename(h.base / 'export', moved)
        self.assertEqual(h.rp_ok('verify-export', '--bundle', moved)['review_status'], 'reviewed')
        text = '\n'.join(p.read_text() for p in moved.rglob('*') if p.suffix in ('.md', '.json'))
        self.assertNotIn(str(h.base), text)
        self.assertNotIn(fg4.MARKER, text)
        # Completion stays honest: one journey is a gap, so the combined study is reviewed but not complete; after the
        # deadline a wake starts nothing.
        final = h.rp_ok(*h.study('status'))
        self.assertEqual((final['review_status'], final['complete']), ('reviewed', False))
        wake = h.ok('wake', '--state-root', h.root, '--study', h.view['study_id'], now=AFTER)
        self.assertEqual((wake['new_tasks_permitted'], wake['cancel']), (False, []))


# ----------------------------------------------------------------------------- provider gap and unsupported isolation


class GapStudyTest(Loopback):
    def test_provider_gap_and_shared_profile_keep_capture_and_an_honest_scope(self):
        h = WorkflowHost(self.base, self.server, interrupt=False)
        h.start()
        payload = {n: h.fi_payload(n, f'Invented first reaction {n}.', walk=[('welcome-clean.txt', 'Short and clear.')])
                   for n in range(4)}
        for n in (0, 1):
            self.assertEqual(h.first(n, payload=payload[n])['code'], 0)
        # REQ-LIMITS, REQ-PILOT: the fresh catalog shows model B's provider unable to run tasks. Nothing launches or is
        # charged, and the matrix is not silently changed to another model.
        charged = h.charged()
        down = {'providers': [p if p['providerInstanceId'] != 'codex' else provider('codex', ['gpt-fixture-one'], runnable=False)
                              for p in fg4.CAPS['providers']]}
        gap = self.refused(h.admit_slot(3, 'first-impression', 'fi-04-r0',
                                        catalog=h.catalog(caps=down, observed_at=LATER)), 'readiness_stale')
        self.assertEqual(gap['data']['catalog_problems'][0]['problem'], 'provider_unavailable')
        held = h.resume(catalog=h.catalog(caps=down, observed_at=LATER))
        self.assertEqual(held['blockers'][0]['code'], 'readiness_stale')
        self.assertEqual(slot_states(held)[f'{h.cell(3)}:first-impression'], 'held')
        self.assertEqual((h.charged(), held['dispatched']), (charged, 0))
        # An older reading never overrides the newer one recorded; the next fresh observation is used from here on.
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'stale_observation')
        h.observed_at = RECOVERED
        # REQ-SESSION, REQ-LIFECYCLE: model A's second cell fails at the provider mid-task. That is a provider outcome,
        # not product friction; a charged retry takes a new request from the shared repair pool.
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        h.prepare('fi-03')
        host = h.launch('fi-03', 'fi-03-r0', n=2)
        self.assertEqual(h.complete('fi-03', 'fi-03-r0', host, 'c-outage', status='failed')[0], 0)
        row = next(r for r in h.reconcile(now=LATER)['requests'] if r['request_id'] == 'fi-03-r0')
        self.assertEqual(row['state'], 'provider-failure')
        error = h.transport(b'Provider error: upstream unavailable')
        self.assertEqual(h.deliver('fi-03', 'fi-03-r0', 'c-outage', error)[0], 0)
        code, out = h.ingest('fi-03', 'fi-03-r0', 'c-outage', error)
        self.assertEqual((code, out['error']['code'], out['data']['product_friction']), (1, 'malformed_result', False))
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'fi-03', 'reason': 'provider outage'})
        retry = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'fi-03')['request_id']
        code, out = h.admit_slot(2, 'first-impression', retry, purpose='repair')
        self.assertEqual((code, out['data']['pool']), (0, 'participant_repairs'), out)
        self.assertEqual(h.first(2, request=retry, payload=payload[2], admit=False)['code'], 0)
        # The provider is back in the next fresh catalog: model B's held cell runs.
        self.assertEqual(h.first(3, payload=payload[3])['code'], 0)
        self.assertEqual(h.charged(), {'first': 4, 'participant_repairs': 1})
        # REQ-ISOLATION, REQ-JOURNEY: model A's child contexts are tabs of one browser profile. The loopback probe shows
        # shared cookies and local storage, so binding is refused and model A's journeys are visible gaps with their
        # capture results kept. Model B's contexts are separate and its journeys run.
        a_cells = [h.cell(0), h.cell(2)]
        profile = fg2.FakeContext(self.server)
        probe, readings = h.probe(h.view, a_cells, {a_cells[0]: profile,
                                                    a_cells[1]: fg2.FakeContext(self.server, shared=profile)})
        for n, cid in enumerate(a_cells):
            code, out = h.bind(h.view, cid, probe, readings, f'shared-profile-tab-{n}')
            self.assertEqual((code, out['error']['code'], out['data']['relay'], out['data']['capture_results']),
                             (1, 'journey_unavailable', 'prohibited', 'retained'))
            self.assertIn('isolation_failed', {p['code'] for p in out['data']['problems']})
        h.isolated_cells = {h.cell(1), h.cell(3)}
        self.assertEqual(h.journey(1)[0], 0)  # model B's pilot journey
        self.assertEqual(h.journey(3)[0], 0)
        self.refused(h.admit_slot(0, 'journey', 'jr-01-r0'), 'journey_brief_missing')
        pilots = {(p['pilot_cell'], p['stage']): p['state'] for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual((pilots[(h.cell(0), 'journey')], pilots[(h.cell(1), 'journey')]), ('unavailable', 'passed'))
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        rows = {r['cell_id']: r for r in coverage['cells']}
        self.assertEqual([rows[h.cell(n)]['journey']['state'] for n in range(4)],
                         ['gap', 'hands-on-evidence', 'gap', 'hands-on-evidence'])
        self.assertEqual({rows[h.cell(n)]['capture'] for n in range(4)}, {'cleared'})
        resumed = h.resume()
        self.assertEqual((resumed['capture_scope_filled'], resumed['complete']), (True, False))
        # REQ-CONTRACT, REQ-RESUME: an explicit capture-only revision of the same study carries every unchanged first
        # impression forward through the validated mapping; journey evidence is staled, nothing re-runs or is
        # refunded, and capture-only completion never completes the combined scope.
        before = h.charged()
        records = self.accepted_records(h)
        draft = h.draft(mode='capture-only', journeys=[])
        draft['personas'] = draft['personas'][:2]
        draft['personas'][1]['priorities'] = ['cost per serving', 'meals that reuse leftovers']
        draft['limits']['max_concurrency'] = 3
        draft.pop('journey_context', None)
        draft['prompts'].pop('journey', None)
        capture = h.plan(draft)
        statuses = {(e['stage'], e['status']) for e in capture['carry_forward']['entries']}
        self.assertIn(('first-impression', 'carried'), statuses)
        self.assertNotIn(('journey', 'carried'), statuses)
        h.approve(capture)
        h.ok('carry', '--state-root', h.root, '--study', capture['study_id'], '--write')
        h.view = capture
        resumed = h.resume()
        self.assertEqual((resumed['capture_scope_filled'], resumed['combined_scope_complete'], resumed['complete']),
                         (True, False, False))
        self.assertEqual({s['state'] for s in resumed['slots']}, {'accepted'})
        self.assertEqual((h.charged(), self.accepted_records(h)), (before, records))


# ----------------------------------------------------------------------------- the declared integration stage


class IntegrationStageTest(unittest.TestCase):
    def test_the_integration_stage_covers_every_requirement_with_real_tests(self):
        declared = INTEGRATION_STAGE['requirements']
        self.assertEqual(list(declared), list(REQUIREMENTS))
        self.assertEqual(len(REQUIREMENTS), 25)
        for requirement, references in declared.items():
            with self.subTest(requirement=requirement):
                self.assertTrue(references)
                for reference in references:
                    parts = reference.split('.')
                    split = next(i for i, p in enumerate(parts) if p[:1].isupper())
                    target = importlib.import_module('.'.join(parts[:split]))
                    for part in parts[split:]:
                        target = getattr(target, part)
                    if isinstance(target, type):
                        tests = [name for name in dir(target) if name.startswith('test_')]
                        self.assertTrue(tests, reference)
                        self.assertTrue(issubclass(target, unittest.TestCase), reference)
                    else:
                        self.assertTrue(callable(target), reference)
        # The two integrated workflows here appear under every criterion they exercise together.
        for name in (COMBINED, GAPS):
            self.assertGreaterEqual(sum(name in refs for refs in declared.values()), 8, name)
        for module in ('plan', 'evidence', 'lifecycle', 'report', 'install', 'workflow'):
            self.assertTrue((ROOT / 'tests' / f'test_focus_group_{module}.py').is_file(), module)

    def test_the_guide_covers_the_operator_decisions(self):
        guide = ' '.join((ROOT / 'docs' / 'plugins' / 'focus-group.md').read_text().split())
        for phrase in ('Pantry Planner', 'invented', 'Edit the panel', 'capture-only', 'task ceiling',
                       'unknown until pilot', 'resume', 'synthetic', 'imps', 'existing approval', 'sharing'):
            self.assertIn(phrase, guide)
        nav = (ROOT / 'mkdocs.yml').read_text()
        self.assertIn('focus-group: plugins/focus-group.md', nav)
        entry = json.loads((ROOT / 'docs' / 'field-guide.json').read_text())['focus-group']
        self.assertTrue(entry['try'].startswith('$t3-focus-group '))
        self.assertTrue((ROOT / 'docs' / 'assets' / 'specimens' / 'focus-group.svg').is_file())


if __name__ == '__main__':
    unittest.main()
