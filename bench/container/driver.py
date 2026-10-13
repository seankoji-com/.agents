#!/usr/bin/env python3
"""Bounded T3 MCP driver. Dispatches only targets accepted by model_policy."""
import argparse
import json
import os
import base64
import hashlib
import itertools
import math
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

sys.path.insert(0, '/opt/bench')
import model_policy

BASE = os.environ.get('BENCH_T3_URL', 'http://127.0.0.1:3773')
POLICY_PATH = Path(os.environ.get('BENCH_MODEL_POLICY', '/bench/config/runtime-targets.json'))


def oauth_token(access='auto'):
    """Mint an MCP-scoped client session through T3's supported local OAuth flow."""
    base = BASE
    redirect_uri = 'http://127.0.0.1:18765/auth/callback'
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(24)

    def http(path, payload=None, form=False):
        data = (urllib.parse.urlencode(payload).encode() if form
                else json.dumps(payload).encode() if payload is not None else None)
        headers = {'Accept': 'application/json'}
        if payload is not None:
            headers['Content-Type'] = ('application/x-www-form-urlencoded' if form
                                       else 'application/json')
        request = urllib.request.Request(base + path, data=data, headers=headers,
                                         method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read(1024 * 1024))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f'T3 MCP OAuth request failed at {path}: {type(exc).__name__}') from None

    resource = http('/.well-known/oauth-protected-resource/mcp').get('resource')
    if not isinstance(resource, str) or not resource.endswith('/mcp'):
        raise RuntimeError('T3 protected-resource metadata is unsupported')
    client = http('/oauth/mcp/register', {'client_name': 'Issue 28 S1b driver',
                                          'redirect_uris': [redirect_uri],
                                          'token_endpoint_auth_method': 'none'})
    client_id = client.get('client_id')
    if not isinstance(client_id, str) or client.get('token_endpoint_auth_method') != 'none':
        raise RuntimeError('T3 dynamic client registration returned an unsupported result')
    authorization = {'response_type': 'code', 'client_id': client_id,
                     'redirect_uri': redirect_uri, 'code_challenge': challenge,
                     'code_challenge_method': 'S256', 'state': state, 'resource': resource}
    approval = http('/oauth/mcp/approval', authorization)
    if not isinstance(approval, dict):
        raise RuntimeError('T3 MCP approval endpoint returned an unsupported result')
    pairing = subprocess.run(
        ['t3', 'auth', 'pairing', 'create', '--base-dir', '/bench/t3', '--json',
         '--ttl', '5m', '--label', 'issue-28-s1b-driver', '--scope', 'orchestration:read',
         '--scope', 'orchestration:operate', '--scope', 'providers:manage'],
        check=True, capture_output=True, text=True, timeout=20)
    try:
        credential = json.loads(pairing.stdout)['credential']
    except (json.JSONDecodeError, KeyError, TypeError):
        raise RuntimeError('T3 pairing credential command returned an unsupported result') from None
    if access not in {'auto', 'full-access'}:
        raise RuntimeError('unsupported isolated MCP client access mode')
    decision = http('/oauth/mcp/decision', {
        'authorization': authorization,
        'decision': {'_tag': 'pairing-code', 'access': access, 'code': credential}})
    redirect = decision.get('redirectTo') if isinstance(decision, dict) else None
    parsed = urllib.parse.urlsplit(redirect or '')
    query = urllib.parse.parse_qs(parsed.query)
    code = query.get('code', [None])[0]
    returned_state = query.get('state', [None])[0]
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
            or parsed.path != '/auth/callback' or not code or returned_state != state):
        raise RuntimeError('T3 MCP approval redirect failed state or callback validation')
    result = http('/oauth/mcp/token', {'grant_type': 'authorization_code', 'code': code,
                                      'redirect_uri': redirect_uri, 'client_id': client_id,
                                      'code_verifier': verifier, 'resource': resource}, form=True)
    value = result.get('access_token') if isinstance(result, dict) else None
    if not isinstance(value, str) or not value or result.get('token_type') != 'Bearer':
        raise RuntimeError('T3 MCP token exchange returned an unsupported result')
    return value


