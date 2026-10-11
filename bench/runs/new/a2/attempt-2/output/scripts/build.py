#!/usr/bin/env python3
"""Build the static E10 price page in out/ from data/ and vendor/leaflet/.

    python3 scripts/build.py          # rewrite out/ (the script owns that directory)
    python3 scripts/build.py --check  # exit 1 if out/ differs from a fresh build
    python3 scripts/build.py --root DIR  # use DIR/data, DIR/vendor/leaflet and DIR/out instead

Standard library only. Output is deterministic, so --check is a byte comparison.
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
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EARTH_RADIUS_KM = 6371.0
RANGE_KM = 10.0
FUEL = 'E10'
MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


# ---------------------------------------------------------------- model

def haversine_km(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def instant(record):
    return datetime.fromisoformat(record['recorded_at'])


def compute(stations_doc, prices_doc):
    """Return (data, extras): data is out/data.json; extras holds page-only facts."""
    centre = stations_doc['centre']
    e10 = [r for r in prices_doc['records'] if r['fuel'] == FUEL]
    by_station = defaultdict(list)
    for record in e10:
        by_station[record['station_id']].append(record)
    for records in by_station.values():
        records.sort(key=instant)  # stable: records at the same instant keep file order

    stations, extras = [], {'brand': {}, 'address': {}}
    for st in stations_doc['stations']:
        distance = haversine_km(centre['lat'], centre['lon'], st['lat'], st['lon'])
        if distance > RANGE_KM:
            continue
        history = by_station.get(st['id'], [])
        stations.append({
            'id': st['id'], 'name': st['name'], 'lat': st['lat'], 'lon': st['lon'],
            'distance_km': distance,
            'listed_price_cpl': history[-1]['price_cpl'] if history else None,
            'history': [{'recorded_at': r['recorded_at'], 'price_cpl': r['price_cpl']} for r in history],
        })
        extras['brand'][st['id']] = st['brand']
        extras['address'][st['id']] = st['address']

    priced = [s for s in stations if s['listed_price_cpl'] is not None]
    if not priced:
        sys.exit('no in-range station has an E10 price')
    best = min(priced, key=lambda s: (s['listed_price_cpl'], s['distance_km'], s['id']))

    # One point per date written in any E10 timestamp; the mean covers in-range stations only.
    overall = []
    for day in sorted({r['recorded_at'][:10] for r in e10}):
        latest = []
        for s in stations:
            upto = [h for h in s['history'] if h['recorded_at'][:10] <= day]
            if upto:
                latest.append(upto[-1]['price_cpl'])
        # A day before any in-range station has a price keeps its point, with no mean.
        overall.append({'date': day, 'mean_price_cpl': sum(latest) / len(latest) if latest else None})

    stations.sort(key=lambda s: (s['listed_price_cpl'] is None, s['listed_price_cpl'] or 0, s['distance_km'], s['id']))
    data = {'recommendation': {'station_id': best['id']}, 'stations': stations, 'overall_history': overall}
    extras.update(centre=centre, excluded=len(stations_doc['stations']) - len(stations))
    return data, extras


# ---------------------------------------------------------------- formatting

def esc(value):
    return html.escape(str(value), quote=True)


def fmt_price(cpl):
    return f'{cpl:.1f}'


def fmt_km(km):
    return f'{km:.2f} km'


# Set by render(): show the year or the UTC offset in every label only when the data mixes them.
TIME_STYLE = {'year': False, 'offset': False}


def fmt_time(ts, year=False):
    """Wall-clock time as written in the timestamp, e.g. '14 Sep, 2:15 pm'."""
    dt = datetime.fromisoformat(ts)
    hour = dt.hour % 12 or 12
    return (f'{dt.day} {MONTHS[dt.month - 1]}' + (f' {dt.year}' if year or TIME_STYLE['year'] else '')
            + f', {hour}:{dt.minute:02d} {"am" if dt.hour < 12 else "pm"}'
            + (f' ({fmt_offset(ts)})' if TIME_STYLE['offset'] else ''))


def fmt_offset(ts):
    """The timestamp's UTC offset, e.g. 'UTC+10:00', from the parsed value rather than its spelling."""
    minutes = int(datetime.fromisoformat(ts).utcoffset().total_seconds() // 60)
    hours, mins = divmod(abs(minutes), 60)
    return f'UTC{"+" if minutes >= 0 else "-"}{hours:02d}:{mins:02d}'


def fmt_day(day, year=False):
    y, m, d = (int(part) for part in day.split('-'))
    return f'{d} {MONTHS[m - 1]}' + (f' {y}' if year else '')


def num(value):
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def fmt_mean(cpl):
    return f'{cpl:.2f}'


def nice_axis(lo, hi, target=5):
    span = (hi - lo) or 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag)
    start, stop = math.floor(lo / step) * step, math.ceil(hi / step) * step
    if stop == start:
        stop += step
    ticks, k = [], 0
    while start + k * step <= stop + step / 1e6:
        ticks.append(round(start + k * step, 6))
        k += 1
    return ticks[0], ticks[-1], ticks


