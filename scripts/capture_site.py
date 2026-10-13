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

``--zoom 200`` sets Chrome's own page zoom (the setting Ctrl and + changes) in the
temporary profile. The run fails unless the page then reports the matching
``devicePixelRatio`` and a correspondingly narrower CSS viewport. ``--controls`` drives
each page through Chrome's DevTools pipe with real mouse and keyboard input: it opens
the navigation and follows a link, types a search and opens a result, and presses a
code-copy button and reads the clipboard back. It saves a screenshot of each state.

    python3 scripts/capture_site.py --site site --out /tmp/zoom --zoom 200 --controls \\
        --width 1440 --page getting-started/index.html
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import html
import http.server
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

DEFAULT_PAGES = ('index.html', 'getting-started/index.html', 'plugins/imps/index.html',
                 'plugins/ralph/index.html')
CHROME_NAMES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')
SCHEMES = {'light': 'light', 'dark': 'dark'}
SEARCH_TERM = 'brew'
# Injected only into pages requested with ?probe; reports layout width and the
# device-pixel ratio, which browser zoom multiplies, in the title.
PROBE = (b'<script>addEventListener("load",function(){setTimeout(function(){'
         b'var d=document.documentElement;'
         b'document.title="PROBE "+d.scrollWidth+" "+innerWidth+" "+devicePixelRatio;'
         b'},300)});</script>')
PROBE_TITLE = re.compile(r'<title>PROBE (\d+) (\d+) ([\d.]+)</title>')
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
                virtual_ms: int | None = 4000) -> list[str]:
    width = max(width, MIN_WINDOW)
    args = [chrome, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
            '--disable-crash-reporter', '--disable-extensions', '--hide-scrollbars',
            f'--user-data-dir={profile}', f'--window-size={width},{height}',
            f'--blink-settings=preferredColorScheme={0 if scheme == "dark" else 1}',
            '--force-device-scale-factor=1']
    return args + ([f'--virtual-time-budget={virtual_ms}'] if virtual_ms is not None else [])


def set_zoom(profile: Path, percent: int) -> None:
    """Give a fresh Chrome profile a default page zoom, as the zoom menu would.

    Chrome stores zoom as a level where each step is a factor of 1.2."""
    if percent <= 0:
        raise CaptureError('zoom must be a positive percentage')
    prefs = profile / 'Default' / 'Preferences'
    prefs.parent.mkdir(parents=True, exist_ok=True)
    if percent != 100:
        level = math.log(percent / 100) / math.log(1.2)
        prefs.write_text(json.dumps({'partition': {'default_zoom_level': {'x': level}}}))


def check_zoom(page: str, percent: int, ratio: float, width: int, inner: int) -> None:
    """Fail unless the page reports both the zoomed pixel ratio and the narrower CSS viewport."""
    if abs(ratio - percent / 100) > .01:
        raise CaptureError(f'{page}: asked for {percent}% zoom but the page reports '
                           f'devicePixelRatio {ratio}; Chrome ignored the zoom setting')
    expected = width * 100 / percent
    if abs(inner - expected) > 1:
        raise CaptureError(f'{page}: at {percent}% zoom a {width}px window should give a '
                           f'{expected:g}px CSS viewport, but the page reports {inner}px')


def run_chrome(args: list[str], env: dict, attempts: int = 2) -> subprocess.CompletedProcess:
    last = None
    for _ in range(attempts):  # an occasional socket() failure in sandboxes is transient
        last = subprocess.run(args, env=env, capture_output=True, text=True, timeout=90)
        if last.returncode == 0:
            return last
    raise CaptureError(f'Chrome exited {last.returncode}: {last.stderr.strip()[-400:]}')


def shot_name(page: str, width: int, scheme: str, zoom: int = 100) -> str:
    stem = page.removesuffix('index.html').strip('/').replace('/', '-') or 'home'
    return f'{stem}-{width}-{scheme}' + (f'-zoom{zoom}' if zoom != 100 else '') + '.png'


