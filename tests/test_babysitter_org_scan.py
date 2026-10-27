"""Org triage through synthetic GraphQL pages and a relocated installed CLI.

No live GitHub, models, mutations or scheduler calls.
"""
import argparse
import copy
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/babysitter/scripts/org_scan.py'
spec = importlib.util.spec_from_file_location('org_scan', SCRIPT)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
HEAD = 'a' * 40
RATE = {'cost': 1, 'remaining': 4999, 'resetAt': '2026-10-25T01:00:00Z'}


def connection(nodes, size=100, cursor=None):
    start = int(cursor or 0)
    end = start + size
    return {'nodes': copy.deepcopy(nodes[start:end]), 'totalCount': len(nodes),
            'pageInfo': {'hasNextPage': end < len(nodes),
                         'endCursor': str(end) if end < len(nodes) else None}}


def check(state='SUCCESS', name='ci', kind='CheckRun', identity=None):
    if kind == 'StatusContext':
        return {'id': identity or name, '__typename': kind, 'context': name, 'state': state}
    return {'id': identity or name, '__typename': kind, 'name': name,
            'status': state if state in scan.PENDING else 'COMPLETED',
            'conclusion': None if state in scan.PENDING else state}


def pr(number=1, repo='fixture/repo', contexts=None, threads=None, **changes):
    node = {'id': repo + '#' + str(number), 'number': number,
            'url': 'https://github.com/' + repo + '/pull/' + str(number),
            'title': 'Fixture', 'state': 'OPEN', 'isDraft': False,
            'isCrossRepository': False, 'headRefOid': HEAD,
            'headRefName': 'topic', 'headRepository': {'nameWithOwner': repo},
            'repository': {'nameWithOwner': repo}, 'autoMergeRequest': {'enabledAt': None},
            'mergeable': 'MERGEABLE', 'mergeStateStatus': 'CLEAN', 'reviewDecision': 'APPROVED',
            'reviewThreads': connection(threads or []),
            'commits': {'nodes': [{'commit': {'oid': HEAD, 'statusCheckRollup': {
                'state': 'SUCCESS', 'contexts': connection(contexts if contexts is not None else [check()])}}}]}}
    node.update(changes)
    return node


