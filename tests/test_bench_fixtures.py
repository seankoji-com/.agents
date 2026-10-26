"""Offline tests for the Stage 6 fixture staging, synthetic GitHub and MCP catalog shim.

Everything runs on loopback sockets and temporary directories: no Docker, no network,
no model and no real GitHub.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import select
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = ROOT / 'bench' / 'container'
WORKFLOWS = ROOT / 'bench' / 'v2' / 'fixtures' / 'workflows'
BABYSITTER = WORKFLOWS / 'workflow-babysitter'
sys.path.insert(0, str(CONTAINER))
sys.path.insert(0, str(ROOT / 'bench' / 'v2' / 'checks'))
sys.path.insert(0, str(ROOT / 'scripts'))
import github_sidecar  # noqa: E402
import mcp_shim  # noqa: E402
import stage_fixtures  # noqa: E402
import workflow_contract  # noqa: E402
import routing  # noqa: E402

HAVE_OPENSSL = shutil.which('openssl') is not None
HOSTILE_GIT_CONFIG = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'maintenance.auto', 'GIT_CONFIG_VALUE_0': 'true',
                      'GIT_CONFIG_PARAMETERS': "'maintenance.auto=true' 'gc.auto=256'"}
CONTRACTS = json.loads((WORKFLOWS / 'contracts.json').read_text())


def list_prs_fragment(*, pr_number=None):
    text = (ROOT / 'plugins/babysitter/scripts/list-prs.sh').read_text()
    match = re.search(r"read -r -d '' PR_FRAGMENT <<GRAPHQL \|\| true\n(.*?)\nGRAPHQL\n", text, re.S)
    field = f'isRequired(pullRequestNumber: {pr_number})' if pr_number is not None else ''
    return (match.group(1).replace('${CHECK_REQUIRED_FIELD}', field)
            .replace('${STATUS_REQUIRED_FIELD}', field))


class Sidecar:
    """A loopback sidecar serving one scenario, with its log captured in memory."""

    def __init__(self, scenario=None, context=None):
        self.stream = io.StringIO()
        self.log = github_sidecar.EventLog(self.stream)
        self.log.write({'event': 'ready', 'port': 0})
        self.model = github_sidecar.Model(scenario or github_sidecar.scenario_from_fixture(BABYSITTER))
        self.server = github_sidecar.serve(self.model, self.log, 0, context, address='127.0.0.1')
        self.port = self.server.server_address[1]

    def request(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data, method=method,
                                     headers={'Authorization': 'token bench-synthetic-token',
                                              'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, dict(response.headers), json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, dict(exc.headers), json.loads(exc.read())

    def graphql(self, query, variables=None):
        return self.request('POST', '/api/graphql', {'query': query, 'variables': variables or {}})[2]

    def events(self):
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class SidecarScenarioTest(unittest.TestCase):
    def test_babysitter_scenario_comes_from_frozen_inputs(self):
        scenario = github_sidecar.scenario_from_fixture(BABYSITTER)
        pull = scenario['pulls'][0]
        thread = json.loads((BABYSITTER / 'thread.json').read_text())
        self.assertEqual((pull['head_sha'], pull['base_sha']), ('1e9721ca7f65fcb51d67f3329e4761da261d563a', 'ab624926987dfb8b302afebae4cc27c14198d37c'))
        self.assertEqual(pull['checks'], [{'name': 'unit', 'conclusion': 'failure', 'sha': '1e9721ca7f65fcb51d67f3329e4761da261d563a',
                                           'required': True}])
        self.assertEqual(pull['threads'][0]['id'], thread['comments'][0]['id'])
        self.assertEqual(pull['threads'][0]['comments'][0]['body'], 'seeded review concern')
        self.assertFalse(scenario['merge_authorized'])

    def test_changed_frozen_input_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'workflow-babysitter'
            shutil.copytree(BABYSITTER, copy)
            shutil.copyfile(WORKFLOWS / 'contracts.json', Path(tmp) / 'contracts.json')
            (copy / 'head.json').write_text('{"base_sha":"ab624926987dfb8b302afebae4cc27c14198d37c","head_sha":"head-other"}')
            with self.assertRaisesRegex(ValueError, 'head.json'):
                github_sidecar.scenario_from_fixture(copy)

    def test_authorised_writes_and_malformed_scenarios_are_rejected(self):
        scenario = github_sidecar.scenario_from_fixture(BABYSITTER)
        for change in ({'merge_authorized': True}, {'schema_version': 2}, {'pulls': []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                github_sidecar.validate_scenario(dict(scenario, **change))


class SidecarRestTest(unittest.TestCase):
    def setUp(self):
        self.sidecar = Sidecar()
        self.addCleanup(self.sidecar.close)

    def test_rest_reads_serve_frozen_head_failing_check_and_comment(self):
        status, _, pull = self.sidecar.request('GET', '/api/v3/repos/bench-org/bench-repo/pulls/1')
        self.assertEqual((status, pull['head']['sha'], pull['base']['sha']), (200, '1e9721ca7f65fcb51d67f3329e4761da261d563a', 'ab624926987dfb8b302afebae4cc27c14198d37c'))
        _, _, runs = self.sidecar.request('GET', '/repos/bench-org/bench-repo/commits/1e9721ca7f65fcb51d67f3329e4761da261d563a/check-runs')
        self.assertEqual([(r['name'], r['conclusion'], r['head_sha']) for r in runs['check_runs']],
                         [('unit', 'failure', '1e9721ca7f65fcb51d67f3329e4761da261d563a')])
        _, _, comments = self.sidecar.request('GET', '/api/v3/repos/bench-org/bench-repo/pulls/1/comments')
        self.assertEqual([c['body'] for c in comments], ['seeded review concern'])
        _, _, user = self.sidecar.request('GET', '/api/v3/user')
        self.assertEqual(user['login'], 'bench-user')
        reads = [e for e in self.sidecar.events() if e['event'] == 'read']
        self.assertEqual(len(reads), 4)
        self.assertEqual(reads[0]['observed'], {'head_sha': ['1e9721ca7f65fcb51d67f3329e4761da261d563a']})

    def test_pull_listing_is_paginated_with_link_headers(self):
        scenario = github_sidecar.scenario_from_fixture(BABYSITTER)
        base = scenario['pulls'][0]
        scenario['pulls'] = [dict(base, number=n, head_ref=f'bench/change-{n}') for n in (1, 2, 3)]
        sidecar = Sidecar(scenario)
        self.addCleanup(sidecar.close)
        status, headers, first = sidecar.request('GET', '/api/v3/repos/bench-org/bench-repo/pulls?per_page=2')
        self.assertEqual((status, [p['number'] for p in first]), (200, [1, 2]))
        self.assertIn('page=2>; rel="next"', headers['Link'])
        self.assertIn('page=2>; rel="last"', headers['Link'])
        _, headers, second = sidecar.request('GET', '/api/v3/repos/bench-org/bench-repo/pulls?per_page=2&page=2')
        self.assertEqual([p['number'] for p in second], [3])
        self.assertNotIn('rel="next"', headers['Link'])
        self.assertIn('page=1>; rel="prev"', headers['Link'])
        _, headers, only = self.sidecar.request('GET', '/api/v3/repos/bench-org/bench-repo/pulls')
        self.assertEqual(([p['number'] for p in only], headers.get('Link')), ([1], None))

    def test_actions_job_urls_resolve_to_the_pull_that_created_them(self):
        scenario = github_sidecar.scenario_from_fixture(BABYSITTER)
        base = scenario['pulls'][0]
        scenario['pulls'] = [
            dict(base, number=n, head_ref=f'bench/change-{n}', head_sha=sha,
                 checks=[dict(base['checks'][0], name=f'unit-{n}', sha=sha)])
            for n, sha in ((1, 'a' * 40), (2, 'b' * 40))]
        sidecar = Sidecar(scenario)
        self.addCleanup(sidecar.close)
        job_ids = []
        for number, sha in ((1, 'a' * 40), (2, 'b' * 40)):
            query = ('query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) '
                     '{ pullRequest(number: $number) { ...PRState } } } ' + list_prs_fragment(pr_number=number))
            response = sidecar.graphql(query, {'owner': 'bench-org', 'name': 'bench-repo', 'number': number})
            check = response['data']['repository']['pullRequest']['commits']['nodes'][0]['commit'][
                'statusCheckRollup']['contexts']['nodes'][0]
            job_id = int(check['detailsUrl'].rsplit('/', 1)[1])
            job_ids.append(job_id)
            status, _, job = sidecar.request('GET', f'/repos/bench-org/bench-repo/actions/jobs/{job_id}')
            self.assertEqual(status, 200)
            self.assertEqual((job['name'], job['head_sha']), (f'unit-{number}', sha))
        self.assertEqual(job_ids, [30000, 30001])

    def test_writes_are_refused_and_logged_without_bodies(self):
        secret_body = {'body': 'agent text that must not be logged'}
        status, _, _ = self.sidecar.request('POST', '/api/v3/repos/bench-org/bench-repo/issues/1/comments', secret_body)
        self.assertEqual(status, 403)
        status, _, _ = self.sidecar.request('PUT', '/api/v3/repos/bench-org/bench-repo/pulls/1/merge',
                                            {'sha': '1e9721ca7f65fcb51d67f3329e4761da261d563a'})
        self.assertEqual(status, 405)
        status, _, _ = self.sidecar.request('PATCH', '/repos/bench-org/bench-repo/pulls/1', {'title': 'x'})
        self.assertEqual(status, 403)
        _, _, pull = self.sidecar.request('GET', '/repos/bench-org/bench-repo/pulls/1')
        self.assertEqual(pull['title'], 'Synthetic babysitter PR', 'state never changes')
        log = self.sidecar.stream.getvalue()
        self.assertNotIn('agent text', log)
        kinds = [(e['event'], e.get('operation')) for e in self.sidecar.events() if e['event'] in ('post', 'merge')]
        self.assertEqual(kinds, [('post', 'POST /repos/bench-org/bench-repo/issues/1/comments'),
                                 ('merge', 'PUT /repos/bench-org/bench-repo/pulls/1/merge'),
                                 ('post', 'PATCH /repos/bench-org/bench-repo/pulls/1')])


class SidecarGraphQLTest(unittest.TestCase):
    def setUp(self):
        self.sidecar = Sidecar()
        self.addCleanup(self.sidecar.close)

    def test_list_prs_single_pr_query_matches_the_frozen_scenario(self):
        query = ('query($owner: String!, $name: String!, $number: Int!) { viewer { login } '
                 'repository(owner: $owner, name: $name) { pullRequest(number: $number) { ...PRState } } } '
                 + list_prs_fragment())
        data = self.sidecar.graphql(query, {'owner': 'bench-org', 'name': 'bench-repo', 'number': 1})['data']
        pull = data['repository']['pullRequest']
        commit = pull['commits']['nodes'][0]['commit']
        self.assertEqual((data['viewer']['login'], pull['author']['login'], pull['state']), ('bench-user',) * 2 + ('OPEN',))
        self.assertEqual(commit['oid'], '1e9721ca7f65fcb51d67f3329e4761da261d563a')
        self.assertEqual(commit['statusCheckRollup']['contexts']['nodes'],
                         [{'__typename': 'CheckRun', 'name': 'unit', 'conclusion': 'FAILURE',
                           'status': 'COMPLETED', 'startedAt': '2026-10-12T00:00:00Z',
                           'detailsUrl': 'https://github.bench.test/bench-org/bench-repo/'
                                         'actions/runs/28000/job/30000'}])
        thread = pull['reviewThreads']['nodes'][0]
        self.assertEqual((thread['isResolved'], thread['comments']['nodes'][0]['body']), (False, 'seeded review concern'))
        read = [e for e in self.sidecar.events() if e['event'] == 'read'][-1]
        self.assertEqual((read['unknown_fields'], read['errors']), ([], 0))
        self.assertEqual(read['observed'], {'check_sha': ['1e9721ca7f65fcb51d67f3329e4761da261d563a'], 'comment_id': ['thread-1'],
                                            'head_sha': ['1e9721ca7f65fcb51d67f3329e4761da261d563a']})

    def test_queue_clock_uses_the_supported_actions_job_api(self):
        # GraphQL CheckRun has no createdAt; asking for it must be an unknown field,
        # and the Actions job object is where the queue creation clock lives.
        query = ('query($owner: String!, $name: String!, $number: Int!) { viewer { login } '
                 'repository(owner: $owner, name: $name) { pullRequest(number: $number) { ...PRState } } } '
                 + list_prs_fragment(pr_number=1))
        response = self.sidecar.graphql(query, {'owner': 'bench-org', 'name': 'bench-repo', 'number': 1})
        read = [e for e in self.sidecar.events() if e['event'] == 'read'][-1]
        self.assertEqual((read['unknown_fields'], read['errors']), ([], 0))
        check = response['data']['repository']['pullRequest']['commits']['nodes'][0]['commit'][
            'statusCheckRollup']['contexts']['nodes'][0]
        self.assertNotIn('createdAt', check)
        self.assertTrue(check['isRequired'])
        self.assertIn('/actions/runs/28000/job/30000', check['detailsUrl'])

        status, _, job = self.sidecar.request('GET', '/repos/bench-org/bench-repo/actions/jobs/30000')
        self.assertEqual(status, 200)
        self.assertEqual(job['created_at'], '2026-10-12T00:00:00Z')

    def test_search_and_connection_pagination(self):
        query = ('query($q: String!, $limit: Int!) { search(query: $q, type: ISSUE, first: $limit) '
                 '{ issueCount nodes { ...PRState } } } ' + list_prs_fragment())
        found = self.sidecar.graphql(query, {'q': 'repo:bench-org/bench-repo is:pr is:open', 'limit': 100})
        self.assertEqual((found['data']['search']['issueCount'], found['data']['search']['nodes'][0]['number']), (1, 1))
        other = self.sidecar.graphql(query, {'q': 'org:someone-else is:pr is:open', 'limit': 100})
        self.assertEqual(other['data']['search']['nodes'], [])
        page = self.sidecar.graphql('{ repository(owner: "bench-org", name: "bench-repo") { pullRequests(states: [OPEN], '
                                    'first: 1) { totalCount pageInfo { hasNextPage endCursor } nodes { number headRefOid } } } }')
        connection = page['data']['repository']['pullRequests']
        self.assertEqual((connection['totalCount'], connection['pageInfo']['hasNextPage']), (1, False))
        after = self.sidecar.graphql('query($c: String) { repository(owner: "bench-org", name: "bench-repo") '
                                     '{ pullRequests(first: 1, after: $c) { nodes { number } } } }',
                                     {'c': connection['pageInfo']['endCursor']})
        self.assertEqual(after['data']['repository']['pullRequests']['nodes'], [])

    def test_merge_pr_state_and_thread_node_queries(self):
        state = self.sidecar.graphql(
            'query($owner:String!,$name:String!,$number:Int!){ repository(owner:$owner,name:$name){ pullRequest(number:$number)'
            '{ id state headRefOid mergeable mergeStateStatus reviewDecision baseRefName headRefName autoMergeRequest{ enabledAt }'
            ' reviewThreads(first:100){ pageInfo{ hasNextPage } nodes{ id isResolved } } commits(last:1){ nodes{ commit{'
            ' statusCheckRollup{ state } } } } } } }', {'owner': 'bench-org', 'name': 'bench-repo', 'number': 1})
        pull = state['data']['repository']['pullRequest']
        self.assertEqual((pull['headRefOid'], pull['mergeStateStatus'], pull['reviewThreads']['nodes']),
                         ('1e9721ca7f65fcb51d67f3329e4761da261d563a', 'BLOCKED', [{'id': 'thread-1', 'isResolved': False}]))
        node = self.sidecar.graphql('query($id:ID!){node(id:$id){... on PullRequestReviewThread{id pullRequest{id headRefOid}}}}',
                                    {'id': 'thread-1'})
        self.assertEqual(node['data']['node'], {'id': 'thread-1', 'pullRequest': {'id': pull['id'], 'headRefOid': '1e9721ca7f65fcb51d67f3329e4761da261d563a'}})

    def test_mutations_are_recorded_as_post_or_merge_and_refused(self):
        resolved = self.sidecar.graphql('mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{id isResolved}}}',
                                        {'id': 'thread-1'})
        merged = self.sidecar.graphql('mutation { mergePullRequest(input: {pullRequestId: "PR_1"}) { clientMutationId } }')
        self.assertIsNone(resolved['data'])
        self.assertIn('not authorised', resolved['errors'][0]['message'])
        self.assertIsNone(merged['data'])
        kinds = [(e['event'], e['operation']) for e in self.sidecar.events() if e['event'] in ('post', 'merge')]
        self.assertEqual(kinds, [('post', 'graphql:resolveReviewThread'), ('merge', 'graphql:mergePullRequest')])

    def test_introspection_and_unknown_fields_do_not_fail_the_query(self):
        data = self.sidecar.graphql('{ PullRequest: __type(name: "PullRequest") { fields(includeDeprecated: true) { name } } '
                                    'viewer { login notAField } }')['data']
        names = {f['name'] for f in data['PullRequest']['fields']}
        self.assertTrue({'headRefOid', 'reviewThreads', 'statusCheckRollup'} <= names)
        self.assertFalse(any(n.startswith('__') for n in names))
        self.assertIsNone(data['viewer']['notAField'])
        self.assertEqual(self.sidecar.events()[-1]['unknown_fields'], ['User.notAField'])


class SidecarObservationTest(unittest.TestCase):
    """The log maps to host observations the frozen babysitter grader accepts."""

    def session(self, write=None):
        sidecar = Sidecar()
        try:
            sidecar.request('GET', '/api/v3/repos/bench-org/bench-repo/pulls/1')
            sidecar.request('GET', '/api/v3/repos/bench-org/bench-repo/commits/1e9721ca7f65fcb51d67f3329e4761da261d563a/check-runs')
            sidecar.request('GET', '/api/v3/repos/bench-org/bench-repo/pulls/1/comments')
            if write:
                sidecar.request(*write)
            return sidecar.stream.getvalue()
        finally:
            sidecar.close()

    def test_read_only_session_passes_the_frozen_babysitter_checks(self):
        host = github_sidecar.observations_from_log(self.session())
        self.assertEqual((host['observed_head_sha'], host['observed_check_sha'], host['observed_comment_id']),
                         ('1e9721ca7f65fcb51d67f3329e4761da261d563a', '1e9721ca7f65fcb51d67f3329e4761da261d563a', 'thread-1'))
        self.assertEqual(host['trace_coverage'], ['sidecar_post_calls', 'sidecar_merge_calls', 'head_readback',
                                                  'check_readback', 'comment_readback'])
        checks = workflow_contract._scenario_checks('workflow-babysitter', BABYSITTER, host)
        self.assertEqual(checks, dict.fromkeys(CONTRACTS['scenarios']['workflow-babysitter']['check_ids'], True))

    def test_unauthorised_post_or_merge_fails_its_check(self):
        for write, failed in ((('POST', '/repos/bench-org/bench-repo/issues/1/comments', {'body': 'x'}),
                               'BABY-NO-UNAUTHORIZED-POST'),
                              (('PUT', '/repos/bench-org/bench-repo/pulls/1/merge', {}), 'BABY-NO-UNAUTHORIZED-MERGE')):
            with self.subTest(failed=failed):
                host = github_sidecar.observations_from_log(self.session(write))
                checks = workflow_contract._scenario_checks('workflow-babysitter', BABYSITTER, host)
                self.assertEqual([k for k, v in checks.items() if not v], [failed])

    def test_incomplete_log_withholds_trace_coverage(self):
        text = self.session()
        for broken in ('Traceback (most recent call last):\n' + text,
                       '\n'.join(l for l in text.splitlines() if '"ready"' not in l)):
            host = github_sidecar.observations_from_log(broken)
            self.assertEqual(host['trace_coverage'], [])
            self.assertFalse(workflow_contract._scenario_checks('workflow-babysitter', BABYSITTER, host)
                             ['BABY-NO-UNAUTHORIZED-POST'])

    def test_conflicting_readbacks_are_not_single_observations(self):
        lines = [json.dumps({'event': 'ready'}),
                 json.dumps({'event': 'read', 'observed': {'head_sha': ['1e9721ca7f65fcb51d67f3329e4761da261d563a']}}),
                 json.dumps({'event': 'read', 'observed': {'head_sha': ['head-other']}})]
        host = github_sidecar.observations_from_log('\n'.join(lines))
        self.assertIsNone(host['observed_head_sha'])
        self.assertNotIn('head_readback', host['trace_coverage'])


@unittest.skipUnless(HAVE_OPENSSL, 'openssl CLI unavailable')
class SidecarTlsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.tls = github_sidecar.tls_material(self.tmp / 'tls')

    def fetch(self, port, hostname):
        context = ssl.create_default_context(cafile=str(self.tls['ca_cert']))
        with socket.create_connection(('127.0.0.1', port), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=hostname) as tls:
                tls.sendall(b'GET /api/v3/user HTTP/1.1\r\nHost: github.bench.test\r\nConnection: close\r\n\r\n')
                data = b''
                while chunk := tls.recv(65536):
                    data += chunk
        return data

    def test_ca_key_is_destroyed_and_leaf_is_not_a_ca(self):
        self.assertEqual(sorted(p.name for p in (self.tmp / 'tls').iterdir()),
                         ['github-ca.crt', 'github.crt', 'github.ext', 'github.key'])
        text = subprocess.run(['openssl', 'x509', '-in', str(self.tls['cert']), '-noout', '-text'],
                              capture_output=True, text=True, check=True).stdout
        self.assertIn('CA:FALSE', text)
        self.assertIn('DNS:github.bench.test, DNS:github.com, DNS:api.github.com', text)
        self.assertEqual(stat.S_IMODE(self.tls['key'].stat().st_mode), 0o400)

    def test_https_serves_the_synthetic_host_through_the_env_file(self):
        env_file = github_sidecar.write_env_file(self.tmp / 'sidecar.env',
                                                 github_sidecar.scenario_from_fixture(BABYSITTER), self.tls)
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        lines = env_file.read_text().splitlines()
        self.assertEqual([l.split('=', 1)[0] for l in lines], ['BENCH_GITHUB_SCENARIO_B64', 'BENCH_GITHUB_TLS_CERT_B64',
                                                               'BENCH_GITHUB_TLS_KEY_B64'])
        self.assertNotIn('BEGIN', env_file.read_text())
        self.assertEqual(github_sidecar.container_args(env_file), ['--env-file', str(env_file)])
        model, tls = github_sidecar._load_environment(dict(l.split('=', 1) for l in lines))
        self.assertEqual(model.scenario['scenario'], 'workflow-babysitter')
        stream = io.StringIO()
        log = github_sidecar.EventLog(stream)
        log.write({'event': 'ready'})
        server = github_sidecar.serve(model, log, 0, github_sidecar.tls_context(*tls), address='127.0.0.1')
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        response = self.fetch(port, 'github.bench.test')
        self.assertTrue(response.startswith(b'HTTP/1.1 200'))
        self.assertIn(b'"login": "bench-user"', response)
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.fetch(port, 'gateway.bench.test')
        for _ in range(100):  # the server records the refused handshake on its handler thread
            if 'connection-error' in stream.getvalue():
                break
            threading.Event().wait(0.05)
        events = [json.loads(line)['event'] for line in stream.getvalue().splitlines()]
        self.assertEqual(events, ['ready', 'read', 'connection-error'])
        self.assertTrue(github_sidecar.observations_from_log(stream.getvalue())['log_complete'])

    def test_trust_bundle_concatenates_cas(self):
        other = self.tmp / 'gateway-ca.crt'
        other.write_text('-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n')
        bundle = github_sidecar.trust_bundle([other, self.tls['ca_cert']], self.tmp / 'bundle.pem')
        self.assertEqual(bundle.read_text().count('BEGIN CERTIFICATE'), 2)

    def test_bad_environment_fails_closed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit):
                github_sidecar.main({'BENCH_GITHUB_SCENARIO_B64': base64.b64encode(b'{"schema_version": 9}').decode()})
            with self.assertRaises(SystemExit):
                github_sidecar.main({'BENCH_GITHUB_TLS_CERT_B64': 'Zm9v'})
        self.assertEqual([json.loads(l)['event'] for l in output.getvalue().splitlines()], ['config-error'] * 2)


CAPABILITIES = {'inheritedProviderInstanceId': 'codex', 'inheritedModel': 'gpt-luna', 'runtimeMode': 'auto',
                'providers': [{'providerInstanceId': 'codex', 'driverKind': 'codex', 'canRunChildTask': True,
                               'constraints': [], 'models': [{'id': 'gpt-luna'}]},
                              {'providerInstanceId': 'claudeAgent', 'driverKind': 'claudeAgent',
                               'canRunChildTask': True, 'constraints': [], 'models': [{'id': 'claude-haiku'}]}]}


class StageFixturesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(self.writable, Path(tmp.name))
        self.workspace = Path(tmp.name) / 'workspace'
        self.workspace.mkdir()
        self.results = Path(tmp.name) / 'results'
        self.results.mkdir(mode=0o700)

    @staticmethod
    def writable(root):
        for path in root.rglob('*'):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755)

    def assert_inputs_only(self, scenario, result):
        terms = stage_fixtures.contract(scenario)
        outcome = Path(result['host_outcome_dir'])
        self.assertEqual(result['staged_inputs'], terms['input_sha256'])
        for name, digest in terms['input_sha256'].items():
            self.assertEqual(hashlib.sha256((outcome / name).read_bytes()).hexdigest(), digest)
        self.assertFalse(set(terms['required_outputs']) & {p.name for p in outcome.iterdir()})
        self.assertTrue(result['outcome_dir'].startswith('/bench/ws/'))

    def test_every_workflow_stages_exactly_its_frozen_inputs(self):
        for scenario in ('workflow-ape', 'workflow-elephant-goldfish', 'workflow-agent-tuneup'):
            with self.subTest(scenario=scenario):
                workspace = self.workspace / scenario
                workspace.mkdir()
                result = stage_fixtures.stage(scenario, workspace, self.results)
                self.assert_inputs_only(scenario, result)
                self.assertIsNone(result['sidecar'])

    def test_ape_sources_are_read_only_git_repositories_on_a_ro_mount(self):
        result = stage_fixtures.stage('workflow-ape', self.workspace, self.results)
        self.assertEqual(result['docker_args'][0], '-v')
        self.assertTrue(result['docker_args'][1].endswith(':/bench/sources:ro'))
        source = Path(result['mounts'][0]['source'])
        for name, relative in (('repo-alpha', 'src/a.py'), ('repo-beta', 'src/b.py')):
            repo = source / name
            self.assertEqual(stat.S_IMODE((repo / relative).stat().st_mode), 0o444)
            self.assertEqual(stat.S_IMODE(repo.stat().st_mode), 0o555)
            head = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                                  check=True).stdout.strip()
            self.assertEqual(result['paths']['sources'][name]['head'], head)
        env = result['agent_env']
        self.assertEqual((env['GIT_CONFIG_COUNT'], env['GIT_CONFIG_KEY_0'], env['GIT_CONFIG_VALUE_1']),
                         ('2', 'safe.directory', '/bench/sources/repo-beta'))

    def git_trace(self, name, build):
        # Issue #58: a detached `git maintenance run --auto` mutates .git after staging returns. The caller's
        # inherited configuration asks for maintenance through both GIT_CONFIG_COUNT and GIT_CONFIG_PARAMETERS.
        trace = self.workspace.parent / f'git-trace-{name}'
        with patch.dict(os.environ, dict(HOSTILE_GIT_CONFIG, GIT_TRACE=str(trace))):
            before = dict(os.environ)
            build()
            self.assertEqual(dict(os.environ), before)
        text = trace.read_text()
        self.assertNotRegex(text, r'run_command: git (maintenance|gc)\b')
        return text

    def test_staged_git_repositories_start_no_background_maintenance(self):
        for scenario, commits in (('workflow-ape', 2), ('negative-missing-delegation', 1)):
            with self.subTest(scenario=scenario):
                workspace = self.workspace / scenario
                workspace.mkdir()
                text = self.git_trace(scenario, lambda: stage_fixtures.stage(scenario, workspace, self.results))
                self.assertEqual(text.count('built-in: git commit'), commits)

    def test_sidecar_fixture_repository_starts_no_background_maintenance(self):
        scenario = github_sidecar.scenario_from_fixture(BABYSITTER)
        text = self.git_trace('sidecar', lambda: github_sidecar.build_fixture_repository(self.results / 'repo', scenario))
        self.assertIn('built-in: git clone', text)

    def test_tuneup_target_is_an_editable_copy_inside_the_workspace(self):
        result = stage_fixtures.stage('workflow-agent-tuneup', self.workspace, self.results)
        target = self.workspace / 'agent-tuneup' / 'target' / 'settings.json'
        self.assertEqual(result['paths']['settings_target'], '/bench/ws/agent-tuneup/target/settings.json')
        self.assertEqual(target.read_bytes(), (WORKFLOWS / 'workflow-agent-tuneup' / 'settings-before.json').read_bytes())

    @unittest.skipUnless(HAVE_OPENSSL, 'openssl CLI unavailable')
    def test_babysitter_stages_repository_sidecar_and_agent_only_host_mapping(self):
        result = stage_fixtures.stage('workflow-babysitter', self.workspace, self.results)
        self.assert_inputs_only('workflow-babysitter', result)
        self.assertEqual(sorted(p.name for p in self.workspace.iterdir()), ['babysitter'],
                         'the agent clones from the sidecar; nothing else is staged in the workspace')
        sidecar = result['sidecar']
        env_file = Path(sidecar['env_file'])
        self.assertTrue(env_file.is_relative_to(self.results))
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        values = dict(l.split('=', 1) for l in env_file.read_text().splitlines())
        served = json.loads(base64.b64decode(values['BENCH_GITHUB_SCENARIO_B64']))
        self.assertEqual(served['pulls'][0]['head_sha'], '1e9721ca7f65fcb51d67f3329e4761da261d563a')
        self.assertEqual(sidecar['tls_names'], ['github.bench.test', 'github.com', 'api.github.com'])
        self.assertEqual(sidecar['agent_add_hosts']['template'],
                         ['--add-host', 'github.com:{sidecar_ip}', '--add-host', 'api.github.com:{sidecar_ip}'])
        self.assertEqual(sidecar['agent_add_hosts']['apply_to'], 'agent container only')
        with tempfile.TemporaryDirectory() as served_root:
            model, _tls = github_sidecar._load_environment(values, Path(served_root))
            bare = model.git_root / 'bench-org' / 'bench-repo.git'
            heads = subprocess.run(['git', '--git-dir', str(bare), 'for-each-ref', '--format=%(refname) %(objectname)'],
                                   capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertIn(f'refs/heads/bench/change {result["paths"]["git_head_commit"]}', heads)
        self.assertTrue(result['paths']['head_matches_git'])
        self.assertEqual(result['paths']['git_base_commit'], 'ab624926987dfb8b302afebae4cc27c14198d37c')
        self.assertEqual(result['paths']['clone_url'], 'https://github.com/bench-org/bench-repo.git')
        self.assertEqual((result['agent_env']['GH_HOST'], result['agent_env']['GH_TOKEN']),
                         ('github.com', 'bench-synthetic-token'))
        self.assertTrue(Path(result['trust']['github_ca']).is_file())

    def test_fixture_repository_commits_are_reproducible(self):
        scenario = github_sidecar.scenario_from_fixture(BABYSITTER)
        first = github_sidecar.build_fixture_repository(self.results / 'one', scenario)
        second = github_sidecar.build_fixture_repository(self.results / 'two', scenario)
        self.assertEqual((first['base_sha'], first['heads']), (second['base_sha'], second['heads']))
        self.assertRegex(first['heads']['bench/change'], r'^[0-9a-f]{40}$')

    def test_negative_missing_delegation_reuses_the_five_stage_workspace(self):
        result = stage_fixtures.stage('negative-missing-delegation', self.workspace, self.results)
        self.assert_inputs_only('negative-missing-delegation', result)
        self.assertTrue((self.workspace / '.git').is_dir())
        self.assertFalse(result['five_stage'].get('reused'))
        status = subprocess.run(['git', '-C', str(self.workspace), 'status', '--porcelain'], capture_output=True,
                                text=True, check=True).stdout
        self.assertEqual(status, '')

    def test_unavailable_review_routing_leaves_no_reviewer_but_keeps_workhorse(self):
        result = stage_fixtures.stage('negative-unavailable-required-review', self.workspace, self.results,
                                      capabilities=CAPABILITIES)
        self.assert_inputs_only('negative-unavailable-required-review', result)
        self.assertEqual(result['paths']['routing'], '/bench/ws/.t3-plugins/routing.json')
        config, sources = routing.effective_config(user_path=self.results / 'absent.json', repo=self.workspace)
        self.assertEqual(sources, [str(self.workspace / '.t3-plugins' / 'routing.json')])
        reviewer = routing.resolve('reviewer', CAPABILITIES, config)
        self.assertEqual(reviewer['candidates'], [])
        self.assertEqual([u['reason'] for u in reviewer['unavailable']], ['provider_absent'])
        workhorse = routing.resolve('workhorse', CAPABILITIES, config)
        # The cheap-family default makes the other provider's haiku-class model work
        # first; the parent's own model stays the last-resort `high` fallback. This case
        # is about the reviewer, not the workhorse.
        self.assertEqual([(c['providerInstanceId'], c['model'], c['tier']) for c in workhorse['candidates']],
                         [('claudeAgent', 'claude-haiku', 'low'), ('codex', 'gpt-luna', 'high')])
        status = subprocess.run(['git', '-C', str(self.workspace), 'status', '--porcelain'], capture_output=True,
                                text=True, check=True).stdout
        self.assertEqual(status, '')

    def test_existing_five_stage_workspace_is_reused_only_when_unchanged(self):
        sys.path.insert(0, str(ROOT / 'bench' / 'v2' / 'tools'))
        import prepare_workspace
        prepare_workspace.prepare(self.workspace)
        result = stage_fixtures.stage('negative-missing-delegation', self.workspace, self.results)
        self.assertTrue(result['five_stage']['reused'])
        other = self.workspace.parent / 'other'
        prepare_workspace.prepare(other)
        (other / 'extra.txt').write_text('drift')
        with self.assertRaisesRegex(ValueError, 'not the frozen five-stage fixture'):
            stage_fixtures.stage('negative-missing-delegation', other, self.workspace.parent / 'results2')

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, 'capabilities'):
            stage_fixtures.stage('negative-unavailable-required-review', self.workspace, self.results)
        with self.assertRaisesRegex(ValueError, 'unknown'):
            stage_fixtures.stage('five-stage', self.workspace, self.results)
        with self.assertRaisesRegex(ValueError, 'outside the worker workspace'):
            stage_fixtures.stage('workflow-ape', self.workspace, self.workspace / 'results')
        (self.workspace / 'stray').write_text('x')
        with self.assertRaisesRegex(ValueError, 'empty workspace'):
            stage_fixtures.stage('workflow-ape', self.workspace, self.results)
        bad = dict(CAPABILITIES, providers=CAPABILITIES['providers'] + [
            {'providerInstanceId': 'reviewer-1', 'driverKind': 'grok', 'canRunChildTask': True,
             'models': [{'id': 'reviewer-1'}]}])
        with self.assertRaisesRegex(ValueError, 'reviewer-1'):
            stage_fixtures.unavailable_review_routing(bad)


def capabilities_message(request_id=7, layout=None, structured=True):
    catalog = json.loads(json.dumps(CAPABILITIES))
    text = json.dumps(catalog, **(layout or {'separators': (',', ':')}))
    result = {'content': [{'type': 'text', 'text': text}]}
    if structured:
        result['structuredContent'] = catalog
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


class McpShimRewriteTest(unittest.TestCase):
    def test_only_the_named_scenario_enables_the_shim(self):
        self.assertTrue(mcp_shim.enabled_for('negative-missing-delegation'))
        for other in ('negative-unavailable-required-review', 'workflow-ape', 'five-stage'):
            self.assertFalse(mcp_shim.enabled_for(other))
            self.assertEqual(mcp_shim.container_args(other, 'codex', Path('/nonexistent')), [])
        with tempfile.TemporaryDirectory() as tmp:
            args = mcp_shim.container_args('negative-missing-delegation', 'codex', Path(tmp))
            source = Path(args[1].split(':', 1)[0])
            self.assertEqual(args[1].split(':', 1)[1], '/run/bench-shim/mcp-shim.json:ro')
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)
            self.assertEqual(mcp_shim.load_config(str(source))['provider_instance_id'], 'codex')
            self.assertIsNone(mcp_shim.load_config(str(Path(tmp) / 'absent.json')))

    def test_rewrite_flips_only_the_parent_providers_field_in_both_forms(self):
        for layout in ({'separators': (',', ':')}, {'indent': 2}):
            with self.subTest(layout=layout):
                message = capabilities_message(layout=layout)
                updated, record = mcp_shim.rewrite_capabilities_result(message, 'codex')
                self.assertEqual(record['event'], 'capabilities_rewrite')
                self.assertTrue(record['text_format_preserved'])
                self.assertEqual(record['changed_paths'], ['result.content[0].text.providers[0].canRunChildTask',
                                                           'result.structuredContent.providers[0].canRunChildTask'])
                text = json.loads(updated['result']['content'][0]['text'])
                for catalog in (text, updated['result']['structuredContent']):
                    self.assertIs(catalog['providers'][0]['canRunChildTask'], False)
                    self.assertIs(catalog['providers'][1]['canRunChildTask'], True)
                    self.assertEqual(catalog['providers'][0]['models'], [{'id': 'gpt-luna'}])
                    self.assertEqual(catalog['inheritedModel'], 'gpt-luna')
                self.assertIs(message['result']['structuredContent']['providers'][0]['canRunChildTask'], True,
                              'the original response is not mutated')
                self.assertEqual(updated['result']['content'][0]['text'],
                                 json.dumps(text, **layout))

    def test_preconditions_refuse_without_changing_the_response(self):
        absent = capabilities_message()
        already = capabilities_message()
        for form in (already['result']['structuredContent'], ):
            form['providers'][0]['canRunChildTask'] = False
        error = {'jsonrpc': '2.0', 'id': 1, 'result': {'isError': True, 'content': []}}
        for message, pid, reason in ((absent, 'missing', 'not listed'), (already, 'codex', 'was not true'),
                                     (error, 'codex', 'error')):
            with self.subTest(reason=reason):
                updated, record = mcp_shim.rewrite_capabilities_result(message, pid)
                self.assertIs(updated, message)
                self.assertEqual(record['event'], 'capabilities_refused')
                self.assertIn(reason, record['reason'])

    def test_claude_argv_and_codex_requests_are_redirected(self):
        records = []
        url_for = lambda url: 'http://127.0.0.1:9999/mcp'  # noqa: E731
        config = {'mcpServers': {'t3-code': {'type': 'http', 'url': 'http://127.0.0.1:3773/mcp',
                                             'headers': {'Authorization': 'Bearer secret-token'}}}}
        argv = ['--model', 'm', '--mcp-config', json.dumps(config), '--strict-mcp-config']
        rewritten = mcp_shim.rewrite_claude_argv(argv, url_for, records.append)
        self.assertEqual(rewritten[:3] + rewritten[4:], argv[:3] + argv[4:])
        server = json.loads(rewritten[3])['mcpServers']['t3-code']
        self.assertEqual(server, dict(config['mcpServers']['t3-code'], url='http://127.0.0.1:9999/mcp'))
        line = json.dumps({'id': 3, 'method': 'thread/start', 'params': {'model': 'gpt-luna', 'config': {
            'mcp_servers': {'t3-code': {'url': 'http://127.0.0.1:3773/mcp',
                                        'http_headers': {'Authorization': 'Bearer secret-token'}}}}}}).encode() + b'\n'
        changed = json.loads(mcp_shim.rewrite_codex_line(line, url_for, records.append))
        self.assertEqual(changed['params']['config']['mcp_servers']['t3-code']['url'], 'http://127.0.0.1:9999/mcp')
        self.assertEqual(changed['params']['model'], 'gpt-luna')
        untouched = b'{"id":4,"method":"turn/start","params":{"input":"thread/start"}}\n'
        self.assertEqual(mcp_shim.rewrite_codex_line(untouched, url_for, records.append), untouched)
        self.assertEqual([r['event'] for r in records], ['upstream_redirect', 'upstream_redirect'])
        self.assertNotIn('secret-token', json.dumps(records))


class FakeMcp(BaseHTTPRequestHandler):
    """A T3-like MCP endpoint: JSON or SSE replies, records what it was sent."""
    protocol_version = 'HTTP/1.1'
    seen = []

    def log_message(self, *_args):
        return

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        FakeMcp.seen.append({'authorization': self.headers.get('Authorization'), 'body': body})
        if body.get('method') == 'tools/call' and body['params']['name'] == 'orchestrator_capabilities':
            reply = capabilities_message(body['id'], structured=False)
        else:
            reply = {'jsonrpc': '2.0', 'id': body.get('id'),
                     'result': {'content': [{'type': 'text', 'text': json.dumps(CAPABILITIES)}]}}
        data = json.dumps(reply).encode()
        if self.headers.get('Accept') == 'text/event-stream':
            payload = b'event: message\nid: 1\ndata: ' + data + b'\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Mcp-Session-Id', 'session-1')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Mcp-Session-Id', 'session-1')
            self.end_headers()
            self.wfile.write(data)


class McpShimProxyTest(unittest.TestCase):
    def setUp(self):
        FakeMcp.seen = []
        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), FakeMcp)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.log = mcp_shim.Log(str(self.tmp / 'shim.jsonl'))
        self.pool = mcp_shim.ProxyPool('codex', self.log)
        self.addCleanup(self.pool.close)
        self.url = self.pool.url_for(f'http://127.0.0.1:{self.upstream.server_address[1]}/mcp')

    def call(self, name, accept='application/json'):
        body = json.dumps({'jsonrpc': '2.0', 'id': 11, 'method': 'tools/call',
                           'params': {'name': name, 'arguments': {}}}).encode()
        request = urllib.request.Request(self.url, body, method='POST', headers={
            'Authorization': 'Bearer token-123', 'Content-Type': 'application/json', 'Accept': accept})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.headers, response.read().decode()

    def test_json_and_sse_capability_replies_are_rewritten_and_audited(self):
        headers, text = self.call('orchestrator_capabilities')
        self.assertEqual(headers['Mcp-Session-Id'], 'session-1')
        catalog = json.loads(json.loads(text)['result']['content'][0]['text'])
        self.assertIs(catalog['providers'][0]['canRunChildTask'], False)
        _, stream = self.call('orchestrator_capabilities', 'text/event-stream')
        self.assertTrue(stream.startswith('event: message\nid: 1\ndata: '))
        data = json.loads(stream.split('data: ', 1)[1])
        self.assertIs(json.loads(data['result']['content'][0]['text'])['providers'][0]['canRunChildTask'], False)
        self.assertEqual([s['authorization'] for s in FakeMcp.seen], ['Bearer token-123'] * 2)
        log = (self.tmp / 'shim.jsonl').read_text()
        self.assertNotIn('token-123', log)
        self.assertEqual(stat.S_IMODE((self.tmp / 'shim.jsonl').stat().st_mode), 0o600)
        audit = mcp_shim.audit_log(log, 'codex')
        self.assertEqual((audit['rewrites'], audit['refusals'], audit['verified']), (2, 0, True))
        self.assertFalse(mcp_shim.audit_log(log, 'claudeAgent')['verified'])

    def test_other_tools_pass_through_unchanged(self):
        _, text = self.call('t3_thread_read')
        catalog = json.loads(json.loads(text)['result']['content'][0]['text'])
        self.assertIs(catalog['providers'][0]['canRunChildTask'], True)
        self.assertFalse((self.tmp / 'shim.jsonl').exists())
        self.assertFalse(mcp_shim.audit_log('', 'codex')['verified'])

    def write_child(self, body):
        script = self.tmp / 'fake-cli'
        script.write_text(f'#!{sys.executable}\n' + body)
        script.chmod(0o755)
        return str(script)

    def test_run_relays_codex_stdin_through_the_proxy(self):
        real = self.write_child('import sys, json\nline = sys.stdin.readline()\n'
                                'print(json.loads(line)["params"]["config"]["mcp_servers"]["t3-code"]["url"])\n'
                                'print(sys.stdin.readline().strip())\nsys.exit(7)\n')
        start = json.dumps({'id': 1, 'method': 'thread/start', 'params': {'config': {'mcp_servers': {'t3-code': {
            'url': f'http://127.0.0.1:{self.upstream.server_address[1]}/mcp'}}}}}).encode()
        out = self.tmp / 'out.txt'
        with out.open('wb') as stdout:
            code = mcp_shim.run('codex', ['app-server'], {'provider_instance_id': 'codex'}, real=real, log=self.log,
                                stdin=io.BytesIO(start + b'\n{"id":2,"method":"ping"}\n'), stdout=stdout)
        seen, passthrough = out.read_text().splitlines()
        self.assertEqual(code, 7)
        self.assertRegex(seen, r'^http://127\.0\.0\.1:\d+/mcp$')
        self.assertNotEqual(seen, f'http://127.0.0.1:{self.upstream.server_address[1]}/mcp')
        self.assertEqual(passthrough, '{"id":2,"method":"ping"}')

    def test_run_rewrites_claude_mcp_config_argument(self):
        real = self.write_child('import sys, json\nconfig = json.loads(sys.argv[sys.argv.index("--mcp-config") + 1])\n'
                                'print(config["mcpServers"]["t3-code"]["url"])\n')
        config = json.dumps({'mcpServers': {'t3-code': {'type': 'http', 'url': 'http://127.0.0.1:3773/mcp'}}})
        out = self.tmp / 'out.txt'
        with out.open('wb') as stdout:
            code = mcp_shim.run('claude', ['--mcp-config', config], {'provider_instance_id': 'claudeAgent'},
                                real=real, log=self.log, stdout=stdout)
        self.assertEqual(code, 0)
        self.assertRegex(out.read_text().strip(), r'^http://127\.0\.0\.1:\d+/mcp$')
        events = [json.loads(l)['event'] for l in (self.tmp / 'shim.jsonl').read_text().splitlines()]
        self.assertEqual(events, ['shim_start', 'upstream_redirect'])


class AgentHostMappingTest(unittest.TestCase):
    def test_real_names_map_only_to_a_private_sidecar_address(self):
        self.assertEqual(github_sidecar.agent_host_args('172.30.0.5'),
                         ['--add-host', 'github.com:172.30.0.5', '--add-host', 'api.github.com:172.30.0.5'])
        for bad in ('127.0.0.1', '0.0.0.0', '8.8.8.8', '169.254.1.1', 'github.com'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                github_sidecar.agent_host_args(bad)
        command = github_sidecar.sidecar_ip_command('t3-issue28-github-x', 't3-issue28-private-x')
        self.assertEqual(command[-1], 't3-issue28-github-x')
        self.assertIn('"t3-issue28-private-x"', command[3])


class ConnectProxy(BaseHTTPRequestHandler):
    """Test stand-in for the agent's `--add-host` entries: CONNECT to github.com:443 or
    api.github.com:443 reaches the loopback sidecar; every other target is refused."""
    routes = {}
    seen = []

    def log_message(self, *_args):
        return

    def do_CONNECT(self):
        ConnectProxy.seen.append(self.path)
        if self.path not in self.routes:
            self.send_error(403)
            return
        upstream = socket.create_connection(self.routes[self.path], timeout=30)
        self.send_response(200, 'Connection established')
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                readable, _, _ = select.select([self.connection, upstream], [], [], 30)
                if not readable:
                    return
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        finally:
            upstream.close()


GH_STUB = '''#!/bin/sh
# Local credential reads only, as the scripts use gh; no network.
case "$1 $2" in
  "auth token") printf '%s\\n' "$GH_TOKEN" ;;
  "auth status") exit 0 ;;
  "auth git-credential") cat >/dev/null; printf 'username=x-access-token\\npassword=%s\\n' "$GH_TOKEN" ;;
  *) echo "gh stub: unsupported $*" >&2; exit 1 ;;
esac
'''


@unittest.skipUnless(HAVE_OPENSSL and shutil.which('jq') and shutil.which('curl') and shutil.which('bash')
                     and subprocess.run(['git', 'http-backend'], capture_output=True,
                                        env={'PATH': os.environ.get('PATH', ''), 'REQUEST_METHOD': 'GET'}).returncode
                     != 128, 'openssl, jq, curl, bash or git http-backend unavailable')
class BabysitterScriptsAgainstSidecarTest(unittest.TestCase):
    """The unmodified babysitter scripts talk to the sidecar as github.com/api.github.com.

    In the container, `--add-host` points both names at the sidecar on port 443. Here a
    CONNECT proxy does the same for the scripts' curl and git, and the per-run CA is
    trusted through CURL_CA_BUNDLE and GIT_SSL_CAINFO. The scripts are run as shipped.
    """
    SCRIPTS = ROOT / 'plugins' / 'babysitter' / 'scripts'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.tls = github_sidecar.tls_material(self.tmp / 'tls')
        self.frozen = github_sidecar.scenario_from_fixture(BABYSITTER)
        self.commits = github_sidecar.build_fixture_repository(self.tmp / 'built', self.frozen)
        self.bundle = github_sidecar.git_bundle(self.commits['bare'])
        (self.tmp / 'bin').mkdir()
        (self.tmp / 'bin' / 'gh').write_text(GH_STUB)
        (self.tmp / 'bin' / 'gh').chmod(0o755)
        (self.tmp / 'home').mkdir()
        (self.tmp / 'gitconfig').write_text('')
        ConnectProxy.seen = []

    def serve(self, scenario):
        """Start the sidecar from the same env-file values `stage()` writes, plus the proxy."""
        env_file = github_sidecar.write_env_file(self.tmp / f'sidecar-{len(list(self.tmp.glob("sidecar-*")))}.env',
                                                 scenario, self.tls, self.bundle)
        values = dict(l.split('=', 1) for l in env_file.read_text().splitlines())
        served = Path(tempfile.mkdtemp(dir=self.tmp))
        model, tls = github_sidecar._load_environment(values, served)
        self.stream = io.StringIO()
        log = github_sidecar.EventLog(self.stream)
        log.write({'event': 'ready'})
        sidecar = github_sidecar.serve(model, log, 0, github_sidecar.tls_context(*tls), address='127.0.0.1')
        self.addCleanup(sidecar.server_close)
        self.addCleanup(sidecar.shutdown)
        address = ('127.0.0.1', sidecar.server_address[1])
        ConnectProxy.routes = {'github.com:443': address, 'api.github.com:443': address}
        proxy = ThreadingHTTPServer(('127.0.0.1', 0), ConnectProxy)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        self.addCleanup(proxy.server_close)
        self.addCleanup(proxy.shutdown)
        proxy_url = f'http://127.0.0.1:{proxy.server_address[1]}'
        ca = str(self.tls['ca_cert'])
        self.env = {'PATH': f'{self.tmp / "bin"}:{os.environ.get("PATH", "")}', 'HOME': str(self.tmp / 'home'),
                    'TMPDIR': str(self.tmp), 'LANG': 'C.UTF-8', 'GH_TOKEN': 'bench-synthetic-token',
                    'HTTPS_PROXY': proxy_url, 'https_proxy': proxy_url, 'NO_PROXY': '', 'no_proxy': '',
                    'CURL_CA_BUNDLE': ca, 'SSL_CERT_FILE': ca, 'GIT_SSL_CAINFO': ca,
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(self.tmp / 'gitconfig'),
                    'GIT_TERMINAL_PROMPT': '0', 'BABYSITTER_RETRY_BASE_SECS': '0'}

    def amended(self, resolved=False, passing=False):
        """The frozen scenario with the fixture repository's real commit IDs."""
        scenario = json.loads(json.dumps(self.frozen))
        pull = scenario['pulls'][0]
        pull['head_sha'] = self.commits['heads'][pull['head_ref']]
        pull['base_sha'] = self.commits['base_sha']
        for check in pull['checks']:
            check['sha'] = pull['head_sha']
            check['conclusion'] = 'success' if passing else check['conclusion']
        for thread in pull['threads']:
            thread['resolved'] = resolved
        return scenario

    def script(self, name, *args, cwd=None):
        return subprocess.run(['bash', str(self.SCRIPTS / name), *args], env=self.env, cwd=cwd or self.tmp,
                              capture_output=True, text=True, timeout=120)

    def events(self, kind):
        return [json.loads(l) for l in self.stream.getvalue().splitlines() if json.loads(l)['event'] == kind]

    def test_list_prs_reads_the_frozen_pr_from_api_github_com(self):
        self.serve(self.frozen)
        single = self.script('list-prs.sh', '--repo', 'bench-org/bench-repo', '--pr', '1')
        self.assertEqual(single.returncode, 0, single.stderr)
        row = json.loads(single.stdout)
        self.assertEqual((row['head_oid'], row['failing'], row['unresolved_threads'], row['mine'], row['checks_state']),
                         ('1e9721ca7f65fcb51d67f3329e4761da261d563a', ['unit'], 1, True, 'FAILURE'))
        swept = self.script('list-prs.sh', '--repo', 'bench-org/bench-repo')
        self.assertEqual(swept.returncode, 0, swept.stderr)
        self.assertEqual([json.loads(l)['number'] for l in swept.stdout.splitlines()], [1])
        self.assertEqual({e['host'] for e in self.events('read')}, {'api.github.com'})
        self.assertEqual(set(ConnectProxy.seen), {'api.github.com:443'})
        host = github_sidecar.observations_from_log(self.stream.getvalue())
        self.assertEqual((host['post_calls'], host['merge_calls'], host['observed_head_sha']), ([], [], '1e9721ca7f65fcb51d67f3329e4761da261d563a'))

    def test_pr_workspace_clones_and_fetches_from_github_com_and_pushes_are_refused(self):
        self.serve(self.frozen)
        root = self.tmp / 'babysitter'
        args = ('--repo', 'bench-org/bench-repo', '--pr', '1', '--branch', 'bench/change', '--root', str(root))
        first = self.script('pr-workspace.sh', *args)
        self.assertEqual(first.returncode, 0, first.stderr)
        worktree = Path(first.stdout.strip())
        head = subprocess.run(['git', '-C', str(worktree), 'rev-parse', 'HEAD'], env=self.env, capture_output=True,
                              text=True, check=True).stdout.strip()
        self.assertEqual(head, self.commits['heads']['bench/change'])
        again = self.script('pr-workspace.sh', *args)
        self.assertEqual((again.returncode, again.stdout.strip()), (0, str(worktree)), again.stderr)
        self.assertIn('reused', again.stderr)
        (worktree / 'fix.txt').write_text('agent change\n')
        subprocess.run(['git', '-C', str(worktree), 'add', 'fix.txt'], env=self.env, check=True)
        subprocess.run(['git', '-C', str(worktree), '-c', 'user.name=bench', '-c', 'user.email=bench@example.invalid',
                        'commit', '-q', '-m', 'agent change'], env=self.env, check=True)
        push = subprocess.run(['git', '-C', str(worktree), 'push', 'origin', 'HEAD:bench/change'], env=self.env,
                              capture_output=True, text=True, timeout=60)
        self.assertNotEqual(push.returncode, 0)
        reads = [e for e in self.events('read') if 'git' in e]
        self.assertTrue(reads and {e['host'] for e in reads} == {'github.com'})
        self.assertTrue(all(e['status'] == 200 for e in reads), reads)
        self.assertEqual([e['operation'] for e in self.events('post')], ['git-receive-pack'])
        host = github_sidecar.observations_from_log(self.stream.getvalue())
        self.assertEqual([c['operation'] for c in host['post_calls']], ['git-receive-pack'])
        self.assertEqual(set(ConnectProxy.seen), {'github.com:443'})

    def test_merge_pr_reads_the_refrozen_git_head_and_blocks_on_the_open_thread(self):
        # Owner-delegated Stage 6 amendment: the frozen head is now the deterministic fixture commit.
        self.assertEqual(self.frozen['pulls'][0]['head_sha'], self.commits['heads']['bench/change'])
        self.serve(self.frozen)
        result = self.script('merge-pr.sh', '--repo', 'bench-org/bench-repo', '--pr', '1')
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn('BLOCKED bench-org/bench-repo#1 reason=unanswered_threads', result.stdout)
        self.assertEqual((self.events('post'), self.events('merge')), ([], []))

    def test_merge_pr_graphql_state_and_resolution_with_a_real_head_sha(self):
        self.serve(self.amended())
        head = self.commits['heads']['bench/change']
        blocked = self.script('merge-pr.sh', '--repo', 'bench-org/bench-repo', '--pr', '1')
        self.assertEqual(blocked.returncode, 4, blocked.stdout + blocked.stderr)
        self.assertIn('BLOCKED bench-org/bench-repo#1 reason=unanswered_threads', blocked.stdout)
        self.assertIn('threads=thread-1', blocked.stdout)
        self.assertEqual((self.events('post'), self.events('merge')), ([], []))
        resolve = self.script('merge-pr.sh', '--repo', 'bench-org/bench-repo', '--pr', '1',
                              '--resolve-thread', 'thread-1', '--verified-head', head)
        self.assertEqual(resolve.returncode, 3, resolve.stdout + resolve.stderr)
        self.assertIn('thread resolution failed', resolve.stderr)
        self.assertEqual([e['operation'] for e in self.events('post')], ['graphql:resolveReviewThread'])
        self.assertEqual({e['host'] for e in self.events('read')}, {'api.github.com'})

    def test_merge_pr_merge_attempts_are_refused_and_logged(self):
        self.serve(self.amended(resolved=True, passing=True))
        result = self.script('merge-pr.sh', '--repo', 'bench-org/bench-repo', '--pr', '1')
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn('BLOCKED bench-org/bench-repo#1 reason=unknown', result.stdout)
        operations = [e['operation'] for e in self.events('merge')]
        self.assertEqual(operations.count('PUT /repos/bench-org/bench-repo/pulls/1/merge'), 3)
        self.assertEqual(operations.count('graphql:enablePullRequestAutoMerge'), 3)
        host = github_sidecar.observations_from_log(self.stream.getvalue())
        self.assertEqual(len(host['merge_calls']), 6)
        self.assertEqual(set(ConnectProxy.seen), {'api.github.com:443'})


if __name__ == '__main__':
    unittest.main()
