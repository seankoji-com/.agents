"""Regression tests for the round-1 adversarial review findings
(conformance/review/round-1.md). Each test reproduces the reported failure
scenario and asserts the fixed behaviour."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from support import ROOT, CoreTestCase, FakeT3, capabilities, cli, done, git, native, result_block
from test_bugfix_delegated import DelegatedFlow, commit_all
import test_install
from test_readiness import Base


def edit(repo, text='\n# changed\n'):
    (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text() + text)


class CoreFindingsTest(Base):
    def review_run(self, **policy):
        settings = {'review': {'required': True, 'role': 'reviewer'}, 'checks': [], 'worktree_root': str(self.tmp / 'wt')}
        settings.update(policy)
        repo, run = self.verifying(plan_overrides={'policy': settings})
        log = run.scratch('ok.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})
        return repo, run

    def verifying(self, plan_overrides=None, caps=True):
        repo = self.make_repo()
        run = self.init(self.plan(repo, **(plan_overrides or {})))
        run.claim()
        if caps:
            run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        edit(repo, '')
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        return repo, run

    def test_1_review_is_bound_to_the_revision_it_was_asked_to_read(self):
        repo, run = self.review_run()
        t3 = FakeT3()
        review = run.only('dispatch')
        t3.script(review['host_call']['arguments']['clientRequestId'], done(result_block(review['task_id'], verdict='approve')))
        run.record('dispatch', {'action_id': review['id'], 'response': t3.call(review['host_call'])})
        edit(repo, '\n# change B after the review was dispatched\n')
        log = run.scratch('ok2.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'B verified', 'artifacts': [str(log)]})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        data = self.validate(run)
        self.assertEqual(data['review']['status'], 'unverified', 'approval of A does not cover B')
        self.assertIn('stale_reason', data['review'])
        self.assertEqual(run.only('dispatch')['task_id'], 'review-2')

    def test_2_check_receipts_must_name_the_checked_snapshot_and_cwd(self):
        repo, run = self.verifying(plan_overrides={'policy': {
            'review': {'required': False, 'role': 'reviewer'}, 'worktree_root': str(self.tmp / 'wt'),
            'checks': [{'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], 'cwd': '.'}]}})
        action = run.only('run_check')
        Path(action['args']['log_path']).write_text('OK (the check ran against revision A)\n')
        edit(repo, '\n# regression introduced before the receipt was recorded\n')
        code, env, _ = run.record_raw('check', {'name': 'unit', 'argv': action['args']['argv'], 'exit_code': 0,
                                                'log': action['args']['log_path'], 'snapshot': action['args']['snapshot']})
        self.assertEqual((code, env['error']['code']), (4, 'stale_evidence'))
        code, env, _ = run.record_raw('check', {'name': 'unit', 'argv': action['args']['argv'], 'exit_code': 0,
                                                'log': action['args']['log_path'], 'cwd': str(self.tmp)})
        self.assertEqual((code, env['error']['code']), (2, 'cwd_mismatch'))
        code, env, _ = run.record_raw('check', {'name': 'unit', 'argv': action['args']['argv'], 'exit_code': 0,
                                                'log': action['args']['log_path'], 'snapshot': ''})
        self.assertEqual((code, env['error']['code']), (2, 'snapshot_missing'))

    def test_3_pr_endstate_requires_committed_changes(self):
        repo, run = self.verifying(plan_overrides={'authorization': {'endstate': 'pr', 'evidence': 'x'},
                                                   'policy': {'review': {'required': False, 'role': 'reviewer'},
                                                              'checks': [], 'worktree_root': str(self.tmp / 'wt')}})
        self.assertEqual([a['action'] for a in run.next()['actions']], ['commit'])
        git(repo, 'commit', '-qam', 'fix')
        self.assertEqual(run.only('accept')['args']['requirement_id'], 'REQ-MULTILINE')

    def test_4_executable_bit_change_invalidates(self):
        repo, run = self.verifying(caps=False, plan_overrides={'policy': {
            'review': {'required': False, 'role': 'reviewer'}, 'checks': [], 'worktree_root': str(self.tmp / 'wt')}})
        os.chmod(repo / 'wordstat.py', 0o755)
        log = run.scratch('ok.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})
        self.assertTrue(self.validate(run)['ready'])
        porcelain = git(repo, 'status', '--porcelain').stdout
        os.chmod(repo / 'wordstat.py', 0o644)
        self.assertEqual(git(repo, 'status', '--porcelain').stdout, porcelain)
        self.assertEqual(self.validate(run)['status'], 'stale')

    def test_5_uncertain_dispatch_errors_retry_the_same_request(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, execution={'mode': 'delegated'},
                                  tasks=[{'id': 'survey', 'purpose': 'read', 'kind': 'read'}],
                                  policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': []}))
        run.claim()
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        first = run.only('dispatch')
        out = run.record('dispatch', {'action_id': first['id'], 'error': {'code': 'transport', 'message': 'request timed out'}})
        self.assertEqual(out['result']['outcome'], 'uncertain')
        again = run.only('dispatch')
        self.assertEqual(again['host_call']['arguments']['clientRequestId'], first['host_call']['arguments']['clientRequestId'])
        self.assertEqual(run.state['tasks'][0]['rounds'], [])
        run.record('dispatch', {'action_id': again['id'], 'error': {'code': 'transport', 'message': 'timed out'}})
        out = run.record('dispatch', {'action_id': again['id'], 'error': {'code': 'transport', 'message': 'timed out'}})
        blocker = out['result']['blocker']
        self.assertIn(first['host_call']['arguments']['clientRequestId'], blocker['reason'])
        run.release()
        self.assertEqual(native([sys.executable, *blocker['resume']['argv'][1:]]).returncode, 0)
        run.claim()
        self.assertEqual(run.only('dispatch')['host_call']['arguments']['clientRequestId'],
                         first['host_call']['arguments']['clientRequestId'], 'retry never mints a new request ID')

    def test_6_report_of_a_completed_run_goes_stale_when_the_tree_changes(self):
        repo, run = self.verifying(caps=False, plan_overrides={'policy': {
            'review': {'required': False, 'role': 'reviewer'}, 'checks': [], 'worktree_root': str(self.tmp / 'wt')}})
        log = run.scratch('ok.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})
        run.record('transition', {'to': 'ready'})
        run.record('transition', {'to': 'completed'})
        self.assertEqual(cli('report', *run.args())[1]['data']['report']['outcome'], 'completed')
        edit(repo, '\n# later edit\n')
        report = cli('report', *run.args())[1]['data']['report']
        self.assertEqual(report['outcome'], 'stale')
        self.assertIn('does not cover the current tree', (run.run_dir / 'reports' / 'report.md').read_text())

    def test_11_artifact_destination_symlink_is_refused(self):
        repo, run = self.verifying(caps=False, plan_overrides={'policy': {
            'review': {'required': False, 'role': 'reviewer'}, 'checks': [], 'worktree_root': str(self.tmp / 'wt')}})
        outside = self.tmp / 'outside'
        outside.mkdir()
        evidence_dir = run.run_dir / 'artifacts' / 'evidence'
        if evidence_dir.exists():
            shutil.rmtree(evidence_dir)
        os.symlink(outside, evidence_dir)
        log = run.scratch('ok.log', 'ok')
        code, env, _ = run.record_raw('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed',
                                                     'kind': 'command', 'explanation': 'ok', 'artifacts': [str(log)]})
        self.assertEqual((code, env['error']['code']), (2, 'path_escape'))
        self.assertEqual(list(outside.iterdir()), [])

    def test_15_bad_record_input_still_returns_an_envelope(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo))
        run.claim()
        code, env, stderr = run.record_raw('resource', {'kind': 'process', 'pid': 'not-a-pid'})
        self.assertEqual((code, env['error']['code']), (2, 'pid'))
        self.assertNotIn('Traceback', stderr)


class DelegationFindingsTest(CoreTestCase):
    def parallel_run(self, tasks):
        repo = self.make_repo()
        run = self.init(self.plan(repo, execution={'mode': 'delegated', 'isolation': 'parallel'}, tasks=tasks,
                                  policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': [],
                                          'worktree_root': str(self.tmp / 'wt')}))
        run.claim()
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        return repo, run, FakeT3()

    def test_7_fast_child_commits_and_corrections_keep_the_baseline(self):
        repo, run, t3 = self.parallel_run([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}])
        flow = DelegatedFlow(self, run, t3)
        flow.create_worktree(run.only('create_worktree'))
        dispatch = run.only('dispatch')
        tree = Path(run.state['tasks'][0]['worktree'])
        response = t3.call(dispatch['host_call'])
        (tree / 'wordstat.py').write_text('fast child\n')
        commit_all(tree, 'committed before the parent recorded the dispatch')
        run.record('dispatch', {'action_id': dispatch['id'], 'response': response})
        t3.tasks[response['taskId']]['queue'] = [done('```json t3-result\n{oops\n```')]
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'correction_requested')
        correction = run.only('dispatch')
        response = t3.call(correction['host_call'])
        t3.tasks[response['taskId']]['queue'] = [done(result_block('fix', changed_files=['wordstat.py']))]
        run.record('dispatch', {'action_id': correction['id'], 'response': response})
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'accepted')

    def test_9_dependants_start_only_after_prerequisites_are_integrated(self):
        repo, run, t3 = self.parallel_run([
            {'id': 'api', 'purpose': 'add api', 'files': ['wordstat.py']},
            {'id': 'docs', 'purpose': 'document api', 'files': ['README.md'], 'depends_on': ['api']}])
        flow = DelegatedFlow(self, run, t3)
        flow.create_worktree(run.only('create_worktree'))
        dispatch = run.only('dispatch')
        response = t3.call(dispatch['host_call'])
        run.record('dispatch', {'action_id': dispatch['id'], 'response': response})
        tree = Path(run.state['tasks'][0]['worktree'])
        (tree / 'wordstat.py').write_text((tree / 'wordstat.py').read_text() + '\ndef api():\n    return 1\n')
        commit_all(tree, 'api')
        t3.tasks[response['taskId']]['queue'] = [done(result_block('api', changed_files=['wordstat.py']))]
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        actions = run.next()['actions']
        self.assertEqual([a['action'] for a in actions], ['integrate'], 'docs waits until api is merged')
        merge = native(actions[0]['args']['argv'])
        run.record('integration', {'action_id': actions[0]['id'], 'exit_code': merge.returncode})
        created = run.only('create_worktree')
        self.assertEqual(created['task_id'], 'docs')
        native(created['args']['argv'])
        self.assertIn('def api', (Path(created['args']['path']) / 'wordstat.py').read_text())

    def test_10_cleanup_never_offers_a_kill_for_a_replaced_pid(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': []}))
        run.claim()
        sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        run.record('resource', {'kind': 'process', 'pid': sleeper.pid, 'purpose': 'server'})
        state_file = run.run_dir / 'run.json'
        data = json.loads(state_file.read_text())
        data['resources'][0]['fingerprint'] = 'Thu Jan  1 00:00:00 1970 /usr/bin/unrelated'
        data['phase'] = 'completed'
        state_file.write_text(json.dumps(data))
        cleanup = run.only('cleanup')
        self.assertIsNone(cleanup['args']['argv'], 'no kill command for a PID that now belongs to something else')
        self.assertEqual(cleanup['args']['identity'], 'replaced')
        self.assertIsNone(sleeper.poll())


class InstallerFindingsTest(test_install.InstallTest):
    def test_install_lifecycle(self):
        pass  # covered by test_install.InstallTest

    def test_new_version_and_rollback(self):
        pass  # covered by test_install.InstallTest

    def test_12_manifest_paths_cannot_escape_the_version_directory(self):
        first = self.installer()['data']
        victim = self.home / '.local' / 'state' / 't3-plugins' / 'imps' / 'runs' / 'evidence.log'
        victim.parent.mkdir(parents=True)
        victim.write_text('run evidence')
        manifest_path = Path(first['version_dir']) / 'install-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        import hashlib
        manifest['files'].append({'path': str(victim), 'sha256': hashlib.sha256(b'run evidence').hexdigest(), 'mode': 420})
        manifest_path.write_text(json.dumps(manifest))
        out = self.installer('--uninstall', expect=2)
        self.assertEqual(out['error']['code'], 'manifest_path_escape')
        self.assertEqual(victim.read_text(), 'run evidence')

    def test_13_modified_files_stay_owned_after_uninstall(self):
        first = self.installer()['data']
        entry = Path(first['version_dir']) / 'entry.md'
        entry.write_text('my edits\n')
        out = self.installer('--uninstall')['data']
        self.assertEqual(out['kept_modified'], [str(entry)])
        self.assertEqual(entry.read_text(), 'my edits\n')
        refused = self.installer(expect=4)
        self.assertEqual(refused['error']['code'], 'locally_modified')
        self.assertEqual(entry.read_text(), 'my edits\n')


class Round2FindingsTest(CoreTestCase):
    """Gaps reported by the (interrupted) round-2 review; see conformance/review/round-2.md."""

    def delegated(self, tasks, isolation=None, review=False, **policy):
        repo = self.make_repo()
        execution = {'mode': 'delegated'}
        if isolation:
            execution['isolation'] = isolation
        settings = {'review': {'required': review, 'role': 'reviewer'}, 'checks': [], 'worktree_root': str(self.tmp / 'wt')}
        settings.update(policy)
        run = self.init(self.plan(repo, execution=execution, tasks=tasks, policy=settings))
        run.claim()
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        return repo, run, FakeT3()

    def test_a_review_binding_is_the_snapshot_next_issued(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, policy={'review': {'required': True, 'role': 'reviewer'}, 'checks': []}))
        run.claim()
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        log = run.scratch('ok.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})
        t3 = FakeT3()
        review = run.only('dispatch')
        issued = review['args']['snapshot']
        t3.script(review['host_call']['arguments']['clientRequestId'], done(result_block(review['task_id'], verdict='approve')))
        response = t3.call(review['host_call'])
        edit(repo, '\n# edited while the reviewer was starting\n')
        code, env, _ = run.record_raw('dispatch', {'action_id': review['id'], 'response': response, 'snapshot': issued})
        self.assertEqual(code, 4, 'the run moved on, so the bare action id is no longer offered')
        run.record('dispatch', {'action': review, 'response': response, 'snapshot': issued})
        self.assertEqual(run.state['tasks'][-1]['rounds'][0]['task_id'], response['taskId'], 'the sent child is tracked')
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        code, env, _ = cli('validate', *run.args())
        self.assertNotEqual(env['data']['review']['status'], 'passed', 'the verdict covers the issued tree only')

    def test_b_fast_serial_child_keeps_its_dispatch_valid(self):
        repo, run, t3 = self.delegated([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}], isolation='serial')
        dispatch = run.only('dispatch')
        response = t3.call(dispatch['host_call'])
        edit(repo, '\n# child change\n')
        commit_all(repo, 'child committed before the parent recorded the dispatch')
        run.record('dispatch', {'action_id': dispatch['id'], 'response': response})
        t3.tasks[response['taskId']]['queue'] = [done(result_block('fix', changed_files=['wordstat.py']))]
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'accepted')

    def test_c_cancel_does_not_ignore_uncertain_dispatches(self):
        repo, run, t3 = self.delegated([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}])
        dispatch = run.only('dispatch')
        request = dispatch['host_call']['arguments']['clientRequestId']
        run.record('dispatch', {'action_id': dispatch['id'], 'error': {'code': 'transport', 'message': 'timed out'}})
        run.record('transition', {'to': 'cancelling'})
        blocked = run.next()['blocked']
        self.assertEqual(blocked['code'], 'cancel_unconfirmed')
        self.assertEqual(blocked['task_ids'], [request])
        code, env, _ = run.record_raw('transition', {'to': 'cancelled'})
        self.assertEqual(code, 4)
        run.release()
        self.assertEqual(native([sys.executable, *blocked['resume']['argv'][1:]]).returncode, 0)
        run.claim()
        self.assertEqual(run.only('transition')['args']['to'], 'cancelled')

    def test_d_cancel_reaches_accepted_children_with_pending_runs(self):
        repo, run, t3 = self.delegated([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}])
        dispatch = run.only('dispatch')
        t3.script(dispatch['host_call']['arguments']['clientRequestId'],
                  dict(done(result_block('survey')), hasPendingChildRuns=True))
        run.record('dispatch', {'action_id': dispatch['id'], 'response': t3.call(dispatch['host_call'])})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(run.state['tasks'][0]['status'], 'accepted')
        run.record('transition', {'to': 'cancelling'})
        self.assertEqual([a['action'] for a in run.next()['actions']], ['cancel_task'])

    def test_e_planted_artifact_target_symlink_is_refused(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': []}))
        run.claim()
        run.record('transition', {'to': 'executing'})
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        log = run.scratch('ok.log', 'ok')
        import hashlib
        digest = hashlib.sha256(b'ok').hexdigest()
        victim = self.tmp / 'victim.txt'
        victim.write_text('do not overwrite')
        planted = run.run_dir / 'artifacts' / 'evidence'
        planted.mkdir(parents=True, exist_ok=True)
        os.symlink(victim, planted / f'{digest[:12]}-ok.log')
        code, env, _ = run.record_raw('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed',
                                                     'kind': 'command', 'explanation': 'ok', 'artifacts': [str(log)]})
        self.assertEqual((code, env['error']['code']), (2, 'path_escape'))
        self.assertEqual(victim.read_text(), 'do not overwrite')


class Round2InstallerTest(test_install.InstallTest):
    def test_install_lifecycle(self):
        pass  # covered by test_install.InstallTest

    def test_new_version_and_rollback(self):
        pass  # covered by test_install.InstallTest

    def test_f_symlinked_version_directory_is_refused(self):
        first = self.installer()['data']
        version_dir = Path(first['version_dir'])
        elsewhere = self.tmp / 'elsewhere'
        shutil.move(str(version_dir), elsewhere)
        os.symlink(elsewhere, version_dir)
        out = self.installer('--uninstall', expect=2)
        self.assertEqual(out['error']['code'], 'manifest_path_escape')
        self.assertTrue((elsewhere / 'entry.md').is_file(), 'nothing outside the prefix was deleted')


class Round3FindingsTest(CoreTestCase):
    """Round-3 adversarial review findings; see conformance/review/round-3.md."""

    def run_with(self, tasks=None, mode='direct', isolation=None, review=False, caps=None, **policy):
        repo = self.make_repo()
        execution = {'mode': mode}
        if isolation:
            execution['isolation'] = isolation
        settings = {'review': {'required': review, 'role': 'reviewer'}, 'checks': [], 'worktree_root': str(self.tmp / 'wt')}
        settings.update(policy)
        overrides = {'execution': execution, 'policy': settings}
        if tasks:
            overrides['tasks'] = tasks
        run = self.init(self.plan(repo, **overrides))
        run.claim()
        if mode == 'delegated' or review:
            run.record('capabilities', {'response': caps or capabilities()})
        run.record('transition', {'to': 'executing'})
        return repo, run, FakeT3()

    def accept(self, run):
        log = run.scratch(f'ok-{run.generation}.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})

    def test_1_no_completion_while_child_runs_are_pending(self):
        repo, run, t3 = self.run_with([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}], mode='delegated')
        dispatch = run.only('dispatch')
        t3.script(dispatch['host_call']['arguments']['clientRequestId'],
                  dict(done(result_block('survey')), hasPendingChildRuns=True))
        run.record('dispatch', {'action_id': dispatch['id'], 'response': t3.call(dispatch['host_call'])})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        self.assertFalse([a for a in run.next()['actions'] if a['action'] == 'transition'])
        code, env, _ = run.record_raw('transition', {'to': 'ready'})
        self.assertEqual((code, env['error']['code']), (4, 'children_running'))
        task_id = run.state['tasks'][0]['rounds'][0]['task_id']
        t3.tasks[task_id]['queue'] = [done(result_block('survey'))]
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        run.record('transition', {'to': 'ready'})

    def test_2_late_dispatch_receipt_is_tracked_during_cancellation(self):
        repo, run, t3 = self.run_with([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}], mode='delegated')
        dispatch = run.only('dispatch')
        response = t3.call(dispatch['host_call'])
        run.record('transition', {'to': 'cancelling'})
        self.assertEqual(run.only('transition')['args']['to'], 'cancelled', 'nothing recorded yet')
        run.record('dispatch', {'action': dispatch, 'response': response})
        self.assertEqual([a['action'] for a in run.next()['actions']], ['cancel_task'])

    def test_3_review_binding_includes_issue_time_policy(self):
        repo, run, t3 = self.run_with(review=True)
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        review = run.only('dispatch')
        t3.script(review['host_call']['arguments']['clientRequestId'], done(result_block(review['task_id'], verdict='approve')))
        response = t3.call(review['host_call'])
        run.record('policy', {'policy': {'role_overrides': {'reviewer': {'providerInstanceId': 'antigravity',
                                                                          'model': 'gemini-3.8-flash-high'}}}})
        run.record('dispatch', {'action': review, 'response': response, 'snapshot': review['args']['snapshot'],
                                'binding': review['args']['binding']})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertNotEqual(cli('validate', *run.args())[1]['data']['review']['status'], 'passed')

    def test_4_approve_with_major_findings_counts_as_adverse(self):
        repo, run, t3 = self.run_with(review=True)
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        review = run.only('dispatch')
        t3.script(review['host_call']['arguments']['clientRequestId'], done(result_block(
            review['task_id'], verdict='approve', findings=[{'severity': 'major', 'summary': 'breaks tabs'}])))
        run.record('dispatch', {'action_id': review['id'], 'response': t3.call(review['host_call']),
                                'binding': review['args']['binding']})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(run.state['reviews'][-1]['verdict'], 'adverse')
        self.assertEqual(run.only('repair')['args']['stage'], 'review')

    def test_5_uncommitted_child_work_is_rejected_not_lost(self):
        repo, run, t3 = self.run_with([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}], mode='delegated',
                                      isolation='parallel')
        tree = run.only('create_worktree')
        native(tree['args']['argv'])
        run.record('resource', {'kind': 'worktree', 'name': tree['args']['name'], 'path': tree['args']['path'],
                                'branch': tree['args']['branch'], 'task_id': 'fix'})
        dispatch = run.only('dispatch')
        response = t3.call(dispatch['host_call'])
        run.record('dispatch', {'action_id': dispatch['id'], 'response': response})
        (Path(tree['args']['path']) / 'wordstat.py').write_text('edited but never committed\n')
        t3.tasks[response['taskId']]['queue'] = [done(result_block('fix', changed_files=['wordstat.py']))]
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertIn('must hold its work as commits', out['result']['blocker']['reason'])
        cleanup = next(r for r in run.state['resources'] if r['kind'] == 'worktree')['cleanup_argv']
        self.assertNotIn('--force', cleanup, 'cleanup never force-discards a task worktree')

    def test_6_recipe_stamp_refuses_a_tree_changed_after_completion(self):
        repo, run, t3 = self.run_with()
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        run.record('transition', {'to': 'ready'})
        run.record('transition', {'to': 'completed'})
        edit(repo, '\n# the recipe or product changed after completion\n')
        code, env, _ = cli('recipe-stamp', *run.args('--recipe', repo / 'recipe.json', '--feature', 'F-X',
                                                     '--requirement', 'REQ-MULTILINE'))
        self.assertEqual((code, env['error']['code']), (4, 'stale_evidence'))

    def test_7_uncertain_dispatch_blocks_cross_parent_resume(self):
        repo, run, t3 = self.run_with([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}], mode='delegated')
        dispatch = run.only('dispatch')
        run.record('dispatch', {'action_id': dispatch['id'], 'error': {'code': 'transport', 'message': 'timed out'}})
        blocked = run.next(parent='thread-elsewhere')['blocked']
        self.assertEqual(blocked['code'], 'cross_parent_resume')
        self.assertEqual(blocked['task_ids'], [dispatch['host_call']['arguments']['clientRequestId']])

    def test_9_dirty_submodule_content_invalidates(self):
        repo, run, t3 = self.run_with()
        sub = self.tmp / 'subsrc'
        sub.mkdir()
        (sub / 'lib.py').write_text('X = 1\n')
        git(sub, 'init', '-q', '-b', 'main')
        git(sub, 'add', '-A')
        git(sub, 'commit', '-qm', 'lib')
        git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(sub), 'dep')
        git(repo, 'commit', '-qm', 'add dep')
        (repo / 'dep' / 'lib.py').write_text('X = 2\n')
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['dep'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        self.assertTrue(cli('validate', *run.args())[1]['data']['ready'])
        porcelain = git(repo, 'status', '--porcelain').stdout
        (repo / 'dep' / 'lib.py').write_text('X = 3\n')
        self.assertEqual(git(repo, 'status', '--porcelain').stdout, porcelain)
        self.assertEqual(cli('validate', *run.args())[1]['data']['status'], 'stale')

    def test_11_scaffold_refuses_symlinked_destination(self):
        repo = self.make_repo('verify-product')
        outside = self.tmp / 'outside-agents'
        outside.mkdir()
        os.symlink(outside, repo / '.agents')
        from test_verification_init import facts
        code, env, _ = cli('recipe-scaffold', '--plugin-dir', ROOT / 'plugins' / 'imps', '--repo', repo, '--json',
                           json.dumps(facts()))
        self.assertEqual((code, env['error']['code']), (2, 'path_escape'))
        self.assertEqual(list(outside.iterdir()), [])

    def test_12_reviewer_excludes_the_provider_that_actually_wrote(self):
        repo, run, t3 = self.run_with([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py'],
                                        'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol'}}],
                                      mode='delegated', isolation='serial', review=True)
        dispatch = run.only('dispatch')
        response = t3.call(dispatch['host_call'])
        run.record('dispatch', {'action_id': dispatch['id'], 'response': response})
        edit(repo)
        commit_all(repo, 'codex child fix')
        t3.tasks[response['taskId']]['queue'] = [done(result_block('fix', changed_files=['wordstat.py']))]
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        target = run.only('dispatch')['args']['target']['providerInstanceId']
        self.assertNotIn(target, ('codex', 'claudeAgent'), 'neither the parent nor the codex writer reviews')

    def test_13_retry_after_no_review_target_rediscovers(self):
        caps = capabilities()
        for provider in caps['providers']:
            provider['canRunChildTask'] = False
        repo, run, t3 = self.run_with(review=True, caps=caps)
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        blocked = run.next()['blocked']
        self.assertEqual(blocked['code'], 'provider_unavailable')
        run.record('block', {'blocker': blocked})
        run.release()
        self.assertEqual(native([sys.executable, *blocked['resume']['argv'][1:]]).returncode, 0)
        run.claim()
        self.assertEqual([a['action'] for a in run.next()['actions']], ['discover'])


class Round3InstallerTest(test_install.InstallTest):
    def test_install_lifecycle(self):
        pass  # covered by test_install.InstallTest

    def test_new_version_and_rollback(self):
        pass  # covered by test_install.InstallTest

    def test_8_uninstall_version_cannot_traverse(self):
        self.installer()
        victim_dir = self.prefix / 'victim'
        victim_dir.mkdir(parents=True)
        (victim_dir / 'keep.txt').write_text('outside the plugin root')
        out = self.installer('--uninstall', '--version', '../victim', expect=2)
        self.assertEqual(out['error']['code'], 'unknown_version')
        self.assertTrue((victim_dir / 'keep.txt').is_file())

    def test_10_uninstall_keeps_unowned_bytecode(self):
        first = self.installer()['data']
        mine = Path(first['version_dir']) / 'unrelated' / '__pycache__' / 'user-data.cpython-314.pyc'
        mine.parent.mkdir(parents=True)
        mine.write_bytes(b'not ours')
        self.installer('--uninstall')
        self.assertTrue(mine.is_file())


class MatrixFindingsTest(CoreTestCase):
    """Defects found by the live conformance matrix (conformance/compatibility.md)."""

    def test_read_only_child_listing_files_gets_a_correction_not_a_block(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, execution={'mode': 'delegated'},
                                  tasks=[{'id': 'survey', 'purpose': 'read', 'kind': 'read'}],
                                  policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': []}))
        run.claim()
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        t3 = FakeT3()
        dispatch = run.only('dispatch')
        self.assertIn('"changed_files": [], "commit": null', dispatch['host_call']['arguments']['task'])
        t3.script(dispatch['host_call']['arguments']['clientRequestId'],
                  done(result_block('survey', changed_files=['wordstat.py'])))
        run.record('dispatch', {'action_id': dispatch['id'], 'response': t3.call(dispatch['host_call'])})
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'correction_requested')
        self.assertIn('changed_files', out['result']['problem'])
