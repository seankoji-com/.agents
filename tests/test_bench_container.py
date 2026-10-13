"""Offline tests for the issue 28 S1b isolation and model egress boundary."""
import contextlib
import errno
import hashlib
import http.client
import io
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = ROOT / 'bench' / 'container'
POLICY = ROOT / 'migration' / 'rebuild' / 'compat-map.d' / 'stage-1b.json'
sys.path.insert(0, str(ROOT / 'bench' / 'v2' / 'tools'))
sys.path.insert(0, str(CONTAINER))
import gateway  # noqa: E402
import model_policy  # noqa: E402
import audit_models  # noqa: E402
import driver  # noqa: E402
import benchctl  # noqa: E402
import smoke  # noqa: E402
import host_observations  # noqa: E402


class FakeResponse:
    status = 200
    reason = 'OK'

    def getheaders(self):
        return [('Content-Type', 'application/json'), ('Connection', 'close')]

    def read(self, _limit=-1):
        return b'{"ok":true}'


class FakeUpstream:
    calls = []

    def __init__(self, host, timeout, context):
        self.calls.append({'host': host, 'timeout': timeout, 'verified_tls_context': context.verify_mode})

    def request(self, method, path, body, headers):
        self.calls[-1].update({'method': method, 'path': path, 'body': body, 'headers': headers})

    def getresponse(self):
        return FakeResponse()

    def close(self):
        pass


class FakeTaskClient:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return {'structuredContent': self.results[arguments['taskId']]}


class PagedReadClient:
    """Live T3 0.0.46 thread-read semantics: items page by position; long text by item offset."""

    def __init__(self, texts, chunk_size, page_limit=2):
        self.texts = texts
        self.chunk_size = chunk_size
        self.page_limit = page_limit
        self.calls = []

    @staticmethod
    def _units(text):
        return sum(2 if ord(ch) > 0xFFFF else 1 for ch in text)

    def _slice(self, text, start_units):
        # T3 offsets count UTF-16 code units, including supplementary symbols.
        units = end = 0
        while end < len(text) and units < start_units:
            units += 2 if ord(text[end]) > 0xFFFF else 1
            end += 1
        start, units = end, 0
        while end < len(text) and units < self.chunk_size:
            units += 2 if ord(text[end]) > 0xFFFF else 1
            end += 1
        following = self._units(text[:end]) if end < len(text) else None
        return text[start:end], following

    def _item(self, position, start_units):
        text, following = self._slice(self.texts[position], start_units)
        return {'position': position, 'itemId': f'item-{position}', 'createdBy': 'agent',
                'type': 'assistant_message', 'text': text,
                'textTruncated': following is not None, 'nextTextOffset': following}

    def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if 'itemId' in arguments:
            position = int(arguments['itemId'].split('-')[1])
            response = {'items': [self._item(position, arguments['textOffset'])],
                        'nextPosition': 0, 'hasMore': False}
        else:
            first = arguments.get('afterPosition', 0)
            positions = range(first, min(first + self.page_limit, len(self.texts)))
            response = {'items': [self._item(position, 0) for position in positions],
                        'nextPosition': first + len(positions),
                        'hasMore': first + len(positions) < len(self.texts)}
        response['thread'] = {'threadId': 'thread:opaque'}
        return {'structuredContent': response}


LIVE_THREAD_READ_SCHEMA = {'name': 't3_thread_read', 'inputSchema': {
    'type': 'object', 'properties': {
        'threadId': {'type': 'string'},
        'itemId': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
        'textOffset': {'anyOf': [{'type': 'integer', 'minimum': 0}, {'type': 'null'}]},
        'view': {'anyOf': [{'type': 'string', 'enum': ['messages', 'activity']}, {'type': 'null'}]},
        'afterPosition': {'anyOf': [{'type': 'integer', 'minimum': 0}, {'type': 'null'}]},
        'limit': {'anyOf': [{'type': 'integer', 'minimum': 1, 'maximum': 100}, {'type': 'null'}]},
        'maxCharsPerItem': {'anyOf': [{'type': 'integer', 'minimum': 1, 'maximum': 50000},
                                      {'type': 'null'}]}},
    'required': ['threadId'], 'additionalProperties': True}}


class FakeHandler(gateway.GatewayHandler):
    def __init__(self, path, payload, raw=None):
        data = raw if raw is not None else json.dumps(payload, separators=(',', ':')).encode()
        self.command = 'POST'
        self.path = path
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json'
        self.headers['Content-Length'] = str(len(data))
        self.headers['Authorization'] = 'Bearer not-a-real-key'
        self.rfile = io.BytesIO(data)
        self.wfile = io.BytesIO()
        self.result_headers = []
        self.status = None

    def send_response(self, status, _message=None):
        self.status = status

    def send_header(self, name, value):
        self.result_headers.append((name, value))

    def end_headers(self):
        pass


def request(_server, path, payload, raw=None):
    handler = FakeHandler(path, payload, raw)
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY':'synthetic-gateway-anthropic','OPENAI_API_KEY':'synthetic-gateway-openai'}):
        handler.do_POST()
    return handler.status, handler.wfile.getvalue()


class GatewayFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = None

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        self.credential_env = patch.dict(os.environ, {'ANTHROPIC_API_KEY':'synthetic-gateway-anthropic','OPENAI_API_KEY':'synthetic-gateway-openai'})
        self.credential_env.start()
        self.original_targets = gateway.TARGETS
        self.original_options = gateway.TARGET_OPTIONS
        self.original_locked = gateway.LOCKED
        gateway.LOCKED = False
        gateway.TARGETS = {'claudeAgent': 'claude-haiku-5-5', 'codex': 'gpt-6-luna'}
        gateway.TARGET_OPTIONS = {'claudeAgent': {'effort': 'low'},
                                  'codex': {'reasoningEffort': 'low', 'serviceTier': 'default'}}
        FakeUpstream.calls = []

    def tearDown(self):
        self.credential_env.stop()
        gateway.TARGETS = self.original_targets
        gateway.TARGET_OPTIONS = self.original_options
        gateway.LOCKED = self.original_locked

    def test_forbidden_models_and_bad_requests_make_zero_upstream_calls(self):
        cases = [
            ('/v1/responses', {'model': 'gpt-6-astra', 'reasoning': {'effort': 'low'},
                               'service_tier': 'default'}, 403),
            ('/v1/responses', {'model': 'gpt-6-luna-sol', 'reasoning': {'effort': 'low'},
                               'service_tier': 'default'}, 403),
            ('/v1/messages', {'model': 'claude-haiku-5-5-opus',
                              'output_config': {'effort': 'low'}}, 403),
            ('/v1/responses', {'reasoning': {'effort': 'low'}}, 400),
            ('/v1/responses', {'target': {'providerInstanceId': 'codex', 'model': 'gpt-6-astra'},
                               'options': {'reasoningEffort': 'low'}}, 400),
            ('/v1/responses', {'model': 'gpt-6-luna', 'reasoning': {'effort': 'high'},
                               'service_tier': 'default'}, 403),
            ('/v1/responses', {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'},
                               'service_tier': 'priority'}, 403),
            ('/v1/messages', {'model': 'claude-haiku-5-5', 'output_config': {'effort': 'high'},
                              'service_tier': 'standard_only'}, 403),
            ('/v1/messages', {'model': 'claude-haiku-5-5', 'output_config': {'effort': 'low'},
                              'service_tier': 'auto'}, 403),
            ('/v1/responses', {}, 400, b'{"model":"gpt-6-luna","model":"gpt-6-astra"}'),
            ('/v1/batches', {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}}, 403),
        ]
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            for case in cases:
                path, payload, expected = case[:3]
                raw = case[3] if len(case) == 4 else None
                with self.subTest(path=path, payload=payload):
                    gateway.LOCKED = False
                    code, _ = request(None, path, payload, raw)
                    self.assertEqual(code, expected)
            self.assertEqual(FakeUpstream.calls, [])

    def test_native_child_and_resume_model_edits_are_stopped_at_gateway(self):
        requests = [
            {'model': 'gpt-6-astra', 'reasoning': {'effort': 'low'}, 'service_tier': 'default'},
            {'target': {'providerInstanceId': 'claudeAgent', 'model': 'claude-opus-5-5'},
             'options': {'effort': 'low'}},
        ]
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            for body in requests:
                code, _ = request(None, '/v1/responses', body)
                self.assertIn(code, (400, 403))
            self.assertEqual(FakeUpstream.calls, [])

    def test_policy_rejection_locks_out_all_later_provider_requests(self):
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            forbidden, _ = request(None, '/v1/responses',
                                   {'model': 'gpt-6-astra', 'reasoning': {'effort': 'low'},
                                    'service_tier': 'default'})
            allowed, _ = request(None, '/v1/responses',
                                 {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'},
                                  'service_tier': 'default'})
        self.assertEqual((forbidden, allowed), (403, 403))
        self.assertTrue(gateway.LOCKED)
        self.assertEqual(FakeUpstream.calls, [])

    def test_isolated_forbidden_probe_uses_fresh_lock_state(self):
        # Production intentionally remains fail-closed. Probe and canary are
        # separate gateway processes, so a negative control cannot poison the
        # later provider process or clear its lock in place.
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            gateway.LOCKED = False
            denied, _ = request(None, '/v1/responses',
                                {'model': 'gpt-6-astra', 'reasoning': {'effort': 'low'},
                                 'service_tier': 'default'})
            self.assertEqual(denied, 403)
            self.assertTrue(gateway.LOCKED)
            self.assertEqual(FakeUpstream.calls, [])
            gateway.LOCKED = False  # fixture simulates a newly started gateway process
            allowed, _ = request(None, '/v1/responses',
                                 {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'},
                                  'service_tier': 'default'})
            self.assertEqual(allowed, 200)
            self.assertFalse(gateway.LOCKED)
            self.assertEqual(len(FakeUpstream.calls), 1)

    def test_allowed_openai_request_is_pinned_to_low_effort_and_standard(self):
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            code, _ = request(None, '/v1/responses',
                              {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}})
        self.assertEqual(code, 200)
        self.assertEqual(len(FakeUpstream.calls), 1)
        sent = json.loads(FakeUpstream.calls[0]['body'])
        self.assertEqual(sent['service_tier'], 'default')
        self.assertEqual(FakeUpstream.calls[0]['host'], 'api.openai.com')
        self.assertEqual(FakeUpstream.calls[0]['verified_tls_context'], 2)

    def test_allowed_anthropic_request_is_pinned_to_standard_only(self):
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            code, _ = request(None, '/v1/messages',
                              {'model': 'claude-haiku-5-5', 'output_config': {'effort': 'low'}})
        self.assertEqual(code, 200)
        sent = json.loads(FakeUpstream.calls[0]['body'])
        self.assertEqual(sent['service_tier'], 'standard_only')
        self.assertEqual(FakeUpstream.calls[0]['host'], 'api.anthropic.com')

    def test_native_anthropic_beta_route_is_forwarded_exactly(self):
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            code, _ = request(None, '/v1/messages?beta=true',
                              {'model': 'claude-haiku-5-5', 'output_config': {'effort': 'low'}})
        self.assertEqual(code, 200)
        self.assertEqual(FakeUpstream.calls[0]['path'], '/v1/messages?beta=true')

    def test_anthropic_query_variants_are_rejected_before_upstream(self):
        variants = ('/v1/messages?beta=true&beta=true', '/v1/messages?beta=false',
                    '/v1/messages?x=1&beta=true', '/v1/messages?%62eta=true',
                    '/v1/messages?beta=%74rue', '/v1/messages?beta=true#fragment',
                    '/v1/messages?beta=true;foo=1')
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            for route in variants:
                gateway.LOCKED = False
                code, _ = request(None, route,
                                  {'model': 'claude-haiku-5-5',
                                   'output_config': {'effort': 'low'}})
                with self.subTest(route=route):
                    self.assertEqual(code, 400)
            self.assertEqual(FakeUpstream.calls, [])

    def test_haiku_boolean_control_is_frozen_off_at_the_api_boundary(self):
        gateway.TARGETS = {'claudeAgent': 'claude-haiku-4-5', 'codex': 'gpt-6-luna'}
        gateway.TARGET_OPTIONS = {'claudeAgent': {'thinking': False}}
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            code, _ = request(None, '/v1/messages', {'model': 'claude-haiku-4-5'})
        self.assertEqual(code, 200)
        sent = json.loads(FakeUpstream.calls[0]['body'])
        self.assertNotIn('thinking', sent)
        self.assertEqual(sent['service_tier'], 'standard_only')
        FakeUpstream.calls = []
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            code, _ = request(None, '/v1/messages', {
                'model': 'claude-haiku-4-5',
                'thinking': {'type': 'enabled', 'budget_tokens': 8192}})
        self.assertEqual(code, 403)
        self.assertEqual(FakeUpstream.calls, [])

    def test_premium_controls_are_rejected_and_forwarded_field_names_are_logged(self):
        """C-8-08: premium speed/region/beta controls never reach the provider."""
        import contextlib
        cases = (({'speed': 'fast'}, None), ({'inference_geo': 'us'}, None),
                 ({}, 'claude-code-20250219,context-1m-2025-08-07'), ({}, 'fast-mode-2026-02-01'))
        for extra, beta in cases:
            with self.subTest(extra=extra, beta=beta):
                gateway.LOCKED = False
                FakeUpstream.calls = []
                handler = FakeHandler('/v1/messages', {'model': 'claude-haiku-5-5',
                                                       'output_config': {'effort': 'low'}, **extra})
                if beta:
                    handler.headers['anthropic-beta'] = beta
                with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream), \
                        contextlib.redirect_stdout(io.StringIO()):
                    handler.do_POST()
                self.assertEqual(handler.status, 403)
                self.assertEqual(FakeUpstream.calls, [])
        gateway.LOCKED = False
        FakeUpstream.calls = []
        log = io.StringIO()
        handler = FakeHandler('/v1/messages', {'model': 'claude-haiku-5-5', 'stream': True,
                                               'output_config': {'effort': 'low'}})
        handler.headers['anthropic-beta'] = 'claude-code-20250219, interleaved-thinking-2025-05-14'
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream), \
                contextlib.redirect_stdout(log):
            handler.do_POST()
        self.assertEqual(handler.status, 200)
        started = next(json.loads(line) for line in log.getvalue().splitlines()
                       if json.loads(line).get('event') == 'forward-started')
        self.assertEqual(started['body_fields'], ['model', 'output_config', 'stream'])
        self.assertEqual(started['beta_tokens'], ['claude-code-20250219', 'interleaved-thinking-2025-05-14'])

    def test_codex_websocket_upgrade_is_refused_without_locking_https_fallback(self):
        upgrade = FakeHandler('/v1/responses', None, raw=b'')
        upgrade.headers['Upgrade'] = 'websocket'
        upgrade.do_GET()
        self.assertEqual(upgrade.status, 426)
        self.assertFalse(gateway.LOCKED)
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            code, _ = request(None, '/v1/responses', {
                'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}})
        self.assertEqual(code, 200)
        self.assertEqual(len(FakeUpstream.calls), 1)
        for path, upgrade_header in (('/v1/responses?x=1', 'websocket'), ('/v1/models', 'websocket'),
                                     ('/v1/responses', None)):
            with self.subTest(path=path, upgrade=upgrade_header):
                gateway.LOCKED = False
                other = FakeHandler(path, None, raw=b'')
                if upgrade_header:
                    other.headers['Upgrade'] = upgrade_header
                other.do_GET()
                self.assertEqual(other.status, 405)
                self.assertTrue(gateway.LOCKED)

    def test_haiku_explicit_disabled_thinking_is_forwarded_and_other_forms_rejected(self):
        """Claude Code 2.1.296 sends {"type": "disabled"} when thinking is off."""
        import contextlib
        gateway.TARGETS = {'claudeAgent': 'claude-haiku-4-5', 'codex': 'gpt-6-luna'}
        gateway.TARGET_OPTIONS = {'claudeAgent': {'thinking': False}}
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            code, _ = request(None, '/v1/messages', {
                'model': 'claude-haiku-4-5', 'thinking': {'type': 'disabled'}})
        self.assertEqual(code, 200)
        sent = json.loads(FakeUpstream.calls[0]['body'])
        self.assertEqual(sent['thinking'], {'type': 'disabled'})
        self.assertEqual(sent['service_tier'], 'standard_only')
        for extra, field in (({'thinking': {'type': 'disabled', 'budget_tokens': 1024}}, 'thinking'),
                             ({'thinking': {'type': 'adaptive'}}, 'thinking'),
                             ({'output_config': {'effort': 'low'}}, 'output_config')):
            with self.subTest(field=field, body=extra):
                gateway.LOCKED = False
                FakeUpstream.calls = []
                log = io.StringIO()
                with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream), \
                        contextlib.redirect_stdout(log):
                    code, _ = request(None, '/v1/messages', {'model': 'claude-haiku-4-5', **extra})
                self.assertEqual(code, 403)
                self.assertEqual(FakeUpstream.calls, [])
                event = json.loads(log.getvalue().splitlines()[-1])
                self.assertEqual(event['fields'][0], field)
                self.assertNotIn('budget_tokens', log.getvalue())
                self.assertNotIn('adaptive', log.getvalue())


class HostObservationTest(unittest.TestCase):
    def test_agent_created_messages_are_selected_by_message_type(self):
        result = {'items': [
            {'createdBy': 'agent', 'type': 'assistant_message', 'status': 'completed',
             'text': '{"complete":true}'},
            {'createdBy': 'assistant', 'type': 'user_message', 'status': 'completed',
             'text': 'must not become the result'},
            {'createdBy': 'agent', 'type': 'assistant_message', 'status': 'running',
             'text': 'partial'}]}
        self.assertEqual(driver.final_assistant_text(result), '{"complete":true}')

    def test_expected_websocket_refusal_is_distinct_from_policy_rejection(self):
        handler = FakeHandler('/v1/responses', None, raw=b'')
        handler.headers['Upgrade'] = 'websocket'
        stream = io.StringIO()
        with patch('sys.stdout', stream):
            handler.do_GET()
        self.assertEqual(json.loads(stream.getvalue())['event'], 'transport-negotiation')
        events = stream.getvalue() + json.dumps({'event': 'rejected'}) + '\n'
        with tempfile.TemporaryDirectory() as temp, patch.object(benchctl.subprocess, 'run',
                return_value=type('Result', (), {'returncode': 0, 'stdout': events})()):
            self.assertEqual(benchctl.gateway_rejection_count('fixture', Path(temp) / 'log'), 1)

    def test_response_observation_reads_only_provider_model_and_usage(self):
        records = [
            {'type': 'response.created', 'response': {'model': 'gpt-6-luna'}},
            {'type': 'response.completed', 'response': {'model': 'gpt-6-luna',
             'output': [{'text': 'not metadata'}], 'usage': {'input_tokens': 4,
             'output_tokens': 7, 'total_tokens': 11,
             'input_tokens_details': {'cached_tokens': 2}}}}]
        raw = ''.join('data: ' + json.dumps(x) + '\n\n' for x in records).encode()
        observed = gateway.response_metadata(raw, 'text/event-stream')
        self.assertEqual(observed['response_model_ids'], ['gpt-6-luna'])
        self.assertEqual(observed['usage'], {'input_tokens': 4, 'output_tokens': 7,
                                          'total_tokens': 11, 'cached_tokens': 2})
        self.assertNotIn('not metadata', json.dumps(observed))
        broken = gateway.response_metadata(raw + b'data: {\n', 'text/event-stream')
        self.assertEqual(broken['response_model_ids'], [])
        self.assertIsNone(broken['usage'])

    def test_anthropic_stream_merges_input_and_output_usage(self):
        raw = (b'data: {"type":"message_start","message":{"model":"claude-haiku-5-5",'
               b'"usage":{"input_tokens":8,"cache_read_input_tokens":3}}}\n\n'
               b'data: {"type":"message_delta","usage":{"output_tokens":5}}\n\n')
        observed = gateway.response_metadata(raw, 'text/event-stream')
        self.assertEqual(observed['response_model_ids'], ['claude-haiku-5-5'])
        self.assertEqual(observed['usage']['output_tokens'], 5)
        self.assertEqual(observed['usage']['input_tokens'], 8)

    def test_host_snapshot_keeps_authenticated_results_and_rejects_pending_or_extra_children(self):
        target = {'providerInstanceId': 'codex', 'model': 'gpt-6-luna',
                  'options': {'reasoningEffort': 'low', 'serviceTier': 'default'}}
        launch = {'threadId': 'parent', 'status': 'completed', 'toolName': 't3-code.delegate_task',
                  'input': {'target': target}, 'output': {'taskId': 'task1'}}
        status = {'threadId': 'parent', 'status': 'completed', 'toolName': 't3-code.task_status',
                  'input': {'taskId': 'task1'}, 'output': {'taskId': 'task1', 'summary': 'whole',
                  'status': 'completed', 'workState': 'result_available', 'hasPendingChildRuns': False,
                  'providerInstanceId': 'codex', 'model': 'gpt-6-luna'}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'host.sqlite'
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE orchestration_v2_projection_turn_items '
                               '(thread_id TEXT, type TEXT, ordinal INTEGER, payload_json TEXT)')
            connection.execute('CREATE TABLE orchestration_v2_projection_subagents '
                               '(thread_id TEXT, payload_json TEXT)')
            for table in ('runs', 'runtime_requests', 'threads'):
                connection.execute('CREATE TABLE orchestration_v2_projection_' + table + ' (thread_id TEXT, payload_json TEXT)')
            for ordinal, record in enumerate((launch, status)):
                connection.execute('INSERT INTO orchestration_v2_projection_turn_items VALUES (?,?,?,?)',
                                   ('parent', 'dynamic_tool', ordinal, json.dumps(record)))
            connection.execute('INSERT INTO orchestration_v2_projection_subagents VALUES (?,?)',
                               ('parent', json.dumps({'threadId': 'parent', 'id': 'task1',
                                                      'childThreadId': 'child1'})))
            connection.execute('INSERT INTO orchestration_v2_projection_threads VALUES (?,?)', ('parent', json.dumps({'id':'parent'})))
            selection = {'instanceId': 'codex', 'model': 'gpt-6-luna', 'options': [
                {'id': key, 'value': value} for key, value in target['options'].items()]}
            connection.execute('INSERT INTO orchestration_v2_projection_threads VALUES (?,?)',
                               ('child1', json.dumps({'id': 'child1', 'modelSelection': selection})))
            connection.execute('INSERT INTO orchestration_v2_projection_runs VALUES (?,?)',
                               ('child1', json.dumps({'threadId': 'child1', 'status': 'completed',
                                                      'modelSelection': selection})))
            connection.commit()
            connection.close()
            observed = host_observations.read_snapshot(path, 'parent')
        self.assertTrue(host_observations.verify_owned_tasks(observed, ['task1'], target)['verified'])
        client = host_observations.CapturedTaskClient(observed)
        self.assertEqual(client.call('task_status', {'taskId': 'task1'})['structuredContent']['summary'], 'whole')
        with self.assertRaises(RuntimeError):
            client.call('task_status', {'taskId': 'unobserved'})
        observed['tool_records'][1]['output']['hasPendingChildRuns'] = True
        self.assertFalse(host_observations.verify_owned_tasks(observed, ['task1'], target)['verified'])
        observed['tool_records'][1]['output']['hasPendingChildRuns'] = False
        observed['subagents'].append({'id': 'unexpected'})
        self.assertFalse(host_observations.verify_owned_tasks(observed, ['task1'], target)['verified'])

    def test_format_only_and_count_requests_keep_cost_guards(self):
        gateway.TARGETS = {'claudeAgent': 'claude-haiku-4-5'}
        gateway.TARGET_OPTIONS = {'claudeAgent': {'thinking': False}}
        for config in ({}, {'format': None}, {'format': {'type': 'json_schema', 'schema': {'type': 'object'}}}):
            gateway.LOCKED = False; FakeUpstream.calls = []
            with self.subTest(config=config), patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
                code, _ = request(None, '/v1/messages', {'model': 'claude-haiku-4-5', 'output_config': config})
            self.assertEqual(code, 200)
        gateway.LOCKED = False; FakeUpstream.calls = []
        stream = io.StringIO()
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream), patch('sys.stdout', stream):
            code, _ = request(None, '/v1/messages/count_tokens', {'model': 'claude-haiku-4-5'})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(stream.getvalue().splitlines()[-1])['request_kind'], 'token-estimation')
        self.assertNotIn('service_tier', json.loads(FakeUpstream.calls[0]['body']))
        for extra in ({'output_config': {'effort': 'high'}}, {'output_config': {'timing': 'fast'}},
                      {'thinking': {'type': 'enabled', 'budget_tokens': 1024}}, {'service_tier': 'auto'}):
            gateway.LOCKED = False; FakeUpstream.calls = []
            with self.subTest(extra=extra), patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
                code, _ = request(None, '/v1/messages/count_tokens', {'model': 'claude-haiku-4-5', **extra})
            self.assertEqual(code, 403); self.assertEqual(FakeUpstream.calls, [])

    def test_sse_delivery_precedes_next_read_and_partial_reply_is_unverified(self):
        destination = io.BytesIO()
        chunks = [b': heartbeat\n\n', b'data: {"type":"response.created","response":{"model":"gpt-6-luna"}}\n\n']
        class Response:
            def read1(self, size):
                if chunks:
                    if len(chunks) == 1:
                        assert destination.getvalue() == b': heartbeat\n\n'
                    return chunks.pop(0)
                return b''
        raw = gateway.relay_stream(Response(), destination)
        self.assertEqual(raw, destination.getvalue())
        self.assertFalse(gateway.response_metadata(raw, 'text/event-stream')['response_complete'])
        with patch.object(gateway, 'MAX_REPLY', 2):
            with self.assertRaises(ValueError):
                gateway.relay_stream(type('Response', (), {'read1': lambda self, size: b'xxx'})(), io.BytesIO())

    def test_native_probe_requires_actual_target_runs_and_no_pending_approvals(self):
        target = {'providerInstanceId': 'codex', 'model': 'gpt-6-luna',
                  'options': {'reasoningEffort': 'low', 'serviceTier': 'default'}}
        observation = {'parent_thread_id': 'parent', 'tool_records': [], 'subagents': [
            {'id': 'native-id', 'origin': 'provider_native', 'threadId': 'parent',
             'prompt': 'ISSUE28_NATIVE_PROBE read/hash only', 'providerInstanceId': 'codex',
             'model': 'gpt-6-luna', 'childThreadId': 'native-thread', 'status': 'completed',
             'completedAt': '2026-10-12T00:00:00Z', 'result': 'a' * 64}], 'runs': [
            {'threadId': 'native-thread', 'status': 'completed', 'modelSelection': {
                'instanceId': 'codex', 'model': 'gpt-6-luna', 'options': [{'id': k, 'value': v} for k, v in target['options'].items()]}}],
            'threads': [{'id': 'native-thread', 'modelSelection': {'instanceId': 'codex',
                'model': 'gpt-6-luna', 'options': [{'id': k, 'value': v} for k, v in target['options'].items()]}}],
            'runtime_requests': []}
        result = host_observations.verify_owned_tasks(observation, [], target, native_probe=True, expected_input_sha256='a' * 64)
        self.assertTrue(result['native_child_visibility_verified'])
        observation['runs'][0]['modelSelection']['options'][0]['value'] = 'high'
        self.assertFalse(host_observations.verify_owned_tasks(observation, [], target, native_probe=True, expected_input_sha256='a' * 64)['native_child_visibility_verified'])
        observation['runs'][0]['modelSelection']['options'][0]['value'] = 'low'
        observation['runtime_requests'].append({'status': 'pending', 'kind': 'permission_approval'})
        self.assertFalse(host_observations.verify_owned_tasks(observation, [], target, native_probe=True, expected_input_sha256='a' * 64)['native_child_visibility_verified'])
        observation['runtime_requests'] = []
        observation['subagents'].append(dict(observation['subagents'][0], id='extra'))
        self.assertFalse(host_observations.verify_owned_tasks(observation, [], target, native_probe=True, expected_input_sha256='a' * 64)['native_child_visibility_verified'])

    def test_boundary_completion_without_pending_result_does_not_pass(self):
        tools = [{'name': 'task_status', 'inputSchema': {'type': 'object',
                 'properties': {'taskId': {'type': 'string'}}, 'required': ['taskId']}}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for size in (32767, 32768, 32769):
                (root / f'summary-{size}.txt').write_bytes(b'x' * size)
            statuses = {str(size): {'summary': 'x' * size, 'status': 'completed',
                         'workState': 'waiting_for_children', 'hasPendingChildRuns': True}
                        for size in (32767, 32768, 32769)}
            observed = driver.verify_summary_boundary_tasks(FakeTaskClient(statuses), tools,
                {'summary_boundary_task_ids': {str(size): str(size) for size in (32767, 32768, 32769)}},
                root, root)
            self.assertFalse(observed['verified'])


class DriverPagingTest(unittest.TestCase):
    def test_large_original_and_terminal_json_are_reassembled_across_utf16_pages(self):
        terminal = json.dumps({'summary': '終端🌙' * 12000}, ensure_ascii=False)
        original = 'original ' + ('🪴' * 16000)
        texts = [original, 'short reply', terminal]
        client = PagedReadClient(texts, 17000)
        readback = driver.paged_thread_read(client, [LIVE_THREAD_READ_SCHEMA], 'thread:opaque:read')
        self.assertEqual([item['text'] for item in readback['items']], texts)
        self.assertTrue(all(item['textTruncated'] is False and 'nextTextOffset' not in item
                            for item in readback['items']))
        self.assertTrue(all(call[1]['maxCharsPerItem'] == 50000 for call in client.calls))
        lists = [call[1] for call in client.calls if 'itemId' not in call[1]]
        self.assertEqual([call.get('afterPosition') for call in lists], [None, 2])
        continuations = [call[1] for call in client.calls if 'itemId' in call[1]]
        self.assertEqual(continuations[0], {'threadId': 'thread:opaque:read', 'itemId': 'item-0',
                                            'textOffset': 17001, 'maxCharsPerItem': 50000})
        self.assertNotIn('nextTextOffset', json.dumps([call[1] for call in client.calls]))
        self.assertEqual(json.loads(readback['items'][2]['text']), {'summary': '終端🌙' * 12000})

    def test_live_anyof_bound_is_used_and_missing_bound_blocks(self):
        self.assertEqual(driver.schema_integer_maximum(
            LIVE_THREAD_READ_SCHEMA['inputSchema']['properties']['maxCharsPerItem']), 50000)
        unbounded = json.loads(json.dumps(LIVE_THREAD_READ_SCHEMA))
        unbounded['inputSchema']['properties']['maxCharsPerItem'] = {
            'anyOf': [{'type': 'integer', 'minimum': 1}, {'type': 'null'}]}
        client = PagedReadClient(['text'], 10)
        with self.assertRaisesRegex(RuntimeError, 'no usable maxCharsPerItem bound'):
            driver.paged_thread_read(client, [unbounded], 'thread:opaque:read')
        self.assertEqual(client.calls, [])

    def test_text_pagination_that_does_not_advance_is_rejected(self):
        class Stuck(PagedReadClient):
            def _item(self, position, start_units):
                row = super()._item(position, 0)
                row['nextTextOffset'] = 5
                return row
        with self.assertRaisesRegex(RuntimeError, 'did not advance'):
            driver.paged_thread_read(Stuck(['x' * 50], 5), [LIVE_THREAD_READ_SCHEMA], 'thread:opaque')

    def test_schema_bounds_reject_overflow_before_tool_call(self):
        schema = {'type': 'object', 'properties': {'count': {'type': 'integer', 'maximum': 3}},
                  'required': ['count']}
        with self.assertRaises(RuntimeError):
            driver.validate_arguments(schema, {'count': 4})


class PolicyAndIsolationTest(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(POLICY.read_text(encoding='utf-8'))
        self.targets = {
            'codex': {'providerInstanceId': 'codex', 'model': 'gpt-6-luna',
                      'options': {'reasoningEffort': 'low', 'serviceTier': 'default'}},
            'claudeAgent': {'providerInstanceId': 'claudeAgent', 'model': 'claude-haiku-5-5',
                            'options': {'effort': 'low'}},
        }
        self.catalog = {'providers': [
            {'providerInstanceId': 'codex', 'canRunChildTask': True, 'models': [
                {'id': 'gpt-6-luna', 'options': [
                    {'id': 'reasoningEffort', 'options': [{'id': 'low'}, {'id': 'high'}]},
                    {'id': 'serviceTier', 'options': [{'id': 'default'}, {'id': 'priority'}]}]}]},
            {'providerInstanceId': 'claudeAgent', 'canRunChildTask': True, 'models': [
                {'id': 'claude-haiku-5-5', 'options': [
                    {'id': 'effort', 'options': [{'id': 'low'}, {'id': 'high'}]}]}]}]}

    def test_live_targets_match_frozen_exact_ids_and_options(self):
        for provider in ('codex', 'claudeAgent'):
            target = self.targets[provider]
            result = model_policy.validate_target(self.catalog, target, self.targets)
            self.assertEqual(result['providerInstanceId'], provider)
            self.assertEqual(result['model'], target['model'])
            self.assertEqual(result['options'], target['options'])

    def test_live_haiku_boolean_option_is_discovered_and_frozen_off(self):
        catalog = json.loads(json.dumps(self.catalog))
        catalog['providers'][1]['models'] = [{
            'id': 'claude-haiku-4-5',
            'options': [{'id': 'thinking', 'type': 'boolean'}]}]
        target = {'providerInstanceId': 'claudeAgent', 'model': 'claude-haiku-4-5',
                  'options': {'thinking': False}}
        self.assertEqual(model_policy.validate_target(catalog, target), target)
        with self.assertRaises(ValueError):
            model_policy.validate_target(catalog, dict(target, options={'thinking': True}))

    def test_driver_discovers_targets_from_only_the_isolated_catalog(self):
        catalog = json.loads(json.dumps(self.catalog))
        catalog['providers'][1]['models'] = [{
            'id': 'claude-haiku-4-5',
            'options': [{'id': 'thinking', 'type': 'boolean'}]}]
        targets = driver.discover_targets(catalog)
        self.assertEqual(targets['codex']['model'], 'gpt-6-luna')
        self.assertEqual(targets['codex']['options'],
                         {'reasoningEffort': 'low', 'serviceTier': 'default'})
        self.assertEqual(targets['claudeAgent']['model'], 'claude-haiku-4-5')
        self.assertEqual(targets['claudeAgent']['options'], {'thinking': False})

    def test_driver_parent_catalog_discovery_does_not_require_child_capability(self):
        catalog = json.loads(json.dumps(self.catalog))
        catalog['providers'][1]['canRunChildTask'] = False
        targets = driver.discover_targets(catalog)
        self.assertEqual(targets['claudeAgent'], self.targets['claudeAgent'])
        self.assertEqual(targets['codex'], self.targets['codex'])

        # The same catalog still fails closed before any delegated dispatch.
        class NoDispatch:
            calls = 0

            def call(self, *_args):
                self.calls += 1

        client = NoDispatch()
        with self.assertRaises(ValueError):
            model_policy.validate_target(catalog, self.targets['claudeAgent'],
                                         role='child')
        self.assertEqual(client.calls, 0)

    def test_frozen_policy_rejects_resume_edit_missing_options_or_provider(self):
        luna = self.targets['codex']
        bad = [dict(luna, model='gpt-6-astra'), dict(luna, options={}),
               dict(luna, providerInstanceId='antigravity')]
        for target in bad:
            with self.subTest(target=target), self.assertRaises(ValueError):
                model_policy.validate_target(self.catalog, target, self.targets)

    def test_costly_target_rejected_with_valid_options_and_absent_or_forged_pins(self):
        costly = {'providerInstanceId': 'codex', 'model': 'gpt-6-sol',
                  'options': {'reasoningEffort': 'low', 'serviceTier': 'default'}}
        self.catalog['providers'][0]['models'].append(
            {'id': 'gpt-6-sol', 'options': [
                {'id': 'reasoningEffort', 'options': [{'id': 'low'}, {'id': 'high'}]},
                {'id': 'serviceTier', 'options': [{'id': 'default'}, {'id': 'priority'}]}]})
        forged = dict(self.targets)
        forged['codex'] = costly
        for pinned in (None, forged):
            with self.subTest(pinned=bool(pinned)), self.assertRaises(ValueError):
                model_policy.validate_target(self.catalog, costly, pinned)

    def test_entire_frozen_map_is_required_and_family_checked(self):
        self.assertEqual(set(model_policy.validate_frozen_map(
            self.catalog, self.targets)), {'codex', 'claudeAgent'})
        forged = dict(self.targets)
        forged['codex'] = dict(forged['codex'], model='gpt-6-sol')
        self.catalog['providers'][0]['models'].append(
            {'id': 'gpt-6-sol', 'options': [
                {'id': 'reasoningEffort', 'options': [{'id': 'low'}]},
                {'id': 'serviceTier', 'options': [{'id': 'default'}]}]})
        with self.assertRaises(ValueError):
            model_policy.validate_frozen_map(self.catalog, forged)

    def test_policy_has_only_the_two_live_cheap_targets(self):
        self.assertNotIn('targets', self.policy)
        self.assertEqual(self.policy['runtime_policy']['families'],
                         {'claudeAgent': 'haiku', 'codex': 'luna'})
        self.assertFalse(self.policy['runtime_policy']['model_escalation'])
        self.assertEqual(self.policy['runtime_policy']['effort'], 'low')
        self.assertEqual(self.policy['runtime_policy']['service_tier'], 'standard')

    def test_container_has_no_owner_home_or_secret_mount_and_main_network_is_private(self):
        root = Path('/private-fixture')
        fixture_run = '20261012T031839Z-d91b43'
        agent_name = 'agent-' + fixture_run
        argv = benchctl.agent_command(agent_name, 'private-fixture', root / 'input',
                                      root / 'workspace', root / 'raw', root / 'state',
                                      root / 'config', root / 'ca.pem', 'image-fixture')
        self.assertEqual(argv[:5], ['docker', 'run', '-d', '--name', agent_name])
        self.assertIn('--network', argv)
        self.assertIn('private-fixture', argv)
        self.assertNotIn('--env-file', argv)
        self.assertNotIn(str(benchctl.SECRET_ENV), argv)
        self.assertIn('ANTHROPIC_API_KEY=bench-synthetic-anthropic', argv)
        self.assertIn('OPENAI_API_KEY=bench-synthetic-openai', argv)
        self.assertNotIn('-p', argv)
        mounts = [argv[index + 1] for index, item in enumerate(argv[:-1]) if item == '-v']
        self.assertEqual(len(mounts), 8)
        self.assertTrue(all('~/.claude' not in mount and '~/.codex' not in mount
                            and '/var/run/docker.sock' not in mount for mount in mounts))
        source = (CONTAINER / 'benchctl.py').read_text(encoding='utf-8')
        self.assertNotIn('SECRET_ENV.read_text', source)
        startup = (CONTAINER / 'start-container.sh').read_text(encoding='utf-8')
        self.assertNotIn('model = "gpt-6-luna"', startup)
        self.assertIn('git -C /bench/ws init --quiet', startup)
        self.assertIn('cd /bench/ws', startup)
        self.assertIn('--auto-bootstrap-project-from-cwd \\\n', startup)
        bootstrap = benchctl.gateway_bootstrap_command('gateway-' + fixture_run, 'egress-fixture',
                                                        root / 'config', root / 'cert',
                                                        root / 'key', 'image-fixture')
        self.assertIn('BENCH_MODEL_POLICY=/bench/config/bootstrap.json', bootstrap)
        self.assertNotIn('-p', bootstrap)

    def test_container_mount_roots_keep_required_modes_under_restrictive_umask(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = __import__('os').umask(0o077)
            try:
                run_dir = Path(tmp) / 'run'
                run_dir.mkdir(mode=0o700)
                config = benchctl.write_policy(run_dir)
                task_input = benchctl.make_input(run_dir)
            finally:
                __import__('os').umask(previous)
            self.assertEqual(config.parent.stat().st_mode & 0o777, 0o755)
            self.assertEqual(task_input.stat().st_mode & 0o777, 0o755)
            self.assertEqual(config.stat().st_mode & 0o777, 0o444)

    @unittest.skipUnless(__import__('shutil').which('openssl'), 'openssl is required')
    def test_gateway_serves_a_ca_signed_leaf_that_rustls_accepts(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            log = run_dir / 'private.log'
            log.touch(mode=0o600)
            ca_cert, cert, key = benchctl.certificate(run_dir, log)
            self.assertEqual({path.name for path in (run_dir / 'tls').iterdir()},
                             {'ca.crt', 'ca.srl', 'gateway.crt', 'gateway.key', 'gateway.ext'})
            self.assertFalse((run_dir / 'tls' / 'ca.key').exists(), 'CA key must not outlive issuance')
            verify = subprocess.run(['openssl', 'verify', '-CAfile', str(ca_cert),
                                     '-verify_hostname', 'gateway.bench.test', '-purpose', 'sslserver',
                                     str(cert)], capture_output=True, text=True)
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            leaf = subprocess.run(['openssl', 'x509', '-in', str(cert), '-noout', '-text'],
                                  capture_output=True, text=True, check=True).stdout
            self.assertIn('CA:FALSE', leaf)
            self.assertIn('DNS:gateway.bench.test', leaf)
            self.assertNotEqual(ca_cert.read_bytes(), cert.read_bytes())
            self.assertTrue(key.is_file())

    def test_helper_run_must_be_recorded_by_t3_for_a_child_thread(self):
        """C-8-04: helper.json alone is not proof; T3's command record is required."""
        import sqlite3
        command = benchctl.helper_command('codex')
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'host.sqlite'
            connection = sqlite3.connect(db)
            for table in ('turn_items', 'subagents', 'runs', 'runtime_requests', 'threads'):
                connection.execute(f'CREATE TABLE orchestration_v2_projection_{table} '
                                   '(thread_id TEXT, type TEXT, ordinal INTEGER, payload_json TEXT)')
            connection.execute('INSERT INTO orchestration_v2_projection_subagents VALUES (?,?,?,?)',
                               ('parent', 'subagent', 1, json.dumps({'threadId': 'parent', 'id': 'primary', 'childThreadId': 'child'})))
            rows = [('child', f"/bin/bash -lc '{command}'", 0, 'completed'),
                    ('child', 'python3 /opt/bench/smoke_helper.py /bench/input/brief.txt /tmp/x.json', 0, 'completed')]
            for ordinal, (thread, text, code, status) in enumerate(rows):
                connection.execute('INSERT INTO orchestration_v2_projection_turn_items VALUES (?,?,?,?)',
                                   (thread, 'command_execution', ordinal, json.dumps({
                                       'id': f'item-{ordinal}', 'threadId': thread, 'status': status,
                                       'exitCode': code, 'input': text, 'output': 'not retained'})))
            connection.commit(); connection.close()
            observed = host_observations.read_snapshot(db, 'parent')
            self.assertEqual(len(observed['commands']), 2)
            self.assertNotIn('output', observed['commands'][0])
            self.assertTrue(host_observations.helper_invocation_observed(observed, command, 'primary'))
        for commands in ([],
                         [{'threadId': 'child', 'status': 'completed', 'exitCode': 1, 'input': command}],
                         [{'threadId': 'parent', 'status': 'completed', 'exitCode': 0, 'input': command}],
                         [{'threadId': 'child', 'status': 'completed', 'exitCode': 0, 'input': command + ' --extra'}],
                         [{'threadId': 'child', 'status': 'completed', 'exitCode': 0, 'input': command}] * 2):
            with self.subTest(commands=commands):
                self.assertFalse(host_observations.helper_invocation_observed(
                    {'parent_thread_id': 'parent', 'tool_records': [], 'commands': commands,
                     'subagents': [{'threadId': 'parent', 'id': 'primary', 'childThreadId': 'child'}]},
                    command, 'primary'))

    def test_lost_launch_response_is_resolved_by_exact_title_without_relaunch(self):
        """C-8-09: an uncertain launch is classified from the server's thread list."""
        tools = [{'name': 't3_thread_list', 'inputSchema': {
            'type': 'object', 'properties': {'limit': {'type': 'integer', 'maximum': 100}}}}]

        class Lister:
            def __init__(self, threads, more=False):
                self.threads, self.more, self.calls = threads, more, []

            def call(self, name, arguments):
                self.calls.append(name)
                return {'structuredContent': {'threads': self.threads, 'hasMore': self.more}}

        title = 'Issue 28 S1b codex canary 0123456789abcdef'
        rows = [{'threadId': 'mcp:accepted-1', 'title': title},
                {'threadId': 'mcp:other', 'title': title + ' (copy)'}]
        client = Lister(rows)
        self.assertEqual(driver.find_launched_threads(client, tools, title), ['mcp:accepted-1'])
        self.assertEqual(client.calls, ['t3_thread_list'])
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            driver.find_launched_threads(Lister(rows, more=True), tools, title)
        manifest = {'containers': {'agent': 'agent'}}
        for found, status in ((['mcp:a'], 'accepted-recovered'), ([], 'absent-observed'),
                              (['mcp:a', 'mcp:b'], 'ambiguous')):
            with self.subTest(status=status), \
                    patch.object(benchctl, 'driver', return_value={'thread_ids': found}) as call:
                outcome = benchctl.resolve_uncertain_launch(manifest, title, None)
                self.assertEqual(outcome['status'], status)
                self.assertFalse(outcome['relaunched'])
                self.assertEqual(call.call_args.args[1], ['--find-launch', title])
        with patch.object(benchctl, 'driver', side_effect=RuntimeError('container driver failed (2)')):
            self.assertEqual(benchctl.resolve_uncertain_launch(manifest, title, None)['status'], 'unresolved')

    def test_host_loopback_control_identifies_the_fixture_and_counts_later_connections(self):
        """C-8-06: the negative container probe is paired with a host positive control."""
        import socket
        with socket.socket() as fixture:
            fixture.bind(('127.0.0.1', 0)); fixture.listen(4); fixture.settimeout(0.2)
            port = fixture.getsockname()[1]
            self.assertTrue(benchctl.host_loopback_positive(fixture, port))
            self.assertEqual(benchctl.loopback_connections_after(fixture), 0)
            stray = socket.create_connection(('127.0.0.1', port), timeout=2)
            try:
                self.assertEqual(benchctl.loopback_connections_after(fixture), 1)
            finally:
                stray.close()
        with socket.socket() as closed:
            closed.bind(('127.0.0.1', 0)); closed.settimeout(0.2)
            self.assertFalse(benchctl.host_loopback_positive(closed, closed.getsockname()[1]))

    def test_codex_built_in_provider_is_routed_to_the_gateway(self):
        startup = (CONTAINER / 'start-container.sh').read_text(encoding='utf-8')
        config = startup.split("<<'TOML'\n", 1)[1].split('\nTOML', 1)[0]
        self.assertTrue(config.startswith('openai_base_url = "https://gateway.bench.test:8443/v1"\n'),
                        'Codex 0.162.1 ignores OPENAI_BASE_URL; the top-level key must route it')

    def test_cleanup_requires_the_recorded_immutable_identity_and_run_labels(self):
        run_id = '20261012T031839Z-d91b43'
        expected = {'kind': 'container', 'name': f't3-issue28-agent-{run_id}',
                    'id': 'immutable-container-id', 'run_id': run_id,
                    'labels': {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': run_id}}
        row = {'Id': expected['id'], 'Name': '/' + expected['name'],
               'Config': {'Labels': dict(expected['labels'])}}
        self.assertTrue(benchctl.validate_owned_resource('container', row, expected, run_id))
        adversarial = [
            dict(row, Id='foreign-replacement-id'),
            dict(row, Name='/unrelated-container'),
            {'Id': expected['id'], 'Name': '/' + expected['name'],
             'Config': {'Labels': {'io.t3.issue28.stage': 's1b',
                                   'io.t3.issue28.run': 'different-run'}}},
        ]
        for current in adversarial:
            with self.subTest(current=current):
                self.assertFalse(benchctl.validate_owned_resource(
                    'container', current, expected, run_id))
        corrupt = dict(expected, run_id='different-run')
        self.assertFalse(benchctl.validate_owned_resource('container', row, corrupt, run_id))

    def test_recovered_legacy_resource_needs_creation_output_evidence(self):
        run_id = '20261012T031839Z-d91b43'
        expected = {'kind': 'container', 'name': f't3-issue28-gateway-{run_id}',
                    'id': 'immutable-container-id', 'run_id': run_id,
                    'labels': {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': 'd91b43'},
                    'recovered_creation_output': True, 'creation_evidence_sha256': 'a' * 64}
        row = {'Id': expected['id'], 'Name': '/' + expected['name'],
               'Config': {'Labels': dict(expected['labels'])}}
        self.assertTrue(benchctl.validate_owned_resource('container', row, expected, run_id))
        without_evidence = dict(expected)
        without_evidence.pop('creation_evidence_sha256')
        self.assertFalse(benchctl.validate_owned_resource(
            'container', row, without_evidence, run_id))

    def test_cleanup_never_inspects_or_mutates_unrecorded_resource_names(self):
        # Partial creation records authorize only their recorded objects. A failed
        # create leaves no role entry, so cleanup has no name it may resolve.
        resources = {'image': {'kind': 'image', 'name': 'expected:tag',
                               'id': 'sha256:recorded', 'run_id': 'run',
                               'labels': {'io.t3.issue28.stage': 's1b',
                                          'io.t3.issue28.run': 'run'}}}
        with patch.object(benchctl, 'docker_inspect_json') as inspect, \
                patch.object(benchctl, 'run') as mutate:
            self.assertNotIn('container_agent', resources)
            self.assertNotIn('container_github', resources)
            self.assertNotIn('container_gateway', resources)
            inspect.assert_not_called()
            mutate.assert_not_called()

    def test_cleanup_fake_docker_preserves_swapped_or_foreign_objects(self):
        run_id = '20261012T031839Z-d91b43'
        manifest = {'run_id': run_id, 'image': f't3-issue28-s1b:{run_id}',
                    'networks': [f't3-issue28-private-{run_id}',
                                 f't3-issue28-egress-{run_id}'],
                    'containers': {'agent': f't3-issue28-agent-{run_id}',
                                   'gateway': f't3-issue28-gateway-{run_id}',
                                   'github': f't3-issue28-github-{run_id}'},
                    'created_resources': {'container_agent': {
                        'kind': 'container', 'name': f't3-issue28-agent-{run_id}',
                        'id': 'creation-time-id', 'run_id': run_id,
                        'labels': {'io.t3.issue28.stage': 's1b',
                                   'io.t3.issue28.run': run_id}}}}
        foreign = {'Id': 'replacement-id', 'Name': '/' + manifest['containers']['agent'],
                   'Config': {'Labels': {'io.t3.issue28.stage': 's1b',
                                         'io.t3.issue28.run': run_id}}}
        with tempfile.TemporaryDirectory() as temp:
            results = Path(temp)
            run_dir = results / run_id
            run_dir.mkdir(mode=0o700)
            (run_dir / 'private.log').touch(mode=0o600)
            path = run_dir / 'resource-manifest.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            path.chmod(0o600)
            with patch.object(benchctl, 'RESULTS', results), \
                    patch.object(benchctl, 'docker_inspect_json', return_value=foreign) as inspect, \
                    patch.object(benchctl, 'run') as mutate, \
                    patch.object(benchctl.subprocess, 'run', return_value=fixture_done()), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = benchctl.manage(type('Args', (), {'command': 'down', 'run_id': run_id})())
            self.assertEqual(code, 2)
            inspect.assert_called_once_with('container', 'creation-time-id')
            mutate.assert_not_called()

    def _replace_gateway(self, log_outputs, clock):
        run_id = '20261012T074226Z-68b699'
        recorded = {'id': 'gateway-id', 'kind': 'container', 'run_id': run_id}
        manifest = {'run_id': run_id, 'image': f't3-issue28-s1b:{run_id}',
                    'networks': [f't3-issue28-private-{run_id}', f't3-issue28-egress-{run_id}'],
                    'containers': {'agent': f't3-issue28-agent-{run_id}',
                                   'gateway': f't3-issue28-gateway-{run_id}'},
                    'created_resources': {'container_gateway': recorded}}
        outputs = iter(log_outputs)
        calls = []

        def fake_subprocess(argv, **_kwargs):
            calls.append(argv[:2])
            stdout = next(outputs, log_outputs[-1]) if argv[:2] == ['docker', 'logs'] else ''
            return type('Done', (), {'returncode': 0, 'stdout': stdout, 'stderr': ''})()

        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            log = run_dir / 'private.log'
            log.touch(mode=0o600)
            policy = run_dir / 'config' / 'runtime-targets.json'
            policy.parent.mkdir()
            policy.write_text('{}', encoding='utf-8')
            with patch.object(benchctl, 'docker_inspect_json', return_value={}), \
                    patch.object(benchctl, 'validate_owned_resource', return_value=True), \
                    patch.object(benchctl, 'run', return_value=0), \
                    patch.object(benchctl, 'record_created'), \
                    patch.object(benchctl, 'find_manifest', return_value=run_dir / 'manifest.json'), \
                    patch.object(benchctl.subprocess, 'run', side_effect=fake_subprocess), \
                    patch.object(benchctl.time, 'monotonic', side_effect=clock), \
                    patch.object(benchctl.time, 'sleep'):
                benchctl.configure_gateway(manifest, policy, log)
        return calls

    def test_gateway_replacement_waits_for_delayed_ready_event(self):
        ready = json.dumps({'event': 'ready', 'targets': {'codex': 'fixture-model'}}) + '\n'
        calls = self._replace_gateway(['', '', ready], iter([0, 1, 2, 3, 4]))
        self.assertEqual([call for call in calls if call == ['docker', 'logs']], [['docker', 'logs']] * 3)
        self.assertIn(['docker', 'exec'], calls, 'health check runs only after the ready event')

    def test_gateway_replacement_still_fails_closed_without_ready_event(self):
        with self.assertRaisesRegex(RuntimeError, 'did not load its locked target manifest'):
            self._replace_gateway([''], iter([0, 5, 10, 15, 21, 30]))

    def test_smoke_accepts_only_fresh_provider_homes_and_task_local_npm_cache(self):
        self.assertTrue(smoke.isolated_home_entries_valid(
            ['.agents', '.claude', '.codex', '.config', '.local']))
        self.assertTrue(smoke.isolated_home_entries_valid(
            ['.agents', '.claude', '.codex', '.config', '.local', '.npm']))
        self.assertTrue(smoke.isolated_home_entries_valid(
            ['.agents', '.claude', '.codex', '.config', '.local', '.claude.json']))
        self.assertFalse(smoke.isolated_home_entries_valid(
            ['.agents', '.claude', '.codex', '.config', '.local', '.ssh']))

    def test_smoke_confinement_ignores_unchanged_git_baseline_and_rejects_other_writes(self):
        before = {Path('.git/config'): 'git-hash'}
        assigned = {Path('.git/config'): 'git-hash',
                    Path('smoke/task-1/result.json'): 'result-hash'}
        self.assertTrue(smoke.assigned_workspace_changes_confined(
            before, assigned, Path('smoke/task-1')))
        escaped = dict(assigned)
        escaped[Path('other/result.json')] = 'escaped-hash'
        self.assertFalse(smoke.assigned_workspace_changes_confined(
            before, escaped, Path('smoke/task-1')))
        self.assertFalse(smoke.assigned_workspace_changes_confined(
            before, before, Path('smoke/task-1')))

    def test_gateway_policy_is_fail_closed_and_tls_verification_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime-targets.json'
            path.write_text(json.dumps({'targets': self.targets}), encoding='utf-8')
            self.assertEqual(gateway.read_policy(path)['codex'], 'gpt-6-luna')
        self.assertNotIn('targets', self.policy)
        self.assertIn('ssl.create_default_context()', (CONTAINER / 'gateway.py').read_text())
        self.assertNotIn('CERT_NONE', (CONTAINER / 'gateway.py').read_text())
        with self.assertRaises(ValueError):
            gateway.parse_body(b'{"model":"gpt-6-luna","model":"gpt-6-astra"}')

    def test_credential_values_are_not_printed_by_container_helpers(self):
        files = [CONTAINER / name for name in ('benchctl.py', 'driver.py', 'start-container.sh')]
        for file in files:
            text = file.read_text(encoding='utf-8')
            self.assertNotIn('printenv', text)
            self.assertNotIn('set -x', text)

    def test_transcript_audit_emits_exact_model_ids_and_flags_a_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            claude = root / 'claude'
            codex = root / 'codex'
            claude.mkdir()
            codex.mkdir()
            (claude / 'session.jsonl').write_text(
                json.dumps({'type': 'assistant', 'message': {'model': 'claude-haiku-5-5'}}) + '\n',
                encoding='utf-8')
            (codex / 'rollout.jsonl').write_text(
                json.dumps({'type': 'turn_context', 'payload': {'model': 'gpt-6-luna'}}) + '\n'
                + json.dumps({'type': 'response_item', 'payload': {'type': 'message'}}) + '\n',
                encoding='utf-8')
            (codex / 'unknown-source.jsonl').write_text(
                json.dumps({'type': 'response_item', 'payload': {'type': 'message'}}) + '\n',
                encoding='utf-8')
            targets = {'claudeAgent': {'model': 'claude-haiku-5-5'}, 'codex': {'model': 'gpt-6-luna'}}
            roots = {'claudeAgent': claude, 'codex': codex}
            result = audit_models.audit(roots, targets)
            self.assertFalse(result['codex']['verified'])
            self.assertGreater(result['codex']['unknown_records'], 0)
            self.assertIn('unknown model attribution', ' '.join(result['codex']['reasons']))
            (codex / 'unknown-source.jsonl').unlink()
            result = audit_models.audit(roots, targets)
            self.assertTrue(result['claudeAgent']['verified'])
            self.assertTrue(result['codex']['verified'])
            (codex / 'rollout.jsonl').write_text(
                json.dumps({'type': 'turn_context', 'payload': {'model': 'gpt-6-luna'}}) + '\n'
                + json.dumps({'type': 'response_item', 'payload': {'type': 'message'}}) + '\n',
                encoding='utf-8')
            result = audit_models.audit(roots, targets)
            self.assertTrue(all(item['verified'] for item in result.values()))
            (codex / 'other.jsonl').write_text(
                json.dumps({'type': 'turn_context', 'payload': {'model': 'gpt-6-astra'}}) + '\n'
                + json.dumps({'type': 'response_item', 'payload': {'type': 'message'}}) + '\n',
                encoding='utf-8')
            mismatch = audit_models.audit({'codex': codex}, targets)['codex']
            self.assertFalse(mismatch['verified'])
            self.assertEqual(mismatch['actual_ids'], ['gpt-6-astra', 'gpt-6-luna'])
            (codex / 'native.jsonl').write_text(
                json.dumps({'type': 'response_item', 'payload': {'type': 'message'}}) + '\n'
                + '{malformed\n', encoding='utf-8')
            native = audit_models.audit({'codex': codex}, targets)['codex']
            self.assertFalse(native['verified'])
            self.assertGreater(native['unknown_records'], 0)
            self.assertGreater(native['malformed_records'], 0)
            self.assertIn('native.jsonl', {item['source'] for item in native['sources']})

    def test_launch_schema_missing_target_or_options_fails_before_dispatch(self):
        class NoCall:
            calls = 0

            def call(self, *_args):
                self.calls += 1

        supplied = {'projectId': 'p', 'title': 't', 'message': 'm',
                    'modelSelection': {'instanceId': 'codex', 'model': 'gpt-6-luna',
                                       'options': {'reasoningEffort': 'low'}},
                    'runtimeMode': 'auto', 'interactionMode': 'default',
                    'workspaceStrategy': {'type': 'root'}}
        base = {'type': 'object', 'properties': {
            key: {} for key in supplied}}
        for nested in ({'instanceId': {}, 'model': {}},
                       {'instanceId': {}, 'options': {}},
                       {'instanceId': {}, 'model': {}, 'options': {}}):
            schema = json.loads(json.dumps(base))
            schema['properties']['modelSelection'] = {
                'type': 'object', 'properties': nested}
            client = NoCall()
            if 'model' not in nested or 'options' not in nested:
                with self.assertRaises(RuntimeError):
                    driver.dispatch_with_schema(client, 't3_thread_launch', schema, supplied)
                self.assertEqual(client.calls, 0)
            else:
                driver.dispatch_with_schema(client, 't3_thread_launch', schema, supplied)
                self.assertEqual(client.calls, 1)
        for omitted in ('modelSelection', 'runtimeMode', 'workspaceStrategy'):
            schema = json.loads(json.dumps(base))
            schema['properties'].pop(omitted)
            client = NoCall()
            with self.subTest(omitted=omitted), self.assertRaises(RuntimeError):
                driver.dispatch_with_schema(client, 't3_thread_launch', schema, supplied)
            self.assertEqual(client.calls, 0)

    def test_host_thread_ids_are_opaque_and_artifacts_are_hashed(self):
        values = ['thread:opaque:abc', 'host/path/id', 'encoded%2Fopaque',
                  'urn:t3:thread/opaque']
        with tempfile.TemporaryDirectory() as temp:
            paths = [driver.thread_artifact_path(temp, value) for value in values]
            self.assertTrue(all(driver.opaque_thread_id(value) for value in values))
            self.assertTrue(all(path.parent == Path(temp) and path.name.endswith(
                '.thread-read.json') for path in paths))
            self.assertEqual(len({path.name for path in paths}), len(values))
            for value in values:
                self.assertNotIn(value, driver.thread_artifact_path(temp, value).name)
        for invalid in ('', 'thread\nforged', 'x' * 4097):
            self.assertFalse(driver.opaque_thread_id(invalid))

    def test_accepted_launch_identity_survives_wait_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.json'
            manifest = {'canary_attempts': [{'provider': 'claudeAgent',
                         'launch': {'status': 'accepted', 'thread_id': 'thread:opaque/1'}}]}
            path.write_text(json.dumps(manifest), encoding='utf-8')
            try:
                raise RuntimeError('wait transport failed')
            except RuntimeError as exc:
                manifest['canary_attempts'][0].update({
                    'phase': 'wait-error', 'wait_error_route': str(exc),
                    'recovery': 'accepted thread identity retained; rerun wait with recorded ID'})
                path.write_text(json.dumps(manifest), encoding='utf-8')
            recovered = json.loads(path.read_text(encoding='utf-8'))['canary_attempts'][0]
            self.assertEqual(recovered['launch']['thread_id'], 'thread:opaque/1')
            self.assertEqual(recovered['phase'], 'wait-error')

    def test_gateway_rejection_is_recorded_separately_from_driver_launch_error(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'gateway.log'
            log.write_text(json.dumps({'event': 'rejected', 'reason': 'forbidden model'}) + '\n',
                           encoding='utf-8')
            with patch.object(benchctl.subprocess, 'run', return_value=type(
                    'Result', (), {'returncode': 0, 'stdout': log.read_text(encoding='utf-8')})()):
                gateway_before = 0
                gateway_after = benchctl.gateway_rejection_count('ignored', log)
            canary = {'phase': 'launch-error',
                      'launch': {'status': 'error', 'thread_id': None,
                                 'error_route': 'T3 driver command failed (exit 2)',
                                 'gateway_rejections_after': gateway_after,
                                 'gateway_rejection_delta': gateway_after - gateway_before}}
            self.assertEqual(canary['launch']['error_route'],
                             'T3 driver command failed (exit 2)')
            self.assertEqual(canary['launch']['gateway_rejection_delta'], 1)

    def test_summary_boundary_audit_reads_real_task_status_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, outputs = root / 'input', root / 'output'
            inputs.mkdir()
            outputs.mkdir()
            results = {}
            ids = {}
            for size in (32767, 32768, 32769):
                payload = b'x' * size
                (inputs / f'summary-{size}.txt').write_bytes(payload)
                task_id = f'task-{size}'
                ids[str(size)] = task_id
                results[task_id] = {'summary': payload.decode(), 'status': 'completed',
                                   'workState': 'result_available', 'hasPendingChildRuns': False}
            tools = [{'name': 'task_status', 'inputSchema': {
                'type': 'object', 'properties': {'taskId': {'type': 'string'}},
                'required': ['taskId']}}]
            client = FakeTaskClient(results)
            audit = driver.verify_summary_boundary_tasks(
                client, tools, {'summary_boundary_task_ids': ids}, inputs, outputs)
            self.assertTrue(audit['verified'])
            self.assertEqual({row['actual_utf8_bytes'] for row in audit['records']},
                             {32767, 32768, 32769})
            results['task-32768']['summary'] = 'truncated'
            failed = driver.verify_summary_boundary_tasks(
                FakeTaskClient(results), tools, {'summary_boundary_task_ids': ids}, inputs, outputs)
            self.assertFalse(failed['verified'])

    def _followup_records(self, after_summary='original task summary', followup_child='child-thread',
                          include_before=True):
        target = {'providerInstanceId': 'codex', 'model': 'fixture-luna'}
        def status(task_id, summary, child):
            return {'toolName': 't3-code.task_status', 'input': {'taskId': task_id},
                    'output': {'taskId': task_id, 'summary': summary, 'status': 'completed',
                               'workState': 'result_available', 'hasPendingChildRuns': False,
                               'childThreadId': child, **target}}
        records = [{'toolName': 't3-code.delegate_task', 'input': {'target': target},
                    'output': {'taskId': 'task-original'}}]
        if include_before:
            records.append(status('task-original', 'original task summary', 'child-thread'))
        records += [{'toolName': 't3-code.delegate_task',
                     'input': {'target': target, 'childThreadId': 'child-thread'},
                     'output': {'taskId': 'task-followup'}},
                    status('task-original', after_summary, 'child-thread'),
                    status('task-followup', 'follow-up result', followup_child)]
        return host_observations.CapturedTaskClient({'tool_records': records})

    def test_tracked_followup_requires_host_observed_pre_post_pair_and_same_child(self):
        tools = [{'name': 'task_status', 'inputSchema': {
            'type': 'object', 'properties': {'taskId': {'type': 'string'}}, 'required': ['taskId']}}]
        # Worker-asserted hashes and "unchanged" flags are ignored; only host records count.
        report = {'tracked_followup': {'status': 'supported', 'original_task_id': 'task-original',
                                       'new_task_id': 'task-followup', 'original_unchanged': True,
                                       'original_summary_sha256_before_followup': '0' * 64}}
        with tempfile.TemporaryDirectory() as temp:
            audit = driver.verify_tracked_followup(self._followup_records(), tools, report, Path(temp))
            self.assertTrue(audit['verified'], audit)
            self.assertEqual(audit['original_summary_sha256'],
                             hashlib.sha256(b'original task summary').hexdigest())
            for client in (self._followup_records(after_summary='rewritten original'),
                           self._followup_records(followup_child='different-child')):
                self.assertFalse(driver.verify_tracked_followup(client, tools, report, Path(temp))['verified'])
            missing = driver.verify_tracked_followup(self._followup_records(include_before=False),
                                                     tools, report, Path(temp))
            self.assertFalse(missing['recorded'])
            self.assertFalse(driver.verify_tracked_followup(FakeTaskClient({}), tools, report,
                                                            Path(temp))['recorded'])

    def test_project_preflight_requires_one_project_at_the_isolated_workspace(self):
        class ProjectClient:
            def __init__(self, projects):
                self.projects = projects

            def call(self, _name, _arguments):
                return {'structuredContent': {'projects': self.projects}}

        tools = [{'name': 't3_project_list', 'inputSchema': {
            'type': 'object', 'properties': {'limit': {'type': 'number'}}}}]
        client = ProjectClient([{'id': 'isolated-project', 'workspaceRoot': '/bench/ws'}])
        project_id, created = driver.ensure_single_workspace_project(client, tools)
        self.assertEqual(project_id, 'isolated-project')
        self.assertFalse(created)
        for projects in ([{'id': 'wrong', 'workspaceRoot': '/bench/other'}],
                         [{'id': 'one', 'workspaceRoot': '/bench/ws'},
                          {'id': 'two', 'workspaceRoot': '/bench/ws'}],
                         [{'id': 'missing-path'}]):
            with self.subTest(projects=projects), self.assertRaises(RuntimeError):
                driver.ensure_single_workspace_project(ProjectClient(projects), tools)


class StreamingUpstream(FakeUpstream):
    """An SSE provider reply larger than the gateway's bound."""

    def getresponse(self):
        class Reply:
            status, reason = 200, 'OK'

            def getheaders(self):
                return [('Content-Type', 'text/event-stream')]

            def read1(self, _size):
                return b'data: {"type":"ping"}\n\n'
        return Reply()


def gateway_events(output):
    return [json.loads(line) for line in output.splitlines() if line.startswith('{')]


def launch_row(program, nonce='0' * 32):
    return {'program': program, 'pid': 7, 'parent_uid': 0, 'worker_uid': 1001,
            'nonce': nonce, 'argv_sha256': 'a' * 64}


class Pass10ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 10 repairs of review 9 container findings."""

    # Reuse the gateway fixture state without re-running its inherited tests.
    setUp = GatewayFixture.setUp
    tearDown = GatewayFixture.tearDown

    def post(self, path, body, headers=None, upstream=FakeUpstream):
        import contextlib
        gateway.LOCKED = False
        FakeUpstream.calls = []
        handler = FakeHandler(path, body)
        for name, value in (headers or {}).items():
            handler.headers[name] = value
        log = io.StringIO()
        with patch.object(gateway.http.client, 'HTTPSConnection', upstream), \
                contextlib.redirect_stdout(log):
            handler.do_POST()
        return handler.status, gateway_events(log.getvalue()), log.getvalue()

    def test_r9_co_01_unknown_top_level_fields_are_rejected_and_logged_by_name_only(self):
        claude = {'model': 'claude-haiku-5-5', 'output_config': {'effort': 'low'}}
        codex = {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}}
        cases = (('/v1/messages', dict(claude, fast_mode=True), 'fast_mode'),
                 ('/v1/messages', dict(claude, mcp_servers=[]), 'mcp_servers'),
                 ('/v1/messages', dict(claude, container='secret-container-value'), 'container'),
                 ('/v1/messages/count_tokens', dict(claude, max_tokens=5), 'max_tokens'),
                 ('/v1/responses', dict(codex, background=True), 'background'),
                 ('/v1/responses', dict(codex, x_priority_lane='secret-lane-value'), 'x_priority_lane'))
        for path, body, field in cases:
            with self.subTest(path=path, field=field):
                status, events, raw = self.post(path, body)
                self.assertEqual(status, 403)
                self.assertEqual(FakeUpstream.calls, [])
                self.assertTrue(gateway.LOCKED)
                self.assertEqual(events[-1]['event'], 'rejected')
                self.assertEqual(events[-1]['fields'], [field])
                self.assertNotIn('secret-', raw)
        status, events, _ = self.post('/v1/messages', dict(claude, speed='fast'))
        self.assertEqual((status, events[-1]['reason'], events[-1]['fields']),
                         (403, 'premium-priced request control is not allowed', ['speed']))
        status, events, _ = self.post('/v1/responses', codex, {'openai-beta': 'responses=v1, priority-x'})
        self.assertEqual((status, events[-1]['fields']), (403, ['openai-beta']))
        self.assertEqual(FakeUpstream.calls, [])

    def test_r9_co_01_normal_cli_request_shapes_are_still_forwarded(self):
        claude = {'model': 'claude-haiku-5-5', 'messages': [], 'system': [], 'tools': [],
                  'tool_choice': {'type': 'auto'}, 'metadata': {'user_id': 'synthetic'},
                  'max_tokens': 1024, 'temperature': 1, 'stream': True,
                  'context_management': {'edits': []}, 'output_config': {'effort': 'low'}}
        status, events, _ = self.post('/v1/messages?beta=true', claude,
                                      {'anthropic-beta': 'claude-code-20250219'})
        self.assertEqual(status, 200)
        self.assertEqual(events[0]['body_fields'], sorted(claude))
        codex = {'model': 'gpt-6-luna', 'instructions': 'x', 'input': [], 'tools': [],
                 'tool_choice': 'auto', 'parallel_tool_calls': False,
                 'reasoning': {'effort': 'low', 'summary': 'auto'}, 'store': False, 'stream': True,
                 'include': ['reasoning.encrypted_content'], 'prompt_cache_key': 'synthetic',
                 'text': {'verbosity': 'low'}, 'service_tier': 'default'}
        status, _, _ = self.post('/v1/responses', codex)
        self.assertEqual(status, 200)
        status, _, _ = self.post('/v1/messages/count_tokens',
                                 {'model': 'claude-haiku-5-5', 'messages': [], 'system': [],
                                  'tools': [], 'output_config': {'effort': 'low'}})
        self.assertEqual(status, 200)

    def test_r9_co_01_allowlist_admits_field_names_captured_from_pinned_clis(self):
        # Field names only, captured 13 October 2026 from Claude Code 2.1.296 and
        # Codex 0.162.1 inside the bench image with no network and a refusing listener.
        captured = {
            '/v1/messages?beta=true': ['context_management', 'max_tokens', 'messages', 'metadata',
                                       'model', 'stream', 'system', 'thinking', 'tools'],
            '/v1/responses': ['client_metadata', 'include', 'input', 'model', 'parallel_tool_calls',
                              'prompt_cache_key', 'reasoning', 'store', 'stream', 'text',
                              'tool_choice'],
        }
        # Claude Code sends a list of client tools with no `type` (pass 11 tool guard).
        samples = {'model': None, 'thinking': {'type': 'disabled'}, 'reasoning': {'effort': 'low'},
                   'stream': True, 'store': False, 'max_tokens': 1024,
                   'tools': [{'name': 'Bash', 'description': 'x', 'input_schema': {'type': 'object'}}]}
        # The live Haiku canary target is claude-haiku-4-5 with only a thinking boolean.
        gateway.TARGETS = {**gateway.TARGETS, 'claudeAgent': 'claude-haiku-4-5'}
        gateway.TARGET_OPTIONS = {**gateway.TARGET_OPTIONS, 'claudeAgent': {'thinking': False}}
        for path, fields in captured.items():
            body = {field: samples.get(field, {}) for field in fields}
            body['model'] = 'claude-haiku-4-5' if path.startswith('/v1/messages') else 'gpt-6-luna'
            status, events, _ = self.post(path, body, {'anthropic-beta': 'claude-code-20250219'}
                                          if path.startswith('/v1/messages') else None)
            self.assertEqual(status, 200, path)
            self.assertEqual(events[0]['body_fields'], fields)

    def test_r9_co_07_oversize_upstream_stream_is_classified_as_upstream_failure(self):
        with patch.object(gateway, 'MAX_REPLY', 64):
            status, events, _ = self.post('/v1/responses', {'model': 'gpt-6-luna',
                                                            'reasoning': {'effort': 'low'}},
                                          upstream=StreamingUpstream)
        failed = [event for event in events if event['event'] == 'forward-failed']
        self.assertEqual(status, 200)  # headers were already relayed when the bound tripped
        self.assertEqual([event['failure_kind'] for event in failed], ['upstream-failure'])
        self.assertIsInstance(gateway.OversizeReply('x'), ValueError)

    def test_r9_co_10_provider_non_2xx_still_locks_the_finite_canary(self):
        class Throttled(FakeUpstream):
            def getresponse(self):
                return type('Reply', (FakeResponse,), {'status': 429, 'reason': 'Too Many Requests'})()
        body = {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}}
        status, _, _ = self.post('/v1/responses', body, upstream=Throttled)
        self.assertEqual(status, 429)
        self.assertTrue(gateway.LOCKED)
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream), \
                patch('sys.stdout', io.StringIO()):
            later, _ = request(None, '/v1/responses', body)
        self.assertEqual(later, 403)
        self.assertIn('transient 429', (CONTAINER / 'README.md').read_text(encoding='utf-8'))

    def test_r9_co_06_smoke_zero_request_check_counts_token_estimation(self):
        events = '\n'.join(json.dumps(event) for event in (
            {'event': 'ready'},
            {'event': 'forward-started', 'request_id': 'r1', 'request_kind': 'token-estimation'},
            {'event': 'forwarded', 'request_id': 'r1', 'request_kind': 'token-estimation'}))
        with tempfile.TemporaryDirectory() as temp, patch.object(
                benchctl.subprocess, 'run', return_value=type('Result', (), {'returncode': 0, 'stdout': events})()):
            self.assertEqual(benchctl.gateway_forward_count('gateway', Path(temp) / 'log'), 1)

    def test_r9_co_03_network_negatives_require_same_run_positive_controls(self):
        def resolve(_name):
            return '172.17.0.1'

        def gateway_only(host, _port):
            return host == 'gateway.bench.test'
        good = smoke.network_controls(4321, reaches=gateway_only, resolve=resolve)
        self.assertTrue(all(ok for _name, ok, _detail in good))
        # Unroutable everything used to pass every negative vacuously.
        dead = dict((name, ok) for name, ok, _ in smoke.network_controls(
            4321, reaches=lambda *_: False, resolve=resolve))
        self.assertFalse(dead['gateway-reachable-positive-control'])

        def unresolved(_name):
            raise OSError('no such host')
        for resolver in (unresolved, lambda _name: '127.0.0.1', lambda _name: 'not-an-ip'):
            rows = dict((name, ok) for name, ok, _ in smoke.network_controls(
                4321, reaches=gateway_only, resolve=resolver))
            self.assertFalse(rows['host-gateway-resolves-positive-control'])
            self.assertFalse(rows['host-loopback-excluded'])
        printed = '\n'.join(json.dumps({'probe': name, 'passed': ok}) for name, ok, _ in good)
        printed += '\n' + json.dumps({'probe': 'gateway-tls', 'passed': True})
        self.assertTrue(benchctl.smoke_probe_results(printed)['paired_controls_passed'])
        negatives_only = '\n'.join(line for line in printed.splitlines() if 'positive-control' not in line)
        self.assertFalse(benchctl.smoke_probe_results(negatives_only)['paired_controls_passed'])
        repeated = printed + '\n' + json.dumps({'probe': 'host-loopback-excluded', 'passed': True})
        self.assertFalse(benchctl.smoke_probe_results(repeated)['paired_controls_passed'])

    def test_r9_co_03_smoke_command_fails_when_exit_zero_lacks_positive_controls(self):
        run_id = '20261013T010203Z-abcdef'
        printed = '\n'.join(json.dumps({'probe': name, 'passed': True}) for name in
                            ('gateway-tls', 'no-direct-provider-egress', 'host-loopback-excluded'))

        def fake(argv, **_kwargs):
            stdout = printed if argv[:2] == ['docker', 'exec'] else ''
            return type('Done', (), {'returncode': 0, 'stdout': stdout})()
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / run_id
            run_dir.mkdir(mode=0o700)
            Path(temp).chmod(0o700)
            (run_dir / 'private.log').touch(mode=0o600)
            manifest = {'run_id': run_id, 'containers': {'agent': 'agent', 'gateway': 'gateway'}}
            (run_dir / 'resource-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(benchctl, 'RESULTS', Path(temp)), \
                    patch.object(benchctl.subprocess, 'run', side_effect=fake), \
                    patch('sys.stdout', io.StringIO()):
                code = benchctl.manage(type('Args', (), {'command': 'smoke', 'run_id': run_id})())
            saved = json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 2)
        self.assertFalse(saved['smoke_passed'])
        self.assertFalse(saved['smoke_network_controls']['paired_controls_passed'])

    def test_r9_co_04_app_child_projected_selection_must_match_frozen_target(self):
        target = {'providerInstanceId': 'codex', 'model': 'gpt-6-luna',
                  'options': {'reasoningEffort': 'low', 'serviceTier': 'default'}}

        def selection(effort):
            return {'instanceId': 'codex', 'model': 'gpt-6-luna', 'options': [
                {'id': 'reasoningEffort', 'value': effort}, {'id': 'serviceTier', 'value': 'default'}]}

        def observation(thread_effort='low', run_effort='low', child='child1'):
            return {'parent_thread_id': 'parent', 'runtime_requests': [],
                    'subagents': [{'threadId': 'parent', 'id': 'task1', 'childThreadId': child}],
                    'threads': [{'id': 'child1', 'modelSelection': selection(thread_effort)}],
                    'runs': [{'threadId': 'child1', 'status': 'completed',
                              'modelSelection': selection(run_effort)}],
                    'tool_records': [
                        {'toolName': 't3-code.delegate_task', 'input': {'target': target},
                         'output': {'taskId': 'task1'}},
                        {'toolName': 't3-code.task_status', 'input': {'taskId': 'task1'},
                         'output': {'taskId': 'task1', 'status': 'completed',
                                    'workState': 'result_available', 'hasPendingChildRuns': False,
                                    'providerInstanceId': 'codex', 'model': 'gpt-6-luna'}}]}
        self.assertTrue(host_observations.verify_owned_tasks(observation(), ['task1'], target)['verified'])
        drifts = {'thread options': observation(thread_effort='high'),
                  'run options': observation(run_effort='high'),
                  'unprojected child': observation(child='unprojected-child'),
                  'no child thread': observation(child=None)}
        for name, drift in drifts.items():
            with self.subTest(name=name):
                result = host_observations.verify_owned_tasks(drift, ['task1'], target)
                self.assertTrue(result['checks']['exact_targets'], 'delegate input alone still matches')
                self.assertFalse(result['checks']['projected_child_selection'])
                self.assertFalse(result['verified'])

    def test_r9_co_02_native_launch_log_requires_worker_shim_launches_for_provider(self):
        version = launch_row('claude', '1' * 32)
        launched = launch_row('claude', '2' * 32)
        data = '\n'.join(json.dumps(row) for row in (version, launched)).encode() + b'\n'
        rows = benchctl.parse_native_launches(data)
        self.assertTrue(benchctl.native_launch_evidence([version], rows, 'claudeAgent')['verified'])
        self.assertFalse(benchctl.native_launch_evidence([version], rows, 'codex')['verified'])
        self.assertFalse(benchctl.native_launch_evidence(rows, rows, 'claudeAgent')['verified'])
        self.assertFalse(benchctl.native_launch_evidence([launch_row('codex')], rows, 'claudeAgent')['verified'])
        for bad in (dict(launched, worker_uid=0), dict(launched, parent_uid=1001),
                    dict(launched, extra=True), dict(launched, nonce=int('1' * 32)),
                    dict(launched, program='claude-native')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                benchctl.parse_native_launches(json.dumps(bad).encode())
        with self.assertRaises(ValueError):
            benchctl.parse_native_launches(b'{"program":"claude","program":"codex"}')

        def exited(code, stdout=b''):
            return patch.object(benchctl.subprocess, 'run', return_value=type(
                'Done', (), {'returncode': code, 'stdout': stdout})())
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'log'
            with exited(3):
                self.assertEqual(benchctl.read_native_launches('agent-id', log, allow_missing=True), [])
                with self.assertRaisesRegex(RuntimeError, 'missing or unreadable'):
                    benchctl.read_native_launches('agent-id', log)
            with exited(1):
                audit = benchctl.canary_native_launch_audit('agent-id', [version], 'claudeAgent', log)
            self.assertFalse(audit['verified'])
            with exited(0, data):
                audit = benchctl.canary_native_launch_audit('agent-id', [version], 'claudeAgent', log)
            self.assertTrue(audit['verified'])
            self.assertEqual(audit['shim_launches'], 1)

    def test_r9_co_02_t3_provider_commands_must_resolve_to_the_shim(self):
        import native_exec
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shim = root / 'opt' / 'native_exec.py'
            shim.parent.mkdir()
            shim.write_text('#!/bin/sh\n')
            shim.chmod(0o755)
            bin_dir, native_dir = root / 'bin', root / 'native'
            bin_dir.mkdir()
            native_dir.mkdir()
            for program in ('claude', 'codex'):
                (bin_dir / program).symlink_to(shim)
                real = native_dir / program
                real.write_text('#!/bin/sh\n')
                real.chmod(0o755)
            with patch.object(native_exec, 'SHIM', os.path.realpath(shim)):
                report = native_exec.binary_resolution_report
                self.assertTrue(report(None, str(bin_dir), temp)['verified'])
                configured = json.dumps({'providerInstances': {'claudeAgent': {
                    'config': {'binaryPath': str(bin_dir / 'claude')}}}})
                self.assertTrue(report(configured, str(bin_dir), temp)['verified'])
                cases = {
                    'native first on PATH': (None, f'{native_dir}:{bin_dir}'),
                    'direct native binary': (json.dumps({'providers': {'codex': {
                        'binaryPath': str(native_dir / 'codex')}}}), str(bin_dir)),
                    'shim under another name': (json.dumps({'x': [{'binaryPath': str(shim)}]}),
                                                str(bin_dir)),
                    'non-string path': (json.dumps({'binaryPath': 7}), str(bin_dir)),
                    'malformed settings': ('{', str(bin_dir)),
                    'missing command': (None, str(native_dir / 'empty')),
                }
                for name, (settings, search) in cases.items():
                    with self.subTest(name=name):
                        self.assertFalse(report(settings, search, temp)['verified'])

    def test_r9_co_02_canary_is_blocked_before_slot_use_without_shim_resolution(self):
        run_id = '20261013T010203Z-abcdef'
        manifest = {'run_id': run_id, 'smoke_passed': True, 'canary_attempts': [],
                    'observer_boundary_preflight': {'status': 'passed',
                                                    'literal_provider_network_verified': True,
                                                    'native_binary_resolution': {'verified': False}}}
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / run_id
            run_dir.mkdir(mode=0o700)
            Path(temp).chmod(0o700)
            path = run_dir / 'resource-manifest.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(benchctl, 'RESULTS', Path(temp)), \
                    patch.object(benchctl.subprocess, 'run') as docker:
                with self.assertRaisesRegex(RuntimeError, 'resolve to the worker shim'):
                    benchctl.manage(type('Args', (), {'command': 'canary', 'run_id': run_id,
                                                      'provider': 'codex'})())
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['canary_attempts'], [])
            docker.assert_not_called()

    def test_r9_co_05_refused_continuation_never_counts_as_a_pass(self):
        self.assertFalse(benchctl.tracked_followup_accepted(
            {'recorded': True, 'policy_blocked': True, 'supported': False, 'verified': False}))
        self.assertFalse(benchctl.tracked_followup_accepted(
            {'recorded': True, 'policy_blocked': True, 'supported': True, 'verified': False}))
        self.assertTrue(benchctl.tracked_followup_accepted(
            {'recorded': True, 'supported': True, 'verified': True}))
        status = {'toolName': 't3-code.task_status', 'input': {'taskId': 'task-original'},
                  'output': {'taskId': 'task-original', 'summary': 'same', 'status': 'completed',
                             'workState': 'result_available', 'hasPendingChildRuns': False}}
        client = host_observations.CapturedTaskClient({'tool_records': [status, status]})
        report = {'tracked_followup': {'status': 'not_allowed', 'original_task_id': 'task-original',
                                       'new_task_id': None}}
        audit = driver.verify_tracked_followup(client, [], report, Path('/nonexistent'))
        self.assertTrue(audit['original_unchanged_host_observed'])
        self.assertFalse(audit['counts_as_pass'])
        self.assertFalse(benchctl.tracked_followup_accepted(audit))
        self.assertIn('never counts as a pass', (CONTAINER / 'README.md').read_text(encoding='utf-8'))

    def test_r9_co_09_canary_summary_rejects_duplicate_keys_and_non_finite_numbers(self):
        self.assertEqual(driver.parse_canary_result('{"input_sha256":"a","n":1.5}'),
                         {'input_sha256': 'a', 'n': 1.5})
        for text in ('{"input_sha256":"a","input_sha256":"b"}', '{"n":NaN}', '{"n":Infinity}',
                     '{"n":-Infinity}', '{"t":{"k":1,"k":2}}', '[1]', 'not json', None,
                     '[' * 100000):
            with self.subTest(text=(text or '')[:40]):
                self.assertIsNone(driver.parse_canary_result(text))

    def test_r9_co_08_unrecorded_replacement_gateway_is_removed_by_labels_and_name(self):
        run_id = '20261012T074226Z-68b699'
        name = f't3-issue28-gateway-{run_id}'
        recorded = {'id': 'bootstrap-id', 'kind': 'container', 'run_id': run_id}
        manifest = {'run_id': run_id, 'image': f't3-issue28-s1b:{run_id}',
                    'networks': [f't3-issue28-private-{run_id}', f't3-issue28-egress-{run_id}'],
                    'containers': {'agent': f't3-issue28-agent-{run_id}', 'gateway': name},
                    'created_resources': {'container_gateway': recorded}}
        listed, mutations = [], []

        def fake_subprocess(argv, **_kwargs):
            if argv[:2] == ['docker', 'ps']:
                listed.append(argv)
                return type('Done', (), {'returncode': 0, 'stdout': 'replacement-id\n'})()
            return type('Done', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()

        def fake_run(argv, _logs, check=True):
            mutations.append(argv)
            return 0
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            log = run_dir / 'private.log'
            log.touch(mode=0o600)
            policy = run_dir / 'config' / 'runtime-targets.json'
            policy.parent.mkdir()
            policy.write_text('{}', encoding='utf-8')
            mpath = run_dir / 'manifest.json'
            with patch.object(benchctl, 'docker_inspect_json', return_value={}), \
                    patch.object(benchctl, 'validate_owned_resource', return_value=True), \
                    patch.object(benchctl, 'run', side_effect=fake_run), \
                    patch.object(benchctl, 'record_created',
                                 side_effect=RuntimeError('inspect failed')) as record, \
                    patch.object(benchctl, 'find_manifest', return_value=mpath), \
                    patch.object(benchctl.subprocess, 'run', side_effect=fake_subprocess), \
                    patch.object(benchctl.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'labelled container removed'):
                    benchctl.configure_gateway(manifest, policy, log)
            saved = json.loads(mpath.read_text(encoding='utf-8'))
        self.assertEqual(record.call_count, 3)
        self.assertEqual(len(listed), 1)
        self.assertIn('label=io.t3.issue28.stage=s1b', listed[0])
        self.assertIn(f'label=io.t3.issue28.run={run_id}', listed[0])
        self.assertTrue(any(item.startswith('name=^/') and item.endswith('$') for item in listed[0]))
        self.assertIn(['docker', 'rm', '--force', 'replacement-id'], mutations)
        self.assertFalse(any(argv[:3] == ['docker', 'network', 'connect'] for argv in mutations))
        self.assertNotIn('container_gateway', saved['created_resources'])
        self.assertEqual(saved['retired_resources'], [recorded])
        self.assertEqual(saved['gateway_replacement_unrecorded']['removed'], 1)


NATIVE_TARGET = {'providerInstanceId': 'codex', 'model': 'gpt-6-luna',
                 'options': {'reasoningEffort': 'low', 'serviceTier': 'default'}}


def projected_selection(effort='low'):
    return {'instanceId': 'codex', 'model': 'gpt-6-luna', 'options': [
        {'id': 'reasoningEffort', 'value': effort}, {'id': 'serviceTier', 'value': 'default'}]}


class Pass11ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 11 repairs of review 10 container findings."""

    setUp = GatewayFixture.setUp
    tearDown = GatewayFixture.tearDown
    post = Pass10ContainerRepairTest.post

    def test_r10_co_01_server_side_tools_are_rejected_before_upstream(self):
        claude = {'model': 'claude-haiku-5-5', 'output_config': {'effort': 'low'}}
        codex = {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}}
        anthropic_tools = (
            ({'type': 'web_search_20250305', 'name': 'web_search'}, 'web_search_20250305'),
            ({'type': 'web_fetch_20250910', 'name': 'web_fetch'}, 'web_fetch_20250910'),
            ({'type': 'code_execution_20250825', 'name': 'code_execution'}, 'code_execution_20250825'),
            ({'type': 'computer_20250124', 'name': 'computer'}, 'computer_20250124'),
            ({'type': 'tool_search_tool_regex_20251119', 'name': 'tool_search'},
             'tool_search_tool_regex_20251119'),
            ({'type': 'mcp_toolset', 'mcp_server_name': 'secret-mcp-name'}, 'mcp_toolset'),
            ({'type': None, 'name': 'Bash'}, '<non-string>'),
            ('secret-tool-string', '<non-object>'))
        openai_tools = (
            ({'type': 'web_search'}, 'web_search'),
            ({'type': 'web_search_preview'}, 'web_search_preview'),
            ({'type': 'image_generation', 'model': 'secret-image-model'}, 'image_generation'),
            ({'type': 'computer_use_preview', 'display_width': 1}, 'computer_use_preview'),
            ({'type': 'code_interpreter', 'container': {'type': 'auto'}}, 'code_interpreter'),
            ({'type': 'file_search', 'vector_store_ids': ['secret-store']}, 'file_search'),
            ({'type': 'mcp', 'server_url': 'https://secret-mcp.example'}, 'mcp'),
            ({'type': 'tool_search'}, 'tool_search'),
            ({'type': 'unknown_future_tool'}, 'unknown_future_tool'),
            ({'name': 'untyped'}, '<missing>'))
        cases = ([('/v1/messages?beta=true', claude, tool, name) for tool, name in anthropic_tools]
                 + [('/v1/messages/count_tokens', claude, tool, name) for tool, name in anthropic_tools[:2]]
                 + [('/v1/responses', codex, tool, name) for tool, name in openai_tools])
        for path, base, tool, name in cases:
            with self.subTest(path=path, tool=name):
                client = {'name': 'Read', 'input_schema': {'type': 'object'}} if path.startswith(
                    '/v1/messages') else {'type': 'function', 'name': 'shell', 'parameters': {}}
                status, events, raw = self.post(path, dict(base, tools=[client, tool]))
                self.assertEqual(status, 403)
                self.assertEqual(FakeUpstream.calls, [])
                self.assertTrue(gateway.LOCKED)
                self.assertEqual(events[-1]['event'], 'rejected')
                self.assertEqual(events[-1]['reason'], 'server-side or unsupported tool type is not allowed')
                self.assertEqual(events[-1]['fields'], ['tools[].type:' + name])
                self.assertNotIn('secret-', raw)
        for path, base in (('/v1/messages', claude), ('/v1/responses', codex)):
            for tools in ({}, {'type': 'web_search'}, 'web_search', None):
                with self.subTest(path=path, tools=tools):
                    status, events, _ = self.post(path, dict(base, tools=tools))
                    self.assertEqual((status, events[-1]['fields']), (403, ['tools']))
                    self.assertEqual(FakeUpstream.calls, [])
                    self.assertTrue(gateway.LOCKED)

    def test_r10_co_01_client_executed_tools_are_forwarded_unchanged(self):
        claude_tools = [{'name': 'Bash', 'description': 'run', 'input_schema': {'type': 'object'}},
                        {'type': 'custom', 'name': 'Edit', 'input_schema': {'type': 'object'}}]
        for path in ('/v1/messages?beta=true', '/v1/messages/count_tokens'):
            with self.subTest(path=path):
                status, _, _ = self.post(path, {'model': 'claude-haiku-5-5', 'tools': claude_tools,
                                                 'output_config': {'effort': 'low'}})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(FakeUpstream.calls[0]['body'])['tools'], claude_tools)
        codex_tools = [{'type': 'function', 'name': 'shell', 'parameters': {'type': 'object'}},
                       {'type': 'custom', 'name': 'apply_patch'}, {'type': 'local_shell'}]
        status, _, _ = self.post('/v1/responses', {'model': 'gpt-6-luna', 'tools': codex_tools,
                                                   'reasoning': {'effort': 'low'}})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(FakeUpstream.calls[0]['body'])['tools'], codex_tools)
        self.assertFalse(gateway.LOCKED)

    def test_r10_co_01_bench_codex_config_disables_default_on_paid_features(self):
        startup = (CONTAINER / 'start-container.sh').read_text(encoding='utf-8')
        config = startup.split("<<'TOML'\n", 1)[1].split('\nTOML', 1)[0]
        self.assertTrue(config.startswith('openai_base_url = "https://gateway.bench.test:8443/v1"\n'))
        top_level = config.split('\n[', 1)[0].splitlines()
        self.assertIn('web_search = "disabled"', top_level)
        features = config.split('\n[features]\n', 1)[1].split('\n[', 1)[0].splitlines()
        for name in ('image_generation', 'computer_use', 'fast_mode', 'ultrafast_mode', 'browser_use'):
            self.assertIn(f'{name} = false', features, name)
        try:
            import tomllib
        except ImportError:  # Python 3.10: the line checks above still apply.
            return
        parsed = tomllib.loads(config)
        self.assertEqual(parsed['web_search'], 'disabled')
        self.assertEqual(parsed['features'], {'image_generation': False, 'computer_use': False,
                                              'fast_mode': False, 'ultrafast_mode': False,
                                              'browser_use': False})

    def native_observation(self, runs):
        return {'parent_thread_id': 'parent', 'tool_records': [], 'runtime_requests': [], 'subagents': [
            {'id': 'native-id', 'origin': 'provider_native', 'threadId': 'parent',
             'prompt': 'ISSUE28_NATIVE_PROBE read/hash only', 'providerInstanceId': 'codex',
             'model': 'gpt-6-luna', 'childThreadId': 'native-thread', 'status': 'completed',
             'completedAt': '2026-10-13T00:00:00Z', 'result': 'a' * 64}],
            'threads': [{'id': 'native-thread', 'modelSelection': projected_selection()}], 'runs': runs}

    def test_r10_co_02_native_probe_with_zero_projected_runs_is_explicit(self):
        result = host_observations.verify_owned_tasks(self.native_observation([]), [], NATIVE_TARGET,
                                                      native_probe=True, expected_input_sha256='a' * 64)
        checks = result['native_probe_checks']
        self.assertTrue(result['native_child_visibility_verified'])
        self.assertEqual(checks['native_runs_projected'], 'none')
        self.assertTrue(checks['native_thread_selection'])
        self.assertTrue(checks['native_runs_terminal_if_projected'])
        self.assertNotIn('native_run_target_and_options', checks)
        # Zero runs still needs the projected thread with the exact selection.
        missing_thread = self.native_observation([])
        missing_thread['threads'] = []
        result = host_observations.verify_owned_tasks(missing_thread, [], NATIVE_TARGET,
                                                      native_probe=True, expected_input_sha256='a' * 64)
        self.assertFalse(result['native_probe_checks']['native_thread_selection'])
        self.assertFalse(result['native_child_visibility_verified'])
        completed = self.native_observation([{'threadId': 'native-thread', 'status': 'completed',
                                              'modelSelection': projected_selection()}])
        result = host_observations.verify_owned_tasks(completed, [], NATIVE_TARGET,
                                                      native_probe=True, expected_input_sha256='a' * 64)
        self.assertTrue(result['native_child_visibility_verified'])
        self.assertEqual(result['native_probe_checks']['native_runs_projected'], 1)

    def test_r10_co_02_running_native_run_fails_the_probe(self):
        running = self.native_observation([{'threadId': 'native-thread', 'status': 'running',
                                            'modelSelection': projected_selection()}])
        result = host_observations.verify_owned_tasks(running, [], NATIVE_TARGET,
                                                      native_probe=True, expected_input_sha256='a' * 64)
        self.assertFalse(result['native_probe_checks']['native_runs_terminal_if_projected'])
        self.assertEqual(result['native_probe_checks']['native_runs_projected'], 1)
        self.assertFalse(result['native_child_visibility_verified'])

    def app_observation(self, runs, extra_runs=()):
        return {'parent_thread_id': 'parent', 'runtime_requests': [],
                'subagents': [{'threadId': 'parent', 'id': 'task1', 'childThreadId': 'child1'}],
                'threads': [{'id': 'child1', 'modelSelection': projected_selection()}],
                'runs': [dict(run, threadId='child1', modelSelection=projected_selection()) for run in runs]
                + list(extra_runs),
                'tool_records': [
                    {'toolName': 't3-code.delegate_task', 'input': {'target': NATIVE_TARGET},
                     'output': {'taskId': 'task1'}},
                    {'toolName': 't3-code.task_status', 'input': {'taskId': 'task1'},
                     'output': {'taskId': 'task1', 'status': 'completed', 'childThreadId': 'child1',
                                'workState': 'result_available', 'hasPendingChildRuns': False,
                                'providerInstanceId': 'codex', 'model': 'gpt-6-luna'}}]}

    def test_r10_co_03_app_child_needs_completed_projected_runs_and_no_active_run(self):
        verify = host_observations.verify_owned_tasks
        self.assertTrue(verify(self.app_observation([{'status': 'completed'}]), ['task1'], NATIVE_TARGET)['verified'])
        self.assertTrue(verify(self.app_observation([{'status': 'interrupted'}, {'status': 'completed'}]),
                               ['task1'], NATIVE_TARGET)['verified'])
        cases = {'cached completed status with live running run': [{'status': 'completed'}, {'status': 'running'}],
                 'no projected runs': [],
                 'no completed run': [{'status': 'failed'}],
                 'unknown run status': [{'status': 'completed'}, {'status': 'queued'}]}
        for name, runs in cases.items():
            with self.subTest(name=name):
                result = verify(self.app_observation(runs), ['task1'], NATIVE_TARGET)
                self.assertTrue(result['checks']['terminal_no_pending'], 'cached status alone still passes')
                self.assertFalse(result['checks']['projected_child_runs_terminal'])
                self.assertFalse(result['verified'])
        grandchild = self.app_observation([{'status': 'completed'}],
                                          [{'threadId': 'grandchild', 'status': 'running'}])
        result = verify(grandchild, ['task1'], NATIVE_TARGET)
        self.assertTrue(result['checks']['projected_child_runs_terminal'])
        self.assertFalse(result['checks']['no_active_descendant_run'])
        self.assertFalse(result['verified'])

    def test_r10_co_04_canary_summary_rejects_overflowing_numbers_at_any_depth(self):
        for text in ('{"metric":1e999}', '{"a":{"b":[0,-1E400]}}', '{"a":[[{"b":1.0e+999}]]}'):
            with self.subTest(text=text):
                self.assertIsNone(driver.parse_canary_result(text))
        self.assertEqual(driver.parse_canary_result('{"a":{"b":[1.5e3,-2e-3,7]}}'),
                         {'a': {'b': [1500.0, -0.002, 7]}})

    def _unrecorded_replacement(self, record_error, receipt_dir_exists=True):
        run_id = '20261013T010203Z-abc123'
        name = f't3-issue28-gateway-{run_id}'
        manifest = {'run_id': run_id, 'created_resources': {}}
        mutations, listed = [], []

        def record(manifest_arg, *_args):
            # Mutate memory first, as record_created does, then fail to persist.
            manifest_arg['created_resources']['container_gateway'] = {'id': 'replacement-id'}
            raise record_error

        def fake_subprocess(argv, **_kwargs):
            listed.append(argv)
            return type('Done', (), {'returncode': 0, 'stdout': 'replacement-id\n'})()

        def fake_run(argv, _logs, check=True):
            mutations.append(argv)
            return 0
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'private.log'
            log.touch(mode=0o600)
            mpath = Path(temp) / ('manifest.json' if receipt_dir_exists else 'missing/manifest.json')
            with patch.object(benchctl, 'record_created', side_effect=record) as recorded, \
                    patch.object(benchctl, 'find_manifest', return_value=mpath), \
                    patch.object(benchctl, 'run', side_effect=fake_run), \
                    patch.object(benchctl.subprocess, 'run', side_effect=fake_subprocess), \
                    patch.object(benchctl.time, 'sleep'):
                with self.assertRaises(RuntimeError) as caught:
                    benchctl.record_replacement_gateway(manifest, run_id, name, log)
            saved = json.loads(mpath.read_text(encoding='utf-8')) if mpath.exists() else None
        return caught.exception, recorded.call_count, listed, mutations, manifest, saved

    def test_r10_co_05_manifest_oserror_is_a_failed_recording_with_scoped_cleanup(self):
        error, attempts, listed, mutations, manifest, saved = self._unrecorded_replacement(
            OSError(28, 'No space left on device'))
        self.assertEqual(attempts, 3)
        self.assertIn('labelled container removed', str(error))
        self.assertEqual(len(listed), 1)
        self.assertIn('label=io.t3.issue28.stage=s1b', listed[0])
        self.assertIn(['docker', 'rm', '--force', 'replacement-id'], mutations)
        self.assertNotIn('container_gateway', manifest['created_resources'])
        self.assertEqual(saved['gateway_replacement_unrecorded']['removed'], 1)
        self.assertNotIn('container_gateway', saved['created_resources'])

    def test_r10_co_05_cleanup_runs_even_when_the_receipt_cannot_be_written(self):
        error, attempts, _listed, mutations, manifest, saved = self._unrecorded_replacement(
            OSError(5, 'Input/output error'), receipt_dir_exists=False)
        self.assertEqual(attempts, 3)
        self.assertIn(['docker', 'rm', '--force', 'replacement-id'], mutations)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn('cleanup receipt was not saved', str(error))
        self.assertIsNone(saved)
        self.assertEqual(manifest['gateway_replacement_unrecorded']['removed'], 1)



RUN_12 = '20261013T040506Z-c0ffee'


def owned_row(kind, role_name, identity, run_id=RUN_12):
    labels = {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': run_id}
    if kind == 'network':
        return {'Id': identity, 'Name': role_name, 'Labels': labels}
    if kind == 'image':
        return {'Id': identity, 'RepoTags': [role_name], 'Config': {'Labels': labels}}
    return {'Id': identity, 'Name': '/' + role_name, 'Config': {'Labels': labels}}


def full_manifest(run_id=RUN_12):
    names = {'agent': f't3-issue28-agent-{run_id}', 'gateway': f't3-issue28-gateway-{run_id}',
             'github': f't3-issue28-github-{run_id}'}
    roles = {'image': ('image', f't3-issue28-s1b:{run_id}'),
             'network_private': ('network', f't3-issue28-private-{run_id}'),
             'network_egress': ('network', f't3-issue28-egress-{run_id}'),
             'container_agent': ('container', names['agent']),
             'container_github': ('container', names['github'])}
    labels = {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': run_id}
    return {'run_id': run_id, 'image': f't3-issue28-s1b:{run_id}',
            'networks': [f't3-issue28-private-{run_id}', f't3-issue28-egress-{run_id}'],
            'containers': names, 'status': 'running',
            'retired_resources': [{'kind': 'container', 'name': names['gateway'], 'id': 'bootstrap-id',
                                   'run_id': run_id, 'labels': dict(labels)}],
            'created_resources': {role: {'kind': kind, 'name': name, 'id': f'{role}-id',
                                         'run_id': run_id, 'labels': dict(labels)}
                                  for role, (kind, name) in roles.items()}}


class Pass12ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 12 repairs of review 11 container findings."""

    def canary_tree(self, temp):
        workspace, results, inputs = Path(temp) / 'workspace', Path(temp) / 'results', Path(temp) / 'input'
        for folder in (workspace / '.git', results, inputs):
            folder.mkdir(parents=True)
        (workspace / '.git' / 'config').write_text('[core]\n', encoding='utf-8')
        brief = inputs / 'brief.txt'
        brief.write_text('S1b deterministic container smoke input.\n', encoding='utf-8')
        digest = hashlib.sha256(brief.read_bytes()).hexdigest()
        (inputs / 'brief.sha256').write_text(digest + '\n', encoding='ascii')
        return workspace, results, inputs, digest

    def scope(self, workspace, before, provider='codex'):
        changes = benchctl.workspace_changes_since(workspace, before)
        return benchctl.workspace_write_scope_valid(workspace, changes, provider)

    def run_helper(self, workspace, brief, target):
        import smoke_helper
        with patch.object(smoke_helper, 'WORKSPACE_ROOT', str(workspace)), \
                contextlib.redirect_stdout(io.StringIO()):
            smoke_helper.main([str(brief), str(target)])

    def test_r11_co_01_helper_output_symlinked_to_results_fails_both_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, results, inputs, digest = self.canary_tree(temp)
            before = benchctl.workspace_inventory(workspace)
            assigned = workspace / 'canary' / 'codex' / 'task-1'
            assigned.mkdir(parents=True)
            escaped = results / 'escaped-helper.json'
            escaped.write_text(json.dumps({'input_sha256': digest}) + '\n', encoding='utf-8')
            (assigned / 'helper.json').symlink_to(escaped)
            self.assertFalse(benchctl.helper_output_valid(
                workspace, 'codex', inputs / 'brief.sha256', ['codex']))
            self.assertFalse(self.scope(workspace, before))

    def test_r11_co_01_symlinked_assigned_ancestor_fails_both_checks(self):
        for link in ('canary/codex', 'canary/codex/task-1'):
            with self.subTest(link=link), tempfile.TemporaryDirectory() as temp:
                workspace, results, inputs, digest = self.canary_tree(temp)
                before = benchctl.workspace_inventory(workspace)
                outside = results / 'outside'
                (outside / 'task-1' if link == 'canary/codex' else outside).mkdir(parents=True)
                helper = (outside / 'task-1' if link == 'canary/codex' else outside) / 'helper.json'
                helper.write_text(json.dumps({'input_sha256': digest}) + '\n', encoding='utf-8')
                (workspace / link).parent.mkdir(parents=True, exist_ok=True)
                (workspace / link).symlink_to(outside, target_is_directory=True)
                self.assertFalse(benchctl.helper_output_valid(
                    workspace, 'codex', inputs / 'brief.sha256', ['codex']))
                self.assertFalse(self.scope(workspace, before))

    def test_r11_co_01_symlink_left_inside_assigned_directory_fails_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, results, inputs, _digest = self.canary_tree(temp)
            assigned = workspace / 'canary' / 'codex' / 'task-1'
            assigned.mkdir(parents=True)
            (assigned / 'escape').symlink_to(results, target_is_directory=True)
            before = benchctl.workspace_inventory(workspace)
            self.run_helper(workspace, inputs / 'brief.txt', assigned / 'helper.json')
            # The pre-existing link is unchanged, yet still a way out of the assigned directory.
            self.assertFalse(self.scope(workspace, before))
            self.assertFalse(benchctl.helper_output_valid(
                workspace, 'codex', inputs / 'brief.sha256', ['codex']))

    def test_r11_co_01_smoke_helper_refuses_symlinked_output_and_ancestors(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, results, inputs, _digest = self.canary_tree(temp)
            assigned = workspace / 'canary' / 'codex' / 'task-1'
            assigned.mkdir(parents=True)
            escaped = results / 'escaped-helper.json'
            escaped.write_text('sentinel\n', encoding='utf-8')
            (assigned / 'helper.json').symlink_to(escaped)
            with self.assertRaises(SystemExit):
                self.run_helper(workspace, inputs / 'brief.txt', assigned / 'helper.json')
            self.assertEqual(escaped.read_text(encoding='utf-8'), 'sentinel\n')
            dangling = assigned / 'dangling.json'
            dangling.symlink_to(results / 'created-through-link.json')
            with self.assertRaises(SystemExit):
                self.run_helper(workspace, inputs / 'brief.txt', dangling)
            self.assertFalse((results / 'created-through-link.json').exists())
            (workspace / 'canary' / 'claudeAgent').symlink_to(results, target_is_directory=True)
            with self.assertRaises(SystemExit):
                self.run_helper(workspace, inputs / 'brief.txt',
                                workspace / 'canary' / 'claudeAgent' / 'task-1' / 'helper.json')
            self.assertFalse((results / 'task-1').exists())
            for outside in (results / 'helper.json',
                            workspace / 'canary' / '..' / '..' / 'results' / 'helper.json'):
                with self.assertRaises(SystemExit):
                    self.run_helper(workspace, inputs / 'brief.txt', outside)
            self.assertFalse((results / 'helper.json').exists())

    def test_r11_co_01_regular_helper_output_still_passes_both_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _results, inputs, digest = self.canary_tree(temp)
            before = benchctl.workspace_inventory(workspace)
            helper = workspace / 'canary' / 'codex' / 'task-1' / 'helper.json'
            self.run_helper(workspace, inputs / 'brief.txt', helper)
            self.assertEqual(json.loads(helper.read_text(encoding='utf-8')), {'input_sha256': digest})
            self.assertTrue(benchctl.helper_output_valid(
                workspace, 'codex', inputs / 'brief.sha256', ['codex']))
            self.assertTrue(self.scope(workspace, before))

    def manifest_dir(self, temp, manifest):
        results = Path(temp)
        run_dir = results / RUN_12
        run_dir.mkdir(mode=0o700)
        log = run_dir / 'private.log'
        log.touch(mode=0o600)
        path = run_dir / 'resource-manifest.json'
        path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        path.chmod(0o600)
        return results, run_dir, log, path

    def test_r11_co_02_failed_manifest_write_keeps_last_good_manifest(self):
        name = f't3-issue28-gateway-{RUN_12}'
        failures = {'replace': (os, 'replace', OSError(28, 'No space left on device')),
                    'fsync': (os, 'fsync', OSError(5, 'Input/output error')),
                    'partial-write': (os, 'write', [17, OSError(28, 'No space left on device')])}
        for label, (module, attribute, error) in failures.items():
            with self.subTest(failure=label), tempfile.TemporaryDirectory() as temp:
                manifest = full_manifest()
                _results, run_dir, log, path = self.manifest_dir(temp, manifest)
                good = path.read_bytes()
                with patch.object(benchctl, 'docker_inspect_json',
                                  return_value=owned_row('container', name, 'replacement-id')), \
                        patch.object(module, attribute, side_effect=error):
                    with self.assertRaises(OSError):
                        benchctl.record_created(manifest, path, 'container', 'container_gateway', name, log)
                self.assertEqual(path.read_bytes(), good)
                self.assertEqual(sorted(item.name for item in run_dir.iterdir()),
                                 ['private.log', 'resource-manifest.json'])

    def test_r11_co_02_unrecorded_replacement_leaves_a_manifest_down_can_use(self):
        manifest = full_manifest()
        name = manifest['containers']['gateway']
        rows = {f'{role}-id': owned_row(row['kind'], row['name'], f'{role}-id')
                for role, row in manifest['created_resources'].items()}
        rows[name] = owned_row('container', name, 'replacement-id')
        mutations = []

        def fake_subprocess(_argv, **_kwargs):
            # Docker lists the replacement only until it has been removed.
            removed = ['docker', 'rm', '--force', 'replacement-id'] in mutations
            return type('Done', (), {'returncode': 0,
                                     'stdout': '' if removed else 'replacement-id\n'})()

        def fake_run(argv, _logs, check=True):
            mutations.append(argv)
            return 0
        with tempfile.TemporaryDirectory() as temp:
            results, _run_dir, log, path = self.manifest_dir(temp, manifest)
            good = path.read_bytes()
            with patch.object(benchctl, 'RESULTS', results), \
                    patch.object(benchctl, 'docker_inspect_json', side_effect=lambda _k, ref: rows[ref]), \
                    patch.object(benchctl, 'run', side_effect=fake_run), \
                    patch.object(benchctl.subprocess, 'run', side_effect=fake_subprocess), \
                    patch.object(benchctl.time, 'sleep'):
                with patch.object(os, 'replace', side_effect=OSError(28, 'No space left on device')):
                    with self.assertRaises(RuntimeError) as caught:
                        benchctl.record_replacement_gateway(manifest, RUN_12, name, log)
                self.assertIn('cleanup receipt was not saved', str(caught.exception))
                self.assertIn(['docker', 'rm', '--force', 'replacement-id'], mutations)
                self.assertEqual(path.read_bytes(), good)
                with contextlib.redirect_stdout(io.StringIO()):
                    code = benchctl.manage(type('Args', (), {'command': 'down', 'run_id': RUN_12})())
            self.assertEqual(code, 0)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['status'], 'stopped')
            self.assertEqual(set(saved['cleanup']) - {'container_gateway'},
                             set(manifest['created_resources']))
            self.assertIn(['docker', 'stop', '--time', '10', 'container_agent-id'], mutations)
            self.assertIn(['docker', 'network', 'rm', 'network_private-id'], mutations)

    def test_r11_co_02_manifest_writer_is_atomic_private_and_used_once_by_gateway_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'resource-manifest.json'
            path.write_text('{"old": true}\n', encoding='utf-8')
            benchctl.write_manifest(path, {'run_id': RUN_12})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'run_id': RUN_12})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual([item.name for item in Path(temp).iterdir()], ['resource-manifest.json'])
        source = (CONTAINER / 'benchctl.py').read_text(encoding='utf-8')
        self.assertNotIn("write_text(json.dumps(manifest", source)
        with patch.object(benchctl, 'write_manifest') as writes:
            PolicyAndIsolationTest._replace_gateway(
                self, ['', json.dumps({'event': 'ready'}) + '\n'], iter([0, 1, 2, 3]))
        # Only the bootstrap retirement is saved here; record_created saves the replacement.
        self.assertEqual(writes.call_count, 1)

    def usage_audit(self, provider, usages):
        wire = 'openai' if provider == 'codex' else 'anthropic'
        lines = []
        for index, usage in enumerate(usages):
            request_id = f'r{index}'
            lines.append({'event': 'forward-started', 'request_kind': 'inference',
                          'provider': wire, 'request_id': request_id})
            lines.append({'event': 'forwarded', 'request_kind': 'inference', 'provider': wire,
                          'request_id': request_id, 'model': 'expected-model', 'status': 200,
                          'response_model_ids': ['canonical-model'], 'response_complete': True,
                          'usage': usage})
        stdout = ''.join(json.dumps(line) + '\n' for line in lines)
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(benchctl.subprocess, 'run',
                             return_value=type('Done', (), {'stdout': stdout, 'returncode': 0})()):
            return benchctl.gateway_model_observations('gateway', 'expected-model', provider,
                                                       Path(temp) / 'private.log', 'canonical-model')

    def test_r11_co_03_partial_or_absent_usage_is_explicitly_incomplete(self):
        cases = [
            ('codex', [{'output_tokens': 5}], False, 'usage-partial'),
            ('codex', [None], False, 'usage-absent'),
            ('codex', [{'input_tokens': 3, 'output_tokens': 5}, None], False, 'usage-partial'),
            ('codex', [{'input_tokens': 3, 'output_tokens': 5, 'total_tokens': 8}], True, None),
            ('claudeAgent', [{'input_tokens': 3}], False, 'usage-partial'),
            ('claudeAgent', [{'cache_read_input_tokens': 2}], False, 'usage-partial'),
            ('claudeAgent', [{'input_tokens': 3, 'output_tokens': 5}], True, None),
        ]
        for provider, usages, complete, reason in cases:
            with self.subTest(provider=provider, usages=usages):
                audit = self.usage_audit(provider, usages)
                self.assertTrue(audit['verified'])
                self.assertIs(audit['usage_complete'], complete)
                self.assertEqual(audit['usage_reason'], reason)
                self.assertEqual(audit['reason'], reason)
                # Known counters are preserved exactly as observed.
                self.assertEqual([row['usage'] for row in audit['requests']], usages)


# Creation order in `setup`, with each role's kind and resource-name prefix.
SETUP_ROLES = {'image': ('image', 't3-issue28-s1b:'),
               'network_private': ('network', 't3-issue28-private-'),
               'network_egress': ('network', 't3-issue28-egress-'),
               'container_gateway': ('container', 't3-issue28-gateway-'),
               'container_github': ('container', 't3-issue28-github-'),
               'container_agent': ('container', 't3-issue28-agent-')}


class ControllerCrash(BaseException):
    """Ends the controller mid-operation; no `except Exception` handler runs, as with a kill."""


def fixture_done(returncode=0, stdout=''):
    return type('Done', (), {'returncode': returncode, 'stdout': stdout, 'stderr': ''})()


def name_owned_row(kind, ref):
    """Docker inspect fixture: names resolve to '<name>-id'; IDs resolve back to their name."""
    name = ref[:-3] if ref.endswith('-id') else ref
    run_id = re.search(r'\d{8}T\d{6}Z-[0-9a-f]{6}$', name).group(0)
    return owned_row(kind, name, name + '-id', run_id)


def listed_name(argv):
    for item in argv:
        if item.startswith('name=^'):
            return item[len('name=^'):].rstrip('$').lstrip('/').replace('\\', '')
        if item.startswith('reference='):
            return item[len('reference='):]
    return None


class Pass13ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 13 repairs of review 12 container findings."""

    canary_tree = Pass12ContainerRepairTest.canary_tree
    scope = Pass12ContainerRepairTest.scope
    run_helper = Pass12ContainerRepairTest.run_helper
    manifest_dir = Pass12ContainerRepairTest.manifest_dir

    # R12-CO-01: every workspace entry is inventoried by type.

    def seeded_canary_tree(self, temp):
        workspace, results, inputs, digest = self.canary_tree(temp)
        (workspace / '.git' / 'refs' / 'tags').mkdir(parents=True)
        (workspace / '.git' / 'description').write_text('fixture\n', encoding='utf-8')
        return workspace, results, inputs, digest

    def test_r12_co_01_empty_directory_created_outside_assigned_path_fails_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _results, inputs, _digest = self.seeded_canary_tree(temp)
            before = benchctl.workspace_inventory(workspace)
            (workspace / '.git' / 'index.lock').mkdir()
            self.run_helper(workspace, inputs / 'brief.txt',
                            workspace / 'canary' / 'codex' / 'task-1' / 'helper.json')
            # The helper check alone cannot see the out-of-scope directory.
            self.assertTrue(benchctl.helper_output_valid(
                workspace, 'codex', inputs / 'brief.sha256', ['codex']))
            changes = benchctl.workspace_changes_since(workspace, before)
            self.assertFalse(benchctl.workspace_write_scope_valid(workspace, changes, 'codex'))
            info = os.lstat(workspace / '.git' / 'index.lock')
            self.assertIn({'path': '.git/index.lock', 'kind': 'added', 'before': None,
                           'after': {'type': 'directory', 'mode': stat.S_IMODE(info.st_mode),
                                     'uid': info.st_uid, 'gid': info.st_gid}}, changes)

    def test_r12_co_01_special_removed_or_retyped_entries_fail_scope(self):
        def make_socket(path):
            # mknod makes a socket inode without binding, so no network access is needed.
            os.mknod(path, stat.S_IFSOCK | 0o600)

        def replace_with_directory(path):
            path.unlink()
            path.mkdir()

        def replace_with_file(path):
            path.rmdir()
            path.write_text('now a file\n', encoding='utf-8')
        cases = {
            'fifo outside': lambda ws: os.mkfifo(ws / '.git' / 'pipe'),
            'fifo inside assigned': lambda ws: os.mkfifo(ws / 'canary' / 'codex' / 'task-1' / 'pipe'),
            'socket outside': lambda ws: make_socket(ws / 's'),
            'empty directory removed': lambda ws: (ws / '.git' / 'refs' / 'tags').rmdir(),
            'file retyped as directory': lambda ws: replace_with_directory(ws / '.git' / 'description'),
            'directory retyped as file': lambda ws: replace_with_file(ws / '.git' / 'refs' / 'tags'),
            'extra sibling of assigned directory': lambda ws: (ws / 'canary' / 'codex' / 'task-2').mkdir(),
            'other provider folder': lambda ws: (ws / 'canary' / 'claudeAgent').mkdir(),
            'symlink outside': lambda ws: (ws / '.git' / 'link').symlink_to(ws / '.git' / 'config'),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                workspace, _results, inputs, _digest = self.seeded_canary_tree(temp)
                before = benchctl.workspace_inventory(workspace)
                self.run_helper(workspace, inputs / 'brief.txt',
                                workspace / 'canary' / 'codex' / 'task-1' / 'helper.json')
                self.assertTrue(self.scope(workspace, before))
                mutate(workspace)
                self.assertFalse(self.scope(workspace, before))

    def test_r12_co_01_assigned_ancestors_may_only_be_created_as_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _results, _inputs, _digest = self.seeded_canary_tree(temp)
            before = benchctl.workspace_inventory(workspace)
            (workspace / 'canary').write_text('not a directory\n', encoding='utf-8')
            self.assertFalse(self.scope(workspace, before))
        with tempfile.TemporaryDirectory() as temp:
            workspace, _results, inputs, _digest = self.seeded_canary_tree(temp)
            earlier = workspace / 'canary' / 'claudeAgent' / 'task-1'
            earlier.mkdir(parents=True)
            (earlier / 'helper.json').write_text('{}\n', encoding='utf-8')
            before = benchctl.workspace_inventory(workspace)
            assigned = workspace / 'canary' / 'codex' / 'task-1'
            self.run_helper(workspace, inputs / 'brief.txt', assigned / 'helper.json')
            (assigned / 'notes').mkdir()
            (assigned / 'notes' / 'summary.txt').write_text('ok\n', encoding='utf-8')
            changes = benchctl.workspace_changes_since(workspace, before)
            self.assertTrue(benchctl.workspace_write_scope_valid(workspace, changes, 'codex'))
            self.assertEqual([change['path'] for change in changes
                              if change['after']['type'] == 'directory'],
                             ['canary/codex', 'canary/codex/task-1', 'canary/codex/task-1/notes'])

    @unittest.skipIf(os.geteuid() == 0, 'root bypasses directory permissions')
    def test_r12_co_01_unlistable_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _results, inputs, _digest = self.seeded_canary_tree(temp)
            before = benchctl.workspace_inventory(workspace)
            self.run_helper(workspace, inputs / 'brief.txt',
                            workspace / 'canary' / 'codex' / 'task-1' / 'helper.json')
            hidden = workspace / '.git' / 'refs'
            hidden.chmod(0)
            try:
                self.assertFalse(self.scope(workspace, before))
                self.assertTrue(benchctl.workspace_inventory(workspace)['.git/refs']['unlisted'])
            finally:
                hidden.chmod(0o755)

    def test_r12_co_01_inventory_records_types_without_following_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'd').mkdir()
            (root / 'd' / 'f').write_bytes(b'x')
            (root / 'l').symlink_to('d', target_is_directory=True)
            os.mkfifo(root / 'p')
            inventory = benchctl.workspace_inventory(root)

            def meta(name):
                info = os.lstat(root / name)
                return {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
            expected = {'.': {'type': 'directory', **meta('.')},
                        'd': {'type': 'directory', **meta('d')},
                        'd/f': {'type': 'file', 'sha256': hashlib.sha256(b'x').hexdigest(),
                                **meta('d/f'), 'links': 1},
                        'l': {'type': 'symlink', 'target': 'd', **meta('l')},
                        'p': {'type': 'fifo', **meta('p')}}
        self.assertEqual(inventory, expected)

    def test_r12_co_01_smoke_confinement_records_directories_and_special_files(self):
        def tree(temp):
            workspace = Path(temp)
            (workspace / '.git').mkdir()
            (workspace / '.git' / 'config').write_text('[core]\n', encoding='utf-8')
            before = smoke.workspace_snapshot(workspace)
            output = workspace / 'smoke' / 'task-1' / 'result.json'
            output.parent.mkdir(parents=True)
            output.write_text('{}\n', encoding='utf-8')
            return workspace, before
        assigned = Path('smoke/task-1')
        with tempfile.TemporaryDirectory() as temp:
            workspace, before = tree(temp)
            self.assertTrue(smoke.assigned_workspace_changes_confined(
                before, smoke.workspace_snapshot(workspace), assigned))
        cases = {'empty directory outside': lambda ws: (ws / '.git' / 'index.lock').mkdir(),
                 'fifo outside': lambda ws: os.mkfifo(ws / '.git' / 'pipe'),
                 'symlink in assigned directory':
                     lambda ws: (ws / 'smoke' / 'task-1' / 'link').symlink_to(ws / '.git'),
                 'fifo in assigned directory': lambda ws: os.mkfifo(ws / 'smoke' / 'task-1' / 'pipe'),
                 'ancestor sibling': lambda ws: (ws / 'smoke' / 'task-2').mkdir()}
        for label, mutate in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                workspace, before = tree(temp)
                mutate(workspace)
                after = smoke.workspace_snapshot(workspace)
                self.assertFalse(smoke.assigned_workspace_changes_confined(before, after, assigned))

    # R12-CO-02: every initial create is recorded or removed.

    def drive_setup(self, temp, persist_fail_role=None, create_fail_role=None,
                    inspect=name_owned_row, lookup=None, crash=None):
        temp = Path(temp)
        results = temp / 'results'
        secret = temp / 'bench.env'
        secret.write_text('FIXTURE=1\n', encoding='utf-8')
        secret.chmod(0o600)
        node = temp / 'node'
        node.write_bytes(b'node fixture')
        runtime = temp / 'runtime'
        runtime.mkdir()
        (runtime / 't3').write_bytes(b't3 fixture')
        commands, listings, storage_full = [], [], []
        real_write = benchctl.write_manifest

        def make_context(run_dir, _log):
            context = run_dir / 'build-context'
            context.mkdir()
            for name in (*benchctl.SOURCE_FILES, 'model_policy.py'):
                (context / name).write_text(name, encoding='utf-8')
            return context

        def certificate(run_dir, _log):
            tls = run_dir / 'tls'
            tls.mkdir()
            paths = tuple(tls / name for name in ('ca.crt', 'gateway.crt', 'gateway.key'))
            for path in paths:
                path.write_text('fixture\n', encoding='utf-8')
            return paths

        def created_name(argv):
            if argv[:2] == ['docker', 'build']:
                return argv[argv.index('--tag') + 1]
            if argv[:3] == ['docker', 'network', 'create']:
                return argv[-1]
            if argv[:3] == ['docker', 'run', '-d']:
                return argv[argv.index('--name') + 1]
            return None

        def fake_run(argv, _logs, check=True):
            commands.append(argv)
            name = created_name(argv)
            if crash is not None:
                crash(argv, name)  # May end the controller like a kill would.
            if create_fail_role and name and name.startswith(SETUP_ROLES[create_fail_role][1]):
                raise RuntimeError(f'command failed (125): {argv[0]}')
            return 0

        def fake_write(path, manifest):
            # Storage fills up once the failing role's identity is about to be saved.
            if persist_fail_role in manifest.get('created_resources', {}) or storage_full:
                storage_full.append(True)
                with patch.object(os, 'replace', side_effect=OSError(28, 'No space left on device')):
                    return real_write(path, manifest)
            return real_write(path, manifest)

        def fake_subprocess(argv, **_kwargs):
            listings.append(argv)
            if lookup is not None:
                return lookup(argv)
            return fixture_done(stdout=listed_name(argv) + '-id\n')
        error = None
        with patch.object(benchctl, 'RESULTS', results), \
                patch.object(benchctl, 'SECRET_ENV', secret), \
                patch.object(benchctl, 'NODE_EXECUTABLE', node), \
                patch.object(benchctl, 'RUNTIME', runtime), \
                patch.object(benchctl, 'docker_ok', return_value={'version': 'fixture', 'rootless': True}), \
                patch.object(benchctl, 'make_context', side_effect=make_context), \
                patch.object(benchctl, 'certificate', side_effect=certificate), \
                patch.object(benchctl, 'image_provenance', return_value={}), \
                patch.object(benchctl, 'verify_isolation', return_value={'mounts_verified': True}), \
                patch.object(benchctl, 'run', side_effect=fake_run), \
                patch.object(benchctl, 'docker_inspect_json', side_effect=inspect), \
                patch.object(benchctl, 'write_manifest', side_effect=fake_write), \
                patch.object(benchctl.subprocess, 'run', side_effect=fake_subprocess), \
                patch.object(benchctl.time, 'sleep'), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                benchctl.setup(None)
            except (Exception, ControllerCrash) as exc:  # noqa: BLE001 - the test inspects it.
                error = exc
        run_dir, = results.iterdir()
        return error, run_dir, commands, listings

    def test_r12_co_02_unpersisted_initial_creation_is_removed_by_labels_and_name(self):
        order = list(SETUP_ROLES)
        for role, (kind, prefix) in SETUP_ROLES.items():
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temp:
                error, run_dir, commands, listings = self.drive_setup(temp, persist_fail_role=role)
                self.assertIsInstance(error, RuntimeError)
                self.assertIn(f'{role} identity could not be recorded; labelled {kind} removed',
                              str(error))
                self.assertIn('cleanup receipt was not saved', str(error))
                name = prefix + run_dir.name
                self.assertEqual(len(listings), 1)
                self.assertIn('label=io.t3.issue28.stage=s1b', listings[0])
                self.assertIn(f'label=io.t3.issue28.run={run_dir.name}', listings[0])
                self.assertEqual(listed_name(listings[0]), name)
                self.assertEqual(commands[-1], [*benchctl.REMOVE_OWNED[kind], name + '-id'])
                # The last committed manifest is intact and names only the earlier resources.
                saved = json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))
                self.assertEqual(set(saved.get('created_resources', {})), set(order[:order.index(role)]))
                self.assertEqual(saved['status'], 'preparing')
                self.assertEqual(list(run_dir.glob('.resource-manifest.json.*')), [])

    def test_r12_co_02_agent_persist_failure_leaves_a_manifest_down_can_finish(self):
        with tempfile.TemporaryDirectory() as temp:
            error, run_dir, commands, _listings = self.drive_setup(
                temp, persist_fail_role='container_agent')
            agent = 't3-issue28-agent-' + run_dir.name
            self.assertIn(['docker', 'rm', '--force', agent + '-id'], commands)
            self.assertIsInstance(error, RuntimeError)
            mutations = []

            def fake_run(argv, _logs, check=True):
                mutations.append(argv)
                return 0
            # Storage has recovered; down works from the last committed manifest.
            with patch.object(benchctl, 'RESULTS', run_dir.parent), \
                    patch.object(benchctl, 'docker_inspect_json', side_effect=name_owned_row), \
                    patch.object(benchctl, 'run', side_effect=fake_run), \
                    patch.object(benchctl.subprocess, 'run', return_value=fixture_done()), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = benchctl.manage(type('Args', (), {'command': 'down', 'run_id': run_dir.name})())
            saved = json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 0)
        self.assertEqual(saved['status'], 'stopped')
        self.assertEqual(saved['cleanup']['container_agent'], 'not-created-no-cleanup-authority')
        self.assertIn(['docker', 'rm', 't3-issue28-gateway-' + run_dir.name + '-id'], mutations)
        self.assertIn(['docker', 'network', 'rm', 't3-issue28-private-' + run_dir.name + '-id'], mutations)

    def test_r12_co_02_failed_create_command_removes_any_labelled_leftover(self):
        for role in ('image', 'network_egress', 'container_github', 'container_agent'):
            kind, prefix = SETUP_ROLES[role]
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temp:
                error, run_dir, commands, listings = self.drive_setup(temp, create_fail_role=role)
                self.assertIsInstance(error, RuntimeError)
                self.assertIn(f'{role} creation failed; labelled {kind} removed', str(error))
                name = prefix + run_dir.name
                self.assertEqual([listed_name(argv) for argv in listings], [name])
                self.assertEqual(commands[-1], [*benchctl.REMOVE_OWNED[kind], name + '-id'])
                saved = json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))
                self.assertNotIn(role, saved.get('created_resources', {}))
                self.assertEqual(saved['unrecorded_resources'][role]['removed'], 1)
                self.assertEqual(saved['status'], 'partial-failure')

    def test_r12_co_02_failed_replacement_create_removes_any_labelled_leftover(self):
        name = f't3-issue28-gateway-{RUN_12}'
        manifest = {'run_id': RUN_12, 'image': f't3-issue28-s1b:{RUN_12}',
                    'networks': [f't3-issue28-private-{RUN_12}', f't3-issue28-egress-{RUN_12}'],
                    'containers': {'agent': f't3-issue28-agent-{RUN_12}', 'gateway': name},
                    'created_resources': {'container_gateway': {'id': 'bootstrap-id'}}}
        mutations, listed = [], []

        def fake_run(argv, _logs, check=True):
            mutations.append(argv)
            if argv[:3] == ['docker', 'run', '-d']:
                raise RuntimeError('command failed (125): docker')
            return 0

        def fake_subprocess(argv, **_kwargs):
            if argv[:2] == ['docker', 'ps']:
                listed.append(argv)
                return fixture_done(stdout='leftover-id\n')
            return fixture_done()
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'private.log'
            log.touch(mode=0o600)
            policy = Path(temp) / 'config' / 'runtime-targets.json'
            policy.parent.mkdir()
            policy.write_text('{}', encoding='utf-8')
            mpath = Path(temp) / 'manifest.json'
            with patch.object(benchctl, 'docker_inspect_json', return_value={}), \
                    patch.object(benchctl, 'validate_owned_resource', return_value=True), \
                    patch.object(benchctl, 'run', side_effect=fake_run), \
                    patch.object(benchctl, 'find_manifest', return_value=mpath), \
                    patch.object(benchctl.subprocess, 'run', side_effect=fake_subprocess):
                with self.assertRaisesRegex(RuntimeError,
                                            'replacement gateway creation failed; labelled container removed'):
                    benchctl.configure_gateway(manifest, policy, log)
            saved = json.loads(mpath.read_text(encoding='utf-8'))
        self.assertEqual([listed_name(argv) for argv in listed], [name])
        self.assertIn(['docker', 'rm', '--force', 'leftover-id'], mutations)
        self.assertFalse(any(argv[:3] == ['docker', 'network', 'connect'] for argv in mutations))
        self.assertNotIn('container_gateway', saved['created_resources'])
        self.assertEqual(saved['gateway_replacement_unrecorded']['removed'], 1)

    def test_r12_co_02_cleanup_lookup_failure_is_reported_not_raised_raw(self):
        manifest = {'run_id': RUN_12, 'created_resources': {}}
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'private.log'
            log.touch(mode=0o600)
            mpath = Path(temp) / 'manifest.json'
            with patch.object(benchctl, 'record_created', side_effect=RuntimeError('inspect failed')), \
                    patch.object(benchctl, 'find_manifest', return_value=mpath), \
                    patch.object(benchctl, 'run') as mutate, \
                    patch.object(benchctl.subprocess, 'run',
                                 side_effect=subprocess.TimeoutExpired('docker', 20)), \
                    patch.object(benchctl.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'cleanup incomplete, inspect run labels'):
                    benchctl.record_replacement_gateway(
                        manifest, RUN_12, f't3-issue28-gateway-{RUN_12}', log)
            saved = json.loads(mpath.read_text(encoding='utf-8'))
        mutate.assert_not_called()
        self.assertFalse(saved['gateway_replacement_unrecorded']['lookup_succeeded'])

    def test_r12_co_02_recording_checks_exact_name_and_survives_a_post_commit_log_failure(self):
        name = f't3-issue28-gateway-{RUN_12}'
        with tempfile.TemporaryDirectory() as temp:
            manifest = full_manifest()
            _results, _run_dir, log, path = self.manifest_dir(temp, manifest)
            good = path.read_bytes()
            with patch.object(benchctl, 'docker_inspect_json',
                              return_value=owned_row('container', 'unrelated-name', 'foreign-id')):
                with self.assertRaisesRegex(RuntimeError, 'exact name or task ownership labels'):
                    benchctl.record_created(manifest, path, 'container', 'container_gateway', name, log)
            self.assertEqual(path.read_bytes(), good)
            with patch.object(benchctl, 'docker_inspect_json',
                              return_value=owned_row('container', name, 'replacement-id')):
                benchctl.record_created(manifest, path, 'container', 'container_gateway', name,
                                        Path(temp) / 'missing' / 'private.log')
            saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved['created_resources']['container_gateway']['id'], 'replacement-id')

    def test_r12_co_02_provenance_probe_containers_carry_run_labels(self):
        calls = []

        def fake_subprocess(argv, **_kwargs):
            calls.append(argv)
            return fixture_done(stdout='fixture 1.0\n')
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(benchctl.subprocess, 'run', side_effect=fake_subprocess):
            benchctl.image_provenance(f't3-issue28-s1b:{RUN_12}', Path(temp) / 'private.log')
        probes = [argv for argv in calls if argv[:2] == ['docker', 'run']]
        self.assertEqual(len(probes), 6)
        for argv in probes:
            self.assertIn('--rm', argv)
            self.assertIn('io.t3.issue28.stage=s1b', argv)
            self.assertIn(f'io.t3.issue28.run={RUN_12}', argv)

    # R12-CO-03: committed-but-not-durable writes and absent recorded objects.

    def test_r12_co_03_directory_fsync_failure_after_replace_is_a_committed_write(self):
        real_fsync = os.fsync
        calls = []

        def second_call_fails(descriptor):
            calls.append(descriptor)
            if len(calls) == 2:
                raise OSError(errno.EIO, 'Input/output error')
            return real_fsync(descriptor)
        name = f't3-issue28-gateway-{RUN_12}'
        with tempfile.TemporaryDirectory() as temp:
            manifest = full_manifest()
            _results, run_dir, log, path = self.manifest_dir(temp, manifest)
            with patch.object(benchctl, 'docker_inspect_json',
                              return_value=owned_row('container', name, 'replacement-id')), \
                    patch.object(os, 'fsync', side_effect=second_call_fails):
                benchctl.record_created(manifest, path, 'container', 'container_gateway', name, log)
            saved = json.loads(path.read_text(encoding='utf-8'))
            leftovers = sorted(item.name for item in run_dir.iterdir())
        self.assertEqual(saved['created_resources']['container_gateway']['id'], 'replacement-id')
        self.assertEqual(saved['manifest_durability_uncertain'],
                         [{'stage': 'directory-fsync-after-replace', 'committed': True, 'error': 'EIO'}])
        self.assertEqual(leftovers, ['private.log', 'resource-manifest.json'])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'resource-manifest.json'
            calls.clear()
            with patch.object(os, 'fsync', side_effect=second_call_fails):
                self.assertIs(benchctl.write_manifest(path, {'run_id': RUN_12}), False)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['run_id'], RUN_12)
            self.assertIs(benchctl.write_manifest(path, {'run_id': RUN_12}), True)
            # A file fsync failure (here the second call overall) is still pre-commit.
            calls[:] = ['earlier call']
            with patch.object(os, 'fsync', side_effect=second_call_fails):
                with self.assertRaises(OSError):
                    benchctl.write_manifest(path, {'run_id': 'not-committed'})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'run_id': RUN_12})

    def test_r12_co_03_replacement_kept_when_every_directory_fsync_fails(self):
        real_fsync = os.fsync

        def directory_fsync_fails(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError(errno.EIO, 'Input/output error')
            return real_fsync(descriptor)
        manifest = full_manifest()
        name = manifest['containers']['gateway']
        with tempfile.TemporaryDirectory() as temp:
            results, _run_dir, log, path = self.manifest_dir(temp, manifest)
            with patch.object(benchctl, 'RESULTS', results), \
                    patch.object(benchctl, 'docker_inspect_json',
                                 return_value=owned_row('container', name, 'replacement-id')), \
                    patch.object(benchctl, 'run') as mutate, \
                    patch.object(benchctl.subprocess, 'run') as lookup, \
                    patch.object(benchctl.time, 'sleep'), \
                    patch.object(os, 'fsync', side_effect=directory_fsync_fails):
                benchctl.record_replacement_gateway(manifest, RUN_12, name, log)
            saved = json.loads(path.read_text(encoding='utf-8'))
        mutate.assert_not_called()
        lookup.assert_not_called()
        self.assertEqual(saved['created_resources']['container_gateway']['id'], 'replacement-id')
        self.assertNotIn('gateway_replacement_unrecorded', saved)
        self.assertTrue(saved['manifest_durability_uncertain'])

    def run_down(self, manifest, inspect):
        mutations = []

        def fake_run(argv, _logs, check=True):
            mutations.append(argv)
            return 0
        with tempfile.TemporaryDirectory() as temp:
            results, _run_dir, _log, path = self.manifest_dir(temp, manifest)
            with patch.object(benchctl, 'RESULTS', results), \
                    patch.object(benchctl, 'docker_inspect_json', side_effect=inspect), \
                    patch.object(benchctl, 'run', side_effect=fake_run), \
                    patch.object(benchctl.subprocess, 'run', return_value=fixture_done()), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = benchctl.manage(type('Args', (), {'command': 'down', 'run_id': RUN_12})())
            saved = json.loads(path.read_text(encoding='utf-8'))
        return code, saved, mutations

    def test_r12_co_03_down_treats_an_absent_recorded_object_as_removed(self):
        cases = [
            ('container_gateway', 'Error response from daemon: No such container: gone-id\n',
             0, 'stopped', 'already-absent'),
            ('container_gateway', 'Error: No such object: gone-id\n', 0, 'stopped', 'already-absent'),
            ('network_private', 'Error response from daemon: network gone-id not found\n',
             0, 'stopped', 'already-absent'),
            ('image', 'Error response from daemon: No such image: gone-id\n', 0, 'stopped', 'already-absent'),
            ('container_gateway', 'Cannot connect to the Docker daemon at unix:///run/fixture.sock\n',
             2, 'cleanup-failed', 'identity-or-ownership-mismatch-preserved'),
            ('container_gateway', 'Error response from daemon: No such container: other-id\n',
             2, 'cleanup-failed', 'identity-or-ownership-mismatch-preserved'),
        ]
        labels = {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': RUN_12}
        for role, stderr, code, status, role_status in cases:
            with self.subTest(role=role, stderr=stderr.strip()):
                manifest = full_manifest()
                manifest['created_resources']['container_gateway'] = {
                    'kind': 'container', 'name': manifest['containers']['gateway'],
                    'id': 'container_gateway-id', 'run_id': RUN_12, 'labels': dict(labels)}
                rows = {f'{name}-id': owned_row(row['kind'], row['name'], f'{name}-id')
                        for name, row in manifest['created_resources'].items()}
                manifest['created_resources'][role]['id'] = 'gone-id'

                def inspect(kind, ref, stderr=stderr, rows=rows):
                    if ref == 'gone-id':
                        raise subprocess.CalledProcessError(1, ['docker', kind, 'inspect', ref],
                                                            output='[]\n', stderr=stderr)
                    return rows[ref]
                result, saved, mutations = self.run_down(manifest, inspect)
                self.assertEqual(result, code)
                self.assertEqual(saved['status'], status)
                self.assertEqual(saved['cleanup'][role], role_status)
                self.assertFalse(any('gone-id' in argv for argv in mutations))
                self.assertIn(['docker', 'stop', '--time', '10', 'container_agent-id'], mutations)

    def test_r12_co_03_down_inspection_timeout_preserves_only_that_resource(self):
        manifest = full_manifest()
        rows = {f'{role}-id': owned_row(row['kind'], row['name'], f'{role}-id')
                for role, row in manifest['created_resources'].items()}

        def inspect(kind, ref):
            if ref == 'container_github-id':
                raise subprocess.TimeoutExpired(['docker', kind, 'inspect', ref], 20)
            return rows[ref]
        code, saved, mutations = self.run_down(manifest, inspect)
        self.assertEqual(code, 2)
        self.assertEqual(saved['status'], 'cleanup-failed')
        self.assertEqual(saved['cleanup']['container_github'], 'inspection-failed-preserved')
        self.assertFalse(any('container_github-id' in argv for argv in mutations))
        self.assertIn(['docker', 'rm', 'container_agent-id'], mutations)



class Pass13GatewayLogDamageTest(unittest.TestCase):
    """The gateway prints only JSON objects; a damaged line is evidence, never skipped."""

    def read(self, function, stdout):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                benchctl.subprocess, 'run', return_value=type('Result', (), {'returncode': 0, 'stdout': stdout})()):
            return function('gateway', Path(temp) / 'log')

    def test_damaged_lines_fail_the_zero_request_and_policy_checks(self):
        ready = json.dumps({'event': 'ready'}) + '\n'
        for damage in ('{"event":"forward-started","request_id":"r1"', 'Traceback (most recent call last):',
                       '[1, 2]', '"forwarded"'):
            with self.subTest(damage=damage):
                stdout = ready + damage + '\n'
                self.assertEqual(self.read(benchctl.gateway_forward_count, stdout), 1)
                self.assertEqual(self.read(benchctl.gateway_rejection_count, stdout), 1)
        self.assertEqual(self.read(benchctl.gateway_forward_count, ready + '\n'), 0)
        self.assertEqual(self.read(benchctl.gateway_rejection_count, ready), 0)

    def test_damaged_line_makes_model_observations_unverified(self):
        wire = 'openai'
        lines = [{'event': 'forward-started', 'request_kind': 'inference', 'provider': wire,
                  'request_id': 'r0'},
                 {'event': 'forwarded', 'request_kind': 'inference', 'provider': wire,
                  'request_id': 'r0', 'model': 'expected-model', 'status': 200,
                  'response_model_ids': ['canonical-model'], 'response_complete': True,
                  'usage': {'input_tokens': 3, 'output_tokens': 5}}]
        clean = ''.join(json.dumps(line) + '\n' for line in lines)
        for stdout, verified in ((clean, True), (clean + '{"event":"forwarded","request_id":"r1"\n', False)):
            with self.subTest(verified=verified), tempfile.TemporaryDirectory() as temp, patch.object(
                    benchctl.subprocess, 'run',
                    return_value=type('Done', (), {'stdout': stdout, 'returncode': 0})()):
                result = benchctl.gateway_model_observations(
                    'gateway', 'expected-model', 'codex', Path(temp) / 'private.log', 'canonical-model')
            self.assertIs(result['verified'], verified)
            self.assertIs(result['usage_complete'], verified)
            self.assertEqual(result['damaged_log_lines'], 0 if verified else 1)
            if not verified:
                self.assertEqual(result['reason'], 'gateway log has damaged lines')


class FakeDocker:
    """Stateful fixture Docker: label/name lookups, inspection and removal agree."""

    KINDS = {'ps': 'container', 'network': 'network', 'image': 'image'}

    def __init__(self, objects=(), lookups_fail=False, stuck=()):
        self.objects = {identity: (kind, name, run_id) for identity, kind, name, run_id in objects}
        self.lookups_fail = lookups_fail
        self.stuck = set(stuck)
        self.lookups, self.mutations = [], []

    def subprocess_run(self, argv, **_kwargs):
        if argv[:2] == ['docker', 'logs']:
            return fixture_done()
        kind = self.KINDS[argv[1]]
        self.lookups.append(argv)
        if self.lookups_fail:
            raise subprocess.TimeoutExpired(argv, 20)
        run_id = next(item.split('=', 2)[2] for item in argv
                      if item.startswith('label=io.t3.issue28.run='))
        name = listed_name(argv)
        found = [identity for identity, (k, n, r) in self.objects.items()
                 if k == kind and r == run_id and name in (None, n)]
        return fixture_done(stdout=''.join(identity + '\n' for identity in found))

    def run(self, argv, _logs, check=True):
        self.mutations.append(argv)
        identity = argv[-1]
        if argv[1] == 'stop':
            return 0 if identity in self.objects else 1
        if identity in self.stuck or identity not in self.objects:
            return 1
        del self.objects[identity]
        return 0

    def inspect(self, kind, ref):
        for identity, (k, name, run_id) in self.objects.items():
            if k == kind and ref in (identity, name):
                return owned_row(kind, name, identity, run_id)
        raise subprocess.CalledProcessError(1, ['docker', kind, 'inspect', ref], output='[]\n',
                                            stderr=f'Error: No such object: {ref}\n')


def recorded_objects(manifest):
    return [(row['id'], row['kind'], row['name'], manifest['run_id'])
            for row in manifest.get('created_resources', {}).values()]


class Pass14ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 14 repairs of review 13 container findings and the gate sweep."""

    canary_tree = Pass12ContainerRepairTest.canary_tree
    scope = Pass12ContainerRepairTest.scope
    run_helper = Pass12ContainerRepairTest.run_helper
    manifest_dir = Pass12ContainerRepairTest.manifest_dir
    seeded_canary_tree = Pass13ContainerRepairTest.seeded_canary_tree
    drive_setup = Pass13ContainerRepairTest.drive_setup

    # R13-CO-01: mode and ownership are part of every inventoried entry and the root.

    def test_r13_co_01_out_of_scope_mode_change_fails_scope(self):
        cases = {'chmod 0555 .git': ('.git', 0o555), 'chmod workspace root': ('.', 0o711),
                 'chmod Git file': ('.git/config', 0o600),
                 'chmod Git subdirectory': ('.git/refs/tags', 0o700)}
        for label, (relative, mode) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                workspace, _results, inputs, _digest = self.seeded_canary_tree(temp)
                target = workspace / relative
                original = stat.S_IMODE(target.stat().st_mode)
                self.assertNotEqual(original, mode)
                before = benchctl.workspace_inventory(workspace)
                self.run_helper(workspace, inputs / 'brief.txt',
                                workspace / 'canary' / 'codex' / 'task-1' / 'helper.json')
                self.assertTrue(self.scope(workspace, before))
                target.chmod(mode)
                try:
                    self.assertTrue(benchctl.helper_output_valid(
                        workspace, 'codex', inputs / 'brief.sha256', ['codex']))
                    changes = benchctl.workspace_changes_since(workspace, before)
                    self.assertFalse(benchctl.workspace_write_scope_valid(workspace, changes, 'codex'))
                    self.assertIn(relative, [change['path'] for change in changes
                                             if change['kind'] == 'modified'])
                finally:
                    target.chmod(original)

    def test_r13_co_01_out_of_scope_ownership_change_fails_scope(self):
        # A test process cannot chown, so the baseline records a different owner instead.
        for relative, field in (('.', 'uid'), ('.git', 'gid'), ('.git/config', 'uid')):
            with self.subTest(path=relative, field=field), tempfile.TemporaryDirectory() as temp:
                workspace, _results, inputs, _digest = self.seeded_canary_tree(temp)
                before = benchctl.workspace_inventory(workspace)
                self.assertEqual(before[relative][field],
                                 getattr(os.lstat(workspace / relative), 'st_' + field))
                before[relative] = dict(before[relative], **{field: before[relative][field] + 1})
                self.run_helper(workspace, inputs / 'brief.txt',
                                workspace / 'canary' / 'codex' / 'task-1' / 'helper.json')
                self.assertFalse(self.scope(workspace, before))

    def test_r13_co_01_hard_link_to_out_of_scope_file_fails_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _results, inputs, _digest = self.seeded_canary_tree(temp)
            before = benchctl.workspace_inventory(workspace)
            assigned = workspace / 'canary' / 'codex' / 'task-1'
            self.run_helper(workspace, inputs / 'brief.txt', assigned / 'helper.json')
            os.link(workspace / '.git' / 'config', assigned / 'config-link')
            changes = benchctl.workspace_changes_since(workspace, before)
            self.assertFalse(benchctl.workspace_write_scope_valid(workspace, changes, 'codex'))
            self.assertIn('.git/config', [change['path'] for change in changes])

    def test_r13_co_01_inside_assigned_only_the_helper_output_may_change(self):
        def tree(temp):
            workspace, _results, inputs, _digest = self.seeded_canary_tree(temp)
            assigned = workspace / 'canary' / 'codex' / 'task-1'
            (assigned / 'notes').mkdir(parents=True)
            (assigned / 'notes' / 'other.txt').write_text('earlier\n', encoding='utf-8')
            (assigned / 'helper.json').write_text('{"stale": true}\n', encoding='utf-8')
            before = benchctl.workspace_inventory(workspace)
            self.run_helper(workspace, inputs / 'brief.txt', assigned / 'helper.json')
            return workspace, assigned, before
        with tempfile.TemporaryDirectory() as temp:
            workspace, assigned, before = tree(temp)
            (assigned / 'helper.json').chmod(0o600)
            (assigned / 'added.txt').write_text('new\n', encoding='utf-8')
            # The helper output's own content and mode may change; new entries may appear.
            self.assertTrue(self.scope(workspace, before))
        cases = {'chmod existing directory': lambda a: (a / 'notes').chmod(0o700),
                 'rewrite existing file': lambda a: (a / 'notes' / 'other.txt').write_text(
                     'changed\n', encoding='utf-8'),
                 'chmod existing file': lambda a: (a / 'notes' / 'other.txt').chmod(0o600),
                 'chmod assigned directory': lambda a: a.chmod(0o700)}
        for label, mutate in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                workspace, assigned, before = tree(temp)
                mutate(assigned)
                self.assertFalse(self.scope(workspace, before))

    def test_r13_co_01_smoke_snapshot_records_mode_owner_and_root(self):
        assigned, output = Path('smoke/task-1'), Path('smoke/task-1/result.json')

        def tree(temp):
            workspace = Path(temp)
            (workspace / '.git').mkdir()
            (workspace / '.git' / 'config').write_text('[core]\n', encoding='utf-8')
            (workspace / 'smoke' / 'task-1').mkdir(parents=True)
            (workspace / 'smoke' / 'task-1' / 'earlier.txt').write_text('x\n', encoding='utf-8')
            (workspace / output).write_text('{}\n', encoding='utf-8')
            before = smoke.workspace_snapshot(workspace)
            (workspace / output).write_text('{"input_sha256": "x"}\n', encoding='utf-8')
            return workspace, before
        with tempfile.TemporaryDirectory() as temp:
            workspace, before = tree(temp)
            after = smoke.workspace_snapshot(workspace)
            self.assertIn(Path('.'), after)
            self.assertTrue(smoke.assigned_workspace_changes_confined(before, after, assigned, output))
        cases = {'chmod 0555 .git': lambda ws: (ws / '.git').chmod(0o555),
                 'chmod workspace root': lambda ws: ws.chmod(0o711),
                 'chmod Git file': lambda ws: (ws / '.git' / 'config').chmod(0o600),
                 'hard link to Git file': lambda ws: os.link(ws / '.git' / 'config',
                                                             ws / 'smoke' / 'task-1' / 'link'),
                 'rewrite earlier assigned file': lambda ws: (ws / 'smoke' / 'task-1' / 'earlier.txt')
                 .write_text('y\n', encoding='utf-8')}
        for label, mutate in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                workspace, before = tree(temp)
                root_mode = stat.S_IMODE(workspace.stat().st_mode)
                git_mode = stat.S_IMODE((workspace / '.git').stat().st_mode)
                mutate(workspace)
                try:
                    self.assertFalse(smoke.assigned_workspace_changes_confined(
                        before, smoke.workspace_snapshot(workspace), assigned, output))
                finally:
                    workspace.chmod(root_mode)
                    (workspace / '.git').chmod(git_mode)

    @unittest.skipIf(os.geteuid() == 0, 'root bypasses file permissions')
    def test_r13_co_01_smoke_rejects_an_unreadable_entry_outside_the_assigned_path(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            hidden = workspace / 'hidden'
            hidden.write_text('content the smoke cannot compare\n', encoding='utf-8')
            hidden.chmod(0)
            try:
                before = smoke.workspace_snapshot(workspace)
                (workspace / 'smoke' / 'task-1').mkdir(parents=True)
                (workspace / 'smoke' / 'task-1' / 'result.json').write_text('{}\n', encoding='utf-8')
                self.assertFalse(smoke.assigned_workspace_changes_confined(
                    before, smoke.workspace_snapshot(workspace), Path('smoke/task-1')))
            finally:
                hidden.chmod(0o600)

    # R13-CO-02: unrecorded resources stay recoverable until down confirms absence.

    def down(self, run_dir, docker):
        with patch.object(benchctl, 'RESULTS', run_dir.parent), \
                patch.object(benchctl, 'docker_inspect_json', side_effect=docker.inspect), \
                patch.object(benchctl, 'run', side_effect=docker.run), \
                patch.object(benchctl.subprocess, 'run', side_effect=docker.subprocess_run), \
                contextlib.redirect_stdout(io.StringIO()):
            code = benchctl.manage(type('Args', (), {'command': 'down', 'run_id': run_dir.name})())
        return code, json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))

    def test_r13_co_02_lookup_timeout_at_up_is_reconciled_by_a_later_down(self):
        def inspect(kind, ref):
            if kind == 'image':
                raise subprocess.CalledProcessError(1, ['docker', 'image', 'inspect', ref],
                                                    stderr='Cannot connect to the Docker daemon\n')
            return name_owned_row(kind, ref)

        def lookup(argv):
            raise subprocess.TimeoutExpired(argv, 20)
        with tempfile.TemporaryDirectory() as temp:
            error, run_dir, commands, _listings = self.drive_setup(temp, inspect=inspect, lookup=lookup)
            run_id = run_dir.name
            image = 't3-issue28-s1b:' + run_id
            labels = {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': run_id}
            self.assertIn('image identity could not be recorded; cleanup incomplete, inspect run labels',
                          str(error))
            self.assertNotIn('receipt was not saved', str(error))
            self.assertEqual(commands[-1][:2], ['docker', 'build'])
            saved = json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(saved.get('created_resources', {}), {})
            self.assertEqual(saved['unrecorded_resources']['image'], {
                'cleanup_by': 'run labels and exact name', 'kind': 'image', 'name': image,
                'run_id': run_id, 'labels': labels, 'lookup_succeeded': False,
                'matched': 0, 'matched_ids': [], 'removed': 0, 'removed_ids': []})
            self.assertEqual(saved['pending_resources']['image'],
                             {'kind': 'image', 'name': image, 'run_id': run_id, 'labels': labels})
            orphan = 'sha256:' + 'a' * 64
            docker = FakeDocker([(orphan, 'image', image, run_id)], lookups_fail=True)
            # The daemon is still unreachable: down cannot confirm anything.
            code, saved = self.down(run_dir, docker)
            self.assertEqual((code, saved['status']), (2, 'cleanup-failed'))
            self.assertFalse(saved['unrecorded_cleanup']['image']['absence_confirmed'])
            # Lookup recovers but removal fails: still not stopped.
            docker.lookups_fail, docker.stuck = False, {orphan}
            code, saved = self.down(run_dir, docker)
            self.assertEqual((code, saved['status']), (2, 'cleanup-failed'))
            self.assertEqual(saved['unrecorded_cleanup']['image']['matched_ids'], [orphan])
            self.assertEqual(saved['unrecorded_cleanup']['image']['remaining_ids'], [orphan])
            self.assertIn(orphan, docker.objects)
            # Removal works: the orphan is removed, absence confirmed, and only now stopped.
            docker.stuck.clear()
            code, saved = self.down(run_dir, docker)
        self.assertEqual((code, saved['status']), (0, 'stopped'))
        self.assertNotIn(orphan, docker.objects)
        self.assertIn(['docker', 'image', 'rm', orphan], docker.mutations)
        receipt = saved['unrecorded_cleanup']['image']
        self.assertEqual((receipt['removed_ids'], receipt['remaining_ids'], receipt['absence_confirmed']),
                         ([orphan], [], True))
        self.assertTrue(saved['labelled_leftovers']['absence_confirmed'])
        for argv in docker.lookups:
            self.assertIn(f'label=io.t3.issue28.run={run_id}', argv)

    def test_r13_co_02_unsaved_receipt_keeps_write_ahead_authority_for_down(self):
        def lookup(argv):
            raise subprocess.TimeoutExpired(argv, 20)
        with tempfile.TemporaryDirectory() as temp:
            error, run_dir, _commands, _listings = self.drive_setup(
                temp, persist_fail_role='container_agent', lookup=lookup)
            run_id = run_dir.name
            agent = 't3-issue28-agent-' + run_id
            self.assertIn('cleanup incomplete, inspect run labels; cleanup receipt was not saved', str(error))
            saved = json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))
            self.assertNotIn('container_agent', saved['created_resources'])
            self.assertEqual(saved['unrecorded_resources'], {})
            self.assertEqual(saved['pending_resources'], {'container_agent': {
                'kind': 'container', 'name': agent, 'run_id': run_id,
                'labels': {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': run_id}}})
            docker = FakeDocker([*recorded_objects(saved), ('orphan-agent-id', 'container', agent, run_id)])
            code, saved = self.down(run_dir, docker)
        self.assertEqual((code, saved['status']), (0, 'stopped'))
        self.assertEqual(docker.objects, {})
        self.assertIn(['docker', 'rm', '--force', 'orphan-agent-id'], docker.mutations)
        # The orphan container goes before the networks it is attached to.
        self.assertLess(docker.mutations.index(['docker', 'rm', '--force', 'orphan-agent-id']),
                        docker.mutations.index(['docker', 'network', 'rm',
                                                f't3-issue28-private-{run_id}-id']))

    def test_r13_co_02_unrecorded_replacement_gateway_is_reconciled_by_down(self):
        manifest = full_manifest()
        name = manifest['containers']['gateway']
        with tempfile.TemporaryDirectory() as temp:
            results, run_dir, log, path = self.manifest_dir(temp, manifest)
            with patch.object(benchctl, 'RESULTS', results), \
                    patch.object(benchctl, 'record_created', side_effect=RuntimeError('inspect failed')), \
                    patch.object(benchctl, 'run') as mutate, \
                    patch.object(benchctl.subprocess, 'run',
                                 side_effect=subprocess.TimeoutExpired('docker', 20)), \
                    patch.object(benchctl.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'cleanup incomplete, inspect run labels$'):
                    benchctl.record_replacement_gateway(manifest, RUN_12, name, log)
            mutate.assert_not_called()
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['gateway_replacement_unrecorded']['name'], name)
            self.assertFalse(saved['gateway_replacement_unrecorded']['lookup_succeeded'])
            docker = FakeDocker([*recorded_objects(saved), ('orphan-gateway-id', 'container', name, RUN_12)],
                                stuck={'orphan-gateway-id'})
            code, saved = self.down(run_dir, docker)
            self.assertEqual((code, saved['status']), (2, 'cleanup-failed'))
            self.assertEqual(saved['cleanup']['container_gateway'], 'not-created-no-cleanup-authority')
            self.assertEqual(saved['labelled_leftovers']['remaining_ids'],
                             {'container': ['orphan-gateway-id']})
            docker.stuck.clear()
            code, saved = self.down(run_dir, docker)
        self.assertEqual((code, saved['status']), (0, 'stopped'))
        self.assertEqual(docker.objects, {})
        self.assertTrue(saved['unrecorded_cleanup']['container_gateway']['absence_confirmed'])

    def test_r13_co_02_receipt_outside_run_scope_blocks_down(self):
        for key, entry in (('unrecorded_resources', {'image': {'kind': 'image', 'name': 'other:tag'}}),
                           ('pending_resources', {'container_agent': {
                               'kind': 'container', 'name': f't3-issue28-agent-{RUN_12}',
                               'run_id': RUN_12, 'labels': {'io.t3.issue28.stage': 's1b',
                                                            'io.t3.issue28.run': 'other-run'}}}),
                           ('pending_resources', {'container_probe': {'kind': 'container'}}),
                           ('gateway_replacement_unrecorded', {'kind': 'network'})):
            with self.subTest(key=key, entry=entry), tempfile.TemporaryDirectory() as temp:
                manifest = dict(full_manifest(), **{key: entry})
                _results, run_dir, _log, _path = self.manifest_dir(temp, manifest)
                docker = FakeDocker(recorded_objects(manifest))
                with self.assertRaisesRegex(RuntimeError, 'run scope or schema validation'):
                    self.down(run_dir, docker)
                self.assertEqual(docker.mutations, [])

    def test_r13_co_02_unnamed_labelled_leftover_keeps_cleanup_failed(self):
        manifest = full_manifest()
        with tempfile.TemporaryDirectory() as temp:
            _results, run_dir, _log, _path = self.manifest_dir(temp, manifest)
            docker = FakeDocker([*recorded_objects(manifest),
                                 ('probe-id', 'container', 'interrupted-probe', RUN_12)])
            code, saved = self.down(run_dir, docker)
        self.assertEqual((code, saved['status']), (2, 'cleanup-failed'))
        self.assertEqual(saved['labelled_leftovers']['remaining_ids'], {'container': ['probe-id']})
        # Looking is not authority: nothing without a record or exact-name scope is removed.
        self.assertIn('probe-id', docker.objects)
        self.assertFalse(any('probe-id' in argv for argv in docker.mutations))

    def test_r13_co_02_nothing_is_created_when_the_intent_cannot_be_committed(self):
        manifest = {'run_id': RUN_12, 'created_resources': {}}
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(benchctl, 'write_manifest', side_effect=OSError(28, 'No space left on device')), \
                patch.object(benchctl, 'run') as create:
            with self.assertRaises(OSError):
                benchctl.create_owned(manifest, lambda: Path(temp) / 'manifest.json', 'network',
                                      'network_private', f't3-issue28-private-{RUN_12}',
                                      ['docker', 'network', 'create', 'fixture'], Path(temp) / 'log')
        create.assert_not_called()

    def test_r13_co_02_failed_identity_write_keeps_the_intent(self):
        name = f't3-issue28-gateway-{RUN_12}'
        manifest = full_manifest()
        benchctl.declare_pending(manifest, 'container_gateway', 'container', name)
        intent = dict(manifest['pending_resources']['container_gateway'])
        with tempfile.TemporaryDirectory() as temp:
            _results, _run_dir, log, path = self.manifest_dir(temp, manifest)
            with patch.object(benchctl, 'docker_inspect_json',
                              return_value=owned_row('container', name, 'replacement-id')):
                with patch.object(os, 'replace', side_effect=OSError(28, 'No space left on device')):
                    with self.assertRaises(OSError):
                        benchctl.record_created(manifest, path, 'container', 'container_gateway', name, log)
                self.assertEqual(manifest['pending_resources'], {'container_gateway': intent})
                benchctl.record_created(manifest, path, 'container', 'container_gateway', name, log)
            saved = json.loads(path.read_text(encoding='utf-8'))
        # The identity and the cleared intent are committed together.
        self.assertEqual(saved['pending_resources'], {})
        self.assertEqual(saved['created_resources']['container_gateway']['id'], 'replacement-id')

    # Gate sweep: absent evidence never passes.

    def test_sweep_unavailable_container_logs_are_not_zero(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                benchctl.subprocess, 'run', return_value=fixture_done(returncode=1)):
            log = Path(temp) / 'log'
            self.assertIsNone(benchctl.gateway_forward_count('gateway', log))
            self.assertIsNone(benchctl.gateway_rejection_count('gateway', log))
            self.assertIsNone(benchctl.github_event_count('github', log))
        self.assertIsNone(benchctl.count_delta(None, 0))
        self.assertIsNone(benchctl.count_delta(3, None))
        self.assertEqual(benchctl.count_delta(3, 1), 2)

    def test_sweep_smoke_fails_when_the_gateway_log_is_unavailable(self):
        printed = '\n'.join(json.dumps({'probe': name, 'passed': True})
                            for name in benchctl.SMOKE_REQUIRED_PROBES)

        def fake(argv, **_kwargs):
            if argv[:2] == ['docker', 'exec']:
                return fixture_done(stdout=printed)
            return fixture_done(returncode=1)  # `docker logs` failed.
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / RUN_12
            run_dir.mkdir(mode=0o700)
            Path(temp).chmod(0o700)
            (run_dir / 'private.log').touch(mode=0o600)
            manifest = {'run_id': RUN_12, 'containers': {'agent': 'agent', 'gateway': 'gateway'}}
            (run_dir / 'resource-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(benchctl, 'RESULTS', Path(temp)), \
                    patch.object(benchctl.subprocess, 'run', side_effect=fake), \
                    patch('sys.stdout', io.StringIO()):
                code = benchctl.manage(type('Args', (), {'command': 'smoke', 'run_id': RUN_12})())
            saved = json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(saved['smoke_network_controls']['paired_controls_passed'])
        self.assertIsNone(saved['smoke_model_requests'])
        self.assertFalse(saved['smoke_passed'])
        self.assertEqual(code, 2)

    def test_sweep_canary_is_blocked_before_slot_use_without_log_baselines(self):
        targets = {'codex': {'providerInstanceId': 'codex', 'model': 'fixture-openai', 'options': {}},
                   'claudeAgent': {'providerInstanceId': 'claudeAgent', 'model': 'fixture-anthropic',
                                   'options': {}}}
        hosts = {'codex': 'api.openai.com', 'claudeAgent': 'api.anthropic.com'}
        identities = {provider: {'provider_instance_id': provider, 'requested_model_id': target['model'],
                                 'source': f'https://{hosts[provider]}/v1/models/{target["model"]}',
                                 'http_status': 200, 'response_model_id': target['model'],
                                 'observed_at': '2026-10-13T00:00:00Z', 'response_sha256': 'a' * 64}
                      for provider, target in targets.items()}
        hashes = {name: hashlib.sha256((CONTAINER / name).read_bytes()).hexdigest()
                  for name in benchctl.SOURCE_FILES}
        hashes['model_policy.py'] = hashlib.sha256(
            (ROOT / 'bench' / 'v2' / 'tools' / 'model_policy.py').read_bytes()).hexdigest()
        manifest = {'run_id': RUN_12, 'status': 'catalog-locked', 'smoke_passed': True,
                    'observer_boundary_preflight': {'status': 'passed',
                                                    'literal_provider_network_verified': True,
                                                    'native_binary_resolution': {'verified': True}},
                    'canary_attempts': [], 'runtime_targets': targets,
                    'response_identity_metadata': {'identities': identities},
                    'build_source_sha256': hashes,
                    'created_resources': {'container_agent': {'id': 'agent-id'}},
                    'containers': {'agent': 'agent', 'gateway': 'gateway', 'github': 'github'}}
        for unavailable in ('github', 'gateway'):
            def fake(argv, unavailable=unavailable, **_kwargs):
                return fixture_done(returncode=1 if argv[-1] == unavailable else 0)
            with self.subTest(unavailable=unavailable), tempfile.TemporaryDirectory() as temp:
                _results, run_dir, _log, path = self.manifest_dir(temp, manifest)
                with patch.object(benchctl, 'RESULTS', run_dir.parent), \
                        patch.object(benchctl, 'read_native_launches', return_value=[]), \
                        patch.object(benchctl, 'driver') as dispatch, \
                        patch.object(benchctl.subprocess, 'run', side_effect=fake):
                    with self.assertRaisesRegex(RuntimeError, 'log baseline is unavailable'):
                        benchctl.manage(type('Args', (), {'command': 'canary', 'run_id': RUN_12,
                                                          'provider': 'codex'})())
                saved = json.loads(path.read_text(encoding='utf-8'))
                dispatch.assert_not_called()
                self.assertEqual(saved['canary_attempts'], [])

    def test_sweep_preflight_needs_every_named_check_exactly_true(self):
        observed = {'native_process_profile_checks': {name: True for name in benchctl.PROFILE_CHECKS},
                    'native_cli_checks': {'claude': True, 'codex': True},
                    'native_binary_resolution': {'verified': True}}
        self.assertTrue(benchctl.preflight_profile_verified(observed))
        missing = dict(observed, native_process_profile_checks={})
        partial = dict(observed, native_process_profile_checks={'uid_is_worker': True})
        truthy = dict(observed, native_cli_checks={'claude': 1, 'codex': True})
        no_cli = dict(observed, native_cli_checks={})
        for label, case in (('empty profile', missing), ('partial profile', partial),
                            ('truthy non-boolean', truthy), ('no CLI checks', no_cli)):
            with self.subTest(case=label):
                self.assertFalse(benchctl.preflight_profile_verified(case))


class Pass14ParentSweepTest(unittest.TestCase):
    def test_unavailable_gateway_log_is_an_unverified_audit_not_an_exception(self):
        for failure in (type('Failed', (), {'stdout': 'Error: No such container', 'returncode': 1})(),
                        subprocess.TimeoutExpired(['docker', 'logs'], 20)):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as temp, \
                    patch.object(benchctl.subprocess, 'run',
                                 side_effect=failure if isinstance(failure, Exception) else None,
                                 return_value=None if isinstance(failure, Exception) else failure):
                result = benchctl.gateway_model_observations(
                    'gateway', 'expected-model', 'codex', Path(temp) / 'private.log', 'canonical-model')
            self.assertIs(result['verified'], False)
            self.assertIs(result['usage_complete'], False)
            self.assertEqual(result['reason'], 'gateway log unavailable')

    def test_hung_docker_cleanup_command_is_a_failure_not_a_hang(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                benchctl.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['docker', 'rm'], 1)):
            log = Path(temp) / 'log'
            self.assertEqual(benchctl.run(['docker', 'rm', 'x'], log, check=False, timeout=1), 124)
            with self.assertRaises(RuntimeError):
                benchctl.run(['docker', 'rm', 'x'], log, timeout=1)
            self.assertIn('timed out', log.read_text())
        seen = []
        def fake(args, **kwargs):
            seen.append((args[:3], kwargs.get('timeout')))
            return type('Done', (), {'returncode': 0})()
        with tempfile.TemporaryDirectory() as temp, patch.object(benchctl.subprocess, 'run', side_effect=fake):
            log = Path(temp) / 'log'
            for argv in (['docker', 'stop', 'x'], ['docker', 'rm', 'x'], ['docker', 'network', 'rm', 'x'],
                         ['docker', 'image', 'rm', 'x'], ['docker', 'build', '.']):
                benchctl.run(argv, log, check=False)
        self.assertEqual([timeout for _, timeout in seen],
                         [benchctl.DOCKER_CLEANUP_TIMEOUT] * 4 + [None])


RUN_ID_PATTERN = re.compile(r'\d{8}T\d{6}Z-[0-9a-f]{6}$')
ACTOR_TASKS = {'task-primary': 'child-primary', 'task-32767': 'child-b1',
               'task-32768': 'child-b2', 'task-32769': 'child-b3'}
CANARY_TARGET = {'providerInstanceId': 'codex', 'model': 'fixture-openai', 'options': {}}


def role_dispatch_records():
    """Captured `delegate_task` inputs carrying the honest frozen role assignment literals."""
    templates = benchctl.canary_task_templates('codex')
    records = [{'threadId': 'parent', 'status': 'completed', 'toolName': 't3-code.delegate_task',
                'input': {'target': CANARY_TARGET, 'role': 'worker', 'task': templates['primary']},
                'output': {'taskId': 'task-primary'}}]
    for size in (32767, 32768, 32769):
        records.append({'threadId': 'parent', 'status': 'completed',
                        'toolName': 't3-code.delegate_task',
                        'input': {'target': CANARY_TARGET, 'role': 'worker',
                                  'task': templates[f'summary-{size}']},
                        'output': {'taskId': f'task-{size}'}})
    return records


def actor_observation(helper_threads=('child-primary',), file_change_threads=(),
                      primary_status_child='child-primary', primary_owner='parent', exit_code=0,
                      dispatches=None):
    """Host observations: a parent, four app children, a native probe and a grandchild."""
    command = benchctl.helper_command('codex')
    subagents = [{'threadId': primary_owner if task == 'task-primary' else 'parent', 'id': task,
                  'childThreadId': child, 'origin': 'app_owned'}
                 for task, child in ACTOR_TASKS.items()]
    subagents += [{'threadId': 'parent', 'id': 'native-1', 'childThreadId': 'child-native',
                   'origin': 'provider_native',
                   'prompt': benchctl.canary_task_templates('codex')['native-probe']},
                  {'threadId': 'child-primary', 'id': 'grandchild', 'childThreadId': 'child-grand',
                   'origin': 'app_owned'}]
    statuses = [{'toolName': 't3-code.task_status', 'input': {'taskId': task},
                 'output': {'taskId': task, 'status': 'completed',
                            'childThreadId': primary_status_child if task == 'task-primary' else child}}
                for task, child in ACTOR_TASKS.items()]
    return {'parent_thread_id': 'parent',
            'tool_records': (role_dispatch_records() if dispatches is None else dispatches) + statuses,
            'subagents': subagents,
            'runs': [], 'runtime_requests': [], 'threads': [],
            'commands': [{'id': f'command-{index}', 'threadId': thread, 'status': 'completed',
                          'exitCode': exit_code, 'input': f"/bin/bash -lc '{command}'"}
                         for index, thread in enumerate(helper_threads)],
            'file_changes': [{'id': f'change-{index}', 'threadId': thread, 'status': 'completed'}
                             for index, thread in enumerate(file_change_threads)]}


class Pass15ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 15 repairs of review 14 container findings and the gate sweep."""

    manifest_dir = Pass12ContainerRepairTest.manifest_dir
    drive_setup = Pass13ContainerRepairTest.drive_setup
    down = Pass14ContainerRepairTest.down

    # R14-CO-01: a crash after any write-ahead intent leaves a manifest down accepts.

    def crash_setup(self, temp, role, created):
        """Kill setup at `role`'s create command, before or after Docker made the object."""
        docker = FakeDocker()
        kind, prefix = SETUP_ROLES[role]

        def crash(_argv, name):
            if name and name.startswith(prefix):
                if created:
                    docker.objects[name + '-orphan'] = (kind, name, RUN_ID_PATTERN.search(name).group(0))
                raise ControllerCrash(role)
        error, run_dir, commands, _listings = self.drive_setup(temp, crash=crash)
        self.assertIsInstance(error, ControllerCrash)
        saved = json.loads((run_dir / 'resource-manifest.json').read_text(encoding='utf-8'))
        docker.objects.update({identity: (kind, name, run_id)
                               for identity, kind, name, run_id in recorded_objects(saved)})
        return run_dir, saved, docker, commands

    def test_r14_co_01_crash_after_first_image_intent_is_cleaned_by_down(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, saved, docker, commands = self.crash_setup(temp, 'image', created=True)
            run_id = run_dir.name
            image = 't3-issue28-s1b:' + run_id
            orphan = image + '-orphan'
            labels = {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': run_id}
            self.assertEqual(commands[-1][:2], ['docker', 'build'])
            # The committed manifest is the first-image intent and nothing else.
            self.assertEqual(saved['status'], 'preparing')
            self.assertEqual(saved['created_resources'], {})
            self.assertEqual(saved['unrecorded_resources'], {})
            self.assertEqual(saved['pending_resources'], {'image': {
                'kind': 'image', 'name': image, 'run_id': run_id, 'labels': labels}})
            self.assertEqual(docker.objects, {orphan: ('image', image, run_id)})
            # Removal fails, then the daemon is unreachable: never stopped.
            docker.stuck = {orphan}
            code, saved = self.down(run_dir, docker)
            self.assertEqual((code, saved['status']), (2, 'cleanup-failed'))
            self.assertEqual(saved['unrecorded_cleanup']['image']['remaining_ids'], [orphan])
            docker.stuck.clear()
            docker.lookups_fail = True
            code, saved = self.down(run_dir, docker)
            self.assertEqual((code, saved['status']), (2, 'cleanup-failed'))
            self.assertIn(orphan, docker.objects)
            # Only once the labelled image is removed and confirmed absent is the run stopped.
            docker.lookups_fail = False
            code, saved = self.down(run_dir, docker)
        self.assertEqual((code, saved['status']), (0, 'stopped'))
        self.assertEqual(docker.objects, {})
        self.assertIn(['docker', 'image', 'rm', orphan], docker.mutations)
        receipt = saved['unrecorded_cleanup']['image']
        self.assertEqual((receipt['removed_ids'], receipt['remaining_ids'], receipt['absence_confirmed']),
                         ([orphan], [], True))
        self.assertTrue(saved['labelled_leftovers']['absence_confirmed'])
        for argv in docker.lookups:
            self.assertIn(f'label=io.t3.issue28.run={run_id}', argv)

    def test_r14_co_01_pending_only_manifest_without_created_map_is_accepted(self):
        # A manifest committed by a controller that never wrote the created map.
        with tempfile.TemporaryDirectory() as temp:
            run_dir, saved, docker, _commands = self.crash_setup(temp, 'image', created=True)
            for key in ('created_resources', 'unrecorded_resources'):
                del saved[key]
            (run_dir / 'resource-manifest.json').write_text(json.dumps(saved), encoding='utf-8')
            code, saved = self.down(run_dir, docker)
        self.assertEqual((code, saved['status']), (0, 'stopped'))
        self.assertEqual(docker.objects, {})
        self.assertTrue(saved['unrecorded_cleanup']['image']['absence_confirmed'])

    def test_r14_co_01_malformed_recovery_maps_still_block_down(self):
        for key, value in (('created_resources', []), ('pending_resources', [])):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                run_dir, saved, docker, _commands = self.crash_setup(temp, 'image', created=True)
                saved[key] = value
                (run_dir / 'resource-manifest.json').write_text(json.dumps(saved), encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'run scope or schema validation'):
                    self.down(run_dir, docker)
                self.assertEqual(docker.mutations, [])

    # Sweep: every committed setup, configure_gateway and down state keeps full authority.

    def test_sweep_crash_at_each_setup_create_leaves_down_full_authority(self):
        for role in SETUP_ROLES:
            for created in (False, True):
                with self.subTest(role=role, created=created), tempfile.TemporaryDirectory() as temp:
                    run_dir, saved, docker, _commands = self.crash_setup(temp, role, created)
                    self.assertEqual(set(saved['pending_resources']), {role})
                    self.assertNotIn(role, saved['created_resources'])
                    code, saved = self.down(run_dir, docker)
                    self.assertEqual((code, saved['status']), (0, 'stopped'))
                    self.assertEqual(docker.objects, {})
                    self.assertTrue(saved['unrecorded_cleanup'][role]['absence_confirmed'])
                    self.assertEqual(saved['unrecorded_cleanup'][role]['removed'], int(created))

    def test_sweep_crash_at_each_gateway_replacement_step_leaves_down_full_authority(self):
        name = f't3-issue28-gateway-{RUN_12}'
        labels = {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': RUN_12}
        for step in ('stop', 'after-remove', 'intent-write', 'before-create', 'after-create',
                     'after-record'):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temp:
                manifest = dict(full_manifest(), retired_resources=[])
                manifest['created_resources']['container_gateway'] = {
                    'kind': 'container', 'name': name, 'id': 'bootstrap-id', 'run_id': RUN_12,
                    'labels': dict(labels)}
                results, run_dir, log, _path = self.manifest_dir(temp, manifest)
                (run_dir / 'config').mkdir()
                policy = run_dir / 'config' / 'runtime-targets.json'
                policy.write_text('{}\n', encoding='utf-8')
                docker = FakeDocker(recorded_objects(manifest))
                real_write = benchctl.write_manifest

                def mutate(argv, logs, check=True, step=step, docker=docker):
                    if argv[:3] == ['docker', 'run', '-d']:
                        if step == 'before-create':
                            raise ControllerCrash(step)
                        docker.objects['replacement-id'] = ('container', name, RUN_12)
                        if step == 'after-create':
                            raise ControllerCrash(step)
                        return 0
                    if argv[:3] == ['docker', 'network', 'connect']:
                        raise ControllerCrash(step)  # 'after-record': the identity is committed.
                    if argv[:2] == ['docker', 'stop'] and step == 'stop':
                        raise ControllerCrash(step)
                    code = docker.run(argv, logs, check)
                    if argv[:2] == ['docker', 'rm'] and step == 'after-remove':
                        raise ControllerCrash(step)
                    return code

                def write(target, current, step=step):
                    if step == 'intent-write':
                        raise ControllerCrash(step)
                    return real_write(target, current)
                with patch.object(benchctl, 'RESULTS', results), \
                        patch.object(benchctl, 'docker_inspect_json', side_effect=docker.inspect), \
                        patch.object(benchctl, 'run', side_effect=mutate), \
                        patch.object(benchctl, 'write_manifest', side_effect=write), \
                        patch.object(benchctl.subprocess, 'run', side_effect=docker.subprocess_run), \
                        patch.object(benchctl.time, 'sleep'):
                    with self.assertRaises(ControllerCrash):
                        benchctl.configure_gateway(manifest, policy, log)
                code, saved = self.down(run_dir, docker)
                self.assertEqual((code, saved['status']), (0, 'stopped'))
                self.assertEqual(docker.objects, {})
                self.assertTrue(saved['labelled_leftovers']['absence_confirmed'])

    def test_sweep_down_killed_midway_is_finished_by_a_later_down(self):
        manifest = dict(full_manifest(), canary_attempts=[
            {'provider': 'codex', 'phase': 'dispatching', 'launch': {'status': 'not-accepted'}}])
        with tempfile.TemporaryDirectory() as temp:
            _results, run_dir, _log, _path = self.manifest_dir(temp, manifest)
            docker = FakeDocker(recorded_objects(manifest))
            calls = []
            real_run = docker.run

            def dying_run(argv, logs, check=True):
                calls.append(argv)
                code = real_run(argv, logs, check)
                if len(calls) == 3:
                    raise ControllerCrash('down killed')
                return code
            docker.run = dying_run
            with self.assertRaises(ControllerCrash):
                self.down(run_dir, docker)
            self.assertTrue(docker.objects)
            docker.run = real_run
            code, saved = self.down(run_dir, docker)
        self.assertEqual((code, saved['status']), (0, 'stopped'))
        self.assertEqual(docker.objects, {})
        self.assertIn('already-absent', saved['cleanup'].values())

    # R14-CO-02: helper execution is bound to the declared primary child thread.

    def test_r14_co_02_helper_must_run_only_in_the_primary_child_thread(self):
        command = benchctl.helper_command('codex')
        self.assertTrue(host_observations.helper_invocation_observed(
            actor_observation(), command, 'task-primary'))
        cases = {'boundary child only': ('child-b1',),
                 'primary plus boundary child': ('child-primary', 'child-b2'),
                 'native probe only': ('child-native',), 'parent only': ('parent',),
                 'primary plus parent': ('child-primary', 'parent'),
                 'grandchild of primary': ('child-grand',), 'unknown thread': ('elsewhere',),
                 'primary twice': ('child-primary', 'child-primary'), 'nowhere': ()}
        for label, threads in cases.items():
            with self.subTest(case=label):
                self.assertFalse(host_observations.helper_invocation_observed(
                    actor_observation(threads), command, 'task-primary'))
        with self.subTest(case='failed primary run'):
            self.assertFalse(host_observations.helper_invocation_observed(
                actor_observation(exit_code=1), command, 'task-primary'))

    def test_r14_co_02_follow_up_in_a_boundary_thread_does_not_count(self):
        command = benchctl.helper_command('codex')
        observation = actor_observation(('child-b3',))
        # A tracked follow-up continues its original's child thread.
        observation['subagents'].append({'threadId': 'parent', 'id': 'task-followup',
                                         'childThreadId': 'child-b3', 'origin': 'app_owned'})
        self.assertFalse(host_observations.helper_invocation_observed(observation, command, 'task-primary'))

    def test_r14_co_02_primary_task_must_resolve_to_one_parent_dispatched_thread(self):
        command = benchctl.helper_command('codex')
        cases = {'no primary ID': (actor_observation(), None),
                 'unknown task': (actor_observation(), 'task-missing'),
                 'boundary task named as primary': (actor_observation(), 'task-32767'),
                 'native probe named as primary': (actor_observation(('child-native',)), 'native-1'),
                 'status names another thread': (actor_observation(primary_status_child='child-b1'),
                                                 'task-primary'),
                 'row owned by a child': (actor_observation(primary_owner='child-b1'), 'task-primary'),
                 'primary resolves to parent': (actor_observation(('parent',), primary_status_child='parent'),
                                                'task-primary')}
        for label, (observation, task_id) in cases.items():
            with self.subTest(case=label):
                self.assertFalse(host_observations.helper_invocation_observed(observation, command, task_id))

    def test_r14_co_02_snapshot_records_parent_and_child_actions_by_thread(self):
        command = benchctl.helper_command('codex')
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'host.sqlite'
            connection = sqlite3.connect(db)
            for table in ('turn_items', 'subagents', 'runs', 'runtime_requests', 'threads'):
                connection.execute(f'CREATE TABLE orchestration_v2_projection_{table} '
                                   '(thread_id TEXT, type TEXT, ordinal INTEGER, payload_json TEXT)')
            for task, child in (('task-primary', 'child-primary'), ('task-32767', 'child-b1')):
                connection.execute('INSERT INTO orchestration_v2_projection_subagents VALUES (?,?,?,?)', (
                    'parent', 'subagent', 1,
                    json.dumps({'threadId': 'parent', 'id': task, 'childThreadId': child})))
            items = [('parent', 'command_execution', {'input': command, 'exitCode': 0}),
                     ('child-primary', 'command_execution', {'input': command, 'exitCode': 0}),
                     ('child-b1', 'file_change', {'changes': [{'path': '/bench/ws/x'}]}),
                     ('parent', 'file_change', {'changes': [{'path': '/bench/ws/y'}]})]
            for ordinal, (thread, kind, payload) in enumerate(items):
                connection.execute('INSERT INTO orchestration_v2_projection_turn_items VALUES (?,?,?,?)', (
                    thread, kind, ordinal, json.dumps(dict(payload, id=f'item-{ordinal}', threadId=thread,
                                                           status='completed'))))
            connection.commit()
            connection.close()
            observed = host_observations.read_snapshot(db, 'parent')
        self.assertEqual(sorted(row['threadId'] for row in observed['commands']), ['child-primary', 'parent'])
        self.assertEqual(sorted(row['threadId'] for row in observed['file_changes']), ['child-b1', 'parent'])
        self.assertNotIn('changes', observed['file_changes'][0])
        # The parent's own helper run is now visible, so the primary's run is not unique.
        self.assertFalse(host_observations.helper_invocation_observed(observed, command, 'task-primary'))
        observed['commands'] = [row for row in observed['commands'] if row['threadId'] != 'parent']
        self.assertTrue(host_observations.helper_invocation_observed(observed, command, 'task-primary'))
        self.assertFalse(host_observations.file_changes_bound_to_primary(observed, 'task-primary'))

    def test_sweep_recorded_file_changes_must_come_from_the_primary(self):
        self.assertTrue(host_observations.file_changes_bound_to_primary(actor_observation(), 'task-primary'))
        self.assertTrue(host_observations.file_changes_bound_to_primary(
            actor_observation(file_change_threads=('child-primary',)), 'task-primary'))
        for threads in (('child-b1',), ('parent',), ('child-native',), ('child-grand',),
                        ('child-primary', 'child-b2')):
            with self.subTest(threads=threads):
                self.assertFalse(host_observations.file_changes_bound_to_primary(
                    actor_observation(file_change_threads=threads), 'task-primary'))
        unresolved = actor_observation(primary_status_child='child-b1')
        self.assertFalse(host_observations.file_changes_bound_to_primary(unresolved, 'task-primary'))
        missing = actor_observation()
        del missing['file_changes']
        self.assertFalse(host_observations.file_changes_bound_to_primary(missing, 'task-primary'))

    def run_canary(self, captured, canary_result=None):
        """Drive `canary` to acceptance with every other piece of evidence passing."""
        targets = {'codex': dict(CANARY_TARGET),
                   'claudeAgent': {'providerInstanceId': 'claudeAgent', 'model': 'fixture-anthropic',
                                   'options': {}}}
        hosts = {'codex': 'api.openai.com', 'claudeAgent': 'api.anthropic.com'}
        identities = {provider: {'provider_instance_id': provider, 'requested_model_id': target['model'],
                                 'source': f'https://{hosts[provider]}/v1/models/{target["model"]}',
                                 'http_status': 200, 'response_model_id': target['model'],
                                 'observed_at': '2026-10-13T00:00:00Z', 'response_sha256': 'a' * 64}
                      for provider, target in targets.items()}
        hashes = {name: hashlib.sha256((CONTAINER / name).read_bytes()).hexdigest()
                  for name in benchctl.SOURCE_FILES}
        hashes['model_policy.py'] = hashlib.sha256(
            (ROOT / 'bench' / 'v2' / 'tools' / 'model_policy.py').read_bytes()).hexdigest()
        manifest = {'run_id': RUN_12, 'status': 'catalog-locked', 'smoke_passed': True,
                    'observer_boundary_preflight': {'status': 'passed',
                                                    'literal_provider_network_verified': True,
                                                    'native_binary_resolution': {'verified': True}},
                    'canary_attempts': [], 'runtime_targets': targets,
                    'response_identity_metadata': {'identities': identities},
                    'build_source_sha256': hashes,
                    'created_resources': {'container_agent': {'id': 'agent-id'}},
                    'containers': {'agent': 'agent', 'gateway': 'gateway', 'github': 'github'}}
        digest = 'b' * 64
        if canary_result is None:
            canary_result = {'input_sha256': digest, 'github_login': 'bench-user',
                             'primary_task_id': 'task-primary',
                             'summary_boundary_task_ids': {key: f'task-{key}'
                                                           for key in ('32767', '32768', '32769')},
                             'tracked_followup': {'new_task_id': None}}
        wait = {'status': 'completed', 'timed_out': False, 'readback_model': 'fixture-openai',
                'readback_provider': 'codex', 'original_message_exact': True,
                'final_message_retrieval_exact': True, 'canary_result': canary_result}

        def fake_driver(_manifest, arguments, _logs):
            return {'threadId': 'parent', 'status': 'running'} if '--launch-provider' in arguments else wait
        owned = {'verified': True, 'native_child_visibility': 'observed finite native probe',
                 'native_probe_checks': {}, 'pending_approvals': [], 'native_child_visibility_verified': True}
        boundary = {'verified': True, 'records': [
            {'expected_utf8_bytes': size, 'actual_utf8_bytes': size, 'exact': True}
            for size in (32767, 32768, 32769)]}
        with tempfile.TemporaryDirectory() as temp:
            _results, run_dir, _log, path = self.manifest_dir(temp, manifest)
            (run_dir / 'input').mkdir()
            (run_dir / 'input' / 'brief.sha256').write_text(digest + '\n', encoding='ascii')
            (run_dir / 'workspace').mkdir()
            with patch.object(benchctl, 'RESULTS', run_dir.parent), \
                    patch.object(benchctl, 'read_native_launches', return_value=[]), \
                    patch.object(benchctl, 'github_event_count', side_effect=[0, 1]), \
                    patch.object(benchctl, 'gateway_rejection_count', return_value=0), \
                    patch.object(benchctl, 'driver', side_effect=fake_driver), \
                    patch.object(benchctl.subprocess, 'run',
                                 return_value=fixture_done(stdout='{"verified": true}\n')), \
                    patch.object(benchctl, 'capture_parent_observations', return_value=captured), \
                    patch.object(host_observations, 'verify_owned_tasks', return_value=owned), \
                    patch.object(benchctl.driver_module, 'verify_summary_boundary_tasks',
                                 return_value=boundary), \
                    patch.object(benchctl.driver_module, 'verify_tracked_followup',
                                 return_value={'recorded': True, 'supported': True, 'verified': True}), \
                    patch.object(benchctl, 'helper_output_valid', return_value=True), \
                    patch.object(benchctl, 'workspace_write_scope_valid', return_value=True), \
                    patch.object(benchctl, 'gateway_model_observations', return_value={'verified': True}), \
                    patch.object(benchctl, 'canary_native_launch_audit', return_value={'verified': True}), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = benchctl.manage(type('Args', (), {'command': 'canary', 'run_id': RUN_12,
                                                         'provider': 'codex'})())
            saved = json.loads(path.read_text(encoding='utf-8'))
            protocol_file = run_dir / 'protocol' / 'canary-roles-codex.json'
            receipt_file = run_dir / 'observations' / 'canary-role-audit-codex.json'
            self.last_canary = {
                'canary': saved['canary_attempts'][0],
                'protocol_file': protocol_file.name if protocol_file.is_file() else None,
                'protocol_mode': (stat.S_IMODE(protocol_file.stat().st_mode)
                                  if protocol_file.is_file() else None),
                'protocol_sha256': (hashlib.sha256(protocol_file.read_bytes()).hexdigest()
                                    if protocol_file.is_file() else None),
                'receipt': (json.loads(receipt_file.read_text(encoding='utf-8'))
                            if receipt_file.is_file() else None),
                'receipt_mode': (stat.S_IMODE(receipt_file.stat().st_mode)
                                 if receipt_file.is_file() else None)}
        return code, saved['canary_attempts'][0]['model_audit']

    def test_r14_co_02_canary_acceptance_binds_helper_and_writes_to_the_primary(self):
        cases = {'helper run only by a boundary reader': (actor_observation(('child-b1',)),
                                                          'helper_invocation_host_observed'),
                 'extra helper run in a boundary reader': (actor_observation(('child-primary', 'child-b2')),
                                                           'helper_invocation_host_observed'),
                 'file change by a boundary reader': (actor_observation(file_change_threads=('child-b3',)),
                                                      'host_recorded_writes_bound')}
        for label, (observation, check) in cases.items():
            with self.subTest(case=label):
                code, audit = self.run_canary(observation)
                self.assertEqual(code, 2)
                self.assertIs(audit['verified'], False)
                self.assertIs(audit[check], False)
        code, audit = self.run_canary(actor_observation(file_change_threads=('child-primary',)))
        self.assertEqual(code, 0)
        self.assertIs(audit['verified'], True)
        self.assertIs(audit['helper_invocation_host_observed'], True)
        self.assertIs(audit['host_recorded_writes_bound'], True)


HONEST_REPORT = {'input_sha256': 'b' * 64, 'github_login': 'bench-user',
                 'primary_task_id': 'task-primary',
                 'summary_boundary_task_ids': {'32767': 'task-32767', '32768': 'task-32768',
                                               '32769': 'task-32769'},
                 'tracked_followup': {'original_task_id': 'task-primary', 'new_task_id': None}}


class Pass16ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 16: bind finite canary roles to the captured dispatch assignment."""

    run_canary = Pass15ContainerRepairTest.run_canary
    manifest_dir = Pass12ContainerRepairTest.manifest_dir

    def protocol(self):
        return benchctl.canary_role_protocol('codex', CANARY_TARGET)

    def test_r15_co_01_consistent_primary_boundary_swap_fails_the_canary(self):
        # The dispatched writer P returns the 32767-byte fixture; the dispatched boundary
        # reader B runs the helper. The report answers consistently in the swapped frame.
        swapped = dict(HONEST_REPORT)
        swapped['primary_task_id'] = 'task-32767'
        swapped['summary_boundary_task_ids'] = {'32767': 'task-primary', '32768': 'task-32768',
                                                '32769': 'task-32769'}
        code, audit = self.run_canary(actor_observation(('child-b1',),
                                                        file_change_threads=('child-b1',)), swapped)
        self.assertEqual(code, 2)
        self.assertIs(audit['verified'], False)
        self.assertIs(audit['canary_roles_bound_to_host_dispatch'], False)
        self.assertIs(audit['helper_invocation_host_observed'], False)
        self.assertIn('reported primary does not match the captured primary dispatch',
                      audit['role_assignment_problems'])

    def test_r15_co_01_honest_assignments_still_pass_and_record_the_authority(self):
        code, audit = self.run_canary(actor_observation(file_change_threads=('child-primary',)))
        self.assertEqual(code, 0)
        self.assertIs(audit['verified'], True)
        self.assertIs(audit['canary_roles_bound_to_host_dispatch'], True)
        self.assertEqual(audit['role_assignment_problems'], [])
        self.assertEqual(audit['role_assignments'], {
            'primary': 'task-primary', 'summary-32767': 'task-32767',
            'summary-32768': 'task-32768', 'summary-32769': 'task-32769', 'native-probe': 'native-1'})
        recorded = self.last_canary
        self.assertEqual(recorded['protocol_file'], 'canary-roles-codex.json')
        self.assertEqual(recorded['protocol_mode'], 0o600)
        self.assertEqual(recorded['canary']['role_protocol']['sha256'], recorded['protocol_sha256'])
        self.assertEqual(recorded['receipt_mode'], 0o600)
        self.assertEqual(recorded['receipt']['assignments'], audit['role_assignments'])
        self.assertEqual(recorded['receipt']['verified'], True)

    def test_r15_co_01_captured_assignments_bind_every_finite_role(self):
        honest = host_observations.captured_role_assignments(actor_observation(), self.protocol())
        self.assertTrue(honest['ok'], honest['problems'])
        self.assertEqual(honest['assignments']['native-probe'], 'native-1')
        # A dispatch that swaps which task carries the primary marker defeats the report binding.
        records = role_dispatch_records()
        records[0]['output']['taskId'] = 'task-99999'
        swapped = host_observations.captured_role_assignments(actor_observation(dispatches=records),
                                                              self.protocol())
        self.assertEqual(swapped['assignments']['primary'], 'task-99999')
        self.assertFalse(host_observations.reported_role_bindings(
            actor_observation(dispatches=records), self.protocol(), HONEST_REPORT)['ok'])

    def test_r15_co_01_missing_duplicate_or_conflicting_dispatches_fail_closed(self):
        cases = {}
        no_primary = [row for row in role_dispatch_records() if row['output']['taskId'] != 'task-primary']
        cases['missing primary marker'] = (actor_observation(dispatches=no_primary), self.protocol())
        renamed = role_dispatch_records()
        renamed[0]['input']['task'] = 'ISSUE28_CANARY_ROLE=writer\n' + benchctl.helper_command('codex')
        cases['marker not a frozen role'] = (actor_observation(dispatches=renamed), self.protocol())
        wrong_scope = role_dispatch_records()
        wrong_scope[0]['input']['task'] = 'ISSUE28_CANARY_ROLE=primary\nread some other file\n'
        cases['marker without its frozen scope'] = (actor_observation(dispatches=wrong_scope), self.protocol())
        wrong_target = role_dispatch_records()
        wrong_target[0]['input']['target'] = {'providerInstanceId': 'claudeAgent',
                                              'model': 'fixture-anthropic', 'options': {}}
        cases['marker without the frozen target'] = (actor_observation(dispatches=wrong_target), self.protocol())
        duplicated = role_dispatch_records() + [dict(role_dispatch_records()[0],
                                                     output={'taskId': 'task-extra'})]
        cases['duplicated primary marker'] = (actor_observation(dispatches=duplicated), self.protocol())
        multi = role_dispatch_records()
        multi[0]['input']['task'] = ('ISSUE28_CANARY_ROLE=primary\nISSUE28_CANARY_ROLE=summary-32767\n'
                                     + benchctl.helper_command('codex') + '\n/bench/input/summary-32767.txt\n')
        cases['one task carries two roles'] = (actor_observation(dispatches=multi), self.protocol())
        native = actor_observation(dispatches=role_dispatch_records())
        for row in native['subagents']:
            if row.get('origin') == 'provider_native':
                row['prompt'] = 'ISSUE28_NATIVE_PROBE'
        cases['native probe without its frozen marker'] = (native, self.protocol())
        malformed = self.protocol()
        malformed['roles'].append(dict(malformed['roles'][0]))
        cases['duplicated protocol role'] = (actor_observation(dispatches=role_dispatch_records()), malformed)
        for label, (observation, protocol) in cases.items():
            with self.subTest(case=label):
                result = host_observations.captured_role_assignments(observation, protocol)
                self.assertFalse(result['ok'], label)
                self.assertFalse(host_observations.reported_role_bindings(
                    observation, protocol, HONEST_REPORT)['ok'], label)

    def test_r15_co_01_report_bindings_reject_reordered_and_relabelled_claims(self):
        observation = actor_observation()
        protocol = self.protocol()
        self.assertTrue(host_observations.reported_role_bindings(observation, protocol, HONEST_REPORT)['ok'])
        variants = {'primary relabelled to a boundary task': {'primary_task_id': 'task-32767'},
                    'boundary 32767 relabelled to the primary task': {
                        'summary_boundary_task_ids': {'32767': 'task-primary', '32768': 'task-32768',
                                                      '32769': 'task-32769'}},
                    'boundaries reordered': {'summary_boundary_task_ids': {
                        '32767': 'task-32768', '32768': 'task-32769', '32769': 'task-32767'}},
                    'missing boundary key': {'summary_boundary_task_ids': {
                        '32767': 'task-32767', '32768': 'task-32768'}},
                    'follow-up original is not a role task': {'tracked_followup': {
                        'original_task_id': 'task-elsewhere', 'new_task_id': None}},
                    'follow-up new task repeats a role task': {'tracked_followup': {
                        'original_task_id': 'task-primary', 'new_task_id': 'task-primary'}}}
        for label, changes in variants.items():
            with self.subTest(case=label):
                report = {**HONEST_REPORT, **changes}
                self.assertFalse(host_observations.reported_role_bindings(observation, protocol, report)['ok'])
        # A refusal that names the real primary is still recorded honestly.
        refused = {**HONEST_REPORT, 'tracked_followup': {'original_task_id': 'task-32767',
                                                         'new_task_id': None}}
        self.assertFalse(host_observations.reported_role_bindings(observation, protocol, refused)['ok'])

    def test_r15_co_01_protocol_is_frozen_host_side_and_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / RUN_12
            run_dir.mkdir()
            path = benchctl.write_canary_role_protocol(run_dir, 'codex', CANARY_TARGET)
            self.assertEqual(path.parent.name, 'protocol')
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            record = {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            loaded = benchctl.load_canary_role_protocol(run_dir, record)
            self.assertTrue(host_observations.frozen_protocol_is_valid(loaded))
            self.assertEqual(loaded, self.protocol())
            path.chmod(0o600)
            path.write_text(json.dumps(self.protocol(), sort_keys=True, indent=2).replace(
                'ISSUE28_CANARY_ROLE=primary', 'ISSUE28_CANARY_ROLE=writer') + '\n', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'changed after launch'):
                benchctl.load_canary_role_protocol(run_dir, record)
            with self.assertRaisesRegex(RuntimeError, 'was not frozen'):
                benchctl.load_canary_role_protocol(run_dir, {})

    def test_r15_co_01_protocol_rejects_duplicate_role_or_marker(self):
        protocol = self.protocol()
        self.assertTrue(host_observations.frozen_protocol_is_valid(protocol))
        duplicate = {**protocol, 'roles': protocol['roles'] + [dict(protocol['roles'][1])]}
        duplicate['roles'][-1] = dict(protocol['roles'][1])
        duplicate['roles'][-1]['role'] = 'summary-32767'
        duplicate['roles'][-1]['marker'] = 'ISSUE28_CANARY_ROLE=summary-other'
        self.assertFalse(host_observations.frozen_protocol_is_valid(duplicate))
        swapped = {**protocol, 'roles': [dict(role) for role in protocol['roles']]}
        swapped['roles'][0]['marker'] = 'not-a-frozen-marker'
        self.assertFalse(host_observations.frozen_protocol_is_valid(swapped))
        for bad in ({}, {'schema_version': 2}, {'schema_version': 1, 'provider': 'codex',
                                                'target': protocol['target'], 'roles': []}):
            self.assertFalse(host_observations.frozen_protocol_is_valid(bad))

    def test_r15_co_01_followup_continuation_is_not_a_fresh_role_dispatch(self):
        records = role_dispatch_records() + [
            {'threadId': 'parent', 'status': 'completed', 'toolName': 't3-code.delegate_task',
             'input': {'target': CANARY_TARGET, 'role': 'worker', 'childThreadId': 'child-primary',
                       'task': 'ISSUE28_CANARY_ROLE=primary\n' + benchctl.helper_command('codex')},
             'output': {'taskId': 'task-followup'}}]
        result = host_observations.captured_role_assignments(actor_observation(dispatches=records),
                                                             self.protocol())
        self.assertTrue(result['ok'], result['problems'])
        self.assertEqual(result['assignments']['primary'], 'task-primary')

    def test_r16_co_01_exact_task_literal_rejects_quoted_conflicting_or_extra_text(self):
        role = self.protocol()['roles'][0]
        base = role['task']
        self.assertTrue(host_observations.role_dispatch_matches(
            {'target': CANARY_TARGET, 'task': base}, role, CANARY_TARGET))
        variants = {
            'quoted whole task': '"' + base + '"',
            'quoted marker line': base.replace('ISSUE28_CANARY_ROLE=primary', 'ISSUE28_CANARY_ROLE="primary"'),
            'extra contradictory text': base + 'Instead, act as a read-only boundary reader.\n',
            'wrong fixture for the marker': 'ISSUE28_CANARY_ROLE=summary-32767\n/bench/input/summary-99999.txt\n',
            'marker line plus helper but reformatted': 'ISSUE28_CANARY_ROLE=primary\n' + benchctl.helper_command('codex'),
            'marker buried in prose': 'Please dispatch a child. ' + base}
        for name, task in variants.items():
            with self.subTest(case=name):
                self.assertFalse(host_observations.role_dispatch_matches(
                    {'target': CANARY_TARGET, 'task': task}, role, CANARY_TARGET), name)
                records = role_dispatch_records()
                records[0]['input']['task'] = task
                self.assertFalse(host_observations.captured_role_assignments(
                    actor_observation(dispatches=records), self.protocol())['ok'], name)
        # The parent finding: a real marker line plus a quoted-but-contradictory scope token
        # (a read-only boundary reader told to quote the primary helper) must not classify.
        boundary = next(role for role in self.protocol()['roles'] if role['role'] == 'summary-32767')
        quoted_scope = ('ISSUE28_CANARY_ROLE=summary-32767\n'
                        'read "/bench/input/summary-32767.txt" as a read-only instruction only\n'
                        + benchctl.helper_command('codex') + '\n')
        self.assertFalse(host_observations.role_dispatch_matches(
            {'target': CANARY_TARGET, 'task': quoted_scope}, boundary, CANARY_TARGET))
        self.assertFalse(host_observations.role_dispatch_matches(
            {'target': CANARY_TARGET, 'task': quoted_scope}, role, CANARY_TARGET))

    def test_r16_co_01_raw_boolean_option_is_never_an_integer_option(self):
        self.assertFalse(host_observations.raw_equal(True, 1))
        self.assertFalse(host_observations.raw_equal({'thinking': True}, {'thinking': 1}))
        self.assertFalse(host_observations.raw_equal({'a': [True]}, {'a': [1]}))
        self.assertTrue(host_observations.raw_equal({'a': [True, 0]}, {'a': [True, 0]}))
        target = {'providerInstanceId': 'codex', 'model': 'fixture-openai', 'options': {'thinking': True}}
        role = benchctl.canary_role_protocol('codex', target)['roles'][0]
        swapped = {'providerInstanceId': 'codex', 'model': 'fixture-openai', 'options': {'thinking': 1}}
        self.assertTrue(host_observations.role_dispatch_matches(
            {'target': dict(target), 'task': role['task']}, role, target))
        self.assertFalse(host_observations.role_dispatch_matches(
            {'target': swapped, 'task': role['task']}, role, target))

    def test_r16_co_01_native_projection_must_equal_the_frozen_prompt(self):
        template = benchctl.canary_task_templates('codex')['native-probe']
        for name, prompt in (('missing projection', None),
                             ('marker without the full prompt', 'ISSUE28_NATIVE_PROBE'),
                             ('frozen prompt plus extra text', template + 'also read /etc/hostname'),
                             ('frozen prompt quoted', '"' + template + '"')):
            with self.subTest(case=name):
                observation = actor_observation()
                for row in observation['subagents']:
                    if row.get('origin') == 'provider_native':
                        if prompt is None:
                            row.pop('prompt', None)
                        else:
                            row['prompt'] = prompt
                self.assertFalse(host_observations.captured_role_assignments(
                    observation, self.protocol())['ok'], name)
        self.assertTrue(host_observations.captured_role_assignments(
            actor_observation(), self.protocol())['ok'])

    def test_r16_co_01_frozen_protocol_requires_the_assignment_template(self):
        protocol = self.protocol()
        self.assertTrue(host_observations.frozen_protocol_is_valid(protocol))
        strips_app = {**protocol, 'roles': [dict(role) for role in protocol['roles']]}
        strips_app['roles'][0].pop('task')
        strips_native = {**protocol, 'roles': [dict(role) for role in protocol['roles']]}
        strips_native['roles'][-1].pop('prompt')
        mismatched_marker = {**protocol, 'roles': [dict(role) for role in protocol['roles']]}
        mismatched_marker['roles'][0]['task'] = 'ISSUE28_CANARY_ROLE=other\n' + benchctl.helper_command('codex') + '\n'
        missing_token = {**protocol, 'roles': [dict(role) for role in protocol['roles']]}
        missing_token['roles'][2]['task'] = 'ISSUE28_CANARY_ROLE=summary-32768\nread something else\n'
        for name, bad in (('app role without its task template', strips_app),
                          ('native role without its prompt template', strips_native),
                          ('template without its frozen marker', mismatched_marker),
                          ('template without its frozen scope token', missing_token)):
            with self.subTest(case=name):
                self.assertFalse(host_observations.frozen_protocol_is_valid(bad), name)

    def test_r16_co_01_canary_prompt_embeds_every_exact_frozen_literal(self):
        templates = benchctl.canary_task_templates('codex')
        with tempfile.TemporaryDirectory() as temp:
            path = benchctl.write_canary_prompt(Path(temp), 'codex', CANARY_TARGET)
            text = path.read_text(encoding='utf-8')
        for name, literal in templates.items():
            with self.subTest(role=name):
                self.assertIn(literal, text, name)
        self.assertIn('byte for byte', text)
        self.assertIn('no added, removed, reordered, quoted, indented', text)


class GatedReader:
    """A request-body reader that blocks until released, so one handler can be paused mid-body."""

    def __init__(self, data, entered, release):
        self.data = data
        self.entered = entered
        self.release = release
        self.offset = 0

    def read(self, size=-1):
        self.entered.set()
        if not self.release.wait(5):
            raise AssertionError('gated request body was never released')
        if size is None or size < 0:
            chunk = self.data[self.offset:]
        else:
            chunk = self.data[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class RejectingUpstream(FakeUpstream):
    """A provider that answers with a non-2xx status, which must lock the gateway."""

    def getresponse(self):
        return type('RejectedResponse', (), {
            'status': 429, 'reason': 'Too Many Requests',
            'getheaders': lambda self: [('Content-Type', 'application/json')],
            'read': lambda self, _limit=-1: b'{"error":"rate limited"}'})()


class Pass18ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 18: serialized upstream admission; strict continuation target equality."""

    def setUp(self):
        self.credential_env = patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'synthetic-gateway-anthropic',
            'OPENAI_API_KEY': 'synthetic-gateway-openai'})
        self.credential_env.start()
        self.original_targets = gateway.TARGETS
        self.original_options = gateway.TARGET_OPTIONS
        self.original_locked = gateway.LOCKED
        gateway.LOCKED = False
        gateway.TARGETS = {'claudeAgent': 'claude-haiku-5-5', 'codex': 'gpt-6-luna'}
        gateway.TARGET_OPTIONS = {'claudeAgent': {'effort': 'low'},
                                  'codex': {'reasoningEffort': 'low', 'serviceTier': 'default'}}
        FakeUpstream.calls = []

    def tearDown(self):
        self.credential_env.stop()
        gateway.TARGETS = self.original_targets
        gateway.TARGET_OPTIONS = self.original_options
        gateway.LOCKED = self.original_locked

    def test_r16_co_01_paused_request_cannot_start_upstream_after_a_parallel_lock(self):
        entered, release = threading.Event(), threading.Event()
        valid = {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}, 'service_tier': 'default'}
        paused = FakeHandler('/v1/responses', valid)
        paused.rfile = GatedReader(json.dumps(valid, separators=(',', ':')).encode(), entered, release)
        log, errors = io.StringIO(), []

        def run():
            try:
                paused.do_POST()
            except BaseException as exc:  # noqa: BLE001 - re-surfaced on the main thread
                errors.append(exc)

        forbidden = {'model': 'gpt-6-astra', 'reasoning': {'effort': 'low'}, 'service_tier': 'default'}
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream), \
                contextlib.redirect_stdout(log):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(entered.wait(5), 'the valid request never reached its body read')
            # Handler B rejects a forbidden model while A is still paused mid-body.
            parallel = FakeHandler('/v1/responses', forbidden)
            parallel.do_POST()
            self.assertEqual(parallel.status, 403)
            self.assertTrue(gateway.LOCKED)
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive(), 'the paused handler never finished')
        self.assertEqual(errors, [])
        self.assertEqual(paused.status, 403)
        self.assertEqual(FakeUpstream.calls, [])
        events = [json.loads(line) for line in log.getvalue().splitlines() if line.strip()]
        self.assertNotIn('forward-started', [event['event'] for event in events])

    def test_r16_co_01_valid_request_still_reaches_the_provider(self):
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream):
            code, _ = request(None, '/v1/responses',
                              {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}})
        self.assertEqual(code, 200)
        self.assertEqual(len(FakeUpstream.calls), 1)
        self.assertFalse(gateway.LOCKED)

    def test_r16_co_01_admission_point_is_shared_with_every_lock_writer(self):
        handler = FakeHandler('/v1/responses', {'model': 'gpt-6-luna'})
        started, log = {'event': 'forward-started', 'request_id': 'synthetic'}, io.StringIO()
        with contextlib.redirect_stdout(log):
            self.assertFalse(handler._is_locked())
            self.assertTrue(handler._admit_upstream(started))
            handler._record_lock()
            self.assertTrue(handler._is_locked())
            self.assertFalse(handler._admit_upstream(started))
        # Pass 19: only the admitted call records a start.
        self.assertEqual(log.getvalue().count('forward-started'), 1)
        code, _ = request(None, '/v1/responses',
                          {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}})
        self.assertEqual(code, 403)
        self.assertEqual(FakeUpstream.calls, [])

    def test_r16_co_01_non_2xx_provider_response_closes_admission(self):
        with patch.object(gateway.http.client, 'HTTPSConnection', RejectingUpstream):
            code, _ = request(None, '/v1/responses',
                              {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}})
        self.assertEqual(code, 429)
        self.assertTrue(gateway.LOCKED)
        fresh = FakeHandler('/v1/responses', {'model': 'gpt-6-luna'})
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            self.assertFalse(fresh._admit_upstream({'event': 'forward-started', 'request_id': 'synthetic'}))
        self.assertEqual(log.getvalue(), '')

    def test_r16_co_02_continuation_target_is_compared_without_bool_int_coercion(self):
        original = {'providerInstanceId': 'codex', 'model': 'gpt-6-luna',
                    'options': {'thinking': False}}

        def records(new_target):
            status = {'toolName': 't3-code.task_status', 'input': {'taskId': 'task-original'},
                      'output': {'taskId': 'task-original', 'childThreadId': 'child-1'}}
            return [status,
                    {'toolName': 't3-code.delegate_task', 'input': {'target': dict(original)},
                     'output': {'taskId': 'task-original'}},
                    {'toolName': 't3-code.delegate_task',
                     'input': {'target': new_target, 'childThreadId': 'child-1'},
                     'output': {'taskId': 'task-followup'}},
                    dict(status)]

        honest = host_observations.CapturedTaskClient({'tool_records': records(dict(original))})
        observed = honest.followup_observation('task-original', 'task-followup')
        self.assertIsNotNone(observed)
        self.assertEqual(observed['launch']['input']['target']['options'], {'thinking': False})
        swapped = {**original, 'options': {'thinking': 0}}
        drift = host_observations.CapturedTaskClient({'tool_records': records(swapped)})
        self.assertIsNone(drift.followup_observation('task-original', 'task-followup'))

    def test_r16_co_02_owned_task_target_is_compared_without_bool_int_coercion(self):
        target = {'providerInstanceId': 'codex', 'model': 'gpt-6-luna',
                  'options': {'thinking': False}}
        selection = {'instanceId': 'codex', 'model': 'gpt-6-luna',
                     'options': [{'id': 'thinking', 'value': False}]}

        def observation(launch_target):
            return {'parent_thread_id': 'parent', 'runtime_requests': [],
                    'subagents': [{'threadId': 'parent', 'id': 'task1', 'childThreadId': 'child1'}],
                    'threads': [{'id': 'child1', 'modelSelection': selection}],
                    'runs': [{'id': 'child1', 'threadId': 'child1', 'status': 'completed',
                              'modelSelection': selection}],
                    'tool_records': [
                        {'toolName': 't3-code.delegate_task', 'input': {'target': launch_target},
                         'output': {'taskId': 'task1'}},
                        {'toolName': 't3-code.task_status', 'input': {'taskId': 'task1'},
                         'output': {'taskId': 'task1', 'status': 'completed',
                                    'workState': 'result_available', 'hasPendingChildRuns': False,
                                    'providerInstanceId': 'codex', 'model': 'gpt-6-luna'}}]}

        honest = host_observations.verify_owned_tasks(observation(dict(target)), ['task1'], target)
        self.assertTrue(honest['checks']['exact_targets'])
        self.assertTrue(honest['verified'])
        swapped = {**target, 'options': {'thinking': 0}}
        drift = host_observations.verify_owned_tasks(observation(swapped), ['task1'], target)
        self.assertFalse(drift['checks']['exact_targets'])
        self.assertFalse(drift['verified'])


