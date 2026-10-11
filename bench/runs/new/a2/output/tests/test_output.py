"""Acceptance tests for out/: recompute every rule from data/ independently of
scripts/build.py and compare with what was generated."""
import filecmp
import json
import math
import re
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'out'
TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
ATTRIBUTION = '© OpenStreetMap contributors'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def distance_km(lat1, lon1, lat2, lon2, radius=6371.0):
    # atan2 form of the haversine formula, deliberately not the build script's asin form.
    p1, p2, dp, dl = map(math.radians, (lat1, lat2, lat2 - lat1, lon2 - lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def utc(stamp):
    return datetime.fromisoformat(stamp).astimezone(timezone.utc)


MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


def written_day(stamp):
    """'2026-09-14...' -> '14 Sep 2026', from the text as written."""
    return f'{int(stamp[8:10])} {MONTHS[int(stamp[5:7]) - 1]} {stamp[:4]}'


def written_when(stamp):
    """'2026-09-14T14:15:00+10:00' -> '14 Sep 2026, 14:15', local time as written."""
    return f'{written_day(stamp)}, {stamp[11:16]}'


def polyline(svg):
    points = re.search(r'<polyline[^>]*\bpoints="([^"]*)"', svg).group(1).split()
    return [tuple(float(v) for v in point.split(',')) for point in points]


def assert_plots(test, points, values, label, strict=True):
    """Points run left to right (records close in time may share a rounded x unless
    strict), and a higher value always sits higher (smaller y)."""
    test.assertEqual(len(points), len(values), label)
    xs = [x for x, _y in points]
    test.assertEqual(xs, sorted(set(xs)) if strict else sorted(xs), f'{label}: x out of order')
    for (_xa, ya), a in zip(points, values):
        for (_xb, yb), b in zip(points, values):
            if a > b:
                test.assertLess(ya, yb, f'{label}: {a} plotted below {b}')
            elif a == b:
                test.assertEqual(ya, yb, label)


class Expected:
    """The rules, written out from the task text."""

    def __init__(self):
        stations = load(ROOT / 'data' / 'stations.json')
        records = load(ROOT / 'data' / 'prices.json')['records']
        centre = stations['centre']
        self.distance = {s['id']: distance_km(centre['lat'], centre['lon'], s['lat'], s['lon'])
                         for s in stations['stations']}
        self.stations = {s['id']: s for s in stations['stations']}
        self.in_range = {sid for sid, d in self.distance.items() if d <= 10.0}
        self.out_of_range = set(self.distance) - self.in_range
        self.e10 = [r for r in records if r['fuel'] == 'E10']
        self.history = {sid: sorted((r for r in self.e10 if r['station_id'] == sid), key=lambda r: utc(r['recorded_at']))
                        for sid in self.in_range}
        self.listed = {sid: max(h, key=lambda r: utc(r['recorded_at']))['price_cpl']
                       for sid, h in self.history.items() if h}
        cheapest = min(self.listed.values())
        self.best = sorted((sid for sid, p in self.listed.items() if p == cheapest),
                           key=lambda sid: (self.distance[sid], sid))[0]
        self.days = sorted({r['recorded_at'][:10] for r in self.e10})
        self.overall = []
        for day in self.days:
            prices = []
            for sid in self.in_range:
                upto = [r for r in self.history[sid] if r['recorded_at'][:10] <= day]
                if upto:
                    prices.append(max(upto, key=lambda r: utc(r['recorded_at']))['price_cpl'])
            self.overall.append((day, sum(prices) / len(prices) if prices else None))


class Page(HTMLParser):
    """Collect elements with attributes, plus script/stylesheet references."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.scripts = []
        self.stylesheets = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        if tag == 'script' and attrs.get('src'):
            self.scripts.append(attrs['src'])
        if tag == 'link' and 'stylesheet' in (attrs.get('rel') or '').split():
            self.stylesheets.append(attrs.get('href') or '')

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        self.text.append(data)


def parse_index():
    page = Page()
    page.feed((OUT / 'index.html').read_text(encoding='utf-8'))
    return page


def is_local(ref):
    return not re.match(r'^([a-z][a-z0-9+.-]*:|//)', ref, re.I)


class DataJsonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exp = Expected()
        cls.data = load(OUT / 'data.json')

    def test_shape(self):
        self.assertEqual(set(self.data), {'recommendation', 'stations', 'overall_history'})
        self.assertEqual(set(self.data['recommendation']), {'station_id'})
        for station in self.data['stations']:
            self.assertEqual(set(station), {'id', 'name', 'lat', 'lon', 'distance_km', 'listed_price_cpl', 'history'})
            for entry in station['history']:
                self.assertEqual(set(entry), {'recorded_at', 'price_cpl'})
        for point in self.data['overall_history']:
            self.assertEqual(set(point), {'date', 'mean_price_cpl'})

    def test_in_range_stations_only(self):
        ids = [s['id'] for s in self.data['stations']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), self.exp.in_range)
        self.assertEqual(len(ids), 21)
        for station in self.data['stations']:
            source = self.exp.stations[station['id']]
            self.assertEqual((station['name'], station['lat'], station['lon']),
                             (source['name'], source['lat'], source['lon']))
            self.assertAlmostEqual(station['distance_km'], self.exp.distance[station['id']], places=9)
            self.assertLessEqual(station['distance_km'], 10.0)

    def test_listed_price_is_latest_e10(self):
        for station in self.data['stations']:
            self.assertEqual(station['listed_price_cpl'], self.exp.listed[station['id']], station['id'])

    def test_full_e10_history(self):
        for station in self.data['stations']:
            expected = [{'recorded_at': r['recorded_at'], 'price_cpl': r['price_cpl']}
                        for r in self.exp.history[station['id']]]
            self.assertEqual(station['history'], expected, station['id'])

    def test_recommendation(self):
        self.assertEqual(self.data['recommendation']['station_id'], self.exp.best)
        # Pinned from inspecting data/: guards against a shared mistake in both computations.
        self.assertEqual(self.exp.best, 'STN-0007')
        self.assertEqual(self.exp.listed['STN-0007'], 179.9)

    def test_overall_history(self):
        got = [(p['date'], p['mean_price_cpl']) for p in self.data['overall_history']]
        self.assertEqual([d for d, _ in got], self.exp.days)
        for (day, mean), (_, want) in zip(got, self.exp.overall):
            self.assertAlmostEqual(mean, want, places=9, msg=day)


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exp = Expected()
        cls.data = load(OUT / 'data.json')
        cls.html = (OUT / 'index.html').read_text(encoding='utf-8')
        cls.page = parse_index()
        cls.local_scripts = [(OUT / src).read_text(encoding='utf-8') for src in cls.page.scripts if is_local(src)]

    def test_single_recommendation_marker(self):
        marked = [attrs for _tag, attrs in self.page.elements if 'data-recommended-station' in attrs]
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0]['data-recommended-station'], self.exp.best)
        self.assertEqual(self.html.count('data-recommended-station'), 1)

    def test_vendored_leaflet_by_relative_path(self):
        self.assertIn('vendor/leaflet/leaflet.css', self.page.stylesheets)
        self.assertIn('vendor/leaflet/leaflet.js', self.page.scripts)
        for ref in self.page.scripts + self.page.stylesheets:
            self.assertTrue(is_local(ref), ref)
            self.assertTrue((OUT / ref).is_file(), ref)
        for tag, attrs in self.page.elements:
            if tag in ('script', 'img', 'iframe') and attrs.get('src'):
                self.assertTrue(is_local(attrs['src']), f'{tag} {attrs}')
            if tag == 'link' and attrs.get('href'):
                self.assertTrue(is_local(attrs['href']), f'{tag} {attrs}')
        self.assertNotRegex(self.html, r'@import')

    def test_vendor_copy_unchanged(self):
        src, dst = ROOT / 'vendor' / 'leaflet', OUT / 'vendor' / 'leaflet'
        files = sorted(p.relative_to(src) for p in src.rglob('*') if p.is_file())
        copied = sorted(p.relative_to(dst) for p in dst.rglob('*') if p.is_file())
        self.assertEqual(files, copied)
        for rel in files:
            self.assertTrue(filecmp.cmp(src / rel, dst / rel, shallow=False), rel)

    def test_osm_tiles_and_attribution(self):
        self.assertIn(TILE_URL, self.html)
        self.assertIn(ATTRIBUTION, self.html)
        self.assertIn(ATTRIBUTION, ''.join(self.page.text))

    def test_every_in_range_id_present(self):
        corpus = self.html + ''.join(self.local_scripts)
        for sid in self.exp.in_range:
            self.assertIn(sid, corpus)

    def test_no_out_of_range_id_anywhere_in_out(self):
        self.assertEqual(len(self.exp.out_of_range), 4)
        for path in OUT.rglob('*'):
            if path.is_file():
                blob = path.read_bytes()
                for sid in self.exp.out_of_range:
                    self.assertNotIn(sid.encode(), blob, f'{sid} in {path}')

    def station_blocks(self):
        blocks = re.split(r'(?=<li class="station)', self.html)
        return {sid: next(b for b in blocks if f'data-station-id="{sid}"' in b) for sid in self.exp.in_range}

    def test_recommendation_card_shows_best_station(self):
        card = re.search(r'<(\w+)[^>]*data-recommended-station="[^"]*"[^>]*>(.*?)</\1>', self.html, re.S).group(2)
        best = self.exp.best
        self.assertEqual(re.search(r'class="big">([^<]*)<', card).group(1), f'{self.exp.listed[best]:.1f}')
        self.assertIn(f'>{self.exp.stations[best]["name"]}<', card)
        self.assertIn(f'{self.exp.distance[best]:.2f} km', card)

    def test_list_shows_price_distance_history(self):
        items = {attrs['data-station-id'] for tag, attrs in self.page.elements
                 if tag == 'li' and 'data-station-id' in attrs}
        self.assertEqual(items, self.exp.in_range)
        for sid, block in self.station_blocks().items():
            price = re.search(r'<div class="price"><span class="value">([^<]*)</span>', block).group(1)
            distance = re.search(r'<div class="dist"><span class="value">([^<]*)</span>', block).group(1)
            self.assertEqual(price, f'{self.exp.listed[sid]:.1f}', sid)
            self.assertEqual(distance, f'{self.exp.distance[sid]:.2f}', sid)
            rows = re.findall(r'<tr><td>([^<]*)</td><td class="num">([^<]*)</td></tr>', block)
            newest_first = [(written_when(r['recorded_at']), f'{r["price_cpl"]:.1f}')
                            for r in reversed(self.exp.history[sid])]
            self.assertEqual(rows, newest_first, sid)

    def test_sparklines_plot_each_history(self):
        for sid, block in self.station_blocks().items():
            points = polyline(re.search(r'<svg class="spark".*?</svg>', block, re.S).group(0))
            history = self.exp.history[sid]
            # A step line: one point per record, a riser before each later record, and a tail.
            self.assertEqual(len(points), 2 * len(history), sid)
            records = [points[0]] + [points[2 * i] for i in range(1, len(history))]
            assert_plots(self, records, [r['price_cpl'] for r in history], sid, strict=False)
            self.assertEqual(points[-1][1], records[-1][1], sid)

    def test_overall_chart_plots_every_day(self):
        chart = re.search(r'<svg class="chart".*?</svg>', self.html, re.S).group(0)
        means = [mean for _day, mean in self.exp.overall]
        self.assertEqual(chart.count('<circle'), len(means))
        assert_plots(self, polyline(chart), means, 'overall')
        table = re.search(r'<section class="overall".*?</section>', self.html, re.S).group(0)
        rows = re.findall(r'<tr><td>([^<]*)</td><td class="num">([^<]*)</td></tr>', table)
        self.assertEqual(rows, [(written_day(day), f'{mean:.2f}') for day, mean in self.exp.overall])

    def test_data_js_matches_data_json(self):
        text = (OUT / 'data.js').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('window.E10_DATA = '))
        self.assertEqual(json.loads(text[len('window.E10_DATA = '):].rstrip().rstrip(';')), self.data)
        self.assertIn('data.js', self.page.scripts)


if __name__ == '__main__':
    unittest.main()