class FixtureAPI:
    def __init__(self, repositories, prs, tails=None):
        self.repositories, self.prs, self.tails = repositories, prs, tails or {}
        self.calls = []

    def query(self, query, variables=None, estimate=1):
        variables = variables or {}
        self.calls.append((query, variables, estimate))
        assert 'mutation' not in query
        assert ' body' not in query and 'comments(' not in query
        if variables.get('org'):
            return {'organization': {'repositories': connection(self.repositories, cursor=variables.get('cursor'))}}
        if 'id0' in variables:
            out = {}
            for i in range(len(variables) // 2):
                identity = variables['id%d' % i]
                out['r%d' % i] = {'id': identity, 'pullRequests': connection(
                    self.prs.get(identity, []), 25, variables.get('c%d' % i))}
            return out
        if 'id' in variables:
            kind = 'threads' if 'reviewThreads(' in query else 'checks'
            base = copy.deepcopy(next(p for nodes in self.prs.values() for p in nodes
                                      if p['id'] == variables['id']))
            conn = connection(self.tails[(base['id'], kind)], cursor=variables['cursor'])
            if kind == 'threads':
                base['reviewThreads'] = conn
            else:
                base['commits']['nodes'][0]['commit']['statusCheckRollup']['contexts'] = conn
            return {'node': base}
        return {'rateLimit': RATE}

    def report(self):
        return {'requests': len(self.calls)}


class ClassificationTest(unittest.TestCase):
    def test_default_lock_dir_keeps_a_pre_198_one_until_moved(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_STATE_HOME': temp}):
            state = Path(temp)
            self.assertEqual(scan.default_state_dir(), state / 'agents/jobs/babysitter/org-scan')
            (state / 't3-plugins/babysitter/org-scan').mkdir(parents=True)
            self.assertEqual(scan.default_state_dir(), state / 't3-plugins/babysitter/org-scan')
            (state / 'agents/jobs/babysitter/org-scan').mkdir(parents=True)
            self.assertEqual(scan.default_state_dir(), state / 'agents/jobs/babysitter/org-scan')

    def row(self, node):
        return scan.classify(node, FixtureAPI([], {}))

    def test_all_terminal_conclusions_and_status_contexts(self):
        for state in scan.FAIL | scan.PASS:
            with self.subTest(state=state):
                row = self.row(pr(contexts=[check(state)]))
                self.assertEqual(row['action'], 'dispatch' if state in scan.FAIL else 'healthy')
        for state in ('SUCCESS', 'FAILURE', 'ERROR'):
            row = self.row(pr(contexts=[check(state, kind='StatusContext')]))
            self.assertEqual(row['action'], 'healthy' if state == 'SUCCESS' else 'dispatch')
        for state in scan.PENDING:
            row = self.row(pr(contexts=[check(state)]))
            self.assertEqual(row['action'], 'waiting')
        for state in ('PENDING', 'EXPECTED'):
            self.assertEqual(self.row(pr(contexts=[check(state, kind='StatusContext')]))['action'], 'waiting')

    def test_unknown_check_states_and_null_conclusions_are_not_green(self):
        for context in (check('NEW_STATE'), {**check(), 'conclusion': None},
                        {**check(), 'status': 'QUEUED'}, {'__typename': 'Unexpected'},
                        check('NEUTRAL', kind='StatusContext')):
            row = self.row(pr(contexts=[context]))
            self.assertEqual(row['action'], 'unknown')
            self.assertEqual(row['checks'], 'unknown')

    def test_all_blockers_survive_a_queued_job(self):
        row = self.row(pr(contexts=[check('QUEUED'), check('FAILURE', 'lint')],
                          threads=[{'id': 'outdated', 'isResolved': False, 'isOutdated': True}],
                          mergeable='CONFLICTING', mergeStateStatus='DIRTY',
                          autoMergeRequest=None, reviewDecision='CHANGES_REQUESTED'))
        self.assertEqual(row['reasons'], ['changes-requested', 'failing-checks', 'merge-conflict', 'unresolved-threads'])
        self.assertEqual(row['unresolved_thread_ids'], ['outdated'])
        self.assertEqual(row['coordinator_actions'], ['enable-auto-merge'])
        self.assertEqual(row['action'], 'dispatch')

    def test_auto_merge_and_human_gates_do_not_dispatch_code_repairs(self):
        self.assertEqual(self.row(pr(autoMergeRequest=None))['action'], 'coordinator')
        row = self.row(pr(reviewDecision='REVIEW_REQUIRED', mergeStateStatus='BLOCKED'))
        self.assertEqual(row['coordinator_actions'], ['required-review'])
        row = self.row(pr(mergeStateStatus='BLOCKED'))
        self.assertEqual(row['coordinator_actions'], ['inspect-merge-gate'])
        self.assertEqual(self.row(pr(mergeable='UNKNOWN'))['action'], 'unknown')
        self.assertEqual(self.row(pr(mergeStateStatus='BEHIND'))['coordinator_actions'], ['update-branch'])

    def test_no_checks_and_head_mismatch(self):
        node = pr(contexts=[])
        node['commits']['nodes'][0]['commit']['statusCheckRollup'] = None
        self.assertEqual(self.row(node)['checks'], 'none')
        node['commits']['nodes'][0]['commit']['oid'] = 'b' * 40
        self.assertEqual(self.row(node)['action'], 'unknown')

    def test_fingerprint_is_stable_and_changes_with_observed_evidence(self):
        first = self.row(pr())
        self.assertEqual(first['observation_key'], self.row(pr())['observation_key'])
        self.assertNotEqual(first['observation_key'], self.row(pr(autoMergeRequest=None))['observation_key'])


class PaginationTest(unittest.TestCase):
    def test_disappearing_rollup_keeps_known_failure_and_other_prs(self):
        node = pr(contexts=[check('FAILURE')] + [check('SUCCESS', str(i)) for i in range(100)])
        api = FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [node, pr(number=2)]})
        query = api.query
        def disappearing(text, variables=None, estimate=1):
            if variables and variables.get('cursor') == '100':
                current = copy.deepcopy(node)
                current['commits']['nodes'][0]['commit']['statusCheckRollup'] = None
                return {'node': current}
            return query(text, variables, estimate)
        with patch.object(api, 'query', side_effect=disappearing):
            out = scan.scan(api, 'fixture')
        self.assertFalse(out['complete'])
        self.assertEqual(len(out['prs']), 2)
        self.assertEqual(out['prs'][0]['unknowns'], ['checks:checks-disappeared'])
        self.assertEqual(out['prs'][0]['failing_checks'][0]['name'], 'ci')
        self.assertEqual(out['prs'][1]['action'], 'healthy')

    def test_all_repositories_prs_threads_and_checks_with_sparse_repos(self):
        repos = [{'id': str(i), 'nameWithOwner': 'fixture/r%03d' % i} for i in range(102)]
        many = [pr(i, 'fixture/r000') for i in range(1, 28)]
        many[0]['isDraft'] = True
        target = pr(2, 'fixture/r101', isCrossRepository=True)
        threads = [{'id': 't%d' % i, 'isResolved': i != 100, 'isOutdated': True} for i in range(101)]
        checks = [check('FAILURE' if i == 100 else 'SUCCESS', 'c%d' % i) for i in range(101)]
        target['reviewThreads'] = connection(threads)
        target['commits']['nodes'][0]['commit']['statusCheckRollup']['contexts'] = connection(checks)
        api = FixtureAPI(repos, {'0': many, '101': [target]},
                         {(target['id'], 'threads'): threads, (target['id'], 'checks'): checks})
        out = scan.scan(api, 'fixture')
        self.assertTrue(out['complete'], out)
        self.assertEqual(len(out['prs']), 27)
        self.assertEqual(out['repositories'], 102)
        self.assertEqual(out['dispatch'], [target['url']])
        self.assertEqual(out['prs'][-1]['unresolved_thread_ids'], ['t100'])
        self.assertEqual(out['prs'][-1]['failing_checks'][0]['name'], 'c100')
        self.assertTrue(out['prs'][-1]['fork'])
        repository_pages = math.ceil(len(repos) / 100)
        extra_pr_pages = math.ceil(len(many) / 25) - 1
        pr_batches = math.ceil((len(repos) + extra_pr_pages) / 10)
        self.assertEqual(len(api.calls), 1 + repository_pages + pr_batches + 2)  # Probe and two nested tails.

    def test_roster_has_no_search_thousand_result_cap(self):
        prs = [pr(i) for i in range(1, 1006)]
        out = scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': prs}), 'fixture')
        self.assertTrue(out['complete'], out['gaps'])
        self.assertEqual(len(out['prs']), 1005)
        self.assertEqual(out['prs'][-1]['number'], 1005)

    def test_later_read_failure_keeps_known_bad_evidence_without_all_clear(self):
        bad = pr(contexts=[check('FAILURE')])
        bad['reviewThreads']['totalCount'] = 101
        bad['reviewThreads']['pageInfo'] = {'hasNextPage': True, 'endCursor': '100'}
        api = FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [bad]})
        original = api.query
        def query(q, v=None, estimate=1):
            if v and v.get('cursor') == '100':
                raise scan.ScanError('request-budget')
            return original(q, v, estimate)
        api.query = query
        out = scan.scan(api, 'fixture')
        self.assertFalse(out['complete'])
        self.assertEqual(out['dispatch'], [bad['url']])
        self.assertIn('threads:request-budget', out['prs'][0]['unknowns'])

    def test_repeated_cursor_missing_metadata_count_drift_and_head_race(self):
        with self.assertRaisesRegex(scan.ScanError, 'malformed-connection'):
            scan.collect({'nodes': [], 'totalCount': 0}, lambda c: None)
        repeated = connection([{'id': 'a'}, {'id': 'b'}], 1)
        with self.assertRaisesRegex(scan.ScanError, 'repeated-cursor'):
            scan.collect(repeated, lambda c: connection([{'id': 'c'}, {'id': 'd'}], 1))
        changed = connection([{'id': 'a'}, {'id': 'b'}], 1)
        with self.assertRaisesRegex(scan.ScanError, 'connection-changed'):
            scan.collect(changed, lambda c: connection([]))
        api = FixtureAPI([], {'r': [pr()]})
        api.query = lambda *a, **k: {'node': pr(headRefOid='b' * 40)}
        with self.assertRaisesRegex(scan.ScanError, 'pr-changed'):
            scan.tail(api, pr(), 'threads', '100')


