#!/usr/bin/env python3
"""Screenshot the built documentation site with headless Chrome.

Serves a built ``site/`` directory on a loopback port, opens each page at each width
and colour scheme, and writes PNGs. It also measures page-level horizontal overflow,
so a mobile layout regression fails the run instead of hiding in a screenshot.

    python3 -m mkdocs build --strict
    python3 scripts/capture_site.py --site site --out /tmp/shots
    python3 scripts/capture_site.py --site site --out docs/assets/screenshots \\
        --page index.html --width 1440 --scheme light --height 900

Chrome is found on PATH (google-chrome, chromium, chromium-browser) or through
``--chrome``. Headless Chrome will not open a window narrower than 500px, so narrower
widths load the page in an iframe of exactly that width and crop the screenshot with
ffmpeg. The run fails with a clear message when Chrome, or ffmpeg for a narrow width,
is missing. Standard library only; the server and Chrome run inside this one process tree.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import html
import http.server
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

DEFAULT_PAGES = ('index.html', 'getting-started/index.html', 'plugins/imps/index.html',
                 'plugins/ralph/index.html')
CHROME_NAMES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')
SCHEMES = {'light': 'light', 'dark': 'dark'}
# Injected only into pages requested with ?probe; reports layout width in the title.
PROBE = (b'<script>addEventListener("load",function(){setTimeout(function(){'
         b'var d=document.documentElement;document.title="PROBE "+d.scrollWidth+" "+innerWidth;'
         b'},300)});</script>')
PROBE_TITLE = re.compile(r'<title>PROBE (\d+) (\d+)</title>')
MIN_WINDOW = 500
FRAME_PATH = '/__frame__'
FRAME = ('<!doctype html><html><head><title>frame</title><style>html,body{{margin:0;overflow:hidden}}'
         'iframe{{border:0;display:block}}</style></head><body>'
         '<iframe id="f" src="{src}" width="{w}" height="{h}"></iframe><script>'
         'var f=document.getElementById("f");setInterval(function(){{try{{'
         'var t=f.contentDocument.title;if(t.indexOf("PROBE")===0)document.title=t;}}catch(e){{}}}},100);'
         '</script></body></html>')


class CaptureError(RuntimeError):
    """A prerequisite is missing or a page failed its checks."""


def find_chrome(explicit: str | None = None) -> str:
    if explicit:
        if shutil.which(explicit) or Path(explicit).is_file():
            return explicit
        raise CaptureError(f'Chrome not found at {explicit}')
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    raise CaptureError('headless Chrome is required: install google-chrome or chromium, '
                       'or pass --chrome PATH')


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the run quiet
        pass

    def send_head(self):
        if self.path.startswith(FRAME_PATH + '?'):
            from urllib.parse import parse_qs, urlsplit
            q = parse_qs(urlsplit(self.path).query)
            src, w, h = q['src'][0], int(q['w'][0]), int(q['h'][0])
            body = FRAME.format(src=html.escape(src), w=w, h=h).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            return io.BytesIO(body)
        if '?probe' not in self.path:
            return super().send_head()
        self.path = self.path.split('?', 1)[0]
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / 'index.html'
        if not path.is_file() or path.suffix != '.html':
            return super().send_head()
        body = path.read_bytes().replace(b'</body>', PROBE + b'</body>', 1)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        return io.BytesIO(body)


@contextlib.contextmanager
def serve(site: Path):
    handler = functools.partial(_Handler, directory=str(site))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}/'
    finally:
        server.shutdown()
        server.server_close()


def find_ffmpeg() -> str:
    found = shutil.which('ffmpeg')
    if not found:
        raise CaptureError(f'widths below {MIN_WINDOW}px need ffmpeg to crop the screenshot; install ffmpeg')
    return found


def page_url(base: str, page: str, width: int, height: int, probe: bool) -> str:
    target = '/' + page + ('?probe' if probe else '')
    if width >= MIN_WINDOW:
        return base.rstrip('/') + target
    from urllib.parse import quote
    return f"{base.rstrip('/')}{FRAME_PATH}?src={quote(target)}&w={width}&h={height}"


def chrome_args(chrome: str, profile: Path, width: int, height: int, scheme: str,
                virtual_ms: int = 4000) -> list[str]:
    width = max(width, MIN_WINDOW)
    return [chrome, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
            '--disable-crash-reporter', '--disable-extensions', '--hide-scrollbars',
            f'--user-data-dir={profile}', f'--window-size={width},{height}',
            f'--blink-settings=preferredColorScheme={0 if scheme == "dark" else 1}',
            '--force-device-scale-factor=1', f'--virtual-time-budget={virtual_ms}']


def run_chrome(args: list[str], env: dict, attempts: int = 2) -> subprocess.CompletedProcess:
    last = None
    for _ in range(attempts):  # an occasional socket() failure in sandboxes is transient
        last = subprocess.run(args, env=env, capture_output=True, text=True, timeout=90)
        if last.returncode == 0:
            return last
    raise CaptureError(f'Chrome exited {last.returncode}: {last.stderr.strip()[-400:]}')


def shot_name(page: str, width: int, scheme: str) -> str:
    stem = page.removesuffix('index.html').strip('/').replace('/', '-') or 'home'
    return f'{stem}-{width}-{scheme}.png'


def capture(site: Path, out: Path, pages, widths, schemes, height: int | None, chrome: str,
            full: bool = False, virtual_ms: int = 4000) -> list[dict]:
    if not (site / 'index.html').is_file():
        raise CaptureError(f'{site} has no index.html; build the site first')
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='capture-site-') as tmp:
        env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=tmp, XDG_CACHE_HOME=tmp)
        with serve(site) as base:
            for page in pages:
                for width in widths:
                    for scheme in schemes:
                        h = height or (844 if width < 600 else 900)
                        profile = Path(tmp) / f'profile-{width}-{scheme}'
                        args = chrome_args(chrome, profile, width, h, scheme)
                        dom = run_chrome(args + ['--dump-dom', page_url(base, page, width, h, True)], env).stdout
                        probe = PROBE_TITLE.search(dom)
                        if not probe:
                            raise CaptureError(f'{page}: layout probe did not report')
                        scroll, inner = int(probe.group(1)), int(probe.group(2))
                        target = out / shot_name(page, width, scheme)
                        shot_h = h if not full else max(h, 6000)
                        raw = target if width >= MIN_WINDOW else Path(tmp) / target.name
                        run_chrome(chrome_args(chrome, profile, width, shot_h, scheme, virtual_ms)
                                   + [f'--screenshot={raw}', page_url(base, page, width, shot_h, False)], env)
                        if raw != target:
                            subprocess.run([find_ffmpeg(), '-v', 'error', '-y', '-i', str(raw), '-vf',
                                            f'crop={width}:{shot_h}:0:0', str(target)], check=True)
                        results.append({'page': page, 'width': width, 'scheme': scheme,
                                        'file': str(target), 'scroll_width': scroll,
                                        'viewport_width': inner, 'overflow': scroll > inner})
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--site', type=Path, default=Path('site'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--page', action='append', dest='pages', help='repeatable; default: four key pages')
    parser.add_argument('--width', action='append', type=int, dest='widths', help='repeatable; default 1440 and 390')
    parser.add_argument('--scheme', action='append', choices=sorted(SCHEMES), dest='schemes')
    parser.add_argument('--height', type=int, help='viewport height; default 900 desktop, 844 mobile')
    parser.add_argument('--full', action='store_true', help='capture a tall window instead of the fold')
    parser.add_argument('--chrome')
    parser.add_argument('--virtual-time', type=int, default=4000, metavar='MS',
                        help='page time to simulate before the screenshot; the recording finishes after ~14000')
    args = parser.parse_args(argv)
    try:
        chrome = find_chrome(args.chrome)
        if any(w < MIN_WINDOW for w in (args.widths or (390,))):
            find_ffmpeg()
        results = capture(args.site, args.out, args.pages or DEFAULT_PAGES, args.widths or (1440, 390),
                          args.schemes or ('light', 'dark'), args.height, chrome, args.full,
                          args.virtual_time)
    except CaptureError as exc:
        print(f'capture_site: {exc}', file=sys.stderr)
        return 2
    failed = False
    for r in results:
        flag = 'OVERFLOW' if r['overflow'] else 'ok'
        failed |= r['overflow']
        print(f"{flag:8} {r['width']:>4} {r['scheme']:5} scroll={r['scroll_width']} "
              f"viewport={r['viewport_width']} {r['file']}")
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
