#!/usr/bin/env python3
"""Build the static E10 recommendation page in out/ from data/ and vendor/.

    python3 scripts/build.py           # (re)generate out/
    python3 scripts/build.py --check   # exit 1 if out/ differs from a fresh build

out/ is fully generated: a build replaces it. data/ and vendor/ are only read.
"""
from __future__ import annotations

import argparse
import filecmp
import html
import json
import math
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EARTH_RADIUS_KM = 6371.0
RANGE_KM = 10.0
FUEL = 'E10'
TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
ATTRIBUTION = '© OpenStreetMap contributors'


def haversine_km(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def instant(record):
    return datetime.fromisoformat(record['recorded_at'])


def written_date(record):
    """The calendar date as written in the timestamp, not converted to any zone."""
    return record['recorded_at'][:10]


def compute(stations_doc, prices_doc):
    """Return (data, details): data is exactly the out/data.json contract;
    details carries page-only fields (brand, address, centre)."""
    centre = stations_doc['centre']
    e10 = [r for r in prices_doc['records'] if r['fuel'] == FUEL]
    by_station = {}
    for record in e10:
        by_station.setdefault(record['station_id'], []).append(record)

    stations, details = [], {}
    for station in stations_doc['stations']:
        distance = haversine_km(centre['lat'], centre['lon'], station['lat'], station['lon'])
        if distance > RANGE_KM:
            continue
        history = sorted(by_station.get(station['id'], []), key=instant)
        stations.append({
            'id': station['id'], 'name': station['name'], 'lat': station['lat'], 'lon': station['lon'],
            'distance_km': distance,
            'listed_price_cpl': history[-1]['price_cpl'] if history else None,
            'history': [{'recorded_at': r['recorded_at'], 'price_cpl': r['price_cpl']} for r in history],
        })
        details[station['id']] = {'brand': station.get('brand', ''), 'address': station.get('address', '')}

    priced = [s for s in stations if s['listed_price_cpl'] is not None]
    if not priced:
        raise SystemExit('no in-range station has an E10 price')
    # Ties on price go to the nearer station, then the lower ID, so the choice is stable.
    best = min(priced, key=lambda s: (s['listed_price_cpl'], s['distance_km'], s['id']))
    stations.sort(key=lambda s: (s['listed_price_cpl'] is None, s['listed_price_cpl'] or 0, s['distance_km'], s['id']))

    overall = []
    for day in sorted({written_date(r) for r in e10}):
        latest = []
        for station in stations:
            upto = [h for h in station['history'] if written_date(h) <= day]
            if upto:
                latest.append(max(upto, key=instant)['price_cpl'])
        overall.append({'date': day, 'mean_price_cpl': sum(latest) / len(latest) if latest else None})

    data = {'recommendation': {'station_id': best['id']}, 'stations': stations, 'overall_history': overall}
    return data, {'centre': centre, 'stations': details}


# ---------- rendering ----------

def esc(value):
    return html.escape(str(value), quote=True)


def fmt_price(cpl):
    return '—' if cpl is None else f'{cpl:.1f}'


def fmt_when(recorded_at):
    when = datetime.fromisoformat(recorded_at)
    return f'{when.day} {when:%b %Y}, {when:%H:%M}'


def fmt_day(day, year=False):
    when = datetime.fromisoformat(day)
    return f'{when.day} {when:%b}' + (f' {when:%Y}' if year else '')


def price_bounds(stations):
    prices = [h['price_cpl'] for s in stations for h in s['history']]
    return math.floor(min(prices)) - 1, math.ceil(max(prices)) + 1


def time_bounds(stations):
    times = [instant(h).timestamp() for s in stations for h in s['history']]
    return min(times), max(times)


def sparkline(station, tbounds, pbounds):
    """Step line: a listed price holds until the next record."""
    width, height, pad = 168, 44, 4
    history = station['history']
    if not history:
        return '<span class="muted">No E10 records</span>'
    (t0, t1), (p0, p1) = tbounds, pbounds

    def x(t):
        return pad + (t - t0) / ((t1 - t0) or 1) * (width - 2 * pad)

    def y(p):
        return pad + (p1 - p) / ((p1 - p0) or 1) * (height - 2 * pad)

    points = []
    for i, h in enumerate(history):
        px, py = x(instant(h).timestamp()), y(h['price_cpl'])
        if i:
            points.append(f'{px:.1f},{points[-1].split(",")[1]}')
        points.append(f'{px:.1f},{py:.1f}')
    end_y = y(history[-1]['price_cpl'])
    points.append(f'{width - pad:.1f},{end_y:.1f}')
    prices = [h['price_cpl'] for h in history]
    label = (f'E10 price history for {station["name"]}: {len(history)} records from '
             f'{fmt_when(history[0]["recorded_at"])} to {fmt_when(history[-1]["recorded_at"])}, '
             f'low {min(prices):.1f}, high {max(prices):.1f} c/L')
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
            f'aria-label="{esc(label)}"><title>{esc(label)}</title>'
            f'<polyline points="{" ".join(points)}"/>'
            f'<circle cx="{width - pad:.1f}" cy="{end_y:.1f}" r="3"/></svg>')