class TransportTest(unittest.TestCase):
    def api(self, **changes):
        args = dict(max_requests=100, max_cost=200, reserve=500, spacing=1, deadline=180)
        return scan.GitHub(argparse.Namespace(**{**args, **changes}))

    def response(self, data=None, stderr='', code=0):
        return subprocess.CompletedProcess([], code, json.dumps(data or {'data': {'rateLimit': RATE}}), stderr)

    def test_request_budget_reserve_cost_deadline_and_secret_free_argv(self):
        with patch.object(scan.subprocess, 'run', return_value=self.response()) as run, patch.object(scan.time, 'sleep'):
            api = self.api(max_requests=1)
            api.query('query { rateLimit { cost remaining resetAt } }')
            self.assertEqual(run.call_args.args[0], ['gh', 'api', 'graphql', '--input', '-'])
            self.assertIn('query', json.loads(run.call_args.kwargs['input']))
            with self.assertRaisesRegex(scan.ScanError, 'request-budget'):
                api.query('query { viewer { login } }')
            api = self.api()
            api.remaining = 500
            with self.assertRaisesRegex(scan.ScanError, 'rate-reserve'):
                api.query('query {}')
            api = self.api(max_cost=1)
            with self.assertRaisesRegex(scan.ScanError, 'cost-budget'):
                api.query('query {}', estimate=2)
            api = self.api()
            api.started -= 181
            with self.assertRaisesRegex(scan.ScanError, 'deadline'):
                api.query('query {}')
            self.assertEqual(run.call_count, 1)

    def test_partial_graphql_errors_and_rate_limits_never_retry(self):
        for response, reason in ((self.response({'data': {'rateLimit': RATE}, 'errors': [{'message': 'private'}]}), 'graphql-errors'),
                                 (self.response(stderr='HTTP 429 private', code=1), 'rate-limit-or-denied'),
                                 (self.response(stderr='HTTP 403 private', code=1), 'rate-limit-or-denied')):
            with patch.object(scan.subprocess, 'run', return_value=response) as run:
                with self.assertRaisesRegex(scan.ScanError, reason):
                    self.api().query('query {}')
                self.assertEqual(run.call_count, 1)

    def test_transients_retry_three_times_and_all_attempts_spend_budget(self):
        with patch.object(scan.subprocess, 'run', return_value=self.response({'message': 'unavailable'}, stderr='HTTP 503', code=1)) as run, \
                patch.object(scan.time, 'sleep'):
            api = self.api()
            with self.assertRaisesRegex(scan.ScanError, 'github-command-failed'):
                api.query('query {}', estimate=2)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(api.cost, 6)
        with patch.object(scan.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gh', 1)) as run, \
                patch.object(scan.time, 'sleep'):
            with self.assertRaisesRegex(scan.ScanError, 'request-budget'):
                self.api(max_requests=2).query('query {}')
            self.assertEqual(run.call_count, 2)

    def test_absent_or_malformed_rate_data_cannot_disable_reserve(self):
        for data in ({'data': {}}, {'data': {'rateLimit': {'cost': 'one', 'remaining': 1000}}}):
            with patch.object(scan.subprocess, 'run', return_value=self.response(data)):
                with self.assertRaisesRegex(scan.ScanError, 'missing-rate-data'):
                    self.api().query('query {}')

    def test_mutation_uses_shared_budget_without_a_rate_query_or_blind_retry(self):
        response = self.response({'data': {'enabled': True}})
        with patch.object(scan.subprocess, 'run', return_value=response) as run:
            api = self.api()
            api.remaining = 1000
            self.assertEqual(api.query('mutation {}', estimate=5, mutation=True), {'enabled': True})
            self.assertEqual((api.cost, api.remaining), (5, 995))
            self.assertEqual(run.call_count, 1)
        with patch.object(scan.subprocess, 'run', return_value=self.response({'message': 'unavailable'}, stderr='HTTP 503', code=1)) as run:
            with self.assertRaises(scan.ScanError):
                self.api().query('mutation {}', estimate=5, mutation=True)
            self.assertEqual(run.call_count, 1)


class InstalledTest(unittest.TestCase):
    def test_relocated_install_executes_scan_and_overlap_lock_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix, agents = root / 'prefix', root / 'agents'
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'babysitter',
                                     '--prefix', str(prefix), '--agents-root', str(agents)],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            moved = root / 'relocated'
            prefix.rename(moved)
            binary = root / 'bin'
            binary.mkdir()
            log = root / 'calls.jsonl'
            fake = binary / 'gh'
            fixture = root / 'pr.json'
            fixture.write_text(json.dumps(pr(contexts=[check('FAILURE')])))
            fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
