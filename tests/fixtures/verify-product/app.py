#!/usr/bin/env python3
"""notes: a tiny JSON notes service used as the verification-init fixture.

Usage: python3 app.py --port PORT --data DIR
  GET  /health  -> 200 {"ok": true}
  GET  /notes   -> 200 [{"id": 1, "text": "..."}]
  POST /notes   -> 201 {"id": n, "text": "..."}   body: {"text": "..."}
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_handler(store: Path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, value):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _notes(self):
            return json.loads(store.read_text()) if store.exists() else []

        def do_GET(self):
            if self.path == '/health':
                return self._send(200, {'ok': True})
            if self.path == '/notes':
                return self._send(200, self._notes())
            return self._send(404, {'error': 'not found'})

        def do_POST(self):
            if self.path != '/notes':
                return self._send(404, {'error': 'not found'})
            length = int(self.headers.get('Content-Length') or 0)
            try:
                text = json.loads(self.rfile.read(length) or b'{}')['text']
            except (ValueError, KeyError, TypeError):
                return self._send(400, {'error': 'body must be {"text": "..."}'})
            notes = self._notes()
            note = {'id': len(notes) + 1, 'text': str(text)}
            store.write_text(json.dumps(notes + [note]))
            return self._send(201, note)

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--data', required=True)
    args = parser.parse_args()
    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(data / 'notes.json')).serve_forever()


if __name__ == '__main__':
    main()