def overall_chart(overall):
    points = [p for p in overall if p['mean_price_cpl'] is not None]
    width, height = 720, 260
    left, right, top, bottom = 52, 16, 16, 34
    lo = math.floor(min(p['mean_price_cpl'] for p in points) - 0.5)
    hi = math.ceil(max(p['mean_price_cpl'] for p in points) + 0.5)
    n = len(overall)

    def x(i):
        return left + (i / ((n - 1) or 1)) * (width - left - right)

    def y(p):
        return top + (hi - p) / ((hi - lo) or 1) * (height - top - bottom)

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-labelledby="overall-title overall-desc">'
             f'<desc id="overall-desc">Daily mean E10 price across in-range stations, '
             f'{fmt_day(overall[0]["date"])} to {fmt_day(overall[-1]["date"], True)}.</desc>']
    step = max(1, round((hi - lo) / 5))
    for tick in range(lo, hi + 1, step):
        ty = y(tick)
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{ty:.1f}" y2="{ty:.1f}"/>'
                     f'<text class="tick" x="{left - 8}" y="{ty + 4:.1f}" text-anchor="end">{tick}</text>')
    for i, point in enumerate(overall):
        if (n - 1 - i) % 2 == 0:  # every other day, always including the latest
            anchor = 'end' if i == n - 1 else 'middle'
            parts.append(f'<text class="tick" x="{x(i):.1f}" y="{height - 10}" text-anchor="{anchor}">'
                         f'{esc(fmt_day(point["date"]))}</text>')
    line = ' '.join(f'{x(i):.1f},{y(p["mean_price_cpl"]):.1f}'
                    for i, p in enumerate(overall) if p['mean_price_cpl'] is not None)
    parts.append(f'<polyline class="trend" points="{line}"/>')
    for i, point in enumerate(overall):
        if point['mean_price_cpl'] is None:
            continue
        parts.append(f'<circle class="dot" cx="{x(i):.1f}" cy="{y(point["mean_price_cpl"]):.1f}" r="3.5">'
                     f'<title>{esc(fmt_day(point["date"], True))}: {point["mean_price_cpl"]:.2f} c/L</title></circle>')
    parts.append(f'<text class="axis" x="14" y="{top + (height - top - bottom) / 2:.0f}" '
                 f'transform="rotate(-90 14 {top + (height - top - bottom) / 2:.0f})" text-anchor="middle">c/L</text>')
    parts.append('</svg>')
    return ''.join(parts)


def history_table(history):
    rows = ''.join(f'<tr><td>{esc(fmt_when(h["recorded_at"]))}</td><td class="num">{fmt_price(h["price_cpl"])}</td></tr>'
                   for h in reversed(history))
    return (f'<table class="history"><thead><tr><th scope="col">Recorded</th>'
            f'<th scope="col" class="num">c/L</th></tr></thead><tbody>{rows}</tbody></table>')


