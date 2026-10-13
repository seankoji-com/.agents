#!/usr/bin/env python3
"""Catalog mutation for the missing-delegation negative start, at the MCP boundary.

bench/v2/plan.json requires the parent's `orchestrator_capabilities` view to report
`canRunChildTask: false` for the parent's provider while every other byte of the
target (provider ID, model, options) stays as validated. The pinned T3 derives the
field from provider health, so a real state change would also stop the parent.

The pinned T3 hands each provider CLI its MCP endpoint in one of two places, and
both pass through `native_exec.py`, the root-owned launcher for every CLI:

- Claude Code: `--mcp-config '{"mcpServers":{"t3-code":{"type":"http","url":...}}}'`
  in argv (Claude Agent SDK);
- Codex: `config.mcp_servers["t3-code"].url` in the `thread/start`, `thread/resume`
  and `thread/fork` JSON-RPC requests that T3 writes to `codex app-server` stdin.

When the coordinator mounts a shim config, `run()` keeps the launcher as a root
process. It starts a loopback HTTP proxy per T3 endpoint, points the CLI's T3 URL
at it, and starts the CLI as the worker UID. The proxy forwards every request
unchanged (Authorization included) and edits exactly one field in
`orchestrator_capabilities` results. Each rewrite, refusal and redirect is
appended to a root-only log; tokens and bodies are never logged, only SHA-256s.

Integration: native_exec.py, root branch, after its launch record:
    import mcp_shim
    config = mcp_shim.load_config()
    if config is not None:
        raise SystemExit(mcp_shim.run(program, sys.argv[1:], config, drop=DROP, real=real))
and the image must contain /opt/bench/mcp_shim.py.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SCENARIO = 'negative-missing-delegation'
TOOL = 'orchestrator_capabilities'
FIELD = 'canRunChildTask'
CONFIG_PATH = '/run/bench-shim/mcp-shim.json'
LOG_PATH = '/bench/t3/mcp-shim.jsonl'  # /bench/t3 is root-only (0700) inside the agent
SERVER = 't3-code'
CODEX_METHODS = ('thread/start', 'thread/resume', 'thread/fork')
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailers',
       'transfer-encoding', 'upgrade', 'content-length', 'host', 'accept-encoding'}


# ---- coordinator side ---------------------------------------------------------

def enabled_for(scenario_id: str) -> bool:
    return scenario_id == SCENARIO


def write_config(results: Path, provider_instance_id: str) -> Path:
    if not isinstance(provider_instance_id, str) or not provider_instance_id:
        raise ValueError('the parent providerInstanceId is required')
    directory = Path(results) / 'stage-fixtures' / 'mcp-shim'
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = directory / 'mcp-shim.json'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump({'schema_version': 1, 'scenario': SCENARIO, 'tool': TOOL, 'field': FIELD,
                   'from': True, 'to': False, 'provider_instance_id': provider_instance_id}, stream, sort_keys=True)
    return path


def container_args(scenario_id: str, provider_instance_id: str | None = None, results: Path | None = None) -> list:
    """Agent `docker run` flags enabling the shim; empty for every other scenario.

    The config is mode 0600 and mapped to container root, so worker-UID processes
    cannot read it; its presence is the only switch.
    """
    if not enabled_for(scenario_id):
        return []
    if results is None:
        raise ValueError('results directory is required to write the shim config')
    return ['-v', f'{write_config(results, provider_instance_id)}:{CONFIG_PATH}:ro']


def load_config(path: str = CONFIG_PATH) -> dict | None:
    target = Path(path)
    if not target.exists():
        return None
    if target.is_symlink():
        raise SystemExit('mcp shim config must not be a symlink')
    config = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or config.get('schema_version') != 1 or config.get('scenario') != SCENARIO \
            or not isinstance(config.get('provider_instance_id'), str):
        raise SystemExit('mcp shim config is invalid')
    return config


def audit_log(text: str, provider_instance_id: str) -> dict:
    """Coordinator check over the shim log: the mutation is verified only when at least
    one capabilities result was rewritten for that provider, none was refused, every
    rewrite changed exactly that provider's field, and every line parsed."""
    rewrites, refusals, redirects, errors, malformed = [], [], [], [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        kind = event.get('event') if isinstance(event, dict) else None
        if kind == 'capabilities_rewrite':
            rewrites.append(event)
        elif kind == 'capabilities_refused':
            refusals.append(event)
        elif kind == 'upstream_redirect':
            redirects.append(event)
        elif kind == 'proxy_error':
            errors.append(event)  # reported; a dropped stream is not by itself a failed mutation
    exact = all(e.get('provider_instance_id') == provider_instance_id and e.get('changed_paths') and
                all(p.endswith('.' + FIELD) for p in e['changed_paths']) and e.get('original_value') is True
                for e in rewrites)
    return {'rewrites': len(rewrites), 'refusals': len(refusals), 'redirects': len(redirects),
            'proxy_errors': len(errors), 'malformed_lines': malformed,
            'verified': bool(rewrites) and not refusals and exact and malformed == 0}


# ---- the rewrite itself -------------------------------------------------------

def _changed(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        found = []
        for key in sorted(set(before) | set(after)):
            found.extend(_changed(before.get(key), after.get(key), f'{prefix}.{key}' if prefix else key))
        return found
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        found = []
        for index, (old, new) in enumerate(zip(before, after)):
            found.extend(_changed(old, new, f'{prefix}[{index}]'))
        return found
    return [] if before == after and type(before) is type(after) else [prefix]


def _flip(catalog, provider_instance_id):
    """Return (new catalog, None) or (None, reason)."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get('providers'), list):
        return None, 'no providers list'
    matches = [i for i, p in enumerate(catalog['providers'])
               if isinstance(p, dict) and p.get('providerInstanceId') == provider_instance_id]
    if len(matches) != 1:
        return None, 'parent provider not listed exactly once'
    entry = catalog['providers'][matches[0]]
    if entry.get(FIELD) is not True:
        return None, f'{FIELD} was not true'
    updated = json.loads(json.dumps(catalog))
    updated['providers'][matches[0]][FIELD] = False
    return updated, None


def _dump_like(original_text, value):
    """Serialise `value` in whichever stock JSON layout reproduces the original text."""
    parsed = json.loads(original_text)
    for options in ({'separators': (',', ':')}, {}, {'indent': 2}, {'indent': 2, 'sort_keys': True},
                    {'separators': (',', ':'), 'sort_keys': True}):
        if json.dumps(parsed, ensure_ascii=False, **options) == original_text:
            return json.dumps(value, ensure_ascii=False, **options), True
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')), False


def _decoded(message):
    """A copy with JSON text content parsed, so a comparison sees values, not layout."""
    copy = json.loads(json.dumps(message))
    for item in copy['result'].get('content') or []:
        if isinstance(item, dict) and isinstance(item.get('text'), str):
            try:
                item['text'] = json.loads(item['text'])
            except ValueError:
                pass
    return copy


def rewrite_capabilities_result(message: dict, provider_instance_id: str):
    """Rewrite one JSON-RPC response to an orchestrator_capabilities call.

    Both MCP result forms are edited: `structuredContent` and every text content item
    that is the catalog as JSON. Returns (message, record). On any failed
    precondition the message is returned unchanged and the record says why.
    """
    original = json.dumps(message, sort_keys=True).encode()
    record = {'request_id': message.get('id'), 'provider_instance_id': provider_instance_id,
              'original_sha256': hashlib.sha256(original).hexdigest()}
    result = message.get('result')
    if not isinstance(result, dict) or result.get('isError'):
        return message, dict(record, event='capabilities_refused', reason='result absent or an error')
    updated = json.loads(json.dumps(message))
    forms, formats = 0, []
    if isinstance(result.get('structuredContent'), dict):
        catalog, reason = _flip(result['structuredContent'], provider_instance_id)
        if catalog is None:
            return message, dict(record, event='capabilities_refused', reason='structuredContent: ' + reason)
        updated['result']['structuredContent'] = catalog
        forms += 1
    for index, item in enumerate(result.get('content') or []):
        if not isinstance(item, dict) or item.get('type') != 'text' or not isinstance(item.get('text'), str):
            continue
        try:
            parsed = json.loads(item['text'])
        except ValueError:
            continue
        if not isinstance(parsed, dict) or 'providers' not in parsed:
            continue
        catalog, reason = _flip(parsed, provider_instance_id)
        if catalog is None:
            return message, dict(record, event='capabilities_refused', reason=f'content[{index}]: ' + reason)
        text, preserved = _dump_like(item['text'], catalog)
        updated['result']['content'][index]['text'] = text
        formats.append(preserved)
        forms += 1
    if forms == 0:
        return message, dict(record, event='capabilities_refused', reason='no catalog in the result')
    changed = _changed(_decoded(message), _decoded(updated))
    if not changed or not all(path.endswith('.' + FIELD) for path in changed):
        return message, dict(record, event='capabilities_refused', reason='rewrite touched other fields')
    rewritten = json.dumps(updated, sort_keys=True).encode()
    return updated, dict(record, event='capabilities_rewrite', original_value=True, forms=forms,
                         changed_paths=changed, text_format_preserved=all(formats),
                         rewritten_sha256=hashlib.sha256(rewritten).hexdigest())


def capability_request_ids(body: bytes) -> set:
    try:
        payload = json.loads(body or b'null')
    except ValueError:
        return set()
    found = set()
    for item in payload if isinstance(payload, list) else [payload]:
        if isinstance(item, dict) and item.get('method') == 'tools/call' and \
                isinstance(item.get('params'), dict) and item['params'].get('name') == TOOL and 'id' in item:
            found.add(json.dumps(item['id']))
    return found


def rewrite_payload(text: str, ids: set, provider_instance_id: str, log):
    """Rewrite matching responses in one JSON body (single or batch); returns text."""
    try:
        payload = json.loads(text)
    except ValueError:
        return text
    changed = False
    items = payload if isinstance(payload, list) else [payload]
    for index, item in enumerate(items):
        if isinstance(item, dict) and json.dumps(item.get('id')) in ids and 'method' not in item:
            new, record = rewrite_capabilities_result(item, provider_instance_id)
            log(record)
            if new is not item:
                items[index] = new
                changed = True
    if not changed:
        return text
    return json.dumps(items if isinstance(payload, list) else items[0], separators=(',', ':'))


# ---- loopback proxy -------------------------------------------------------------

class Log:
    def __init__(self, path=LOG_PATH):
        self.path, self.lock = path, threading.Lock()

    def __call__(self, record):
        line = json.dumps(dict(record, ts=time.time(), pid=os.getpid()), sort_keys=True) + '\n'
        with self.lock:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a', encoding='utf-8') as stream:
                stream.write(line)


class ProxyServer(ThreadingHTTPServer):
    """Handler errors go to the shim log, never to the CLI's inherited stderr."""
    daemon_threads = True
    shim_log = None

    def handle_error(self, request, client_address):
        self.shim_log({'event': 'proxy_error', 'reason': type(sys.exc_info()[1]).__name__})


class ProxyPool:
    """One loopback proxy per distinct T3 MCP origin, owned by the root launcher."""

    def __init__(self, provider_instance_id, log):
        self.provider_instance_id, self.log = provider_instance_id, log
        self.servers, self.lock = {}, threading.Lock()

    def url_for(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme != 'http' or not parts.hostname:
            raise ValueError('only the plain-HTTP container-local T3 endpoint is supported')
        origin = (parts.hostname, parts.port or 80)
        with self.lock:
            if origin not in self.servers:
                handler = make_proxy_handler(parts, self.provider_instance_id, self.log)
                server = ProxyServer(('127.0.0.1', 0), handler)
                server.shim_log = self.log
                threading.Thread(target=server.serve_forever, daemon=True).start()
                self.servers[origin] = server
            port = self.servers[origin].server_address[1]
        return f'http://127.0.0.1:{port}{parts.path or "/"}' + (f'?{parts.query}' if parts.query else '')

    def close(self):
        for server in self.servers.values():
            server.shutdown()
            server.server_close()


def make_proxy_handler(upstream, provider_instance_id, log):
    """Build the request handler; capability IDs are tracked per request."""
    class Proxy(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, _format, *_args):
            return

        def _read_body(self):
            if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
                chunks = []
                while True:
                    size = int(self.rfile.readline().split(b';', 1)[0].strip() or b'0', 16)
                    if size == 0:
                        while self.rfile.readline() not in (b'\r\n', b'\n', b''):
                            pass
                        return b''.join(chunks)
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline()
            length = int(self.headers.get('Content-Length') or 0)
            return self.rfile.read(length) if length else b''

        def _forward(self):
            body = self._read_body()
            ids = capability_request_ids(body) if self.command == 'POST' else set()
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            headers['Accept-Encoding'] = 'identity'
            if body:
                headers['Content-Length'] = str(len(body))
            connection = http.client.HTTPConnection(upstream.hostname, upstream.port or 80, timeout=None)
            try:
                connection.request(self.command, self.path, body or None, headers)
                response = connection.getresponse()
            except OSError as exc:
                log({'event': 'proxy_error', 'reason': type(exc).__name__})
                self.send_error(502)
                return
            kind = (response.getheader('Content-Type') or '').split(';', 1)[0].strip().lower()
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in HOP:
                    self.send_header(name, value)
            if kind != 'text/event-stream' and (ids or response.getheader('Content-Length') is not None):
                data = response.read()
                if ids:
                    data = rewrite_payload(data.decode('utf-8'), ids, provider_instance_id, log).encode('utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                # Streams (SSE and unsized bodies) are delimited by connection close.
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                self._relay(response, ids if kind == 'text/event-stream' else set())
            connection.close()

        def _relay(self, response, ids):
            pending = []
            while True:
                chunk = response.readline() if ids else response.read1(65536)
                if not chunk:
                    break
                if not ids:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    continue
                pending.append(chunk)
                if chunk in (b'\n', b'\r\n'):
                    self.wfile.write(self._event(pending, ids))
                    self.wfile.flush()
                    pending = []
            if pending:
                self.wfile.write(self._event(pending, ids))
                self.wfile.flush()

        def _event(self, lines, ids):
            data = [line[5:].rstrip(b'\r\n') for line in lines if line.startswith(b'data:')]
            data = [part[1:] if part.startswith(b' ') else part for part in data]
            if not data:
                return b''.join(lines)
            text = b'\n'.join(data).decode('utf-8')
            new = rewrite_payload(text, ids, provider_instance_id, log)
            if new == text:
                return b''.join(lines)
            kept = [line for line in lines if not line.startswith(b'data:') and line not in (b'\n', b'\r\n')]
            return b''.join(kept) + b'data: ' + new.encode('utf-8') + b'\n\n'

        do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = do_OPTIONS = _forward

    return Proxy


# ---- endpoint redirection -----------------------------------------------------------

def rewrite_claude_argv(argv: list, url_for, log) -> list:
    """Point the `t3-code` HTTP server in `--mcp-config` JSON at the proxy."""
    result, index = list(argv), 0
    while index < len(result):
        arg = result[index]
        inline = arg.startswith('--mcp-config=')
        if arg == '--mcp-config' or inline:
            position = index if inline else index + 1
            raw = arg.split('=', 1)[1] if inline else (result[position] if position < len(result) else '')
            try:
                config = json.loads(raw)
                server = config['mcpServers'][SERVER]
                if server.get('type') != 'http' or not isinstance(server.get('url'), str):
                    raise ValueError('t3-code server is not HTTP')
            except (ValueError, KeyError, TypeError) as exc:
                log({'event': 'redirect_skipped', 'program': 'claude', 'reason': type(exc).__name__})
                index += 1
                continue
            upstream = server['url']
            server['url'] = url_for(upstream)
            encoded = json.dumps(config, separators=(',', ':'))
            result[position] = ('--mcp-config=' + encoded) if inline else encoded
            log({'event': 'upstream_redirect', 'program': 'claude', 'via': 'argv --mcp-config',
                 'upstream': urlsplit(upstream).netloc + urlsplit(upstream).path})
        index += 1
    return result


def rewrite_codex_line(line: bytes, url_for, log) -> bytes:
    """Point `config.mcp_servers["t3-code"].url` in Codex thread requests at the proxy.

    Lines that are not such requests pass through byte for byte.
    """
    if not any(method.encode() in line for method in CODEX_METHODS):
        return line
    try:
        message = json.loads(line)
        server = message['params']['config']['mcp_servers'][SERVER]
        if message.get('method') not in CODEX_METHODS or not isinstance(server.get('url'), str):
            return line
    except (ValueError, KeyError, TypeError):
        return line
    upstream = server['url']
    server['url'] = url_for(upstream)
    log({'event': 'upstream_redirect', 'program': 'codex', 'via': 'app-server ' + message['method'],
         'upstream': urlsplit(upstream).netloc + urlsplit(upstream).path})
    ending = b'\r\n' if line.endswith(b'\r\n') else (b'\n' if line.endswith(b'\n') else b'')
    return json.dumps(message, separators=(',', ':')).encode('utf-8') + ending


# ---- launcher ---------------------------------------------------------------------

def run(program: str, argv: list, config: dict, *, drop=(), real: str | None = None,
        log=None, stdin=None, stdout=None) -> int:
    """Launch the provider CLI with its T3 endpoint routed through the proxy.

    `drop` is native_exec's setpriv prefix, so the CLI runs as the worker UID while
    this process (and the proxy it owns) keeps root. Exit status mirrors the CLI.
    """
    log = log or Log()
    real = real or f'/usr/local/bin/{program}-native'
    pool = ProxyPool(config['provider_instance_id'], log)
    log({'event': 'shim_start', 'program': program, 'provider_instance_id': config['provider_instance_id']})
    stdin = stdin if stdin is not None else sys.stdin.buffer
    try:
        if program == 'claude':
            child = subprocess.Popen([*drop, real, *rewrite_claude_argv(argv, pool.url_for, log)],
                                     stdout=stdout)
            relay = None
        elif program == 'codex':
            child = subprocess.Popen([*drop, real, *argv], stdin=subprocess.PIPE, stdout=stdout)

            def pump():
                try:
                    for line in iter(stdin.readline, b''):
                        child.stdin.write(rewrite_codex_line(line, pool.url_for, log))
                        child.stdin.flush()
                except (BrokenPipeError, ValueError):
                    pass
                finally:
                    try:
                        child.stdin.close()
                    except OSError:
                        pass
            relay = threading.Thread(target=pump, daemon=True)
            relay.start()
        else:
            raise SystemExit('mcp shim supports claude and codex only')
        previous = {}
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                previous[number] = signal.signal(number, lambda sig, _frame: child.send_signal(sig))
            except ValueError:
                pass  # not the main thread (tests)
        code = child.wait()
        for number, handler in previous.items():
            signal.signal(number, handler)
        return code if code >= 0 else 128 - code
    finally:
        pool.close()


if __name__ == '__main__':
    loaded = load_config()
    if loaded is None:
        raise SystemExit('mcp shim is not configured')
    name = Path(sys.argv[1]).name if len(sys.argv) > 1 else ''
    raise SystemExit(run(name, sys.argv[2:], loaded))
