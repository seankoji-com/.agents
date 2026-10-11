#!/usr/bin/env python3
"""Open out/index.html from disk (file://) in headless Chrome and check the rendered DOM.

    python3 tests/render_check.py

Set RENDER_SCREENSHOT=/path/shot.png to also save a screenshot. Exits 0 on pass,
1 on a failed assertion, 127 when no Chrome/Chromium binary is available.
Host resolution is blocked, so the check makes no network requests: map tiles do not
load and nothing here depends on them. The Chrome profile lives in a temporary directory
(honours TMPDIR).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / 'out' / 'index.html'
BROWSERS = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')


def chrome(binary, profile, *extra):
    argv = [binary, '--headless=new', '--no-sandbox', '--disable-gpu', '--no-first-run',
            '--no-default-browser-check', '--disable-crash-reporter', '--disable-breakpad',
            '--disable-background-networking', '--disable-component-update', '--no-pings',
            '--host-resolver-rules=MAP * ~NOTFOUND', f'--user-data-dir={profile}', '--window-size=1280,2200',
            '--virtual-time-budget=8000', '--enable-logging=stderr', '--v=0', *extra, INDEX.as_uri()]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120)


def main():
    binary = next((b for b in BROWSERS if shutil.which(b)), None)
    if not binary:
        print('no Chrome/Chromium binary found', file=sys.stderr)
        return 127
    data = json.loads((ROOT / 'out' / 'data.json').read_text(encoding='utf-8'))
    ids = [s['id'] for s in data['stations']]
    failures = []
    with tempfile.TemporaryDirectory() as profile:
        result = chrome(binary, profile, '--dump-dom')
        dom = result.stdout
        errors = [line for line in result.stderr.splitlines()
                  if 'CONSOLE' in line and re.search(r'Uncaught|TypeError|ReferenceError|SyntaxError', line)]
        shot = os.environ.get('RENDER_SCREENSHOT')
        if shot:
            chrome(binary, profile, f'--screenshot={shot}')
    checks = {
        'Leaflet initialised the map container': 'leaflet-container' in dom,
        f'map script added {len(ids)} station markers': f'data-map-markers="{len(ids)}"' in dom,
        'station + centre markers drawn as vector paths': dom.count('leaflet-interactive') >= len(ids) + 1,
        'attribution control shows © OpenStreetMap contributors':
            re.search(r'leaflet-control-attribution.*?(©|&copy;) OpenStreetMap contributors', dom, re.S) is not None,
        'tile layer requests tile.openstreetmap.org': 'tile.openstreetmap.org' in dom,
        'exactly one recommended-station marker': dom.count('data-recommended-station=') == 1,
        'recommended station is ' + data['recommendation']['station_id']:
            f'data-recommended-station="{data["recommendation"]["station_id"]}"' in dom,
        'every in-range station listed': all(f'data-station-id="{sid}"' in dom for sid in ids),
        'overall history chart rendered': '<svg class="chart"' in dom,
        'no uncaught script errors': not errors,
    }
    for name, ok in checks.items():
        print(('PASS ' if ok else 'FAIL ') + name)
        if not ok:
            failures.append(name)
    for line in errors:
        print('console:', line)
    if not dom:
        print('chrome stderr tail:', result.stderr[-2000:])
    print(f'{len(checks) - len(failures)}/{len(checks)} checks passed ({binary}, {INDEX.as_uri()})')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