# ---------------------------------------------------------------- charts

def overall_chart(points):
    """Line chart of the daily means; a day without any in-range price is a gap in the line."""
    w, h = 720, 260
    left, right, top, bottom = 56, 84, 18, 40
    pw, ph = w - left - right, h - top - bottom
    known = [(i, p) for i, p in enumerate(points) if p['mean_price_cpl'] is not None]
    if not known:
        return '<p class="sub">No in-range station has an E10 price yet.</p>'
    values = [p['mean_price_cpl'] for _, p in known]
    lo, hi, ticks = nice_axis(min(values), max(values), 4)
    n = len(points)
    days = [date.fromisoformat(p['date']).toordinal() for p in points]
    span = days[-1] - days[0]

    def x(i):  # by calendar day, so uneven gaps between dates keep their true width
        return left + (pw / 2 if span == 0 else (days[i] - days[0]) * pw / span)

    def y(v):
        return top + ph - (v - lo) / (hi - lo) * ph

    out = [f'<svg class="chart chart-overall" viewBox="0 0 {w} {h}" role="img" aria-labelledby="overall-title overall-desc">']
    (i0, first), (i1, last) = known[0], known[-1]
    out.append(f'<desc id="overall-desc">Daily mean E10 price across in-range stations from {fmt_day(first["date"])} '
               f'({fmt_mean(first["mean_price_cpl"])} c/L) to {fmt_day(last["date"])} ({fmt_mean(last["mean_price_cpl"])} c/L), '
               f'ranging {fmt_mean(min(values))} to {fmt_mean(max(values))} c/L.</desc>')
    for t in ticks:
        out.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="tick" x="{left - 14}" y="{y(t) + 4:.1f}" text-anchor="end">{num(t)}</text>')
    for i, p in enumerate(points):
        if (n - 1 - i) % 2 == 0:
            out.append(f'<text class="tick" x="{x(i):.1f}" y="{h - 12}" text-anchor="middle">{fmt_day(p["date"])}</text>')
    out.append(f'<line class="crosshair" x1="0" x2="0" y1="{top}" y2="{top + ph}"/>')
    segment = []
    for p_i, p in enumerate(points + [{'mean_price_cpl': None}]):
        if p['mean_price_cpl'] is not None:
            segment.append(f'{x(p_i):.1f},{y(p["mean_price_cpl"]):.1f}')
        elif segment:
            out.append(f'<polyline class="line" points="{" ".join(segment)}"/>')
            segment = []
    for i, p in known:
        out.append(f'<circle class="dot" cx="{x(i):.1f}" cy="{y(p["mean_price_cpl"]):.1f}" r="4"/>')
    for i, p in {i0: first, i1: last}.items():
        dx, dy = (10, 5) if i == i1 else (8, -14)
        out.append(f'<text class="value" x="{x(i) + dx:.1f}" y="{y(p["mean_price_cpl"]) + dy:.1f}" '
                   f'text-anchor="start">{fmt_mean(p["mean_price_cpl"])}</text>')
    for i, p in enumerate(points):
        x0 = left if i == 0 else (x(i - 1) + x(i)) / 2
        x1 = left + pw if i == n - 1 else (x(i) + x(i + 1)) / 2
        mean = p['mean_price_cpl']
        tip = f'{fmt_day(p["date"], True)}: ' + (f'{fmt_mean(mean)} c/L average' if mean is not None
                                                 else 'no in-range price yet')
        out.append(f'<rect class="hit" x="{x0:.1f}" y="{top}" width="{x1 - x0:.1f}" height="{ph}" '
                   f'data-x="{x(i):.1f}" data-tip="{esc(tip)}"><title>{esc(tip)}</title></rect>')
    out.append('</svg>')
    return ''.join(out)


