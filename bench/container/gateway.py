#!/usr/bin/env python3
"""Model-filtering HTTPS reverse gateway for the isolated benchmark network."""
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

POLICY = Path(os.environ.get('BENCH_MODEL_POLICY', '/bench/config/stage-1b.json'))
MAX_BODY = 16 * 1024 * 1024
MAX_REPLY = 128 * 1024 * 1024
TARGETS = {}
TARGET_OPTIONS = {}
LOCKED = False
# ThreadingHTTPServer runs every connection in its own handler thread. One mutex
# serializes every LOCKED transition with the single upstream admission point,
# which records the request's forward-started event before releasing it: every
# recorded start precedes any lock, and no request is admitted after one.
LOCK_GUARD = threading.Lock()
UPSTREAMS = {
    'anthropic': ('api.anthropic.com', frozenset({'/v1/messages', '/v1/messages/count_tokens'})),
    'openai': ('api.openai.com', frozenset({'/v1/responses'})),
}
ANTHROPIC_QUERY_ROUTE = '/v1/messages?beta=true'
ANTHROPIC_COUNT_QUERY_ROUTE = '/v1/messages/count_tokens?beta=true'


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_policy(path=POLICY):
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    targets = data.get('targets')
    if not isinstance(targets, dict):
        raise ValueError('target map missing')
    if data.get('deny_all') is True and targets == {}:
        return {}
    expected = {'claudeAgent': r'claude-haiku-[0-9]+(?:-[0-9]+)*',
                'codex': r'gpt-[0-9]+(?:\.[0-9]+)?-luna'}
    if set(targets) != set(expected):
        raise ValueError('frozen provider allowlist mismatch')
    for provider, pattern in expected.items():
        entry = targets[provider]
        if (not isinstance(entry, dict) or not isinstance(entry.get('model'), str)
                or entry.get('providerInstanceId') != provider
                or not re.fullmatch(pattern, entry['model'])):
            raise ValueError('frozen model family mismatch')
        expected_options = ({'reasoningEffort': 'low', 'serviceTier': 'default'}
                            if provider == 'codex' else None)
        if provider == 'claudeAgent':
            options = entry.get('options')
            if (not isinstance(options, dict)
                    or options not in ({'effort': 'low'}, {'effort': 'low', 'fastMode': False},
                                       {'thinking': False}) or any(type(v) is not bool for k, v in options.items() if k in {'thinking', 'fastMode'})):
                raise ValueError('frozen Claude options mismatch')
        elif entry.get('options') != expected_options:
            raise ValueError('frozen Codex options mismatch')
    return {provider: entry['model'] for provider, entry in targets.items()}


