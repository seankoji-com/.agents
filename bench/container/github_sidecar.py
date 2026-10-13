#!/usr/bin/env python3
"""Small deterministic GitHub-compatible fixture for offline bench canaries."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class GitHubHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def _send(self, code, value):
        body = json.dumps(value, sort_keys=True).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record_read(self, path):
        print(json.dumps({'event': 'read', 'route': path}, separators=(',', ':')), flush=True)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        self._record_read(path)
        if path in ('/api/v3/user', '/user'):
            self._send(200, {'login': 'bench-user', 'id': 28, 'type': 'User'})
        elif path in ('/api/v3/repos/bench-org/bench-repo', '/repos/bench-org/bench-repo'):
            self._send(200, {'id': 2800, 'name': 'bench-repo', 'full_name': 'bench-org/bench-repo',
                             'default_branch': 'main', 'private': True})
        elif path in ('/api/v3/repos/bench-org/bench-repo/pulls/1',
                      '/repos/bench-org/bench-repo/pulls/1'):
            self._send(200, {'number': 1, 'title': 'Synthetic benchmark PR', 'state': 'open',
                             'head': {'ref': 'bench/change', 'sha': 'a' * 40},
                             'base': {'ref': 'main', 'sha': 'b' * 40}, 'mergeable': True})
        elif path.endswith('/pulls'):
            self._send(200, [{'number': 1, 'title': 'Synthetic benchmark PR', 'state': 'open'}])
        elif path.endswith('/check-runs'):
            self._send(200, {'total_count': 1, 'check_runs': [{'name': 'fixture-check', 'status': 'completed',
                                                                'conclusion': 'failure'}]})
        elif path.endswith('/reviews') or path.endswith('/comments'):
            self._send(200, [{'id': 2801, 'body': 'Synthetic review finding', 'state': 'CHANGES_REQUESTED'}])
        else:
            self._send(404, {'message': 'synthetic fixture route not found'})

    def do_POST(self):
        # No mutations are needed by the Stage 1b canaries.
        self._send(403, {'message': 'synthetic GitHub fixture is read-only'})


def main():
    port = int(os.environ.get('BENCH_GITHUB_PORT', '8080'))
    server = ThreadingHTTPServer(('0.0.0.0', port), GitHubHandler)
    print(json.dumps({'event': 'ready', 'port': port}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