def capture(site: Path, out: Path, pages, widths, schemes, height: int | None, chrome: str,
            full: bool = False, virtual_ms: int = 4000, zoom: int = 100) -> list[dict]:
    if not (site / 'index.html').is_file():
        raise CaptureError(f'{site} has no index.html; build the site first')
    if zoom != 100 and any(w < MIN_WINDOW for w in widths):
        raise CaptureError(f'--zoom needs widths of at least {MIN_WINDOW}px; narrower widths load '
                           'in a fixed-width frame that page zoom does not narrow')
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
                        set_zoom(profile, zoom)
                        args = chrome_args(chrome, profile, width, h, scheme)
                        dom = run_chrome(args + ['--dump-dom', page_url(base, page, width, h, True)], env).stdout
                        probe = PROBE_TITLE.search(dom)
                        if not probe:
                            raise CaptureError(f'{page}: layout probe did not report')
                        scroll, inner = int(probe.group(1)), int(probe.group(2))
                        check_zoom(page, zoom, float(probe.group(3)), width, inner)
                        target = out / shot_name(page, width, scheme, zoom)
                        shot_h = h if not full else max(h, 6000)
                        raw = target if width >= MIN_WINDOW else Path(tmp) / target.name
                        run_chrome(chrome_args(chrome, profile, width, shot_h, scheme, virtual_ms)
                                   + [f'--screenshot={raw}', page_url(base, page, width, shot_h, False)], env)
                        if raw != target:
                            subprocess.run([find_ffmpeg(), '-v', 'error', '-y', '-i', str(raw), '-vf',
                                            f'crop={width}:{shot_h}:0:0', str(target)], check=True)
                        results.append({'page': page, 'width': width, 'scheme': scheme, 'zoom': zoom,
                                        'file': str(target), 'scroll_width': scroll,
                                        'viewport_width': inner, 'overflow': scroll > inner})
    return results


class DevTools:
    """A minimal Chrome DevTools Protocol client over ``--remote-debugging-pipe``.

    Chrome reads commands on fd 3 and writes replies on fd 4, each a JSON object ending
    in a NUL byte. A short Python trampoline moves the pipe ends onto those numbers and
    then runs Chrome, which avoids a ``preexec_fn`` while the server thread runs."""

    MOVE = ('import fcntl,os,sys\n'
            'fds=[int(a) for a in sys.argv[1:3]]\n'
            'high=[fcntl.fcntl(fd,fcntl.F_DUPFD,10) for fd in fds]\n'
            'os.dup2(high[0],3);os.dup2(high[1],4)\n'
            '[os.close(fd) for fd in set(fds+high) if fd not in (3,4)]\n'
            'os.execv(sys.argv[3],sys.argv[3:])\n')

    def __init__(self, args: list[str], env: dict, timeout: float = 30):
        to_chrome, self._commands = os.pipe()
        self._replies, from_chrome = os.pipe()
        self.proc = subprocess.Popen([sys.executable, '-c', self.MOVE, str(to_chrome), str(from_chrome),
                                      *args, '--remote-debugging-pipe', 'about:blank'],
                                     env=env, pass_fds=(to_chrome, from_chrome),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        os.close(to_chrome)
        os.close(from_chrome)
        self.timeout, self._buffer, self._id, self.session = timeout, b'', 0, None

    def __enter__(self):
        targets = self.send('Target.getTargets', session=False)['targetInfos']
        page = next(t['targetId'] for t in targets if t['type'] == 'page')
        self.session = self.send('Target.attachToTarget', {'targetId': page, 'flatten': True},
                                 session=False)['sessionId']
        self.send('Page.enable')
        self.send('Emulation.setFocusEmulationEnabled', {'enabled': True})
        return self

    def __exit__(self, *exc):
        try:
            self.send('Browser.close', session=False)
        except CaptureError:
            pass
        for fd in (self._commands, self._replies):
            os.close(fd)
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()

    def _read(self) -> dict:
        import select
        while b'\0' not in self._buffer:
            if not select.select([self._replies], [], [], self.timeout)[0]:
                raise CaptureError('Chrome DevTools did not answer in time')
            chunk = os.read(self._replies, 1 << 16)
            if not chunk:
                err = self.proc.stderr.read().decode(errors='replace').strip()[-400:]
                raise CaptureError(f'Chrome closed the DevTools pipe: {err}')
            self._buffer += chunk
        message, self._buffer = self._buffer.split(b'\0', 1)
        return json.loads(message)

    def send(self, method: str, params: dict | None = None, session: bool = True) -> dict:
        self._id += 1
        message = {'id': self._id, 'method': method, 'params': params or {}}
        if session and self.session:
            message['sessionId'] = self.session
        os.write(self._commands, json.dumps(message).encode() + b'\0')
        while True:
            reply = self._read()
            if reply.get('id') == self._id:
                if 'error' in reply:
                    raise CaptureError(f"{method}: {reply['error'].get('message')}")
                return reply['result']

    def js(self, expression: str):
        result = self.send('Runtime.evaluate', {'expression': expression, 'awaitPromise': True,
                                                'returnByValue': True})
        if 'exceptionDetails' in result:
            raise CaptureError(f"page script failed: {result['exceptionDetails'].get('text')}")
        return result['result'].get('value')

    def until(self, expression: str, what: str, seconds: float = 8):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = self.js(expression)
            if value:
                return value
            time.sleep(.2)
        raise CaptureError(f'timed out waiting for {what}')

    def open(self, url: str) -> None:
        self.send('Page.navigate', {'url': url})
        self.until(f'location.href === {json.dumps(url)} && document.readyState === "complete"', url)
        time.sleep(.8)  # Material's scripts mount buttons and search after load

    def click(self, point) -> None:
        for kind in ('mousePressed', 'mouseReleased'):
            self.send('Input.dispatchMouseEvent', {'type': kind, 'x': point[0], 'y': point[1],
                                                   'button': 'left', 'clickCount': 1})

    def type(self, text: str) -> None:
        for char in text:
            self.send('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': char, 'text': char})
            self.send('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': char})

    def screenshot(self, path: Path) -> None:
        import base64
        time.sleep(.6)  # let Material's header and dialog transitions finish
        path.write_bytes(base64.b64decode(self.send('Page.captureScreenshot')['data']))


