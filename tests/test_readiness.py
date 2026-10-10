"""Source-spec cases 4 and 5, REQ-SNAPSHOT and REQ-ACCEPTANCE label separation."""
import json
import subprocess
import sys

from support import CoreTestCase, cli, git, result_block


class Base(CoreTestCase):
    def verifying_run(self, repo=None, plan_overrides=None, edit=True, state_root=None):
        repo = repo or self.make_repo()
        if state_root:
            self.state_root = state_root
        run = self.init(self.plan(repo, **(plan_overrides or {})))
        run.claim()
        run.record('transition', {'to': 'executing'})
        if edit:
            (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        return repo, run

    def satisfy(self, run, repo):
        self.run_check(run, run.only('run_check'))
        log = run.scratch('accept.log', 'count prints 3')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'reproduction prints 3', 'artifacts': [str(log)]})
        return log

    def validate(self, run):
        code, env, _ = cli('validate', *run.args())
        self.assertEqual(code, 0, env)
        return env['data']


class CompletionGateTest(Base):
    def test_missing_requirement_check_or_review_blocks_completion(self):
        repo, run = self.verifying_run(plan_overrides={'policy': {
            'review': {'required': True, 'role': 'reviewer'},
            'checks': [{'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], 'cwd': '.'}],
            'worktree_root': str(self.tmp / 'wt')}})
        code, env, _ = run.record_raw('transition', {'to': 'ready'})
        self.assertEqual((code, env['error']['code']), (4, 'not_ready'))
        missing = {item['obligation'] for item in env['error']['details']['missing']}
        self.assertEqual(missing, {'requirement:REQ-MULTILINE', 'check:unit', 'review'})
        code, env, _ = run.record_raw('transition', {'to': 'completed'})
        self.assertEqual(code, 4, 'verifying cannot jump to completed')

    def test_failed_requirement_is_failed_not_unverified(self):
        repo, run = self.verifying_run()
        log = run.scratch('red.log', 'prints 2')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'failed', 'kind': 'command',
                                  'explanation': 'still prints 2', 'artifacts': [str(log)]})
        data = self.validate(run)
        self.assertEqual(data['requirements'][0]['status'], 'failed')
        self.assertEqual(data['status'], 'failed')

    def test_wrong_evidence_kind_and_missing_artifacts_rejected(self):
        repo, run = self.verifying_run()
        log = run.scratch('x.log', 'x')
        code, env, _ = run.record_raw('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed',
                                                     'kind': 'inspection', 'explanation': 'looked at it', 'artifacts': [str(log)]})
        self.assertEqual((code, env['error']['code']), (4, 'evidence_kind'))
        code, env, _ = run.record_raw('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed',
                                                     'kind': 'command', 'explanation': 'trust me', 'artifacts': []})
        self.assertEqual((code, env['error']['code']), (4, 'evidence_missing'))


class InvalidationTest(Base):
    def ready_run(self, **kwargs):
        repo, run = self.verifying_run(**kwargs)
        self.satisfy(run, repo)
        self.assertTrue(self.validate(run)['ready'])
        return repo, run

    def test_head_change_invalidates(self):
        repo, run = self.ready_run()
        git(repo, 'commit', '-qam', 'commit the fix')
        data = self.validate(run)
        self.assertEqual(data['status'], 'stale')
        self.assertIn('HEAD changed', data['stale'][0]['reason'])

    def test_same_dirty_file_edited_again_invalidates(self):
        """REQ-SNAPSHOT: porcelain output is identical, content is not."""
        repo, run = self.ready_run()
        porcelain = git(repo, 'status', '--porcelain').stdout
        source = repo / 'wordstat.py'
        source.write_text(source.read_text() + '\n# a second edit to an already-dirty file\n')
        self.assertEqual(git(repo, 'status', '--porcelain').stdout, porcelain)
        data = self.validate(run)
        self.assertFalse(data['ready'])
        self.assertEqual(data['status'], 'stale')
        self.assertIn('working-tree content changed', data['stale'][0]['reason'])

    def test_new_untracked_file_invalidates(self):
        repo, run = self.ready_run()
        (repo / 'scratch.py').write_text('print(1)\n')
        self.assertEqual(self.validate(run)['status'], 'stale')

    def test_state_dir_inside_repo_and_checkbox_edits_do_not_invalidate(self):
        repo = self.make_repo()
        goal = repo / 'GOAL.md'
        goal.write_text('# Goal\n\n## Definition of done\n- [ ] [REQ-MULTILINE] count splits on any whitespace [verify:command]\n'
                        '- [ ] Gates green\n\n## Global constraints\n- Keep the CLI usage text.\n')
        git(repo, 'add', 'GOAL.md')
        git(repo, 'commit', '-qm', 'goal')
        plan = self.plan(repo, brief={'text': 'fix', 'requirements_source': str(goal)})
        plan['brief'].pop('requirements', None)
        plan['brief'].pop('constraints', None)
        self.state_root = repo / '.imps-state'
        run = self.init(plan)
        run.claim()
        run.record('transition', {'to': 'executing'})
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.satisfy(run, repo)
        self.assertTrue(self.validate(run)['ready'])
        (self.state_root / 'runs' / run.run_id / 'scratch' / 'more.log').write_text('state-dir edits are excluded')
        goal.write_text(goal.read_text().replace('- [ ] [REQ-MULTILINE]', '- [x] [REQ-MULTILINE]'))
        self.assertTrue(self.validate(run)['ready'], 'progress checkbox and state-dir edits keep readiness')
        goal.write_text(goal.read_text().replace('any whitespace', 'spaces only'))
        data = self.validate(run)
        self.assertEqual(data['status'], 'stale')
        self.assertIn('requirements or constraints changed', json.dumps(data['stale']))

    def test_policy_change_invalidates(self):
        repo, run = self.ready_run()
        run.record('policy', {'policy': {'brief_notes': 'briefs only'}})
        self.assertTrue(self.validate(run)['ready'], 'non-evidence policy keeps readiness')
        run.record('policy', {'policy': {'review': {'required': False, 'role': 'reviewer', 'waivable': False}}})
        self.assertIn('policy changed', json.dumps(self.validate(run)['stale']))

    def test_artifact_change_invalidates(self):
        repo, run = self.ready_run()
        stored = run.state['acceptance'][-1]['artifacts'][0]['path']
        (run.run_dir / stored).write_text('tampered')
        self.assertIn('artifact hash changed', json.dumps(self.validate(run)['stale']))