class Mcp:
    def __init__(self, bearer):
        self.bearer = bearer
        self.session = None
        self.next_id = 0
        self.headers = {'Authorization': 'Bearer ' + bearer,
                        'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, params=None, notify=False):
        body = {'jsonrpc': '2.0', 'method': method}
        if not notify:
            self.next_id += 1
            body['id'] = self.next_id
        if params is not None:
            body['params'] = params
        headers = dict(self.headers)
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        if hasattr(self, 'protocol_version'):
            headers['MCP-Protocol-Version'] = self.protocol_version
        req = urllib.request.Request(BASE + '/mcp', json.dumps(body).encode(), headers, method='POST')
        try:
            timeout = 120
            if (method == 'tools/call' and isinstance(params, dict)
                    and params.get('name') == 't3_thread_wait'):
                requested = params.get('arguments', {}).get('timeoutMs')
                if isinstance(requested, (int, float)) and not isinstance(requested, bool):
                    timeout = max(timeout, requested / 1000 + 15)
            with self.opener.open(req, timeout=timeout) as response:
                session = response.headers.get('Mcp-Session-Id')
                if session:
                    self.session = session
                raw_payload = response.read(256 * 1024 * 1024 + 1)
                if len(raw_payload) > 256 * 1024 * 1024:
                    raise RuntimeError('T3 MCP response exceeds finite 256 MiB bound')
                payload = raw_payload.decode('utf-8')
                content_type = response.headers.get('Content-Type', '')
        except (OSError, urllib.error.URLError) as exc:
            raise RuntimeError(f'T3 MCP request failed: {type(exc).__name__}') from None
        if notify or not payload:
            return None
        if 'text/event-stream' in content_type:
            objects = [line[5:].strip() for line in payload.splitlines() if line.startswith('data:')]
            if not objects:
                raise RuntimeError('T3 MCP stream had no result')
            payload = objects[-1]
        result = json.loads(payload)
        if 'error' in result:
            error = result['error']
            raise RuntimeError('T3 MCP error: ' + str(error.get('code', 'unknown')))
        return result.get('result')

    def connect(self):
        result = self.request('initialize', {'protocolVersion': '2025-03-26',
                                             'capabilities': {},
                                             'clientInfo': {'name': 'issue-28-s1b-driver', 'version': '1'}})
        if not isinstance(result, dict):
            raise RuntimeError('T3 MCP initialization returned no result')
        self.protocol_version = result.get('protocolVersion', '2025-03-26')
        self.request('notifications/initialized', notify=True)

    def tools(self):
        found = []
        cursor = None
        while True:
            args = {'cursor': cursor} if cursor else {}
            result = self.request('tools/list', args)
            found.extend(result.get('tools', []))
            cursor = result.get('nextCursor')
            if not cursor:
                return found

    def call(self, name, arguments):
        result = self.request('tools/call', {'name': name, 'arguments': arguments})
        if result.get('isError'):
            raise RuntimeError('T3 tool failed: ' + name)
        return result


def unpack(result):
    structured = result.get('structuredContent')
    if isinstance(structured, dict):
        return structured
    for item in result.get('content', []):
        if item.get('type') == 'text':
            try:
                value = json.loads(item['text'])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise RuntimeError('T3 tool returned no structured JSON result')


def schema_for(tools, name):
    matches = [item for item in tools if item.get('name') == name]
    if len(matches) != 1:
        raise RuntimeError(f'required T3 tool missing or ambiguous: {name}')
    schema = matches[0].get('inputSchema')
    if not isinstance(schema, dict):
        raise RuntimeError(f'T3 tool has no input schema: {name}')
    return schema


def validate_arguments(schema, arguments, path='arguments'):
    """Validate the JSON-schema subset used by discovered T3 tool inputs."""
    if not isinstance(schema, dict):
        raise RuntimeError('T3 tool input schema is malformed')
    for option in schema.get('allOf', []):
        validate_arguments(option, arguments, path)
    expected = schema.get('type')
    if 'anyOf' in schema or 'oneOf' in schema:
        choices = schema.get('anyOf', schema.get('oneOf', []))
        valid = []
        for choice in choices:
            try:
                validate_arguments(choice, arguments, path)
                valid.append(choice)
            except RuntimeError:
                continue
        if not valid or ('oneOf' in schema and len(valid) != 1):
            raise RuntimeError(f'{path} does not match the live schema alternatives')
        return
    if expected == 'object':
        if not isinstance(arguments, dict):
            raise RuntimeError(f'{path} must be an object')
        missing = [name for name in schema.get('required', []) if name not in arguments]
        if missing:
            raise RuntimeError(f"{path} lacks required schema fields: {','.join(missing)}")
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(arguments) - set(props):
            raise RuntimeError(f'{path} has fields outside the live schema')
        for name, value in arguments.items():
            if name in props:
                validate_arguments(props[name], value, path + '.' + name)
        return
    if expected == 'array':
        if not isinstance(arguments, list):
            raise RuntimeError(f'{path} must be an array')
        if isinstance(schema.get('maxItems'), int) and len(arguments) > schema['maxItems']:
            raise RuntimeError(f'{path} exceeds the live schema item bound')
        if isinstance(schema.get('minItems'), int) and len(arguments) < schema['minItems']:
            raise RuntimeError(f'{path} is below the live schema item bound')
        if isinstance(schema.get('items'), dict):
            for index, value in enumerate(arguments):
                validate_arguments(schema['items'], value, f'{path}[{index}]')
        return
    if expected == 'string' and not isinstance(arguments, str):
        raise RuntimeError(f'{path} must be a string')
    if expected == 'boolean' and not isinstance(arguments, bool):
        raise RuntimeError(f'{path} must be a boolean')
    if expected == 'number' and (not isinstance(arguments, (int, float))
                                 or isinstance(arguments, bool)):
        raise RuntimeError(f'{path} must be a number')
    if expected == 'integer' and (not isinstance(arguments, int) or isinstance(arguments, bool)):
        raise RuntimeError(f'{path} must be an integer')
    if isinstance(arguments, (int, float)) and not isinstance(arguments, bool):
        if isinstance(schema.get('minimum'), (int, float)) and arguments < schema['minimum']:
            raise RuntimeError(f'{path} is below the live schema bound')
        if isinstance(schema.get('maximum'), (int, float)) and arguments > schema['maximum']:
            raise RuntimeError(f'{path} exceeds the live schema bound')


def call_tool(client, tools, name, arguments):
    validate_arguments(schema_for(tools, name), arguments)
    return client.call(name, arguments)


def schema_integer_maximum(schema):
    """Return the integer maximum of a property, including one nested in anyOf/oneOf."""
    if not isinstance(schema, dict):
        return None
    if schema.get('type') == 'integer' and isinstance(schema.get('maximum'), int) \
            and not isinstance(schema.get('maximum'), bool):
        return schema['maximum']
    bounds = [schema_integer_maximum(choice)
              for choice in schema.get('anyOf', schema.get('oneOf', []))]
    bounds = [bound for bound in bounds if bound is not None]
    return min(bounds) if bounds else None


def _cursor(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f'T3 thread-read returned an invalid {name}')
    return value


def paged_thread_read(client, tools, thread_id, limit=100):
    """Read every thread message: page items by position, then complete truncated text.

    The pinned T3 schema pages items with afterPosition=nextPosition while hasMore,
    and continues one item's text with itemId and textOffset=nextTextOffset (UTF-16
    units counted by the server) until nextTextOffset is null.
    """
    name = 't3_thread_read'
    schema = schema_for(tools, name)
    maximum = schema_integer_maximum(schema.get('properties', {}).get('maxCharsPerItem'))
    if maximum is None or maximum <= 0:
        raise RuntimeError('T3 thread-read schema has no usable maxCharsPerItem bound')
    page_size = min(50000, maximum)
    collected = {}
    positions = []
    base_result = None
    after = None
    for _ in range(10000):
        args = {'threadId': thread_id, 'view': 'messages', 'limit': limit,
                'maxCharsPerItem': page_size}
        if after is not None:
            args['afterPosition'] = after
        result = unpack(call_tool(client, tools, name, args))
        if base_result is None:
            base_result = result
        items = result.get('items')
        if not isinstance(items, list):
            raise RuntimeError('T3 thread-read returned malformed items')
        for item in items:
            position = item.get('position') if isinstance(item, dict) else None
            if not isinstance(position, int) or isinstance(position, bool):
                raise RuntimeError('T3 thread-read returned an invalid item position')
            text_value = item.get('text')
            if text_value is not None and not isinstance(text_value, str):
                raise RuntimeError('T3 thread-read returned malformed item text')
            if position in collected:
                raise RuntimeError('T3 thread-read repeated an item position')
            row = dict(item, text=text_value or '')
            row['text'] += _item_text_rest(client, tools, thread_id, row, page_size)
            row.pop('nextTextOffset', None)
            row['textTruncated'] = False
            collected[position] = row
            positions.append(position)
        if not result.get('hasMore'):
            base_result['items'] = [collected[position] for position in positions]
            return base_result
        next_position = _cursor(result.get('nextPosition'), 'item position cursor')
        if after is not None and next_position <= after:
            raise RuntimeError('T3 thread-read pagination did not advance')
        after = next_position
    raise RuntimeError('T3 thread-read exceeded its finite page bound')


def _item_text_rest(client, tools, thread_id, item, page_size):
    """Fetch the remainder of one truncated item through itemId/textOffset reads."""
    offset = item.get('nextTextOffset')
    if offset is None:
        return ''
    item_id = item.get('itemId')
    if not isinstance(item_id, str) or not item_id:
        raise RuntimeError('T3 thread-read truncated an item without an item ID')
    parts = []
    for _ in range(10000):
        offset = _cursor(offset, 'text offset cursor')
        result = unpack(call_tool(client, tools, 't3_thread_read', {
            'threadId': thread_id, 'itemId': item_id, 'textOffset': offset,
            'maxCharsPerItem': page_size}))
        rows = result.get('items')
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise RuntimeError('T3 item read did not return exactly one item')
        row = rows[0]
        for key in ('itemId', 'position', 'createdBy', 'type'):
            if key in item and row.get(key) != item.get(key):
                raise RuntimeError('T3 thread-read pagination changed item identity')
        text_value = row.get('text')
        if not isinstance(text_value, str):
            raise RuntimeError('T3 thread-read returned malformed item text')
        parts.append(text_value)
        following = row.get('nextTextOffset')
        if following is None:
            return ''.join(parts)
        if _cursor(following, 'text offset cursor') <= offset or not text_value:
            raise RuntimeError('T3 thread-read text pagination did not advance')
        offset = following
    raise RuntimeError('T3 thread-read exceeded its finite text page bound')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def only_required_fields(schema, supplied):
    props = schema.get('properties', {})
    missing_policy = sorted(set(supplied) - set(props))
    if missing_policy:
        raise RuntimeError('T3 launch schema cannot transmit policy fields: ' + ','.join(missing_policy))
    missing = [field for field in schema.get('required', []) if field not in supplied]
    if missing:
        raise RuntimeError('unsupported required T3 launch fields: ' + ','.join(missing))
    return {key: value for key, value in supplied.items() if key in props}


def schema_has_property(schema, name):
    if not isinstance(schema, dict):
        return False
    if name in schema.get('properties', {}):
        return True
    return any(schema_has_property(child, name)
               for key in ('anyOf', 'oneOf', 'allOf')
               for child in schema.get(key, []) if isinstance(child, dict))


def dispatch_with_schema(client, tool_name, schema, supplied):
    arguments = only_required_fields(schema, supplied)
    selection_schema = schema.get('properties', {}).get('modelSelection')
    if not isinstance(selection_schema, dict) or not all(
            schema_has_property(selection_schema, field)
            for field in ('instanceId', 'model', 'options')):
        raise RuntimeError('T3 launch schema cannot transmit exact provider, model and options')
    validate_arguments(schema, arguments)
    return client.call(tool_name, arguments)


def project_path(project):
    if not isinstance(project, dict):
        return None
    for key in ('path', 'cwd', 'workingDirectory', 'workingDirectoryPath',
                'rootPath', 'workspaceRoot'):
        value = project.get(key)
        if isinstance(value, str) and value:
            return os.path.realpath(value)
    return None


def project_listing(client, tools):
    name = next((candidate for candidate in ('t3_project_list', 'project_list')
                 if any(item.get('name') == candidate for item in tools)), None)
    if name is None:
        raise RuntimeError('supported project listing MCP tool is unavailable')
    schema = schema_for(tools, name)
    properties = schema.get('properties', {})
    arguments = {'limit': 50} if 'limit' in properties else {}
    missing = sorted(set(schema.get('required', [])) - set(arguments))
    if missing:
        raise RuntimeError('project listing schema has unsupported required fields: ' + ','.join(missing))
    result = unpack(call_tool(client, tools, name, arguments))
    projects = result.get('projects')
    if not isinstance(projects, list):
        raise RuntimeError('project listing returned a malformed result')
    return name, projects


def find_launched_threads(client, tools, title):
    """List isolated-server threads whose title exactly equals a launch's unique title."""
    name = 't3_thread_list'
    schema = schema_for(tools, name)
    properties = schema.get('properties', {})
    arguments = {'limit': 100} if 'limit' in properties else {}
    missing = sorted(set(schema.get('required', [])) - set(arguments))
    if missing:
        raise RuntimeError('thread listing schema has unsupported required fields: ' + ','.join(missing))
    result = unpack(call_tool(client, tools, name, arguments))
    threads = result.get('threads')
    if not isinstance(threads, list) or result.get('hasMore'):
        raise RuntimeError('thread listing is malformed or incomplete')
    return sorted(row['threadId'] for row in threads
                  if isinstance(row, dict) and row.get('title') == title
                  and opaque_thread_id(row.get('threadId')))


def ensure_single_workspace_project(client, tools):
    project_tool, projects = project_listing(client, tools)
    created = False
    if not projects:
        create_name = next((name for name in ('t3_project_create', 'project_create')
                            if any(item.get('name') == name for item in tools)), None)
        if create_name is None:
            raise RuntimeError('supported isolated project creation MCP tool is unavailable')
        setup = Mcp(oauth_token('full-access'))
        setup.connect()
        setup_tools = setup.tools()
        create_schema = schema_for(setup_tools, create_name)
        create_args = {'title': 'Issue 28 S1b isolated bench',
                       'workspaceRoot': '/bench/ws'}
        create_payload = only_required_fields(create_schema, create_args)
        if set(create_payload) != set(create_args):
            raise RuntimeError('project-create schema cannot express isolated workspace authority')
        call_tool(setup, setup_tools, create_name, create_payload)
        project_tool, projects = project_listing(setup, setup_tools)
        created = True
    if len(projects) != 1:
        raise RuntimeError('expected exactly one isolated T3 project')
    project = projects[0]
    if project_path(project) != os.path.realpath('/bench/ws'):
        raise RuntimeError('isolated T3 project path does not match /bench/ws')
    project_id = project.get('id') if isinstance(project, dict) else None
    if not isinstance(project_id, str) or not project_id:
        raise RuntimeError('isolated T3 project has no valid ID')
    return project_id, created


def final_assistant_text(result, run_id=None):
    """Return the last completed assistant message, limited to run_id when one is given."""
    items = result.get('items') if isinstance(result, dict) else None
    if not isinstance(items, list):
        return None
    for item in reversed(items):
        if (isinstance(item, dict) and item.get('type') == 'assistant_message'
                and (run_id is None or item.get('runId') == run_id)
                and item.get('status') == 'completed' and isinstance(item.get('text'), str)):
            return item['text']
    return None


def opaque_thread_id(value):
    """Accept host-issued IDs as opaque transport strings; never treat them as paths."""
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 4096:
        return False
    return not any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in value)


