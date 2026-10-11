#!/usr/bin/env python3
"""Build the static E10 price page in out/ from data/ and vendor/leaflet/.

    python3 tools/build_site.py          write out/
    python3 tools/build_site.py --check  exit 1 unless out/ matches a fresh build

Standard library only. The output is deterministic: the same inputs give the
same bytes, so --check can confirm the committed out/ is current.
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
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
VENDOR_DIR = ROOT / "vendor" / "leaflet"
OUT_DIR = ROOT / "out"

EARTH_RADIUS_KM = 6371.0
RANGE_KM = 10.0
FUEL = "E10"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --- Model -----------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def latest(records: list[dict]) -> dict:
    """Most recent record by recorded_at instant. On an exact tie the record
    later in file order wins, so the result never depends on sort stability."""
    return max(records, key=lambda r: (r["_at"], r["_seq"]))


def rank_key(s: dict) -> tuple:
    """Cheapest first; ties go to the nearer station, then the lower ID.
    Stations with no E10 price sort last."""
    price = s["listed"]["price_cpl"] if s["listed"] else math.inf
    return (price, s["distance_km"], s["station"]["id"])


def build_model(stations_doc: dict, prices_doc: dict) -> dict:
    centre = stations_doc["centre"]
    e10 = []
    for seq, record in enumerate(prices_doc["records"]):
        if record["fuel"] != FUEL:
            continue
        e10.append(dict(record, _at=datetime.fromisoformat(record["recorded_at"]), _seq=seq,
                        _day=record["recorded_at"][:10]))

    by_station: dict[str, list[dict]] = {}
    for record in e10:
        by_station.setdefault(record["station_id"], []).append(record)

    in_range = []
    for station in stations_doc["stations"]:
        distance = haversine_km(centre["lat"], centre["lon"], station["lat"], station["lon"])
        if distance > RANGE_KM:
            continue
        records = by_station.get(station["id"], [])
        history = sorted(records, key=lambda r: (r["_at"], r["_seq"]))
        in_range.append({"station": station, "distance_km": distance, "records": history,
                         "listed": latest(records) if records else None})

    priced = [s for s in in_range if s["listed"]]
    if not priced:
        raise SystemExit("no in-range station has an E10 price")
    best = min(priced, key=rank_key)

    overall = []
    for day in sorted({r["_day"] for r in e10}):
        prices = []
        for s in sorted(in_range, key=lambda s: s["station"]["id"]):
            upto = [r for r in s["records"] if r["_day"] <= day]
            if upto:
                prices.append(latest(upto)["price_cpl"])
        overall.append({"date": day, "mean_price_cpl": math.fsum(prices) / len(prices) if prices else None,
                        "stations": len(prices)})

    return {"centre": centre, "in_range": in_range, "best": best, "overall": overall}


def public_data(model: dict) -> dict:
    """The out/data.json contract: what the page shows, in-range stations only."""
    ranked = sorted(model["in_range"], key=rank_key)
    return {
        "recommendation": {"station_id": model["best"]["station"]["id"]},
        "stations": [{
            "id": s["station"]["id"],
            "name": s["station"]["name"],
            "lat": s["station"]["lat"],
            "lon": s["station"]["lon"],
            "distance_km": s["distance_km"],
            "listed_price_cpl": s["listed"]["price_cpl"] if s["listed"] else None,
            "history": [{"recorded_at": r["recorded_at"], "price_cpl": r["price_cpl"]} for r in s["records"]],
        } for s in ranked],
        "overall_history": [{"date": p["date"], "mean_price_cpl": p["mean_price_cpl"]} for p in model["overall"]],
    }


# --- Formatting --------------------------------------------------------------

def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fmt_price(cpl: float) -> str:
    return f"{cpl:.1f}"


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def fmt_mean(cpl: float | None) -> str:
    return "—" if cpl is None else f"{cpl:.2f}"


def fmt_day(iso_day: str, year: bool = False) -> str:
    d = date.fromisoformat(iso_day)
    return f"{d.day} {MONTHS[d.month - 1]}" + (f" {d.year}" if year else "")


def fmt_stamp(recorded_at: str) -> str:
    """Wall-clock time as written in the record, e.g. '14 Sep 2026, 5:40 pm'."""
    t = datetime.fromisoformat(recorded_at)
    hour = t.hour % 12 or 12
    return f"{t.day} {MONTHS[t.month - 1]} {t.year}, {hour}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    if hi - lo < 1e-9:  # a flat series still needs a non-zero axis span
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    magnitude = 10 ** math.floor(math.log10(span / target))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if span / (m * magnitude) <= target)
    start, stop = math.floor(lo / step) * step, math.ceil(hi / step) * step
    count = round((stop - start) / step)
    return [round(start + i * step, 6) for i in range(count + 1)]


def fmt_tick(value: float, step: float) -> str:
    decimals = 0
    while decimals < 6 and abs(step * 10 ** decimals - round(step * 10 ** decimals)) > 1e-6:
        decimals += 1
    return f"{value:.{decimals}f}"


# --- Charts --------------------------------------------------------------------

def overall_chart(overall: list[dict]) -> str:
    points = [p for p in overall if p["mean_price_cpl"] is not None]
    width, height = 760, 260
    left, right, top, bottom = 52, 72, 18, 34
    ticks = nice_ticks(min(p["mean_price_cpl"] for p in points), max(p["mean_price_cpl"] for p in points))
    y_lo, y_hi = ticks[0], ticks[-1]
    ordinals = [date.fromisoformat(p["date"]).toordinal() for p in points]
    x_lo, x_hi = ordinals[0], ordinals[-1]

    def x(ordinal: int) -> float:
        return left + (ordinal - x_lo) / max(x_hi - x_lo, 1) * (width - left - right)

    def y(value: float) -> float:
        return top + (y_hi - value) / (y_hi - y_lo) * (height - top - bottom)

    parts = [f'<svg class="trend" viewBox="0 0 {width} {height}" role="img" '
             f'aria-labelledby="trend-title trend-desc" data-plot-left="{left}" data-plot-right="{width - right}">',
             '<title id="trend-title">Average listed E10 price within 10 km, by day</title>',
             f'<desc id="trend-desc">From {fmt_price(points[0]["mean_price_cpl"])} c/L on {fmt_day(points[0]["date"])} '
             f'to {fmt_price(points[-1]["mean_price_cpl"])} c/L on {fmt_day(points[-1]["date"])}. '
             'The table below the chart lists every value.</desc>']
    for tick in ticks:
        ty = y(tick)
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{ty + 4:.1f}" text-anchor="end">'
                     f'{fmt_tick(tick, ticks[1] - ticks[0])}</text>')
    step = max(1, math.ceil(len(points) / 7))
    for i, p in enumerate(points):
        if i % step == 0 or i == len(points) - 1:
            parts.append(f'<text class="tick" x="{x(ordinals[i]):.1f}" y="{height - 10}" '
                         f'text-anchor="middle">{fmt_day(p["date"])}</text>')
    path = " ".join(f'{"M" if i == 0 else "L"}{x(o):.1f},{y(p["mean_price_cpl"]):.1f}'
                    for i, (o, p) in enumerate(zip(ordinals, points)))
    parts.append(f'<path class="line" d="{path}"/>')
    parts.append(f'<line class="crosshair" x1="0" x2="0" y1="{top}" y2="{height - bottom}" visibility="hidden"/>')
    for i, (o, p) in enumerate(zip(ordinals, points)):
        parts.append(f'<circle class="pt" cx="{x(o):.1f}" cy="{y(p["mean_price_cpl"]):.1f}" r="4" '
                     f'data-date="{esc(fmt_day(p["date"], True))}" data-value="{p["mean_price_cpl"]:.2f}" '
                     f'data-stations="{p["stations"]}"/>')
    end_x, end_y = x(ordinals[-1]), y(points[-1]["mean_price_cpl"])
    parts.append(f'<circle class="end" cx="{end_x:.1f}" cy="{end_y:.1f}" r="4"/>')
    parts.append(f'<text class="end-label" x="{end_x + 10:.1f}" y="{end_y + 4:.1f}">'
                 f'{fmt_price(points[-1]["mean_price_cpl"])}</text>')
    parts.append(f'<rect class="hit" x="{left}" y="{top}" width="{width - left - right}" '
                 f'height="{height - top - bottom}"/>')
    parts.append("</svg>")
    return "".join(parts)


def sparkline(records: list[dict], t_lo: float, t_hi: float, p_lo: float, p_hi: float) -> str:
    """Step line on scales shared by every station, so the sparklines compare."""
    width, height, pad = 200, 40, 5

    def x(t: datetime) -> float:
        return pad + (t.timestamp() - t_lo) / max(t_hi - t_lo, 1) * (width - 2 * pad)

    def y(price: float) -> float:
        return pad + (p_hi - price) / max(p_hi - p_lo, 1e-9) * (height - 2 * pad)

    coords = []
    for i, r in enumerate(records):
        if i:
            coords.append(f"{x(r['_at']):.1f},{y(records[i - 1]['price_cpl']):.1f}")
        coords.append(f"{x(r['_at']):.1f},{y(r['price_cpl']):.1f}")
    last = records[-1]
    low = min(r["price_cpl"] for r in records)
    high = max(r["price_cpl"] for r in records)
    label = (f"E10 price history: {len(records)} records from {fmt_day(records[0]['_day'])} to "
             f"{fmt_day(last['_day'])}, low {fmt_price(low)}, high {fmt_price(high)}, latest {fmt_price(last['price_cpl'])} c/L")
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
            f'aria-label="{esc(label)}"><polyline points="{" ".join(coords)}"/>'
            f'<circle cx="{x(last["_at"]):.1f}" cy="{y(last["price_cpl"]):.1f}" r="3.5"/></svg>')


# --- Page ----------------------------------------------------------------------

def station_item(s: dict, rank: int, is_best: bool, spark: str) -> str:
    st, listed = s["station"], s["listed"]
    rows = "".join(f'<tr><td>{esc(fmt_stamp(r["recorded_at"]))}</td><td class="num">{fmt_price(r["price_cpl"])}</td></tr>'
                   for r in reversed(s["records"]))
    badge = '<span class="badge">Cheapest</span>' if is_best else ""
    price = (f'{fmt_price(listed["price_cpl"])}<span class="unit"> c/L</span>' if listed
             else '<span class="unit">No E10 price</span>')
    updated = f"Listed {fmt_stamp(listed['recorded_at'])}" if listed else "No E10 records"
    return f"""
      <li class="station{' is-best' if is_best else ''}" id="station-{esc(st['id'])}" data-station-id="{esc(st['id'])}"
          data-price="{listed['price_cpl'] if listed else 'Infinity'}" data-distance="{s['distance_km']:.6f}" data-rank="{rank}">
        <div class="st-head">
          <span class="st-rank" title="Price rank">{rank}</span>
          <div class="st-title">
            <h3><button type="button" class="st-name" aria-label="Show {esc(st['name'])} on the map">{esc(st['name'])}</button>{badge}</h3>
            <p class="st-meta"><span class="st-addr">{esc(st['address'])}</span> · {esc(st['brand'])} · <span class="st-id">{esc(st['id'])}</span></p>
          </div>
          <div class="st-figs">
            <span class="st-price">{price}</span>
            <span class="st-dist">{s['distance_km']:.2f} km</span>
          </div>
        </div>
        <div class="st-trend">
          {spark}
          <span class="st-updated">{esc(updated)}</span>
        </div>
        <details class="st-history">
          <summary>E10 price history · {len(s['records'])} records</summary>
          <table><thead><tr><th scope="col">Recorded</th><th scope="col" class="num">c/L</th></tr></thead><tbody>{rows}</tbody></table>
        </details>
      </li>"""


def render_page(model: dict) -> str:
    in_range = model["in_range"]
    best = model["best"]
    ranked = sorted(in_range, key=rank_key)
    all_records = [r for s in in_range for r in s["records"]]
    t_lo = min(r["_at"] for r in all_records).timestamp()
    t_hi = max(r["_at"] for r in all_records).timestamp()
    p_lo = min(r["price_cpl"] for r in all_records)
    p_hi = max(r["price_cpl"] for r in all_records)
    items = "".join(station_item(s, i + 1, s is best,
                                 sparkline(s["records"], t_lo, t_hi, p_lo, p_hi) if s["records"] else "")
                    for i, s in enumerate(ranked))

    listed_prices = [s["listed"]["price_cpl"] for s in in_range if s["listed"]]
    average_listed = math.fsum(listed_prices) / len(listed_prices)
    saving = average_listed - best["listed"]["price_cpl"]
    latest_day = max(r["_day"] for r in all_records)
    overall = model["overall"]
    trend_rows = "".join(
        f'<tr><td>{esc(fmt_day(p["date"], True))}</td><td class="num">{fmt_mean(p["mean_price_cpl"])}</td>'
        f'<td class="num">{p["stations"]}</td></tr>' for p in overall)
    st, listed = best["station"], best["listed"]
    centre = model["centre"]

    return f"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cheapest E10 near Greenwich, NSW</title>
<link rel="stylesheet" href="vendor/leaflet/leaflet.css">
<style>
{CSS}
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    <p class="eyebrow">E10 fuel · Greenwich, NSW</p>
    <h1>Where to buy E10 near Greenwich</h1>
    <p class="lede">{len(in_range)} stations within {RANGE_KM:g} km of Greenwich, ranked by their latest listed E10 price.
      Prices are a snapshot of records up to {esc(fmt_day(latest_day, True))}.</p>
  </header>

  <section class="reco" data-recommended-station="{esc(st['id'])}" aria-labelledby="reco-title">
    <div class="reco-figure">
      <p class="reco-kicker" id="reco-title">Cheapest E10 within {RANGE_KM:g} km</p>
      <p class="reco-price">{fmt_price(listed['price_cpl'])}<span class="unit"> c/L</span></p>
      <p class="reco-saving">{saving:.1f} c/L below the {fmt_price(average_listed)} c/L average listed price of {plural(len(listed_prices), "station")} in range</p>
    </div>
    <div class="reco-detail">
      <h2>{esc(st['name'])}</h2>
      <p>{esc(st['address'])} · {esc(st['brand'])}</p>
      <p>{best['distance_km']:.2f} km from Greenwich · listed {esc(fmt_stamp(listed['recorded_at']))}</p>
      <p class="reco-id">Station {esc(st['id'])}</p>
      <button type="button" class="reco-locate" data-station-id="{esc(st['id'])}">Show on map</button>
    </div>
  </section>

  <div class="layout">
    <section class="map-panel" aria-label="Map of stations">
      <div id="map" data-centre-lat="{centre['lat']}" data-centre-lon="{centre['lon']}" data-radius-km="{RANGE_KM:g}">
        <noscript><p class="map-fallback">The map needs JavaScript. Every station is in the list.</p></noscript>
      </div>
      <p class="map-note">Pins show the listed price in cents per litre. The circle marks {RANGE_KM:g} km from Greenwich.</p>
    </section>

    <section class="list-panel" aria-labelledby="list-title">
      <div class="list-head">
        <h2 id="list-title">All {len(in_range)} stations in range</h2>
        <div class="sort" role="group" aria-label="Sort stations">
          <button type="button" data-sort="price" aria-pressed="true">Cheapest</button>
          <button type="button" data-sort="distance" aria-pressed="false">Nearest</button>
        </div>
      </div>
      <ol class="stations" id="stations">{items}
      </ol>
    </section>
  </div>

  <section class="trend-panel" aria-labelledby="trend-heading">
    <h2 id="trend-heading">Average E10 price within {RANGE_KM:g} km</h2>
    <p class="trend-sub">Each day's mean of every in-range station's latest price recorded on or before that day, in cents per litre.</p>
    <div class="trend-wrap">
      {overall_chart(overall)}
      <div class="tip" role="status" hidden><strong class="tip-value"></strong><span class="tip-date"></span></div>
    </div>
    <details class="trend-table">
      <summary>Show the daily averages as a table</summary>
      <table><thead><tr><th scope="col">Day</th><th scope="col" class="num">Mean c/L</th><th scope="col" class="num">Stations</th></tr></thead>
      <tbody>{trend_rows}</tbody></table>
    </details>
  </section>

  <footer class="foot">
    <p>Listed price is each station's most recent E10 record. Distances are straight-line (haversine) from
      {centre['lat']}, {centre['lon']}. Other fuels are ignored.</p>
  </footer>
</div>
<script src="vendor/leaflet/leaflet.js"></script>
<script src="data.js"></script>
<script>
{SCRIPT}
</script>
</body>
</html>
"""


CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6e69;
  --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10);
  --accent: #2a78d6; --accent-fill: #256abf; --accent-ink: #1c5cab; --accent-wash: rgba(42,120,214,0.10);
  --on-accent: #ffffff;
  --good: #006300;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #9a9890;
    --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
    --accent: #3987e5; --accent-fill: #3987e5; --accent-ink: #86b6ef; --accent-wash: rgba(57,135,229,0.16);
    --on-accent: #0b0b0b;
    --good: #0ca30c;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
.page { max-width: 1240px; margin: 0 auto; padding: 28px 20px 40px; }
h1, h2, h3, p { margin: 0; }
button { font: inherit; color: inherit; }
.num, .st-figs, .tick { font-variant-numeric: tabular-nums; }

.masthead { margin-bottom: 20px; }
.eyebrow { color: var(--muted); font-size: 13px; letter-spacing: 0.02em; }
.masthead h1 { font-size: 28px; line-height: 1.2; margin: 4px 0 6px; }
.lede { color: var(--ink-2); max-width: 62ch; }

.reco { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); gap: 24px;
  background: var(--surface); border: 1px solid var(--ring); border-left: 4px solid var(--accent);
  border-radius: 10px; padding: 22px 24px; margin-bottom: 24px; }
.reco-kicker { color: var(--ink-2); font-weight: 600; }
.reco-price { font-size: 56px; font-weight: 650; line-height: 1.1; margin: 4px 0 6px; }
.reco-price .unit, .st-price .unit { font-size: 0.4em; font-weight: 500; color: var(--ink-2); }
.reco-saving { color: var(--good); font-weight: 600; font-size: 14px; }
.reco-detail h2 { font-size: 22px; margin-bottom: 6px; }
.reco-detail p { color: var(--ink-2); }
.reco-detail .reco-id { font-size: 13px; color: var(--muted); margin-top: 2px; }
.reco-locate { margin-top: 12px; padding: 7px 14px; border-radius: 6px; border: 0; cursor: pointer;
  background: var(--accent-fill); color: var(--on-accent); font-weight: 600; }
