"""Owner-accepted identity evidence through analysis, review and portable report export.

Kept in its own module so these full-workflow cases and the other reporting cases each
retain the test runner's unchanged per-module timeout. Every host observation is invented.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_focus_group_lifecycle import setUpModule, tearDownModule  # noqa: E402
from tests.test_focus_group_report import (BEFORE, CLAUDE, GPT, PASS_SPENT, STICKY, ReportHost,  # noqa: E402
                                            delivered_inputs, ident, load_report_module, sha, sources)


class IdentityProjectionTest(unittest.TestCase):
    """An owner-accepted identity discrepancy reaches the analysis inputs, the report coverage and the portable sources
    as the evidence the owner accepted: a complete contradiction keeps observed null with every reported association,
    a consistent wrong model keeps its one observed model, and the requested target stays apart. The evidence hash
    follows that material identity evidence, so a new reading stales frozen inputs; an equivalent one does not."""

    def decide(self, h, record_sha, statement, source=None):
        """The owner's exact answer, through accept-identity. Its `decision_input` (the same owner source and quote,
        bound to the one mismatched job execution) is kept in `self.job_decision` for job_cli.py decision."""
        h.counter += 1
        if source is None:
            source = h.base / 'owner' / f'identity-{h.counter}.txt'
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(f'Selected option: {statement}\n')
        code, out = h.lc(*h.study('accept-identity'), '--input', h.write(f'id-{h.counter}.json', {
            'record_sha256': record_sha, 'message_ref': 'picker-identity', 'statement': statement,
            'source': str(source), 'source_sha256': sha(source.read_bytes())}))
        self.assertEqual(code, 0, out)
        self.job_decision, self.decision_recorded = out['data'].get('decision_input'), out['data'].get('decision_recorded')
        return out['data']['decision']

    def record_exception(self, h):
        """Record the owner's identity exception in the shared job: no new prompt, the answer already given."""
        decision = self.job_decision['decision']
        self.assertEqual((decision['scope'].split(':')[:2], self.decision_recorded), (['identity-exception', 'task'], False))
        return h.job_ok('decision', self.job_decision)

    @staticmethod
    def stage_error(outcome):
        return (outcome[0], outcome[1].get('accepted'), outcome[1].get('error'))

    def assert_mismatch_kept(self, h, task_id, request_id):
        """The shared handle stays mismatched and its sticky blocker stays: an exception relabels nothing."""
        job = h.job_state()
        task = next(t for t in job['tasks'] if t['task_id'] == task_id)
        self.assertEqual([x['observed_identity']['status'] for x in task['handles'] if x['request_id'] == request_id],
                         ['mismatched'])
        self.assertEqual([(b['task_id'], b['request_id']) for b in job['blockers'] if b['kind'] == 'identity-mismatch'],
                         [(task_id, request_id)])

    def synthesis_of(self, h, c, record):
        s = sources(record)

        def obs(ref, n):
            src = s[(c[n], 'first-impression')]
            return {'ref': ref, 'source_id': src['source_id'], 'pointer': '/initial_viewport/reaction',
                    'quote': src['payload']['initial_viewport']['reaction'], 'cell_id': c[n],
                    'stage': 'first-impression', 'revision': src['revision'],
                    'capture': [{'pack': 'initial-viewport.png'}]}
        return {'schema': 'focus-group/synthesis', 'schema_version': 1, 'study_revision': h.view['revision'],
                'inputs_sha256': record['inputs_sha256'],
                'decision': {'answer': 'inconclusive', 'summary': 'Two synthetic cells only.', 'finding_ids': [],
                             'uncertainty': 'One persona.'},
                'observations': [obs('clear', 0), obs('busy', 1)],
                'findings': [{'id': 'F-start', 'category': 'first-impression', 'title': 'Starting is clear enough',
                              'statement': 'The first screen read as clear or busy but usable.',
                              'observation_refs': ['clear', 'busy'], 'verification': 'observed'}], 'backlog': []}

    def study(self, first_identity='default'):
        """Two combined cells of one persona: cell 0 on the Claude fixture, cell 1 on the GPT fixture."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve() / 'study'
        base.mkdir()
        h = ReportHost(base)
        h.start(personas=1)
        runs = [h.first(0, identity=first_identity, payload=h.fi_payload(0, 'Clear enough to start.',
                                                                         walk=[('welcome-clean.txt', 'Short.')])),
                h.first(1, payload=h.fi_payload(1, 'Busy but usable.', walk=[('welcome-clean.txt', 'Fine.')]))]
        self.assertEqual([r['code'] for r in runs], [0, 0], [r['out'] for r in runs])
        return h, [h.cell(0), h.cell(1)], [r['out']['data']['record_sha256'] for r in runs]

    @staticmethod
    def evidence_row(h, cell):
        return {r['cell_id']: r for r in h.progress()['cells']}[cell]['first-impression']['identity_evidence']

    def test_a_consistent_wrong_model_reaches_the_analyst_with_its_one_observed_model(self):
        wrong = {'providerInstanceId': 'claudeAgent', 'model': 'claude-fixture-deep'}
        h, c, rec = self.study(first_identity=wrong)
        found = self.evidence_row(h, c[0])
        decision = self.decide(h, rec[0], found['instruction'])
        _, record = h.bind_analysis()
        for view in (record['inputs']['evidence'], delivered_inputs(record)['evidence']):
            row = {(s['cell_id'], s['stage']): s for s in view['sources']}
            moved, other = row[(c[0], 'first-impression')], row[(c[1], 'first-impression')]
            self.assertEqual((moved['identity'], moved['observed'], moved['lineage']),
                             ('owner-accepted-discrepancy', wrong, 'anthropic'))
            self.assertEqual(moved.get('identity_evidence'), {
                'kind': 'wrong-model', 'requested': ident(CLAUDE), 'observed': wrong, 'shared_status': 'mismatched',
                'associations': [wrong], 'resolutions': [wrong], 'canonical': wrong,
                'discrepancy_sha256': found['discrepancy_sha256'], 'decision_sha256': decision['decision_sha256'],
                'statement': found['instruction']})
            # A verified source carries no discrepancy evidence; its bytes are as before.
            self.assertEqual((other['identity'], other['observed'], 'identity_evidence' in other),
                             ('verified', ident(GPT), False))
            self.assertEqual(ident(next(x for x in view['cells'] if x['cell_id'] == c[0])['requested']), ident(CLAUDE))

        # Through the shared job: the stage holds the mismatched execution until the owner's exact answer is recorded
        # there, then accepts it as unverified evidence; a real analyst run and render follow.
        for n in (0, 1):
            self.assertEqual(h.journey(n)[0], 0)
        self.assertEqual(self.stage_error(h.accept('first-impression')), (2, False, STICKY))
        self.record_exception(h)
        for stage in ('first-impression', 'journey'):
            self.assertEqual(self.stage_error(h.accept(stage)), (0, True, None))
        self.assert_mismatch_kept(h, 'fi-01', 'fi-01-r0')
        _, record = h.bind_analysis()
        code, out = h.run_analysis(self.synthesis_of(h, c, record))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.stage_error(h.accept('analysis')), (0, True, None))
        code, out = h.render()
        self.assertEqual(code, 0, out)
        self.assertIn(f'- Owner-accepted identity discrepancy for `{c[0]}` first-impression (requested '
                      'claudeAgent/claude-fixture-swift): host reported claudeAgent/claude-fixture-deep; observed: '
                      'claudeAgent/claude-fixture-deep. Not verified; excluded from verified coverage.',
                      (Path(out['data']['bundle']) / 'report.md').read_text())

    def test_an_accepted_contradiction_reaches_every_consumer_whole_and_new_readings_stale_its_inputs(self):
        h, c, rec = self.study()
        rec0 = rec[0]
        for n in (0, 1):
            self.assertEqual(h.journey(n)[0], 0)
        for stage in ('first-impression', 'journey'):
            code, out = h.accept(stage)
            self.assertEqual((code, out.get('accepted')), (0, True), out)
        study_dir = h.root / h.view['study_id']
        records = {p.name: p.read_bytes() for p in (study_dir / 'focus-group' / 'accepted').glob('*.json')}

        def participant_requests():
            return {r: row for r, row in json.loads(h.ledger_bytes())['requests'].items()
                    if not str(row.get('slot', '')).startswith(('analysis:', 'review:'))}
        charged = participant_requests()

        def synthesis_of(record):
            s = sources(record)

            def obs(ref, n):
                src = s[(c[n], 'first-impression')]
                return {'ref': ref, 'source_id': src['source_id'], 'pointer': '/initial_viewport/reaction',
                        'quote': src['payload']['initial_viewport']['reaction'], 'cell_id': c[n],
                        'stage': 'first-impression', 'revision': src['revision'],
                        'capture': [{'pack': 'initial-viewport.png'}]}
            return {'schema': 'focus-group/synthesis', 'schema_version': 1, 'study_revision': h.view['revision'],
                    'inputs_sha256': record['inputs_sha256'],
                    'decision': {'answer': 'inconclusive', 'summary': 'Two synthetic cells only.', 'finding_ids': [],
                                 'uncertainty': 'One persona.'},
                    'observations': [obs('clear', 0), obs('busy', 1)],
                    'findings': [{'id': 'F-start', 'category': 'first-impression', 'title': 'Starting is clear enough',
                                  'statement': 'The first screen read as clear or busy but usable.',
                                  'observation_refs': ['clear', 'busy'], 'verification': 'observed'}], 'backlog': []}
        # While every identity is verified: analysed, rendered and bound for review.
        _, before = h.bind_analysis()
        self.assertFalse(any('identity_evidence' in s for s in before['inputs']['evidence']['sources']))
        code, out = h.run_analysis(synthesis_of(before))
        self.assertEqual(code, 0, out)
        self.assertEqual(h.accept('analysis')[0], 0)
        code, out = h.render()
        self.assertEqual(code, 0, out)
        bundle = Path(out['data']['bundle'])
        h.bind_review(bundle)
        self.assertEqual(h.rp(*h.study('verify-bundle'), '--bundle', bundle)[0], 0)

        def host_of(task_id):
            handle = next(t for t in h.job_state()['tasks'] if t['task_id'] == task_id)['handles'][-1]
            return handle.get('task_id', handle.get('host_task_id'))

        # The original R8 case: the status keeps the requested model and a later receipt names another.
        def reading(task_id='fi-01', **source):
            code, out = h.observe(task_id, kind='reconciled', request_id=f'{task_id}-r0', host_task_id=host_of(task_id),
                                  status='completed', work_state='result_available', has_pending_child_runs=False,
                                  **source)
            self.assertEqual(code, 0, out)

        def evidence_row(n):
            return self.evidence_row(h, c[n])
        deep = {'providerInstanceId': 'claudeAgent', 'model': 'claude-fixture-deep'}
        reading(receipt_identity=deep)
        self.assertEqual(h.rp(*h.study('analysis-inputs'), '--capabilities', h.catalog(), '--now', BEFORE)[0], 1)
        found = evidence_row(0)
        self.assertEqual(found['kind'], 'contradictory')
        decision = self.decide(h, rec0, found['instruction'])
        self.assertIsNone(decision['observed'])
        _, accepted = h.bind_analysis()
        swift = ident(CLAUDE)
        with self.subTest('analyst inputs'):
            self.assertIn('claude-fixture-deep', Path(accepted['document']['path']).read_text())
            for view in (accepted['inputs']['evidence'], delivered_inputs(accepted)['evidence']):
                row = {(s['cell_id'], s['stage']): s for s in view['sources']}[(c[0], 'first-impression')]
                self.assertEqual((row['identity'], row['observed'], row['lineage']),
                                 ('owner-accepted-discrepancy', None, 'unknown'))
                shown = row['identity_evidence']
                self.assertEqual((shown['kind'], shown['observed'], shown['requested'], shown['associations'],
                                  shown['discrepancy_sha256'], shown['decision_sha256'], shown['statement']),
                                 ('contradictory', None, swift, [deep, swift], found['discrepancy_sha256'],
                                  decision['decision_sha256'], found['instruction']))
                cell = next(x for x in view['cells'] if x['cell_id'] == c[0])
                self.assertEqual(ident(cell['requested']), swift)

        # Equivalent repeats, here and on another request, keep the frozen inputs exactly; nothing is asked again.
        reading(receipt_identity=deep)
        reading('fi-02', status_identity=ident(GPT))
        out, same = h.bind_analysis()
        self.assertEqual((out['changed'], same['inputs_sha256'], self.evidence_row(h, c[0])['discrepancy_sha256']),
                         (False, accepted['inputs_sha256'], found['discrepancy_sha256']))

        # A configuration source naming a third model withdraws the decision and holds the frozen inputs.
        reading(configuration_identity={'providerInstanceId': 'claudeAgent', 'model': 'claude-fixture-max'})
        self.assertEqual(h.rp(*h.study('analysis-inputs'), '--capabilities', h.catalog(), '--now', BEFORE)[0], 1)
        self.assertEqual(h.render('held')[0], 1)
        fresh = evidence_row(0)
        self.assertNotEqual(fresh['discrepancy_sha256'], found['discrepancy_sha256'])
        later = self.decide(h, rec0, fresh['instruction'])
        _, record = h.bind_analysis()
        with self.subTest('fresh decision refreezes changed inputs'):
            self.assertNotEqual(record['evidence_sha256'], accepted['evidence_sha256'])
            self.assertNotEqual(record['document']['sha256'], accepted['document']['sha256'])
            self.assertIn('claude-fixture-max', Path(record['document']['path']).read_text())
            shown = sources(record)[(c[0], 'first-impression')]['identity_evidence']
            self.assertEqual((shown['observed'], shown['decision_sha256'], [p['model'] for p in shown['associations']]),
                             (None, later['decision_sha256'], ['claude-fixture-deep', 'claude-fixture-max',
                                                               'claude-fixture-swift']))
        # The earlier frozen document and the accepted records stay byte for byte; no participant work is charged.
        self.assertEqual(sha(Path(accepted['document']['path']).read_bytes()), accepted['document']['sha256'])
        self.assertEqual({p.name: p.read_bytes() for p in (study_dir / 'focus-group' / 'accepted').glob('*.json')},
                         records)
        self.assertEqual(participant_requests(), charged)

        # The synthesis, report and review bound to the verified evidence stay stale until analysed again.
        self.refused_code(h.render('stale'), 'inputs_changed')
        self.assertNotEqual(h.rp(*h.study('verify-bundle'), '--bundle', bundle)[0], 0)
        # The supported route first: the validated analysis pass needs a charged repair before a new execution.
        prepare = {'caller': h.caller, 'task_id': 'analysis'}
        self.assertEqual(h.job('prepare', prepare), (2, 'job_error: stale reexecution or a new execution in a '
                                                        'validated pass requires a charged repair pass\n'))
        primary = next(s for s in h.job_state()['stages'] if s['id'] == 'analysis')['attempts']['primary']
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'analysis', 'reason': 'analysis inputs changed'})
        self.assertEqual(next(s for s in h.job_state()['stages'] if s['id'] == 'analysis')['attempts']['primary'],
                         primary + 1)
        # These readings arrived after first-impression was accepted, so that acceptance is no longer current. Even
        # with the owner's exception recorded, a validated participant pass is accepted again only after a charged
        # participant re-execution (the shared pass rule); nothing here relabels or re-runs anything.
        self.assertEqual(h.job('prepare', prepare), (2, 'job_error: predecessor acceptance is not current\n'))
        self.record_exception(h)
        self.assertEqual(self.stage_error(h.accept('first-impression')), (2, False, PASS_SPENT))
        self.assertEqual(h.job('prepare', prepare), (2, 'job_error: predecessor acceptance is not current\n'))
        self.assert_mismatch_kept(h, 'fi-01', 'fi-01-r0')
        self.assertEqual(participant_requests(), charged)

        # The report and portable source the frozen inputs would render: rendered from the exact recorded view.
        report = load_report_module()
        view = record['inputs']['evidence']
        study = report.Study(str(h.root), h.view['study_id'])
        coverage = '\n'.join(report.coverage_lines(view))
        self.assertIn(f'- Owner-accepted identity discrepancy for `{c[0]}` first-impression (requested '
                      'claudeAgent/claude-fixture-swift): host reported claudeAgent/claude-fixture-deep, '
                      'claudeAgent/claude-fixture-max, claudeAgent/claude-fixture-swift; observed: none, the readings '
                      'contradict each other. Not verified; excluded from verified coverage.', coverage)
        self.assertNotIn(f'discrepancy for `{c[1]}`', coverage)
        s = sources(record)
        for n, observed in ((0, None), (1, ident(GPT))):
            src = s[(c[n], 'first-impression')]
            files, row = report.source_projection(study, view, src)
            projected = json.loads(files[report.source_file(src['source_id'])])
            self.assertEqual((projected['identity'], projected['observed'], projected.get('identity_evidence')),
                             (src['identity'], observed, src.get('identity_evidence')))
            self.assertEqual((row['result_sha256'], report.absolute_paths('source', projected)), (src['result_sha256'], []))

    def test_an_accepted_contradiction_is_analysed_reviewed_and_exported_through_the_job(self):
        """FG3-R8-P1: the owner's exact answer, recorded once in the shared job, lets the participant stage accept the
        mismatched execution as unverified evidence, so a real analyst, render, fidelity review and export follow.
        Without it, or after any new association, the stage holds; the handle and its blocker never change."""
        h, c, rec = self.study()
        for n in (0, 1):
            self.assertEqual(h.journey(n)[0], 0)
        study_dir = h.root / h.view['study_id']
        records = {p.name: p.read_bytes() for p in (study_dir / 'focus-group' / 'accepted').glob('*.json')}

        def participant_requests():
            return {r: row for r, row in json.loads(h.ledger_bytes())['requests'].items()
                    if not str(row.get('slot', '')).startswith(('analysis:', 'review:'))}
        charged = participant_requests()
        host = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'fi-01')['handles'][-1]['task_id']

        def reading(task_id='fi-01', host_task_id=host, **source):
            code, out = h.observe(task_id, kind='reconciled', request_id=f'{task_id}-r0', host_task_id=host_task_id,
                                  status='completed', work_state='result_available', has_pending_child_runs=False,
                                  **source)
            self.assertEqual(code, 0, out)
        deep = {'providerInstanceId': 'claudeAgent', 'model': 'claude-fixture-deep'}
        maximum = {'providerInstanceId': 'claudeAgent', 'model': 'claude-fixture-max'}
        reading(receipt_identity=deep)
        # No owner answer yet: the discrepancy is visible and the stage holds.
        self.assertEqual(self.stage_error(h.accept('first-impression')), (2, False, STICKY))
        found = self.evidence_row(h, c[0])
        first = self.decide(h, rec[0], found['instruction'])
        stale_exception = self.job_decision
        self.record_exception(h)
        _, frozen = h.bind_analysis()

        # A configuration source naming a third model withdraws both the study decision and the job exception.
        reading(configuration_identity=maximum)
        self.assertEqual(h.rp(*h.study('analysis-inputs'), '--capabilities', h.catalog(), '--now', BEFORE)[0], 1)
        self.assertEqual(self.stage_error(h.accept('first-impression')), (2, False, STICKY))
        # Equivalent repeats and another request's readings change nothing, and ask nothing.
        fresh = self.evidence_row(h, c[0])
        reading(configuration_identity=maximum)
        reading('fi-02', host_task_id=next(t for t in h.job_state()['tasks'] if t['task_id'] == 'fi-02')['handles'][-1]['task_id'],
                status_identity=ident(GPT))
        self.assertEqual(self.evidence_row(h, c[0])['discrepancy_sha256'], fresh['discrepancy_sha256'])
        self.assertNotEqual(fresh['discrepancy_sha256'], found['discrepancy_sha256'])
        # An exception whose owner source no longer holds its quote covers nothing, even with the exact binding.
        later_source = h.base / 'owner' / 'identity-later.txt'
        later_source.write_text(f'Selected option: {fresh["instruction"]}\n')
        later = self.decide(h, rec[0], fresh['instruction'], source=later_source)
        self.assertNotEqual(self.job_decision['decision']['binding'], stale_exception['decision']['binding'])
        self.record_exception(h)
        self.decide(h, rec[0], fresh['instruction'], source=later_source)
        self.assertTrue(self.decision_recorded, 'an equivalent answer is already recorded; no new approval')
        later_source.write_text('Selected option: something else\n')
        self.assertEqual(self.stage_error(h.accept('first-impression')), (2, False, STICKY))
        later_source.write_text(f'Selected option: {fresh["instruction"]}\n')
        for stage in ('first-impression', 'journey'):
            self.assertEqual(self.stage_error(h.accept(stage)), (0, True, None))
        self.assert_mismatch_kept(h, 'fi-01', 'fi-01-r0')

        # The analyst receives the accepted contradiction whole, freshly frozen against the later decision.
        _, record = h.bind_analysis()
        self.assertNotEqual((record['evidence_sha256'], record['document']['sha256']),
                            (frozen['evidence_sha256'], frozen['document']['sha256']))
        self.assertEqual(sha(Path(frozen['document']['path']).read_bytes()), frozen['document']['sha256'])
        shown = sources(record)[(c[0], 'first-impression')]['identity_evidence']
        self.assertEqual((shown['observed'], shown['decision_sha256'], shown['requested'],
                          [p['model'] for p in shown['associations']]),
                         (None, later['decision_sha256'], ident(CLAUDE),
                          ['claude-fixture-deep', 'claude-fixture-max', 'claude-fixture-swift']))
        self.assertNotEqual(first['decision_sha256'], later['decision_sha256'])
        code, out = h.run_analysis(self.synthesis_of(h, c, record))
        self.assertEqual(code, 0, out)
        brief = json.loads(Path(next(t for t in h.job_state()['tasks'] if t['task_id'] == 'analysis')['brief']['path'])
                           .read_text())
        self.assertEqual(brief['document'], record['document'])
        self.assertEqual(self.stage_error(h.accept('analysis')), (0, True, None))
        code, out = h.render()
        self.assertEqual(code, 0, out)
        bundle = Path(out['data']['bundle'])
        line = (f'- Owner-accepted identity discrepancy for `{c[0]}` first-impression (requested '
                'claudeAgent/claude-fixture-swift): host reported claudeAgent/claude-fixture-deep, '
                'claudeAgent/claude-fixture-max, claudeAgent/claude-fixture-swift; observed: none, the readings '
                'contradict each other. Not verified; excluded from verified coverage.')
        self.assertIn(line, (bundle / 'report.md').read_text())
        h.bind_review(bundle)
        _, delivered = h.run_review()
        self.assertEqual(delivered[0], 0, delivered)
        self.assertEqual(self.stage_error(h.accept('review')), (0, True, None))
        self.assertEqual(h.rp(*h.study('verify-bundle'), '--bundle', bundle)[0], 0)
        export = h.base / 'export'
        self.assertEqual(h.rp_ok(*h.study('export'), '--bundle', bundle, '--out', export)['review_status'], 'reviewed')
        self.assertEqual(h.rp_ok('verify-export', '--bundle', export)['review_status'], 'reviewed')
        self.assertIn(line, (export / 'report.md').read_text())
        projected = json.loads((export / 'sources' / f'{sources(record)[(c[0], "first-impression")]["source_id"]}.json')
                               .read_text())
        self.assertEqual((projected['identity'], projected['observed'], projected['identity_evidence']),
                         ('owner-accepted-discrepancy', None, shown))
        self.assertEqual({p.name: p.read_bytes() for p in (study_dir / 'focus-group' / 'accepted').glob('*.json')},
                         records)
        self.assertEqual(participant_requests(), charged)

        # A reading after acceptance holds every consumer again; the job keeps the accepted pass as history and a
        # new pass needs a charged participant re-execution, never a relabel.
        reading(status_identity=deep)
        self.assertEqual(h.rp(*h.study('analysis-inputs'), '--capabilities', h.catalog(), '--now', BEFORE)[0], 1)
        self.assertEqual(h.render('held')[0], 1)
        self.assertNotEqual(h.rp(*h.study('verify-bundle'), '--bundle', bundle)[0], 0)
        self.assertFalse(h.validate('first-impression')[1].get('accepted'))

    def reemit(self, h, rec0, found, source, original):
        """An equivalent reading from a new source: the study decision and its evidence hash stay, the job exception
        goes stale, and the exact original answer re-emits one for the current binding without rewriting anything."""
        decision_file = h.root / h.view['study_id'] / 'focus-group' / 'identity' / \
            f"{rec0}.{found['discrepancy_sha256'][:16]}.json"
        kept = decision_file.read_bytes()
        stale = self.job_decision
        self.assertEqual(self.evidence_row(h, h.cell(0))['discrepancy_sha256'], found['discrepancy_sha256'])
        self.assertEqual(self.evidence_row(h, h.cell(0))['instruction'], found['instruction'])
        self.assertEqual(self.stage_error(h.accept('first-impression')), (2, False, STICKY))
        # Another owner source or message for the same evidence is not the recorded authority.
        other = h.base / 'owner' / 'identity-other.txt'
        other.write_text(f'Selected option: {found["instruction"]}\n')
        for source_path, message in ((other, 'picker-identity'), (source, 'another-message')):
            code, out = h.lc(*h.study('accept-identity'), '--input', h.write(f'id-other-{message}.json', {
                'record_sha256': rec0, 'message_ref': message, 'statement': found['instruction'],
                'source': str(source_path), 'source_sha256': sha(source_path.read_bytes())}))
            self.assertEqual((code, out['error']['code']), (2, 'immutable_record'), out)
        again = self.decide(h, rec0, found['instruction'], source=source)
        self.assertEqual((again, decision_file.read_bytes()), (original, kept))
        fresh = self.job_decision['decision']
        self.assertNotEqual((fresh['id'], fresh['binding']), (stale['decision']['id'], stale['decision']['binding']))
        self.assertEqual({k: fresh[k] for k in ('quote', 'source', 'source_sha256', 'scope')},
                         {k: stale['decision'][k] for k in ('quote', 'source', 'source_sha256', 'scope')})
        self.assertEqual({k: v for k, v in fresh['binding'].items() if k != 'observed_identity_sha256'},
                         {k: v for k, v in stale['decision']['binding'].items() if k != 'observed_identity_sha256'})
        # The stale exception's own ID is already recorded and still covers only its old binding.
        self.assertEqual(h.job('decision', stale), (2, 'job_error: owner decision ID already recorded\n'))
        self.assertEqual(self.stage_error(h.accept('first-impression')), (2, False, STICKY))
        self.record_exception(h)
        self.decide(h, rec0, found['instruction'], source=source)
        self.assertEqual((self.decision_recorded, self.job_decision['decision']), (True, fresh))
        ids = [d['id'] for d in h.job_state()['decisions'] if d['scope'] == fresh['scope']]
        self.assertEqual(ids, [stale['decision']['id'], fresh['id']])
        self.assertEqual(decision_file.read_bytes(), kept)

    def test_an_equivalent_reading_from_a_new_source_reuses_the_owner_answer_through_export(self):
        """FG3-R8-P1: before any participant pass, a configuration reading repeats the accepted receipt association.
        The owner's exact original answer re-emits the job exception for the changed binding, and the study goes
        on through analysis, review and export with the contradiction still unverified and observed null."""
        h, c, rec = self.study()
        for n in (0, 1):
            self.assertEqual(h.journey(n)[0], 0)
        study_dir = h.root / h.view['study_id']
        records = {p.name: p.read_bytes() for p in (study_dir / 'focus-group' / 'accepted').glob('*.json')}

        def participant_requests():
            return {r: row for r, row in json.loads(h.ledger_bytes())['requests'].items()
                    if not str(row.get('slot', '')).startswith(('analysis:', 'review:'))}
        charged = participant_requests()
        host = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'fi-01')['handles'][-1]['task_id']

        def reading(**source):
            code, out = h.observe('fi-01', kind='reconciled', request_id='fi-01-r0', host_task_id=host,
                                  status='completed', work_state='result_available', has_pending_child_runs=False,
                                  **source)
            self.assertEqual(code, 0, out)
        deep = {'providerInstanceId': 'claudeAgent', 'model': 'claude-fixture-deep'}
        reading(receipt_identity=deep)
        found = self.evidence_row(h, c[0])
        self.assertEqual(found['kind'], 'contradictory')
        source = h.base / 'owner' / 'identity-original.txt'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f'Selected option: {found["instruction"]}\n')
        first = self.decide(h, rec[0], found['instruction'], source=source)
        self.record_exception(h)
        _, frozen = h.bind_analysis()
        # A same-source repeat changes nothing and asks nothing.
        reading(receipt_identity=deep)
        self.decide(h, rec[0], found['instruction'], source=source)
        self.assertTrue(self.decision_recorded)

        reading(configuration_identity=deep)
        out, same = h.bind_analysis()
        self.assertEqual((out['changed'], same['inputs_sha256']), (False, frozen['inputs_sha256']))
        self.assertEqual(h.job('prepare', {'caller': h.caller, 'task_id': 'analysis'}),
                         (2, 'job_error: predecessor acceptance is not current\n'))
        self.reemit(h, rec[0], found, source, first)

        for stage in ('first-impression', 'journey'):
            self.assertEqual(self.stage_error(h.accept(stage)), (0, True, None))
        self.assert_mismatch_kept(h, 'fi-01', 'fi-01-r0')
        _, record = h.bind_analysis()
        self.assertEqual(record['inputs_sha256'], frozen['inputs_sha256'])
        code, out = h.run_analysis(self.synthesis_of(h, c, record))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.stage_error(h.accept('analysis')), (0, True, None))
        code, out = h.render()
        self.assertEqual(code, 0, out)
        bundle = Path(out['data']['bundle'])
        h.bind_review(bundle)
        _, delivered = h.run_review()
        self.assertEqual(delivered[0], 0, delivered)
        self.assertEqual(self.stage_error(h.accept('review')), (0, True, None))
        export = h.base / 'export'
        self.assertEqual(h.rp_ok(*h.study('export'), '--bundle', bundle, '--out', export)['review_status'], 'reviewed')
        self.assertEqual(h.rp_ok('verify-export', '--bundle', export)['review_status'], 'reviewed')
        shown = sources(record)[(c[0], 'first-impression')]['identity_evidence']
        self.assertEqual((shown['observed'], shown['decision_sha256'], shown['requested'], shown['associations']),
                         (None, first['decision_sha256'], ident(CLAUDE), [deep, ident(CLAUDE)]))
        projected = json.loads((export / 'sources' / f'{sources(record)[(c[0], "first-impression")]["source_id"]}.json')
                               .read_text())
        self.assertEqual((projected['identity'], projected['observed'], projected['identity_evidence']),
                         ('owner-accepted-discrepancy', None, shown))
        self.assertEqual({p.name: p.read_bytes() for p in (study_dir / 'focus-group' / 'accepted').glob('*.json')},
                         records)
        self.assertEqual(participant_requests(), charged)

    def test_an_equivalent_wrong_model_reading_from_a_new_source_reuses_the_owner_answer(self):
        wrong = {'providerInstanceId': 'claudeAgent', 'model': 'claude-fixture-deep'}
        h, c, rec = self.study(first_identity=wrong)
        found = self.evidence_row(h, c[0])
        self.assertEqual(found['kind'], 'wrong-model')
        source = h.base / 'owner' / 'identity-original.txt'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f'Selected option: {found["instruction"]}\n')
        first = self.decide(h, rec[0], found['instruction'], source=source)
        for n in (0, 1):
            self.assertEqual(h.journey(n)[0], 0)
        self.record_exception(h)
        host = next(t for t in h.job_state()['tasks'] if t['task_id'] == 'fi-01')['handles'][-1]['task_id']
        code, out = h.observe('fi-01', kind='reconciled', request_id='fi-01-r0', host_task_id=host, status='completed',
                              work_state='result_available', has_pending_child_runs=False,
                              configuration_identity=wrong)
        self.assertEqual(code, 0, out)
        self.reemit(h, rec[0], found, source, first)
        for stage in ('first-impression', 'journey'):
            self.assertEqual(self.stage_error(h.accept(stage)), (0, True, None))
        self.assert_mismatch_kept(h, 'fi-01', 'fi-01-r0')
        _, record = h.bind_analysis()
        moved = sources(record)[(c[0], 'first-impression')]
        self.assertEqual((moved['identity'], moved['observed'], moved['identity_evidence']['decision_sha256']),
                         ('owner-accepted-discrepancy', wrong, first['decision_sha256']))

    def refused_code(self, outcome, code):
        self.assertEqual((outcome[0], outcome[1]['error']['code']), (1, code), outcome[1])


if __name__ == '__main__':
    unittest.main()
