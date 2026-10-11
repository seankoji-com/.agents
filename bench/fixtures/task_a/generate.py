#!/usr/bin/env python3
"""Regenerate the frozen Task A dataset (stations and fuel prices near Greenwich, NSW).

The output is committed; this script documents how it was made and must reproduce it
byte for byte. Station names and prices are fictional. Positions are placed by bearing
and great-circle distance from the centre so the radius cases are exact by design:
20 stations well inside 10 km, one 35 m inside the boundary, four outside it.

Usage: python3 bench/fixtures/task_a/generate.py [--check]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / 'workspace' / 'data'
CENTRE = (-33.833, 151.183)
EARTH_RADIUS_KM = 6371.0
DAYS = [f'2026-09-{day:02d}' for day in range(1, 15)]
SEED = 20261011

# (id, name, bearing degrees, distance km). Names are fictional.
STATIONS = [
    ('STN-0001', 'Greenwich Point Fuel', 140, 0.6),
    ('STN-0002', 'River Road Service Centre', 300, 1.4),
    ('STN-0003', 'Longueville Express', 95, 2.1),
    ('STN-0004', 'Pacific Highway Fuels', 20, 2.7),
    ('STN-0005', 'Northbridge Corner Store', 70, 3.2),
    ('STN-0006', 'Lane Cove West Fuel Stop', 280, 3.6),
    ('STN-0007', 'Artarmon Junction Fuels', 10, 6.4),
    ('STN-0008', 'Cammeray Bridge Service', 110, 4.1),
    ('STN-0009', 'Hunters Hill Motor Fuel', 240, 4.4),
    ('STN-0010', 'Gladesville Roundabout Fuel', 265, 5.0),
    ('STN-0011', 'Neutral Bay Fuel Co', 150, 4.8),
    ('STN-0012', 'Chatswood Chase Service', 15, 5.6),
    ('STN-0013', 'Balmain Wharf Fuel', 195, 5.9),
    ('STN-0014', 'Drummoyne Bay Petroleum', 225, 6.8),
    ('STN-0015', 'Pyrmont Bridge Road Fuel', 170, 7.2),
    ('STN-0016', 'North Ryde Link Fuel', 305, 7.7),
    ('STN-0017', 'Willoughby Heights Fuel', 45, 6.1),
    ('STN-0018', 'Mosman Spit Junction Fuel', 100, 8.3),
    ('STN-0019', 'Putney Ferry Service', 255, 8.8),
    ('STN-0020', 'Roseville Ridge Fuel', 25, 9.4),
    ('STN-0021', 'Boundary Road Fuel', 330, 9.965),
    ('STN-0901', 'Marsfield Outer Fuel', 300, 10.6),
    ('STN-0902', 'Strathfield Plaza Fuel', 230, 12.1),
    ('STN-0903', 'Manly Corso Fuel', 75, 14.8),
    ('STN-0904', 'Hornsby Gateway Fuel', 355, 21.5),
]

# Final E10 prices (cents per litre) that decide the answer. Everything else is noise.
FINAL = {'STN-0007': 179.9, 'STN-0021': 183.9, 'STN-0901': 178.9, 'STN-0902': 174.9}
# STN-0003 was briefly the cheapest station, but its latest E10 price is not.
EARLY_DIP = ('STN-0003', '2026-09-05T08:10:00+10:00', 176.9)
# Cheaper U91 records exist, but the task is about E10.
U91 = {'STN-0012': 171.9, 'STN-0005': 173.4}


def destination(bearing_deg: float, distance_km: float) -> tuple[float, float]:
    lat1, lon1 = map(math.radians, CENTRE)
    bearing = math.radians(bearing_deg)
    delta = distance_km / EARTH_RADIUS_KM
    lat2 = math.asin(math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(bearing))
    lon2 = lon1 + math.atan2(math.sin(bearing) * math.sin(delta) * math.cos(lat1),
                             math.cos(delta) - math.sin(lat1) * math.sin(lat2))
    return round(math.degrees(lat2), 6), round(math.degrees(lon2), 6)


def stamp(day: str, rng: random.Random) -> str:
    return f'{day}T{rng.randint(6, 21):02d}:{rng.choice((0, 10, 20, 30, 40, 50)):02d}:00+10:00'


def build() -> tuple[list, list]:
    rng = random.Random(SEED)
    stations = []
    for sid, name, bearing, distance in STATIONS:
        lat, lon = destination(bearing, distance)
        stations.append({'id': sid, 'name': name, 'brand': rng.choice(['Independent', 'Metro', 'Coastal', 'Harbour']),
                         'address': f'{rng.randint(1, 400)} {name.split()[0]} Street', 'lat': lat, 'lon': lon})
    prices = []
    for sid, *_ in STATIONS:
        price = rng.choice([x / 10 for x in range(1869, 2100, 10)])
        prices.append({'station_id': sid, 'fuel': 'E10', 'price_cpl': round(price, 1),
                       'recorded_at': f'{DAYS[0]}T06:00:00+10:00'})
        for day in DAYS[1:-1]:
            for _ in range(rng.choice((0, 0, 1, 1, 2))):
                price = min(209.9, max(184.9, price + rng.choice((-3.0, -2.0, -1.0, 1.0, 2.0, 4.0))))
                prices.append({'station_id': sid, 'fuel': 'E10', 'price_cpl': round(price, 1),
                               'recorded_at': stamp(day, rng)})
        final = FINAL.get(sid, round(max(price, 185.9), 1))
        prices.append({'station_id': sid, 'fuel': 'E10', 'price_cpl': final,
                       'recorded_at': f'{DAYS[-1]}T{rng.randint(7, 20):02d}:15:00+10:00'})
        if sid in U91:
            prices.append({'station_id': sid, 'fuel': 'U91', 'price_cpl': U91[sid],
                           'recorded_at': f'{DAYS[-1]}T22:30:00+10:00'})
    sid, at, value = EARLY_DIP
    prices.append({'station_id': sid, 'fuel': 'E10', 'price_cpl': value, 'recorded_at': at})
    rng.shuffle(prices)  # file order is not chronological; "latest" means by timestamp
    return stations, prices


def render() -> dict:
    stations, prices = build()
    return {
        'stations.json': json.dumps({'centre': {'lat': CENTRE[0], 'lon': CENTRE[1]}, 'stations': stations},
                                    indent=2) + '\n',
        'prices.json': json.dumps({'unit': 'cents per litre', 'records': prices}, indent=2) + '\n',
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true', help='fail if the committed files differ')
    args = parser.parse_args(argv)
    stale = []
    for name, text in render().items():
        path = DATA / name
        if args.check:
            if not path.is_file() or path.read_text() != text:
                stale.append(name)
        else:
            path.write_text(text)
    if stale:
        print('stale: ' + ', '.join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