def parse_body(body):
    if not body:
        raise ValueError('empty request')
    try:
        obj = json.loads(body.decode('utf-8'), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError('invalid JSON') from exc
    if not isinstance(obj, dict) or not isinstance(obj.get('model'), str):
        raise ValueError('missing model')
    return obj['model']


def response_metadata(body, content_type):
    """Read model/usage from provider response envelopes; never log content."""
    models, usage = set(), {}
    allowed_usage = {'input_tokens', 'output_tokens', 'total_tokens',
                     'cache_creation_input_tokens', 'cache_read_input_tokens'}
    try:
        text = body.decode('utf-8')
        if 'text/event-stream' in content_type:
            records = [json.loads(line[5:].strip(), object_pairs_hook=unique_object)
                       for line in text.splitlines() if line.startswith('data:')
                       and line[5:].strip() != '[DONE]']
        else:
            records = [json.loads(text, object_pairs_hook=unique_object)]
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('provider response envelope is not an object')
            envelope = record
            if isinstance(record.get('response'), dict):
                envelope = record['response']
            elif record.get('type') == 'message_start' and isinstance(record.get('message'), dict):
                envelope = record['message']
            model = envelope.get('model')
            if isinstance(model, str) and model:
                models.add(model)
            fields = envelope.get('usage')
            if isinstance(fields, dict):
                for name in allowed_usage:
                    value = fields.get(name)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        usage[name] = value
                for section, name in (('input_tokens_details', 'cached_tokens'),
                                      ('output_tokens_details', 'reasoning_tokens')):
                    detail = fields.get(section)
                    value = detail.get(name) if isinstance(detail, dict) else None
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        usage[name] = value
        complete = (any(record.get('type') in {'response.completed', 'message_stop'} for record in records)
                    if 'text/event-stream' in content_type else bool(models))
        return {'response_model_ids': sorted(models), 'usage': usage or None, 'response_complete': complete,
                'observation_reason': None if models else 'provider response has no model identity'}
    except (UnicodeError, ValueError, TypeError):
        return {'response_model_ids': [], 'usage': None, 'response_complete': False,
                'observation_reason': 'provider response metadata could not be parsed completely'}


def header_safe(value):
    """Return the text if it is safe to emit in an HTTP header line, else None (no CR, LF or NUL)."""
    text = str(value)
    return None if any(c in text for c in '\r\n\x00') else text


class PolicyError(ValueError):
    """A policy rejection that names the offending request fields, never their values."""

    def __init__(self, reason, fields=()):
        super().__init__(reason)
        self.fields = sorted(fields)


# Request controls with documented price or speed premiums. They keep their own
# rejection reason; the allowlist below would also reject them.
PREMIUM_BODY_FIELDS = {'anthropic': {'speed', 'inference_geo'}, 'openai': set()}
PREMIUM_BETA_TOKEN = re.compile(r'(?i)context-1m|fast-mode|priority')
# Documented top-level request fields per route (Anthropic Messages and Count
# Tokens, OpenAI Responses) that carry no separate price, speed, region or
# server-side execution premium. Anything else is rejected before upstream.
# Nested values are not price-checked here except the tool and option guards below.
ALLOWED_BODY_FIELDS = {
    '/v1/messages': frozenset({
        'model', 'messages', 'system', 'max_tokens', 'metadata', 'stop_sequences',
        'stream', 'temperature', 'top_k', 'top_p', 'tools', 'tool_choice', 'thinking',
        'output_config', 'service_tier', 'context_management'}),
    '/v1/messages/count_tokens': frozenset({
        'model', 'messages', 'system', 'tools', 'tool_choice', 'thinking',
        'output_config', 'context_management'}),
    '/v1/responses': frozenset({
        'model', 'input', 'instructions', 'tools', 'tool_choice', 'parallel_tool_calls',
        'reasoning', 'store', 'stream', 'stream_options', 'include', 'prompt_cache_key',
        'text', 'service_tier', 'metadata', 'client_metadata', 'max_output_tokens', 'max_tool_calls',
        'temperature', 'top_p', 'top_logprobs', 'truncation', 'user', 'safety_identifier',
        'previous_response_id'}),
}
MAX_LOGGED_FIELD = 64
# Client-executed tool shapes only. Provider server tools (web search, image
# generation, computer use, code execution, file search, MCP, web fetch, tool
# search, ...) run and bill on the provider side, so any other `type` is rejected.
# Claude Code 2.1.296 sends client tools with no `type`; Anthropic's explicit
# form is `custom`. Codex executes function, custom and local_shell tools itself.
ALLOWED_TOOL_TYPES = {'anthropic': frozenset({None, 'custom'}),
                      'openai': frozenset({'function', 'custom', 'local_shell'})}


def beta_tokens(values):
    return sorted({token.strip() for value in values for token in value.split(',') if token.strip()})


def logged_field_name(name):
    """Field names are client-controlled; log a bounded printable form, never a value."""
    text = ''.join(ch if ch.isprintable() else '?' for ch in name)
    return text[:MAX_LOGGED_FIELD]


def enforce_tools(provider, obj):
    """Admit only client-executed tool definitions; log tool type names, never definitions."""
    if 'tools' not in obj:
        return
    tools = obj['tools']
    if not isinstance(tools, list):
        raise PolicyError('tools must be a list of client tool definitions', ['tools'])
    allowed = ALLOWED_TOOL_TYPES[provider]
    rejected = set()
    for tool in tools:
        if not isinstance(tool, dict):
            rejected.add('<non-object>')
            continue
        kind = tool.get('type')
        if 'type' in tool and not isinstance(kind, str):
            rejected.add('<non-string>')
        elif kind not in allowed:
            rejected.add('<missing>' if kind is None else logged_field_name(kind))
    if rejected:
        raise PolicyError('server-side or unsupported tool type is not allowed',
                          ['tools[].type:' + name for name in rejected])


def enforce_request_controls(provider, obj, beta_values, route=None, openai_beta_values=()):
    """Reject premium-priced or undocumented body fields and beta tokens before any upstream connection."""
    premium = sorted(PREMIUM_BODY_FIELDS[provider] & set(obj))
    if premium:
        raise PolicyError('premium-priced request control is not allowed', premium)
    route = route or ('/v1/messages' if provider == 'anthropic' else '/v1/responses')
    unknown = sorted(logged_field_name(key) for key in set(obj) - ALLOWED_BODY_FIELDS[route])
    if unknown:
        raise PolicyError('request field is outside the documented allowlist', unknown)
    enforce_tools(provider, obj)
    tokens = beta_tokens(beta_values)
    if any(PREMIUM_BETA_TOKEN.search(token) for token in tokens):
        raise PolicyError('premium-priced beta feature is not allowed', ['anthropic-beta'])
    if any(PREMIUM_BETA_TOKEN.search(token) for token in beta_tokens(openai_beta_values)):
        raise PolicyError('premium-priced beta feature is not allowed', ['openai-beta'])
    return tokens


def enforce_options(provider, obj, model):
    """Reject cost-tier drift; pin the documented standard tier if clients omit it."""
    if provider == 'anthropic':
        options = TARGET_OPTIONS.get('claudeAgent', {})
        if options == {'thinking': False}:
            # This catalog exposes only a thinking boolean. Its false value is
            # omission or Claude Code's explicit {"type": "disabled"}; reject any
            # attempt to enable extended thinking or substitute an effort field.
            if 'thinking' in obj and obj['thinking'] != {'type': 'disabled'}:
                raise PolicyError('extended thinking or unsupported effort setting is not allowed',
                                  ['thinking'])
            output = obj.get('output_config', {})
            if not isinstance(output, dict) or set(output) - {'format'}:
                raise PolicyError('unsupported output configuration or effort setting', ['output_config'])
            fmt = output.get('format')
            if fmt is not None and (not isinstance(fmt, dict) or set(fmt) != {'type', 'schema'}
                                    or fmt['type'] != 'json_schema' or not isinstance(fmt['schema'], dict)):
                raise PolicyError('unsupported structured output format', ['output_config'])
            if obj.get('service_tier', 'standard_only') != 'standard_only':
                raise ValueError('standard-only service is required')
            obj['service_tier'] = 'standard_only'
            return json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if options.get('effort') != 'low':
            raise ValueError('unsupported frozen Claude effort option')
        output = obj.get('output_config')
        if not isinstance(output, dict) or output.get('effort') != options['effort'] or set(output) - {'effort', 'format'}:
            raise ValueError('low effort is required')
        if 'thinking' in obj and obj['thinking'] != {'type': 'disabled'}:
            raise PolicyError('extended thinking is not allowed', ['thinking'])
        fmt = output.get('format')
        if fmt is not None and (not isinstance(fmt, dict) or set(fmt) != {'type', 'schema'} or fmt['type'] != 'json_schema' or not isinstance(fmt['schema'], dict)):
            raise PolicyError('unsupported structured output format', ['output_config'])
        if obj.get('service_tier', 'standard_only') != 'standard_only':
            raise ValueError('standard-only service is required')
        obj['service_tier'] = 'standard_only'
    else:
        reasoning = obj.get('reasoning')
        if not isinstance(reasoning, dict) or reasoning.get('effort') != 'low':
            raise ValueError('low effort is required')
        if obj.get('service_tier', 'default') != 'default':
            raise ValueError('standard service is required')
        obj['service_tier'] = 'default'
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # Never emit URLs, request headers, provider keys or request/response text.
        return

    def _reject(self, code, reason, lock=False, fields=None, event_kind='rejected'):
        if lock:
            self._record_lock()
        event = {'event': event_kind, 'reason': reason}
        if fields:
            event['fields'] = fields
        target = urlsplit(self.path)
        event['route'] = target.path if target.path in {'/v1/messages', '/v1/messages/count_tokens', '/v1/responses'} else 'unrecognized'
        event['query_present'] = bool(target.query)
        event['exact_beta_query'] = target.query == 'beta=true'
        print(json.dumps(event, separators=(',', ':')), flush=True)
        payload = json.dumps({'error': {'type': 'model_policy_rejected', 'message': reason}}).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)

    def _record_lock(self):
        """Record the fail-closed lock under the admission mutex (a lock writer)."""
        global LOCKED
        with LOCK_GUARD:
            LOCKED = True

    def _is_locked(self):
        """Read the lock under the admission mutex."""
        with LOCK_GUARD:
            return LOCKED

    def _admit_upstream(self, started):
        """The gateway's single atomic upstream admission point.

        Called once, after a request body is fully read and validated and
        immediately before any provider connection is opened. Under the same
        mutex every lock writer uses, it either refuses the request (the lock is
        set) or admits it and writes its forward-started event, so admission and
        the record of owned started work are one step: no lock can be recorded
        between them, every recorded start precedes the lock, and a refused
        request records no start and never reaches the provider. The provider
        connection itself is opened after the mutex is released, so a slow
        upstream or SSE relay never blocks a lock writer.
        """
        with LOCK_GUARD:
            if LOCKED:
                return False
            print(json.dumps(started), flush=True)
            return True

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/healthz' and not parsed.query and not parsed.fragment:
            payload = b'{"ready":true}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if (self.path == '/v1/responses'
                and (self.headers.get('Upgrade') or '').lower() == 'websocket'):
            # Codex tries a Responses websocket before its HTTPS fallback. Refuse
            # the upgrade without forwarding or locking; the POST is then checked.
            self._reject(426, 'websocket transport not offered; use HTTPS',
                         event_kind='transport-negotiation')
            return
        self._reject(405, 'endpoint not allowed', lock=True)

    def do_PUT(self):
        self._reject(405, 'endpoint not allowed', lock=True)

    def do_PATCH(self):
        self._reject(405, 'endpoint not allowed', lock=True)

    def do_DELETE(self):
        self._reject(405, 'endpoint not allowed', lock=True)

    def do_POST(self):
        if self._is_locked():
            self._reject(403, 'gateway locked after a rejected request')
            return
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            self._reject(400, 'invalid request target', lock=True)
            return
        if self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Content-Encoding'):
            self._reject(400, 'encoded request bodies are not accepted', lock=True)
            return
        lengths = self.headers.get_all('Content-Length') or []
        if len(lengths) != 1 or not lengths[0].isdigit():
            self._reject(411, 'one content length is required', lock=True)
            return
        length = int(lengths[0])
        if length <= 0 or length > MAX_BODY:
            self._reject(413, 'request size rejected', lock=True)
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._reject(400, 'incomplete request', lock=True)
            return
        try:
            obj = json.loads(body.decode('utf-8'), object_pairs_hook=unique_object)
            if not isinstance(obj, dict) or not isinstance(obj.get('model'), str):
                raise ValueError('missing model')
            model = obj['model']
        except ValueError as exc:
            self._reject(400, str(exc), lock=True)
            return

        endpoint = parsed.path
        if parsed.query:
            # Claude Code 2.1.296 uses this exact native Messages route.
            # Compare the raw request target; parsing/normalizing query strings
            # would also admit duplicate, reordered, or encoded variants.
            if self.path not in {ANTHROPIC_QUERY_ROUTE, ANTHROPIC_COUNT_QUERY_ROUTE}:
                self._reject(400, 'invalid request target', lock=True)
                return
            endpoint = parsed.path
        match = next(((name, host, paths) for name, (host, paths) in UPSTREAMS.items()
                      if endpoint in paths or (name == 'anthropic'
                                               and endpoint == ANTHROPIC_QUERY_ROUTE
                                               and '/v1/messages' in paths)), None)
        if match is None:
            self._reject(403, 'endpoint not allowed', lock=True)
            return
        provider_name, host, _paths = match
        provider_id = 'claudeAgent' if provider_name == 'anthropic' else 'codex'
        if TARGETS.get(provider_id) != model:
            self._reject(403, 'model is outside the frozen low-cost allowlist', lock=True)
            return
        estimation = parsed.path == '/v1/messages/count_tokens'
        try:
            request_fields = sorted(obj)
            betas = enforce_request_controls(provider_name, obj, self.headers.get_all('anthropic-beta') or [],
                                             route=parsed.path,
                                             openai_beta_values=self.headers.get_all('openai-beta') or [])
            original_tier = obj.get('service_tier')
            body = enforce_options(provider_name, obj, model)
            if estimation and original_tier is None:
                obj.pop('service_tier', None)  # The count API has no inference tier.
                body = json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        except ValueError as exc:
            fields = list(getattr(exc, 'fields', None) or [])
            output = obj.get('output_config')
            if 'output_config' in fields and isinstance(output, dict):
                fields += ['output_config.' + key for key in sorted(output) if key in {'effort', 'format', 'task_budget', 'timing'}]
            self._reject(403, str(exc), lock=True, fields=fields)
            return

        digest = hashlib.sha256(body).hexdigest()
        headers = {}
        allowed_headers = {'content-type', 'anthropic-version', 'anthropic-beta',
                           'openai-beta', 'accept', 'user-agent'}
        for key, value in self.headers.items():
            if key.lower() in allowed_headers:
                headers[key] = value
        credential = os.environ.get('ANTHROPIC_API_KEY' if provider_name == 'anthropic' else 'OPENAI_API_KEY')
        if not credential:
            self._reject(503, 'gateway provider credential unavailable', lock=True)
            return
        headers['x-api-key' if provider_name == 'anthropic' else 'Authorization'] = credential if provider_name == 'anthropic' else 'Bearer ' + credential
        # Prevent request-controlled proxy/routing headers and never follow redirects.
        headers['Host'] = host
        headers['Content-Length'] = str(len(body))
        conn = None
        begun = False
        failure_phase = 'upstream-failure'
        request_id = __import__('uuid').uuid4().hex
        kind = 'token-estimation' if estimation else 'inference'
        base = {'provider': provider_name, 'model': model, 'request_sha256': digest,
                'request_id': request_id, 'request_kind': kind,
                'body_fields': request_fields, 'beta_tokens': betas}
        # Admission point: the request body is complete and validated but a
        # concurrent handler may have rejected a forbidden request while this
        # body was still being read. Admission re-checks the lock and records
        # forward-started under the mutex every lock writer uses; a refused
        # request records no start and never reaches the provider.
        if not self._admit_upstream({'event': 'forward-started', **base}):
            self._reject(403, 'gateway locked after a rejected request')
            return
        try:
            conn = http.client.HTTPSConnection(host, timeout=900, context=ssl.create_default_context())
            conn.request('POST', self.path, body=body, headers=headers)
            response = conn.getresponse()
            status = response.status
            # Upstream values reach our own header lines: drop any that could split the response.
            response_headers = [(k, header_safe(v)) for k, v in response.getheaders()
                                if k.lower() in {'content-type', 'cache-control', 'request-id'}
                                and header_safe(v) is not None]
            reason = header_safe(response.reason) or ''
            content_type = next((v for k, v in response_headers if k.lower() == 'content-type'), '')
            if not 200 <= status < 300:
                self._record_lock()
            if 'text/event-stream' in content_type:
                failure_phase = 'downstream-cancellation'
                self.send_response(status, reason)
                for key, value in response_headers:
                    self.send_header(key, value)
                self.send_header('Connection', 'close')
                self.end_headers()
                begun = True
                result = relay_stream(response, self.wfile)
                self.close_connection = True
            else:
                result = response.read(MAX_REPLY + 1)
                if len(result) > MAX_REPLY:
                    raise OversizeReply('upstream response too large')
                failure_phase = 'downstream-cancellation'
                self.send_response(status, reason)
                for key, value in response_headers:
                    self.send_header(key, value)
                self.send_header('Content-Length', str(len(result)))
                self.send_header('Connection', 'close')
                self.end_headers()
                begun = True
                self.wfile.write(result)
            metadata = response_metadata(result, content_type)
            print(json.dumps({'event': 'forwarded', **base, 'status': status, **metadata}), flush=True)
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as exc:
            failure_kind = getattr(exc, 'failure_kind', failure_phase)
            print(json.dumps({'event': 'forward-failed', **base, 'reason': 'incomplete provider transport', 'failure_kind': failure_kind, 'exception_type': type(exc).__name__}), flush=True)
            if begun:
                self.close_connection = True
            else:
                self._reject(502, 'provider connection failed', event_kind='transport-error')
        finally:
            if conn is not None:
                conn.close()