class PausingStdout(io.StringIO):
    """A log stream that blocks the first write naming `marker` until released."""

    def __init__(self, marker, entered, release):
        super().__init__()
        self.marker, self.entered, self.release = marker, entered, release

    def write(self, text):
        if self.marker in text and not self.entered.is_set():
            self.entered.set()
            if not self.release.wait(5):
                raise AssertionError('paused log write was never released')
        return super().write(text)


class Pass19ContainerRepairTest(unittest.TestCase):
    """Issue 28 pass 19: an admitted request is recorded as started inside the admission section."""

    setUp = Pass18ContainerRepairTest.setUp
    tearDown = Pass18ContainerRepairTest.tearDown
    valid = {'model': 'gpt-6-luna', 'reasoning': {'effort': 'low'}, 'service_tier': 'default'}
    forbidden = {'model': 'gpt-6-astra', 'reasoning': {'effort': 'low'}, 'service_tier': 'default'}

    def run_in_thread(self, handler, errors, done=None):
        def run():
            try:
                handler.do_POST()
            except BaseException as exc:  # noqa: BLE001 - re-surfaced on the main thread
                errors.append(exc)
            finally:
                if done is not None:
                    done.set()
        thread = threading.Thread(target=run)
        thread.start()
        return thread

    def assert_starts_precede_lock(self, events):
        kinds = [event['event'] for event in events]
        lock = next(i for i, event in enumerate(events)
                    if event['event'] == 'rejected' and event['reason'] != 'gateway locked after a rejected request')
        self.assertTrue(all(i < lock for i, kind in enumerate(kinds) if kind == 'forward-started'), kinds)

    def test_r16_co_01_admitted_request_is_recorded_started_before_a_parallel_lock(self):
        """Admission returns, B locks, then A continues: A's start must already be on record."""
        admitted, release = threading.Event(), threading.Event()
        paused = FakeHandler('/v1/responses', self.valid)
        real_admit = paused._admit_upstream

        def admit_then_pause(*args):
            result = real_admit(*args)
            admitted.set()
            if not release.wait(5):
                raise AssertionError('admitted handler was never released')
            return result
        paused._admit_upstream = admit_then_pause
        log, errors = io.StringIO(), []
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream), \
                contextlib.redirect_stdout(log):
            thread = self.run_in_thread(paused, errors)
            self.assertTrue(admitted.wait(5), 'the valid request never reached admission')
            parallel = FakeHandler('/v1/responses', self.forbidden)
            parallel.do_POST()
            self.assertEqual(parallel.status, 403)
            release.set()
            thread.join(5)
            later = FakeHandler('/v1/responses', self.valid)
            later.do_POST()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        # The already-admitted request is real owned work: it starts once and is accounted.
        self.assertEqual((paused.status, len(FakeUpstream.calls), later.status), (200, 1, 403))
        events = [json.loads(line) for line in log.getvalue().splitlines() if line.strip()]
        started = [e['request_id'] for e in events if e['event'] == 'forward-started']
        self.assertEqual(len(started), 1)
        self.assertIn(started[0], {e['request_id'] for e in events if e['event'] == 'forwarded'})
        self.assert_starts_precede_lock(events)

    def test_r16_co_01_lock_writer_waits_for_an_admission_being_recorded(self):
        """A lock cannot land between admission and its start record."""
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        log, errors = PausingStdout('forward-started', entered, release), []
        admitting = FakeHandler('/v1/responses', self.valid)
        with patch.object(gateway.http.client, 'HTTPSConnection', FakeUpstream), \
                contextlib.redirect_stdout(log):
            first = self.run_in_thread(admitting, errors)
            self.assertTrue(entered.wait(5), 'the valid request never recorded its start')
            locker = self.run_in_thread(FakeHandler('/v1/responses', self.forbidden), errors, done)
            self.assertFalse(done.wait(0.3), 'a lock writer finished while an admission was being recorded')
            self.assertFalse(gateway.LOCKED)
            release.set()
            first.join(5)
            locker.join(5)
        self.assertFalse(first.is_alive() or locker.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(gateway.LOCKED)
        self.assertEqual((admitting.status, len(FakeUpstream.calls)), (200, 1))
        self.assert_starts_precede_lock([json.loads(line) for line in log.getvalue().splitlines() if line.strip()])

    def test_r16_co_01_refused_admission_records_no_start(self):
        started = {'event': 'forward-started', 'request_id': 'synthetic'}
        handler = FakeHandler('/v1/responses', self.valid)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            self.assertTrue(handler._admit_upstream(started))
            handler._record_lock()
            self.assertFalse(handler._admit_upstream(started))
        self.assertEqual([json.loads(line) for line in log.getvalue().splitlines()], [started])

    def test_r16_co_02_resumed_continuation_identity_is_compared_without_bool_int_coercion(self):
        """The resumed continuation's provider/model must equal the launch target with identical raw types."""
        tools = [{'name': 'task_status', 'inputSchema': {
            'type': 'object', 'properties': {'taskId': {'type': 'string'}}, 'required': ['taskId']}}]
        report = {'tracked_followup': {'status': 'supported', 'original_task_id': 'task-original',
                                       'new_task_id': 'task-followup'}}

        def records(target, resumed):
            def status(task_id, summary, identity):
                return {'toolName': 't3-code.task_status', 'input': {'taskId': task_id},
                        'output': {'taskId': task_id, 'summary': summary, 'status': 'completed',
                                   'workState': 'result_available', 'hasPendingChildRuns': False,
                                   'childThreadId': 'child-thread', **identity}}
            return host_observations.CapturedTaskClient({'tool_records': [
                {'toolName': 't3-code.delegate_task', 'input': {'target': target},
                 'output': {'taskId': 'task-original'}},
                status('task-original', 'original', target),
                {'toolName': 't3-code.delegate_task', 'input': {'target': target, 'childThreadId': 'child-thread'},
                 'output': {'taskId': 'task-followup'}},
                status('task-original', 'original', target),
                status('task-followup', 'follow-up', resumed)]})
        honest = {'providerInstanceId': 'codex', 'model': 'fixture-luna'}
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(driver.verify_tracked_followup(records(honest, honest), tools, report, Path(temp))['verified'])
            for target, resumed in (({'providerInstanceId': 'codex', 'model': 1}, {'providerInstanceId': 'codex', 'model': True}),
                                    ({'providerInstanceId': 0, 'model': 'fixture-luna'}, {'providerInstanceId': False, 'model': 'fixture-luna'})):
                audit = driver.verify_tracked_followup(records(target, resumed), tools, report, Path(temp))
                self.assertFalse(audit['verified'], (target, resumed))


if __name__ == '__main__':
    unittest.main()