def station_item(rank, station, info, best_id, tbounds, pbounds):
    best = station['id'] == best_id
    listed = station['history'][-1]['recorded_at'] if station['history'] else None
    badge = '<span class="badge">Cheapest</span>' if best else ''
    return f'''
      <li class="station{' is-best' if best else ''}" id="station-{esc(station['id'])}" data-station-id="{esc(station['id'])}">
        <div class="rank" aria-hidden="true">{rank}</div>
        <div class="who">
          <h3>{esc(station['name'])} {badge}</h3>
          <p class="muted">{esc(info['brand'])} · {esc(info['address'])} · <span class="sid">{esc(station['id'])}</span></p>
          <button type="button" class="link" data-show-on-map="{esc(station['id'])}">Show on map</button>
        </div>
        <div class="price"><span class="value">{fmt_price(station['listed_price_cpl'])}</span><span class="unit">c/L</span>
          <span class="muted small">{esc(fmt_when(listed)) if listed else 'no E10 price'}</span></div>
        <div class="dist"><span class="value">{station['distance_km']:.2f}</span><span class="unit">km</span></div>
        <div class="trend-cell">
          {sparkline(station, tbounds, pbounds)}
          <details><summary>{len(station['history'])} E10 records</summary>{history_table(station['history'])}</details>
        </div>
      </li>'''


def render_index(data, details):
    stations = data['stations']
    best_id = data['recommendation']['station_id']
    best = next(s for s in stations if s['id'] == best_id)
    best_info = details['stations'][best_id]
    tbounds, pbounds = time_bounds(stations), price_bounds(stations)
    overall = data['overall_history']
    latest_mean = next(p for p in reversed(overall) if p['mean_price_cpl'] is not None)
    below = latest_mean['mean_price_cpl'] - best['listed_price_cpl']
    first_day, last_day = overall[0]['date'], overall[-1]['date']
    items = ''.join(station_item(i + 1, s, details['stations'][s['id']], best_id, tbounds, pbounds)
                    for i, s in enumerate(stations))
    overall_rows = ''.join(f'<tr><td>{esc(fmt_day(p["date"], True))}</td><td class="num">'
                           f'{"—" if p["mean_price_cpl"] is None else format(p["mean_price_cpl"], ".2f")}</td></tr>'
                           for p in overall)
    centre = details['centre']
    map_script = MAP_SCRIPT.replace('__CENTRE__', json.dumps([centre['lat'], centre['lon']])) \
        .replace('__RANGE_M__', str(int(RANGE_KM * 1000))) \
        .replace('__TILE_URL__', json.dumps(TILE_URL)) \
        .replace('__ATTRIBUTION__', json.dumps(f'<a href="https://www.openstreetmap.org/copyright">{ATTRIBUTION}</a>',
                                               ensure_ascii=False))
    return PAGE.format(
        count=len(stations), range_km=f'{RANGE_KM:g}',
        first_day=esc(fmt_day(first_day)), last_day=esc(fmt_day(last_day, True)),
        best_id=esc(best_id), best_name=esc(best['name']), best_brand=esc(best_info['brand']),
        best_address=esc(best_info['address']), best_price=fmt_price(best['listed_price_cpl']),
        best_distance=f'{best["distance_km"]:.2f}', best_when=esc(fmt_when(best['history'][-1]['recorded_at'])),
        below=f'{below:.1f}', latest_mean=f'{latest_mean["mean_price_cpl"]:.2f}',
        latest_mean_day=esc(fmt_day(latest_mean['date'])),
        overall_chart=overall_chart(overall), overall_rows=overall_rows, items=items,
        attribution=ATTRIBUTION, map_script=map_script)