def thread_artifact_path(results_root, thread_id):
    if not opaque_thread_id(thread_id):
        raise RuntimeError('thread ID rejected by safe transport constraints')
    digest = hashlib.sha256(thread_id.encode('utf-8')).hexdigest()
    return Path(results_root) / (digest + '.thread-read.json')


def verify_summary_boundary_tasks(client, tools, canary_result,
                                  input_root=Path('/bench/input'),
                                  results_root=Path('/bench/t3/observations')):
    ids = canary_result.get('summary_boundary_task_ids') if isinstance(canary_result, dict) else None
    if not isinstance(ids, dict) or set(ids) != {'32767', '32768', '32769'}:
        return {'verified': False, 'reason': 'summary boundary task IDs are missing or malformed',
                'records': []}
    try:
        task_schema = schema_for(tools, 'task_status')
        rows = []
        raw = {}
        for value in (32767, 32768, 32769):
            task_id = ids[str(value)]
            if not isinstance(task_id, str) or not task_id:
                raise RuntimeError('summary boundary task ID is invalid')
            arguments = only_required_fields(task_schema, {'taskId': task_id})
            status = unpack(call_tool(client, tools, 'task_status', arguments))
            if (status.get('status') not in {'completed', 'failed', 'cancelled', 'interrupted'}
                    or status.get('workState') != 'result_available'
                    or status.get('hasPendingChildRuns') is not False):
                raise RuntimeError(f'boundary task {value} is not terminal without pending work')
            summary = status.get('summary')
            if not isinstance(summary, str):
                raise RuntimeError(f'task_status returned no summary for {value}')
            returned = summary.encode('utf-8')
            expected = (input_root / f'summary-{value}.txt').read_bytes()
            expected_hash = hashlib.sha256(expected).hexdigest()
            actual_hash = hashlib.sha256(returned).hexdigest()
            row = {'expected_utf8_bytes': value, 'actual_utf8_bytes': len(returned),
                   'expected_sha256': expected_hash, 'actual_sha256': actual_hash,
                   'exact': returned == expected, 'task_id': task_id}
            rows.append(row)
            raw[str(value)] = status
        evidence = results_root / 'task-summary-boundaries.json'
        evidence.write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True) + '\n',
                            encoding='utf-8')
        evidence.chmod(0o600)
        return {'verified': all(row['exact'] for row in rows), 'records': rows}
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        return {'verified': False, 'reason': str(exc), 'records': []}


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(name):
    raise ValueError('non-finite JSON number ' + name)


