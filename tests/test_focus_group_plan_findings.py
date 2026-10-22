"""Focus-group planning review regressions within the existing module deadline."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_focus_group_plan import (  # noqa: E402
    BEFORE,
    CAPS,
    ContractTest,
    FixtureCase,
    copy,
    json,
    provider,
    target,
)


class ReviewFindingsTest(FixtureCase):
    """Regressions for independent-review findings FG1-F7 to FG1-F15, through the CLI."""

    accept, accept_all, carry, statuses = ContractTest.accept, ContractTest.accept_all, ContractTest.carry, ContractTest.statuses
    context, result_sha = ContractTest.context, ContractTest.result_sha

    def study_file(self, view, *parts):
        return self.ws.root.joinpath(view['study_id'], *parts)

    def approve_args(self, view):
        return ('approve', '--state-root', self.ws.root, '--study', view['study_id'], '--input')

    # FG1-F7 -----------------------------------------------------------------------------------

    def test_f7_returning_to_an_approved_revision_needs_an_amendment_for_its_grown_ceiling(self):
        draft = self.ws.draft()
        draft['limits']['max_concurrency'] = 32
        a = self.ws.plan(draft)
        self.ws.approve(a)
        self.assertEqual(a['ceiling']['max_tasks'], 22)
        # FG-3: each model's pilot gates its other cells and a journey needs its own brief, so the sixteen
        # participant charges are real accepted cells, except two journeys charged and left unfilled.
        for n, cell in enumerate(a['cells'], 1):
            self.assertEqual(self.accept(a, cell['cell_id'], 'first-impression', f'fi-{n:02d}')[0], 0)
            if n <= 6:
                self.assertEqual(self.accept(a, cell['cell_id'], 'journey', f'jr-{n:02d}',
                                             predecessors=[self.result_sha(a, f'fi-{n:02d}')])[0], 0)
            else:
                self.ws.bound_context(a, cell['cell_id'])
                self.assertIsNotNone(self.ws.participant_brief(a, cell['cell_id'], 'journey', f'jr-{n:02d}'))
                self.assertEqual(self.ws.admit(a, f'a-jr-{n}', 'journey', cell['cell_id'])[0], 0)
                self.ws.release(a, f'a-jr-{n}')
        self.assertEqual(self.ws.admit(a, 'a-analysis', 'analysis')[0], 0)
        self.assertEqual(self.ws.admit(a, 'a-review', 'review')[0], 0)
        self.assertEqual(self.ws.status(a)['charged_tasks'], 18)
        edited = copy.deepcopy(draft)
        edited['personas'][1]['constraints'] = ['small kitchen', 'no oven']
        b = self.ws.plan(edited)
        self.ws.approve(b)
        # The unchanged pilots carry into b and gate its changed cells there.
        self.ws.ok('carry', '--state-root', self.ws.root, '--study', b['study_id'], '--write')
        changed = next(c['cell_id'] for c in b['cells'] if c['persona'] == 'budget-student')
        self.assertEqual(self.ws.admit(b, 'b-new', 'first-impression', changed)[0], 0)
        back = self.ws.plan(draft)
        self.assertEqual(back['revision'], a['revision'])
        approval = back['approval']
        self.assertEqual((approval['state'], approval['approved_max_tasks'], approval['required_max_tasks']),
                         ('insufficient', 22, 23))
        self.assertIn('(ceiling 23 tasks)', approval['instruction'])
        out = self.ws.check_run(back, expect='approval_insufficient')
        self.assertEqual((out['data']['approved_max_tasks'], out['data']['required_max_tasks']), (22, 23))
        code, out = self.ws.admit(back, 'a-repair-0', 'first-impression', a['cells'][0]['cell_id'], purpose='repair')
        self.assertEqual((code, out['error']['code']), (1, 'approval_insufficient'))
        self.assertEqual(self.ws.status(back)['charged_tasks'], 19)
        # The old instruction cannot be reused; only an amendment naming the new ceiling restores authority.
        args = self.approve_args(back)
        self.ws.refused('approval_scope_mismatch', *args, self.ws.approval(back, statement=a['approval_instruction']))
        first = self.study_file(a, 'focus-group', 'approvals', a['revision'], '0000.json')
        original = first.read_bytes()
        amended = self.ws.approve(back, statement=approval['instruction'], message_ref='picker-answer-2')['approval']
        self.assertEqual((amended['state'], amended['approved_max_tasks']), ('approved', 23))
        self.assertEqual([(h['kind'], h['max_tasks'], h['message_ref']) for h in amended['history']],
                         [('approval', 22, 'picker-answer-1'), ('amendment', 23, 'picker-answer-2')])
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(self.ws.status(back)['charged'], {'first': 19})
        # The amended ceiling admits exactly the remaining repair pools and nothing beyond 23.
        cells = [c['cell_id'] for c in a['cells']]
        repairs = [('journey', cells[6]), ('journey', cells[7]), ('analysis', None), ('review', None)]
        for n, (stage, cell) in enumerate(repairs):
            code, out = self.ws.admit(back, f'repair-{n}', stage, cell, purpose='repair')
            self.assertEqual(code, 0, out)
            self.ws.release(back, f'repair-{n}')
        self.assertEqual(self.ws.status(back)['charged_tasks'], 23)
        code, out = self.ws.admit(back, 'repair-x', 'journey', cells[6], purpose='repair')
        self.assertEqual((code, out['error']['code']), (1, 'budget_exhausted'))
        self.assertEqual(self.ws.status(back)['charged_tasks'], 23)

    # FG1-F8 -----------------------------------------------------------------------------------

    def test_f8_capture_provenance_target_and_context_changes_stale_exactly_their_dependants(self):
        view = self.ws.approved()
        self.accept_all(view)

        def revise(change):
            draft = self.ws.draft()
            change(draft)
            # This only inspects draft carry diagnostics, so it must remain non-ready
            # rather than consume another assessment or enlarge the retained budget.
            preview = self.ws.plan(draft, review=False)
            self.assertFalse(preview['planning_review']['ready'])
            mapping = preview['carry_forward']
            by_stage = {}
            for entry in mapping['entries']:
                by_stage.setdefault(entry['stage'], set()).add(entry['status'])
            return by_stage, mapping

        cases = {
            'journey target URL': (lambda d: d['target'].update(url='https://staging-2.pantry-planner.example/welcome'),
                                   {'carried'}, 'journey_target_sha256'),
            'journey context': (lambda d: d.update(journey_context={'class': 'preauthenticated-test',
                                                                    'reference': 'fixture-test-context'}),
                                {'carried'}, 'context_policy_sha256'),
            'capture manifest': (lambda d: d['stimulus'].update(manifest_sha256='a' * 64), {'stale'}, 'pack_sha256'),
            'capture provenance': (lambda d: d['stimulus'].update(provenance={
                'context_class': 'fresh-anonymous', 'final_url': 'https://staging.pantry-planner.example/welcome',
                'http_status': 'unavailable-from-mechanism'}), {'stale'}, 'pack_sha256'),
        }
        for name, (change, first_status, binding) in cases.items():
            with self.subTest(change=name):
                by_stage, mapping = revise(change)
                self.assertEqual(by_stage['first-impression'], first_status)
                self.assertEqual(by_stage['journey'], {'stale'})
                journey = next(e for e in mapping['entries'] if e['stage'] == 'journey')
                stage = 'first-impression' if first_status == {'stale'} else 'journey'
                reasons = ' '.join(next(e for e in mapping['entries'] if e['stage'] == stage)['reasons'])
                self.assertIn(binding, reasons)
                if name == 'journey context':
                    self.assertIn('recorded browser context does not satisfy', ' '.join(journey['reasons']))

    def test_f8_journey_records_bind_the_browser_context_they_ran_in(self):
        view = self.ws.approved()
        cell = view['cells'][0]['cell_id']
        code, out = self.accept(view, cell, 'first-impression', 'fi-01', context=self.context(view, cell))
        self.assertEqual((code, out['error']['code']), (2, 'invalid_record'))
        self.assertEqual(self.accept(view, cell, 'first-impression', 'fi-01')[0], 0)
        first = self.result_sha(view, 'fi-01')
        code, out = self.accept(view, cell, 'journey', 'jr-01', predecessors=[first],
                                context=self.context(view, cell, cls='preauthenticated-test'))
        self.assertEqual((code, out['error']['code']), (1, 'context_mismatch'))
        code, out = self.accept(view, cell, 'journey', 'jr-01', predecessors=[first],
                                context=dict(self.context(view, cell), binding_sha256='not-a-hash'))
        self.assertEqual((code, out['error']['code']), (2, 'invalid_record'))
        self.assertEqual(self.accept(view, cell, 'journey', 'jr-01', predecessors=[first])[0], 0)
        record = json.loads(self.study_file(view, 'focus-group', 'accepted',
                                            f"{view['revision'][:16]}.{cell}.journey.json").read_text())
        self.assertEqual(record['context'], self.context(view, cell))
        self.assertIn('journey_target_sha256', record['bindings'])

    # FG1-F9 -----------------------------------------------------------------------------------

    def test_f9_changed_missing_or_escaped_accepted_artifacts_never_carry(self):
        view = self.ws.approved()
        self.accept_all(view)
        accepted = self.study_file(view, 'focus-group', 'accepted')
        records = {p.name: p.read_bytes() for p in accepted.iterdir()}
        draft = self.ws.draft()
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        good = self.ws.plan(draft)['carry_forward']
        self.assertEqual({e['status'] for e in good['entries']}, {'carried'})
        result = lambda task: self.study_file(view, 'artifacts', 'tasks', task, 'result.json')
        cells = [c['cell_id'] for c in view['cells']]
        result('fi-01').write_bytes(b'{"fixture": "rewritten after acceptance"}')
        result('fi-02').unlink()
        outside = self.ws.base / 'outside.json'
        outside.write_bytes(result('fi-03').read_bytes())
        result('fi-03').unlink()
        result('fi-03').symlink_to(outside)
        mapping = self.carry(view)
        reasons = {(e['cell_id'], e['stage']): ' '.join(e['reasons']) for e in mapping['entries']}
        statuses = self.statuses(mapping)
        self.assertIn('bytes do not match', reasons[(cells[0], 'first-impression')])
        self.assertIn('artifact is missing', reasons[(cells[1], 'first-impression')])
        self.assertIn('without symlinks', reasons[(cells[2], 'first-impression')])
        for cell in cells[:3]:
            self.assertEqual(statuses[(cell, 'journey')], 'stale')
        self.assertEqual((statuses[(cells[3], 'first-impression')], statuses[(cells[3], 'journey')]), ('carried', 'carried'))
        out = self.ws.refused('carry_forward_rejected', 'validate-carry', '--state-root', self.ws.root,
                              '--study', view['study_id'], '--input', self.ws.write('before-tamper.json', good))
        ineligible = [e for e in out['data']['errors'] if e['code'] == 'ineligible_reuse']
        self.assertEqual(len(ineligible), 6)
        # Original accepted records and their reasons for acceptance are untouched.
        self.assertEqual({p.name: p.read_bytes() for p in accepted.iterdir()}, records)

    # FG1-F10 ----------------------------------------------------------------------------------

    def test_f10_journey_builds_on_a_first_impression_carried_by_the_validated_mapping(self):
        view = self.ws.approved()
        cells = [c['cell_id'] for c in view['cells']]
        self.assertEqual(self.accept(view, cells[0], 'first-impression', 'fi-01')[0], 0)
        first = self.result_sha(view, 'fi-01')
        draft = self.ws.draft()
        draft['journeys'][0]['goal'] = 'Plan two weeknight dinners for a household of three.'
        revised = self.ws.plan(draft)
        self.ws.approve(revised)
        # Without a written mapping there is no effective predecessor in the new revision, so no journey brief
        # can be built and the journey is refused at admission, uncharged (FG-3, FG2-F1).
        self.assertIsNone(self.ws.participant_brief(revised, cells[0], 'journey', 'jr-01'))
        code, out = self.ws.admit(revised, 'jr-01-r0', 'journey', cells[0])
        self.assertEqual((code, out['error']['code']), (1, 'journey_brief_missing'))
        self.ws.ok('carry', '--state-root', self.ws.root, '--study', view['study_id'], '--write')
        code, out = self.ws.admit(revised, 'fi-again', 'first-impression', cells[0])
        self.assertEqual((code, out['error']['code']), (1, 'slot_already_filled'))
        code, out = self.accept(revised, cells[0], 'journey', 'jr-01b', predecessors=[first])
        self.assertEqual(code, 0, out)
        source = out['data']['predecessor_records']
        self.assertEqual([(s['revision'], s['result_sha256'], s['via']) for s in source],
                         [(view['revision'], first, 'carry')])
        code, out = self.ws.admit(revised, 'jr-02-r0', 'journey', cells[1])
        self.assertEqual((code, out['error']['code']), (1, 'journey_brief_missing'))
        raw = json.loads(self.study_file(view, 'focus-group', 'accepted',
                                         f"{view['revision'][:16]}.{cells[0]}.first-impression.json").read_text())
        self.assertEqual(raw['revision'], view['revision'])
        # A later deadline-only revision carries both: the original first impression and the new journey.
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        statuses = self.statuses(self.ws.plan(draft)['carry_forward'])
        self.assertEqual((statuses[(cells[0], 'first-impression')], statuses[(cells[0], 'journey')]),
                         ('carried', 'carried'))

    # FG1-F11 ----------------------------------------------------------------------------------

    def test_f11_validate_carry_checks_every_field_and_returns_the_canonical_mapping(self):
        view = self.ws.approved()
        self.accept_all(view)
        draft = self.ws.draft()
        draft['personas'][1]['constraints'] = ['small kitchen', 'no oven']
        mapping = self.ws.plan(draft, review=False)['carry_forward']
        args = ('validate-carry', '--state-root', self.ws.root, '--study', view['study_id'], '--input')
        good = self.ws.ok(*args, self.ws.write('good.json', mapping))
        self.assertEqual(good['mapping'], mapping)
        self.assertEqual(good['carried'], mapping['filled_slots'])
        carried = [e for e in mapping['entries'] if e['status'] == 'carried']
        stale = next(e for e in mapping['entries'] if e['status'] == 'stale')
        cases = {
            'forged from_revision': (dict(mapping, entries=[dict(carried[0], from_revision='0' * 64)],
                                          filled_slots=[f"{carried[0]['cell_id']}:{carried[0]['stage']}"]),
                                     'provenance_mismatch'),
            'stale entry moved to another cell': (dict(mapping, entries=[dict(stale, cell_id=carried[0]['cell_id'])]),
                                                  'silent_pooling'),
            'invented filled slot': (dict(mapping, filled_slots=mapping['filled_slots'] + ['invented:journey']),
                                     'derived_mismatch'),
            'flipped completion flag': (dict(mapping, combined_scope_complete=True), 'derived_mismatch'),
            'unknown status': (dict(mapping, entries=[dict(carried[0], status='accepted')]), 'invalid_entry'),
            'extra entry field': (dict(mapping, entries=[dict(carried[0], approved=True)]), 'invalid_entry'),
            'invented reasons': (dict(mapping, entries=[dict(carried[0], reasons=['owner said fine'])],
                                      filled_slots=[f"{carried[0]['cell_id']}:{carried[0]['stage']}"]),
                                 'provenance_mismatch'),
        }
        for name, (bad, code_name) in cases.items():
            with self.subTest(case=name):
                out = self.ws.refused('carry_forward_rejected', *args, self.ws.write(f'{code_name}.json', bad))
                self.assertEqual(out['data']['errors'][0]['code'], code_name)
        self.ws.refused('invalid_mapping', *args, self.ws.write('extra.json', dict(mapping, note='trust me')),
                        exit_code=2)

    # FG1-F12 ----------------------------------------------------------------------------------

    def test_f12_fresh_catalog_rechecks_targets_options_and_independence_before_dispatch(self):
        view = self.ws.approved()
        cell = view['cells'][1]['cell_id']
        t1, t2, t3, t4 = ('2029-06-01T00:10:00Z', '2029-06-01T00:20:00Z', '2029-06-01T00:30:00Z',
                          '2029-06-01T01:30:00Z')
        off = copy.deepcopy(CAPS)
        off['providers'][1]['canRunChildTask'] = False
        out = self.ws.check_run(view, now=t1, caps=off, expect='readiness_stale')
        self.assertEqual(out['data']['catalog_problems'][0]['problem'], 'provider_unavailable')
        code, out = self.ws.admit(view, 'fi-02-r0', 'first-impression', cell, now=t1,
                                  catalog=self.ws.catalog(t1, caps=off))
        self.assertEqual((code, out['error']['code']), (1, 'readiness_stale'))
        status = self.ws.status(view)
        self.assertEqual((status['charged_tasks'], status['catalog_observation']['ready']), (0, False))
        # Replaying an earlier passing observation cannot undo the failed refresh.
        self.ws.check_run(view, now=t1, observed_at=BEFORE, expect='stale_observation')
        code, out = self.ws.admit(view, 'fi-02-r0', 'first-impression', cell, now=t1,
                                  catalog=self.ws.catalog(t1, observed_at=BEFORE))
        self.assertEqual((code, out['error']['code']), (1, 'stale_observation'))
        # A same-lineage reviewer after a driver remap fails the independence recheck.
        remapped = copy.deepcopy(CAPS)
        for row in remapped['providers']:
            if row['providerInstanceId'] in ('fixture-a', 'fixture-c'):
                row['driverKind'] = 'claudeAgent'
        out = self.ws.check_run(view, now=t2, caps=remapped, expect='readiness_stale')
        self.assertEqual(out['data']['reviewer_independence'], 'same-lineage')
        # A fresh passing observation restores readiness; an old one is refused by age.
        self.assertTrue(self.ws.check_run(view, now=t3)['ready'])
        self.assertEqual(self.ws.admit(view, 'fi-02-r0', 'first-impression', cell, now=t3)[0], 0)
        self.ws.check_run(view, now=t4, observed_at=t3, expect='stale_observation')
        # Option domains are rechecked too.
        draft = self.ws.draft(study_id='option-study',
                              participant_models=[target('fixture-a', 'alpha-swift', reasoningEffort='high'),
                                                  target('fixture-b', 'beta-one')])
        options = self.ws.plan(draft)
        self.ws.approve(options)
        narrowed = copy.deepcopy(CAPS)
        narrowed['providers'][0]['models'][0]['options'] = [{'id': 'reasoningEffort', 'type': 'select',
                                                             'options': [{'id': 'low'}]}]
        out = self.ws.check_run(options, caps=narrowed, expect='readiness_stale')
        self.assertEqual(out['data']['catalog_problems'][0]['problem'], 'unsupported_option')
        # A journey on a model whose fresh schema shows no browser tools is a gap, not a dispatch.
        later = '2029-06-01T00:05:00Z'
        no_browser = self.ws.catalog(later, observations=[{'fact': 'browser_tools', 'state': 'unavailable',
                                                           'providerInstanceId': 'fixture-a',
                                                           'source': 'child tool schema lists no browser tools'}])
        first_cell = options['cells'][0]['cell_id']
        code, out = self.ws.admit(options, 'jr-01-r0', 'journey', first_cell, now=later, catalog=no_browser)
        self.assertEqual((code, out['error']['code']), (1, 'journey_unavailable'))
        self.ws.refused('observation_invalid', 'check-run', '--state-root', self.ws.root, '--study', view['study_id'],
                        '--capabilities', self.ws.caps, now=t4, exit_code=2)

    # FG1-F13 ----------------------------------------------------------------------------------

    def test_f13_select_options_need_an_advertised_domain_and_booleans_take_booleans(self):
        def caps(option):
            return {'providers': [provider('fixture-a', ['alpha-swift', 'alpha-deep'], options=[option]),
                                  provider('fixture-b', ['beta-one']), provider('fixture-c', ['gamma-pro'])]}
        cases = [
            ({'id': 'reasoningEffort', 'type': 'select', 'options': []}, 'not-in-catalog', 'option_domain_unavailable'),
            ({'id': 'reasoningEffort', 'type': 'select'}, 'high', 'option_domain_unavailable'),
            ({'id': 'reasoningEffort', 'type': 'select', 'options': 'low,high'}, 'low', 'option_domain_unavailable'),
            ({'id': 'reasoningEffort', 'type': 'select', 'options': [{'label': 'Low'}]}, 'low', 'option_domain_unavailable'),
            ({'id': 'reasoningEffort', 'type': 'slider', 'options': [{'id': 'low'}]}, 'low', 'option_domain_unavailable'),
            ({'id': 'reasoningEffort', 'type': 'select', 'options': [{'id': 'low'}]}, 'medium', 'unsupported_option'),
            ({'id': 'fastMode', 'type': 'boolean'}, 'true', 'unsupported_option'),
        ]
        for n, (option, value, problem) in enumerate(cases):
            with self.subTest(option=option, value=value):
                draft = self.ws.draft(study_id=f'option-{n}',
                                      participant_models=[target('fixture-a', 'alpha-swift', **{option['id']: value}),
                                                          target('fixture-b', 'beta-one')])
                code, out = self.ws.plan(draft, expect=True, caps=caps(option))
                self.assertEqual((code, out['error']['code']), (1, 'matrix_unavailable'))
                self.assertEqual(out['data']['problems'][0]['problem'], problem)
        for n, (option, value) in enumerate([({'id': 'fastMode', 'type': 'boolean'}, True),
                                             ({'id': 'reasoningEffort', 'type': 'select',
                                               'options': [{'id': 'low'}, {'id': 'high'}]}, 'high')]):
            draft = self.ws.draft(study_id=f'valid-option-{n}',
                                  participant_models=[target('fixture-a', 'alpha-swift', **{option['id']: value}),
                                                      target('fixture-b', 'beta-one')])
            view = self.ws.plan(draft, caps=caps(option))
            self.assertEqual(view['assessment']['catalog_problems'], [])
            self.assertEqual(view['cells'][0]['options'], {option['id']: value})

    # FG1-F15 ----------------------------------------------------------------------------------

    def test_f15_rejection_negation_and_quoted_instructions_never_approve(self):
        view = self.ws.plan(self.ws.draft())
        args = self.approve_args(view)
        instruction = view['approval_instruction']
        prefix = view['revision'][:12]
        for statement in (instruction.replace('Approve', 'Reject', 1), f'Do not {instruction}',
                          f'{instruction}, but not yet'):
            with self.subTest(statement=statement):
                self.ws.refused('approval_scope_mismatch', *args, self.ws.approval(view, statement=statement))
        for source in (f'Do not {instruction}\n', f'Type "{instruction}" when you are ready.\n',
                       f'Selected option: {instruction} once legal signs off\n',
                       f'Selected option: Reject focus-group revision {prefix} (ceiling 22 tasks)\n'
                       f'Example approval: "{instruction}"\n'):
            with self.subTest(source=source):
                self.ws.refused('approval_not_affirmative', *args, self.ws.approval(view, source_text=source))
        self.ws.refused('approval_ambiguous', *args, self.ws.approval(
            view, source_text=f'Selected option: {instruction}\nReject focus-group revision {prefix} (ceiling 22 tasks)\n'))
        self.assertEqual(self.ws.status(view)['approval']['state'], 'unapproved')
        self.assertFalse(self.study_file(view, 'focus-group', 'approvals').exists())
        self.ws.check_run(view, expect='unapproved_revision')
        approved = self.ws.approve(view, source_text=f'{instruction}.\n')['approval']
        self.assertEqual((approved['state'], approved['statement']), ('approved', instruction))
        self.ws.check_run(view)

    # FG1-F16 ----------------------------------------------------------------------------------

    def test_f16_a_listed_approval_option_never_overrides_the_selected_answer(self):
        view = self.ws.plan(self.ws.draft())
        args = self.approve_args(view)
        instruction = view['approval_instruction']
        question = f'Question: which option?\n{instruction}\nCancel the study\n'
        for source in (question + 'Selected option: Cancel the study\n',
                       question + 'answer: Cancel the study\n',
                       question + 'Reply: No\n',
                       question + 'Selected option:\n',
                       f'Previous answer: {instruction}\nSelected option: Cancel the study\n'):
            with self.subTest(source=source):
                self.ws.refused('approval_not_affirmative', *args, self.ws.approval(view, source_text=source))
        # A full picker transcript is not the supported record, even when its selected answer approves:
        # the saved source is the single answer alone.
        for source in (question,
                       question + f'selected option: {instruction}\n',
                       f'{instruction}\nCancel the study\n',
                       question + f'Selected option: Cancel the study\nAnswer: {instruction}\n',
                       question + f'Selected option: {instruction}\nReply: Cancel the study\n',
                       f'Selected option: {instruction}\nSelected option: {instruction}\n',
                       question + f'Selected option: {instruction}\nExample: "{instruction}"\n'):
            with self.subTest(source=source):
                self.ws.refused('approval_ambiguous', *args, self.ws.approval(view, source_text=source))
        self.assertEqual(self.ws.status(view)['approval']['state'], 'unapproved')
        self.assertFalse(self.study_file(view, 'focus-group', 'approvals').exists())
        self.ws.check_run(view, expect='unapproved_revision')
        approved = self.ws.approve(view, source_text=f'\nselected option: {instruction}\n\n')['approval']
        self.assertEqual((approved['state'], approved['statement']), ('approved', instruction))
        self.ws.check_run(view)

    # FG1-A6-N1 --------------------------------------------------------------------------------

    def test_a6_n1_a_cancelled_or_conditional_answer_never_authorises_a_task(self):
        view = self.ws.plan(self.ws.draft())
        args = self.approve_args(view)
        instruction = view['approval_instruction']
        cell = view['cells'][0]['cell_id']
        sources = (f'Selected option: {instruction}\nWait, cancel the study instead.\n',
                   f'Selected option: {instruction}\nOnly proceed after I confirm the sharing terms.\n',
                   f'Wait, cancel the study instead.\nSelected option: {instruction}\n',
                   f'{instruction}\nOnly proceed after I confirm the sharing terms.\n',
                   f'Answer: {instruction}\n\nP.S. hold off until Friday.\n')
        for n, source in enumerate(sources):
            with self.subTest(source=source):
                path = self.ws.approval(view, source_text=source)
                saved = Path(json.loads(path.read_text())['source'])
                self.ws.refused('approval_ambiguous', *args, path)
                # The actual source is read, never rewritten or trimmed to its approving line.
                self.assertEqual(saved.read_text(), source)
                self.ws.check_run(view, expect='unapproved_revision')
                code, out = self.ws.admit(view, f'fi-01-r{n}', 'first-impression', cell)
                self.assertEqual((code, out['error']['code']), (1, 'unapproved_revision'))
        self.assertEqual(self.ws.status(view)['approval']['state'], 'unapproved')
        self.assertFalse(self.study_file(view, 'focus-group', 'approvals').exists())
        self.assertFalse(self.study_file(view, 'focus-group', 'ledger.json').exists())
        # The supported single-answer record approves, and the record keeps its source, hash and message.
        path = self.ws.approval(view, source_text=f'Selected option: {instruction}\n', message_ref='picker-answer-9')
        request = json.loads(path.read_text())
        self.assertEqual(self.ws.ok(*args, path)['approval']['state'], 'approved')
        record = json.loads(self.study_file(view, 'focus-group', 'approvals', view['revision'], '0000.json').read_text())
        self.assertEqual((record['source'], record['source_sha256'], record['message_ref']),
                         (request['source'], request['source_sha256'], 'picker-answer-9'))
        self.assertTrue(self.ws.check_run(view)['ready'])
        code, out = self.ws.admit(view, 'fi-01-ok', 'first-impression', cell)
        self.assertEqual((code, out['data']['charged_tasks']), (0, 1), out)

    # FG1-F17 ----------------------------------------------------------------------------------

    def accepted_pair(self, view, cell, n=1):
        self.assertEqual(self.accept(view, cell, 'first-impression', f'fi-{n:02d}')[0], 0)
        first = self.result_sha(view, f'fi-{n:02d}')
        code, out = self.accept(view, cell, 'journey', f'jr-{n:02d}', predecessors=[first])
        self.assertEqual(code, 0, out)
        return first

    def test_f17_a_carried_journey_needs_its_first_impression_in_the_same_mapping(self):
        view = self.ws.approved()
        cell = view['cells'][0]['cell_id']
        self.accepted_pair(view, cell)
        draft = self.ws.draft()
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        mapping = self.ws.plan(draft, review=False)['carry_forward']
        first = next(e for e in mapping['entries'] if e['stage'] == 'first-impression')
        journey = next(e for e in mapping['entries'] if e['stage'] == 'journey')
        self.assertEqual((first['status'], journey['status']), ('carried', 'carried'))
        args = ('validate-carry', '--state-root', self.ws.root, '--study', view['study_id'], '--input')
        only_journey = dict(mapping, entries=[journey], filled_slots=[f'{cell}:journey'])
        out = self.ws.refused('carry_forward_rejected', *args, self.ws.write('journey-only.json', only_journey))
        self.assertEqual([e['code'] for e in out['data']['errors']], ['predecessor_missing', 'derived_mismatch'])
        # Declaring the first impression stale does not make its journey carry either.
        declined = dict(mapping, entries=[dict(first, status='stale'), journey], filled_slots=[f'{cell}:journey'])
        del declined['entries'][0]['binding_sha256']
        out = self.ws.refused('carry_forward_rejected', *args, self.ws.write('declined.json', declined))
        self.assertEqual({e['code'] for e in out['data']['errors']},
                         {'provenance_mismatch', 'predecessor_missing', 'derived_mismatch'})
        # A closed subset is valid: the first impression alone, or both.
        alone = dict(mapping, entries=[first], filled_slots=[f'{cell}:first-impression'])
        self.assertEqual(self.ws.ok(*args, self.ws.write('first-only.json', alone))['carried'],
                         [f'{cell}:first-impression'])
        self.assertEqual(self.ws.ok(*args, self.ws.write('both.json', mapping))['mapping'], mapping)

    # FG1-F18 ----------------------------------------------------------------------------------

    def late_completion(self, study_id):
        """Revision A admits a first impression and journey; revision B (deadline only) is approved and
        admits a different first impression for the same cell; then A's results complete late.

        FG-2 builds a journey brief only on its cell's accepted, frozen first impression in the current
        revision. So A's first impression completes late first; the owner returns to A (still approved) to
        brief and admit its journey, goes back to B, and A's journey then completes late as well."""
        a = self.ws.approved(study_id=study_id)
        cell = a['cells'][0]['cell_id']
        self.assertTrue(self.ws.participant_brief(a, cell, 'first-impression', 'fi-01'))
        self.assertEqual(self.ws.admit(a, 'fi-01-r0', 'first-impression', cell)[0], 0)
        draft = self.ws.draft(study_id=study_id)
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        b = self.ws.plan(draft)
        self.ws.approve(b)
        code, out = self.ws.admit(b, 'bfi-01-r0', 'first-impression', cell)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ws.participant_brief(b, cell, 'first-impression', 'bfi-01'))
        self.assertEqual(self.accept(a, cell, 'first-impression', 'fi-01', admit=False)[0], 0)
        back = self.ws.plan(self.ws.draft(study_id=study_id))
        self.assertEqual((back['revision'], back['approval']['state']), (a['revision'], 'approved'))
        self.ws.bound_context(a, cell)
        self.assertTrue(self.ws.participant_brief(a, cell, 'journey', 'jr-01'))
        self.assertEqual(self.ws.admit(a, 'jr-01-r0', 'journey', cell)[0], 0)
        again = self.ws.plan(draft)
        self.assertEqual((again['revision'], again['approval']['state']), (b['revision'], 'approved'))
        old_first = self.accepted_pair_late(a, cell)
        return a, b, cell, old_first

    def accepted_pair_late(self, view, cell):
        first = self.result_sha(view, 'fi-01')
        code, out = self.accept(view, cell, 'journey', 'jr-01', predecessors=[first], admit=False)
        self.assertEqual(code, 0, out)
        return first

    def test_f18_eligible_carry_holds_dispatch_until_the_mapping_is_written(self):
        a = self.ws.approved()
        cell = a['cells'][0]['cell_id']
        self.accepted_pair(a, cell)
        draft = self.ws.draft()
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        b = self.ws.plan(draft)
        self.ws.approve(b)
        charged = self.ws.status(b)['charged']
        for stage in ('first-impression', 'journey'):
            code, out = self.ws.admit(b, f'b-{stage}', stage, cell)
            self.assertEqual((code, out['error']['code']), (1, 'carry_unresolved'))
        self.ws.ok('carry', '--state-root', self.ws.root, '--study', b['study_id'], '--write')
        code, out = self.ws.admit(b, 'b-again', 'first-impression', cell)
        self.assertEqual((code, out['error']['code']), (1, 'slot_already_filled'))
        self.assertEqual(self.ws.status(b)['charged'], charged)

    def test_f18_a_native_result_occupies_its_slot_and_stales_the_old_first_and_journey(self):
        a, b, cell, old_first = self.late_completion('native-first')
        args = ('validate-carry', '--state-root', self.ws.root, '--study', b['study_id'], '--input')
        early = self.carry(b)
        self.assertEqual(set(self.statuses(early).values()), {'carried'})
        # B's own result is accepted before any carry mapping is written.
        code, out = self.accept(b, cell, 'first-impression', 'bfi-01', admit=False)
        self.assertEqual(code, 0, out)
        native = self.result_sha(b, 'bfi-01')
        self.assertNotEqual(native, old_first)
        out = self.ws.refused('carry_forward_rejected', *args, self.ws.write('early.json', early))
        self.assertEqual({e['code'] for e in out['data']['errors']}, {'ineligible_reuse', 'derived_mismatch'})
        written = self.ws.ok('carry', '--state-root', self.ws.root, '--study', b['study_id'], '--write')
        reasons = {(e['cell_id'], e['stage']): ' '.join(e['reasons']) for e in written['entries']}
        self.assertEqual(set(self.statuses(written).values()), {'stale'})
        self.assertIn('this revision has its own accepted result', reasons[(cell, 'first-impression')])
        self.assertIn("not this revision's effective first impression", reasons[(cell, 'journey')])
        self.assertEqual(written['filled_slots'], [])
        self.assertEqual(self.ws.ok(*args, self.ws.write('written.json', written))['carried'], [])
        # One effective first impression: a B journey binds the native result, never the old one.
        code, out = self.accept(b, cell, 'journey', 'bjr-01', predecessors=[old_first])
        self.assertEqual((code, out['error']['code']), (1, 'foreign_predecessor'))
        code, out = self.accept(b, cell, 'journey', 'bjr-01', predecessors=[native], admit=False)
        self.assertEqual(code, 0, out)
        self.assertEqual([(s['result_sha256'], s['via']) for s in out['data']['predecessor_records']],
                         [(native, 'native')])
        self.assertEqual(self.ws.status(b)['accepted_results'], 4)

    def test_f18_a_written_carry_refuses_a_late_native_result_for_the_same_slot(self):
        a, b, cell, old_first = self.late_completion('carry-first')
        written = self.ws.ok('carry', '--state-root', self.ws.root, '--study', b['study_id'], '--write')
        self.assertEqual(written['filled_slots'], [f'{cell}:first-impression', f'{cell}:journey'])
        before = self.ws.status(b)
        accepted = sorted(p.name for p in self.study_file(b, 'focus-group', 'accepted').iterdir())
        code, out = self.accept(b, cell, 'first-impression', 'bfi-01', admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'slot_already_filled'))
        # Raw evidence and counters are untouched; the carried result stays the one effective result.
        self.assertTrue(self.study_file(b, 'artifacts', 'tasks', 'bfi-01', 'result.json').is_file())
        self.assertEqual(sorted(p.name for p in self.study_file(b, 'focus-group', 'accepted').iterdir()), accepted)
        after = self.ws.status(b)
        self.assertEqual((after['charged'], after['accepted_results']), (before['charged'], before['accepted_results']))
        self.ws.ok('validate-carry', '--state-root', self.ws.root, '--study', b['study_id'], '--input',
                   self.ws.write('carry-first.json', written))

    # FG1-F20 ----------------------------------------------------------------------------------

    def native_return(self, study_id):
        """A first impression accepted in A; deadline-only B carries it (written) and accepts a journey
        built on it; the owner returns to A, where that first impression is native."""
        a = self.ws.approved(study_id=study_id)
        cell = a['cells'][0]['cell_id']
        self.assertEqual(self.accept(a, cell, 'first-impression', 'fi-01')[0], 0)
        first = self.result_sha(a, 'fi-01')
        draft = self.ws.draft(study_id=study_id)
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        b = self.ws.plan(draft)
        self.ws.approve(b)
        self.ws.ok('carry', '--state-root', self.ws.root, '--study', study_id, '--write')
        code, out = self.accept(b, cell, 'journey', 'bjr-01', predecessors=[first])
        self.assertEqual(code, 0, out)
        self.assertEqual([s['via'] for s in out['data']['predecessor_records']], ['carry'])
        back = self.ws.plan(self.ws.draft(study_id=study_id))
        self.assertEqual((back['revision'], back['approval']['state']), (a['revision'], 'approved'))
        # Control: with its native predecessor intact, the B journey carries into A.
        mapping = self.carry(back)
        self.assertEqual(self.statuses(mapping)[(cell, 'journey')], 'carried')
        self.assertEqual(mapping['filled_slots'], [f'{cell}:journey'])
        return back, cell, mapping

    def break_native_first(self, view, how):
        """Make A's native first impression unusable without touching any accepted record."""
        result = self.study_file(view, 'artifacts', 'tasks', 'fi-01', 'result.json')
        if how == 'changed':
            result.write_bytes(b'{"fixture": "rewritten after acceptance"}')
        elif how == 'missing':
            result.unlink()
        else:
            # The outside file holds the original bytes; containment must still fail.
            outside = self.ws.base / f'outside-{view["study_id"]}.json'
            outside.write_bytes(result.read_bytes())
            result.unlink()
            result.symlink_to(outside)
        return {'changed': 'bytes do not match', 'missing': 'artifact is missing', 'escaped': 'without symlinks'}[how]

    def frozen(self, view):
        status = self.ws.status(view)
        accepted = {p.name: p.read_bytes() for p in self.study_file(view, 'focus-group', 'accepted').iterdir()}
        return status['charged'], status['accepted_results'], accepted

    def test_f20_an_unusable_native_predecessor_stales_its_carried_journey_before_generation(self):
        for how in ('changed', 'missing', 'escaped'):
            with self.subTest(how=how):
                a, cell, good = self.native_return(f'native-before-{how}')
                before = self.frozen(a)
                why = self.break_native_first(a, how)
                validate = ('validate-carry', '--state-root', self.ws.root, '--study', a['study_id'], '--input')
                # Generation: the native first still occupies its slot; its dependent journey is stale.
                mapping = self.carry(a)
                entry = next(e for e in mapping['entries'] if (e['cell_id'], e['stage']) == (cell, 'journey'))
                self.assertEqual(entry['status'], 'stale')
                self.assertIn('predecessor in this revision is unusable', ' '.join(entry['reasons']))
                self.assertIn(why, ' '.join(entry['reasons']))
                self.assertEqual(mapping['filled_slots'], [])
                # A prior (or forged) mapping that claims the journey is rejected.
                out = self.ws.refused('carry_forward_rejected', *validate, self.ws.write(f'prior-{how}.json', good))
                self.assertEqual({e['code'] for e in out['data']['errors']}, {'ineligible_reuse', 'derived_mismatch'})
                forged = dict(good, filled_slots=[f'{cell}:journey'])
                self.ws.refused('carry_forward_rejected', *validate, self.ws.write(f'forged-{how}.json', forged))
                # carry --write records the stale journey; nothing is certified filled.
                written = self.ws.ok('carry', '--state-root', self.ws.root, '--study', a['study_id'], '--write')
                self.assertEqual((written, written['filled_slots']), (mapping, []))
                self.assertEqual(self.ws.ok(*validate, self.ws.write(f'written-{how}.json', written))['carried'], [])
                self.assertTrue(self.ws.check_run(a)['ready'])
                # The broken native result still occupies its slot; no journey launches on it.
                code, out = self.ws.admit(a, f'fi-again-{how}', 'first-impression', cell)
                self.assertEqual((code, out['error']['code']), (1, 'slot_already_filled'))
                code, out = self.ws.admit(a, f'jr-{how}', 'journey', cell)
                self.assertEqual((code, out['error']['code']), (1, 'predecessor_unusable'))
                self.assertEqual(self.frozen(a), before)

    def test_f20_native_predecessor_drift_after_a_written_mapping_refuses_its_consumers(self):
        for how in ('changed', 'missing', 'escaped'):
            with self.subTest(how=how):
                a, cell, good = self.native_return(f'native-after-{how}')
                written = self.ws.ok('carry', '--state-root', self.ws.root, '--study', a['study_id'], '--write')
                self.assertEqual(written, good)
                code, out = self.ws.admit(a, f'jr-{how}', 'journey', cell)
                self.assertEqual((code, out['error']['code']), (1, 'slot_already_filled'))
                other = a['cells'][1]['cell_id']
                self.assertEqual(self.ws.admit(a, f'ofi-{how}-r0', 'first-impression', other)[0], 0)
                before = self.frozen(a)
                self.break_native_first(a, how)
                validate = ('validate-carry', '--state-root', self.ws.root, '--study', a['study_id'], '--input')
                out = self.ws.refused('carry_forward_rejected', *validate, self.ws.write(f'written-{how}.json', written))
                self.assertIn('ineligible_reuse', {e['code'] for e in out['data']['errors']})
                # Every consumer of the written mapping refuses instead of treating the journey as filled.
                self.ws.check_run(a, expect='carry_invalid')
                for stage in ('journey', 'first-impression'):
                    code, out = self.ws.admit(a, f'{stage}-{how}', stage, cell)
                    self.assertEqual((code, out['error']['code']), (1, 'carry_invalid'))
                # record-acceptance revalidates the written mapping before accepting any result.
                code, out = self.accept(a, other, 'first-impression', f'ofi-{how}', admit=False)
                self.assertEqual((code, out['error']['code']), (1, 'carry_invalid'))
                self.ws.refused('carry_invalid', 'job-spec', '--state-root', self.ws.root, '--study', a['study_id'],
                                '--capabilities', self.ws.catalog(), '--installation-id', 'fixture-install', now=BEFORE)
                # The written mapping and accepted records are retained exactly; nothing is reset.
                self.assertEqual(json.loads(self.study_file(a, 'focus-group', 'carry', f"{a['revision']}.json")
                                            .read_text()), written)
                self.assertEqual(self.frozen(a), before)

    # FG1-F19 ----------------------------------------------------------------------------------

    def test_f19_an_admission_replayed_after_a_new_revision_is_never_dispatch_permission(self):
        a = self.ws.approved()
        cell = a['cells'][0]['cell_id']
        old = self.ws.admission(a, 'fi-01-r0', 'first-impression', cell)
        replay = lambda path: self.ws.call('admit', '--state-root', self.ws.root, '--study', a['study_id'], '--input',
                                           path, '--capabilities', self.ws.catalog(), now=BEFORE)
        code, out = replay(old)
        self.assertEqual((code, out['data']['charged']), (0, True), out)
        draft = self.ws.draft()
        draft['personas'][0]['goal'] = 'Decide two weeknight dinners before the school run.'
        b = self.ws.plan(draft)
        self.assertIn(cell, [c['cell_id'] for c in b['cells']])
        self.ws.approve(b)
        code, out = replay(old)
        self.assertEqual((code, out['error']['code']), (1, 'superseded_revision'), out)
        self.assertEqual((out['data']['request_revision'], out['data']['current_revision'], out['data']['charged']),
                         (a['revision'], b['revision'], False))
        status = self.ws.status(b)
        self.assertEqual((status['charged_tasks'], status['open_requests']), (1, ['fi-01-r0']))
        # The current revision keeps idempotent retries; a closed request is never relaunched.
        new = self.ws.admission(b, 'fi-01-b0', 'first-impression', cell)
        self.assertEqual(replay(new)[1]['data']['charged'], True)
        code, out = replay(new)
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False))
        self.ws.release(b, 'fi-01-b0')
        code, out = replay(new)
        self.assertEqual((code, out['error']['code']), (1, 'request_closed'))
        # The old request reconciles through the host lifecycle and still never becomes a launch.
        self.ws.release(a, 'fi-01-r0')
        code, out = replay(old)
        self.assertEqual((code, out['error']['code']), (1, 'superseded_revision'))
        self.assertEqual(self.ws.status(b)['charged_tasks'], 2)



# The class captures these helper methods above; do not collect the imported concrete test class.
del ContractTest


if __name__ == "__main__":
    unittest.main()
