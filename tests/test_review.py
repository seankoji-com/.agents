"""Source-spec cases 6 and 7, REQ-REVIEW, using the default imps config."""
import json

from support import CoreTestCase, FakeT3, capabilities, cli, done, git, result_block
from test_readiness import Base


def catalog(available=('codex', 'claudeAgent')):
    caps = capabilities()
    for provider in caps['providers']:
        if provider['providerInstanceId'] not in available:
            provider['canRunChildTask'] = False
    return caps


class ReviewTest(Base):
    def review_run(self, repo=None, caps=None, repair_limit=2):
        overrides = {'policy': {'review': {'required': True, 'role': 'reviewer'}, 'repair_limit': repair_limit,
                                'checks': [], 'worktree_root': str(self.tmp / 'wt')}}
        repo = repo or self.make_repo()
        run = self.init(self.plan(repo, **overrides))
        run.claim()
        run.record('capabilities', {'response': caps or capabilities()})
        run.record('transition', {'to': 'executing'})
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        log = run.scratch('ok.log', 'prints 3')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'prints 3', 'artifacts': [str(log)]})
        return repo, run

    def test_unavailable_reviewer_walks_the_default_chain(self):
        repo, run = self.review_run(caps=catalog(available=('codex', 'claudeAgent', 'opencode')))
        t3 = FakeT3()
        first = run.only('dispatch')
        self.assertEqual(first['args']['target']['providerInstanceId'], 'codex')
        self.assertIn('first catalog provider other than', first['args']['why'])
        run.record('dispatch', {'action_id': first['id'], 'error': {'code': 'capability_denied',
                                                                    'message': 'Provider codex is not authenticated'}})
        second = run.only('dispatch')
        self.assertEqual(second['args']['target']['providerInstanceId'], 'opencode',
                         'next non-implementer catalog provider')
        run.record('dispatch', {'action_id': second['id'], 'error': {'code': 'capability_denied', 'message': 'provider unavailable'}})
        third = run.only('dispatch')
        self.assertEqual(third['args']['target']['providerInstanceId'], 'claudeAgent')
        self.assertIn('fresh isolated same-provider', third['args']['why'])
        ids = {a['host_call']['arguments']['clientRequestId'] for a in (first, second, third)}
        self.assertEqual(len(ids), 3)
        t3.script(third['host_call']['arguments']['clientRequestId'], done(result_block(third['task_id'], verdict='approve')))
        run.record('dispatch', {'action_id': third['id'], 'response': t3.call(third['host_call'])})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(run.only('transition')['args']['to'], 'ready')
        code, env, _ = cli('report', *run.args())
        reviews = env['data']['report']['reviews']
        self.assertEqual([r['verdict'] for r in reviews], ['unavailable', 'unavailable', 'approve'])
        self.assertEqual(reviews[-1]['selection']['providerInstanceId'], 'claudeAgent')
        self.assertIn('fresh isolated same-provider', reviews[-1]['why'])
        markdown = (run.run_dir / 'reports' / 'report.md').read_text()
        self.assertIn('approve by claudeAgent', markdown)

    def test_adverse_verdict_is_retained_and_never_triggers_fallback(self):
        repo, run = self.review_run(repair_limit=0)
        t3 = FakeT3()
        review = run.only('dispatch')
        t3.script(review['host_call']['arguments']['clientRequestId'], done(result_block(
            review['task_id'], verdict='adverse', findings=[{'severity': 'blocker', 'summary': 'breaks tabs'}])))
        run.record('dispatch', {'action_id': review['id'], 'response': t3.call(review['host_call'])})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        data = run.next()
        self.assertFalse([a for a in data['actions'] if a['action'] == 'dispatch'], 'no second reviewer after an adverse verdict')
        self.assertEqual(data['blocked']['code'], 'repair_limit')
        self.assertEqual(len(t3.dispatches()), 1)
        self.assertEqual(run.state['reviews'][-1]['verdict'], 'adverse')
        code, env, _ = run.record_raw('transition', {'to': 'ready'})
        self.assertEqual(code, 4, 'an adverse verdict blocks readiness')
        code, env, _ = run.record_raw('waiver', {'target': 'review', 'reason': 'x', 'decided_by': 'operator',
                                                 'operator_quote': 'override code review: x'})
        self.assertEqual(code, 0, 'operator override is a distinct, recorded decision')
        self.assertEqual(cli('validate', *run.args())[1]['data']['review']['status'], 'waived')

    def test_repository_policy_reviewer_overrides_default_chain(self):
        repo = self.make_repo()
        (repo / '.t3-plugins').mkdir()
        (repo / '.t3-plugins' / 'imps.json').write_text(json.dumps({'schema_version': 1, 'policy': {
            'role_overrides': {'reviewer': {'providerInstanceId': 'antigravity', 'model': 'gemini-3.8-flash-high'}},
            'review': {'required': True, 'role': 'reviewer', 'waivable': False}}}))
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'policy')
        repo, run = self.review_run(repo=repo)
        review = run.only('dispatch')
        self.assertEqual(review['args']['target'], {'providerInstanceId': 'antigravity', 'model': 'gemini-3.8-flash-high', 'options': {}})
        self.assertIn('repository policy', review['args']['why'])
        run.record('dispatch', {'action_id': review['id'], 'error': {'code': 'capability_denied', 'message': 'provider disabled'}})
        data = run.next()
        self.assertEqual(data['blocked']['code'], 'provider_unavailable', 'a named reviewer has no silent fallback')
        code, env, _ = run.record_raw('waiver', {'target': 'review', 'reason': 'x', 'decided_by': 'operator',
                                                 'operator_quote': 'skip code review'})
        self.assertEqual((code, env['error']['code']), (4, 'waiver_forbidden'))

    def test_repair_invalidates_review_and_counters_survive_resume(self):
        repo, run = self.review_run(repair_limit=1)
        t3 = FakeT3()
        review = run.only('dispatch')
        t3.script(review['host_call']['arguments']['clientRequestId'], done(result_block(
            review['task_id'], verdict='adverse', findings=[{'severity': 'major', 'summary': 'needs a test'}])))
        run.record('dispatch', {'action_id': review['id'], 'response': t3.call(review['host_call'])})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        run.record('repair', {'stage': 'review', 'findings': run.only('repair')['args']['findings']})
        state = run.state
        self.assertTrue(all(entry.get('invalidated') for entry in state['acceptance'] + state['reviews']))
        run.release()
        run.claim()
        self.assertEqual(run.state['counters']['repairs'], {'review': 1})
        implement = run.only('implement')
        self.assertEqual(implement['task_id'], 'repair-1')
        self.assertIn('needs a test', implement['args']['brief'])
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text() + '\n# repaired\n')
        run.record('result', {'task_id': 'repair-1', 'text': result_block('repair-1', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.assertEqual(run.only('accept')['args']['requirement_id'], 'REQ-MULTILINE', 'acceptance needed again')
        log = run.scratch('ok2.log', 'prints 3')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'prints 3', 'artifacts': [str(log)]})
        review2 = run.only('dispatch')
        t3.script(review2['host_call']['arguments']['clientRequestId'], done(result_block(
            review2['task_id'], verdict='adverse', findings=[{'severity': 'major', 'summary': 'still no test'}])))
        run.record('dispatch', {'action_id': review2['id'], 'response': t3.call(review2['host_call'])})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(run.next()['blocked']['code'], 'repair_limit', 'limit persisted across resume')
        code, env, _ = run.record_raw('repair', {'stage': 'review'})
        self.assertEqual((code, env['error']['code']), (4, 'repair_limit'))
