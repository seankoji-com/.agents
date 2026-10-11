#!/usr/bin/env python3
"""Absolute checks for a Task A output directory (E10 near Greenwich, NSW).

Inspects the emitted files statically; it never runs or renders the page. Four checks
gate (`required`): Leaflet is vendored, the station IDs are exactly the in-radius set,
price series exist for every station and for the overall history, and the
recommendation names the cheapest in-radius station. Other results are informational.

Usage: python3 bench/checks/task_a.py OUTPUT_DIR [--data DATA_DIR] [--json]
OUTPUT_DIR is the run's `out/` directory. DATA_DIR defaults to the frozen fixture data.
Exit status: 0 when every required check passes, 1 otherwise, 2 on bad usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / 'fixtures' / 'task_a' / 'workspace'
EARTH_RADIUS_KM = 6371.0
RADIUS_KM = 10.0
STATION_ID = re.compile(r'\bSTN-\d{4}\b')
CDN_HOSTS = ('unpkg.com', 'cdnjs.cloudflare.com', 'cdn.jsdelivr.net', 'ajax.googleapis.com', 'cdn.skypack.dev',
             'esm.sh', 'leafletjs.com/dist')
TEXT_SUFFIXES = {'.html', '.htm', '.js', '.mjs', '.json', '.css', '.svg', '.txt', '.md', '.csv'}
REMOTE_ATTR = re.compile(r'''(?:src|href)\s*=\s*["']((?:https?:)?//[^"']+)["']''', re.I)
RECOMMENDED = re.compile(r'''data-recommended-station\s*=\s*["']([^"']*)["']''')


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def expected(data_dir: Path) -> dict:
    """Derive the answer from the dataset, as the task prompt defines it."""
    geo = json.loads((data_dir / 'stations.json').read_text())
    records = json.loads((data_dir / 'prices.json').read_text())['records']
    centre = geo['centre']
    distance = {s['id']: haversine_km(centre['lat'], centre['lon'], s['lat'], s['lon']) for s in geo['stations']}
    inside = sorted(sid for sid, km in distance.items() if km <= RADIUS_KM)
    outside = sorted(sid for sid, km in distance.items() if km > RADIUS_KM)
    e10 = sorted((r for r in records if r['fuel'] == 'E10'), key=lambda r: datetime.fromisoformat(r['recorded_at']))
    listed = {}
    for record in e10:
        listed[record['station_id']] = record['price_cpl']
    ranked = sorted((listed[sid], sid) for sid in inside if sid in listed)
    if len(ranked) < 2 or ranked[0][0] == ranked[1][0]:
        raise ValueError('dataset has no unique cheapest in-radius station')
    days = sorted({datetime.fromisoformat(r['recorded_at']).date().isoformat() for r in e10})
    overall, latest = [], {}
    queue = list(e10)
    for day in days:
        while queue and datetime.fromisoformat(queue[0]['recorded_at']).date().isoformat() <= day:
            record = queue.pop(0)
            if record['station_id'] in inside:
                latest[record['station_id']] = record['price_cpl']
        if latest:
            overall.append({'date': day, 'mean_price_cpl': round(sum(latest.values()) / len(latest), 4)})
    return {'in_radius': inside, 'out_of_radius': outside, 'cheapest': ranked[0][1],
            'listed_price_cpl': {sid: listed[sid] for sid in inside},
            'distance_km': {sid: round(km, 4) for sid, km in sorted(distance.items())},
            'overall_history': overall}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def texts(out: Path) -> dict:
    """Every emitted text file except the vendored Leaflet itself."""
    found = {}
    for path in sorted(out.rglob('*')):
        rel = path.relative_to(out).as_posix()
        if not path.is_file() or rel.startswith('vendor/leaflet/') or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        found[rel] = path.read_text(errors='replace')
    return found


def number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check(out: Path, data_dir: Path) -> list:
    want = expected(data_dir)
    results = []

    def add(name, ok, detail, required=True):
        results.append({'check': name, 'required': required, 'ok': bool(ok), 'detail': detail})

    index = out / 'index.html'
    page = index.read_text(errors='replace') if index.is_file() else ''
    files = texts(out)
    try:
        data = json.loads((out / 'data.json').read_text())
        if not isinstance(data, dict):
            raise ValueError('top level is not an object')
    except (OSError, ValueError) as exc:
        data = {}
        add('data_json', False, f'out/data.json unreadable: {exc}', required=False)

    # 1. Leaflet is vendored: the fixture's files, loaded by relative path, and no CDN.
    problems = []
    for name in ('leaflet.js', 'leaflet.css'):
        copy = out / 'vendor' / 'leaflet' / name
        if not copy.is_file():
            problems.append(f'missing out/vendor/leaflet/{name}')
        elif sha256(copy) != sha256(FIXTURE / 'vendor' / 'leaflet' / name):
            problems.append(f'out/vendor/leaflet/{name} differs from the provided Leaflet')
        if not re.search(r'''(?:src|href)\s*=\s*["'](?:\./)?vendor/leaflet/''' + re.escape(name) + r'''["']''', page):
            problems.append(f'index.html does not load vendor/leaflet/{name} by relative path')
    for rel, text in files.items():
        lowered = text.lower()
        problems += [f'{rel} references CDN host {host}' for host in CDN_HOSTS if host in lowered]
        problems += [f'{rel} loads remote {url}' for url in REMOTE_ATTR.findall(text) if 'leaflet' in url.lower()]
    add('leaflet_vendored', not problems, problems or 'vendored, loaded relatively, no CDN')

    # 2. Station IDs: every in-radius ID is listed; no out-of-radius ID appears anywhere.
    listed_ids = [s.get('id') for s in data.get('stations', []) if isinstance(s, dict)]
    missing = sorted(set(want['in_radius']) - set(listed_ids))
    extra = sorted(set(listed_ids) - set(want['in_radius']))
    leaked = sorted({sid for text in files.values() for sid in STATION_ID.findall(text)} & set(want['out_of_radius']))
    add('station_ids', not (missing or extra or leaked) and bool(page),
        {'missing_in_radius': missing, 'unexpected_in_data_json': extra, 'out_of_radius_present': leaked,
         'index_html_present': bool(page)})

    # 3. A price series per station and for the overall history.
    empty = []
    for station in data.get('stations', []):
        history = station.get('history') if isinstance(station, dict) else None
        if not isinstance(history, list) or not history or not all(
                isinstance(p, dict) and number(p.get('price_cpl')) and p.get('recorded_at') for p in history):
            empty.append(station.get('id') if isinstance(station, dict) else repr(station))
    overall = data.get('overall_history')
    overall_ok = isinstance(overall, list) and bool(overall) and all(
        isinstance(p, dict) and number(p.get('mean_price_cpl')) and p.get('date') for p in overall)
    add('price_series', not empty and overall_ok and not missing,
        {'stations_without_series': sorted(map(str, empty)), 'overall_history_present': overall_ok})

    # 4. The recommendation names the cheapest in-radius station, in data.json and on the page.
    chosen = (data.get('recommendation') or {}).get('station_id') if isinstance(data.get('recommendation'), dict) else None
    marked = RECOMMENDED.findall(page)
    add('recommendation', chosen == want['cheapest'] and marked == [want['cheapest']],
        {'expected': want['cheapest'], 'data_json': chosen, 'page_markers': marked})

    # Informational: values and map details the grader may want to see.
    by_id = {s.get('id'): s for s in data.get('stations', []) if isinstance(s, dict)}
    wrong_listed = sorted(sid for sid, price in want['listed_price_cpl'].items()
                          if sid in by_id and by_id[sid].get('listed_price_cpl') != price)
    add('listed_prices_match', not wrong_listed, {'mismatched': wrong_listed}, required=False)
    got = {p.get('date'): p.get('mean_price_cpl') for p in overall} if overall_ok else {}
    off = [p['date'] for p in want['overall_history']
           if not number(got.get(p['date'])) or abs(got[p['date']] - p['mean_price_cpl']) > 0.05]
    add('overall_history_values', overall_ok and not off and len(got) == len(want['overall_history']),
        {'dates_missing_or_off_by_more_than_0.05': off, 'expected_days': len(want['overall_history'])},
        required=False)
    everything = '\n'.join(files.values())
    add('osm_tiles_and_attribution', 'tile.openstreetmap.org' in everything and 'OpenStreetMap' in everything,
        'tile URL and attribution text found' if 'tile.openstreetmap.org' in everything else 'not found',
        required=False)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('--data', type=Path, default=FIXTURE / 'data')
    parser.add_argument('--json', action='store_true', help='print results as JSON')
    args = parser.parse_args(argv)
    if not args.output_dir.is_dir():
        parser.error(f'{args.output_dir} is not a directory')
    results = check(args.output_dir, args.data)
    passed = all(r['ok'] for r in results if r['required'])
    if args.json:
        print(json.dumps({'passed': passed, 'results': results}, indent=2))
    else:
        for r in results:
            label = 'PASS' if r['ok'] else ('FAIL' if r['required'] else 'info')
            print(f"{label:4} {r['check']}: {json.dumps(r['detail'])}")
        print('passed' if passed else 'failed')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
