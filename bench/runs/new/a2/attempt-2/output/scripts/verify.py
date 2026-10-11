#!/usr/bin/env python3
"""Check out/ against the output contract, recomputing the expected values from data/
independently of scripts/build.py. Prints one line per check; exits 1 on any failure.

    python3 scripts/verify.py [--root DIR]   # DIR holds data/, vendor/leaflet/ and out/ (default: repo)
"""
from __future__ import annotations

import argparse
import filecmp
import json
import math
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'out'  # main() rebinds both for --root
TOL = 1e-9
TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
ATTRIBUTION = '© OpenStreetMap contributors'

failures = []


def check(ok, label, detail=''):
    print(('PASS ' if ok else 'FAIL ') + label + (f' -- {detail}' if detail and not ok else ''))
    if not ok:
        failures.append(label)
    return ok


def distance_km(a_lat, a_lon, b_lat, b_lon):
    # atan2 form of the haversine formula, R = 6371.0 km
    la1, la2 = math.radians(a_lat), math.radians(b_lat)
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2)
    return 6371.0 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def expected(chosen=frozenset()):
    """Recompute the contract values. `chosen` is data.json's station ids, used only to settle stations
    whose computed distance is within roundoff (1e-9 km) of the limit, where formulas may disagree."""
    stations_doc = json.loads((ROOT / 'data/stations.json').read_text(encoding='utf-8'))
    records = json.loads((ROOT / 'data/prices.json').read_text(encoding='utf-8'))['records']
    c = stations_doc['centre']
    dist = {s['id']: distance_km(c['lat'], c['lon'], s['lat'], s['lon']) for s in stations_doc['stations']}
    boundary = {sid for sid, d in dist.items() if abs(d - 10.0) <= 1e-9}
    inside = {sid for sid, d in dist.items() if d <= 10.0 and sid not in boundary} | (boundary & set(chosen))
    outside = set(dist) - inside
    for sid in sorted(boundary):
        print(f'NOTE {sid} is {dist[sid]!r} km from the centre; following data.json ({"in" if sid in inside else "out"})')
    # Records sharing an instant are ordered by file position, so the later one counts as more recent.
    e10 = [(i, r) for i, r in enumerate(records) if r['fuel'] == 'E10']
    order = {id(r): (datetime.fromisoformat(r['recorded_at']), i) for i, r in e10}
    history = {sid: sorted((r for _, r in e10 if r['station_id'] == sid), key=lambda r: order[id(r)]) for sid in inside}
    listed = {sid: (hist[-1]['price_cpl'] if hist else None) for sid, hist in history.items()}
    priced = {sid: p for sid, p in listed.items() if p is not None}
    cheapest = min(priced.values())
    best = sorted(sid for sid, p in priced.items() if p == cheapest)
    days = sorted({re.match(r'\d{4}-\d{2}-\d{2}', r['recorded_at']).group(0) for _, r in e10})
    overall = []
    for day in days:
        prices = []
        for sid in sorted(inside):
            upto = [r for r in history[sid] if r['recorded_at'][:10] <= day]
            if upto:
                prices.append(max(upto, key=lambda r: order[id(r)])['price_cpl'])
        overall.append((day, math.fsum(prices) / len(prices) if prices else None))
    names = {s['id']: s['name'] for s in stations_doc['stations']}
    pos = {s['id']: (s['lat'], s['lon']) for s in stations_doc['stations']}
    return dict(dist=dist, inside=inside, outside=outside, history=history, listed=listed, best=best,
                overall=overall, names=names, pos=pos)


