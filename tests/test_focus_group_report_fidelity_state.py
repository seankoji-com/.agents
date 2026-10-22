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



if __name__ == '__main__':
    unittest.main()