assert sys.argv[1:] == ['api', 'graphql', '--input', '-']
request = json.load(sys.stdin)
assert 'mutation' not in request['query']
with Path(os.environ['SCAN_LOG']).open('a') as out:
    out.write(json.dumps(request) + '\\n')
data = {'rateLimit': {'cost': 1, 'remaining': 4999, 'resetAt': '2026-10-25T01:00:00Z'}}
if 'organization(' in request['query']:
    data['organization'] = {'repositories': {'nodes': [{'id':'repo','nameWithOwner':'fixture/repo'}], 'totalCount': 1,
        'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
elif 'id0' in request['variables']:
    data['r0'] = {'id': 'repo', 'pullRequests': {'nodes': [json.loads(Path(os.environ['SCAN_PR']).read_text())],
        'totalCount': 1, 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
print(json.dumps({'data': data}))
''')
            fake.chmod(0o755)
            env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                   'SCAN_LOG': str(log), 'SCAN_PR': str(fixture)}
            command = [sys.executable, str(moved / 'babysitter/current/scripts/org_scan.py'),
                       '--org', 'Fixture', '--state-dir', str(root / 'locks')]
            result = subprocess.run(command, env=env, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            body = json.loads(result.stdout)
            self.assertTrue(body['complete'])
            self.assertEqual(body['org'], 'fixture')
            self.assertEqual(body['dispatch'], ['https://github.com/fixture/repo/pull/1'])
            requests_before_contention = len(log.read_text().splitlines())
            with (root / 'locks/fixture.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(json.loads(result.stdout)['gaps'][0]['reason'], 'scan-already-running')
            self.assertEqual(len(log.read_text().splitlines()), requests_before_contention)


if __name__ == '__main__':
    unittest.main()