class Page(HTMLParser):
    """Collect what the contract cares about from index.html."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.recommended = []
        self.scripts, self.styles, self.inline_style = [], [], ''
        self.items = {}          # station id -> {'text': str, 'rows': [(datetime attr, price text)]}
        self.overall_rows = []   # [(date attr, mean text)]
        self._item = None
        self._depth = 0
        self._in_style = False
        self._row = None         # current history/overall row being read
        self._cell = False
        self._field = None       # 'price' or 'meta' paragraph of the current station entry
        self.ids = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'id' in a:
            self.ids.append(a['id'])
        if 'data-recommended-station' in a:
            self.recommended.append((tag, a['data-recommended-station']))
        if tag == 'script' and a.get('src'):
            self.scripts.append(a['src'])
        if tag == 'link' and 'stylesheet' in (a.get('rel') or '').split():
            self.styles.append(a.get('href') or '')
        if tag == 'style':
            self._in_style = True
        classes = (a.get('class') or '').split()
        if tag == 'tr' and ('hist-row' in classes or 'overall-row' in classes):
            self._row = {'kind': 'hist' if 'hist-row' in classes else 'overall', 'when': None, 'value': ''}
        if self._row is not None and tag == 'time':
            self._row['when'] = a.get('datetime')
        if self._row is not None and tag == 'td' and 'n' in classes:
            self._cell = True
        if self._item is not None:
            if tag == 'li':
                self._depth += 1
            if tag == 'p' and ('station-price' in classes or 'station-meta' in classes):
                self._field = 'price' if 'station-price' in classes else 'meta'
        elif tag == 'li' and a.get('data-station-id'):
            self._item = a['data-station-id']
            self._depth = 1
            self.items[self._item] = {'text': '', 'price': '', 'meta': '', 'rows': [], 'id': a.get('id')}

    def handle_endtag(self, tag):
        if tag == 'style':
            self._in_style = False
        if tag == 'td':
            self._cell = False
        if tag == 'p':
            self._field = None
        if tag == 'tr' and self._row is not None:
            row = (self._row['when'], self._row['value'].strip())
            if self._row['kind'] == 'overall':
                self.overall_rows.append(row)
            elif self._item is not None:
                self.items[self._item]['rows'].append(row)
            self._row = None
        if self._item is not None and tag == 'li':
            self._depth -= 1
            if self._depth == 0:
                self._item = None

    def handle_data(self, data):
        if self._cell and self._row is not None:
            self._row['value'] += data
        if self._in_style:
            self.inline_style += data
        if self._item is not None:
            self.items[self._item]['text'] += data
            if self._field:
                self.items[self._item][self._field] += data


def is_local(ref):
    return bool(ref) and not re.match(r'^([a-z][a-z0-9+.-]*:|//|/)', ref, re.I)


def main():
    global ROOT, OUT
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT, help='directory holding data/, vendor/leaflet/ and out/')
    ROOT = parser.parse_args().root.resolve()
    OUT = ROOT / 'out'
    check(OUT.is_dir(), 'out/ exists')
    data = json.loads((OUT / 'data.json').read_text(encoding='utf-8'))
    exp = expected({s.get('id') for s in data.get('stations', [])})

    # data.json shape and values
    check(set(data) >= {'recommendation', 'stations', 'overall_history'}, 'data.json has the top-level keys')
    stations = data.get('stations', [])
    ids = [s.get('id') for s in stations]
    check(len(ids) == len(set(ids)), 'data.json station ids are unique')
    check(set(ids) == exp['inside'], 'data.json lists exactly the in-range stations',
          f'extra {sorted(set(ids) - exp["inside"])}, missing {sorted(exp["inside"] - set(ids))}')
    recommended = data.get('recommendation', {}).get('station_id')
    check(recommended in exp['best'], 'recommendation is the cheapest in-range station',
          f'got {data.get("recommendation")}, expected one of {exp["best"]}')
    for s in stations:
        sid = s.get('id')
        if sid not in exp['inside']:
            continue
        keys = {'id', 'name', 'lat', 'lon', 'distance_km', 'listed_price_cpl', 'history'}
        check(keys <= set(s), f'{sid}: has every station field', f'missing {sorted(keys - set(s))}')
        check(s.get('name') == exp['names'][sid] and (s.get('lat'), s.get('lon')) == exp['pos'][sid],
              f'{sid}: name and position match data/')
        check(abs(s.get('distance_km', -1) - exp['dist'][sid]) <= TOL, f'{sid}: distance_km',
              f'{s.get("distance_km")} vs {exp["dist"][sid]}')
        check(s.get('listed_price_cpl') == exp['listed'].get(sid), f'{sid}: listed price is the latest E10 record',
              f'{s.get("listed_price_cpl")} vs {exp["listed"].get(sid)}')
        want = [{'recorded_at': r['recorded_at'], 'price_cpl': r['price_cpl']} for r in exp['history'][sid]]
        got = [{'recorded_at': h.get('recorded_at'), 'price_cpl': h.get('price_cpl')} for h in s.get('history', [])]
        check(got == want, f'{sid}: history is the full E10 history in time order', f'{len(got)} vs {len(want)} records')
    got_overall = [(p.get('date'), p.get('mean_price_cpl')) for p in data.get('overall_history', [])]
    check([d for d, _ in got_overall] == [d for d, _ in exp['overall']], 'overall_history has one point per E10 day',
          f'{[d for d, _ in got_overall]}')
    for (day, mean), (_, want) in zip(got_overall, exp['overall']):
        ok = mean is None if want is None else isinstance(mean, (int, float)) and abs(mean - want) <= TOL
        check(ok, f'overall {day}: mean', f'{mean} vs {want}')

    # vendored Leaflet
    src, dst = ROOT / 'vendor/leaflet', OUT / 'vendor/leaflet'
    src_files = sorted(p.relative_to(src) for p in src.rglob('*') if p.is_file())
    dst_files = sorted(p.relative_to(dst) for p in dst.rglob('*') if p.is_file()) if dst.is_dir() else []
    check(src_files == dst_files and all(filecmp.cmp(src / p, dst / p, shallow=False) for p in src_files),
          'out/vendor/leaflet is a byte-identical copy of vendor/leaflet')

    # index.html
    index_text = (OUT / 'index.html').read_text(encoding='utf-8')
    page = Page()
    page.feed(index_text)
    check('vendor/leaflet/leaflet.css' in page.styles, 'index.html loads vendor/leaflet/leaflet.css by relative path')
    check('vendor/leaflet/leaflet.js' in page.scripts, 'index.html loads vendor/leaflet/leaflet.js by relative path')
    remote = [r for r in page.scripts + page.styles if not is_local(r)]
    check(not remote, 'no remote script or stylesheet', f'{remote}')
    check(all((OUT / r).is_file() for r in page.scripts + page.styles if is_local(r)), 'every loaded script and stylesheet exists')
    check(not re.search(r'@import|url\(\s*["\']?(https?:)?//', page.inline_style), 'inline CSS imports nothing remote')
    check(len(page.recommended) == 1 and page.recommended[0][1] == recommended,
          'exactly one element carries data-recommended-station with the recommended id', f'{page.recommended}')
    check(TILE_URL in index_text, 'map uses the OpenStreetMap tile URL')
    check(ATTRIBUTION in index_text, 'page carries the attribution "© OpenStreetMap contributors"')
    check(len(page.ids) == len(set(page.ids)), 'element ids are unique')

    loaded = index_text + ''.join((OUT / r).read_text(encoding='utf-8') for r in page.scripts
                                  if is_local(r) and not r.startswith('vendor/'))
    for sid in sorted(exp['inside']):
        check(sid in loaded, f'{sid}: id appears in index.html or a local script it loads')
        item = page.items.get(sid)
        if not check(item is not None, f'{sid}: listed on the page'):
            continue
        price = 'No E10 price' if exp['listed'][sid] is None else f'{exp["listed"][sid]:.1f} c/L'
        km = f'{exp["dist"][sid]:.2f} km away'
        shown_price, shown_meta = ''.join(item['price'].split()), ' '.join(item['meta'].split())
        check(shown_price == price.replace(' ', '') and km in shown_meta,
              f'{sid}: list entry shows price {price} and distance {km}', f'price {shown_price!r}, meta {shown_meta!r}')
        want_rows = [(r['recorded_at'], f'{r["price_cpl"]:.1f}') for r in reversed(exp['history'][sid])]
        check(item['rows'] == want_rows, f'{sid}: history table shows every E10 record with its price, newest first',
              f'first mismatch {next(((g, w) for g, w in zip(item["rows"], want_rows) if g != w), (len(item["rows"]), len(want_rows)))}')
    want_overall = [(day, '—' if mean is None else f'{mean:.2f}') for day, mean in exp['overall']]
    check(page.overall_rows == want_overall, 'daily averages table shows every day with its mean',
          f'first mismatch {next(((g, w) for g, w in zip(page.overall_rows, want_overall) if g != w), (len(page.overall_rows), len(want_overall)))}')

    data_js = (OUT / 'data.js').read_text(encoding='utf-8')
    m = re.match(r'window\.FUEL_DATA = (.*?);\n', data_js)
    check(bool(m) and json.loads(m.group(1)) == data, 'data.js carries the same data as data.json')

    # out-of-range ids anywhere under out/
    leaks = [(str(p.relative_to(OUT)), sid) for p in OUT.rglob('*') if p.is_file()
             for sid in sorted(exp['outside']) if sid.encode() in p.read_bytes()]
    check(not leaks, f'no out-of-range station id ({len(exp["outside"])} ids) appears under out/', f'{leaks}')

    print(f'\n{len(failures)} failure(s)' if failures else '\nall checks passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
