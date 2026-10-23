#!/usr/bin/env python3
"""Private reporting ledger. Host actions stay with the agent, never this helper.

Observations are assertions supplied by the operator, not proof of their truth.
No network, scheduler, model client, subprocess or live configuration access.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from urllib.parse import urlparse
import uuid

if sys.version_info < (3, 10):
    raise SystemExit('bug-report requires Python 3.10+')
try:
    import fcntl
except ImportError:
    raise SystemExit('bug-report requires POSIX advisory file locks')

ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$')
OUTCOMES = {'upstream-defect', 't3-defect', 'unconfirmed', 't3-improvement', 'external', 'explained'}
FIELDS = ('symptom', 'expected', 'actual', 'impact', 'version', 'channel',
          'provider', 'platform', 'procedure', 'results', 'references')
PUBLIC = {'issue', 'comment', 'idea', 'reply'}
KINDS = PUBLIC | {'launch', 'schedule', 'cleanup', 'diagnostic', 'read'}


class Held(ValueError):
    """Fixed messages only: never echo private inputs into logs."""


def require(value, message):
    if not value:
        raise Held(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'invalid clock or budget')
    return value


def redact(value, private=()):
    """Defense in depth; semantic privacy review remains mandatory."""
    if isinstance(value, dict):
        return {str(k): ('[redacted]' if re.search(
            r'(?i)token|secret|password|credential|transcript|private_source', str(k))
            else redact(v, private)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, private) for v in value]
    if not isinstance(value, str):
        return value
    for literal in sorted(private, key=len, reverse=True):
        if literal:
            value = value.replace(literal, '[redacted]')
    value = re.sub(r'(?i)\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)', '[redacted]', value)
    value = re.sub(r'(?i)\b(?:Bearer\s+\S+|(?:token|password|secret|api[_-]?key)\s*[:=]\s*\S+)', '[redacted]', value)
    value = re.sub(r'(?:/(?:home|Users|private|tmp|var|opt|mnt)/[^\s`<>"\]\)]+|[A-Za-z]:\\[^\s`<>"\]\)]+)', '[private path]', value)
    value = re.sub(r'\b[\w.-]+\.(?:local|internal|lan|home)\b', '[private host]', value)
    value = re.sub(r'\b(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b', '[private address]', value)
    return value


def reporting_route(problem):
    """Bind each verified upstream to its documented intake, not a model-picked host."""
    if problem.get('outcome') != 'upstream-defect':
        return {'method': 'github', 'destination': 'https://github.com/pingdotgg/t3code'}
    route = problem.get('reporting_route')
    require(isinstance(route, dict) and isinstance(problem.get('upstream_name'), str)
            and problem['upstream_name'].strip(), 'upstream and documented reporting route required')
    require(set(route) == {'method', 'destination', 'documentation', 'ownership_evidence'}
            and all(isinstance(v, str) and v.strip() for v in route.values())
            and route['method'] in {'github', 'web', 'email'}
            and route['ownership_evidence'], 'documented reporting method and ownership evidence required')
    docs = urlparse(route['documentation'])
    require(docs.scheme == 'https' and docs.netloc and not docs.username and not docs.password,
            'reporting method needs an authoritative HTTPS documentation reference')
    u = urlparse(route['destination'])
    require(not any(c in route['destination'] for c in '\r\n') and not u.fragment,
            'invalid reporting destination')
    if route['method'] == 'email':
        require(u.scheme == 'mailto' and not u.netloc and not u.query
                and re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', u.path),
                'reporting email must name one documented recipient')
    else:
        require(u.scheme == 'https' and u.netloc and not u.username and not u.password,
                'reporting destination must be HTTPS without credentials')
        if route['method'] == 'github':
            require(u.netloc == 'github.com' and not u.query
                    and re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', u.path)
                    and not any(part in {'.', '..'} for part in u.path.split('/')),
                    'GitHub reporting destination must name one canonical repository')
    return dict(route)


def target(url, kind=None, route=None):
    route = route or reporting_route({})
    u = urlparse(url or '')
    if route['method'] == 'email':
        require(url == route['destination'], 'email receipt must retain the documented recipient')
        return url
    if route['method'] == 'web':
        destination = urlparse(route['destination'])
        require(u.scheme == 'https' and u.netloc == destination.netloc and not u.username and not u.password,
                'report receipt must belong to the documented tracker')
        return url
    require(u.scheme == 'https' and u.netloc == 'github.com' and not u.query,
            'destination must be a canonical upstream GitHub URL')
    match = re.fullmatch(re.escape(urlparse(route['destination']).path) + r'/(issues|discussions)/([1-9][0-9]*)', u.path)
    require(match, 'destination must belong to the verified upstream repository')
    if kind == 'idea':
        require(match[1] == 'discussions', 'Ideas requires a Discussion destination')
    if kind == 'issue':
        require(match[1] == 'issues', 'bug report requires an issue destination')
    return url


class Store:
    """All access is relative to no-follow directory descriptors.

    A root lock serializes sessions as well as the cross-session incident index.
    The filesystem must implement POSIX flock and atomic rename.
    """
    def __init__(self, root, clock=time.time):
        self.root = Path(root)
        self.clock = clock
        require(self.root.is_absolute() and '..' not in self.root.parts,
                'state root must be absolute without traversal')
        require('userdata' not in self.root.parts, 'live userdata is forbidden')
        for p in (self.root, *self.root.parents):
            require(not (p / '.git').exists(), 'state root must be outside repositories')

    @contextmanager
    def directory(self, create=False):
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.root.parts[1:]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            s = os.fstat(fd)
            require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) & 0o077 == 0,
                    'state root must be owned and private (0700)')
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def read(fd, name, default=None):
        try:
            f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return default
        with os.fdopen(f) as stream:
            s = os.fstat(stream.fileno())
            require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid()
                    and stat.S_IMODE(s.st_mode) & 0o077 == 0 and s.st_nlink == 1,
                    'unsafe state file')
            return json.load(stream)

    @staticmethod
    def write(fd, name, value):
        try:
            s = os.stat(name, dir_fd=fd, follow_symlinks=False)
            require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1,
                    'unsafe state destination')
        except FileNotFoundError:
            pass
        tmp = '.pending-' + uuid.uuid4().hex
        f = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(f, 'w') as stream:
                json.dump(value, stream, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(tmp, dir_fd=fd)
            except FileNotFoundError:
                pass

    @contextmanager
    def locked(self, create=False):
        with self.directory(create) as fd:
            lock = os.open('ledger.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
            try:
                s = os.fstat(lock)
                require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid()
                        and s.st_nlink == 1 and stat.S_IMODE(s.st_mode) & 0o077 == 0,
                        'unsafe lock file')
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield fd
            finally:
                os.close(lock)

    def status(self, sid):
        require(ID.fullmatch(sid), 'invalid session ID')
        with self.directory() as fd:
            state = self.read(fd, sid + '.json')
            require(state, 'session missing')
            state['last_clock'] = max(state['last_clock'], number(self.clock()))
            return summary(state)

    def apply(self, sid, action, data):
        require(ID.fullmatch(sid), 'invalid session ID')
        now = number(self.clock())
        with self.locked(action == 'init') as fd:
            name = sid + '.json'
            s = self.read(fd, name)
            if action == 'init':
                require(data.get('incident_key') and data.get('owner_thread'), 'incident identity and owner required')
                private = data.get('private_values', [])
                require(isinstance(private, list) and all(isinstance(v, str) and v for v in private),
                        'private values must be nonempty strings')
                key = digest(data['incident_key'])
                index = self.read(fd, 'incidents.json', {})
                existing = index.get(key)
                if existing:
                    other = self.read(fd, existing + '.json')
                    require(other, 'incident recovery required')
                    other['last_clock'] = max(other['last_clock'], now)
                    merged = list(dict.fromkeys([*other['private_values'], *private]))
                    if merged != other['private_values']:
                        other['private_values'] = merged
                        # Preserve intent hashes and remote-recovery records. An
                        # unsent request must be reconciled and prepared again
                        # under the expanded privacy declarations before dispatch.
                        for op in other['operations'].values():
                            if op['status'] == 'prepared' and op['kind'] != 'cleanup':
                                op['privacy_stale'] = True
                        self.write(fd, existing + '.json', other)
                    return {'existing_session': existing, **summary(other)}
                require(s is None, 'session ID already belongs to another incident')
                s = {'schema': 1, 'id': sid, 'incident_hash': key, 'owner_thread': data['owner_thread'],
                     'reporting_thread': None, 'created_at': now, 'last_clock': now,
                     'private_values': list(dict.fromkeys(private)), 'problems': {}, 'searches': {},
                     'budget': {'seconds': 600, 'spent': 0, 'active_since': None},
                     'operations': {}, 'comments': {}, 'requests': [], 'coverage_gaps': [],
                     'monitor_started_at': None, 'deadline': None, 'schedule': None,
                     'cleanup': 'not-needed', 'cancelled': False, 'blockers': [], 'failures': {}}
                # Reserve ownership first. A crash before the session write leaves a
                # recoverable hold, never an unindexed session that can dispatch twice.
                index[key] = sid
                self.write(fd, 'incidents.json', index)
                self.write(fd, name, s)
                return summary(s)
            require(s, 'session missing')
            require(now >= s['last_clock'], 'clock moved backwards; reconcile before work')
            s['last_clock'] = now
            result = transition(s, action, data, now)
            self.write(fd, name, s)
            return redact(result, s['private_values'])


def alive(s, now):
    require(not s['cancelled'], 'session cancelled; cleanup only')
    require(s['deadline'] is None or now < s['deadline'], 'deadline reached; cleanup only')


def cleanup_due(s, now):
    require(s['cancelled'] or (s['deadline'] is not None and now >= s['deadline']),
            'monitoring window active; owner cancellation required for cleanup')


def budget(s, now):
    b = s['budget']
    return b['spent'] + (now - b['active_since'] if b['active_since'] is not None else 0)


def problem_ready(s, pid):
    p = s['problems'].get(pid)
    require(p and p['outcome'] in {'upstream-defect', 't3-defect', 't3-improvement'}, 'problem is not reportable')
    route = reporting_route(p)
    evidence = p['evidence']
    require(all(k in evidence for k in FIELDS), 'evidence fields must retain unknowns explicitly')
    require(all(evidence[k] for k in ('symptom', 'expected', 'actual', 'impact', 'references')),
            'report lacks core evidence')
    require(p.get('ownership_evidence') and p.get('expectation_evidence') and p.get('documentation'),
            'ownership, expectation and intended behavior evidence required')
    require(p.get('claims') and all(c.get('evidence') and 'limits' in c for c in p['claims']),
            'each claim needs evidence and limits')
    for claim in p['claims']:
        if claim.get('fixes_affected_environment') is True:
            require(p.get('environment') and claim.get('tested_environment') == p['environment']
                    and claim.get('fix_observation'), 'fix claim lacks matching affected-environment observation')
    if p['outcome'] in {'t3-defect', 'upstream-defect'}:
        require(evidence['procedure'] and evidence['results'] and p.get('observation'),
                'verified defect needs observed reproduction')
    search = s['searches'].get(pid)
    query_required = True
    if route['method'] == 'github':
        complete = search and search.get('issues_complete') is True and search.get('discussions_complete') is True
    else:
        channels = (search or {}).get('channels', [])
        complete = (search and search.get('channels_complete') is True
                    and isinstance(channels, list) and channels
                    and all(isinstance(c, dict) and c.get('channel') and c.get('status') in {'searched', 'not-applicable'}
                            and c.get('evidence') for c in channels))
        query_required = not complete or any(c['status'] == 'searched' for c in channels)
    require(complete and (search.get('queries') or not query_required) and search.get('reason'),
            'complete duplicate search required')
    require(all(all(k in c for k in ('url', 'content', 'comments', 'versions', 'resolution', 'reason'))
                for c in search.get('candidates', [])), 'candidate inspection incomplete')
    return p, search


def render(p, search=None):
    e = p['evidence']
    lines = ['# ' + e['symptom'], '', 'Outcome: ' + p['outcome']]
    if p.get('upstream_name'):
        lines += ['', 'Upstream: ' + p['upstream_name'],
                  'Reporting method: ' + json.dumps(p['reporting_route'], ensure_ascii=False)]
    for k in FIELDS[1:]:
        lines += ['', k.replace('_', ' ').capitalize() + ':',
                  json.dumps(e.get(k), ensure_ascii=False) if e.get(k) is not None else 'Unknown']
    lines += ['', 'Claims and limits:', json.dumps(p.get('claims', []), ensure_ascii=False),
              '', 'Ownership evidence:', str(p.get('ownership_evidence')),
              '', 'Expected behavior evidence:', str(p.get('expectation_evidence')),
              '', 'Workaround:', str(p.get('workaround', 'Unknown'))]
    lines += ['', 'Related reports:']
    if search is None:
        lines += ['Duplicate search not recorded.']
    else:
        selected = search.get('selected')
        lines += ['Canonical report: ' + str(selected or 'None selected'),
                  'Search assessment: ' + str(search.get('reason', 'Unknown'))]
        for candidate in search.get('candidates', []):
            if selected and candidate.get('url') == selected:
                lines += ['Match reasoning: ' + str(candidate.get('reason', 'Unknown'))]
    return '\n'.join(lines)


def public_request(kind, payload, canonical, observation, transport, route=None):
    """Generate the actual destination-bearing request; never pass through arguments.

    Repository/category/object identity observations still require a current fetch.
    Unknown payload keys fail closed rather than smuggling another destination.
    """
    require(set(payload) <= {'body', 'title'} and isinstance(payload.get('body'), str),
            'public payload accepts only body and title')
    route = route or reporting_route({})
    if route['method'] != 'github':
        require((kind == 'issue' and bool(payload.get('title'))) or
                (kind in {'comment', 'reply'} and set(payload) == {'body'}),
                'report needs a title; replies accept only body')
        require(transport == 'documented' and observation.get('reporting_destination') == route['destination']
                and observation.get('method_documentation') == route['documentation'],
                'current documented intake observation required')
        if canonical:
            target(canonical, route=route)
        return {'transport': 'documented', 'method': route['method'], 'destination': route['destination'],
                'target': canonical, 'arguments': payload}
    repository = urlparse(route['destination']).path.lstrip('/')
    require(observation.get('repository_url') == route['destination'],
            'current upstream repository identity observation required')
    if kind == 'issue':
        require(payload.get('title'), 'issue title required')
        if transport == 'github-create-issue':
            return {'transport': transport, 'arguments': {'repository_full_name': repository, **payload}}
        require(transport == 'github-rest', 'unsupported issue transport')
        return {'transport': transport, 'method': 'POST', 'endpoint': f'repos/{repository}/issues', 'input': payload}
    if kind in {'comment', 'reply'} and '/issues/' in canonical:
        require(transport == 'github-rest', 'unsupported issue-comment transport')
        require(set(payload) == {'body'}, 'comment accepts only body')
        n = urlparse(canonical).path.split('/')[-1]
        return {'transport': transport, 'method': 'POST',
                'endpoint': f'repos/{repository}/issues/{n}/comments', 'input': payload}
    require(transport == 'github-graphql', 'Ideas requires supported Discussion transport')
    if kind == 'idea':
        require(payload.get('title') and observation.get('repository_id') and observation.get('ideas_category_id'),
                'current Discussion repository/category identity required')
        query = ('mutation($r:ID!,$c:ID!,$t:String!,$b:String!){createDiscussion(input:{'
                 'repositoryId:$r,categoryId:$c,title:$t,body:$b}){discussion{id url createdAt body}}}')
        variables = {'r': observation['repository_id'], 'c': observation['ideas_category_id'],
                     't': payload['title'], 'b': payload['body']}
    else:
        require(set(payload) == {'body'} and observation.get('object_url') == canonical
                and observation.get('discussion_id'), 'current canonical Discussion identity required')
        query = ('mutation($d:ID!,$b:String!){addDiscussionComment(input:{discussionId:$d,body:$b})'
                 '{comment{id url createdAt body}}}')
        variables = {'d': observation['discussion_id'], 'b': payload['body']}
    return {'transport': transport, 'query': query, 'variables': variables}


def transition(s, action, d, now):
    if action == 'problem':
        alive(s, now)
        pid = d.get('id', '')
        require(ID.fullmatch(pid) and d.get('outcome') in OUTCOMES, 'invalid problem classification')
        require(isinstance(d.get('evidence'), dict), 'evidence required')
        if d['outcome'] == 'unconfirmed':
            require(d.get('missing'), 'unconfirmed problem needs a targeted question')
        if d['outcome'] == 'external':
            require(d.get('destination') and d.get('ownership_evidence'), 'external attribution and suggestion required')
        if d['outcome'] == 'upstream-defect':
            reporting_route(d)
        old = s['problems'].get(pid, {})
        history = old.get('history', []) + ([{k:v for k,v in old.items() if k != 'history'}] if old else [])
        s['problems'][pid] = {**d, 'recorded_at': now, 'history': history}
        s['searches'].pop(pid, None)
        return {'id': pid, 'outcome': d['outcome'], 'draft': render(d)}
    if action == 'search':
        alive(s, now)
        require(d.get('problem') in s['problems'], 'problem missing')
        s['searches'][d['problem']] = d
        return {'recorded': True, 'draft': render(s['problems'][d['problem']], d)}
    if action == 'budget':
        alive(s, now)
        b = s['budget']
        if 'seconds' in d:
            require(d.get('owner_decision'), 'budget change requires owner decision')
            b['seconds'] = number(d['seconds'])
            b['owner_decision'] = d['owner_decision']
        if d.get('active') is False and b['active_since'] is not None:
            require(not any(o['status'] in {'sent', 'uncertain'} and 'sent_at' in o
                    and o.get('budgeted', o['kind'] in {'diagnostic', 'read'})
                    for o in s['operations'].values()),
                    'finish in-flight investigation before pausing its budget')
            b['spent'] = budget(s, now)
            b['active_since'] = None
        elif d.get('active') is True:
            require(budget(s, now) < b['seconds'], 'investigation budget exhausted')
            if b['active_since'] is None:
                b['active_since'] = now
        return {'spent': budget(s, now), 'limit': b['seconds']}
    if action == 'prepare':
        kind = d.get('kind')
        require(kind in KINDS, 'action outside reporting authority')
        pending = [o for o in s['operations'].values() if o['status'] in {'prepared', 'sent', 'uncertain'}]
        reconciliation = d.get('reconciliation_for')
        reconciliation_read = (kind == 'read' and reconciliation in s['operations']
            and s['operations'][reconciliation] in pending
            and all(o['kind'] != 'read' or o['id'] == reconciliation for o in pending))
        require(not pending or reconciliation_read
                or (kind == 'cleanup' and all(o['kind'] != 'cleanup' for o in pending)),
                'unfinished operation requires reconciliation')
        if kind != 'cleanup':
            alive(s, now)
        if kind == 'diagnostic' or (kind == 'read' and s['deadline'] is None):
            require(s['budget']['active_since'] is not None and budget(s, now) < s['budget']['seconds'],
                    'start active budget before investigation')
        if kind == 'diagnostic':
            require(d.get('scope') in {'read-only', 'task-owned-disposable'}
                    and d.get('safe_procedure_reviewed') is True, 'safe diagnostic scope required')
        if kind == 'read':
            require(isinstance(d.get('read_key'), str) and d['read_key'], 'stable logical read identity required')
            failures = s['failures'].get(d.get('read_key'), [])
            require(len(failures) < 3 and not (len(failures) >= 2 and failures[-1] == failures[-2]),
                    'read retry budget exhausted or identical failure repeated')
        payload = d.get('payload', {})
        pid = d.get('problem')
        request = None
        evidence_key = None
        if kind in PUBLIC | {'launch'}:
            p, search = problem_ready(s, pid)
            require(d.get('privacy_reviewed') is True, 'semantic privacy review required')
            if kind == 'launch':
                require(s['reporting_thread'] is None and payload.get('scratch') is True
                        and not payload.get('projectId') and not payload.get('workspaceStrategy'),
                        'explicit reporting-only scratch workspace required')
                require(set(payload) == {'title', 'message', 'scratch'} and payload['title'],
                        'launch accepts only title, message and scratch')
                require(d.get('thread_search_complete') is True, 'check existing reporting threads before launch')
                require(payload.get('message'), 'self-contained reporting summary required')
            else:
                require(s['reporting_thread'] and d.get('actor_thread') == s['reporting_thread'],
                        'only reporting thread may publish')
                require(d.get('destination_refreshed') is True, 'refresh actual destination before writing')
                caps = d.get('destination_observation', {})
                require(caps.get('write_access') is True and caps.get('templates_read') is True,
                        'current destination access and template observation required')
                selected = search.get('selected')
                if kind == 'issue':
                    require(p['outcome'] in {'t3-defect', 'upstream-defect'} and selected is None,
                            'new issue requires verified distinct upstream defect')
                elif kind == 'idea':
                    require(p['outcome'] == 't3-improvement' and caps.get('ideas_category_id') and selected is None,
                            'new Ideas requires established distinct improvement and current category')
                else:
                    target(d.get('target'), route=reporting_route(p))
                    require('#' not in d['target'], 'canonical target must name the report rather than a comment fragment')
                    require(selected == d.get('target'), 'comment target must match inspected canonical report')
                require(payload.get('body'), 'public body required')
                if kind == 'reply':
                    version = d.get('comment_version')
                    comment = s['comments'].get(version, {})
                    require(comment and comment['target'] == d.get('target')
                            and comment['status'] in {'unanswered', 'needs-owner'}, 'response must bind an outstanding request version')
                evidence_key = digest([pid, p['outcome'], p['evidence'], p['claims'],
                                       p['ownership_evidence'], p['expectation_evidence'], p['documentation']])
                if kind == 'reply' and d.get('reference_operation'):
                    prior = s['operations'].get(d['reference_operation'], {})
                    require(prior.get('status') == 'confirmed' and prior.get('evidence_key') == evidence_key
                            and prior.get('canonical_destination') == d.get('target'),
                            'reference reply requires already-published matching evidence')
                    expected = 'Evidence is already recorded here: ' + prior['observation']['url'] + '.'
                    require(payload == {'body': expected}, 'reference reply must link existing evidence without repeating it')
                    evidence_key = digest(['reference', d['comment_version'], d['reference_operation']])
                request = public_request(kind, payload, d.get('target'), caps, d.get('transport'), reporting_route(p))
        if kind == 'schedule':
            require(s['reporting_thread'] and d.get('actor_thread') == s['reporting_thread'],
                    'schedule must belong to reporting thread')
            require(s['deadline'] is not None and s['schedule'] is None, 'schedule requires confirmed first publication')
            require(payload.get('schedule') == {'type': 'interval', 'everyMs': 120000}
                    and payload.get('bindToCurrentThread') is True, 'native two-minute bound schedule required')
            require(set(payload) <= {'schedule', 'bindToCurrentThread', 'prompt', 'title', 'clientRequestId'}
                    and payload.get('prompt'), 'schedule accepts only current-thread native arguments')
        if kind == 'cleanup':
            require(s['schedule'], 'no owned schedule to clean up')
            cleanup_due(s, now)
            require(payload.get('task_id') == s['schedule']['task_id'], 'cleanup must name owned schedule')
            require(set(payload) == {'task_id'}, 'cleanup accepts only owned task handle')
        safe = redact(payload, s['private_values'])
        if request is not None:
            # Rebuild from sanitized content. No unredacted body survives in a host request.
            request = public_request(kind, safe, d.get('target'), caps, d.get('transport'), reporting_route(p))
        elif kind == 'launch':
            request = {'transport': 't3-thread-launch', 'arguments': safe}
        elif kind == 'schedule':
            request = {'transport': 't3-schedule-task', 'arguments': safe}
        elif kind == 'cleanup':
            request = {'transport': 't3-delete-scheduled-task', 'arguments': {'scheduledTaskId': safe['task_id']}}
        content_hash = digest({'kind': kind, 'problem': pid, 'target': d.get('target'), 'payload': safe})
        for op in s['operations'].values():
            if op['status'] != 'confirmed' or kind in {'read', 'diagnostic'}:
                continue
            if op['hash'] == content_hash or (evidence_key is not None and op.get('evidence_key') == evidence_key
                    and op.get('canonical_destination') == d.get('target')):
                return {'duplicate': True, 'operation': op['id']}
            if kind in {'issue', 'idea'} and op['kind'] == kind and op['problem'] == pid:
                raise Held('report already exists; inspect canonical destination and contribute new evidence')
        oid = uuid.uuid4().hex
        s['operations'][oid] = {'id': oid, 'kind': kind, 'problem': pid, 'target': d.get('target'),
                                'hash': content_hash, 'payload': safe, 'status': 'prepared', 'prepared_at': now,
                                'read_key': d.get('read_key'), 'request': request, 'evidence_key': evidence_key,
                                'reconciliation_for': reconciliation, 'reference_operation': d.get('reference_operation'),
                                'budgeted': kind == 'diagnostic' or (kind == 'read' and s['deadline'] is None),
                                'comment_version': d.get('comment_version'),
                                'reporting_route': reporting_route(p) if kind in PUBLIC else None,
                                'problem_generation': digest(s['problems'][pid]) if kind in PUBLIC | {'launch'} else None,
                                'search_generation': digest(s['searches'][pid]) if kind in PUBLIC | {'launch'} else None}
        if kind == 'diagnostic':
            s['operations'][oid].update(scope=d['scope'], safe_procedure_reviewed=True)
        return {'operation': oid, 'hash': content_hash, 'payload': safe, 'request': request}
    if action in {'send', 'finish', 'reconcile'}:
        op = s['operations'].get(d.get('operation'))
        require(op, 'operation missing')
        if action == 'send':
            require(op['status'] == 'prepared', 'operation cannot be dispatched again')
            require(not op.get('privacy_stale'), 'privacy declarations changed; reconcile stale intent')
            if op['kind'] == 'cleanup':
                cleanup_due(s, now)
            else:
                alive(s, now)
            if op.get('budgeted', op['kind'] in {'diagnostic', 'read'}):
                require(s['budget']['active_since'] is not None and budget(s, now) < s['budget']['seconds'],
                        'active investigation budget required')
            if op['kind'] in PUBLIC | {'launch'}:
                problem_ready(s, op['problem'])
                require(op['problem_generation'] == digest(s['problems'][op['problem']])
                        and op['search_generation'] == digest(s['searches'][op['problem']]),
                        'classification or routing changed; reconcile stale intent')
            op.update(status='sent', sent_at=now)
            return {'operation': op['id'], 'payload': op['payload'], 'request': op['request']}
        require(op['status'] in {'prepared', 'sent', 'uncertain'}, 'operation already final')
        if d.get('failed') is True:
            require(op['status'] == 'sent' and d.get('confirmed_no_effect') is True,
                    'failed external write must be reconciled when outcome is uncertain')
            if op['kind'] in {'diagnostic', 'read'}:
                require(d.get('request_terminal') is True, 'observe investigative request termination before closing failure')
            if op['kind'] == 'read':
                failure = d.get('failure_class')
                require(isinstance(failure, str) and failure.strip(), 'read failure class required')
                s['failures'].setdefault(op['read_key'], []).append(digest(failure))
                op.update(failure_class=redact(failure, s['private_values']),
                          failure_evidence=redact(d.get('evidence'), s['private_values']))
            op.update(status='failed', completed_at=now)
            return {'recorded': True, 'operation': op['id']}
        if d.get('uncertain') is True:
            op['status'] = 'uncertain'
            return {'blocked': 'reconcile remote operation before retry', 'operation': op['id']}
        if d.get('absent') is True:
            require(action == 'reconcile' and d.get('complete_search') is True and d.get('evidence'),
                    'absence requires exhaustive reconciliation evidence')
            if op['kind'] in {'diagnostic', 'read'} and 'sent_at' in op:
                require(d.get('request_terminal') is True, 'absence of effects does not prove investigative request termination')
            op.update(status='absent', reconciliation=redact(d, s['private_values']))
            return {'retry_permitted': True}
        require('sent_at' in op or action == 'reconcile', 'no external dispatch recorded')
        obs = d.get('observation', {})
        require(obs.get('fetched') is True and obs.get('operation_hash') == op['hash'],
                'fetch and match operation identity/content before confirming')
        if op['kind'] in {'diagnostic', 'read'}:
            require(obs.get('request_terminal') is True, 'observe investigative request completion before confirming')
        if op['kind'] in PUBLIC:
            route = op.get('reporting_route') or reporting_route({})
            target(obs.get('url'), op['kind'], route)
            observed = urlparse(obs['url'])
            if route['method'] != 'github':
                require(obs.get('receipt_reference'), 'documented submission needs a fetched ticket or sent-message receipt')
            elif op['kind'] in {'comment', 'reply'}:
                prefix = 'issuecomment-' if '/issues/' in observed.path else 'discussioncomment-'
                require(re.fullmatch(prefix + r'[1-9][0-9]*', observed.fragment),
                        'fetch the specific published comment URL before confirming')
            else:
                require(not observed.fragment, 'publication must name the created report URL')
            if op['target']:
                require(obs['url'].split('#')[0] == op['target'].split('#')[0], 'fetched object differs from destination')
            require(obs.get('payload_sha256') == digest(op['payload']), 'published content mismatch')
            op['canonical_destination'] = obs['url'].split('#')[0]
            if s['monitor_started_at'] is None:
                started = number(obs.get('created_at'))
                precision = obs.get('timestamp_precision', 0)
                require(precision in (0, 1) and started <= now
                        and started >= op.get('sent_at', op['prepared_at']) - precision,
                        'invalid publication time')
                s['monitor_started_at'], s['deadline'] = started, started + 1800
        if op['kind'] == 'launch':
            require(obs.get('thread_id') and obs.get('state') in {'preparing', 'running', 'idle', 'completed'},
                    'accepted reporting thread handle required')
            s['reporting_thread'] = obs['thread_id']
        if op['kind'] == 'schedule':
            require(obs.get('task_id') and obs.get('next_run') and obs.get('bound_thread') == s['reporting_thread'],
                    'native schedule handle, next run and binding required')
            s['schedule'] = {'task_id': obs['task_id'], 'next_run': obs['next_run'], 'everyMs': 120000}
            s['cleanup'] = 'pending'
        if op['kind'] == 'cleanup':
            require(obs.get('task_id') == s['schedule']['task_id'] and obs.get('disabled_or_absent') is True,
                    'verify owned schedule disabled or deleted')
            s['cleanup'] = 'verified'
        op.update(status='confirmed', observation=redact(obs, s['private_values']), completed_at=now)
        return summary(s)
    if action == 'comments':
        alive(s, now)
        require(d.get('pages_complete') is True, 'fetch every page before processing replies')
        routes = [o.get('reporting_route') or reporting_route({}) for o in s['operations'].values()
                  if o.get('status') == 'confirmed' and o.get('canonical_destination') == d.get('target')]
        routes.extend(reporting_route(s['problems'][pid]) for pid, search in s['searches'].items()
                      if search.get('selected') == d.get('target'))
        require(routes, 'follow-up target is not owned or verified canonical')
        target(d.get('target'), route=routes[0])
        if routes[0]['method'] == 'email':
            references = {o['observation'].get('receipt_reference') for o in s['operations'].values()
                          if o.get('status') == 'confirmed' and o.get('canonical_destination') == d['target']}
            require(d.get('receipt_reference') and d['receipt_reference'] in references,
                    'email follow-up must bind an actual owned sent-message receipt')
        require('#' not in d['target'], 'comment collection must name the canonical report')
        known = {o['observation']['url'].split('#')[0] for o in s['operations'].values()
                 if o['status'] == 'confirmed' and 'url' in o.get('observation', {})}
        known.update(x['selected'] for x in s['searches'].values() if x.get('selected'))
        require(d['target'].split('#')[0] in known, 'follow-up target is not owned or verified canonical')
        require(d.get('actor') and isinstance(d.get('items'), list), 'comment observations required')
        fresh = []
        for item in d['items']:
            require(item.get('id') and item.get('author') and 'body' in item, 'comment identity incomplete')
            key = digest([d['target'], str(item['id']), item['body']])
            if item['author'] == d['actor'] or key in s['comments']:
                continue
            record = redact({**item, 'target': d['target'], 'version': key, 'status': 'unanswered',
                             'observed_at': now}, s['private_values'])
            s['comments'][key] = record
            fresh.append(record)
        return {'comments': fresh}
    if action == 'handled':
        require(d.get('version') in s['comments'], 'comment version missing')
        require(d.get('disposition') in {'answered', 'needs-owner', 'irrelevant', 'out-of-scope'},
                'explicit request disposition required')
        if d['disposition'] == 'answered':
            op = s['operations'].get(d.get('operation'), {})
            comment = s['comments'][d['version']]
            require(op.get('status') == 'confirmed' and op.get('kind') == 'reply'
                    and op.get('comment_version') == d['version'] and op.get('target') == comment['target']
                    and op['sent_at'] >= comment['observed_at'], 'answer needs request-bound verified reply')
        s['comments'][d['version']].update(disposition=d['disposition'], status=d['disposition'],
                                          detail=redact(d.get('detail', ''), s['private_values']),
                                          response_operation=d.get('operation'))
        return {'recorded': True}
    if action == 'block':
        require(d.get('requirement') and d.get('next_action'), 'blocker needs requirement and next action')
        s['blockers'].append(redact(d, s['private_values']))
        return summary(s)
    if action == 'gap':
        require(d.get('reason') and d.get('since') is not None, 'coverage gap needs interval and cause')
        s['coverage_gaps'].append(redact(d, s['private_values']))
        return summary(s)
    if action == 'cancel':
        require(isinstance(d.get('owner_instruction'), str) and d['owner_instruction'].strip(),
                'cancellation needs owner instruction')
        s.setdefault('cancellation', {'owner_instruction': redact(d['owner_instruction'], s['private_values']),
                                      'cancelled_at': now})
        s['cancelled'] = True
        return summary(s)
    if action == 'wake':
        # Persist liveness without starting diagnostics; pending operations stay held.
        return summary(s)
    raise Held('unknown ledger action')


def summary(s):
    now = s['last_clock']
    expired = s['deadline'] is not None and now >= s['deadline']
    return redact({'session': s['id'], 'owner_thread': s['owner_thread'],
                   'reporting_thread': s['reporting_thread'],
                   'problems': {k: {'outcome': v['outcome'], 'missing': v.get('missing'),
                                    'destination': v.get('destination')} for k,v in s['problems'].items()},
                   'urls': [o['observation']['url'] for o in s['operations'].values()
                            if o['status'] == 'confirmed' and 'url' in o.get('observation', {})],
                   'receipts': [{'url': o['observation']['url'],
                                 'reference': o['observation'].get('receipt_reference')}
                                for o in s['operations'].values()
                                if o['status'] == 'confirmed' and o['kind'] in PUBLIC],
                   'actions': [{'operation': o['id'], 'kind': o['kind'], 'status': o['status'],
                                **{k: o[k] for k in ('scope', 'safe_procedure_reviewed',
                                                    'failure_class', 'failure_evidence') if k in o}}
                               for o in s['operations'].values()],
                   'monitor_started_at': s['monitor_started_at'], 'deadline': s['deadline'],
                   'schedule': s['schedule'], 'cleanup': s['cleanup'],
                   'expired': expired, 'cancelled': s['cancelled'], 'cancellation': s.get('cancellation'),
                   'unanswered': [v for v in s['comments'].values() if v['status'] in {'unanswered', 'needs-owner'}],
                   'coverage_gaps': s['coverage_gaps'], 'blockers': s['blockers'],
                   'acceptance': 'unverified'}, s['private_values'])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['init', 'status', 'problem', 'search', 'budget', 'prepare',
                                    'send', 'finish', 'reconcile', 'comments', 'handled',
                                    'block', 'gap', 'cancel', 'wake'])
    p.add_argument('--session', required=True)
    p.add_argument('--state-root', default=str(Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'t3-plugins/bug-report'))
    p.add_argument('--input', type=Path)
    a = p.parse_args(argv)
    try:
        data = json.loads(a.input.read_text()) if a.input else {}
        require(isinstance(data, dict), 'JSON input must be an object')
        store = Store(a.state_root)
        out = store.status(a.session) if a.action == 'status' else store.apply(a.session, a.action, data)
        print(json.dumps({'ok': True, 'data': out}, allow_nan=False))
        return 0
    except Held as exc:
        # Held messages are fixed strings authored in this module, never input values.
        print(json.dumps({'ok': False, 'error': str(exc)}))
        return 2
    except Exception:
        # No exception interpolation: paths, JSON contents and private values stay private.
        print(json.dumps({'ok': False, 'error': 'operation held; verify input, private storage, ownership and current session state'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