PAGE = '''<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cheapest E10 near Greenwich, NSW</title>
<link rel="stylesheet" href="vendor/leaflet/leaflet.css">
<style>
  :root {{
    --ink: #1b1f23; --muted: #5d6670; --line: #dfe3e6; --paper: #f6f4ef; --card: #ffffff;
    --asphalt: #20262c; --best: #0f7b4b; --best-soft: #e3f3ea; --accent: #c2410c;
    --mono: ui-monospace, "SF Mono", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--paper); color: var(--ink);
         font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }}
  header {{ background: var(--asphalt); color: #f3f1ea; padding: 28px 24px 24px; }}
  header .wrap {{ display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: baseline; justify-content: space-between; }}
  header h1 {{ margin: 0; font-size: clamp(1.5rem, 3vw, 2.1rem); letter-spacing: -0.01em; }}
  header p {{ margin: 0; color: #c9cdd1; }}
  .wrap {{ max-width: 1180px; margin: 0 auto; }}
  main {{ padding: 24px; display: grid; gap: 24px; grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); }}
  section {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 20px; }}
  h2 {{ margin: 0 0 12px; font-size: 1.15rem; }}
  .muted {{ color: var(--muted); }}
  .small {{ font-size: 0.8rem; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .reco {{ border: 2px solid var(--best); background: var(--best-soft); display: flex; flex-direction: column; gap: 10px; }}
  .reco .eyebrow {{ margin: 0; text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.78rem; font-weight: 700; color: var(--best); }}
  .reco .big {{ font-size: clamp(3rem, 7vw, 4.5rem); line-height: 1; font-weight: 800; letter-spacing: -0.02em;
                font-variant-numeric: tabular-nums; color: var(--best); }}
  .reco .big small {{ font-size: 1.1rem; font-weight: 600; margin-left: 6px; }}
  .reco h2 {{ font-size: 1.5rem; margin: 0; }}
  .reco p {{ margin: 0; }}
  .reco dl {{ display: grid; grid-template-columns: auto 1fr; gap: 2px 14px; margin: 4px 0 0; }}
  .reco dt {{ color: var(--muted); }}
  .reco dd {{ margin: 0; font-variant-numeric: tabular-nums; }}
  .map-panel {{ padding: 0; overflow: hidden; display: flex; flex-direction: column; }}
  #map {{ flex: 1; min-height: 420px; }}
  .map-panel p {{ margin: 0; padding: 8px 14px; font-size: 0.8rem; border-top: 1px solid var(--line); }}
  .overall, .stations {{ grid-column: 1 / -1; }}
  .chart-scroll {{ overflow-x: auto; }}
  .chart {{ width: 100%; min-width: 560px; height: auto; display: block; }}
  .chart .grid {{ stroke: var(--line); }}
  .chart .tick, .chart .axis {{ fill: var(--muted); font-size: 12px; }}
  .chart .trend {{ fill: none; stroke: var(--accent); stroke-width: 2.5; stroke-linejoin: round; }}
  .chart .dot {{ fill: var(--card); stroke: var(--accent); stroke-width: 2; }}
  details summary {{ cursor: pointer; color: var(--muted); font-size: 0.85rem; }}
  table.history {{ border-collapse: collapse; margin-top: 6px; font-size: 0.85rem; width: 100%; max-width: 280px; }}
  table.history th, table.history td {{ padding: 2px 6px; border-bottom: 1px solid var(--line); text-align: left; }}
  table.history .num {{ text-align: right; }}
  ol.list {{ list-style: none; margin: 0; padding: 0; }}
  .station {{ display: grid; grid-template-columns: 36px minmax(0, 1fr) 120px 90px 190px; gap: 12px 16px;
             align-items: start; padding: 14px 8px; border-top: 1px solid var(--line); }}
  .station.is-best {{ background: var(--best-soft); border-radius: 8px; border-top-color: transparent; }}
  .station h3 {{ margin: 0; font-size: 1rem; }}
  .station p {{ margin: 0; font-size: 0.85rem; }}
  .rank {{ font-family: var(--mono); color: var(--muted); font-size: 1.1rem; padding-top: 2px; }}
  .price, .dist {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 4px; }}
  .price .value, .dist .value {{ font-family: var(--mono); font-size: 1.35rem; font-weight: 700; font-variant-numeric: tabular-nums; }}
  .is-best .price .value {{ color: var(--best); }}
  .price .muted {{ flex-basis: 100%; }}
  .unit {{ color: var(--muted); font-size: 0.85rem; }}
  .badge {{ display: inline-block; vertical-align: 2px; margin-left: 6px; padding: 1px 8px; border-radius: 999px;
           background: var(--best); color: #fff; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
  .sid {{ font-family: var(--mono); font-size: 0.78rem; }}
  .spark {{ display: block; overflow: visible; }}
  .spark polyline {{ fill: none; stroke: var(--ink); stroke-width: 1.6; stroke-linejoin: round; }}
  .spark circle {{ fill: var(--accent); }}
  .is-best .spark polyline {{ stroke: var(--best); }}
  .is-best .spark circle {{ fill: var(--best); }}
  button.link {{ background: none; border: 0; padding: 0; margin-top: 4px; color: #1d4ed8; cursor: pointer; font: inherit; font-size: 0.85rem; text-decoration: underline; }}
  .legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 0 0 12px; font-size: 0.85rem; color: var(--muted); }}
  footer {{ padding: 0 24px 32px; color: var(--muted); font-size: 0.85rem; }}
  @media (max-width: 860px) {{
    main {{ grid-template-columns: minmax(0, 1fr); padding: 16px; gap: 16px; }}
    .station {{ grid-template-columns: 28px minmax(0, 1fr) minmax(0, 1fr); }}
    .station .who, .station .trend-cell {{ grid-column: 2 / -1; }}
    .station .price {{ grid-column: 2; }}
    .station .dist {{ grid-column: 3; }}
  }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>Cheapest E10 near Greenwich, NSW</h1>
    <p>{count} stations within {range_km} km · prices recorded {first_day} – {last_day}</p>
  </div>
</header>
<main class="wrap">
  <section class="reco" data-recommended-station="{best_id}" aria-labelledby="reco-title">
    <p class="eyebrow">Recommended: lowest listed E10 price</p>
    <div class="big">{best_price}<small>c/L</small></div>
    <h2 id="reco-title">{best_name}</h2>
    <p>{best_brand} · {best_address}</p>
    <dl>
      <dt>Distance</dt><dd>{best_distance} km from Greenwich</dd>
      <dt>Listed</dt><dd>{best_when}</dd>
      <dt>Saving</dt><dd>{below} c/L below the {latest_mean_day} in-range average ({latest_mean} c/L)</dd>
      <dt>Station ID</dt><dd class="sid">{best_id}</dd>
    </dl>
  </section>

  <section class="map-panel" aria-label="Map of stations">
    <div id="map" role="region" aria-label="Map of in-range E10 stations"></div>
    <p class="muted">Green: recommended station. Dashed ring: {range_km} km search radius. Map data {attribution}.</p>
  </section>

  <section class="overall" aria-labelledby="overall-title">
    <h2 id="overall-title">Average E10 price across in-range stations</h2>
    <p class="legend"><span>Each day: mean of every in-range station's latest E10 price recorded on or before that day.</span></p>
    <div class="chart-scroll">{overall_chart}</div>
    <details><summary>Daily values</summary>
      <table class="history"><thead><tr><th scope="col">Day</th><th scope="col" class="num">Mean c/L</th></tr></thead>
      <tbody>{overall_rows}</tbody></table>
    </details>
  </section>

  <section class="stations" aria-labelledby="list-title">
    <h2 id="list-title">All {count} stations within {range_km} km, cheapest first</h2>
    <p class="legend"><span>Listed price: the station's most recent E10 record.</span><span>Distance: straight line from Greenwich.</span><span>Trend: E10 price history, {first_day} – {last_day}.</span></p>
    <ol class="list">{items}
    </ol>
  </section>
</main>
<footer class="wrap">Prices in cents per litre. Map tiles and data {attribution}.</footer>
<script src="vendor/leaflet/leaflet.js"></script>
<script src="data.js"></script>
<script>
{map_script}
</script>
</body>
</html>
'''

