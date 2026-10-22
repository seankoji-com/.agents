"""Focus-group fidelity scenarios split to retain the 600-second module deadline."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_focus_group_report import (  # noqa: E402
    BEFORE, CAPS, CLAUDE, ReportCase, fg3, ident, json, load_report_module,
    setUpModule, subprocess, synthesis_for, tearDownModule,
)


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
        # A known validation exception keeps its stable code, never arbitrary exception text.
        from unittest import mock
        report = load_report_module()
        marker = 'INVENTED-VALIDATOR-DETAIL'
        with mock.patch.object(report, 'review_stage', side_effect=report.StudyError('fixture_rejection', marker)):
            checked = report.validate_observation(frozen)
        self.assertFalse(checked['accepted'])
        self.assertNotIn(marker, json.dumps(checked))
        self.assertIn({'code': 'fixture_rejection'},
                      checked['requirement_outcomes']['STUDY-REVIEW']['evidence']['problems'])


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



if __name__ == '__main__':
    unittest.main()