def _finite_float(token):
    # Exponent overflow such as 1e999 parses to infinity without parse_constant.
    value = float(token)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number')
    return value


MAX_JSON_DEPTH = 512  # core.jobs.store's limit: Python 3.14+ may parse deeper without RecursionError


def json_depth(text):
    """Container nesting depth of already-parsed JSON text; quoted brackets are stripped first."""
    stripped = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"|[^\][{}"]+', '', text)
    return max(itertools.accumulate(1 if c in '[{' else -1 for c in stripped), default=0)


def parse_canary_result(text):
    """Parse the parent's final JSON object strictly: no duplicate keys, NaN, Infinity or deep nesting."""
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text, object_pairs_hook=_strict_object, parse_constant=_reject_constant,
                           parse_float=_finite_float)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) and json_depth(text) <= MAX_JSON_DEPTH else None


def verify_tracked_followup(client, tools, canary_result, results_root=Path('/bench/t3/observations')):
    followup = canary_result.get('tracked_followup') if isinstance(canary_result, dict) else None
    if not isinstance(followup, dict) or not hasattr(client, 'followup_observation'):
        return {'recorded': False, 'verified': False, 'reason': 'independent chronological host follow-up capture missing'}
    original_id, new_id = followup.get('original_task_id'), followup.get('new_task_id')
    if not isinstance(original_id, str) or new_id is not None and (not isinstance(new_id, str) or new_id == original_id):
        return {'recorded': False, 'verified': False, 'reason': 'follow-up identity invalid'}
    observed = client.followup_observation(original_id, new_id)
    if not observed:
        return {'recorded': False, 'verified': False, 'reason': 'no host-observed pre/post pair around the accepted continuation'}
    before, after = observed['before'], observed['after']
    summaries = [row.get('summary') for row in (before, after)]
    unchanged = all(isinstance(value, str) for value in summaries) and summaries[0] == summaries[1]
    terminal = all(row.get('status') == 'completed' and row.get('workState') == 'result_available'
                   and row.get('hasPendingChildRuns') is False for row in (before, after))
    if new_id is None:
        # Owner decision (pass 10): a refused continuation is recorded but never
        # counts as a pass, even when the host observed the original unchanged.
        # No authoritative policy-refusal record exists, so policy_blocked stays False.
        return {'recorded': True, 'supported': False, 'verified': False, 'policy_blocked': False,
                'counts_as_pass': False,
                'original_unchanged_host_observed': unchanged and terminal,
                'reason': 'continuation refused or unsupported; recorded fail-closed, never a pass'}
    try:
        resumed = unpack(client.call('task_status', {'taskId': new_id}))
        launch = observed['launch']
        target = launch['input'].get('target', {})
        same_child = bool(before.get('childThreadId')) and before['childThreadId'] == after.get('childThreadId') == resumed.get('childThreadId')
        verified = (unchanged and terminal and same_child and followup.get('status') == 'supported'
                    and resumed.get('status') == 'completed' and resumed.get('workState') == 'result_available'
                    and resumed.get('hasPendingChildRuns') is False and
                    # Raw types too: an integer identity never equals a boolean one.
                    all(type(resumed.get(key)) is str and resumed.get(key) == target.get(key)
                        for key in ('model', 'providerInstanceId')))
        path = results_root / 'tracked-followup-status.json'; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(json.dumps(observed, sort_keys=True) + '\n'); path.chmod(0o600)
        return {'recorded': True, 'supported': True, 'verified': verified, 'same_child_thread': same_child,
                'original_summary_sha256': hashlib.sha256(summaries[0].encode()).hexdigest() if unchanged else None}
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        return {'recorded': False, 'supported': True, 'verified': False, 'reason': type(exc).__name__}