MAP_SCRIPT = '''(function () {
  var data = window.E10_DATA;
  var mapEl = document.getElementById('map');
  if (!data || !window.L) {
    mapEl.textContent = 'The map could not load. The station list below has every price.';
    return;
  }
  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  var centre = __CENTRE__;
  var bestId = data.recommendation.station_id;
  var map = L.map(mapEl, {scrollWheelZoom: false});
  L.tileLayer(__TILE_URL__, {maxZoom: 19, attribution: __ATTRIBUTION__}).addTo(map);
  L.circle(centre, {radius: __RANGE_M__, color: '#5d6670', weight: 1, dashArray: '6 6', fill: false, interactive: false}).addTo(map);
  L.circleMarker(centre, {radius: 5, color: '#20262c', weight: 2, fillColor: '#ffffff', fillOpacity: 1})
    .bindTooltip('Greenwich (search centre)').addTo(map);
  var markers = {};
  var bounds = L.latLngBounds([centre]);
  data.stations.forEach(function (s) {
    var best = s.id === bestId;
    var price = s.listed_price_cpl === null ? 'no E10 price' : s.listed_price_cpl.toFixed(1) + ' c/L';
    var marker = L.circleMarker([s.lat, s.lon], {
      radius: best ? 11 : 7, weight: 2, color: best ? '#0b5c38' : '#20262c',
      fillColor: best ? '#0f7b4b' : '#c2410c', fillOpacity: best ? 0.95 : 0.8
    }).addTo(map);
    marker.bindPopup('<strong>' + escapeHtml(s.name) + '</strong>' + (best ? ' (recommended)' : '') +
      '<br>' + escapeHtml(price) + ' · ' + s.distance_km.toFixed(2) + ' km' +
      '<br><a href="#station-' + escapeHtml(s.id) + '">Price history</a>');
    marker.bindTooltip(escapeHtml(price), {permanent: best, direction: 'top', offset: [0, -8]});
    markers[s.id] = marker;
    bounds.extend([s.lat, s.lon]);
  });
  map.fitBounds(bounds, {padding: [20, 20]});
  Array.prototype.forEach.call(document.querySelectorAll('button[data-show-on-map]'), function (button) {
    button.addEventListener('click', function () {
      var marker = markers[button.getAttribute('data-show-on-map')];
      if (!marker) return;
      mapEl.scrollIntoView({behavior: 'smooth', block: 'center'});
      map.setView(marker.getLatLng(), 15);
      marker.openPopup();
    });
  });
  document.documentElement.setAttribute('data-map-markers', String(Object.keys(markers).length));
})();'''