def sparkline(station, x_domain, y_domain):
    w, h = 320, 60
    left, right, top, bottom = 2, 10, 8, 8
    pw, ph = w - left - right, h - top - bottom
    (t0, t1), (lo, hi, ticks) = x_domain, y_domain
    span = (t1 - t0).total_seconds()

    def x(ts):
        return left + (datetime.fromisoformat(ts) - t0).total_seconds() / span * pw

    def y(v):
        return top + ph - (v - lo) / (hi - lo) * ph

    hist = station['history']
    prices = [p['price_cpl'] for p in hist]
    label = (f'E10 price history for {station["name"]}: {len(hist)} records from '
             f'{fmt_time(hist[0]["recorded_at"])} to {fmt_time(hist[-1]["recorded_at"])}, between '
             f'{fmt_price(min(prices))} and {fmt_price(max(prices))} c/L, latest {fmt_price(prices[-1])} c/L.')
    out = [f'<svg class="chart chart-spark" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}">']
    for t in ticks:
        out.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
    out.append(f'<line class="crosshair" x1="0" x2="0" y1="{top}" y2="{top + ph}"/>')
    d = f'M{x(hist[0]["recorded_at"]):.1f},{y(prices[0]):.1f}'
    for p in hist[1:]:
        d += f'H{x(p["recorded_at"]):.1f}V{y(p["price_cpl"]):.1f}'
    d += f'H{left + pw}'
    out.append(f'<path class="line" d="{d}"/>')
    out.append(f'<circle class="dot dot-end" cx="{left + pw}" cy="{y(prices[-1]):.1f}" r="4"/>')
    for i, p in enumerate(hist):
        x0 = x(p['recorded_at'])
        x1 = x(hist[i + 1]['recorded_at']) if i + 1 < len(hist) else left + pw
        tip = f'{fmt_time(p["recorded_at"])}: {fmt_price(p["price_cpl"])} c/L'
        out.append(f'<rect class="hit" x="{x0:.1f}" y="0" width="{max(x1 - x0, 2):.1f}" height="{h}" '
                   f'data-x="{x0:.1f}" data-tip="{esc(tip)}"><title>{esc(tip)}</title></rect>')
    out.append('</svg>')
    return ''.join(out)


def history_table(station):
    rows = ''.join(f'<tr class="hist-row"><td><time datetime="{esc(p["recorded_at"])}">{esc(fmt_time(p["recorded_at"]))}</time></td>'
                   f'<td class="n">{fmt_price(p["price_cpl"])}</td></tr>' for p in reversed(station['history']))
    return (f'<table class="hist"><caption class="sr">E10 price history for {esc(station["name"])}, newest first</caption>'
            f'<thead><tr><th scope="col">Recorded</th><th scope="col" class="n">c/L</th></tr></thead><tbody>{rows}</tbody></table>')


# ---------------------------------------------------------------- page

def station_item(rank, s, extras, best_id, x_domain, y_domain):
    best = s['id'] == best_id
    sid = esc(s['id'])
    badge = '<span class="badge">Cheapest</span>' if best else ''
    head = (f'<li class="station{" is-best" if best else ""}" id="station-{sid}" data-station-id="{sid}">'
            f'<div class="station-main"><span class="rank" aria-hidden="true">{rank}</span>'
            f'<div class="station-who"><h3 class="station-name">{esc(s["name"])}{badge}</h3>'
            f'<p class="station-addr">{esc(extras["brand"][s["id"]])} · {esc(extras["address"][s["id"]])}</p></div>')
    if s['listed_price_cpl'] is None:
        return (head + '<p class="station-price none">No E10 price</p></div>'
                f'<p class="station-meta"><span>{fmt_km(s["distance_km"])} away</span><span class="sid">{sid}</span></p>'
                f'<div class="station-actions"><button type="button" class="locate" data-station-id="{sid}">Show on map</button></div></li>')
    hist = s['history']
    prices = [p['price_cpl'] for p in hist]
    return (head + f'<p class="station-price"><span class="num">{fmt_price(s["listed_price_cpl"])}</span>'
            f'<span class="unit">c/L</span></p></div>'
            f'<p class="station-meta"><span>{fmt_km(s["distance_km"])} away</span>'
            f'<span>Updated <span class="js-updated">{esc(fmt_time(hist[-1]["recorded_at"]))}</span></span>'
            f'<span class="sid">{sid}</span></p>'
            f'<figure class="spark">{sparkline(s, x_domain, y_domain)}'
            f'<figcaption>Low {fmt_price(min(prices))} · High {fmt_price(max(prices))} c/L</figcaption></figure>'
            f'<div class="station-actions"><button type="button" class="locate" data-station-id="{sid}">Show on map</button>'
            f'<details><summary>Price history · {len(hist)} records</summary>{history_table(s)}</details></div></li>')