class TransportFailure(OSError):
    def __init__(self, failure_kind):
        self.failure_kind = failure_kind
        super().__init__(failure_kind)


class OversizeReply(ValueError):
    """The provider sent more than MAX_REPLY bytes: an upstream fault, not a client cancel."""
    failure_kind = 'upstream-failure'


def relay_stream(response, destination):
    """Deliver SSE/heartbeat bytes immediately; retain bounded bytes for metadata."""
    chunks, length = [], 0
    while True:
        try:
            chunk = response.read1(64 * 1024)
        except (OSError, http.client.HTTPException):
            raise TransportFailure('upstream-failure') from None
        if not chunk:
            return b''.join(chunks)
        length += len(chunk)
        if length > MAX_REPLY:
            raise OversizeReply('upstream response too large')
        chunks.append(chunk)
        try:
            destination.write(chunk)
            destination.flush()
        except OSError:
            raise TransportFailure('downstream-cancellation') from None



def main():
    global TARGETS, TARGET_OPTIONS
    TARGETS = read_policy()
    data = json.loads(POLICY.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    TARGET_OPTIONS = {provider: entry['options'] for provider, entry in data.get('targets', {}).items()}
    cert = os.environ.get('BENCH_GATEWAY_CERT', '/run/secrets/gateway.crt')
    key = os.environ.get('BENCH_GATEWAY_KEY', '/run/secrets/gateway.key')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('BENCH_GATEWAY_PORT', '8443'))),
                                 GatewayHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(json.dumps({'event': 'ready', 'targets': TARGETS}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print('model gateway configuration rejected', file=sys.stderr)
        sys.exit(2)
