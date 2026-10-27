#!/usr/bin/env python3
"""One read-only org sweep. JSON only; 0=complete, 2=usage, 3=incomplete.

GitHub CLI supplies authentication. No models, dispatch, mutations, scheduler, or
cached PR state. Connections are paginated, including checks and review threads.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


RATE = 'rateLimit { cost remaining resetAt }'
PAGE = 'totalCount pageInfo { hasNextPage endCursor }'
THREADS = 'nodes { id isResolved isOutdated }'
CONTEXTS = '''nodes { __typename
  ... on CheckRun { id name status conclusion detailsUrl }
  ... on StatusContext { id context state targetUrl }
}'''
PR_FIELDS = '''id number url title state isDraft isCrossRepository headRefOid headRefName
  baseRefOid baseRefName
  repository { nameWithOwner } headRepository { nameWithOwner }
  autoMergeRequest { enabledAt } mergeable
  mergeStateStatus reviewDecision
  reviewThreads(first:100) { %s %s }
  commits(last:1) { nodes { commit { oid statusCheckRollup {
    state contexts(first:100) { %s %s }
  } } } }
''' % (PAGE, THREADS, PAGE, CONTEXTS)
PENDING = {'QUEUED', 'IN_PROGRESS', 'WAITING', 'PENDING', 'REQUESTED'}
PASS = {'SUCCESS', 'NEUTRAL', 'SKIPPED'}
FAIL = {'FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT', 'STALE',
        'STARTUP_FAILURE', 'ACTION_REQUIRED'}


class ScanError(Exception):
    """A safe, machine-readable gap, containing no command output or credentials."""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


class GitHub:
    def __init__(self, args):
        self.args = args
        self.requests = self.cost = 0
        self.remaining = self.reset_at = None
        self.started = time.monotonic()
        self.last_request = None

    def query(self, query, variables=None, estimate=1, *, mutation=False):
        # A conservative point estimate is checked before each call. The server's
        # actual charge is recorded afterward; GitHub can change its cost formula.
        for attempt in range(1 if mutation else 3):
            if self.requests >= self.args.max_requests:
                raise ScanError('request-budget')
            if self.cost + estimate > self.args.max_cost:
                raise ScanError('cost-budget')
            if self.remaining is not None and self.remaining - estimate < self.args.reserve:
                raise ScanError('rate-reserve')
            delay = max(0, (self.last_request or 0) + self.args.spacing - time.monotonic())
            if attempt:
                delay = max(delay, 2 ** attempt)
            remaining_time = self.args.deadline - (time.monotonic() - self.started) - delay
            if remaining_time <= 0:
                raise ScanError('deadline')
            if delay:
                time.sleep(delay)
            self.requests += 1
            self.last_request = time.monotonic()
            try:
                proc = subprocess.run(
                    ['gh', 'api', 'graphql', '--input', '-'],
                    input=json.dumps({'query': query, 'variables': variables or {}}),
                    text=True, capture_output=True, timeout=min(30, remaining_time))
            except FileNotFoundError:
                raise ScanError('gh-unavailable') from None
            except subprocess.TimeoutExpired:
                # A timed-out query may still have consumed points.
                self.cost += estimate
                if self.remaining is not None:
                    self.remaining -= estimate
                if attempt < 2:
                    continue
                raise ScanError('github-timeout') from None
            try:
                payload = json.loads(proc.stdout)
            except ValueError:
                payload = {}
            data = payload.get('data') if isinstance(payload, dict) else None
            rate = data.get('rateLimit') if isinstance(data, dict) else None
            valid_rate = (isinstance(rate, dict) and type(rate.get('cost')) is int
                          and type(rate.get('remaining')) is int)
            if valid_rate:
                self.cost += rate['cost']
                self.remaining, self.reset_at = rate['remaining'], rate.get('resetAt')
            else:
                self.cost += estimate
                if self.remaining is not None:
                    self.remaining -= estimate
            errors = payload.get('errors') if isinstance(payload, dict) else None
            # Do not print server/CLI messages: they may contain private data.
            error_text = json.dumps(errors or []) + proc.stderr
            if re.search(r'rate.?limit|HTTP (403|429)', error_text, re.I):
                raise ScanError('github-rate-limit-or-denied')
            if errors:
                raise ScanError('graphql-errors')  # Never trust partial GraphQL data.
            if proc.returncode:
                if re.search(r'HTTP (502|503|504)', error_text) and attempt < 2:
                    continue
                raise ScanError('github-command-failed')
            if (not mutation and not valid_rate) or not isinstance(data, dict):
                raise ScanError('missing-rate-data')
            return data
        raise ScanError('github-unavailable')

    def report(self):
        return {'requests': self.requests, 'cost': self.cost, 'remaining': self.remaining,
                'reset_at': self.reset_at, 'max_requests': self.args.max_requests,
                'max_cost': self.args.max_cost, 'reserve': self.args.reserve}


def page(connection):
    """Reject missing pagination and counts rather than silently claiming a full read."""
    if not isinstance(connection, dict):
        raise ScanError('missing-connection')
    nodes, info, total = connection.get('nodes'), connection.get('pageInfo'), connection.get('totalCount')
    if (not isinstance(nodes, list) or any(not isinstance(n, dict) for n in nodes)
            or not isinstance(info, dict) or type(info.get('hasNextPage')) is not bool
            or type(total) is not int or total < 0):
        raise ScanError('malformed-connection')
    cursor = info.get('endCursor') if info['hasNextPage'] else None
    if info['hasNextPage'] and not isinstance(cursor, str):
        raise ScanError('missing-cursor')
    return nodes, cursor, total


def collect(connection, fetch):
    nodes, cursor, total = page(connection)
    seen = set()
    while cursor is not None:
        if cursor in seen:
            raise ScanError('repeated-cursor')
        seen.add(cursor)
        more, cursor, new_total = page(fetch(cursor))
        if new_total != total:
            raise ScanError('connection-changed')
        nodes.extend(more)
    if len(nodes) != total or len({n.get('id') for n in nodes}) != len(nodes):
        raise ScanError('connection-count-mismatch')
    return nodes


def rollup(node):
    commits = node['commits']['nodes']
    if len(commits) != 1 or commits[0]['commit']['oid'] != node['headRefOid']:
        raise ScanError('head-changed')
    return commits[0]['commit']['statusCheckRollup']


def tail(api, node, kind, cursor):
    if kind == 'threads':
        field = 'reviewThreads(first:100,after:$cursor) { %s %s }' % (PAGE, THREADS)
    else:
        field = '''commits(last:1) { nodes { commit { oid statusCheckRollup {
          state contexts(first:100,after:$cursor) { %s %s }
        } } } }''' % (PAGE, CONTEXTS)
    data = api.query('query($id:ID!,$cursor:String!) { node(id:$id) { ... on PullRequest '
                     '{ id state isDraft headRefOid %s } } %s }' % (field, RATE),
                     {'id': node['id'], 'cursor': cursor})
    current = data.get('node')
    if (not current or current['headRefOid'] != node['headRefOid']
            or current['state'] != 'OPEN' or current['isDraft']):
        raise ScanError('pr-changed-during-pagination')
    if kind == 'threads':
        return current['reviewThreads']
    checks = rollup(current)
    if checks is None:
        raise ScanError('checks-disappeared')
    return checks['contexts']


def classify(node, api):
    row = {'repo': node['repository']['nameWithOwner'], 'number': node['number'],
           'node_id': node['id'], 'head_ref': node['headRefName'],
           'head_repo': (node.get('headRepository') or {}).get('nameWithOwner'),
           'url': node['url'], 'title': node['title'], 'head_sha': node['headRefOid'],
           'base_sha': node.get('baseRefOid'), 'base_ref': node.get('baseRefName'),
           'state': node['state'], 'draft': node['isDraft'],
           'fork': node['isCrossRepository'], 'reasons': [], 'unknowns': [],
           'coordinator_actions': [], 'failing_checks': [], 'pending_checks': [],
           'unresolved_thread_ids': [], 'review_decision': node['reviewDecision'],
           'mergeable': node['mergeable'], 'merge_state_status': node['mergeStateStatus']}
    if not row['head_sha']:
        row['unknowns'].append('missing-head')
    row['auto_merge'] = node['autoMergeRequest'] is not None
    if node['state'] in {'MERGED', 'CLOSED'}:
        row.update(checks='none', action='lifecycle')
        row['observation_key'] = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        return row
    if not row['auto_merge']:
        row['coordinator_actions'].append('enable-auto-merge')
    if node['mergeable'] == 'CONFLICTING' or node['mergeStateStatus'] == 'DIRTY':
        row['reasons'].append('merge-conflict')
    elif node['mergeable'] != 'MERGEABLE':
        row['unknowns'].append('mergeability-unknown')
    if node['reviewDecision'] == 'CHANGES_REQUESTED':
        row['reasons'].append('changes-requested')
    elif node['reviewDecision'] == 'REVIEW_REQUIRED':
        row['coordinator_actions'].append('required-review')
    # Keep known adverse evidence if a later page fails. Incompleteness never
    # erases a failure on a page that was successfully read at this head.
    threads = node['reviewThreads'].get('nodes', [])
    try:
        threads = collect(node['reviewThreads'], lambda c: tail(api, node, 'threads', c))
    except ScanError as exc:
        row['unknowns'].append('threads:' + str(exc))
    row['unresolved_thread_ids'] = sorted(t['id'] for t in threads if t.get('isResolved') is False)
    if any(type(t.get('isResolved')) is not bool for t in threads):
        row['unknowns'].append('thread-resolution-unknown')
    if row['unresolved_thread_ids']:
        row['reasons'].append('unresolved-threads')
    contexts = []
    try:
        checks = rollup(node)
        if checks is not None:
            contexts = checks['contexts'].get('nodes', [])
            contexts = collect(checks['contexts'], lambda c: tail(api, node, 'checks', c))
    except ScanError as exc:
        row['unknowns'].append('checks:' + str(exc))
    for context in contexts:
        kind = context.get('__typename')
        name = context.get('name') if kind == 'CheckRun' else context.get('context')
        state = context.get('conclusion') if kind == 'CheckRun' else context.get('state')
        if kind == 'CheckRun' and context.get('status') != 'COMPLETED':
            # Pending runs have no conclusion. An inconsistent combination is
            # unknown rather than silently accepted as a pass or a pending run.
            state = context.get('status') if state is None else 'UNKNOWN'
        detail = {'id': context.get('id'), 'name': name, 'state': state}
        failed = FAIL if kind == 'CheckRun' else {'FAILURE', 'ERROR'}
        pending_states = PENDING if kind == 'CheckRun' else {'PENDING', 'EXPECTED'}
        passed = PASS if kind == 'CheckRun' else {'SUCCESS'}
        if kind not in {'CheckRun', 'StatusContext'} or not name:
            row['unknowns'].append('check-context-unknown')
        elif state in failed:
            row['failing_checks'].append(detail)
        elif state in pending_states:
            row['pending_checks'].append(detail)
        elif state not in passed:
            row['unknowns'].append('check-state-unknown:' + name)
    for key in ('failing_checks', 'pending_checks'):
        row[key].sort(key=lambda c: (c['name'], c['id'] or ''))
    if row['failing_checks']:
        row['reasons'].append('failing-checks')
    row['checks'] = ('failed' if row['failing_checks'] else 'unknown' if any(
        s.startswith('checks:') or s.startswith('check-') for s in row['unknowns'])
        else 'pending' if row['pending_checks'] else 'passed' if contexts else 'none')
    # Keep opaque protection/merge-queue state visible without inventing a code fix.
    if node['mergeStateStatus'] not in {'CLEAN', 'UNSTABLE', 'DIRTY', 'BEHIND'} and not (
            row['reasons'] or row['pending_checks'] or row['coordinator_actions'] or row['unknowns']):
        row['coordinator_actions'].append('inspect-merge-gate')
    if node['mergeStateStatus'] == 'BEHIND':
        row['coordinator_actions'].append('update-branch')
    row['reasons'].sort()
    row['unknowns'] = sorted(set(row['unknowns']))
    row['coordinator_actions'].sort()
    row['action'] = ('dispatch' if row['reasons'] and row['head_sha'] else
                     'unknown' if row['unknowns'] else
                     'coordinator' if row['coordinator_actions'] else
                     'waiting' if row['pending_checks'] else 'healthy')
    row['observation_key'] = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
    return row


def targeted(api, known):
    owner, name = known['repo'].split('/')
    data = api.query('''query($owner:String!,$name:String!,$number:Int!) {
      repository(owner:$owner,name:$name) { pullRequest(number:$number) { %s } } %s
    }''' % (PR_FIELDS, RATE), {'owner': owner, 'name': name, 'number': known['number']})
    node = (data.get('repository') or {}).get('pullRequest')
    if not node or node.get('url') != known['url'] or node.get('state') not in {'OPEN', 'MERGED', 'CLOSED'}:
        raise ScanError('targeted-lifecycle-unavailable')
    return classify(node, api)


def scan(api, org, *, include_drafts=False, repository=None, repository_offset=0):
    result = {'schema_version': 1, 'org': org, 'started_at': utc_now(),
              'complete': False, 'gaps': [], 'prs': [], 'repositories': 0}
    try:
        api.query('query { %s }' % RATE)  # Check the shared budget before a large query.
        def repos(cursor):
            data = api.query('''query($org:String!,$cursor:String) {
              organization(login:$org) { repositories(first:100,after:$cursor,
                orderBy:{field:NAME,direction:ASC}) { %s nodes { id nameWithOwner } } } %s
            }''' % (PAGE, RATE), {'org': org, 'cursor': cursor})
            if not data.get('organization'):
                raise ScanError('organization-inaccessible')
            return data['organization']['repositories']
        if repository:
            owner, name = repository.split('/')
            data = api.query('''query($owner:String!,$name:String!) {
              repository(owner:$owner,name:$name) { id nameWithOwner } %s
            }''' % RATE, {'owner': owner, 'name': name})
            if not data.get('repository') or data['repository']['nameWithOwner'].lower() != repository.lower():
                raise ScanError('repository-inaccessible')
            repositories = [data['repository']]
        else:
            repositories = collect(repos(None), repos)
        result['repositories'] = len(repositories)
        if repositories:
            start = repository_offset % len(repositories)
            repositories = repositories[start:] + repositories[:start]
        pending = [(r, None) for r in repositories]
        seen_cursors = set()
        seen_prs = set()
        totals, counts = {}, Counter()
        while pending:
            batch, pending = pending[:10], pending[10:]
            # Aliases permit an independent PR cursor for each repository.
            fields, variables, declarations = [], {}, []
            for i, (repo, cursor) in enumerate(batch):
                declarations.extend(['$id%d:ID!' % i, '$c%d:String' % i])
                variables.update({'id%d' % i: repo['id'], 'c%d' % i: cursor})
                fields.append('''r%d:node(id:$id%d) { ... on Repository {
                  id pullRequests(first:25,after:$c%d,states:OPEN,
                    orderBy:{field:CREATED_AT,direction:ASC}) { %s nodes { %s } }
                } }''' % (i, i, i, PAGE, PR_FIELDS))
            estimate = math.ceil(len(batch) * (1 + 25 * 3) / 100) + 1
            data = api.query('query(%s) { %s %s }' % (','.join(declarations), '\n'.join(fields), RATE),
                             variables, estimate=estimate)
            for i, (repo, prior_cursor) in enumerate(batch):
                current = data.get('r%d' % i)
                if not current or current.get('id') != repo['id']:
                    result['gaps'].append({'scope': repo['nameWithOwner'], 'reason': 'repository-inaccessible'})
                    continue
                nodes, cursor, total = page(current.get('pullRequests'))
                if repo['id'] in totals and totals[repo['id']] != total:
                    raise ScanError('pr-roster-changed')
                totals[repo['id']] = total
                counts[repo['id']] += len(nodes)
                for node in nodes:
                    if node['id'] in seen_prs:
                        raise ScanError('duplicate-pr-during-pagination')
                    seen_prs.add(node['id'])
                    if node['state'] == 'OPEN' and (node['isDraft'] is False or include_drafts):
                        result['prs'].append(classify(node, api))
                if cursor is not None:
                    key = (repo['id'], cursor)
                    if key in seen_cursors or cursor == prior_cursor:
                        raise ScanError('repeated-pr-cursor')
                    seen_cursors.add(key)
                    pending.append((repo, cursor))
                elif counts[repo['id']] != total:
                    raise ScanError('pr-count-mismatch')
        result['complete'] = not result['gaps']
    except (ScanError, KeyError, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ScanError) else 'malformed-response'
        result['gaps'].append({'scope': org, 'reason': reason})
    result['prs'].sort(key=lambda p: (p['repo'].casefold(), p['number']))
    # Discovery completeness and per-PR evidence completeness are separate.
    for row in result['prs']:
        if row['unknowns']:
            result['complete'] = False
    result['summary'] = {key: sum(p['action'] == key for p in result['prs'])
                         for key in ('dispatch', 'coordinator', 'waiting', 'healthy', 'unknown')}
    result['dispatch'] = [p['url'] for p in result['prs'] if p['action'] == 'dispatch']
    result['finished_at'], result['api'] = utc_now(), api.report()
    return result


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--org', required=True)
    parser.add_argument('--max-requests', type=positive, default=100)
    parser.add_argument('--max-cost', type=positive, default=200)
    parser.add_argument('--reserve', type=positive, default=500)
    parser.add_argument('--deadline', type=positive, default=180, help='maximum elapsed seconds')
    parser.add_argument('--spacing', type=positive, default=1, help='minimum seconds between requests')
    parser.add_argument('--state-dir', type=Path, help='private directory for the per-org overlap lock')
    parser.add_argument('--execute', action='store_true', help='arm auto-merge and dispatch through an admitted T3 run')
    parser.add_argument('--run-config', type=Path, help='frozen run configuration for --execute')
    parser.add_argument('--bridge', action='store_true', help='use the enclosing harness code-mode tool bridge')
    parser.add_argument('--wake-kind', choices=('schedule', 'manual', 'event', 'resume'), default='manual')
    parser.add_argument('--wake-id')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', args.org):
        parser.error('invalid organization login')
    args.org = args.org.lower()
    if args.execute:
        if not args.run_config:
            parser.error('--execute requires --run-config')
        try:
            if json.loads(args.run_config.read_text())['org'] != args.org:
                parser.error('--org differs from the admitted run configuration')
        except (OSError, ValueError, KeyError):
            parser.error('invalid run configuration')
        import org_execute
        forwarded = ['--run-config', str(args.run_config)]
        if args.bridge:
            forwarded.append('--bridge')
        forwarded += ['--wake-kind', args.wake_kind]
        if args.wake_id:
            forwarded += ['--wake-id', args.wake_id]
        for option in ('max_requests', 'max_cost', 'reserve', 'deadline', 'spacing'):
            forwarded += ['--' + option.replace('_', '-'), str(getattr(args, option))]
        return org_execute.main(forwarded)
    if args.run_config:
        parser.error('--run-config requires --execute')
    if args.bridge:
        parser.error('--bridge requires --execute')
    directory = args.state_dir or Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'agents/jobs/babysitter/org-scan'
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / (args.org + '.lock')).open('a') as lock:
            os.chmod(lock.name, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                result = {'schema_version': 1, 'org': args.org, 'complete': False,
                          'gaps': [{'scope': args.org, 'reason': 'scan-already-running'}],
                          'prs': [], 'dispatch': []}
            else:
                result = scan(GitHub(args), args.org)
    except OSError:
        result = {'schema_version': 1, 'org': args.org, 'complete': False,
                  'gaps': [{'scope': args.org, 'reason': 'lock-unavailable'}], 'prs': [], 'dispatch': []}
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['complete'] else 3


if __name__ == '__main__':
    sys.exit(main())