def render(data, extras):
    stations = data['stations']
    best_id = data['recommendation']['station_id']
    best = next(s for s in stations if s['id'] == best_id)
    priced = [s for s in stations if s['listed_price_cpl'] is not None]
    others = [s for s in priced if s['id'] != best_id]
    average = sum(s['listed_price_cpl'] for s in priced) / len(priced)
    overall = data['overall_history']

    all_hist = [p for s in priced for p in s['history']]
    times = [datetime.fromisoformat(p['recorded_at']) for p in all_hist]
    first, last = min(times), max(times)
    t0 = first.replace(hour=0, minute=0, second=0, microsecond=0)
    t1 = last.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    y_domain = nice_axis(min(p['price_cpl'] for p in all_hist), max(p['price_cpl'] for p in all_hist), 4)
    latest_ts = max(all_hist, key=instant)['recorded_at']
    offsets = {fmt_offset(p['recorded_at']) for p in all_hist}
    TIME_STYLE.update(year=len({t.year for t in times}) > 1, offset=len(offsets) > 1)
    time_note = (f'Times are shown as recorded ({fmt_offset(latest_ts)}).' if len(offsets) == 1
                 else 'Times are shown as recorded, with their UTC offset.')

    comparison = []
    if others:
        runner = others[0]
        comparison.append(f'<div><dt>Next cheapest</dt><dd>{esc(runner["name"])}, '
                          f'{fmt_price(runner["listed_price_cpl"])} c/L '
                          f'(<strong>{runner["listed_price_cpl"] - best["listed_price_cpl"]:.1f} c/L more</strong>)</dd></div>')
    comparison.append(f'<div><dt>In-range average</dt><dd>{fmt_mean(average)} c/L '
                      f'(<strong>{fmt_mean(average - best["listed_price_cpl"])} c/L more</strong>)</dd></div>')

    centre = extras['centre']
    search = {'centre': {'lat': centre['lat'], 'lon': centre['lon']}, 'radius_km': RANGE_KM}
    items = ''.join(station_item(i + 1, s, extras, best_id, (t0, t1), y_domain) for i, s in enumerate(stations))
    overall_rows = ''.join(f'<tr class="overall-row"><td><time datetime="{p["date"]}">{fmt_day(p["date"], True)}</time></td>'
                           f'<td class="n">{"—" if p["mean_price_cpl"] is None else fmt_mean(p["mean_price_cpl"])}</td></tr>'
                           for p in overall)

    return f'''<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cheapest E10 near Greenwich, NSW</title>
<meta name="description" content="Where to buy E10 within {num(RANGE_KM)} km of Greenwich, NSW, ranked by the latest listed price.">
<link rel="stylesheet" href="vendor/leaflet/leaflet.css">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header class="masthead">
<p class="eyebrow">E10 · within {num(RANGE_KM)} km of Greenwich, NSW</p>
<h1>Where to buy E10 near Greenwich</h1>
<p class="lede">{len(stations)} stations within {num(RANGE_KM)} km, ranked by their latest listed price.
Latest record: <time datetime="{esc(latest_ts)}">{esc(fmt_time(latest_ts, True))}</time>. {time_note}</p>
</header>

<div class="top">
<section class="card hero" data-recommended-station="{esc(best_id)}" aria-labelledby="rec-title">
<p class="eyebrow">Recommended · cheapest listed price</p>
<h2 id="rec-title">{esc(best["name"])}</h2>
<p class="hero-addr">{esc(extras["brand"][best_id])} · {esc(extras["address"][best_id])}</p>
<p class="hero-price"><span class="num">{fmt_price(best["listed_price_cpl"])}</span><span class="unit">c/L</span></p>
<dl class="hero-facts">
<div><dt>Distance</dt><dd>{fmt_km(best["distance_km"])} from Greenwich</dd></div>
<div><dt>Listed</dt><dd>{esc(fmt_time(best["history"][-1]["recorded_at"]))}</dd></div>
{"".join(comparison)}
</dl>
<button type="button" class="locate primary" data-station-id="{esc(best_id)}">Show on map</button>
</section>

<section class="card overall" aria-labelledby="overall-title">
<h2 id="overall-title">Average E10 price, in-range stations</h2>
<p class="sub">Daily mean of each station's latest price on or before that day, in c/L.</p>
{overall_chart(overall)}
<details><summary>Daily averages table</summary>
<table class="hist"><thead><tr><th scope="col">Day</th><th scope="col" class="n">Mean c/L</th></tr></thead><tbody>{overall_rows}</tbody></table>
</details>
</section>
</div>

<section class="explore" aria-labelledby="list-title">
<div class="map-col"><div id="map" role="region" aria-label="Map of stations within {num(RANGE_KM)} km">
<noscript><p class="map-note">The map needs JavaScript. Every station is listed alongside.</p></noscript>
</div></div>
<div class="list-col">
<h2 id="list-title">All {len(stations)} stations, cheapest first</h2>
<p class="sub">Charts share one scale: {num(y_domain[0])}–{num(y_domain[1])} c/L, {fmt_day(t0.date().isoformat())} to {fmt_day(last.date().isoformat())}. Hover a chart for each price change.</p>
<ol class="stations">{items}</ol>
</div>
</section>

<footer class="foot">
<p><strong>How this is worked out.</strong> Distance is the haversine great-circle distance from the search centre
({centre["lat"]:.4f}, {centre["lon"]:.4f}) with an Earth radius of {EARTH_RADIUS_KM} km; stations up to and including {num(RANGE_KM)} km are listed
({extras["excluded"]} further stations are left out). Only E10 records count. A station's listed price is its most recent E10 record;
if two of its records share a timestamp, the one later in the price file counts. A day's average covers stations with a price on or before
that day; a day before any in-range price has no average (— in the table, null in data.json).
The recommendation is the in-range station with the lowest listed price.</p>
<p>Machine-readable copy: <a href="data.json">data.json</a>. Map data © OpenStreetMap contributors.
Map library: Leaflet 1.9.4 (<a href="vendor/leaflet/LICENSE">licence</a>).</p>
</footer>
</div>
<div id="chart-tip" class="chart-tip" role="status" hidden></div>
<script src="vendor/leaflet/leaflet.js"></script>
<script src="data.js"></script>
<script>{JS}</script>
</body>
</html>
'''


