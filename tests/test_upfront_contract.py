from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from shared import execution_agreement as agreements, model_selection as models
from upfront_fixtures import chosen, engineering, completion_payload
from tests.upfront_fixtures import agree
from tests.model_selection_fixtures import answer, selection_input, replacement
from shared import delivery

ROOT = Path(__file__).resolve().parents[1]


class PublicAgreementTests(unittest.TestCase):
    def cli(self, command, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            path.write_text(json.dumps(data))
            return subprocess.run([sys.executable, str(ROOT / 'scripts/catalog.py'), 'agreement',
                command, '--input', str(path)], cwd=ROOT, capture_output=True, text=True)

    def test_public_inventory_covers_every_manifest(self):
        result = self.cli('inventory', {'root': str(ROOT)})
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(rows, agreements.inventory(ROOT))
        manifests = [json.loads(path.read_text()) for path in (ROOT / 'plugins').glob('*/plugin.json')]
        expected = {m['name'] + '/' + op for m in manifests for op in m['operations']}
        self.assertEqual({row['operation'] for row in rows}, expected)
        self.assertEqual(len(rows), len(expected))

    def test_public_completion_requires_current_ci(self):
        record = chosen()
        evidence = engineering(record)
        good = self.cli('complete', {'selection': record, 'evidence': evidence, 'revision': 'revision-one'})
        self.assertEqual(good.returncode, 0, good.stderr)
        evidence['ci']['checks']['required'] = 'failed'
        bad = self.cli('complete', {'selection': record, 'evidence': evidence, 'revision': 'revision-one'})
        self.assertNotEqual(bad.returncode, 0)

    def test_public_continuations_need_no_retain_prompt(self):
        record = chosen()
        for event in ('resume', 'repair', 'compaction', 'wake', 'forward'):
            result = self.cli('admit', {'selection': record, 'event': event})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)['chooser'])

    def test_direct_control_cannot_dispatch_or_publish_with_an_approved_selection(self):
        selected = chosen('imps/doctor', 'Reviewed output')
        self.assertEqual(self.cli('admit', {'selection': selected}).returncode, 0)
        self.assertEqual(self.cli('admit', {'operation': 'imps/doctor', 'action': 'deterministic'}).returncode, 0)
        for action in ('dispatch', 'edit', 'pr'):
            self.assertNotEqual(self.cli('admit', {'selection': selected, 'operation': 'imps/doctor',
                                                  'action': action}).returncode, 0)

    def test_real_resume_operation_alias_consumes_its_existing_scope(self):
        for producer, resume, endpoint in (('imps/run', 'imps/resume', 'Open PR'),
                ('ralph/run', 'ralph/resume', 'Open PR'),
                ('focus-group/run', 'focus-group/resume', 'Reviewed output')):
            selected = chosen(producer, endpoint)
            result = self.cli('inherit', {'selection': selected, 'operation': resume})
            self.assertEqual(result.returncode, 0, result.stderr)
            inherited = json.loads(result.stdout)
            self.assertFalse(inherited['chooser'])
            self.assertEqual(inherited['agreement_sha256'], selected['agreement']['agreement_sha256'])
        self.assertNotEqual(self.cli('inherit', {'selection': chosen(), 'operation': 'ralph/resume'}).returncode, 0)

    def test_inspection_infers_supplied_choices_and_rounds_only_material_gaps(self):
        data = {'operation': 'imps/run', 'inspected': {k: 'fixture:' + k for k in agreements.INSPECTIONS},
            'context': {'base': 'trunk', 'checks': ['unit'], 'destination': 'fixture-production'},
            'supplied': {'endpoint': 'Verified in Prod'},
            'required': ['base', 'checks', 'destination', 'endpoint', 'approval'],
            'recommendations': {'approval': 'Approve displayed bounded path'},
            'assumptions': ['Use the documented deploy procedure']}
        out = json.loads(self.cli('inspect', data).stdout)
        self.assertEqual(out['question_batches'], 1)
        self.assertEqual([q['field'] for q in out['questions']], ['approval'])
        data['supplied']['approval'] = 'fixture:existing-scoped-answer'
        self.assertEqual(json.loads(self.cli('inspect', data).stdout)['questions'], [])
        data['required'] += ['workhorse', 'reviewer']
        out = json.loads(self.cli('inspect', data).stdout)
        self.assertEqual(out['question_batches'], 2)
        self.assertEqual([q['field'] for q in out['questions']], ['workhorse', 'reviewer'])
        data['supplied']['workhorse'] = 'fixture:chosen-workhorse'
        out = json.loads(self.cli('inspect', data).stdout)
        self.assertEqual(out['question_batches'], 1)
        self.assertEqual([q['field'] for q in out['questions']], ['reviewer'])
        self.assertEqual(out['facts']['workhorse'], 'fixture:chosen-workhorse')
        self.assertEqual(out['facts']['approval'], 'fixture:existing-scoped-answer')
        data['inspected'].pop('state')
        self.assertNotEqual(self.cli('inspect', data).returncode, 0)

    def test_new_boundaries_hold_only_dependent_action_and_silence_grants_nothing(self):
        record = chosen()
        for boundary in ({'destinations': {'production': 'new-place'}}, {'limits': {'max_cost': 100}},
                         {'operations': ['imps/run', 'unapproved-provider/run']}):
            self.assertNotEqual(self.cli('admit', {'selection': record, 'boundary': boundary}).returncode, 0)
            self.assertEqual(self.cli('admit', {'selection': record, 'action': 'edit'}).returncode, 0)
        raw = selection_input(); raw['operation'] = 'imps/run'; agree(raw)
        raw['agreement']['authority'] = [{'actions': ['inspect', 'edit', 'test', 'dispatch'], 'source': answer()}]
        raw['agreement'] = agreements.freeze(raw['agreement'], raw); record = models.freeze(raw)
        self.assertEqual(self.cli('admit', {'selection': record, 'action': 'edit'}).returncode, 0)
        self.assertNotEqual(self.cli('admit', {'selection': record, 'action': 'pr'}).returncode, 0)
        raw['agreement']['source'] = None
        with self.assertRaises(ValueError): agreements.freeze(raw['agreement'], raw)

    def test_all_direct_controls_are_question_free_and_nested_calls_inherit(self):
        for row in agreements.inventory(ROOT):
            self.assertTrue((ROOT / row['entry']).is_file())
            self.assertTrue((ROOT / row['route']).is_file())
            if row['classification'] == 'direct':
                out = self.cli('admit', {'operation': row['operation'], 'action': 'deterministic'})
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(json.loads(out.stdout), {'allowed': True, 'chooser': False, 'dispatch': False})
        raw = selection_input(); raw['operation'] = 'imps/prs'
        agree(raw, operations=['imps/prs', 'babysitter/pr'])
        record = models.freeze(raw)
        out = self.cli('inherit', {'selection': record, 'operation': 'babysitter/pr'})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)['agreement_sha256'], record['agreement']['agreement_sha256'])
        self.assertNotEqual(self.cli('inherit', {'selection': record, 'operation': 'agent-tuneup/tuneup'}).returncode, 0)

    def test_endpoint_review_dispositions_require_resolution_evidence(self):
        invalid = [None, 'deferred', 'arbitrary', 'fixed', 'rejected']
        findings = [{'severity': severity, **({'disposition': value} if value else {})}
                    for severity in ('blocker', 'major') for value in invalid]
        findings += [{'severity': severity, 'disposition': value, 'evidence': ['fixture:deferred-reason']}
                     for severity in ('blocker', 'major') for value in ('deferred', 'arbitrary')]
        findings += [{'severity': severity, 'disposition': value, 'evidence': evidence}
                     for severity in ('blocker', 'major') for value in ('fixed', 'rejected')
                     for evidence in ([], '')]
        for endpoint in (*agreements.ENGINEERING, 'Markdown PR'):
            selected = chosen('elephant-goldfish/thinking' if endpoint == 'Markdown PR' else 'imps/run', endpoint)
            original = engineering(selected)
            if endpoint == 'Markdown PR':
                original['pr']['files'] = ['docs/brief.md']
            if endpoint in agreements.ENGINEERING[1:]:
                original['pr']['state'] = 'merged'
            def complete(finding):
                evidence = deepcopy(original)
                evidence['review']['findings'] = [finding]
                if endpoint != 'Markdown PR':
                    return self.cli('complete', {'selection': selected, 'evidence': evidence, 'revision': 'revision-one'})
                content = 'a' * 64
                state = delivery.start(selected, content)
                row = {**evidence, 'reference': 'fixture:actual-markdown-pr', 'content_sha256': content}
                state = delivery.reconcile(selected, state, 'delivery', row)['state']
                return self.cli('delivery-complete', {'selection': selected, 'state': state,
                    'content_sha256': content, 'source_ready': True, 'revision': 'revision-one'})
            for finding in findings:
                with self.subTest(endpoint=endpoint, finding=finding):
                    result = complete(finding)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('unresolved adverse review findings', result.stderr)
            for severity in ('blocker', 'major'):
                for disposition in ('fixed', 'rejected'):
                    result = complete({'severity': severity, 'disposition': disposition,
                                       'evidence': ['fixture:current-source-resolution']})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(json.loads(result.stdout)['complete'])

    def test_external_approval_and_agreement_tampering_fail_closed(self):
        raw = selection_input(); raw['operation'] = 'imps/run'; agree(raw)
        raw['agreement']['external_gates'] = [{'id': 'organisation', 'actions': ['merge']}]
        raw['agreement'] = agreements.freeze(raw['agreement'], raw); record = models.freeze(raw)
        self.assertNotEqual(self.cli('admit', {'selection': record, 'action': 'merge'}).returncode, 0)
        self.assertEqual(self.cli('admit', {'selection': record, 'action': 'merge',
            'external': [{'id': 'organisation', 'status': 'approved', 'reference': 'fixture:actual-approval'}]}).returncode, 0)
        broken = deepcopy(record); broken['agreement']['target']['label'] = 'Verified in Prod'
        self.assertNotEqual(self.cli('admit', {'selection': broken}).returncode, 0)
        legacy = selection_input(); legacy['operation'] = 'imps/run'
        legacy = models.freeze(legacy)
        self.assertNotEqual(self.cli('admit', {'selection': legacy}).returncode, 0)

    def test_split_reviews_cannot_hide_any_unresolved_major(self):
        for endpoint in (*agreements.ENGINEERING, 'Markdown PR'):
            selected = chosen('elephant-goldfish/thinking' if endpoint == 'Markdown PR' else 'imps/run', endpoint)
            for location in ('primary', 'slot', 'additional'):
                for severity in ('blocker', 'major'):
                    for disposition, proof, code in (('deferred', ['fixture:reason'], 2),
                            ('arbitrary', ['fixture:reason'], 2), ('fixed', [], 2), ('rejected', [], 2),
                            ('fixed', ['fixture:resolution'], 0), ('rejected', ['fixture:resolution'], 0)):
                        with self.subTest(endpoint=endpoint, location=location, severity=severity, disposition=disposition, proof=proof):
                            evidence = engineering(selected)
                            if endpoint in agreements.ENGINEERING[1:]: evidence['pr']['state'] = 'merged'
                            evidence['reviews'] = [deepcopy(evidence['review'])]
                            row = evidence['review'] if location == 'primary' else evidence['reviews'][0]
                            if location == 'additional':
                                row = {'slot_id': 'historical-objection'}
                                evidence['reviews'].append(row)
                            row['findings'] = [{'severity': severity, 'disposition': disposition, 'evidence': proof}]
                            result = self.cli(*completion_payload(selected, evidence))
                            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                            if code: self.assertIn('unresolved adverse review findings', result.stderr)
                            else: self.assertTrue(json.loads(result.stdout)['complete'])

    def test_completion_requires_actual_replacement_authors_but_allows_unused_backup(self):
        for endpoint in (*agreements.ENGINEERING, 'Markdown PR'):
            raw = selection_input()
            raw['operation'] = 'elephant-goldfish/thinking' if endpoint == 'Markdown PR' else 'imps/run'
            backup = deepcopy(raw['review_panel'][0]['target'])
            spare = deepcopy(raw['profiles']['models'][2]['target'])
            raw['work_replacements'] = [replacement(raw, backup)]
            raw['review_replacements'] = [replacement(raw, spare, review=True)]
            agree(raw, endpoint); selected = models.freeze(raw)
            failure = {'kind': 'technical', 'reference': 'fixture:outage', 'reconciled': [{
                'target': raw['work']['workhorse'], 'request_id': 'original-request', 'host_task_id': 'original-host',
                'owned': True, 'has_pending_child_runs': False, 'status': 'failed',
                'reason': 'technical', 'reference': 'fixture:terminal'}]}
            plan = models.dispatch(selected, role='workhorse', target=backup, unavailable=failure)
            self.assertEqual(plan['target'], backup)
            for authors, switched, code in ((None, False, 2), ([], False, 2), (['unknown'], False, 2),
                    (['beta'], False, 2), (['alpha'], False, 0), (['alpha', 'beta'], True, 0),
                    (['alpha', 'beta', 'gamma'], True, 2)):
                with self.subTest(endpoint=endpoint, authors=authors, switched=switched):
                    evidence = engineering(selected)
                    if endpoint in agreements.ENGINEERING[1:]: evidence['pr']['state'] = 'merged'
                    if authors is not None: evidence['author_lineages'] = authors
                    if switched:
                        evidence['review'].update(target=spare, observed=deepcopy(spare), unavailable={
                            'kind': 'capability', 'cause': 'author-independence', 'reference': 'fixture:actual-authors',
                            'original_not_launched': True})
                    result = self.cli(*completion_payload(selected, evidence))
                    self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                    if not code: self.assertTrue(json.loads(result.stdout)['complete'])
            # A review row alone cannot assert the work's complete author history.
            evidence = engineering(selected); evidence['review']['author_lineages'] = ['alpha']
            if endpoint in agreements.ENGINEERING[1:]: evidence['pr']['state'] = 'merged'
            self.assertEqual(self.cli(*completion_payload(selected, evidence)).returncode, 2)

    def test_exact_engineering_choices_and_endpoint_negative_matrix(self):
        for endpoint in agreements.ENGINEERING:
            record = chosen(endpoint=endpoint); evidence = engineering(record)
            if endpoint != 'Open PR': evidence['pr']['state'] = 'merged'
            data = {'selection': record, 'evidence': evidence, 'revision': 'revision-one'}
            self.assertEqual(self.cli('complete', data).returncode, 0, endpoint)
            cases = [('pr', 'head', 'old'), ('pr', 'base', 'wrong'), ('pr', 'linked', False),
                     ('review', 'head', 'old'), ('review', 'status', 'adverse'), ('ci', 'head', 'old')]
            for group, field, value in cases:
                broken = deepcopy(data); broken['evidence'][group][field] = value
                self.assertNotEqual(self.cli('complete', broken).returncode, 0, (endpoint, group, field))
            for field in ('local', 'review', 'ci', 'pr'):
                broken = deepcopy(data); broken['evidence'].pop(field)
                self.assertNotEqual(self.cli('complete', broken).returncode, 0)
            if endpoint != 'Open PR':
                for group, field, value in [('tag', 'revision', 'wrong'), ('tag', 'remote', False),
                                             ('tag', 'name', 'v9.9.9'), ('merge', 'status', 'queued')]:
                    broken = deepcopy(data); broken['evidence']['release'][group][field] = value
                    self.assertNotEqual(self.cli('complete', broken).returncode, 0)
                broken = deepcopy(data); broken['evidence']['release']['distribution'] = {}
                self.assertNotEqual(self.cli('complete', broken).returncode, 0)
            if endpoint == 'Verified in Prod':
                for field, value in [('version', '0.1.0'), ('revision', 'old'), ('status', 'queued'),
                                     ('destination', 'another-place')]:
                    broken = deepcopy(data); broken['evidence']['production'][field] = value
                    self.assertNotEqual(self.cli('complete', broken).returncode, 0)
                broken = deepcopy(data); broken['evidence']['production']['checks']['health']['deployment_id'] = 'old'
                self.assertNotEqual(self.cli('complete', broken).returncode, 0)
                broken = deepcopy(data); broken['evidence'].pop('production')
                self.assertNotEqual(self.cli('complete', broken).returncode, 0)
        raw = selection_input(); raw['operation'] = 'imps/run'; agree(raw)
        raw['agreement']['target']['no_change'] = True
        with self.assertRaises(ValueError): agreements.freeze(raw['agreement'], raw)

    def test_ordered_backups_exact_options_ownership_and_all_authors(self):
        raw = selection_input(); raw['operation'] = 'imps/run'
        backup = deepcopy(raw['review_panel'][0]['target'])
        spare = deepcopy(raw['profiles']['models'][2]['target'])
        raw['work_replacements'] = [replacement(raw, backup)]
        raw['review_replacements'] = [replacement(raw, spare, review=True)]
        agree(raw); record = models.freeze(raw)
        prior = {'target': raw['work']['workhorse'], 'request_id': 'original-request', 'host_task_id': 'original-host',
            'owned': True, 'has_pending_child_runs': False, 'status': 'failed', 'reason': 'technical', 'reference': 'fixture:terminal'}
        failure = {'kind': 'technical', 'reference': 'fixture:outage', 'reconciled': [prior]}
        plan = models.dispatch(record, role='workhorse', target=backup, unavailable=failure)
        self.assertEqual(plan['target']['options'], backup['options'])
        self.assertEqual(models.correlate(plan, plan['target'])['options'], 'matched')
        for observed in ({k: v for k, v in backup.items() if k != 'options'}, {**backup, 'options': {}},
                         {**backup, 'model': 'unseen'}):
            with self.assertRaises(ValueError): models.correlate(plan, observed)
        for change in ({'status': 'running'}, {'owned': False}, {'has_pending_child_runs': True}):
            bad = deepcopy(failure); bad['reconciled'][0].update(change)
            with self.assertRaises(ValueError): models.dispatch(record, role='workhorse', target=backup, unavailable=bad)
        for bad in ({'kind': 'adverse', 'reference': 'fixture:healthy'}, {**failure, 'verdict': 'adverse'}):
            with self.assertRaises(ValueError): models.dispatch(record, role='workhorse', target=backup, unavailable=bad)
        with self.assertRaises(ValueError): models.dispatch(record, role='workhorse', target=backup,
            unavailable=failure, live_tasks=['original-request'])
        with self.assertRaises(ValueError): models.dispatch(record, role='reviewer', slot_id='review', author_lineages=['beta'])
        independent = {'kind': 'capability', 'cause': 'author-independence', 'reference': 'fixture:authors',
                       'original_not_launched': True}
        plan = models.dispatch(record, role='reviewer', slot_id='review', target=spare,
                               unavailable=independent, author_lineages=['beta'])
        self.assertEqual(plan['target'], spare)
        with self.assertRaises(ValueError): models.dispatch(record, role='reviewer', slot_id='review', target=spare,
                               unavailable=independent, author_lineages=['beta', 'gamma'])
        with self.assertRaises(ValueError): models.dispatch(record, role='reviewer', slot_id='review', author_lineages=['unknown'])
        state = {'handles': ['original-host'], 'findings': ['F-major'], 'rounds_used': 2, 'round_limit': 3}
        continued = models.prospective(record, record, state, requested_rereview=True)
        self.assertEqual(continued['handles'], state['handles']); self.assertEqual(continued['findings'], state['findings'])
        self.assertEqual(continued['rounds_used'], 3)
        with self.assertRaises(ValueError): models.prospective(record, record, continued, requested_rereview=True)

    def test_preferred_live_custom_names_need_suitability_and_exact_options(self):
        raw = selection_input()
        raw['profiles']['models'][0]['preference_names'] = ['Preferred worker']
        raw['profiles']['models'][1]['preference_names'] = ['Preferred judge']
        result = models.recommend(raw['capabilities'], raw['profiles'],
            ['Preferred worker', 'Preferred judge', 'Missing choice'], authors=['alpha'])
        self.assertEqual(result['chains']['workhorse'][0]['target']['model'], 'alpha-work')
        self.assertEqual(result['chains']['reviewer'][0]['target']['options'], {'effort': 'high'})
        self.assertTrue(any(g.get('reason') == 'missing' for g in result['gaps']))
        raw['profiles']['models'][1]['quality'] = 0
        self.assertFalse(models.recommend(raw['capabilities'], raw['profiles'], ['Preferred judge'], authors=['alpha'])['chains']['reviewer'])


    def test_all_required_reviews_and_release_publication_are_obligations(self):
        raw = selection_input(); raw['operation'] = 'imps/run'
        second = deepcopy(raw['review_panel'][0]); second['slot_id'] = 'second'
        second['target'] = deepcopy(raw['profiles']['models'][2]['target'])
        raw['review_panel'].append(second); agree(raw); selected = models.freeze(raw)
        evidence = engineering(selected)
        args = {'selection': selected, 'evidence': evidence, 'revision': 'revision-one'}
        self.assertNotEqual(self.cli('complete', args).returncode, 0)
        second_row = {**deepcopy(evidence['review']), 'slot_id': 'second', 'execution_id': 'second-host',
                      'observed': second['target']}
        evidence['reviews'] = [evidence['review'], second_row]
        self.assertEqual(self.cli('complete', args).returncode, 0)
        # The host adapter's retained authors cannot be omitted by a delivery caller.
        with self.assertRaises(ValueError):
            delivery.engineering(selected, evidence, 'revision-one', author_lineages=['beta'])
        for change in ({'head': 'old'}, {'execution_id': evidence['review']['execution_id']},
                       {'status': 'adverse'}, {'execution_id': True}, {'findings': [{'severity': 'major'}]}):
            bad = deepcopy(evidence); bad['reviews'][1].update(change)
            self.assertNotEqual(self.cli('complete', {**args, 'evidence': bad}).returncode, 0)
        for label in ('Tagged Version', 'Verified in Prod'):
            selected = chosen(endpoint=label); evidence = engineering(selected)
            evidence['pr']['state'] = 'merged'
            evidence['source_head'] = 'pre-squash-head'; evidence['pr']['head'] = 'pre-squash-head'
            evidence['release']['merge']['head'] = 'pre-squash-head'
            self.assertEqual(self.cli('complete', {'selection': selected, 'evidence': evidence,
                                                 'revision': 'revision-one'}).returncode, 0)
            for field, value in (('status', 'draft'), ('revision', 'old'), ('id', None)):
                bad = deepcopy(evidence); bad['release']['publication'][field] = value
                self.assertNotEqual(self.cli('complete', {'selection': selected, 'evidence': bad,
                                                        'revision': 'revision-one'}).returncode, 0)

    def test_repair_new_revision_reuses_scope_and_absence_retains_budget(self):
        selected = chosen(); evidence = engineering(selected)
        evidence['ci']['checks']['required'] = 'failed'
        self.assertNotEqual(self.cli('complete', {'selection': selected, 'evidence': evidence,
                                               'revision': 'revision-one'}).returncode, 0)
        self.assertEqual(self.cli('complete', {'selection': selected, 'evidence': engineering(selected, 'revision-two'),
                                            'revision': 'revision-two'}).returncode, 0)
        self.assertFalse(json.loads(self.cli('admit', {'selection': selected, 'event': 'repair'}).stdout)['chooser'])
        from shared.job_coordinator import _shared_observation, corroborate_replacement
        target = selected['work']['workhorse']
        task = {'task_id': 'work', 'request_id': 'owned-request', 'target': target, 'uncertain_calls': 1,
                'cycle': 2, 'attempt': 2, 'handles': [], 'findings': ['F-major']}
        job = {'tasks': [task], 'model_selection': selected}
        event = {'kind': 'reconciled', 'status': 'absent', 'request_id': 'owned-request',
                 'has_pending_child_runs': False, 'target': target, 'reference': 'fixture:host-absence'}
        with self.assertRaises(ValueError): _shared_observation(job, 'work', {**event, 'request_id': 'other'})
        self.assertTrue(_shared_observation(job, 'work', event))
        self.assertEqual((task['attempt'], task['cycle'], task['findings']), (2, 2, ['F-major']))
        task['request_id'] = 'retry-request'
        corroborate_replacement(job, {'unavailable': {'reconciled': [event]}})
        with self.assertRaises(ValueError):
            corroborate_replacement(job, {'unavailable': {'reconciled': [{**event, 'reference': 'invented'}]}})


