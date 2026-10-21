"""Focus-group contract scenarios split to keep each module within the existing test deadline."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_focus_group_report import (  # noqa: E402
    NonFreshHost,
    ReportHost,
    TEST_STATE,
    delivered_inputs,
    finding_sections,
    json,
    setUpModule,
    sha,
    sources,
    tearDownModule,
    tempfile,
)


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