CSS = r'''
:root{color-scheme:light dark;--bg:#f4f3ee;--surface:#fff;--ink:#1b1d1f;--ink-2:#474c52;--muted:#676d74;--rule:#e1dfd7;--grid:#ebe9e2;
--series:#2b5fd9;--best:#0a7a57;--best-ink:#fff;--best-wash:#e5f2ec;--radius:14px;
--shadow:0 1px 2px rgba(20,20,20,.05),0 6px 18px rgba(20,20,20,.05);
font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#111315;--surface:#1a1d20;--ink:#ecebe6;--ink-2:#c3c6ca;--muted:#959aa0;--rule:#2c3035;
--grid:#25292d;--series:#86a9ff;--best:#3fcf9b;--best-ink:#06251a;--best-wash:#132f28;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.45;font-size:15px}
.wrap{max-width:1240px;margin:0 auto;padding:28px 20px 48px}
h1,h2,h3{line-height:1.2;margin:0}
h1{font-size:clamp(1.7rem,3.2vw,2.4rem);letter-spacing:-.015em;margin:.25rem 0 .4rem}
h2{font-size:1.15rem}
.eyebrow{margin:0;text-transform:uppercase;letter-spacing:.08em;font-size:.72rem;font-weight:650;color:var(--muted)}
.lede,.sub{color:var(--ink-2);margin:.2rem 0 0}
.sub{font-size:.88rem;color:var(--muted);margin:.25rem 0 .6rem}
.num,.n,td,.station-meta,.hero-facts{font-variant-numeric:tabular-nums}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 22px}
.top{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:20px;margin-top:22px}
.hero{border-top:5px solid var(--best)}
.hero h2{font-size:1.6rem;margin-top:.35rem}
.hero-addr{margin:.25rem 0 0;color:var(--ink-2)}
.hero-price{margin:.7rem 0 .4rem;color:var(--best);font-weight:750;line-height:1}
.hero-price .num{font-size:3.6rem;letter-spacing:-.03em}
.hero-price .unit{font-size:1.1rem;margin-left:.35rem;color:var(--ink-2);font-weight:600}
.hero-facts{margin:.6rem 0 1rem;display:grid;gap:.45rem}
.hero-facts div{display:grid;grid-template-columns:8.5rem 1fr;gap:.6rem}
.hero-facts dt{color:var(--muted)}.hero-facts dd{margin:0}
.chart{display:block;width:100%;height:auto;overflow:visible}
.chart .grid{stroke:var(--grid);stroke-width:1}
.chart .tick{fill:var(--muted);font-size:12px}
.chart .value{fill:var(--ink);font-size:12.5px;font-weight:650}
.chart .line{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round;stroke-linecap:round;vector-effect:non-scaling-stroke}
.chart .dot{fill:var(--series);stroke:var(--surface);stroke-width:2}
.chart .crosshair{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3;visibility:hidden;vector-effect:non-scaling-stroke}
.chart .hit{fill:transparent;cursor:crosshair}
.is-best .chart .line{stroke:var(--best)}.is-best .chart .dot{fill:var(--best)}
details{margin-top:.6rem}
summary{cursor:pointer;color:var(--ink-2);font-size:.88rem}
table.hist{border-collapse:collapse;margin-top:.5rem;font-size:.86rem;min-width:14rem}
.hist th,.hist td{padding:.25rem .7rem .25rem 0;border-bottom:1px solid var(--rule);text-align:left}
.hist .n{text-align:right;padding-right:0}
.hist th{color:var(--muted);font-weight:600}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.explore{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:20px;margin-top:20px;align-items:start}
.map-col{position:sticky;top:16px}
#map{height:calc(100vh - 32px);min-height:440px;max-height:760px;border-radius:var(--radius);border:1px solid var(--rule);background:var(--grid)}
.map-note{padding:1rem;margin:0;color:var(--ink-2)}
.list-col h2{margin-top:.2rem}
.stations{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.station{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:14px 16px;scroll-margin-top:16px;transition:border-color .15s}
.station.is-best{border:2px solid var(--best);background:linear-gradient(var(--best-wash),var(--surface) 70%)}
.station.is-active{border-color:var(--series);box-shadow:0 0 0 2px var(--series) inset}
.station.is-best.is-active{border-color:var(--best);box-shadow:0 0 0 2px var(--best) inset}
.station-main{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:start}
.rank{display:inline-grid;place-items:center;min-width:1.7rem;height:1.7rem;border-radius:999px;background:var(--bg);color:var(--ink-2);font-size:.8rem;font-weight:650;border:1px solid var(--rule)}
.is-best .rank{background:var(--best);color:var(--best-ink);border-color:var(--best)}
.station-name{font-size:1rem}
.badge{display:inline-block;margin-left:.5rem;padding:.1rem .45rem;border-radius:999px;background:var(--best);color:var(--best-ink);font-size:.7rem;font-weight:700;vertical-align:.1em;text-transform:uppercase;letter-spacing:.05em}
.station-addr{margin:.15rem 0 0;color:var(--muted);font-size:.86rem}
.station-price{margin:0;text-align:right;white-space:nowrap;font-weight:700}
.station-price .num{font-size:1.45rem}
.station-price .unit{font-size:.8rem;color:var(--muted);margin-left:.2rem;font-weight:600}
.is-best .station-price{color:var(--best)}
.station-price.none{color:var(--muted);font-weight:500}
.station-meta{display:flex;flex-wrap:wrap;gap:.35rem 1rem;margin:.5rem 0 0;color:var(--ink-2);font-size:.86rem}
.sid{color:var(--muted);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.78rem}
.spark{margin:.55rem 0 0}
.spark figcaption{font-size:.78rem;color:var(--muted);margin-top:.1rem}
.station-actions{display:flex;flex-wrap:wrap;align-items:baseline;gap:.4rem 1rem}
.station-actions details{margin-top:.4rem}
button.locate{font:inherit;font-size:.85rem;cursor:pointer;border:1px solid var(--rule);background:var(--bg);color:var(--ink);border-radius:8px;padding:.35rem .7rem;margin-top:.5rem}
button.locate:hover{border-color:var(--series)}
button.locate.primary{background:var(--best);color:var(--best-ink);border-color:var(--best);font-weight:650;padding:.5rem .9rem}
button:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid var(--series);outline-offset:2px}
.foot{margin-top:28px;padding-top:14px;border-top:1px solid var(--rule);color:var(--muted);font-size:.84rem;max-width:80ch}
.foot a{color:var(--ink-2)}
.chart-tip{position:fixed;z-index:2000;pointer-events:none;background:var(--ink);color:var(--surface);font-size:.8rem;padding:.3rem .5rem;border-radius:6px;white-space:nowrap;font-variant-numeric:tabular-nums}
.leaflet-tooltip.best-label{background:var(--best);color:var(--best-ink);border-color:var(--best);font-weight:700}
.leaflet-tooltip-top.best-label:before{border-top-color:var(--best)}
.leaflet-popup-content{font-size:13px;line-height:1.45}
.leaflet-container{font-family:inherit}
@media (max-width:900px){.top,.explore{grid-template-columns:1fr}.map-col{position:relative;top:0}
#map{height:380px;min-height:0}}
@media (max-width:600px){.chart-overall .tick{font-size:24px}.chart-overall .value{font-size:25px}.chart-overall .dot{r:7}}
@media (forced-colors:active){.chart .line{stroke:CanvasText}.chart .dot{fill:CanvasText}}
'''