ACTIVE_THREAD_STATUSES = frozenset({'preparing', 'queued', 'starting', 'running', 'waiting'})
TERMINAL_RUN_STATUSES = frozenset({'completed', 'failed', 'interrupted', 'cancelled'})
DEFAULT_WAIT_SECONDS = 2700
WAIT_SLICE_SECONDS = 900
UNSETTLED_POLL_SECONDS = 10
NOT_SETTLED = 'not settled'


def thread_snapshot(client, tools, thread_id):
    """One small thread-read for durable thread state: the thread row and its recent runs."""
    name = 't3_thread_read'
    props = schema_for(tools, name).get('properties', {})
    supplied = {'threadId': thread_id, 'view': 'messages', 'limit': 1, 'maxCharsPerItem': 1}
    if 'runLimit' in props:
        supplied['runLimit'] = min(50, schema_integer_maximum(props['runLimit']) or 50)
    arguments = {key: value for key, value in supplied.items() if key == 'threadId' or key in props}
    return unpack(call_tool(client, tools, name, arguments))


def thread_settlement(wait_result, snapshot):
    """Return (settled, latest_run_id, reasons) from the live wait and thread-read shapes.

    A thread is settled only when its latest run is terminal, no recent run is queued,
    starting, running or pending, no request is pending, and no child run is pending.
    A completed wait on one run says nothing about a later run T3 already queued.
    """
    reasons = []
    wait_result = wait_result if isinstance(wait_result, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    thread = snapshot.get('thread') if isinstance(snapshot.get('thread'), dict) else {}
    if wait_result.get('status') in ACTIVE_THREAD_STATUSES:
        reasons.append('wait status is ' + str(wait_result.get('status')))
    if thread.get('status') in ACTIVE_THREAD_STATUSES or 'status' not in thread:
        reasons.append('thread status is ' + str(thread.get('status')))
    pending = thread.get('pendingRequestCount')
    if type(pending) is not int or pending != 0:
        reasons.append('thread has pending requests or no pending-request count')
    for source in (wait_result, thread):
        if 'hasPendingChildRuns' in source and source['hasPendingChildRuns'] is not False:
            reasons.append('child runs are pending')
        if source.get('workState') == 'waiting_for_children':
            reasons.append('thread is waiting for children')
    runs = snapshot.get('recentRuns')
    if not isinstance(runs, list) or not runs or not all(
            isinstance(run, dict) and type(run.get('ordinal')) is int and isinstance(run.get('runId'), str)
            for run in runs):
        return False, None, reasons + ['thread read returned no usable recent runs']
    latest = max(runs, key=lambda run: run['ordinal'])
    if thread.get('latestRunId') != latest['runId']:
        reasons.append('latest run is missing from the recent runs')
    run_count = thread.get('runCount')
    if type(run_count) is int and run_count != latest['ordinal']:
        reasons.append('latest run ordinal differs from the thread run count')
    for run in sorted(runs, key=lambda row: row['ordinal']):
        if run.get('status') not in TERMINAL_RUN_STATUSES:
            reasons.append(f"run {run['ordinal']} is {run.get('status')}")
    # An active-run pointer must name a listed terminal run; anything else is live work.
    active = thread.get('activeRunId')
    if active is not None and not any(run['runId'] == active and run.get('status') in TERMINAL_RUN_STATUSES
                                      for run in runs):
        reasons.append('thread has an active run')
    return not reasons, (latest['runId'] if not reasons else None), reasons


def wait_for_thread(client, tools, thread_id, deadline_seconds=DEFAULT_WAIT_SECONDS, clock=None, sleep=None):
    """Wait in bounded slices until the thread settles or the deadline passes.

    Returns (last wait result, deadline_exceeded). The result carries settled=True and
    latestRunId only when thread_settlement accepts a fresh thread read; otherwise it
    carries settled=False, status 'not settled' and the reasons. A deadline is a wait
    bound only: the accepted thread keeps running and is never relaunched.
    """
    import time
    clock = clock or time.monotonic
    pause = sleep or time.sleep
    if not isinstance(deadline_seconds, int) or isinstance(deadline_seconds, bool) or deadline_seconds <= 0:
        raise RuntimeError('wait deadline must be a positive whole number of seconds')
    deadline = clock() + deadline_seconds
    result = {'status': NOT_SETTLED, 'settled': False, 'unsettled': ['no wait completed']}
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            return result, True
        slice_ms = int(min(WAIT_SLICE_SECONDS, max(1, remaining)) * 1000)
        started = clock()
        waited = unpack(call_tool(client, tools, 't3_thread_wait', {'threadId': thread_id, 'timeoutMs': slice_ms}))
        reasons = ['wait status is ' + str(waited.get('status'))]
        if waited.get('status') not in ACTIVE_THREAD_STATUSES:
            settled, latest_run_id, reasons = thread_settlement(
                waited, thread_snapshot(client, tools, thread_id))
            if settled:
                return dict(waited, settled=True, latestRunId=latest_run_id), False
            # A terminal earlier run while another is queued, or pending work: keep waiting.
            # Idle threads return at once, so poll at a modest bounded rate.
            remaining = deadline - clock()
            if remaining > 0:
                pause(min(UNSETTLED_POLL_SECONDS, remaining))
        elif clock() - started < 1:
            pause(1)  # A wait that returns at once must not become a busy loop.
        result = dict(waited, status=NOT_SETTLED, observedStatus=waited.get('status'),
                      settled=False, unsettled=reasons)


def wait_and_read(client, tools, thread_id, deadline_seconds=DEFAULT_WAIT_SECONDS,
                  expected_message=None, results_root=Path('/bench/t3/observations'),
                  clock=None, sleep=None):
    """Wait for settlement, then read the final report from the latest terminal run only.

    An unsettled thread (deadline, queued run, pending request or child) reports status
    'not settled' and no final report: interim assistant output is never parsed or audited.
    """
    schema_for(tools, 't3_thread_wait')
    schema_for(tools, 't3_thread_read')
    wait_result, deadline_exceeded = wait_for_thread(client, tools, thread_id, deadline_seconds,
                                                     clock=clock, sleep=sleep)
    read_result = paged_thread_read(client, tools, thread_id)
    raw_path = thread_artifact_path(results_root, thread_id)
    raw_path.write_text(json.dumps(read_result, ensure_ascii=False) + '\n', encoding='utf-8')
    raw_path.chmod(0o600)
    exact_message = None
    if expected_message is not None:
        exact_message = any(item.get('type') == 'user_message' and item.get('text') == expected_message
                            for item in read_result.get('items', []))
    run_id = wait_result.get('latestRunId') if wait_result.get('settled') is True else None
    settled = run_id is not None and not deadline_exceeded
    if settled:
        # The final read must still describe the same settled run; a run queued since the
        # wait returned makes the read interim.
        still, latest, reasons = thread_settlement(wait_result, read_result)
        settled = still and latest == run_id
        if not settled:
            wait_result = dict(wait_result, settled=False, unsettled=reasons or ['latest run changed'])
    final_text = final_exact = canary_result = None
    if settled:
        final_text = final_assistant_text(read_result, run_id)
        reread = paged_thread_read(client, tools, thread_id)
        final_exact = final_text is not None and final_text.encode('utf-8') == (
            final_assistant_text(reread, run_id) or '').encode('utf-8')
        canary_result = parse_canary_result(final_text)
    thread = read_result.get('thread', {})
    # This OAuth client has no agent thread credential. Child observations
    # are exported from the authenticated parent's host-owned tool records
    # by benchctl, never obtained by expanding this client's authority.
    return {'threadId': thread_id,
            'status': wait_result.get('status') if settled else NOT_SETTLED,
            'settled': settled, 'latest_run_id': run_id if settled else None,
            'unsettled_reasons': [] if settled else wait_result.get('unsettled', []),
            'timed_out': deadline_exceeded,
            'readback_model': thread.get('model'),
            'readback_provider': thread.get('providerInstanceId'),
            'original_message_exact': exact_message,
            'final_message_retrieval_exact': final_exact is True,
            'final_message_utf8_bytes': len(final_text.encode('utf-8')) if final_text else None,
            'canary_result': canary_result,
            'summary_boundary_audit': {'verified': False,
                                       'reason': 'awaiting authenticated parent observations'},
            'tracked_followup_audit': {'recorded': False,
                                       'reason': 'awaiting authenticated parent observations'},
            'message_count': len(read_result.get('items', []))}


def _structured_or_empty(result):
    try:
        return unpack(result)
    except RuntimeError:
        return {}


def interrupt_thread(client, tools, thread_id):
    """Interrupt the owned parent thread through the live schema; no other field is sent."""
    name = 't3_thread_interrupt'
    schema = schema_for(tools, name)
    arguments = only_required_fields(schema, {'threadId': thread_id})
    validate_arguments(schema, arguments)
    return _structured_or_empty(client.call(name, arguments))


def resume_thread(client, tools, catalog, frozen, provider, thread_id, message):
    """Send the resume turn to the same thread with the frozen target, validated as role=resume.

    A live send schema that cannot carry the thread and message, or that requires a field this
    driver does not set, blocks before dispatch. Where the schema exposes modelSelection, the
    exact frozen target is sent so a resume can never change model or options.
    """
    selected = frozen[provider]
    model_policy.validate_target(catalog, {'providerInstanceId': provider, 'model': selected['model'],
                                           'options': selected['options']}, frozen, role='resume')
    name = 't3_thread_send'
    schema = schema_for(tools, name)
    props = schema.get('properties', {})
    supplied = {'threadId': thread_id, 'message': message}
    if 'modelSelection' in props:
        supplied['modelSelection'] = {'instanceId': provider, 'provider': provider,
                                      'model': selected['model'], 'options': selected['options']}
    for key, value in (('runtimeMode', 'auto'), ('interactionMode', 'default')):
        if key in props:
            supplied[key] = value
    arguments = only_required_fields(schema, supplied)
    validate_arguments(schema, arguments)
    return _structured_or_empty(client.call(name, arguments))


def discover_targets(catalog):
    patterns = {'codex': r'gpt-[0-9]+(?:\.[0-9]+)?-luna',
                'claudeAgent': r'claude-haiku-[0-9]+(?:-[0-9]+)*'}
    import re
    discovered = {}
    for provider_id, pattern in patterns.items():
        providers = [item for item in catalog.get('providers', [])
                     if item.get('providerInstanceId') == provider_id]
        # This catalog probe is for the top-level canary parent. A provider
        # that cannot run delegated children is still valid for this role;
        # child dispatches are checked separately with role='child'.
        if len(providers) != 1:
            raise RuntimeError('required cheap provider is unavailable in isolated catalog')
        candidates = []
        for model in providers[0].get('models', []):
            model_id = model.get('id')
            if not isinstance(model_id, str) or not re.fullmatch(pattern, model_id):
                continue
            option_ids = {item.get('id'): item for item in model.get('options', [])}
            if provider_id == 'codex':
                options = {'reasoningEffort': 'low', 'serviceTier': 'default'}
            elif option_ids.get('effort'):
                options = {'effort': 'low'}
                if 'fastMode' in option_ids:
                    options['fastMode'] = False
            elif (isinstance(option_ids.get('thinking'), dict)
                  and option_ids['thinking'].get('type') == 'boolean'):
                options = {'thinking': False}
            else:
                continue
            target = {'providerInstanceId': provider_id, 'model': model_id, 'options': options}
            try:
                model_policy.validate_target(catalog, target, role='canary')
            except ValueError:
                continue
            candidates.append(target)
        if not candidates:
            raise RuntimeError('no exact low-cost model with required options in isolated catalog')
        discovered[provider_id] = sorted(candidates, key=lambda item: item['model'])[0]
    return discovered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-only', action='store_true', help='discover exact targets from the isolated live catalog')
    parser.add_argument('--project-preflight', action='store_true',
                        help='verify or create the sole isolated workspace project without model dispatch')
    parser.add_argument('--launch-provider', choices=('codex', 'claudeAgent'))
    parser.add_argument('--wait-thread')
    parser.add_argument('--expected-message', type=Path)
    parser.add_argument('--prompt-file', type=Path)
    parser.add_argument('--title', default='Issue 28 S1b model policy canary')
    parser.add_argument('--find-launch', metavar='TITLE',
                        help='after an uncertain launch, list threads with this exact title; never relaunch')
    parser.add_argument('--role', choices=('canary', 'parent'), default='canary',
                        help='model-policy role of a top-level launch')
    parser.add_argument('--deadline-seconds', type=int,
                        help='with --wait-thread: total wait bound in seconds (default 2700)')
    parser.add_argument('--thread-status', metavar='THREAD', help='report a thread status after a 1 s wait')
    parser.add_argument('--interrupt-thread', metavar='THREAD', help='interrupt an owned parent thread')
    parser.add_argument('--send-thread', metavar='THREAD',
                        help='send --message-file to an owned thread as a resume turn (role=resume)')
    parser.add_argument('--message-file', type=Path)
    args = parser.parse_args()

    Path('/bench/t3/observations').mkdir(mode=0o700, exist_ok=True)
    client = Mcp(oauth_token())
    client.connect()
    tools = client.tools()
    caps_name = 'orchestrator_capabilities'
    schema_for(tools, caps_name)
    catalog = unpack(call_tool(client, tools, caps_name, {}))
    if args.catalog_only:
        targets = discover_targets(catalog)
        raw_path = Path('/bench/t3/observations/isolated-live-catalog.json')
        raw_path.write_text(json.dumps(catalog, sort_keys=True) + '\n', encoding='utf-8')
        raw_path.chmod(0o600)
        print(json.dumps({'catalog_discovered': True, 'targets': targets,
                          'catalog': catalog}, sort_keys=True))
        return 0
    policy = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    frozen = policy.get('targets')
    if not isinstance(frozen, dict):
        raise RuntimeError('immutable runtime target manifest is malformed')
    targets = model_policy.validate_frozen_map(catalog, frozen, role='canary')
    print(json.dumps({'catalog_verified': True, 'targets': targets}, sort_keys=True))
    if args.project_preflight:
        _project_id, created = ensure_single_workspace_project(client, tools)
        print(json.dumps({'project_preflight': 'passed', 'project_count': 1,
                          'workspace_path_matches': True,
                          'created_with_isolated_full_access_client': created}, sort_keys=True))
        return 0
    if args.thread_status or args.interrupt_thread:
        thread_id = args.thread_status or args.interrupt_thread
        if not opaque_thread_id(thread_id):
            raise RuntimeError('thread ID rejected by safe transport constraints')
        interrupted = interrupt_thread(client, tools, thread_id) if args.interrupt_thread else None
        state, _late = wait_for_thread(client, tools, thread_id, 60 if args.interrupt_thread else 1)
        print(json.dumps({'threadId': thread_id, 'status': state.get('status'),
                          'settled': state.get('settled') is True,
                          'interrupt_requested': args.interrupt_thread is not None,
                          'interrupt_result_status': (interrupted or {}).get('status')}, sort_keys=True))
        return 0
    if args.send_thread:
        thread_id = args.send_thread
        if not opaque_thread_id(thread_id):
            raise RuntimeError('thread ID rejected by safe transport constraints')
        if not args.launch_provider or not args.message_file:
            raise RuntimeError('--send-thread needs --launch-provider and --message-file')
        sent = resume_thread(client, tools, catalog, frozen, args.launch_provider, thread_id,
                             args.message_file.read_text(encoding='utf-8'))
        print(json.dumps({'resume_sent': True, 'threadId': thread_id,
                          'status': sent.get('status')}, sort_keys=True))
        return 0
    if args.wait_thread:
        thread_id = args.wait_thread
        if not opaque_thread_id(thread_id):
            raise RuntimeError('thread ID rejected by safe transport constraints')
        expected = (args.expected_message.read_text(encoding='utf-8')
                    if args.expected_message else None)
        report = wait_and_read(client, tools, thread_id, args.deadline_seconds or DEFAULT_WAIT_SECONDS,
                               expected)
        print(json.dumps(report, sort_keys=True))
        return 0 if report['settled'] else 2
    if args.find_launch:
        matches = find_launched_threads(client, tools, args.find_launch)
        print(json.dumps({'launch_lookup': True, 'thread_ids': matches}, sort_keys=True))
        return 0
    if not args.launch_provider:
        raise RuntimeError('select --catalog-only or --launch-provider')
    if not args.prompt_file:
        raise RuntimeError('--prompt-file is required for a parent canary launch')

    launch_name = 't3_thread_launch'
    launch_schema = schema_for(tools, launch_name)
    # The headless server is bootstrapped from /bench/ws and exposes one project.
    project_id, _created = ensure_single_workspace_project(client, tools)
    provider = args.launch_provider
    selected = targets[provider]
    model_selection = {'instanceId': provider, 'provider': provider,
                       'model': selected['model'], 'options': selected['options']}
    supplied = {'projectId': project_id, 'title': args.title,
                'message': args.prompt_file.read_text(encoding='utf-8'),
                'modelSelection': model_selection,
                'runtimeMode': 'auto', 'interactionMode': 'default',
                'workspaceStrategy': {'type': 'root'}}
    # Validate immediately before dispatch, regardless of caller/resume/retry path.
    model_policy.validate_target(catalog, {'providerInstanceId': provider, 'model': selected['model'],
                                           'options': selected['options']}, frozen, role=args.role)
    result = unpack(dispatch_with_schema(client, launch_name, launch_schema, supplied))
    thread_id = result.get('threadId')
    if not opaque_thread_id(thread_id):
        raise RuntimeError('T3 launch returned an invalid opaque thread ID')
    print(json.dumps({'launched': True, 'provider': provider,
                      'threadId': thread_id, 'status': result.get('status')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
        print('bench driver blocked: ' + str(exc), file=sys.stderr)
        sys.exit(2)
