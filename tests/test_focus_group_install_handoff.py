"""Installed handoff cases split to retain the 600-second module deadline."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.focus_group_install_fixtures import (  # noqa: E402
    HandoffHost, RelocatedInstallCase, STATE, Swap, audit_rows, audited,
    setUpModule, sha, tearDownModule,
)


class RelocatedInstallTest(RelocatedInstallCase):
    def test_5_generated_handoff_reaches_frozen_pinned_participant_stage_acceptance(self):
        self.adopt()
        base = STATE['base'] / 'handoff-accepted'
        base.mkdir()
        with Swap(self.inst, audited(self.inst['env'], base), base):
            h = HandoffHost(base, self.inst['package'])
            h.start(mode='capture-only')
            for n in range(len(h.view['cells'])):
                run = h.begin(n)
                task = next(t for t in h.job_state()['tasks'] if t['task_id'] == run['task'])
                self.assertEqual((task['context_policy'], task['max_followups']), ('document-only', 0))
                self.assert_artifact_example(run)
                brief = run['brief']
                files = h.stimulus(h.view['study_id'])['files']
                expected = [{k: f[k] for k in ('path', 'sha256')}
                            for f in sorted(files, key=lambda f: f['name'] != 'initial-viewport.png')]
                self.assertEqual(brief['context_files'], expected)
                self.assertEqual(brief['authorization']['read'],
                                 [run['document']['path']] + [f['path'] for f in expected])
                for f in files:
                    self.assertIn(f['path'], run['text'])
                    self.assertIn(f['sha256'], run['text'])
                for contract in ('"text-only"', 'arrays of strings', 'integer byte count',
                                 'logical_slot_id', 'effective_brief_sha256', 'snapshot object exactly',
                                 'not the prepared outer JSON brief hash'):
                    self.assertIn(contract, run['text'])
                self.assertNotEqual(run['payload']['brief_sha256'], brief['effective_brief_sha256'])
                code, trace = h.trace(run)
                self.assertEqual((code, trace['data']['attempt_compliance']), (0, 'clean-in-trace'), trace)
                rows = list((h.root / h.view['study_id'] / 'focus-group/evidence/traces').glob('*.json'))
                bound = next(json.loads(p.read_text()) for p in rows
                             if json.loads(p.read_text())['request_id'] == run['request'])
                self.assertEqual(bound['document'], run['document'])
                self.assertEqual(bound['prepared_brief']['sha256'],
                                 sha(Path(bound['prepared_brief']['path']).read_bytes()))
                delivery = None
                if n == len(h.view['cells']) - 1:
                    run['payload']['image_use'] = {'saw_images': False, 'basis': 'text-only'}
                    delivery = {'state': 'unknown', 'source': 'Codex activity omitted image-view events'}
                delivered, (code, out) = h.finish(run, delivery=delivery)
                self.assertEqual(delivered[0], 0, delivered)
                self.assertEqual(code, 0, out)
            code, gate = h.accept('first-impression')
            self.assertEqual((code, gate.get('accepted')), (0, True), gate)
            self.assertEqual(h.charged()['first'], len(h.view['cells']))
        rows = audit_rows(base)
        self.assertIn('validate_study.py', {Path(r['script']).name for r in rows})
        self.assertEqual(sorted({hit for row in rows for hit in row['hits']}), [])


    def test_5b_combined_generated_journey_with_credential_gap_reaches_pinned_stage_acceptance(self):
        self.adopt()
        base = STATE['base'] / 'handoff-combined'
        base.mkdir()
        with Swap(self.inst, audited(self.inst['env'], base), base):
            h = HandoffHost(base, self.inst['package'])
            journeys = h.draft()['journeys'] + [
                {'id': 'save-plan', 'goal': 'Log in and save the plan to an account.',
                 'permitted_actions': ['sign in with a test account'], 'excluded_actions': []}]
            # One cell per model: the all-gap example makes each journey pilot unavailable,
            # so further cells on that model must remain held by the existing pilot gate.
            h.start(personas=1, mode='combined', journeys=journeys)
            self.assertFalse(any(t['stage_id'] == 'journey' for t in h.job_state()['tasks']))
            first_material = {}
            for n in range(len(h.view['cells'])):
                run = h.begin(n)
                first_material[n] = run['brief']['context_files']
                self.assertEqual(h.trace(run)[0], 0)
                delivered, outcome = h.finish(run)
                self.assertEqual((delivered[0], outcome[0]), (0, 0), (delivered, outcome))
            code, gate = h.accept('first-impression')
            self.assertEqual((code, gate.get('accepted')), (0, True), gate)

            # Real journey-slots, owner decision and plan revision, using installed helpers.
            h.declare_journeys()
            for n in range(len(h.view['cells'])):
                run = h.begin(n, stage='journey')
                task = next(t for t in h.job_state()['tasks'] if t['task_id'] == run['task'])
                self.assertEqual((task['context_policy'], task['max_followups']), ('document-only', 0))
                self.assert_artifact_example(run)
                payload = run['payload']
                self.assertEqual(payload['goals'], [])
                self.assertEqual([g['journey_id'] for g in payload['gaps']], ['plan-three-dinners'])
                self.assertIn('do not repeat them in goals or gaps', run['text'])
                briefs = h.root / h.view['study_id'] / 'focus-group/evidence/briefs'
                metadata = next(json.loads(p.read_text()) for p in briefs.glob('*.json')
                                if json.loads(p.read_text())['document'] == run['document'])
                self.assertEqual([g['journey_id'] for g in metadata['gaps']], ['save-plan'])
                self.assertEqual(run['brief']['context_files'], first_material[n])
                self.assertEqual(run['brief']['authorization']['read'],
                                 [run['document']['path']] + [f['path'] for f in run['brief']['context_files']])
                code, trace = h.trace(run)
                self.assertEqual((code, trace['data']['attempt_compliance']), (0, 'clean-in-trace'), trace)
                traces = h.root / h.view['study_id'] / 'focus-group/evidence/traces'
                bound = next(json.loads(p.read_text()) for p in traces.glob('*.json')
                             if json.loads(p.read_text())['request_id'] == run['request'])
                self.assertEqual(bound['document'], run['document'])
                self.assertEqual(bound['prepared_brief']['sha256'],
                                 sha(Path(bound['prepared_brief']['path']).read_bytes()))
                delivered, outcome = h.finish(run)
                self.assertEqual((delivered[0], outcome[0]), (0, 0), (delivered, outcome))
                # Ingest preserves exactly what the fixture child returned, with no gap repair.
                self.assertEqual(json.loads((h.root / h.view['study_id'] / run['item']['path']).read_text()), payload)
            code, gate = h.accept('journey')
            self.assertEqual((code, gate.get('accepted')), (0, True), gate)
            self.assertEqual(h.charged(), {'first': 2 * len(h.view['cells'])})
        rows = audit_rows(base)
        self.assertIn('validate_study.py', {Path(r['script']).name for r in rows})
        self.assertEqual(sorted({hit for row in rows for hit in row['hits']}), [])


    def test_6_generated_contract_negative_payloads_and_transports_stay_rejected(self):
        self.adopt()
        cases = ('basis', 'observed', 'inferred', 'size', 'bytes-string', 'bytes-bool',
                 'markdown-hash', 'outer-hash', 'binding', 'missing-image-receipts')
        for case in cases:
            with self.subTest(case=case):
                base = STATE['base'] / f'handoff-{case}'
                base.mkdir()
                with Swap(self.inst, self.inst['env'], base):
                    h = HandoffHost(base, self.inst['package'])
                    h.start(mode='capture-only')
                    run = h.begin()
                    self.assertEqual(h.trace(run)[0], 0)
                    if case == 'basis':
                        run['payload']['image_use']['basis'] = 'I read every screenshot'
                    elif case in ('observed', 'inferred'):
                        run['payload']['initial_viewport'][case] = 'a string instead of an array'
                    elif case == 'markdown-hash':
                        run['payload']['brief_sha256'] = run['brief']['effective_brief_sha256']

                    def change(result):
                        if case == 'size':
                            result['artifacts'][0]['size'] = result['artifacts'][0].pop('bytes')
                        elif case in ('bytes-string', 'bytes-bool'):
                            result['artifacts'][0]['bytes'] = '123' if case == 'bytes-string' else True
                        elif case == 'outer-hash':
                            result['effective_brief_sha256'] = run['document']['sha256']
                        elif case == 'binding':
                            result['binding'] = {'sha256': run['document']['sha256']}

                    delivery = {'state': 'unknown', 'source': 'Codex activity omitted image-view events'} \
                        if case == 'missing-image-receipts' else None
                    _, (code, out) = h.finish(run, change, delivery)
                    self.assertEqual(code, 1, out)
                    if case in ('basis', 'observed', 'inferred', 'markdown-hash', 'missing-image-receipts'):
                        check = h.write('check-exact-returned-payload.json', {
                            'revision': h.view['revision'], 'cell_id': h.cell(0), 'stage': 'first-impression',
                            'task_id': run['task'], 'payload': {k: run['item'][k] for k in ('path', 'sha256')},
                            'image_delivery': delivery or {'state': 'delivered', 'source': 'invented host receipts'}})
                        checked, verdict = h.call_evidence(*h.study('check-payload'), '--input', check)
                        self.assertEqual(checked, 1, verdict)
                    self.assertFalse(list((h.root / h.view['study_id'] / 'focus-group/accepted').glob('*.json')))
                    session = h.session(run['request'])
                    self.assertTrue(session)
                    self.assertEqual(run['transport'].read_bytes(),
                                     (h.root / h.view['study_id'] / 'focus-group' / session[-1]['raw']).read_bytes())
                    code, gate = h.accept('first-impression')
                    self.assertFalse(gate.get('accepted'), (code, gate))


    def test_7_outer_brief_permission_does_not_grant_other_job_or_source_reads(self):
        self.adopt()
        base = STATE['base'] / 'handoff-trace-refusals'
        base.mkdir()
        with Swap(self.inst, self.inst['env'], base):
            h = HandoffHost(base, self.inst['package'])
            h.start(mode='capture-only')
            run = h.begin()
            self.assertEqual(h.trace(run)[0], 0)
            foreign = h.begin(1)
            foreign_outer = next(t['brief']['path'] for t in h.job_state()['tasks'] if t['task_id'] == foreign['task'])
            for path in (foreign_outer, foreign['document']['path'],
                         h.root / h.view['study_id'] / 'job.json',
                         h.root / h.view['study_id'] / 'artifacts/tasks/fi-02/payload.json',
                         self.inst['package'] / 'scripts/study.py'):
                code, out = h.trace(run, [{'tool': 'read', 'path': str(path)}])
                self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
            code, clean = h.trace(run)
            self.assertEqual((code, clean['data']['compliance'], clean['data']['attempt_compliance']),
                             (1, 'clean-in-trace', 'contaminated'))
            _, (code, refused) = h.finish(run)
            self.assertEqual((code, refused['error']['code']), (1, 'attempt_contaminated'), refused)
            # Opaque commands naming the permitted outer brief stay unverified, never clean.
            own = next(t['brief']['path'] for t in h.job_state()['tasks'] if t['task_id'] == foreign['task'])
            code, opaque = h.trace(foreign, [{'tool': 'exec_command', 'command': f'cat {own}'}])
            self.assertEqual((code, opaque['data']['attempt_compliance']), (0, 'unverified'), opaque)
            self.assertIn('opaque_event', [p['code'] for p in opaque['data']['limits']])



if __name__ == '__main__':
    unittest.main()