def build(out: Path):
    stations_doc = json.loads((ROOT / 'data' / 'stations.json').read_text(encoding='utf-8'))
    prices_doc = json.loads((ROOT / 'data' / 'prices.json').read_text(encoding='utf-8'))
    data, details = compute(stations_doc, prices_doc)
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    (out / 'data.json').write_text(text, encoding='utf-8')
    (out / 'data.js').write_text('window.E10_DATA = ' + text.rstrip('\n') + ';\n', encoding='utf-8')
    (out / 'index.html').write_text(render_index(data, details), encoding='utf-8')
    shutil.copytree(ROOT / 'vendor' / 'leaflet', out / 'vendor' / 'leaflet')
    return data


def same_tree(a: Path, b: Path) -> list:
    files_a = {p.relative_to(a) for p in a.rglob('*') if p.is_file()}
    files_b = {p.relative_to(b) for p in b.rglob('*') if p.is_file()}
    problems = [f'only in {a}: {p}' for p in sorted(files_a - files_b)]
    problems += [f'only in {b}: {p}' for p in sorted(files_b - files_a)]
    problems += [f'differs: {p}' for p in sorted(files_a & files_b) if not filecmp.cmp(a / p, b / p, shallow=False)]
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='compare out/ with a fresh build instead of writing')
    args = parser.parse_args(argv)
    out = ROOT / 'out'
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp) / 'out')
            problems = same_tree(Path(tmp) / 'out', out) if out.is_dir() else [f'{out} is missing']
        for problem in problems:
            print(problem)
        print('out/ is up to date' if not problems else f'{len(problems)} difference(s); run scripts/build.py')
        return 1 if problems else 0
    if out.exists():
        shutil.rmtree(out)
    data = build(out)
    print(f'wrote {out}: {len(data["stations"])} stations, recommendation {data["recommendation"]["station_id"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
