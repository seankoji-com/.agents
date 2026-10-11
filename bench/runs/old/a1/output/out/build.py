#!/usr/bin/env python3
"""Build the E10 fuel page for Greenwich, NSW.

Reads ../data/stations.json and ../data/prices.json, copies ../vendor/leaflet,
and writes index.html, data.json and data.js next to this script, or into the
directory given as the first argument. style.css and app.js are hand-written
and live beside this script. Standard library only; the same inputs always
produce the same bytes.

    python3 out/build.py            # rebuild out/
    python3 out/build.py /tmp/x     # build elsewhere (style.css and app.js are not copied)
"""
import html
import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

EARTH_RADIUS_KM = 6371.0
RANGE_KM = 10.0
FUEL = 'E10'
FILL_LITRES = 50
TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
ATTRIBUTION = '© OpenStreetMap contributors'
ATTRIBUTION_HTML = '<a href="https://www.openstreetmap.org/copyright">' + ATTRIBUTION + '</a>'

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


# ---------------------------------------------------------------- rules

def haversine_km(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def parse_time(text):
    moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('recorded_at needs an offset: %r' % text)
    return moment


def compute(stations_doc, prices_doc):
    """Apply the page's rules and return the data.json document."""
    centre = stations_doc['centre']

    # E10 records per station, oldest first. Equal instants keep file order,
    # so the later record in the file counts as the more recent one.
    e10 = {}
    for index, record in enumerate(prices_doc['records']):
        if record['fuel'] != FUEL:
            continue
        e10.setdefault(record['station_id'], []).append((parse_time(record['recorded_at']), index, record))
    for records in e10.values():
        records.sort(key=lambda item: (item[0], item[1]))

    stations = []
    for station in stations_doc['stations']:
        distance = haversine_km(centre['lat'], centre['lon'], station['lat'], station['lon'])
        if distance > RANGE_KM:
            continue
        history = [{'recorded_at': r['recorded_at'], 'price_cpl': r['price_cpl']}
                   for _, _, r in e10.get(station['id'], [])]
        stations.append({
            'id': station['id'],
            'name': station['name'],
            'brand': station['brand'],
            'address': station['address'],
            'lat': station['lat'],
            'lon': station['lon'],
            'distance_km': distance,
            'listed_price_cpl': history[-1]['price_cpl'] if history else None,
            'history': history,
        })

    # Cheapest first; ties go to the nearer station, then the lower ID.
    stations.sort(key=lambda s: (s['listed_price_cpl'] is None, s['listed_price_cpl'] or 0,
                                 s['distance_km'], s['id']))
    priced = [s for s in stations if s['listed_price_cpl'] is not None]
    recommendation = {'station_id': priced[0]['id']} if priced else None

    # One point per date (as written) seen in any E10 record. A day before any
    # in-range station has a price would have an empty mean, so it is skipped.
    days = sorted({moment.date() for records in e10.values() for moment, _, _ in records})
    overall = []
    for day in days:
        latest = []
        for station in stations:
            seen = [item for item in e10.get(station['id'], []) if item[0].date() <= day]
            if seen:
                latest.append(max(seen, key=lambda item: (item[0], item[1]))[2]['price_cpl'])
        if latest:
            overall.append({'date': day.isoformat(), 'mean_price_cpl': sum(latest) / len(latest)})

    return {'recommendation': recommendation, 'stations': stations, 'overall_history': overall}


# ---------------------------------------------------------------- formatting

def esc(value):
    return html.escape(str(value), quote=True)


def cpl(value):
    return '%.1f' % value


def km(value):
    return '%.2f' % value


def when(text, year=False):
    """A recorded_at timestamp as written (no time zone conversion)."""
    moment = parse_time(text)
    hour = moment.hour % 12 or 12
    suffix = 'am' if moment.hour < 12 else 'pm'
    date = '%s %d %s' % (DAYS[moment.weekday()], moment.day, MONTHS[moment.month - 1])
    if year:
        date += ' %d' % moment.year
    return '%s, %d:%02d %s' % (date, hour, moment.minute, suffix)


def offset_label(text):
    offset = parse_time(text).strftime('%z')
    return 'UTC%s:%s' % (offset[:3], offset[3:])


def short_day(iso_date):
    day = datetime.strptime(iso_date, '%Y-%m-%d')
    return '%d %s' % (day.day, MONTHS[day.month - 1])


def long_day(iso_date):
    day = datetime.strptime(iso_date, '%Y-%m-%d')
    return '%s %d %s' % (DAYS[day.weekday()], day.day, MONTHS[day.month - 1])


def nice_step(span, intervals=5):
    for step in (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100):
        if span / step <= intervals:
            return step
    return 100.0


def num(value):
    return ('%.2f' % value).rstrip('0').rstrip('.')


# ---------------------------------------------------------------- charts

def overall_chart(points):
    width, height = 460, 280
    left, right, top, bottom = 46, 14, 30, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [p['mean_price_cpl'] for p in points]
    step = nice_step(max(max(values) - min(values), 1.0), 4)
    low = math.floor(min(values) / step) * step
    high = math.ceil(max(values) / step) * step
    if high - low < step:
        high = low + step
    count = len(points)

    def x(i):
        return left + (plot_w * i / (count - 1) if count > 1 else plot_w / 2)

    def y(v):
        return top + plot_h * (high - v) / (high - low)

    out = ['<svg class="chart-svg" id="overall-chart" viewBox="0 0 %d %d" role="img" '
           'aria-labelledby="overall-chart-desc" preserveAspectRatio="xMidYMid meet">' % (width, height)]
    first, last = points[0], points[-1]
    out.append('<desc id="overall-chart-desc">Area average E10 price by day, from %s c/L on %s to %s c/L on %s.</desc>'
               % (num(first['mean_price_cpl']), long_day(first['date']),
                  num(last['mean_price_cpl']), long_day(last['date'])))
    tick = low
    while tick <= high + 1e-9:
        ty = y(tick)
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.2f" y2="%.2f"/>' % (left, width - right, ty, ty))
        out.append('<text class="axis-label" x="%d" y="%.2f" text-anchor="end" dy="0.32em">%s</text>'
                   % (left - 8, ty, num(tick)))
        tick += step
    out.append('<line class="baseline" x1="%d" x2="%d" y1="%d" y2="%d"/>' % (left, width - right, top + plot_h, top + plot_h))
    # Label every k-th day counting back from the latest, so the newest day is always labelled.
    every = max(1, math.ceil(48 / (plot_w / max(count - 1, 1))))
    for i, point in enumerate(points):
        if (count - 1 - i) % every == 0:
            out.append('<text class="axis-label" x="%.2f" y="%d" text-anchor="middle">%s</text>'
                       % (x(i), top + plot_h + 20, short_day(point['date'])))
    out.append('<text class="axis-title" x="%d" y="%d">c/L</text>' % (left - 8, top - 16))
    path = ' '.join('%s%.2f,%.2f' % ('M' if i == 0 else 'L', x(i), y(v)) for i, v in enumerate(values))
    # The hit area sits under the points so their native <title> tooltips still work without JavaScript.
    out.append('<rect class="hit" x="%d" y="%d" width="%d" height="%d"/>' % (left, top, plot_w, plot_h))
    out.append('<line class="crosshair" id="overall-crosshair" x1="0" x2="0" y1="%d" y2="%d" visibility="hidden"/>'
               % (top, top + plot_h))
    out.append('<path class="series-line" d="%s"/>' % path)
    for i, point in enumerate(points):
        out.append('<circle class="series-point" cx="%.2f" cy="%.2f" r="4" data-index="%d" data-label="%s" '
                   'data-value="%s"><title>%s: %s c/L</title></circle>'
                   % (x(i), y(point['mean_price_cpl']), i, esc(long_day(point['date'])),
                      '%.2f' % point['mean_price_cpl'], esc(long_day(point['date'])),
                      '%.2f' % point['mean_price_cpl']))
    out.append('</svg>')
    return '\n'.join(out)


def sparkline(station, x_domain, y_domain):
    width, height, pad = 180, 44, 5
    history = station['history']
    if not history:
        return '<p class="muted">No E10 prices recorded.</p>'
    t0, t1 = x_domain
    lo, hi = y_domain

    def x(moment):
        return pad + (width - 2 * pad) * (moment.timestamp() - t0) / (t1 - t0)

    def y(price):
        return pad + (height - 2 * pad) * (hi - price) / (hi - lo)

    points = [(x(parse_time(h['recorded_at'])), y(h['price_cpl']), h) for h in history]
    # A listed price holds until the next record, so the line steps.
    d = 'M%.2f,%.2f' % points[0][:2]
    for (px, py, _), (nx, ny, _) in zip(points, points[1:]):
        d += ' H%.2f V%.2f' % (nx, ny)
    d += ' H%.2f' % (width - pad)
    first, last = history[0], history[-1]
    label = ('E10 price history for %s: %d records, from %s c/L on %s to %s c/L on %s'
             % (station['name'], len(history), cpl(first['price_cpl']), when(first['recorded_at']),
                cpl(last['price_cpl']), when(last['recorded_at'])))
    out = ['<svg class="spark" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (width, height, esc(label))]
    out.append('<path class="spark-line" d="%s"/>' % d)
    for px, py, h in points[:-1]:
        out.append('<circle class="spark-point" cx="%.2f" cy="%.2f" r="2"><title>%s: %s c/L</title></circle>'
                   % (px, py, esc(when(h['recorded_at'])), cpl(h['price_cpl'])))
    px, py, h = points[-1]
    out.append('<circle class="spark-last" cx="%.2f" cy="%.2f" r="3.5"><title>Listed now (%s): %s c/L</title></circle>'
               % (px, py, esc(when(h['recorded_at'])), cpl(h['price_cpl'])))
    out.append('</svg>')
    return ''.join(out)


# ---------------------------------------------------------------- page

def history_table(station):
    rows = []
    previous = None
    for h in station['history']:
        if previous is None:
            change = '<span class="muted">first</span>'
        else:
            delta = round(h['price_cpl'] - previous, 1)
            change = '0.0' if delta == 0 else ('+%.1f' % delta if delta > 0 else '−%.1f' % -delta)
        rows.append('<tr><td><time datetime="%s">%s</time></td><td class="num">%s</td><td class="num">%s</td></tr>'
                    % (esc(h['recorded_at']), esc(when(h['recorded_at'])), cpl(h['price_cpl']), change))
        previous = h['price_cpl']
    return ('<table class="history"><thead><tr><th scope="col">Recorded</th><th scope="col" class="num">E10 c/L</th>'
            '<th scope="col" class="num">Change</th></tr></thead><tbody>%s</tbody></table>' % ''.join(rows))


def station_item(station, best_id, x_domain, y_domain):
    sid = station['id']
    best = sid == best_id
    price = station['listed_price_cpl']
    history = station['history']
    parts = ['<li class="station%s" id="station-%s" data-station-id="%s" data-price="%s" data-distance="%r">'
             % (' is-best' if best else '', esc(sid), esc(sid), '' if price is None else cpl(price),
                station['distance_km'])]
    parts.append('<div class="st-main"><h3 class="st-name">%s%s</h3>'
                 % (esc(station['name']), ' <span class="badge">Cheapest</span>' if best else ''))
    parts.append('<p class="st-meta">%s · %s · <span class="st-id">%s</span></p>'
                 % (esc(station['brand']), esc(station['address']), esc(sid)))
    if history:
        parts.append('<p class="st-listed">Listed %s</p>' % esc(when(history[-1]['recorded_at'])))
    parts.append('</div>')
    if price is None:
        parts.append('<div class="st-price"><span class="muted">No E10 price</span></div>')
    else:
        parts.append('<div class="st-price"><span class="num">%s</span> <span class="unit">c/L</span></div>' % cpl(price))
    parts.append('<div class="st-dist"><span class="num">%s</span> <span class="unit">km</span></div>'
                 % km(station['distance_km']))
    parts.append('<div class="st-spark">%s' % sparkline(station, x_domain, y_domain))
    if history:
        prices = [h['price_cpl'] for h in history]
        parts.append('<p class="spark-caption">%d prices · low %s · high %s</p>'
                     % (len(history), cpl(min(prices)), cpl(max(prices))))
    parts.append('</div>')
    parts.append('<button type="button" class="st-locate" data-station-id="%s" hidden>Show on map</button>' % esc(sid))
    if history:
        parts.append('<details class="st-history"><summary>Full E10 price history (%d)</summary>%s</details>'
                     % (len(history), history_table(station)))
    parts.append('</li>')
    return ''.join(parts)


def recommendation_block(doc, best):
    stations = [s for s in doc['stations'] if s['listed_price_cpl'] is not None]
    runner = stations[1] if len(stations) > 1 else None
    average = doc['overall_history'][-1]['mean_price_cpl'] if doc['overall_history'] else None
    listed = best['history'][-1]['recorded_at']
    compare = []
    if runner:
        compare.append('%s c/L below the next cheapest, %s (%s c/L, %s km away).'
                       % (cpl(runner['listed_price_cpl'] - best['listed_price_cpl']), esc(runner['name']),
                          cpl(runner['listed_price_cpl']), km(runner['distance_km'])))
    if average is not None and average > best['listed_price_cpl']:
        saving = average - best['listed_price_cpl']
        compare.append('%s c/L below the area average of %s c/L on %s: about $%.2f less on a %d L fill.'
                       % (cpl(saving), '%.2f' % average, long_day(doc['overall_history'][-1]['date']),
                          saving * FILL_LITRES / 100, FILL_LITRES))
    return '\n'.join([
        '<section class="recommendation" data-recommended-station="%s" aria-labelledby="rec-title">' % esc(best['id']),
        '<div class="rec-body">',
        '<p class="kicker">Cheapest listed E10 within %s km</p>' % num(RANGE_KM),
        '<h2 id="rec-title">%s</h2>' % esc(best['name']),
        '<p class="rec-address">%s · %s</p>' % (esc(best['address']), esc(best['brand'])),
        '<p class="rec-compare">%s</p>' % ' '.join(compare),
        '</div>',
        '<div class="rec-figures">',
        '<p class="rec-price"><span class="num">%s</span> <span class="unit">c/L</span></p>' % cpl(best['listed_price_cpl']),
        '<dl class="rec-facts">',
        '<div><dt>Distance</dt><dd>%s km</dd></div>' % km(best['distance_km']),
        '<div><dt>Price listed</dt><dd><time datetime="%s">%s</time></dd></div>' % (esc(listed), esc(when(listed))),
        '<div><dt>Station ID</dt><dd>%s</dd></div>' % esc(best['id']),
        '</dl>',
        '<a class="rec-link" href="#station-%s">See its price history</a>' % esc(best['id']),
        '</div>',
        '</section>',
    ])


def render(doc, centre):
    stations = doc['stations']
    best_id = doc['recommendation']['station_id'] if doc['recommendation'] else None
    best = next((s for s in stations if s['id'] == best_id), None)
    stamps = [h['recorded_at'] for s in stations for h in s['history']]
    latest = max(stamps, key=parse_time) if stamps else None
    moments = [parse_time(t).timestamp() for t in stamps]
    prices = [h['price_cpl'] for s in stations for h in s['history']]
    x_domain = (min(moments), max(moments)) if moments else (0, 1)
    if x_domain[1] <= x_domain[0]:
        x_domain = (x_domain[0], x_domain[0] + 1)
    y_domain = (min(prices) - 1, max(prices) + 1) if prices else (0, 1)

    lede = '%d stations within %s km of the search centre' % (len(stations), num(RANGE_KM))
    if latest:
        lede += ' · prices recorded up to %s (%s)' % (when(latest, year=True), offset_label(latest))

    body = []
    body.append('<header class="masthead"><div class="wrap">')
    body.append('<p class="kicker">E10 fuel · Greenwich, NSW</p>')
    body.append('<h1>Where to buy E10 near Greenwich</h1>')
    body.append('<p class="lede">%s</p>' % esc(lede))
    body.append('</div></header>')
    body.append('<main class="wrap">')
    if best:
        body.append(recommendation_block(doc, best))
    else:
        body.append('<p class="panel">No in-range station lists an E10 price.</p>')

    body.append('<div class="pair">')
    body.append('<section class="panel map-panel" aria-labelledby="map-title">')
    body.append('<h2 id="map-title">Map</h2>')
    body.append('<div id="map" class="map" role="region" aria-label="Map of the %d in-range stations" '
                'data-tile-url="%s" data-attribution="%s" data-centre-lat="%r" data-centre-lon="%r" '
                'data-radius-km="%r"></div>'
                % (len(stations), esc(TILE_URL), esc(ATTRIBUTION_HTML), centre['lat'], centre['lon'], RANGE_KM))
    body.append('<noscript><p class="note">The map needs JavaScript. The station list below works without it.</p></noscript>')
    body.append('<p class="note">Pins show each station\'s listed E10 price in c/L. The ring marks the %s km range '
                'around the search centre (%s, %s).</p>' % (num(RANGE_KM), centre['lat'], centre['lon']))
    body.append('</section>')

    body.append('<section class="panel" aria-labelledby="overall-title">')
    body.append('<h2 id="overall-title">Area average E10 price</h2>')
    body.append('<p class="note">For each day, the mean of every in-range station\'s latest E10 price recorded on or '
                'before that day.</p>')
    if doc['overall_history']:
        body.append('<figure class="chart">%s<div class="tooltip" id="overall-tooltip" hidden></div></figure>'
                    % overall_chart(doc['overall_history']))
        rows = ''.join('<tr><td><time datetime="%s">%s</time></td><td class="num">%s</td></tr>'
                       % (p['date'], esc(long_day(p['date'])), '%.2f' % p['mean_price_cpl'])
                       for p in doc['overall_history'])
        body.append('<details><summary>Show as a table</summary><table class="history"><thead><tr>'
                    '<th scope="col">Day</th><th scope="col" class="num">Mean E10 c/L</th></tr></thead>'
                    '<tbody>%s</tbody></table></details>' % rows)
    body.append('</section>')
    body.append('</div>')

    body.append('<section class="panel list-panel" aria-labelledby="list-title">')
    body.append('<div class="list-head"><h2 id="list-title">All %d stations in range</h2>' % len(stations))
    body.append('<div class="sort" role="group" aria-label="Sort stations" hidden>'
                '<button type="button" data-sort="price" aria-pressed="true">Cheapest first</button>'
                '<button type="button" data-sort="distance" aria-pressed="false">Nearest first</button></div></div>')
    body.append('<p class="note">Each line steps at every recorded price change; the dot marks the price listed now. '
                'All lines share one time and price scale.</p>')
    body.append('<ol class="stations" id="station-list">')
    for station in stations:
        body.append(station_item(station, best_id, x_domain, y_domain))
    body.append('</ol>')
    body.append('</section>')
    body.append('</main>')
    body.append('<footer class="wrap footer"><p>Prices in cents per litre. A station is in range when its haversine '
                'distance (Earth radius %s km) from the search centre is at most %s km; its listed price is its most '
                'recent E10 record. Times are shown as recorded. Map data %s. Map library: Leaflet 1.9.4.</p></footer>'
                % ('%.1f' % EARTH_RADIUS_KM, '%.1f' % RANGE_KM, ATTRIBUTION_HTML))

    head = '\n'.join([
        '<!doctype html>',
        '<html lang="en-AU">',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>Where to buy E10 near Greenwich, NSW</title>',
        '<link rel="stylesheet" href="vendor/leaflet/leaflet.css">',
        '<link rel="stylesheet" href="style.css">',
        '</head>',
        '<body>',
    ])
    tail = '\n'.join([
        '<script src="vendor/leaflet/leaflet.js"></script>',
        '<script src="data.js"></script>',
        '<script src="app.js"></script>',
        '</body>',
        '</html>',
        '',
    ])
    return head + '\n' + '\n'.join(body) + '\n' + tail


def main(argv):
    target = Path(argv[1]).resolve() if len(argv) > 1 else HERE
    stations_doc = json.loads((ROOT / 'data' / 'stations.json').read_text(encoding='utf-8'))
    prices_doc = json.loads((ROOT / 'data' / 'prices.json').read_text(encoding='utf-8'))
    doc = compute(stations_doc, prices_doc)

    target.mkdir(parents=True, exist_ok=True)
    data_json = json.dumps(doc, indent=2, ensure_ascii=False) + '\n'
    (target / 'data.json').write_text(data_json, encoding='utf-8')
    (target / 'data.js').write_text('window.FUEL_DATA = ' + data_json.rstrip('\n') + ';\n', encoding='utf-8')
    (target / 'index.html').write_text(render(doc, stations_doc['centre']), encoding='utf-8')

    leaflet = target / 'vendor' / 'leaflet'
    if leaflet.exists():
        shutil.rmtree(leaflet)
    shutil.copytree(ROOT / 'vendor' / 'leaflet', leaflet)
    best = doc['recommendation']['station_id'] if doc['recommendation'] else 'none'
    print('wrote %s: %d stations in range, recommend %s' % (target, len(doc['stations']), best))


if __name__ == '__main__':
    main(sys.argv)