# Centre of the first element matching a selector that a click there would reach, or
# null. Only the window scrolls, vertically: scrollIntoView would also slide Material's
# drawer sideways towards hidden nested panels. The hit test skips covered elements.
WHERE = ('(function(sel){var list=document.querySelectorAll(sel);for(var i=0;i<list.length;i++){'
         'var e=list[i],r=e.getBoundingClientRect();if(!r.width||!r.height)continue;'
         'if(r.top<0||r.bottom>innerHeight){scrollBy(0,r.top+r.height/2-innerHeight/2);r=e.getBoundingClientRect()}'
         'var x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);'
         'if(hit&&(hit===e||e.contains(hit)))return [x,y,Math.round(r.width),Math.round(r.height),'
         'e.getAttribute("href")||""]}return null})(%s)')


def check_controls(site: Path, out: Path, page: str, width: int, height: int, scheme: str,
                   zoom: int, chrome: str) -> dict:
    """Use one page the way a reader would and return what happened."""
    if width < MIN_WINDOW:
        raise CaptureError(f'--controls needs a window of at least {MIN_WINDOW}px')
    out.mkdir(parents=True, exist_ok=True)
    stem = shot_name(page, width, scheme, zoom).removesuffix('.png')
    with tempfile.TemporaryDirectory(prefix='capture-site-') as tmp, serve(site) as base:
        env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=tmp, XDG_CACHE_HOME=tmp)
        profile = Path(tmp) / 'profile'
        set_zoom(profile, zoom)
        url = base + page
        with DevTools(chrome_args(chrome, profile, width, height, scheme, None), env) as tab:
            def where(selector, what):
                point = tab.js(WHERE % json.dumps(selector))
                if not point:
                    raise CaptureError(f'{page}: no visible {what} ({selector})')
                return point

            def path_now():
                return tab.js('location.pathname + location.hash')

            tab.open(url)
            inner, ratio = tab.js('[innerWidth, devicePixelRatio]')
            check_zoom(page, zoom, ratio, width, inner)
            result = {'page': page, 'width': width, 'scheme': scheme, 'zoom': zoom,
                      'viewport_width': inner, 'device_pixel_ratio': ratio}

            # Navigation: below Material's sidebar breakpoint the menu is a drawer.
            toggle = tab.js(WHERE % json.dumps('label.md-header__button[for="__drawer"]'))
            if toggle:
                tab.click(toggle)
                tab.until('document.getElementById("__drawer").checked', 'the navigation drawer')
                time.sleep(.4)
            here = path_now()
            link = where('.md-sidebar--primary .md-nav__link[href]:not([href^="#"]):not([href="."])'
                         ':not(.md-nav__link--active)', 'navigation link')
            tab.screenshot(out / f'{stem}-nav.png')
            tab.click(link)
            followed = tab.until(f'location.pathname + location.hash !== {json.dumps(here)} && '
                                 'location.pathname', 'the navigation link to load')
            result['navigation'] = {'drawer': bool(toggle), 'link': link[4], 'opened': followed}

            # Search: open it, type, wait for results, then open the first one.
            tab.open(url)
            opener = tab.js(WHERE % json.dumps('label.md-header__button[for="__search"]'))
            tab.click(opener or where('.md-search__input', 'search box'))
            tab.until('document.activeElement && document.activeElement.matches(".md-search__input")',
                      'the search box to take focus')
            tab.type(SEARCH_TERM)
            tab.until('document.querySelectorAll(".md-search-result__item").length',
                      f'search results for {SEARCH_TERM!r}')
            time.sleep(.5)  # results render in batches
            count = tab.js('document.querySelectorAll(".md-search-result__item").length')
            tab.screenshot(out / f'{stem}-search.png')
            here = path_now()
            tab.click(where('.md-search-result__link', 'search result'))
            opened = tab.until(f'location.pathname + location.hash !== {json.dumps(here)} && '
                               '(location.pathname + location.hash)', 'the search result to open')
            result['search'] = {'query': SEARCH_TERM, 'results': count, 'opened': opened}

            # Copy: press the first code block's copy button and read the clipboard back.
            tab.open(url)
            tab.send('Browser.grantPermissions', {'origin': base.rstrip('/'),
                     'permissions': ['clipboardReadWrite', 'clipboardSanitizedWrite']}, session=False)
            button = where('.md-code__button[data-md-type="copy"]', 'code-copy button')
            expected = tab.js('document.querySelector(".md-code__button[data-md-type=copy]")'
                              '.closest("pre").querySelector("code").innerText')
            tab.click(button)
            copied = tab.until('navigator.clipboard.readText()', 'the clipboard to fill')
            tab.screenshot(out / f'{stem}-copy.png')
            if copied.strip() != expected.strip():
                raise CaptureError(f'{page}: the copy button put different text on the clipboard')
            result['copy'] = {'button': button[2:4], 'lines': len(copied.strip().splitlines())}
    return result


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
    parser.add_argument('--zoom', type=int, default=100, metavar='PERCENT',
                        help="Chrome's own page zoom, e.g. 200; not a viewport or device-scale change")
    parser.add_argument('--controls', action='store_true',
                        help='also open the navigation, search and copy a code block with real input')
    args = parser.parse_args(argv)
    try:
        chrome = find_chrome(args.chrome)
        if any(w < MIN_WINDOW for w in (args.widths or (390,))):
            find_ffmpeg()
        pages, widths = args.pages or DEFAULT_PAGES, args.widths or (1440, 390)
        schemes = args.schemes or ('light', 'dark')
        results = capture(args.site, args.out, pages, widths, schemes, args.height, chrome, args.full,
                          args.virtual_time, args.zoom)
        controls = [check_controls(args.site, args.out, page, width, args.height or 900, scheme,
                                   args.zoom, chrome)
                    for page in pages for width in widths for scheme in schemes] if args.controls else []
    except CaptureError as exc:
        print(f'capture_site: {exc}', file=sys.stderr)
        return 2
    failed = False
    for r in results:
        flag = 'OVERFLOW' if r['overflow'] else 'ok'
        failed |= r['overflow']
        print(f"{flag:8} {r['width']:>4} {r['scheme']:5} zoom={r['zoom']}% scroll={r['scroll_width']} "
              f"viewport={r['viewport_width']} {r['file']}")
    for c in controls:
        nav, search, copy = c['navigation'], c['search'], c['copy']
        print(f"controls {c['width']:>4} {c['scheme']:5} zoom={c['zoom']}% viewport={c['viewport_width']} "
              f"dpr={c['device_pixel_ratio']} {c['page']}\n"
              f"  navigation: {'drawer' if nav['drawer'] else 'sidebar'} link {nav['link']} opened {nav['opened']}\n"
              f"  search: {search['results']} results for {search['query']!r}, first opened {search['opened']}\n"
              f"  copy: {copy['button'][0]}x{copy['button'][1]}px button, clipboard matched "
              f"{copy['lines']} line(s)")
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
