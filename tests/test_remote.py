"""Source-spec case 12: publish receipts are reconciled before any retry, and a
local pass never satisfies a required remote outcome."""
from support import CoreTestCase, git, result_block


class RemoteTest(CoreTestCase):
    def publishing_run(self, endstate='pr'):
        repo = self.make_repo()
        run = self.init(self.plan(repo, authorization={'endstate': endstate, 'remote': ['push', 'pr'], 'evidence': 'test'},
                                  policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': [],
                                          'worktree_root': str(self.tmp / 'wt')}))
        run.claim()
        run.record('transition', {'to': 'executing'})
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        git(repo, 'commit', '-qam', 'fix')
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        log = run.scratch('ok.log', 'prints 3')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'prints 3', 'artifacts': [str(log)]})
        run.record('transition', {'to': 'ready'})
        head = git(repo, 'rev-parse', 'HEAD').stdout.strip()
        return repo, run, head

    def test_local_pass_cannot_complete_a_pr_endstate(self):
        repo, run, head = self.publishing_run()
        code, env, _ = run.record_raw('transition', {'to': 'completed'})
        self.assertEqual((code, env['error']['code']), (4, 'remote_unconfirmed'))
        self.assertEqual(run.only('transition')['args']['to'], 'publishing')

    def test_receipt_is_reconciled_before_retry(self):
        repo, run, head = self.publishing_run()
        run.record('transition', {'to': 'publishing'})
        publish = run.only('publish')
        self.assertEqual(publish['args']['head'], head)
        url = 'https://github.com/example/repo/pull/7'
        run.record('remote-receipt', {'kind': 'pr', 'url': url, 'number': 7, 'head_sha': head})
        data = run.next()
        self.assertEqual([a['action'] for a in data['actions']], ['confirm_remote'],
                         'an interrupted publish is observed, never repeated')
        code, env, _ = run.record_raw('remote-receipt', {'kind': 'pr', 'url': url + '-again'})
        self.assertEqual((code, env['error']['code']), (4, 'receipt_exists'))
        code, env, _ = run.record_raw('transition', {'to': 'completed'})
        self.assertEqual(code, 4, 'a receipt alone is not an observed outcome')
        run.record('remote-observation', {'kind': 'pr', 'url': url, 'state': 'OPEN', 'head_sha': head})
        run.record('transition', {'to': 'completed'})
        self.assertEqual(run.status()['phase'], 'completed')

    def test_observation_at_a_different_head_does_not_complete(self):
        repo, run, head = self.publishing_run()
        run.record('transition', {'to': 'publishing'})
        url = 'https://github.com/example/repo/pull/8'
        run.record('remote-receipt', {'kind': 'pr', 'url': url, 'head_sha': head})
        run.record('remote-observation', {'kind': 'pr', 'url': url, 'state': 'OPEN', 'head_sha': '0' * 40})
        data = run.next()
        self.assertEqual(data['blocked']['code'], 'remote_unconfirmed')
        self.assertIn('head differs', data['blocked']['reason'])

    def test_release_endstate_is_blocked_not_faked(self):
        repo, run, head = self.publishing_run(endstate='release')
        data = run.next()
        self.assertEqual(data['blocked']['code'], 'endstate_unsupported')
        self.assertIn('set-endstate', data['blocked']['resume']['argv'])