JS = r'''
(function () {
  'use strict';
  var data = window.FUEL_DATA, search = window.FUEL_SEARCH;
  var tip = document.getElementById('chart-tip');

  // Chart hover: crosshair plus tooltip for the band under the pointer.
  function hideTip(svg) {
    tip.hidden = true;
    var cross = svg && svg.querySelector('.crosshair');
    if (cross) cross.style.visibility = 'hidden';
  }
  Array.prototype.forEach.call(document.querySelectorAll('svg.chart'), function (svg) {
    var cross = svg.querySelector('.crosshair');
    svg.addEventListener('pointermove', function (e) {
      var band = e.target.closest ? e.target.closest('[data-tip]') : null;
      if (!band) { hideTip(svg); return; }
      tip.textContent = band.getAttribute('data-tip');
      tip.hidden = false;
      var x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      var y = Math.max(e.clientY - tip.offsetHeight - 12, 8);
      tip.style.left = x + 'px';
      tip.style.top = y + 'px';
      if (cross) {
        cross.setAttribute('x1', band.getAttribute('data-x'));
        cross.setAttribute('x2', band.getAttribute('data-x'));
        cross.style.visibility = 'visible';
      }
    });
    svg.addEventListener('pointerleave', function () { hideTip(svg); });
  });

  var mapEl = document.getElementById('map');
  if (!data || !search || typeof L === 'undefined') {
    mapEl.innerHTML = '<p class="map-note">The map could not load. Every station is listed alongside.</p>';
    return;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var css = getComputedStyle(document.documentElement);
  function colour(name) { return css.getPropertyValue(name).trim(); }

  var centre = [search.centre.lat, search.centre.lon];
  var map = L.map(mapEl, { scrollWheelZoom: false });
  // Set the view first: Leaflet only creates vector layers once the map has one.
  map.fitBounds(L.latLng(centre).toBounds(search.radius_km * 2000), { padding: [8, 8] });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
  }).addTo(map);
  L.circle(centre, {
    radius: search.radius_km * 1000, color: colour('--muted'), weight: 1.5, dashArray: '6 6',
    fillColor: colour('--series'), fillOpacity: 0.04, interactive: false
  }).addTo(map);
  L.circleMarker(centre, { radius: 5, color: colour('--surface'), weight: 2, fillColor: colour('--ink'), fillOpacity: 1 })
    .bindTooltip('Search centre: Greenwich', { direction: 'top', offset: [0, -6] })
    .addTo(map);

  var bestId = data.recommendation.station_id;
  var markers = {};
  function highlight(id) {
    Array.prototype.forEach.call(document.querySelectorAll('.station.is-active'), function (el) {
      el.classList.remove('is-active');
    });
    var item = document.getElementById('station-' + id);
    if (item) item.classList.add('is-active');
    return item;
  }

  data.stations.forEach(function (s) {
    var best = s.id === bestId, priced = s.listed_price_cpl !== null;
    var price = priced ? s.listed_price_cpl.toFixed(1) + ' c/L' : 'No E10 price';
    var item = document.getElementById('station-' + s.id);
    var updated = item ? item.querySelector('.js-updated') : null;
    var marker = L.circleMarker([s.lat, s.lon], {
      radius: best ? 10 : 7, weight: 2, color: colour('--surface'),
      fillColor: best ? colour('--best') : priced ? colour('--series') : colour('--muted'), fillOpacity: 1
    });
    marker.bindTooltip(best ? 'Cheapest · ' + price : esc(s.name) + ' · ' + price, {
      direction: 'top', offset: [0, best ? -10 : -7], permanent: best, className: best ? 'best-label' : ''
    });
    marker.bindPopup(
      '<strong>' + esc(s.name) + '</strong><br>' + price + ' · ' + s.distance_km.toFixed(2) + ' km away' +
      (updated ? '<br>Updated ' + esc(updated.textContent) : '') +
      '<br><a href="#station-' + esc(s.id) + '">' + (priced ? 'Price history' : 'In the list') + '</a>'
    );
    marker.on('click', function () { highlight(s.id); });
    marker.addTo(map);
    markers[s.id] = marker;
  });
  if (markers[bestId]) markers[bestId].bringToFront();

  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('button.locate') : null;
    if (!btn) return;
    var id = btn.getAttribute('data-station-id');
    var marker = markers[id];
    if (!marker) return;
    highlight(id);
    if (window.matchMedia('(max-width: 900px)').matches) mapEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    map.setView(marker.getLatLng(), Math.max(map.getZoom(), 14));
    marker.openPopup();
  });
})();
'''