class LabelTest(Base):
    def test_labels_stay_distinct_and_waiver_is_not_a_pass(self):
        repo = self.make_repo()
        plan = self.plan(repo)
        plan['brief']['requirements'] = [
            {'id': 'REQ-PASS', 'text': 'passes', 'kind': 'command'},
            {'id': 'REQ-FAIL', 'text': 'fails', 'kind': 'command'},
            {'id': 'REQ-MISSING', 'text': 'never verified', 'kind': 'command'},
            {'id': 'REQ-TOOLS', 'text': 'needs a browser', 'kind': 'runtime'},
            {'id': 'REQ-WAIVED', 'text': 'operator waived', 'kind': 'manual'}]
        repo, run = self.verifying_run(repo=repo, plan_overrides={'brief': plan['brief']})
        log = run.scratch('a.log', 'ok')
        self.run_check(run, run.only('run_check'))
        run.record('acceptance', {'requirement_id': 'REQ-PASS', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})
        run.record('acceptance', {'requirement_id': 'REQ-FAIL', 'status': 'failed', 'kind': 'command',
                                  'explanation': 'no', 'artifacts': [str(log)]})
        run.record('acceptance', {'requirement_id': 'REQ-TOOLS', 'status': 'unavailable', 'kind': 'runtime',
                                  'explanation': 'no browser tool was found'})
        run.record('waiver', {'target': 'requirement:REQ-WAIVED', 'reason': 'out of scope today',
                              'decided_by': 'operator', 'operator_quote': 'skip REQ-WAIVED: out of scope'})
        data = self.validate(run)
        labels = {row['id']: row['status'] for row in data['requirements']}
        self.assertEqual(labels, {'REQ-PASS': 'passed', 'REQ-FAIL': 'failed', 'REQ-MISSING': 'unverified',
                                  'REQ-TOOLS': 'unavailable', 'REQ-WAIVED': 'waived'})
        self.assertEqual(data['counts'], {'passed': 1, 'failed': 1, 'unverified': 1, 'unavailable': 1, 'waived': 1})
        code, env, _ = cli('report', *run.args())
        self.assertEqual(env['data']['report']['readiness']['counts']['passed'], 1)
        self.assertIn('Waived is never counted as passed', (run.run_dir / 'reports' / 'report.md').read_text())

    def test_repository_required_check_cannot_be_waived(self):
        repo = self.make_repo()
        (repo / '.t3-plugins').mkdir()
        (repo / '.t3-plugins' / 'imps.json').write_text(json.dumps({'schema_version': 1, 'policy': {
            'checks': [{'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests']}]}}))
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'policy')
        repo, run = self.verifying_run(repo=repo)
        code, env, _ = run.record_raw('waiver', {'target': 'check:unit', 'reason': 'slow', 'decided_by': 'operator',
                                                 'operator_quote': 'skip unit'})
        self.assertEqual((code, env['error']['code']), (4, 'waiver_forbidden'))