.reco-locate:hover { filter: brightness(1.08); }

.layout { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 24px; align-items: start; }
.map-panel { position: sticky; top: 16px; }
#map { height: 600px; border-radius: 10px; border: 1px solid var(--ring); background: var(--grid); }
.map-note, .map-fallback { color: var(--muted); font-size: 13px; margin-top: 8px; }
.map-failed { display: grid; place-items: center; padding: 24px; text-align: center; color: var(--ink-2); }

.list-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px;
  margin-bottom: 10px; }
.list-head h2, .trend-panel h2 { font-size: 18px; }
.sort { display: inline-flex; border: 1px solid var(--ring); border-radius: 8px; overflow: hidden; }
.sort button { border: 0; background: var(--surface); padding: 5px 12px; cursor: pointer; color: var(--ink-2); }
.sort button[aria-pressed="true"] { background: var(--accent-wash); color: var(--ink); font-weight: 600; }

.stations { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.station { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px; padding: 12px 14px;
  transition: box-shadow 0.2s, border-color 0.2s; }
.station.is-best { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.station.flash { box-shadow: 0 0 0 3px var(--accent-wash), inset 3px 0 0 var(--accent); border-color: var(--accent); }
.st-head { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 12px; align-items: start; }
.st-rank { min-width: 26px; height: 26px; border-radius: 13px; display: grid; place-items: center;
  font-size: 13px; font-weight: 600; color: var(--ink-2); background: var(--page); border: 1px solid var(--ring); }
.is-best .st-rank { background: var(--accent-fill); color: var(--on-accent); border-color: var(--accent-fill); }
.st-title h3 { font-size: 16px; line-height: 1.3; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.st-name { border: 0; background: none; padding: 0; font-weight: 600; text-align: left; cursor: pointer; }
.st-name:hover { text-decoration: underline; text-underline-offset: 3px; }
.badge { font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 999px;
  background: var(--accent-wash); color: var(--accent-ink); }
.st-meta { color: var(--ink-2); font-size: 13px; }
.st-id { color: var(--muted); }
.st-figs { display: grid; justify-items: end; }
.st-price { font-size: 22px; font-weight: 650; line-height: 1.1; }
.st-dist { color: var(--ink-2); font-size: 13px; }
.st-trend { display: flex; align-items: center; gap: 12px; margin: 8px 0 0 38px; }
.st-updated { color: var(--muted); font-size: 12px; }
.spark polyline { fill: none; stroke: var(--muted); stroke-width: 1.5; stroke-linejoin: round; stroke-linecap: round; }
.spark circle { fill: var(--ink-2); stroke: var(--surface); stroke-width: 2; }
.is-best .spark polyline { stroke: var(--accent); stroke-width: 2; }
.is-best .spark circle { fill: var(--accent); }
details { margin: 6px 0 0 38px; }
summary { cursor: pointer; color: var(--ink-2); font-size: 13px; }
table { border-collapse: collapse; margin-top: 6px; font-size: 13px; }
th, td { padding: 3px 14px 3px 0; text-align: left; border-bottom: 1px solid var(--grid); }
th { color: var(--muted); font-weight: 600; }
.num { text-align: right; }

.trend-panel { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px;
  padding: 20px 22px; margin-top: 28px; }
.trend-sub { color: var(--ink-2); font-size: 14px; margin: 2px 0 10px; }
.trend-wrap { position: relative; overflow-x: auto; }
.trend { width: 100%; min-width: 560px; height: auto; display: block; }
.trend .grid { stroke: var(--grid); stroke-width: 1; }
.trend .tick { fill: var(--muted); font-size: 12px; }
.trend .line { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.trend .pt { fill: var(--accent); stroke: var(--surface); stroke-width: 2; opacity: 0; }
.trend .pt.on { opacity: 1; }
.trend .end { fill: var(--accent); stroke: var(--surface); stroke-width: 2; }
.trend .end-label { fill: var(--ink); font-size: 13px; font-weight: 600; }
.trend .crosshair { stroke: var(--axis); stroke-width: 1; }
.trend .hit { fill: transparent; cursor: crosshair; }
.trend:focus { outline: 2px solid var(--accent); outline-offset: 4px; border-radius: 4px; }
.tip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--ring);
  border-radius: 6px; padding: 5px 9px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); font-size: 13px;
  display: grid; white-space: nowrap; transform: translate(-50%, -110%); }
.tip.below { transform: translate(-50%, 14px); }
.tip[hidden] { display: none; }
.tip-date { color: var(--ink-2); }
.trend-table { margin-left: 0; }

.foot { color: var(--muted); font-size: 13px; margin-top: 24px; max-width: 80ch; }

.price-pin { background: none; border: 0; }
.price-pin span { display: inline-block; transform: translate(-50%, -50%); padding: 2px 7px; border-radius: 999px;
  background: #fcfcfb; color: #0b0b0b; border: 1px solid rgba(11,11,11,0.35); font: 600 12px/1.4 system-ui, sans-serif;
  white-space: nowrap; box-shadow: 0 1px 3px rgba(0,0,0,0.25); font-variant-numeric: tabular-nums; }
.price-pin.best span { background: #256abf; color: #ffffff; border-color: #1c5cab; font-size: 13px; padding: 3px 9px; }
.price-pin.unpriced span { color: #52514e; font-weight: 500; font-style: italic; }
.centre-pin span { display: inline-block; transform: translate(-50%, -50%); width: 12px; height: 12px; border-radius: 50%;
  background: #0b0b0b; border: 2px solid #fcfcfb; box-shadow: 0 0 0 1px #0b0b0b; }
.leaflet-popup-content { font: 13px/1.45 system-ui, sans-serif; }
.leaflet-popup-content strong { font-size: 14px; }

@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .map-panel { position: static; }
  #map { height: 380px; }
  .reco { grid-template-columns: 1fr; gap: 12px; }
  .reco-price { font-size: 48px; }
  .st-trend { flex-wrap: wrap; gap: 4px 12px; }
}
""".strip()


SCRIPT = r"""
(function () {
  "use strict";
  var data = window.E10_DATA;
  var list = document.getElementById("stations");
  var items = Array.prototype.slice.call(list.querySelectorAll(".station"));
  var byId = {};
  items.forEach(function (li) { byId[li.dataset.stationId] = li; });

  // Sorting
  var sortButtons = document.querySelectorAll(".sort button");
  Array.prototype.forEach.call(sortButtons, function (button) {
    button.addEventListener("click", function () {
      var key = button.dataset.sort;
      Array.prototype.forEach.call(sortButtons, function (b) { b.setAttribute("aria-pressed", String(b === button)); });
      items.slice().sort(function (a, b) {
        var pa = parseFloat(a.dataset.price), pb = parseFloat(b.dataset.price);
        var da = parseFloat(a.dataset.distance), db = parseFloat(b.dataset.distance);
        return key === "distance" ? (da - db || pa - pb) : (Number(a.dataset.rank) - Number(b.dataset.rank));
      }).forEach(function (li) { list.appendChild(li); });
    });
  });

  function narrow() { return window.matchMedia("(max-width: 900px)").matches; }

  function flash(li, scroll) {
    items.forEach(function (other) { other.classList.remove("flash"); });
    li.classList.add("flash");
    if (scroll) { li.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
  }

  // Map
  var mapEl = document.getElementById("map");
  var markers = {};
  if (!data || typeof L === "undefined") {
    mapEl.classList.add("map-failed");
    mapEl.textContent = "The map could not load. Every station is in the list.";
  } else {
    var centre = [parseFloat(mapEl.dataset.centreLat), parseFloat(mapEl.dataset.centreLon)];
    var map = L.map(mapEl, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>'
    }).addTo(map);
    L.circle(centre, {
      radius: parseFloat(mapEl.dataset.radiusKm) * 1000,
      color: "#2a78d6", weight: 1.5, opacity: 0.7, fillColor: "#2a78d6", fillOpacity: 0.04, interactive: false
    }).addTo(map);
    L.marker(centre, {
      icon: L.divIcon({ className: "centre-pin", html: "<span></span>", iconSize: [0, 0] }),
      title: "Greenwich (search centre)", keyboard: false
    }).addTo(map).bindTooltip("Greenwich");

    var bounds = L.latLngBounds([centre]);
    var bestId = data.recommendation.station_id;
    data.stations.forEach(function (s) {
      var li = byId[s.id];
      var isBest = s.id === bestId;
      var priced = s.listed_price_cpl !== null;
      var price = priced ? s.listed_price_cpl.toFixed(1) + " c/L" : "No E10 price";
      var pin = document.createElement("span");
      pin.textContent = priced ? s.listed_price_cpl.toFixed(1) : "No price";
      var marker = L.marker([s.lat, s.lon], {
        icon: L.divIcon({ className: "price-pin" + (isBest ? " best" : "") + (priced ? "" : " unpriced"),
                          html: pin.outerHTML, iconSize: [0, 0] }),
        title: s.name + ": " + price,
        riseOnHover: true,
        zIndexOffset: isBest ? 1000 : 0
      }).addTo(map);

      var popup = document.createElement("div");
      var name = document.createElement("strong");
      name.textContent = s.name;
      popup.appendChild(name);
      var lines = [
        (li ? li.querySelector(".st-addr").textContent : ""),
        price + " · " + s.distance_km.toFixed(2) + " km away",
        isBest ? "Cheapest E10 within 10 km" : ""
      ];
      lines.forEach(function (text) {
        if (!text) { return; }
        popup.appendChild(document.createElement("br"));
        popup.appendChild(document.createTextNode(text));
      });
      marker.bindPopup(popup);
      marker.on("click", function () { if (li) { flash(li, !narrow()); } });
      markers[s.id] = marker;
      bounds.extend([s.lat, s.lon]);
    });
    map.fitBounds(bounds, { padding: [24, 24] });

    var focusStation = function (id) {
      var marker = markers[id];
      if (!marker) { return; }
      map.setView(marker.getLatLng(), Math.max(map.getZoom(), 14));
      marker.openPopup();
      if (narrow()) { mapEl.scrollIntoView({ block: "center", behavior: "smooth" }); }
    };
    items.forEach(function (li) {
      li.querySelector(".st-name").addEventListener("click", function () {
        flash(li, false);
        focusStation(li.dataset.stationId);
      });
    });
    document.querySelector(".reco-locate").addEventListener("click", function (event) {
      var id = event.currentTarget.dataset.stationId;
      focusStation(id);
      mapEl.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  }

  // Trend chart: crosshair and tooltip that snap to the nearest day
  var svg = document.querySelector(".trend");
  var tip = document.querySelector(".tip");
  var points = Array.prototype.slice.call(svg.querySelectorAll(".pt"));
  var cross = svg.querySelector(".crosshair");
  var active = -1;
  var wrap = svg.parentNode;
  wrap.scrollLeft = wrap.scrollWidth;  // narrow screens scroll the chart; open on the latest day
  function show(index, reveal) {
    if (index < 0 || index >= points.length) { return; }
    active = index;
    var pt = points[index];
    points.forEach(function (p) { p.classList.toggle("on", p === pt); });
    var cx = pt.getAttribute("cx");
    cross.setAttribute("x1", cx);
    cross.setAttribute("x2", cx);
    cross.setAttribute("visibility", "visible");
    tip.querySelector(".tip-value").textContent = parseFloat(pt.dataset.value).toFixed(2) + " c/L";
    tip.querySelector(".tip-date").textContent = pt.dataset.date + " · " + pt.dataset.stations + " stations";
    var box = svg.getBoundingClientRect();
    var scale = box.width / svg.viewBox.baseVal.width;
    var x = parseFloat(cx) * scale;
    if (reveal && (x < wrap.scrollLeft + 24 || x > wrap.scrollLeft + wrap.clientWidth - 24)) {
      wrap.scrollLeft = x - wrap.clientWidth / 2;  // keyboard selection scrolls its day into view
    }
    tip.hidden = false;
    var half = tip.offsetWidth / 2;
    // Keep the tooltip inside the visible part of the (possibly scrolled) chart.
    tip.style.left = Math.min(Math.max(x, wrap.scrollLeft + half), wrap.scrollLeft + wrap.clientWidth - half) + "px";
    var y = parseFloat(pt.getAttribute("cy")) * scale;
    tip.style.top = y + "px";
    tip.classList.toggle("below", y < tip.offsetHeight * 1.1 + 4);  // no room above a high point
  }
  function hide() {
    active = -1;
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
    points.forEach(function (p) { p.classList.remove("on"); });
  }
  function nearest(clientX) {
    var box = svg.getBoundingClientRect();
    var x = (clientX - box.left) * svg.viewBox.baseVal.width / box.width;
    var best = 0;
    points.forEach(function (p, i) {
      if (Math.abs(p.getAttribute("cx") - x) < Math.abs(points[best].getAttribute("cx") - x)) { best = i; }
    });
    return best;
  }
  svg.addEventListener("pointermove", function (event) { show(nearest(event.clientX)); });
  svg.addEventListener("pointerdown", function (event) { show(nearest(event.clientX)); });
  // A mouse leaving hides the tooltip; a tapped tooltip stays until the next tap elsewhere.
  svg.addEventListener("pointerleave", function (event) { if (event.pointerType === "mouse") { hide(); } });
  document.addEventListener("pointerdown", function (event) { if (!svg.contains(event.target)) { hide(); } });
  svg.setAttribute("tabindex", "0");
  svg.addEventListener("focus", function () { show(points.length - 1, true); });
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", function (event) {
    if (event.key === "ArrowLeft") { show(Math.max(0, active - 1), true); event.preventDefault(); }
    if (event.key === "ArrowRight") { show(Math.min(points.length - 1, active + 1), true); event.preventDefault(); }
    if (event.key === "Escape") { hide(); }
  });
})();
""".strip()


# --- Output --------------------------------------------------------------------

def build(target: Path) -> None:
    stations_doc = json.loads((DATA_DIR / "stations.json").read_text(encoding="utf-8"))
    prices_doc = json.loads((DATA_DIR / "prices.json").read_text(encoding="utf-8"))
    model = build_model(stations_doc, prices_doc)
    payload = public_data(model)
    target.mkdir(parents=True, exist_ok=True)
    (target / "data.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (target / "data.js").write_text("window.E10_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
                                    encoding="utf-8")
    (target / "index.html").write_text(render_page(model), encoding="utf-8")
    shutil.copytree(VENDOR_DIR, target / "vendor" / "leaflet")


def same_tree(a: Path, b: Path) -> list[str]:
    """Paths that differ between two directory trees, compared byte for byte."""
    files_a = {p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file()}
    diffs = sorted(files_a ^ files_b)
    diffs += [rel for rel in sorted(files_a & files_b) if not filecmp.cmp(a / rel, b / rel, shallow=False)]
    return diffs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify out/ matches a fresh build; write nothing")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "out"
        build(fresh)
        if args.check:
            if not OUT_DIR.is_dir():
                print("out/ is missing; run python3 tools/build_site.py", file=sys.stderr)
                return 1
            diffs = same_tree(fresh, OUT_DIR)
            for rel in diffs:
                print(f"stale: out/{rel}", file=sys.stderr)
            print("out/ is up to date" if not diffs else f"{len(diffs)} file(s) differ from a fresh build")
            return 1 if diffs else 0
        if OUT_DIR.exists():
            shutil.rmtree(OUT_DIR)
        shutil.copytree(fresh, OUT_DIR)
    print(f"wrote {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