# ---------------------------------------------------------------- output

def build(root: Path, target: Path):
    stations_doc = json.loads((root / 'data' / 'stations.json').read_text(encoding='utf-8'))
    prices_doc = json.loads((root / 'data' / 'prices.json').read_text(encoding='utf-8'))
    data, extras = compute(stations_doc, prices_doc)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / 'vendor' / 'leaflet', target / 'vendor' / 'leaflet')
    (target / 'data.json').write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    search = {'centre': extras['centre'], 'radius_km': RANGE_KM}
    (target / 'data.js').write_text(
        'window.FUEL_DATA = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'
        'window.FUEL_SEARCH = ' + json.dumps(search, separators=(',', ':')) + ';\n', encoding='utf-8')
    (target / 'index.html').write_text(render(data, extras), encoding='utf-8')
    return data


def tree_diff(a: Path, b: Path):
    """Relative paths that differ between two directory trees (missing, extra or changed)."""
    files_a = {p.relative_to(a) for p in a.rglob('*') if p.is_file()}
    files_b = {p.relative_to(b) for p in b.rglob('*') if p.is_file()}
    changed = {p for p in files_a & files_b if not filecmp.cmp(a / p, b / p, shallow=False)}
    return sorted(str(p) for p in (files_a ^ files_b) | changed)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='compare a fresh build with out/ instead of writing it')
    parser.add_argument('--root', type=Path, default=ROOT, help='directory holding data/ and vendor/leaflet/ (default: repo)')
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / 'out'
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / 'out'
        data = build(root, fresh)
        if args.check:
            diff = tree_diff(fresh, out) if out.is_dir() else ['out/ is missing']
            for path in diff:
                print('differs:', path)
            print('out/ is up to date' if not diff else f'out/ is stale: {len(diff)} path(s) differ')
            return 1 if diff else 0
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(fresh, out)
    print(f'wrote {out}/ with {len(data["stations"])} stations; '
          f'recommended {data["recommendation"]["station_id"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
