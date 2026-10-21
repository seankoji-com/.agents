"""Focus-group contract scenarios split to keep each module within the existing test deadline."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_focus_group_report import (  # noqa: E402
    MARKER,
    ReportCase,
    copy,
    json,
    load_report_module,
    setUpModule,
    sha,
    shutil,
    synthesis_for,
    tearDownModule,
)


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



if __name__ == '__main__':
    unittest.main()