class ThinkingDeliveryTests(unittest.TestCase):
    cli = PublicAgreementTests.cli
    def published(self, key, content, number):
        return {'id': number, 'url': 'https://github.com/example/project/issues/' + str(number),
            'repository': 'example/project', 'content_sha256': content, 'status': 'published',
            'reference': 'fixture:actual-' + key}

    def test_native_subissue_content_requires_sha256(self):
        selected = chosen('elephant-goldfish/thinking', 'Issue with subissues')
        spec = {'key': 'one', 'content_sha256': 'b' * 64, 'depends_on': [], 'acceptance': ['Observable criterion']}
        data = {'selection': selected, 'content_sha256': 'a' * 64, 'subissues': [spec]}
        self.assertEqual(self.cli('delivery-start', data).returncode, 0)
        for value in ('not-a-content-hash', True, 'b' * 63):
            spec['content_sha256'] = value
            self.assertNotEqual(self.cli('delivery-start', data).returncode, 0)

    def test_native_dependencies_are_distinct_edges(self):
        selected = chosen('elephant-goldfish/thinking', 'Issue with subissues')
        specs = [{'key': 'one', 'content_sha256': 'b' * 64, 'depends_on': [], 'acceptance': ['First criterion']},
                 {'key': 'two', 'content_sha256': 'c' * 64, 'depends_on': ['one', 'one'], 'acceptance': ['Second criterion']}]
        self.assertNotEqual(self.cli('delivery-start', {'selection': selected, 'content_sha256': 'a' * 64,
                                                      'subissues': specs}).returncode, 0)
        specs[1]['depends_on'] = ['one']
        self.assertEqual(self.cli('delivery-start', {'selection': selected, 'content_sha256': 'a' * 64,
                                                   'subissues': specs}).returncode, 0)

    def test_native_issue_delivery_partial_reconciliation_and_dependencies(self):
        selected = chosen('elephant-goldfish/thinking', 'Issue with subissues')
        content = 'a' * 64
        specs = [{'key': 'first', 'content_sha256': 'b' * 64, 'depends_on': [], 'acceptance': ['local behavior']},
                 {'key': 'second', 'content_sha256': 'c' * 64, 'depends_on': ['first'], 'acceptance': ['integrated behavior']}]
        state = delivery.start(selected, content, specs)
        state = delivery.reconcile(selected, state, 'parent', request_id='create-parent')['state']
        self.assertEqual(delivery.reconcile(selected, state, 'parent', request_id='different')['action'], 'reconcile')
        parent = self.published('parent', content, 1); parent['request_id'] = 'create-parent'; parent['native_subissue_ids'] = [2, 3]
        state = delivery.reconcile(selected, state, 'parent', parent)['state']
        self.assertEqual(delivery.reconcile(selected, state, 'parent')['action'], 'inspect-existing')
        with self.assertRaises(ValueError): delivery.thinking(selected, state, content, source_ready=True)
        for number, spec in enumerate(specs, 2):
            row = self.published(spec['key'], spec['content_sha256'], number)
            row.update(parent_id=1, native_subissue=True, acceptance=spec['acceptance'],
                       depends_on_ids=[] if number == 2 else [2])
            state = delivery.reconcile(selected, state, spec['key'], row)['state']
        args = {'selection': selected, 'state': state, 'content_sha256': content, 'source_ready': True}
        self.assertEqual(self.cli('delivery-complete', args).returncode, 0)
        self.assertFalse(json.loads(self.cli('delivery-complete', args).stdout)['execution_authorized'])
        for key, field, value in [('parent', 'native_subissue_ids', []), ('first', 'native_subissue', False),
                                   ('second', 'depends_on_ids', []), ('first', 'content_sha256', 'd' * 64)]:
            broken = deepcopy(state); broken['observations'][key][field] = value; broken = delivery._seal(broken)
            self.assertNotEqual(self.cli('delivery-complete', {**args, 'state': broken}).returncode, 0)
        with self.assertRaises(ValueError): delivery.reconcile(selected, state, 'parent', {**parent, 'id': 999})
        with self.assertRaises(ValueError): delivery.thinking(selected, state, 'd' * 64, source_ready=True)
        with self.assertRaises(ValueError): delivery.thinking(selected, state, content, source_ready=False)

    def test_draft_discussion_and_wrong_head_markdown_fail(self):
        selected = chosen('elephant-goldfish/thinking', 'Discussion post'); content = 'a' * 64
        state = delivery.start(selected, content)
        row = self.published('discussion', content, 5)
        row.update(url='https://github.com/example/project/discussions/5', category_id='category-fixture', is_draft=False)
        state = delivery.reconcile(selected, state, 'delivery', row)['state']
        self.assertTrue(delivery.thinking(selected, state, content, source_ready=True)['complete'])
        for field, value in [('is_draft', True), ('status', 'draft'), ('category_id', 'other')]:
            broken = deepcopy(state); broken['observations']['delivery'][field] = value
            with self.assertRaises(ValueError): delivery.thinking(selected, delivery._seal(broken), content, source_ready=True)
        selected = chosen('elephant-goldfish/thinking', 'Markdown PR'); state = delivery.start(selected, content)
        row = engineering(selected); row['content_sha256'] = content; row['pr']['files'] = ['docs/brief.md']
        state = delivery.reconcile(selected, state, 'delivery', {**row, 'reference': 'fixture:actual-pr'})['state']
        self.assertTrue(delivery.thinking(selected, state, content, source_ready=True, revision='revision-one')['complete'])
        for field, value in [('head', 'wrong-head'), ('files', ['src/feature.py'])]:
            broken = deepcopy(state); broken['observations']['delivery']['pr'][field] = value
            with self.assertRaises(ValueError): delivery.thinking(selected, delivery._seal(broken), content,
                                                                 source_ready=True, revision='revision-one')

    def test_external_approval_is_required_and_retained_without_new_interview(self):
        raw = selection_input(); raw['operation'] = 'elephant-goldfish/thinking'
        agree(raw, 'Discussion post')
        raw['agreement']['external_gates'] = [{'id': 'publication-owner', 'actions': ['publish-discussion']}]
        raw['agreement'] = agreements.freeze(raw['agreement'], raw); selected = models.freeze(raw)
        content = 'a' * 64; state = delivery.start(selected, content)
        row = self.published('discussion', content, 5)
        row.update(url='https://github.com/example/project/discussions/5', category_id='category-fixture', is_draft=False)
        with self.assertRaises(ValueError): delivery.reconcile(selected, state, 'delivery', row)
        approval = [{'id': 'publication-owner', 'status': 'approved', 'reference': 'fixture:external-approval'}]
        state = delivery.reconcile(selected, state, 'delivery', row, external=approval)['state']
        self.assertTrue(delivery.thinking(selected, state, content, source_ready=True)['complete'])
        self.assertEqual(delivery.reconcile(selected, state, 'delivery')['action'], 'inspect-existing')
        bad = deepcopy(state); bad['observations']['delivery']['id'] = 999
        with self.assertRaises(ValueError): delivery.thinking(selected, delivery._seal(bad), content, source_ready=True)


if __name__ == '__main__':
    unittest.main()
