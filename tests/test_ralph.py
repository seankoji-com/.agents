"""Offline Ralph lifecycle and installed-artifact tests. No live models."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ralph_cli', ROOT / 'plugins/ralph/cli.py')
ralph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ralph)


class RalphTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Resolve macOS /var aliases before the skill installer's symlink checks.
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / 'work tree'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '--allow-empty', '-qm', 'base')
        self.state_path = self.base / 'checkpoints/run.json'
        self.caps = {'runtimeMode': 'auto', 'inheritedProviderInstanceId': 'gateway',
                     'features': {'appOwnedSubagents': True}, 'providers': [
            {'providerInstanceId': 'gateway', 'canRunChildTask': True,
             'runtimeModes': ['approval-required', 'auto'],
             'models': [{'id': 'custom/worker', 'options': [{'id': 'effort', 'type': 'select',
                                                          'options': [{'id': 'high'}]}]},
                        {'id': 'custom/evaluator'}]}]}
        self.init = {'goal': 'Fix the goal', 'brief': 'Only owned files. Verify behavior. Open a normal PR.',
                     'worktree': str(self.repo), 'capabilities': self.caps,
                     'implementer': {'providerInstanceId': 'gateway', 'model': 'custom/worker',
                                     'lineage': 'family-a', 'lineageSource': 'owner-confirmed',
                                     'options': {'effort': 'high'}},
                     'evaluator': {'providerInstanceId': 'gateway', 'model': 'custom/evaluator',
                                   'lineage': 'family-b', 'lineageSource': 'owner-confirmed'}}
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)

    def git(self, *args):
        result = subprocess.run(['git', *args], cwd=self.repo, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def issue(self):
        request = ralph.advance(self.state)['dispatch']
        task_id = f"task-{len(self.state['tasks'])}"
        ralph.attach(self.state, {'clientRequestId': request['clientRequestId'], 'taskId': task_id})
        return request, task_id

    def response(self, task_id, **values):
        record = next(t for t in self.state['tasks'] if t.get('taskId') == task_id)
        chosen = self.state['implementer' if record['role'] == 'implementation' else 'evaluator']
        data = {'taskId': task_id, 'status': 'completed', 'workState': 'result_available',
                'hasPendingChildRuns': False, 'providerInstanceId': chosen['providerInstanceId'],
                'model': chosen['model'], 'summary': 'Verified fixture outcome'}
        if record['role'] == 'review':
            verdict = {'goalAchieved': True, 'feedback': [], 'evidence': ['Fixture inspection'],
                       'revision': ralph.snapshot.token(record['binding'])}
            data['summary'] = self.verdict_summary(verdict)
        return dict(data, **values)

    def verdict_summary(self, verdict):
        return 'Observed result:\n```ralph-evaluation\n' + json.dumps(verdict) + '\n```'

    def implementation(self):
        request, task_id = self.issue()
        ralph.observe(self.state, self.response(task_id))
        self.assertEqual(self.state['phase'], 'evaluate')
        return request, task_id

    def review(self, achieved=True, feedback=None, repair_minor=True):
        request, task_id = self.issue()
        data = self.response(task_id)
        verdict = {'goalAchieved': achieved, 'feedback': feedback or [], 'evidence': ['Fixture inspection'],
                   'revision': ralph.snapshot.token(self.state['tasks'][-1]['binding'])}
        data['summary'] = self.verdict_summary(verdict)
        ralph.observe(self.state, data)
        if self.state['phase'] == 'triage' and repair_minor:
            self.repair_minor(task_id)
        return request, task_id

    def repair_minor(self, task_id):
        ralph.triage(self.state, {'taskId': task_id, 'dispositions': [
            {'feedbackIndex': i, 'disposition': 'repair', 'reason': 'Required fixture correction'}
            for i, item in enumerate(self.state['tasks'][-1]['evaluation']['feedback'])
            if item['severity'] in {'minor', 'info'}]})

    def deferral(self, index=0, **fields):
        return dict({'feedbackIndex': index, 'disposition': 'deferred',
                     'issueUrl': 'https://github.com/fixture/project/issues/12',
                     'reason': 'Optional clarity improvement; supported behavior already passes',
                     'impact': 'Less detailed help text', 'owner': 'Maintainer',
                     'nextAction': 'Expand help examples and check the rendered help',
                     'evidence': 'Fixture issue-create receipt and help inspection'}, **fields)

    def test_two_lineages_can_share_one_gateway_and_custom_models(self):
        self.assertEqual(self.state['maxAttempts'], 20)
        self.assertEqual(self.state['implementer']['model'], 'custom/worker')

    def test_rejects_unknown_same_lineage_and_unavailable_targets(self):
        for change in ({'lineage': ' Family-A '}, {'lineage': 'unknown'},
                       {'model': 'missing'}, {'providerInstanceId': 'missing'}, {'lineageSource': ''}):
            data = copy.deepcopy(self.init)
            data['evaluator'].update(change)
            with self.subTest(change=change), self.assertRaises(ralph.InvalidInput):
                ralph.initialize(data, self.state_path)
        data = copy.deepcopy(self.init)
        data['capabilities']['providers'][0]['canRunChildTask'] = False
        with self.assertRaises(ralph.InvalidInput):
            ralph.initialize(data, self.state_path)

    def test_rejects_state_inside_worktree_and_invalid_limit(self):
        with self.assertRaises(ralph.InvalidInput):
            ralph.initialize(self.init, self.repo / 'state.json')
        for limit in (0, -1, True, 1.5, '5'):
            with self.subTest(limit=limit), self.assertRaises(ralph.InvalidInput):
                ralph.initialize(dict(self.init, maxAttempts=limit), self.state_path)

    def test_uncertain_dispatch_reuses_exact_request_and_attachment_is_idempotent(self):
        first = ralph.advance(self.state)['dispatch']
        self.assertEqual(first, ralph.advance(self.state)['dispatch'])
        self.assertEqual(len(self.state['tasks']), 1)
        data = {'taskId': 't', 'clientRequestId': first['clientRequestId']}
        ralph.attach(self.state, data)
        ralph.attach(self.state, data)
        self.assertEqual(ralph.advance(self.state), {'taskId': 't', 'action': 'task_status'})
        for bad in (dict(data, taskId='other'), dict(data, clientRequestId='other')):
            with self.assertRaises(ralph.InvalidInput):
                ralph.attach(self.state, bad)

    def test_terminal_task_with_pending_runs_and_incomplete_work_state_cannot_advance(self):
        _, task_id = self.issue()
        for values in ({'hasPendingChildRuns': True}, {'workState': 'waiting_for_children'}, {'status': 'running'}):
            ralph.observe(self.state, self.response(task_id, **values))
            self.assertEqual(self.state['phase'], 'implement')
            self.assertEqual(ralph.advance(self.state)['taskId'], task_id)
        ralph.observe(self.state, self.response(task_id))
        self.assertEqual(self.state['phase'], 'evaluate')

    def test_rejected_receipt_does_not_partially_attach(self):
        request = ralph.advance(self.state)['dispatch']
        before = copy.deepcopy(self.state)
        for target in ({'providerInstanceId': 'wrong'}, {'model': 'wrong'},
                       {'providerInstanceId': 'gateway', 'model': 'wrong'}):
            with self.subTest(target=target), self.assertRaises(ralph.InvalidInput):
                ralph.attach(self.state, dict(target, taskId='rejected',
                                             clientRequestId=request['clientRequestId']))
            self.assertEqual(self.state, before)

    def test_cli_retains_null_or_absent_model_task_for_identity_reconciliation(self):
        cli = ROOT / 'plugins/ralph/cli.py'
        for model_fields in ({'model': None}, {}):
            with self.subTest(model_fields=model_fields):
                state_path = self.base / ('null.json' if model_fields else 'absent.json')

                def call(command, data=None, code=0):
                    args = [sys.executable, str(cli), command, '--state', str(state_path)]
                    if data is not None:
                        input_file = self.base / 'receipt-input.json'
                        input_file.write_text(json.dumps(data))
                        args.extend(['--input', str(input_file)])
                    result = subprocess.run(args, cwd=self.base, text=True, capture_output=True)
                    self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                    return json.loads(result.stdout)

                call('init', self.init)
                request = call('next')['dispatch']
                response = dict(model_fields, taskId='unreported', providerInstanceId='gateway',
                                childThreadId='fixture-child', childRunId=None, status='queued',
                                workState='working', hasPendingChildRuns=False, summary=None,
                                waitTimedOut=False)
                attached = call('attach', dict(response, clientRequestId=request['clientRequestId']))['state']
                self.assertEqual(attached['tasks'][-1]['taskId'], response['taskId'])
                self.assertNotIn('receipt', attached['tasks'][-1])
                self.assertEqual(call('next')['action'], 'task_status')
                blocked = call('observe', response)['state']
                self.assertEqual(blocked['blocker']['kind'], 'identity')
                self.assertEqual(blocked['blocker']['taskId'], response['taskId'])
                call('recover', {'reason': 'Cannot waive missing identity'}, code=2)
                verified = call('observe', dict(response, model='custom/worker', status='completed',
                                               workState='result_available', summary='Verified outcome'))['state']
                self.assertEqual(verified['phase'], 'evaluate')
                self.assertTrue(verified['tasks'][-1]['observation']['identityVerified'])

    def test_observation_requires_an_attached_nonempty_task_id_without_mutation(self):
        initial = copy.deepcopy(self.state)
        for role in ('implementation', 'review'):
            self.state = copy.deepcopy(initial)
            if role == 'review':
                self.implementation()
            dispatch = ralph.advance(self.state)['dispatch']
            before = copy.deepcopy(self.state)
            chosen = self.state['implementer' if role == 'implementation' else 'evaluator']
            response = dict(status='completed', workState='result_available', hasPendingChildRuns=False,
                            providerInstanceId=chosen['providerInstanceId'], model=chosen['model'],
                            summary='Verified fixture outcome')
            if role == 'review':
                response['summary'] = self.verdict_summary(dict(goalAchieved=True, feedback=[],
                    evidence=['Fixture inspection'], revision=ralph.snapshot.token(self.state['tasks'][-1]['binding'])))
            for fields in ({}, {'taskId': None}, {'taskId': ''}, {'taskId': ' \t'},
                           {'taskId': False}, {'taskId': []}, {'taskId': 'not-attached'}):
                with self.subTest(role=role, fields=fields), self.assertRaises(ralph.InvalidInput):
                    ralph.observe(self.state, dict(response, **fields))
                self.assertEqual(self.state, before)
                self.assertNotIn('observation', self.state['tasks'][-1])
                self.assertFalse(self.state['tasks'][-1].get('consumed', False))
                self.assertEqual(ralph.advance(self.state)['dispatch'], dispatch)

    def test_cli_rejects_task_id_less_false_success_and_publication_requires_handles(self):
        cli = ROOT / 'plugins/ralph/cli.py'

        def call(command, data=None, code=0):
            args = [sys.executable, str(cli), command, '--state', str(self.state_path)]
            if data is not None:
                input_file = self.base / 'observation-input.json'
                input_file.write_text(json.dumps(data))
                args.extend(['--input', str(input_file)])
            result = subprocess.run(args, cwd=self.base, text=True, capture_output=True)
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
            self.assertEqual(result.stderr, '')
            return json.loads(result.stdout)

        call('init', self.init)
        for role, task_id in (('implementation', 'impl'), ('review', 'eval')):
            dispatch = call('next')['dispatch']
            state = call('status')['state']
            chosen = state['implementer' if role == 'implementation' else 'evaluator']
            response = dict(status='completed', workState='result_available', hasPendingChildRuns=False,
                            providerInstanceId=chosen['providerInstanceId'], model=chosen['model'],
                            summary='Verified fixture outcome')
            if role == 'review':
                response['summary'] = self.verdict_summary(dict(goalAchieved=True, feedback=[],
                    evidence=['Fixture inspection'], revision=ralph.snapshot.token(state['tasks'][-1]['binding'])))
            before = self.state_path.read_bytes()
            for fields in ({}, {'taskId': None}, {'taskId': ' '}):
                with self.subTest(role=role, fields=fields):
                    self.assertFalse(call('observe', dict(response, **fields), code=2)['ok'])
                    self.assertEqual(self.state_path.read_bytes(), before)
                    unchanged = call('status')['state']
                    self.assertNotIn('observation', unchanged['tasks'][-1])
                    self.assertFalse(unchanged['readyForPublication'])
                    self.assertEqual(call('next')['dispatch'], dispatch)
            call('attach', dict(taskId=task_id, clientRequestId=dispatch['clientRequestId']))
            call('observe', dict(response, taskId=task_id))
        self.assertTrue(call('status')['state']['readyForPublication'])
        successful = json.loads(self.state_path.read_text())
        for missing_tasks in ([], successful['tasks'][:1]):
            forged = copy.deepcopy(successful)
            forged['tasks'] = missing_tasks
            self.state_path.write_text(json.dumps(forged))
            self.assertEqual(call('status', code=2)['error']['code'], 'invalid_input')
        for key, value in (('consumed', False), ('stale', True), ('evaluation', None),
                           ('evaluation', dict(successful['tasks'][-1]['evaluation'], goalAchieved=False)),
                           ('evaluation', dict(successful['tasks'][-1]['evaluation'],
                                               feedback=[{'severity': 'info', 'message': 'Still needs work'}])),
                           ('binding', dict(successful['evaluatedRevision'], content_hash='other revision'))):
            forged = copy.deepcopy(successful)
            if value is None:
                forged['tasks'][-1].pop(key)
            else:
                forged['tasks'][-1][key] = value
            self.state_path.write_text(json.dumps(forged))
            self.assertFalse(call('status')['state']['readyForPublication'])
        legacy = copy.deepcopy(successful)
        for task in legacy['tasks']:
            task.pop('taskId')
        self.state_path.write_text(json.dumps(legacy))
        self.assertFalse(call('status')['state']['readyForPublication'])

    def test_feedback_marked_for_repair_retries_original_pair_in_same_tree_with_full_context(self):
        (self.repo / 'previous-work.txt').write_text('keep me')
        original, _ = self.implementation()
        feedback = [{'severity': 'info', 'message': 'Fix this small issue ' + 'x' * 10000},
                    {'severity': 'minor', 'message': 'Also inspect this artifact'}]
        review, _ = self.review(achieved=True, feedback=feedback)
        self.assertEqual(self.state['phase'], 'implement')
        again, _ = self.issue()
        self.assertEqual(again['target'], original['target'])
        self.assertNotEqual(again['clientRequestId'], original['clientRequestId'])
        self.assertNotEqual(again['clientRequestId'], review['clientRequestId'])
        self.assertIn(feedback[0]['message'], again['task'])
        self.assertIn(feedback[1]['message'], again['task'])
        self.assertIn(str(self.repo), again['task'])
        self.assertEqual((self.repo / 'previous-work.txt').read_text(), 'keep me')
        self.assertEqual(again['mode'], 'async')
        self.assertEqual(again['runtimeMode'], 'auto')
        self.assertNotIn('childThreadId', again)

    def test_issue_backed_deferral_finishes_full_review_at_attempt_limit_without_new_round(self):
        self.git('remote', 'add', 'origin', 'git@github.com:fixture/project.git')
        self.state['maxAttempts'] = 1
        self.implementation()
        request, task_id = self.review(feedback=[{'severity': 'info', 'message': 'Expand optional help examples'}],
                                       repair_minor=False)
        original = copy.deepcopy(self.state['tasks'][-1]['evaluation'])
        self.assertIn('final acceptance review', request['task'])
        self.assertEqual(ralph.advance(self.state)['action'], 'triage_feedback')
        self.assertFalse(ralph.publication_verified(self.state))
        ralph.triage(self.state, {'taskId': task_id, 'dispositions': [self.deferral()]})
        self.assertEqual(self.state['phase'], 'evaluated')
        self.assertEqual(self.state['attempt'], 1)
        self.assertEqual(len(self.state['tasks']), 2)
        self.assertEqual(self.state['tasks'][-1]['evaluation'], original)
        self.assertTrue(ralph.publication_verified(self.state))
        ralph.validate_checkpoint(self.state)
        saved = self.base / 'deferred-state.json'
        saved.write_text(json.dumps(self.state))
        result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'), 'status',
                                 '--state', str(saved)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['state']['readyForPublication'])

    def test_triage_refuses_missing_issue_borrowed_issue_duplicate_and_major_dispositions(self):
        self.git('remote', 'add', 'origin', 'https://github.com/fixture/project.git')
        self.implementation()
        _, task_id = self.review(feedback=[{'severity': 'minor', 'message': 'Optional wording'},
                                          {'severity': 'major', 'message': 'Supported path crashes'}], repair_minor=False)
        before = copy.deepcopy(self.state)
        for dispositions in ([], [self.deferral(issueUrl='')], [self.deferral(evidence='')],
                             [self.deferral(issueUrl='https://github.com/other/repo/issues/12')],
                             [self.deferral(), self.deferral()], [self.deferral(index=1)],
                             [self.deferral(index=True)]):
            with self.subTest(dispositions=dispositions), self.assertRaises(ralph.InvalidInput):
                ralph.triage(self.state, {'taskId': task_id, 'dispositions': dispositions})
            self.assertEqual(self.state, before)
        ralph.triage(self.state, {'taskId': task_id, 'dispositions': [self.deferral()]})
        self.assertEqual(self.state['phase'], 'implement')
        self.assertEqual(ralph.open_feedback(self.state['tasks'][-1])[0]['severity'], 'major')

    def test_deferral_does_not_clear_false_goal_and_delta_deferral_still_needs_full_review(self):
        self.git('remote', 'add', 'origin', 'https://github.com/fixture/project')
        self.implementation()
        _, task_id = self.review(achieved=False, feedback=[{'severity': 'minor', 'message': 'Optional help'}],
                                 repair_minor=False)
        ralph.triage(self.state, {'taskId': task_id, 'dispositions': [self.deferral()]})
        self.assertEqual(self.state['phase'], 'implement')
        self.implementation()
        self.review(feedback=[{'severity': 'major', 'message': 'Required input fails'}])
        self.implementation()
        _, task_id = self.review(feedback=[{'severity': 'minor', 'message': 'Optional help'}], repair_minor=False)
        self.assertEqual(self.state['tasks'][-1]['scope'], 'delta')
        attempt = self.state['attempt']
        ralph.triage(self.state, {'taskId': task_id, 'dispositions': [self.deferral()]})
        self.assertEqual(self.state['phase'], 'evaluate')
        self.assertEqual(self.state['attempt'], attempt)
        self.assertEqual(ralph.advance(self.state)['dispatch']['role'], 'review')
        self.assertEqual(self.state['tasks'][-1]['scope'], 'full')

    def test_triage_rechecks_revision_and_pending_tasks_before_accepting_deferrals(self):
        self.git('remote', 'add', 'origin', 'https://github.com/fixture/project.git')
        self.implementation()
        _, task_id = self.review(feedback=[{'severity': 'minor', 'message': 'Optional help'}], repair_minor=False)
        self.state['tasks'][0]['observation']['hasPendingChildRuns'] = True
        with self.assertRaises(ralph.InvalidInput):
            ralph.triage(self.state, {'taskId': task_id, 'dispositions': [self.deferral()]})
        self.state['tasks'][0]['observation']['hasPendingChildRuns'] = False
        (self.repo / 'changed.txt').write_text('changed after review')
        ralph.triage(self.state, {'taskId': task_id, 'dispositions': [self.deferral()]})
        self.assertEqual(self.state['phase'], 'evaluate')
        self.assertTrue(self.state['tasks'][-1]['stale'])
        self.assertNotIn('feedbackDispositions', self.state['tasks'][-1])

    def test_briefs_carry_every_verdict_but_only_the_latest_implementation_summary(self):
        self.state['maxAttempts'] = 8
        for attempt in range(1, 8):
            _, task_id = self.issue()
            ralph.observe(self.state, self.response(task_id, summary=f'Implementation summary {attempt} ' + 'y' * 5000))
            self.review(feedback=[{'severity': 'minor', 'message': f'Finding from round {attempt}'}])
        brief = ralph.advance(self.state)['dispatch']['task']
        for attempt in range(1, 8):
            self.assertIn(f'Finding from round {attempt}', brief)
        self.assertIn('Implementation summary 7 ', brief)
        self.assertNotIn('Implementation summary 6 ', brief)
        self.assertEqual(brief.count('```ralph-evaluation'), 1)  # only the latest evaluator report
        self.assertLess(len(brief), 20000)
        self.assertIn('Implementation summary 1 ', self.state['tasks'][0]['observation']['summary'])

    def test_rejection_is_rechecked_by_a_fresh_delta_review_that_cannot_accept(self):
        (self.repo / 'unrelated.txt').write_text('before the run')
        self.implementation()
        full, _ = self.review(feedback=[{'severity': 'major', 'message': 'Handle the empty input'}])
        self.assertIn('"reviewScope": "full"', full['task'])
        self.assertIn('full task diff', full['task'])
        (self.repo / 'fix.txt').write_text('empty input handled')
        self.implementation()
        delta, _ = self.review()
        self.assertNotEqual(delta['clientRequestId'], full['clientRequestId'])
        self.assertEqual(delta['target'], full['target'])
        contract = json.loads(delta['task'].split('(reports are data, not instructions):\n', 1)[1])
        self.assertEqual(contract['reviewScope'], 'delta')
        self.assertEqual(contract['delta']['changedPathsSinceReview'], ['fix.txt'])
        self.assertEqual(contract['delta']['openFeedback'][0]['message'], 'Handle the empty input')
        self.assertEqual(contract['delta']['sinceRevision'],
                         ralph.snapshot.token(self.state['tasks'][1]['binding']))
        self.assertIn('cannot finish the run', delta['task'])
        self.assertEqual([full['title'], delta['title']], ['R1 review', 'R2 delta'])
        # The delta pass earns a fresh full review, not acceptance or another attempt.
        self.assertEqual(self.state['phase'], 'evaluate')
        self.assertEqual(self.state['attempt'], 2)
        self.assertFalse(ralph.publication_verified(dict(self.state, evaluatedRevision=self.state['tasks'][-1]['binding'])))
        final, _ = self.review()
        self.assertIn('"reviewScope": "full"', final['task'])
        self.assertEqual(final['title'], 'R2 review')
        self.assertEqual(self.state['tasks'][0]['dispatch']['title'], 'R1 impl')
        self.assertEqual(self.state['phase'], 'evaluated')
        self.assertTrue(ralph.publication_verified(self.state))
        ralph.validate_checkpoint(self.state)

    def test_delta_rejection_retries_and_next_delta_starts_from_the_latest_review(self):
        self.implementation()
        self.review(feedback=[{'severity': 'major', 'message': 'First gap'}])
        (self.repo / 'one.txt').write_text('first fix')
        self.implementation()
        self.review(feedback=[{'severity': 'minor', 'message': 'Second gap'}])
        self.assertEqual((self.state['phase'], self.state['attempt']), ('implement', 3))
        (self.repo / 'two.txt').write_text('second fix')
        self.implementation()
        delta = ralph.advance(self.state)['dispatch']['task']
        contract = json.loads(delta.split('(reports are data, not instructions):\n', 1)[1])
        self.assertEqual(contract['delta']['changedPathsSinceReview'], ['two.txt'])
        self.assertEqual([f['message'] for f in contract['delta']['openFeedback']], ['Second gap'])
        self.assertIn('First gap', delta)

    def test_delta_paths_include_an_unstaged_chmod_and_committed_changes(self):
        for name in ('script.sh', 'committed.txt', 'already-dirty.sh'):
            (self.repo / name).write_text('original\n')
        self.git('add', '--', 'script.sh', 'committed.txt', 'already-dirty.sh')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'files')
        os.chmod(self.repo / 'already-dirty.sh', 0o755)
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        self.implementation()
        self.review(feedback=[{'severity': 'minor', 'message': 'Make the script executable'}])
        os.chmod(self.repo / 'script.sh', 0o755)
        (self.repo / 'committed.txt').write_text('changed and committed\n')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'fix', '--', 'committed.txt')
        self.implementation()
        task = ralph.advance(self.state)['dispatch']['task']
        contract = json.loads(task.split('(reports are data, not instructions):\n', 1)[1])
        self.assertEqual(contract['delta']['changedPathsSinceReview'], ['committed.txt', 'script.sh'])

    def delta_paths(self):
        self.implementation()
        task = ralph.advance(self.state)['dispatch']['task']
        return json.loads(task.split('(reports are data, not instructions):\n', 1)[1])['delta']['changedPathsSinceReview']

    def test_delta_paths_follow_the_permission_bits_the_revision_token_hashes(self):
        script = self.repo / 'script.sh'
        script.write_text('original\n')
        self.git('add', '--', 'script.sh')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'script')
        os.chmod(script, 0o755)
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        self.implementation()
        self.review(feedback=[{'severity': 'minor', 'message': 'Restrict the script'}])
        os.chmod(script, 0o744)  # Git still records 100755; the revision token still moves.
        self.assertEqual(self.delta_paths(), ['script.sh'])
        # With core.fileMode=false Git ignores the chmod and the revision does not move either.
        self.git('config', 'core.fileMode', 'false')
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        self.implementation()
        self.review(feedback=[{'severity': 'minor', 'message': 'Gap'}])
        before = ralph.snapshot.token(ralph.snapshot.take(self.repo))
        os.chmod(script, 0o644)
        self.assertEqual(ralph.snapshot.token(ralph.snapshot.take(self.repo)), before)
        self.assertEqual(self.delta_paths(), [])

    def test_unchanged_tree_still_gets_a_delta_review_of_the_implementer_reasoning(self):
        self.implementation()
        self.review(feedback=[{'severity': 'info', 'message': 'Possibly wrong'}])
        _, task_id = self.issue()
        ralph.observe(self.state, self.response(task_id, summary='Left unchanged: the finding is incorrect because X'))
        task = ralph.advance(self.state)['dispatch']['task']
        contract = json.loads(task.split('(reports are data, not instructions):\n', 1)[1])
        self.assertEqual(contract['reviewScope'], 'delta')
        self.assertEqual(contract['delta']['changedPathsSinceReview'], [])
        self.assertEqual(contract['latestImplementationSummary'], 'Left unchanged: the finding is incorrect because X')

    def test_full_review_after_failure_without_feedback_drift_or_older_records(self):
        self.implementation()
        self.review(achieved=False)
        self.implementation()
        self.assertIn('"reviewScope": "full"', ralph.advance(self.state)['dispatch']['task'])
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        self.implementation()
        self.review(feedback=[{'severity': 'minor', 'message': 'Gap'}])
        self.state['tasks'][-1].pop('reviewBaseline')  # a review recorded before scoped re-review
        self.implementation()
        self.assertIn('"reviewScope": "full"', ralph.advance(self.state)['dispatch']['task'])
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        self.implementation()
        self.review()
        (self.repo / 'late.txt').write_text('edited after acceptance')
        self.assertIn('"reviewScope": "full"', ralph.advance(self.state)['dispatch']['task'])

    def test_invalidated_or_malformed_latest_review_forces_a_full_review(self):
        self.implementation()
        self.review(feedback=[{'severity': 'major', 'message': 'Earlier rejection'}])
        self.implementation()
        _, task_id = self.issue()
        (self.repo / 'drift.txt').write_text('changed during the delta review')
        ralph.observe(self.state, self.response(task_id))
        self.assertTrue(self.state['tasks'][-1]['stale'])
        self.assertIn('"reviewScope": "full"', ralph.advance(self.state)['dispatch']['task'])
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        self.implementation()
        self.review(feedback=[{'severity': 'major', 'message': 'Earlier rejection'}])
        self.implementation()
        _, task_id = self.issue()
        ralph.observe(self.state, self.response(task_id, summary='No verdict block'))
        ralph.recover(self.state, {'reason': 'Evaluator format fixed'})
        recovered = ralph.advance(self.state)['dispatch']['task']
        self.assertIn('"reviewScope": "full"', recovered)
        self.assertIn('Evaluator format fixed', recovered)

    def test_briefs_keep_failure_diagnostics_and_the_latest_evaluator_report(self):
        _, task_id = self.issue()
        ralph.observe(self.state, self.response(task_id, status='failed', summary='error: cannot compile parser.c:12'))
        ralph.recover(self.state, {'reason': 'Installed the missing compiler'})
        self.implementation()
        _, task_id = self.issue()
        verdict = {'goalAchieved': False, 'feedback': [{'severity': 'major', 'message': 'Fix the failure above'}],
                   'evidence': ['Ran the suite'], 'revision': ralph.snapshot.token(self.state['tasks'][-1]['binding'])}
        ralph.observe(self.state, self.response(task_id, summary='parser.c:40 crashes on empty input\n'
                                                + self.verdict_summary(verdict)))
        brief = ralph.advance(self.state)['dispatch']['task']
        for text in ('cannot compile parser.c:12', 'Installed the missing compiler', 'parser.c:40 crashes'):
            self.assertIn(text, brief)

    def test_cli_upgrades_a_format_2_checkpoint_and_marks_its_reviews_full(self):
        self.implementation()
        self.review(feedback=[{'severity': 'minor', 'message': 'Gap'}])
        legacy = copy.deepcopy(self.state)
        legacy['schemaVersion'] = 2
        for task in legacy['tasks']:
            task.pop('scope', None)
            task.pop('reviewBaseline', None)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(legacy))

        def call(command):
            result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'), command,
                                     '--state', str(self.state_path)], cwd=self.base, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)

        self.assertEqual(call('status')['state']['schemaVersion'], 3)
        self.assertEqual(json.loads(self.state_path.read_text())['schemaVersion'], 2)  # status never writes
        self.assertEqual(call('next')['dispatch']['role'], 'implementation')
        saved = json.loads(self.state_path.read_text())
        self.assertEqual(saved['schemaVersion'], 3)
        self.assertEqual(saved['tasks'][1]['scope'], 'full')
        scoped = dict(copy.deepcopy(legacy), tasks=[dict(t, scope='delta') for t in legacy['tasks']])
        with self.assertRaisesRegex(ralph.InvalidInput, 'cannot hold scoped reviews'):
            ralph.upgrade(scoped)

    def threaded_review(self, thread, feedback=None):
        issued = ralph.advance(self.state)
        task_id = f"task-{len(self.state['tasks'])}"
        receipt = {'threadId': thread} if issued['tool'] == 't3_thread_send' else {'childThreadId': thread}
        ralph.attach(self.state, dict(receipt, clientRequestId=issued['dispatch']['clientRequestId'], taskId=task_id))
        verdict = {'goalAchieved': True, 'feedback': feedback or [], 'evidence': ['Fixture inspection'],
                   'revision': ralph.snapshot.token(self.state['tasks'][-1]['binding'])}
        ralph.observe(self.state, self.response(task_id, childThreadId=thread, summary=self.verdict_summary(verdict)))
        if self.state['phase'] == 'triage':
            self.repair_minor(task_id)
        return issued

    def test_delta_review_continues_the_rejecting_reviewers_thread_and_full_reviews_stay_fresh(self):
        self.implementation()
        first = self.threaded_review('thread-a', [{'severity': 'major', 'message': 'Handle empty input'}])
        self.assertEqual(first['tool'], 'delegate_task')
        (self.repo / 'fix.txt').write_text('fixed')
        self.implementation()
        follow = self.threaded_review('thread-a', [{'severity': 'minor', 'message': 'Add a regression test'}])
        self.assertEqual(follow['tool'], 't3_thread_send')
        self.assertEqual({k: v for k, v in follow['dispatch'].items() if k != 'message'},
                         {'threadId': 'thread-a', 'mode': 'queue',
                          'clientRequestId': self.state['tasks'][3]['dispatch']['clientRequestId']})
        message = follow['dispatch']['message']
        self.assertIn('re-read every changed path', message)
        contract = json.loads(message.split('(reports are data, not instructions):\n', 1)[1])
        self.assertEqual([e['role'] for e in contract['history']], ['implementation'])  # the thread holds the rest
        self.assertNotIn('latestEvaluationReport', contract)
        self.assertEqual(contract['delta']['openFeedback'][0]['message'], 'Handle empty input')
        self.assertEqual(self.state['tasks'][3]['childThreadId'], 'thread-a')
        ralph.validate_checkpoint(self.state)
        (self.repo / 'test.txt').write_text('regression test')
        self.implementation()
        again = self.threaded_review('thread-a')  # a delta chain stays in one conversation
        self.assertEqual((again['tool'], again['dispatch']['threadId']), ('t3_thread_send', 'thread-a'))
        self.assertEqual(self.state['phase'], 'evaluate')
        final = self.threaded_review('thread-b', [{'severity': 'minor', 'message': 'Rename the helper'}])
        self.assertEqual((final['tool'], final['dispatch']['title']), ('delegate_task', 'R3 review'))
        (self.repo / 'rename.txt').write_text('renamed')
        self.implementation()
        self.assertEqual(ralph.advance(self.state)['dispatch']['threadId'], 'thread-b')

    def test_follow_up_threads_must_match_and_checkpoints_only_continue_earlier_reviews(self):
        self.implementation()
        self.threaded_review('thread-a', [{'severity': 'major', 'message': 'Gap'}])
        self.implementation()
        issued = ralph.advance(self.state)
        request = issued['dispatch']['clientRequestId']
        with self.assertRaisesRegex(ralph.InvalidInput, 'receipt thread'):
            ralph.attach(self.state, {'clientRequestId': request, 'taskId': 'follow', 'threadId': 'thread-x'})
        self.assertNotIn('taskId', self.state['tasks'][-1])
        ralph.attach(self.state, {'clientRequestId': request, 'taskId': 'follow', 'threadId': 'thread-a'})
        with self.assertRaisesRegex(ralph.InvalidInput, 'status thread'):
            ralph.observe(self.state, self.response('follow', childThreadId='thread-x'))
        for bad in ({'threadId': 'thread-x'}, {'mode': 'steer'}):
            with self.subTest(bad=bad):
                state = copy.deepcopy(self.state)
                state['tasks'][-1]['dispatch'].update(bad)
                with self.assertRaisesRegex(ralph.InvalidInput, 'earlier review thread'):
                    ralph.validate_checkpoint(state)
        state = copy.deepcopy(self.state)
        state['tasks'][-1]['scope'] = 'full'
        with self.assertRaisesRegex(ralph.InvalidInput, 'earlier review thread'):
            ralph.validate_checkpoint(state)

    def test_a_relabelled_continuation_can_never_be_the_accepting_review(self):
        self.implementation()
        self.threaded_review('thread-a', [{'severity': 'major', 'message': 'Gap'}])
        self.implementation()
        self.threaded_review('thread-a')
        record = self.state['tasks'][-1]
        self.assertEqual((record['tool'], record['consumed'], self.state['phase']), ('t3_thread_send', True, 'evaluate'))
        forged = copy.deepcopy(self.state)
        forged['tasks'][-1]['scope'] = 'full'
        forged.update(phase='evaluated', evaluatedRevision=record['binding'])
        for label in (None, 'delegate_task', 't3_thread_send'):
            with self.subTest(tool=label):
                attempt = copy.deepcopy(forged)
                attempt['tasks'][-1].pop('tool')
                if label:
                    attempt['tasks'][-1]['tool'] = label
                with self.assertRaises(ralph.InvalidInput):
                    ralph.validate_checkpoint(attempt)
                self.assertFalse(ralph.publication_verified(attempt))

    def test_checkpoint_cannot_claim_acceptance_from_a_delta_review(self):
        self.implementation()
        self.review(feedback=[{'severity': 'minor', 'message': 'Gap'}])
        self.implementation()
        self.review()
        forged = dict(copy.deepcopy(self.state), phase='evaluated', evaluatedRevision=self.state['tasks'][-1]['binding'])
        with self.assertRaisesRegex(ralph.InvalidInput, 'final full review'):
            ralph.validate_checkpoint(forged)
        missing = copy.deepcopy(self.state)
        missing['tasks'][-1].pop('scope')
        with self.assertRaisesRegex(ralph.InvalidInput, 'review scope'):
            ralph.validate_checkpoint(missing)
        baseline = self.state['tasks'][-1]['reviewBaseline']
        for bad in ({'scope': 'partial'}, {'reviewBaseline': 'head'},
                    {'reviewBaseline': dict(baseline, index=None)},
                    {'reviewBaseline': dict(baseline, dirty={'a': 1})},
                    {'reviewBaseline': dict(baseline, head=3)},
                    {'reviewBaseline': {k: v for k, v in baseline.items() if k != 'modes'}}):
            with self.subTest(bad=bad):
                state = copy.deepcopy(self.state)
                state['tasks'][-1].update(bad)
                with self.assertRaises(ralph.InvalidInput):
                    ralph.validate_checkpoint(state)

    def test_unachieved_goal_without_feedback_retries(self):
        self.implementation()
        self.review(achieved=False)
        self.assertEqual(self.state['phase'], 'implement')
        self.assertEqual(self.state['attempt'], 2)
        self.assertIn('"goalAchieved": false', ralph.advance(self.state)['dispatch']['task'])

    def test_limit_exhaustion_retains_feedback_and_blocks_dispatch(self):
        self.state['maxAttempts'] = 1
        self.implementation()
        self.review(feedback=[{'severity': 'major', 'message': 'Missing requirement'}])
        self.assertEqual(self.state['phase'], 'exhausted')
        self.assertEqual(ralph.advance(self.state), {'phase': 'exhausted'})
        self.assertEqual(self.state['tasks'][-1]['evaluation']['feedback'][0]['message'], 'Missing requirement')

    def test_only_true_without_feedback_is_evaluated(self):
        self.implementation()
        self.review()
        self.assertEqual(self.state['phase'], 'evaluated')
        self.assertEqual(ralph.advance(self.state), {'phase': 'evaluated'})

    def test_malformed_or_wrong_revision_verdict_never_passes(self):
        self.implementation()
        _, task_id = self.issue()
        good = self.response(task_id)
        issued = copy.deepcopy(self.state)
        for patch in ({'goalAchieved': 'true'}, {'feedback': ''}, {'evidence': []}, {'revision': 'old'},
                      {'feedback': [{'severity': 'minor', 'message': ''}]}):
            data = copy.deepcopy(good)
            verdict = {'goalAchieved': True, 'feedback': [], 'evidence': ['Fixture inspection'],
                       'revision': ralph.snapshot.token(self.state['tasks'][-1]['binding'])}
            verdict.update(patch)
            data['summary'] = self.verdict_summary(verdict)
            with self.subTest(patch=patch):
                self.state = copy.deepcopy(issued)
                ralph.observe(self.state, data)
                self.assertEqual(self.state['phase'], 'blocked')
                self.assertEqual(self.state['blocker']['kind'], 'invalid_evaluation')
                self.assertTrue(self.state['tasks'][-1]['consumed'])
                self.assertEqual(ralph.advance(self.state)['phase'], 'blocked')
                ralph.recover(self.state, {'reason': 'Formatting cause addressed; request a fresh verdict'})
                fresh = ralph.advance(self.state)['dispatch']
                self.assertNotEqual(fresh['clientRequestId'], issued['tasks'][-1]['dispatch']['clientRequestId'])
                self.assertEqual(fresh['target'], issued['tasks'][-1]['dispatch']['target'])
                self.assertIn(self.state['tasks'][-2]['evaluationGap'], fresh['task'])

    def test_tree_changes_during_or_after_evaluation_need_new_request(self):
        self.implementation()
        request, task_id = self.issue()
        (self.repo / 'changed').write_text('new bytes')
        ralph.observe(self.state, self.response(task_id))
        self.assertEqual(self.state['phase'], 'evaluate')
        invalidated = self.state['tasks'][-1]
        self.assertTrue(invalidated['stale'])
        self.assertEqual(invalidated['invalidation']['issuedRevision'],
                         ralph.snapshot.token(invalidated['binding']))
        self.assertEqual(invalidated['invalidation']['observedRevision'],
                         ralph.snapshot.token(ralph.snapshot.take(self.repo)))
        fresh, task_id = self.issue()
        self.assertNotEqual(request['clientRequestId'], fresh['clientRequestId'])
        self.assertIn(json.dumps(invalidated['invalidation']['reason']), fresh['task'])
        self.assertIn(invalidated['invalidation']['observedRevision'], fresh['task'])
        ralph.observe(self.state, self.response(task_id))
        self.assertEqual(self.state['phase'], 'evaluated')
        (self.repo / 'changed').write_text('changed again')
        another = ralph.advance(self.state)['dispatch']
        self.assertEqual(self.state['phase'], 'evaluate')
        self.assertNotEqual(another['clientRequestId'], fresh['clientRequestId'])
        invalidated = self.state['tasks'][-2]
        self.assertTrue(invalidated['stale'])
        self.assertIn(invalidated['invalidation']['issuedRevision'], another['task'])
        self.assertIn(invalidated['invalidation']['observedRevision'], another['task'])

    def test_raw_summary_is_authoritative_and_ambiguous_results_are_rejected(self):
        self.implementation()
        _, task_id = self.issue()
        good = self.response(task_id)
        issued = copy.deepcopy(self.state)
        for summary in ('No evaluation provided', '```ralph-evaluation\n{broken}\n```',
                        good['summary'] + '\n' + good['summary']):
            with self.subTest(summary=summary):
                self.state = copy.deepcopy(issued)
                ralph.observe(self.state, dict(good, summary=summary,
                                              evaluation={'goalAchieved': True, 'feedback': []}))
                self.assertEqual(self.state['phase'], 'blocked')
                self.assertIn('evaluationGap', self.state['tasks'][-1])

    def test_failed_tasks_block_and_identity_mismatch_is_rejected(self):
        _, task_id = self.issue()
        ralph.observe(self.state, self.response(task_id, model='fallback'))
        self.assertEqual(self.state['blocker']['kind'], 'identity')
        ralph.observe(self.state, self.response(task_id, status='failed', summary='Exact provider failure'))
        self.assertEqual(self.state['phase'], 'blocked')
        self.assertIn('Exact provider failure', self.state['tasks'][-1]['observation']['summary'])
        self.assertEqual(ralph.advance(self.state)['phase'], 'blocked')
        ralph.recover(self.state, {'reason': 'Provider failure resolved'})
        self.assertEqual(self.state['attempt'], 2)
        self.assertIn('dispatch', ralph.advance(self.state))

    def test_empty_terminal_summaries_are_consumed_and_recover_with_fresh_tasks(self):
        initial = copy.deepcopy(self.state)
        for role in ('implementation', 'review'):
            for summary in (None, '', ' \n\t'):
                with self.subTest(role=role, summary=summary):
                    self.state = copy.deepcopy(initial)
                    if role == 'review':
                        self.implementation()
                    request, task_id = self.issue()
                    ralph.observe(self.state, self.response(task_id, summary=summary))
                    self.assertEqual(self.state['phase'], 'blocked')
                    self.assertEqual(self.state['blocker']['kind'], 'invalid_result')
                    self.assertTrue(self.state['tasks'][-1]['consumed'])
                    self.assertEqual(self.state['tasks'][-1]['observation']['summary'], summary)
                    self.assertNotIn('dispatch', ralph.advance(self.state))
                    ralph.recover(self.state, {'reason': 'Missing result cause addressed'})
                    self.assertEqual(self.state['attempt'], 2 if role == 'implementation' else 1)
                    fresh = ralph.advance(self.state)['dispatch']
                    self.assertNotEqual(fresh['clientRequestId'], request['clientRequestId'])
                    self.assertEqual(fresh['target'], request['target'])
                    self.assertEqual(fresh['role'], request['role'])

    def test_cli_concurrent_next_issues_one_stable_dispatch(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(json.dumps(self.state))
        args = [sys.executable, str(ROOT / 'plugins/ralph/cli.py'), 'next', '--state', str(self.state_path)]
        processes = []
        try:
            for _ in range(8):
                processes.append(subprocess.Popen(args, cwd=self.base, text=True,
                                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            requests = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assertEqual(stderr, '')
                response = json.loads(stdout)
                self.assertTrue(response['ok'])
                requests.append(response['dispatch'])
            self.assertTrue(all(request == requests[0] for request in requests))
            state = json.loads(self.state_path.read_text())
            self.assertEqual(len(state['tasks']), 1)
            self.assertEqual(state['tasks'][0]['dispatch'], requests[0])
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)

    def test_cli_zero_task_stop_is_cancelled_without_dispatch(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(json.dumps(self.state))
        for command in ('stop', 'next', 'status'):
            result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                     command, '--state', str(self.state_path)],
                                    cwd=self.base, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            response = json.loads(result.stdout)
            self.assertTrue(response['state']['stopRequested'])
            self.assertEqual(response['state']['phase'], 'cancelled')
            self.assertEqual(response['state']['tasks'], [])
            self.assertNotIn('dispatch', response)
            self.assertFalse(response['state']['readyForPublication'])

    def test_stop_archives_current_blockers_without_re_emitting_them(self):
        initial = copy.deepcopy(self.state)
        for kind in ('identity', 'pending_runs'):
            self.state = copy.deepcopy(initial)
            _, task_id = self.issue()
            if kind == 'pending_runs':
                ralph.observe(self.state, self.response(task_id))
            bad = self.response(task_id, **({'model': 'wrong'} if kind == 'identity'
                                           else {'hasPendingChildRuns': True}))
            ralph.observe(self.state, bad)
            self.assertEqual(self.state['blocker']['kind'], kind)
            blocker = copy.deepcopy(self.state['blocker'])
            ralph.operate(self.state, 'stop', {})
            self.assertNotIn('blocker', self.state)
            self.assertEqual(self.state['stoppedBlocker'], blocker)
            self.assertNotIn('blocker', ralph.advance(self.state))
            ralph.observe(self.state, self.response(task_id))
            self.assertEqual(self.state['phase'], 'cancelled')
            self.assertNotIn('blocker', self.state)
            ralph.operate(self.state, 'stop', {})
            self.assertEqual(self.state['stoppedBlocker'], blocker)

    def test_stop_cannot_be_bypassed_by_late_success_or_uncertain_dispatch(self):
        ralph.advance(self.state)
        ralph.operate(self.state, 'stop', {})
        self.assertEqual(self.state['phase'], 'stopping')
        self.assertNotIn('dispatch', ralph.advance(self.state))
        request = self.state['tasks'][0]['dispatch']
        ralph.attach(self.state, {'clientRequestId': request['clientRequestId'], 'taskId': 'late'})
        ralph.observe(self.state, self.response('late', hasPendingChildRuns=True))
        self.assertEqual(self.state['phase'], 'stopping')
        ralph.observe(self.state, self.response('late'))
        self.assertEqual(self.state['phase'], 'cancelled')
        self.assertNotIn('dispatch', ralph.advance(self.state))

    def test_later_pending_turn_on_old_task_blocks_dispatch(self):
        _, old = self.implementation()
        ralph.observe(self.state, self.response(old, hasPendingChildRuns=True))
        self.assertEqual(self.state['phase'], 'blocked')
        self.assertNotIn('dispatch', ralph.advance(self.state))
        ralph.observe(self.state, self.response(old))
        self.assertEqual(self.state['phase'], 'evaluate')
        self.assertIn('dispatch', ralph.advance(self.state))

    def test_pending_descendants_clear_without_losing_the_evaluated_verdict(self):
        _, impl = self.implementation()
        _, review = self.review()
        binding = self.state['evaluatedRevision']
        for task_id in (impl, review):
            ralph.observe(self.state, self.response(task_id, hasPendingChildRuns=True))
        self.assertEqual(self.state['blocker']['kind'], 'pending_runs')
        ralph.observe(self.state, self.response(impl))
        self.assertEqual(self.state['phase'], 'blocked')
        ralph.observe(self.state, self.response(review))
        self.assertEqual(self.state['phase'], 'evaluated')
        self.assertEqual(self.state['evaluatedRevision'], binding)

    def test_null_model_needs_an_authoritative_receipt_and_mismatch_cannot_be_waived(self):
        request, task_id = self.issue()
        ralph.observe(self.state, self.response(task_id, model=None))
        self.assertEqual(self.state['blocker']['kind'], 'identity')
        self.assertFalse(self.state['tasks'][-1]['observation']['modelReported'])
        with self.assertRaises(ralph.InvalidInput):
            ralph.recover(self.state, {'reason': 'Guess the model'})
        ralph.attach(self.state, {'taskId': task_id, 'clientRequestId': request['clientRequestId'],
                                'providerInstanceId': 'gateway', 'model': 'custom/worker'})
        ralph.observe(self.state, self.response(task_id, model=None))
        self.assertEqual(self.state['phase'], 'evaluate')
        self.assertTrue(self.state['tasks'][-1]['observation']['identityVerified'])
        ralph.observe(self.state, self.response(task_id, model='normalized-or-fallback'))
        self.assertEqual(self.state['blocker']['kind'], 'identity')
        ralph.observe(self.state, self.response(task_id))
        self.assertEqual(self.state['phase'], 'evaluate')

    def test_status_provider_is_required_even_with_an_exact_receipt(self):
        initial = copy.deepcopy(self.state)
        for role in ('implementation', 'review'):
            self.state = copy.deepcopy(initial)
            if role == 'review':
                self.implementation()
            request, task_id = self.issue()
            chosen = self.state['implementer' if role == 'implementation' else 'evaluator']
            ralph.attach(self.state, {'taskId': task_id, 'clientRequestId': request['clientRequestId'],
                                     'providerInstanceId': chosen['providerInstanceId'], 'model': chosen['model']})
            issued = copy.deepcopy(self.state)
            for provider in ('omitted', None, 'different-provider'):
                with self.subTest(role=role, provider=provider):
                    self.state = copy.deepcopy(issued)
                    observation = self.response(task_id)
                    if provider == 'omitted':
                        observation.pop('providerInstanceId')
                    else:
                        observation['providerInstanceId'] = provider
                    ralph.observe(self.state, observation)
                    self.assertEqual(self.state['phase'], 'blocked')
                    self.assertEqual(self.state['blocker']['kind'], 'identity')
                    self.assertFalse(self.state['tasks'][-1]['observation']['identityVerified'])
                    with self.assertRaises(ralph.InvalidInput):
                        ralph.recover(self.state, {'reason': 'Use receipt instead of status provider'})
                    ralph.observe(self.state, self.response(task_id))
                    self.assertEqual(self.state['phase'], 'evaluate' if role == 'implementation' else 'evaluated')

    def test_runtime_modes_are_provider_specific_and_opencode_always_uses_full_access(self):
        data = copy.deepcopy(self.init)
        data['capabilities']['runtimeMode'] = 'full-access'
        state = ralph.initialize(data, self.state_path)
        self.assertEqual(state['evaluator']['runtimeMode'], 'auto')
        self.assertEqual(ralph.advance(state)['dispatch']['runtimeMode'], 'auto')
        data['evaluator']['runtimeMode'] = 'full-access'
        with self.assertRaises(ralph.InvalidInput):
            ralph.initialize(data, self.state_path)
        data['evaluator'].pop('runtimeMode')
        data['capabilities']['providers'][0].pop('runtimeModes')
        self.assertEqual(ralph.initialize(data, self.state_path)['evaluator']['runtimeMode'], 'inherit')
        provider = data['capabilities']['providers'][0]
        provider.update(driverKind='opencode', runtimeModes=['auto', 'full-access'])
        state = ralph.initialize(data, self.state_path)
        self.assertEqual(ralph.advance(state)['dispatch']['runtimeMode'], 'full-access')
        data['capabilities']['runtimeMode'] = 'auto'
        with self.assertRaises(ralph.InvalidInput):
            ralph.initialize(data, self.state_path)

    def test_cross_provider_capability_is_relative_to_the_invoking_provider(self):
        data = copy.deepcopy(self.init)
        data['capabilities']['inheritedProviderInstanceId'] = 'another-parent'
        with self.assertRaises(ralph.InvalidInput):
            ralph.initialize(data, self.state_path)
        data['capabilities']['providers'][0]['canRunCrossProviderChildTask'] = True
        self.assertEqual(ralph.initialize(data, self.state_path)['implementer']['model'], 'custom/worker')

    def test_recorded_opencode_modes_and_older_unadvertised_catalog(self):
        data = copy.deepcopy(self.init)
        recorded = json.loads((ROOT / 'tests/fixtures/t3/ralph-runtime-modes.json').read_text())
        # The capture records modes only; synthetic model choices stay offline.
        opencode = next(p for p in recorded['providers'] if p['driverKind'] == 'opencode')
        opencode['models'] = copy.deepcopy(self.caps['providers'][0]['models'])
        data['capabilities'] = recorded
        for role in ('implementer', 'evaluator'):
            data[role]['providerInstanceId'] = opencode['providerInstanceId']
        state = ralph.initialize(data, self.state_path)
        self.assertEqual(state['implementer']['runtimeMode'], 'full-access')
        self.assertEqual(state['evaluator']['runtimeMode'], 'full-access')
        self.assertEqual(ralph.advance(state)['dispatch']['runtimeMode'], 'full-access')

        older = json.loads((ROOT / 'tests/fixtures/t3/capabilities.json').read_text())
        data['capabilities'] = older
        for role, driver in (('implementer', 'opencode'), ('evaluator', 'codex')):
            provider = next(p for p in older['providers'] if p['driverKind'] == driver)
            data[role].update(providerInstanceId=provider['providerInstanceId'],
                              model=provider['models'][0]['id'], options={})
        with self.assertRaisesRegex(ralph.InvalidInput, 'OpenCode must advertise Full Access support'):
            ralph.initialize(data, self.state_path)

    def test_boolean_options_validate_both_roles_and_reach_dispatch(self):
        initial = copy.deepcopy(self.init)
        for model in initial['capabilities']['providers'][0]['models']:
            model['options'] = [{'id': 'enabled', 'type': 'boolean'}]
        for chosen in (True, False):
            with self.subTest(chosen=chosen):
                data = copy.deepcopy(initial)
                for role in ('implementer', 'evaluator'):
                    data[role]['options'] = {'enabled': chosen}
                self.state = ralph.initialize(data, self.state_path)
                for role in ('implementer', 'evaluator'):
                    self.assertEqual(self.state[role]['options'], {'enabled': chosen})
                dispatch, _ = self.implementation()
                self.assertEqual(dispatch['target']['options'], {'enabled': chosen})
                self.assertEqual(ralph.advance(self.state)['dispatch']['target']['options'], {'enabled': chosen})
        for role in ('implementer', 'evaluator'):
            for selected in ('true', 0, 1, None, [], {}):
                data = copy.deepcopy(initial)
                for target in ('implementer', 'evaluator'):
                    data[target]['options'] = {'enabled': True}
                data[role]['options'] = {'enabled': selected}
                with self.subTest(role=role, selected=selected), self.assertRaises(ralph.InvalidInput):
                    ralph.initialize(data, self.state_path)

    def test_recorded_live_model_options_validate_selection_and_dispatch(self):
        provider = json.loads((ROOT / 'tests/fixtures/t3/ralph-model-options.json').read_text())
        provider.pop('_comment')
        data = copy.deepcopy(self.init)
        data['capabilities'].update(runtimeMode='full-access', providers=[provider])
        for role in ('implementer', 'evaluator'):
            data[role].update(providerInstanceId=provider['providerInstanceId'],
                              model=provider['models'][0]['id'], options={'variant': 'medium'})
        self.state = ralph.initialize(data, self.state_path)
        dispatch, _ = self.implementation()
        self.assertEqual(dispatch['target']['options'], {'variant': 'medium'})
        self.assertEqual(ralph.advance(self.state)['dispatch']['target']['options'], {'variant': 'medium'})
        for role in ('implementer', 'evaluator'):
            for options in ({'variant': 'xhigh'}, {'variant': True}, {'agent': 'build'}):
                invalid = copy.deepcopy(data)
                invalid[role]['options'] = options
                with self.subTest(role=role, options=options), self.assertRaises(ralph.InvalidInput):
                    ralph.initialize(invalid, self.state_path)

    def test_invalid_model_options_are_rejected_before_dispatch(self):
        for options in ({'missing': 'x'}, {'effort': 'invented'}, {'effort': True},
                        [], False, 0, 'high', [{'id': 'effort', 'value': 'high'}]):
            data = copy.deepcopy(self.init)
            data['implementer']['options'] = options
            with self.subTest(options=options), self.assertRaises(ralph.InvalidInput):
                ralph.initialize(data, self.state_path)

    def test_null_options_mean_no_overrides_for_both_targets(self):
        data = copy.deepcopy(self.init)
        for role in ('implementer', 'evaluator'):
            data[role]['options'] = None
        self.state = ralph.initialize(data, self.state_path)
        self.assertEqual(self.state['implementer']['options'], {})
        self.assertEqual(self.state['evaluator']['options'], {})
        request, _ = self.implementation()
        self.assertEqual(request['target']['options'], {})
        self.assertEqual(ralph.advance(self.state)['dispatch']['target']['options'], {})

    def test_cli_malformed_capabilities_return_json_errors_without_checkpoint(self):
        variations = []
        for key, value in (('providers', [None]), ('providers', ['provider']),
                           ('features', None), ('features', []), ('features', 'features')):
            caps = copy.deepcopy(self.caps)
            caps[key] = value
            variations.append(caps)
        for key, value in (('models', [None]), ('models', {})):
            caps = copy.deepcopy(self.caps)
            caps['providers'][0][key] = value
            variations.append(caps)
        for value in ([None], {}):
            caps = copy.deepcopy(self.caps)
            caps['providers'][0]['models'][0]['options'] = value
            variations.append(caps)
        caps = copy.deepcopy(self.caps)
        caps['providers'][0]['models'][0]['options'][0]['options'] = [None]
        variations.append(caps)
        for caps in variations:
            with self.subTest(capabilities=caps):
                input_file = self.base / 'invalid-init.json'
                input_file.write_text(json.dumps(dict(self.init, capabilities=caps)))
                result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                         'init', '--state', str(self.state_path), '--input', str(input_file)],
                                        cwd=self.base, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                envelope = json.loads(result.stdout)
                self.assertFalse(envelope['ok'])
                self.assertEqual(envelope['error']['code'], 'invalid_input')
                self.assertEqual(result.stderr, '')
                self.assertFalse(self.state_path.exists())

    def test_failed_implementation_recovery_cannot_exceed_the_attempt_limit(self):
        self.state['maxAttempts'] = 1
        _, task_id = self.issue()
        ralph.observe(self.state, self.response(task_id, status='failed'))
        ralph.recover(self.state, {'reason': 'Cause resolved'})
        self.assertEqual(self.state['phase'], 'exhausted')
        self.assertNotIn('dispatch', ralph.advance(self.state))

    def test_cli_io_failure_classes_and_missing_input(self):
        input_path = self.base / 'input.json'
        input_path.write_text(json.dumps(self.init))
        blocked_parent = self.base / 'parent-is-file'
        blocked_parent.write_text('owned fixture')
        cases = [(blocked_parent / 'state.json', input_path, 5, 'io_error'),
                 (self.state_path, self.base / 'missing.json', 2, 'missing_input'),
                 (self.state_path, self.base, 2, 'missing_input')]
        if os.geteuid() != 0:
            readonly = self.base / 'readonly'
            readonly.mkdir(mode=0o500)
            self.addCleanup(readonly.chmod, 0o700)
            cases.append((readonly / 'nested/state.json', input_path, 5, 'io_error'))
        for state_path, source, exit_code, error_code in cases:
            with self.subTest(state=state_path, source=source):
                result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                         'init', '--state', str(state_path), '--input', str(source)],
                                        cwd=self.base, text=True, capture_output=True)
                self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
                self.assertEqual(result.stderr, '')
                envelope = json.loads(result.stdout)
                self.assertFalse(envelope['ok'])
                self.assertEqual(envelope['error']['code'], error_code)
                self.assertFalse(state_path.exists())
        self.assertEqual(blocked_parent.read_text(), 'owned fixture')

    def test_cli_malformed_checkpoint_fields_return_json_without_mutation(self):
        self.implementation()
        self.issue()
        cases = [('baseline', value) for value in (None, 'x', [], 5)]
        cases += [('tasks', value) for value in ({}, None, [None])]
        cases += [(key, None) for key in ('implementer', 'evaluator', 'blocker', 'evaluatedRevision')]
        for key, value in cases:
            for command in ('status', 'next'):
                with self.subTest(key=key, value=value, command=command):
                    state = copy.deepcopy(self.state)
                    state[key] = value
                    self.state_path.parent.mkdir(parents=True, exist_ok=True)
                    self.state_path.write_text(json.dumps(state))
                    before = self.state_path.read_bytes()
                    result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                             command, '--state', str(self.state_path)],
                                            cwd=self.base, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, '')
                    envelope = json.loads(result.stdout)
                    self.assertFalse(envelope['ok'])
                    self.assertEqual(envelope['error']['code'], 'invalid_input')
                    self.assertEqual(self.state_path.read_bytes(), before)

    def test_cli_evaluated_revision_and_recoveries_require_valid_checkpoint_shapes(self):
        self.implementation()
        self.review()
        states = []
        missing = copy.deepcopy(self.state)
        missing.pop('evaluatedRevision')
        states.append(missing)
        for tasks in ([], self.state['tasks'][:1]):
            invalid = copy.deepcopy(self.state)
            invalid['tasks'] = tasks
            states.append(invalid)
        for value in (None, {}, 'x', 1, [None]):
            invalid = copy.deepcopy(self.state)
            invalid['recoveries'] = value
            states.append(invalid)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        (self.repo / 'drift.txt').write_text('changed after evaluation')
        for index, state in enumerate(states):
            for command in ('status', 'next', 'recover'):
                with self.subTest(index=index, command=command):
                    self.state_path.write_text(json.dumps(state))
                    before = self.state_path.read_bytes()
                    result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                             command, '--state', str(self.state_path)],
                                            cwd=self.base, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, '')
                    envelope = json.loads(result.stdout)
                    self.assertFalse(envelope['ok'])
                    self.assertEqual(envelope['error']['code'], 'invalid_input')
                    self.assertEqual(self.state_path.read_bytes(), before)
        # A successful checkpoint without a recovery history remains readable.
        ralph.validate_checkpoint(self.state)
        self.state['recoveries'] = []
        ralph.validate_checkpoint(self.state)

    def test_cli_invalid_phases_and_blocker_fields_return_json_without_mutation(self):
        self.implementation()
        self.issue()
        good = {'kind': 'identity', 'resumePhase': 'evaluate',
                'message': 'Reconcile identity', 'taskId': self.state['tasks'][-1]['taskId']}
        blocked = dict(copy.deepcopy(self.state), phase='blocked', blocker=good)
        ralph.validate_checkpoint(blocked)
        cases = []
        for phase in ('bogus', ' blocked ', '', None, [], {}):
            cases.append(dict(copy.deepcopy(self.state), phase=phase))
        cases.append(dict(copy.deepcopy(self.state), phase='blocked'))
        cases.append(dict(copy.deepcopy(self.state), blocker=good))
        cases.append(dict(copy.deepcopy(blocked), blocker=dict(good, resumePhase='evaluated')))
        cases.append(dict(copy.deepcopy(self.state), stopRequested=True))
        for phase in ('stopping', 'cancelled'):
            cases.append(dict(copy.deepcopy(self.state), phase=phase))
        invalid_blockers = [{}]
        for key in ('kind', 'resumePhase', 'message'):
            missing = dict(good)
            missing.pop(key)
            invalid_blockers.append(missing)
        for key, values in (('kind', ('bogus', None, [], {})),
                            ('resumePhase', ('bogus', '', None, [], {}, 'blocked', 'stopping', 'cancelled')),
                            ('message', ('', None, [])), ('taskId', ('', [], {}))):
            for value in values:
                invalid_blockers.append(dict(good, **{key: value}))
        cases += [dict(copy.deepcopy(blocked), blocker=value) for value in invalid_blockers]
        # Historical copies are validated too; they cannot hide malformed fields.
        cases += [dict(copy.deepcopy(self.state), stoppedBlocker={'kind': 'identity'}),
                  dict(copy.deepcopy(self.state), recoveries=[{}]),
                  dict(copy.deepcopy(self.state), recoveries=[{'reason': 'Resolved', 'blocker': {}}])]
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        for index, state in enumerate(cases):
            for command in ('status', 'next', 'recover'):
                with self.subTest(index=index, command=command):
                    self.state_path.write_text(json.dumps(state))
                    before = self.state_path.read_bytes()
                    result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                             command, '--state', str(self.state_path)],
                                            cwd=self.base, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, '')
                    self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_input')
                    self.assertEqual(self.state_path.read_bytes(), before)
        for kind in ralph.BLOCKER_KINDS:
            for phase in ('implement', 'evaluate', 'evaluated', 'exhausted'):
                valid = dict(copy.deepcopy(blocked), blocker=dict(good, kind=kind, resumePhase=phase))
                if phase == 'evaluated':
                    valid['evaluatedRevision'] = valid['tasks'][-1]['binding']
                ralph.validate_checkpoint(valid)
        history = dict(copy.deepcopy(self.state), stoppedBlocker=good,
                       recoveries=[{'reason': 'Resolved cause', 'blocker': good}])
        ralph.validate_checkpoint(history)

    def test_cli_invalid_observation_shapes_return_json_without_mutation(self):
        _, task_id = self.issue()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state))
        before = self.state_path.read_bytes()
        for field in ('status', 'workState'):
            for value in ([], {}, 1, None, True):
                with self.subTest(field=field, value=value):
                    data = self.response(task_id, **{field: value})
                    source = self.base / 'observation.json'
                    source.write_text(json.dumps(data))
                    result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                             'observe', '--state', str(self.state_path), '--input', str(source)],
                                            cwd=self.base, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, '')
                    self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_input')
                    self.assertEqual(self.state_path.read_bytes(), before)

    def test_cli_malformed_severity_is_consumed_and_recoverable(self):
        self.implementation()
        _, task_id = self.issue()
        issued = copy.deepcopy(self.state)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        source = self.base / 'input.json'

        def call(command, data=None):
            args = [sys.executable, str(ROOT / 'plugins/ralph/cli.py'), command,
                    '--state', str(self.state_path)]
            if data is not None:
                source.write_text(json.dumps(data))
                args += ['--input', str(source)]
            result = subprocess.run(args, cwd=self.base, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr, '')
            return json.loads(result.stdout)

        for severity in ([], {}, ['major'], 1, None):
            with self.subTest(severity=severity):
                self.state_path.write_text(json.dumps(issued))
                verdict = {'goalAchieved': True, 'evidence': ['Fixture inspection'],
                           'revision': ralph.snapshot.token(issued['tasks'][-1]['binding']),
                           'feedback': [{'severity': severity, 'message': 'Repair needed'}]}
                call('observe', self.response(task_id, summary=self.verdict_summary(verdict)))
                saved = json.loads(self.state_path.read_text())
                self.assertEqual(saved['phase'], 'blocked')
                self.assertEqual(saved['blocker']['kind'], 'invalid_evaluation')
                self.assertTrue(saved['tasks'][-1]['consumed'])
                self.assertEqual(call('next')['phase'], 'blocked')
                call('recover', {'reason': 'Malformed severity corrected; request fresh evaluation'})
                fresh = call('next')['dispatch']
                self.assertNotEqual(fresh['clientRequestId'], issued['tasks'][-1]['dispatch']['clientRequestId'])
                self.assertEqual(fresh['target'], issued['tasks'][-1]['dispatch']['target'])

    def test_cli_rejects_malformed_saved_task_fields_without_mutation(self):
        self.implementation()
        self.review()
        cases = []
        for field, values in (
                ('status', ([], {}, None, 'bogus')),
                ('workState', ([], {}, None, 'bogus')),
                ('hasPendingChildRuns', (1, 'false', None)),
                ('identityVerified', (1, 'true', None)),
                ('modelReported', (0, 'false', None))):
            for value in values:
                state = copy.deepcopy(self.state)
                state['tasks'][-1]['observation'][field] = value
                cases.append(state)
        for field in ('stale', 'consumed'):
            for value in (1, 'yes', [], {}, None):
                state = copy.deepcopy(self.state)
                state['tasks'][-1][field] = value
                cases.append(state)
        # A pending dispatch must be safe to replay and attach, even before a handle exists.
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        self.issue()
        for dispatch in ({}, {'clientRequestId': ''}, {'clientRequestId': []},
                         {'clientRequestId': 'issued'}, {'clientRequestId': 'issued', 'target': []}):
            state = copy.deepcopy(self.state)
            state['tasks'][-1]['dispatch'] = dispatch
            cases.append(state)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        source = self.base / 'input.json'
        source.write_text(json.dumps({'clientRequestId': 'issued', 'taskId': 'attached'}))
        for index, state in enumerate(cases):
            for command in ('status', 'next', 'attach'):
                with self.subTest(index=index, command=command):
                    self.state_path.write_text(json.dumps(state))
                    before = self.state_path.read_bytes()
                    result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                             command, '--state', str(self.state_path), '--input', str(source)],
                                            cwd=self.base, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, '')
                    self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_input')
                    self.assertEqual(self.state_path.read_bytes(), before)

    def test_cli_loaded_target_domains_preserve_parent_permission_boundary(self):
        cases = []
        for parent in ('bogus-parent', 'inherit', None, [], {}):
            cases.append(dict(copy.deepcopy(self.state), runtimeMode=parent))
        missing = copy.deepcopy(self.state)
        missing.pop('runtimeMode')
        cases.append(missing)
        for role in ('implementer', 'evaluator'):
            for field, values in (
                    ('runtimeMode', ('bogus', 'full-access', None, [], {})),
                    ('options', ({'effort': {'nested': [1]}}, {'effort': []}, {'effort': 1}, {'effort': None})),
                    ('lineage', ('unknown', ' UNVERIFIED ', 'Inferred'))):
                for value in values:
                    state = copy.deepcopy(self.state)
                    state[role][field] = value
                    cases.append(state)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        for index, state in enumerate(cases):
            for command in ('status', 'next'):
                with self.subTest(index=index, command=command):
                    self.state_path.write_text(json.dumps(state))
                    before = self.state_path.read_bytes()
                    result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                             command, '--state', str(self.state_path)],
                                            cwd=self.base, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, '')
                    self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_input')
                    self.assertEqual(self.state_path.read_bytes(), before)
        for role in ('implementer', 'evaluator'):
            for mode in (*ralph.RUNTIME_MODES, 'inherit'):
                valid = copy.deepcopy(self.state)
                valid['runtimeMode'] = 'full-access'
                valid[role]['runtimeMode'] = mode
                valid[role]['options'] = {'effort': 'high', 'flag': False}
                ralph.validate_checkpoint(valid)
        # Unknown provider modes use host inheritance; loading must retain that pin.
        self.caps['providers'][0].pop('runtimeModes')
        inherited = ralph.initialize(self.init, self.state_path)
        ralph.validate_checkpoint(inherited)
        self.assertEqual(ralph.advance(inherited)['dispatch']['runtimeMode'], 'inherit')

    def assert_checkpoint_rejected_without_mutation(self, state, commands=('status', 'next', 'recover')):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        source = self.base / 'recovery.json'
        source.write_text(json.dumps({'reason': 'Fixture recovery'}))
        for command in commands:
            with self.subTest(command=command):
                self.state_path.write_text(json.dumps(state))
                before = self.state_path.read_bytes()
                result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                         command, '--state', str(self.state_path), '--input', str(source)],
                                        cwd=self.base, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_input')
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_cli_loaded_checkpoint_requires_distinct_verified_lineages(self):
        for phase in ('implement', 'evaluate'):
            if phase == 'evaluate':
                self.implementation()
            for implementer, evaluator in (('family-a', 'family-a'), (' Family-A ', 'family-a'),
                                            ('family-a', ' FAMILY-A ')):
                with self.subTest(phase=phase, implementer=implementer, evaluator=evaluator):
                    state = copy.deepcopy(self.state)
                    state['implementer']['lineage'] = implementer
                    state['evaluator']['lineage'] = evaluator
                    self.assert_checkpoint_rejected_without_mutation(state)
            # Matching case/whitespace normalization still allows distinct verified families.
            valid = copy.deepcopy(self.state)
            valid['implementer']['lineage'] = ' Family-A '
            valid['evaluator']['lineage'] = ' FAMILY-B '
            ralph.validate_checkpoint(valid)
            self.state_path.write_text(json.dumps(valid))
            before = self.state_path.read_bytes()
            result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                     'status', '--state', str(self.state_path)],
                                    cwd=self.base, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])
            self.assertEqual(result.stderr, '')
            self.assertEqual(self.state_path.read_bytes(), before)

    def test_cli_pending_dispatch_replay_requires_the_pinned_role_target_and_mode(self):
        for model in self.caps['providers'][0]['models']:
            model.setdefault('options', []).append({'id': 'enabled', 'type': 'boolean'})
        for role in ('implementer', 'evaluator'):
            self.init[role].setdefault('options', {})['enabled'] = False
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        for role in ('implementation', 'review'):
            request = ralph.advance(self.state)['dispatch']
            self.assertEqual(request['role'], role)
            pending = copy.deepcopy(self.state)
            # Valid uncertain dispatches retain exactly the issued request, including boolean options.
            ralph.validate_checkpoint(pending)
            self.assertEqual(ralph.advance(pending)['dispatch'], request)
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(pending))
            replay = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                     'next', '--state', str(self.state_path)],
                                    cwd=self.base, text=True, capture_output=True)
            self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
            self.assertEqual(json.loads(replay.stdout)['dispatch'], request)
            self.assertEqual(replay.stderr, '')
            task_id = f'task-{len(self.state["tasks"])}'
            ralph.attach(self.state, {'clientRequestId': request['clientRequestId'], 'taskId': task_id})
            # Reconciliation of attached tasks must validate the same pinned request.
            for issued in (pending, self.state):
                changes = [('runtimeMode', 'full-access'), ('runtimeMode', 'inherit'),
                           ('role', 'review' if role == 'implementation' else 'implementation'),
                           ('target', dict(request['target'], model='foreign/model')),
                           ('target', dict(request['target'], providerInstanceId='foreign-provider')),
                           ('target', dict(request['target'], options={'foreign-option': 'high'})),
                           ('target', dict(request['target'], options=dict(request['target']['options'], enabled=0))),
                           ('target', None)]
                for field, value in changes:
                    with self.subTest(role=role, attached='taskId' in issued['tasks'][-1], field=field, value=value):
                        state = copy.deepcopy(issued)
                        state['tasks'][-1]['dispatch'][field] = value
                        self.assert_checkpoint_rejected_without_mutation(state)
            if role == 'implementation':
                ralph.observe(self.state, self.response(task_id))

    def test_cli_usage_errors_have_json_envelopes_and_help_remains_successful(self):
        for args in (['next'], ['unknown'], [], ['status', '--state'], ['next', '--unknown']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'), *args],
                                        cwd=self.base, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)['error']['code'], 'usage')
                self.assertIn('usage:', result.stderr)
                self.assertFalse(self.state_path.exists())
        help_result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'), '--help'],
                                     cwd=self.base, text=True, capture_output=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn('usage:', help_result.stdout)
        self.assertEqual(help_result.stderr, '')

    def test_cli_status_reports_staged_change_with_unchanged_working_bytes(self):
        source = self.repo / 'tracked.txt'
        source.write_text('original\n')
        self.git('add', 'tracked.txt')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'tracked file')
        from tests.adopter_plan_review_fixtures import ralph_admission
        self.init['admission'] = ralph_admission(self.init)
        self.state = ralph.initialize(self.init, self.state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state))
        source.write_text('staged\n')
        self.git('add', 'tracked.txt')
        source.write_text('original\n')
        result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                 'status', '--state', str(self.state_path)],
                                cwd=self.base, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = json.loads(result.stdout)['state']
        self.assertEqual(state['changedPaths'], ['tracked.txt'])
        self.assertTrue(state['hasChanges'])

    def test_cli_unsupported_checkpoint_versions_return_json_without_mutation(self):
        for version in (1, 4, True, '3', None):
            with self.subTest(version=version):
                state = copy.deepcopy(self.state)
                state['schemaVersion'] = version
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                self.state_path.write_text(json.dumps(state))
                before = self.state_path.read_bytes()
                result = subprocess.run([sys.executable, str(ROOT / 'plugins/ralph/cli.py'),
                                         'status', '--state', str(self.state_path)],
                                        cwd=self.base, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stderr, '')
                envelope = json.loads(result.stdout)
                self.assertFalse(envelope['ok'])
                self.assertEqual(envelope['error']['code'], 'invalid_input')
                self.assertIn('unsupported checkpoint version', envelope['error']['message'])
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_cli_persistence_relocation_adapter_and_revision_status(self):
        prefix = self.base / 'package with spaces'
        skills = self.base / 'skills'
        # Isolated home: setup also materializes worker bundles under the default agents root.
        env = {**os.environ, 'HOME': str(self.base / 'home'), 'XDG_CONFIG_HOME': str(self.base / 'config'),
               'XDG_STATE_HOME': str(self.base / 'state')}
        for args in (['setup', 'ralph', '--root', str(skills)], ['doctor', 'ralph']):
            result = subprocess.run([sys.executable, str(ROOT / 'bin/t3-plugins'), '--prefix', str(prefix), *args],
                                    cwd=self.base, text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        adapter = (skills / 't3-ralph/SKILL.md').read_text()
        self.assertIn('name: t3-ralph', adapter)
        self.assertIn(str(prefix / 'ralph/current/entry.md'), adapter)
        self.assertNotIn('imps', adapter)
        self.assertIn('do not switch to another ralph installation', adapter)
        cli = prefix / 'ralph/current/cli.py'

        def call(command, data=None, code=0):
            args = [sys.executable, str(cli), command, '--state', str(self.state_path)]
            if data is not None:
                input_file = self.base / 'input.json'
                input_file.write_text(json.dumps(data))
                args.extend(['--input', str(input_file)])
            result = subprocess.run(args, cwd=self.base, text=True, capture_output=True)
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
            return json.loads(result.stdout)

        (self.repo / 'unrelated-existing.txt').write_text('preserve this earlier work')
        self.git('remote', 'add', 'origin', 'https://github.com/fixture/project.git')
        call('init', self.init)
        self.assertFalse(call('status')['state']['hasChanges'])
        self.assertEqual(call('status')['state']['changedPaths'], [])
        call('init', self.init, code=2)
        first = call('next')['dispatch']
        self.assertEqual(call('next')['dispatch'], first)
        call('attach', {'clientRequestId': first['clientRequestId'], 'taskId': 'impl'})
        self.state = call('status')['state']
        call('observe', self.response('impl'))
        review = call('next')['dispatch']
        call('attach', {'clientRequestId': review['clientRequestId'], 'taskId': 'eval'})
        self.state = call('status')['state']
        response = self.response('eval')
        verdict = {'goalAchieved': True, 'feedback': [{'severity': 'minor', 'message': 'Optional help examples'}],
                   'evidence': ['Fixture inspection'], 'revision': ralph.snapshot.token(self.state['tasks'][-1]['binding'])}
        response['summary'] = self.verdict_summary(verdict)
        self.assertEqual(call('observe', response)['state']['phase'], 'triage')
        call('triage', {'taskId': 'eval', 'dispositions': [self.deferral()]})
        before = self.state_path.read_bytes()
        self.assertTrue(call('status')['state']['readyForPublication'])
        self.assertEqual(self.state_path.read_bytes(), before)
        (self.repo / 'new').write_text('stale')
        changed = call('status')['state']
        self.assertFalse(changed['readyForPublication'])
        self.assertTrue(changed['hasChanges'])
        self.assertEqual(changed['changedPaths'], ['new'])
        self.git('add', '--', 'new')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'Commit owned implementation change')
        committed = call('status')['state']
        self.assertTrue(committed['hasChanges'])
        self.assertEqual(committed['changedPaths'], ['new'])
        self.assertFalse(committed['readyForPublication'])
        self.assertEqual(self.git('status', '--porcelain', '--', 'new'), '')
        reevaluate = call('next')['dispatch']
        self.assertNotEqual(reevaluate['clientRequestId'], review['clientRequestId'])
        call('attach', {'clientRequestId': reevaluate['clientRequestId'], 'taskId': 'malformed'})
        self.state = call('status')['state']
        call('observe', self.response('malformed', summary='Malformed evaluator output'))
        blocked = call('status')['state']
        self.assertEqual(blocked['phase'], 'blocked')
        self.assertEqual(blocked['blocker']['kind'], 'invalid_evaluation')
        self.assertEqual(blocked['tasks'][-1]['observation']['summary'], 'Malformed evaluator output')
        self.assertTrue(blocked['tasks'][-1]['consumed'])
        self.assertFalse(blocked['readyForPublication'])
        call('recover', {'reason': 'Evaluator formatting cause addressed'})
        recovered = call('next')['dispatch']
        self.assertNotEqual(recovered['clientRequestId'], reevaluate['clientRequestId'])
        self.assertEqual(recovered['target'], reevaluate['target'])
        self.assertEqual((self.repo / 'unrelated-existing.txt').read_text(), 'preserve this earlier work')


if __name__ == '__main__':
    unittest.main()
