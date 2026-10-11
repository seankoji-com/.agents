"""Edge cases for the generator's rules, on small synthetic inputs."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location("build_site", Path(__file__).resolve().parent.parent / "tools" / "build_site.py")
build_site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_site)

CENTRE = {"lat": -33.833, "lon": 151.183}


def station(sid, lat, lon=151.183):
    return {"id": sid, "name": sid, "brand": "B", "address": "A", "lat": lat, "lon": lon}


def rec(sid, price, at, fuel="E10"):
    return {"station_id": sid, "fuel": fuel, "price_cpl": price, "recorded_at": at}


def model(stations, records):
    return build_site.build_model({"centre": CENTRE, "stations": stations}, {"records": records})


class BuildModel(unittest.TestCase):
    def test_range_limit_is_inclusive(self):
        edge = station("EDGE", -33.92)
        distance = build_site.haversine_km(CENTRE["lat"], CENTRE["lon"], edge["lat"], edge["lon"])
        records = [rec("EDGE", 180.0, "2026-09-01T06:00:00+10:00")]
        with mock.patch.object(build_site, "RANGE_KM", distance):
            self.assertEqual([s["station"]["id"] for s in model([edge], records)["in_range"]], ["EDGE"])
        with mock.patch.object(build_site, "RANGE_KM", distance - 1e-9):
            with self.assertRaises(SystemExit):
                model([edge], records)

    def test_listed_price_is_latest_e10_regardless_of_file_order_and_other_fuels(self):
        records = [
            rec("A", 190.0, "2026-09-03T08:00:00+10:00"),
            rec("A", 150.0, "2026-09-04T08:00:00+10:00", fuel="U91"),
            rec("A", 200.0, "2026-09-01T08:00:00+10:00"),
            rec("A", 185.0, "2026-09-02T23:00:00+10:00"),
        ]
        m = model([station("A", -33.84)], records)
        self.assertEqual(m["best"]["listed"]["price_cpl"], 190.0)
        self.assertEqual([r["price_cpl"] for r in m["in_range"][0]["records"]], [200.0, 185.0, 190.0])

    def test_latest_compares_instants_not_strings(self):
        records = [rec("A", 190.0, "2026-09-02T09:00:00+10:00"), rec("A", 170.0, "2026-09-02T08:30:00+09:00")]
        m = model([station("A", -33.84)], records)
        self.assertEqual(m["best"]["listed"]["price_cpl"], 170.0)  # 08:30+09:00 is 09:30+10:00

    def test_recommendation_excludes_out_of_range_and_breaks_ties_by_distance(self):
        stations = [station("FAR", -34.5), station("NEAR", -33.84), station("MID", -33.86)]
        records = [rec("FAR", 150.0, "2026-09-01T06:00:00+10:00"),
                   rec("MID", 180.0, "2026-09-01T06:00:00+10:00"),
                   rec("NEAR", 180.0, "2026-09-01T07:00:00+10:00")]
        m = model(stations, records)
        self.assertEqual(m["best"]["station"]["id"], "NEAR")
        self.assertNotIn("FAR", [s["id"] for s in build_site.public_data(m)["stations"]])

    def test_overall_history_carries_prices_forward_and_skips_stations_without_records(self):
        stations = [station("A", -33.84), station("B", -33.85)]
        records = [rec("A", 200.0, "2026-09-01T06:00:00+10:00"),
                   rec("B", 180.0, "2026-09-02T18:00:00+10:00"),
                   rec("A", 190.0, "2026-09-02T07:00:00+10:00"),
                   rec("A", 210.0, "2026-09-04T07:00:00+10:00")]
        overall = build_site.public_data(model(stations, records))["overall_history"]
        self.assertEqual(overall, [{"date": "2026-09-01", "mean_price_cpl": 200.0},
                                   {"date": "2026-09-02", "mean_price_cpl": 185.0},
                                   {"date": "2026-09-04", "mean_price_cpl": 195.0}])

    def test_overall_history_uses_the_date_as_written(self):
        records = [rec("A", 200.0, "2026-09-01T23:30:00+10:00"), rec("A", 100.0, "2026-09-02T00:30:00+12:00")]
        overall = build_site.public_data(model([station("A", -33.84)], records))["overall_history"]
        self.assertEqual([p["date"] for p in overall], ["2026-09-01", "2026-09-02"])

    def test_in_range_station_without_e10_is_listed_but_not_recommended(self):
        stations = [station("A", -33.84), station("B", -33.85)]
        m = model(stations, [rec("A", 200.0, "2026-09-01T06:00:00+10:00"),
                             rec("B", 150.0, "2026-09-01T06:00:00+10:00", fuel="U91")])
        data = build_site.public_data(m)
        self.assertEqual(data["recommendation"], {"station_id": "A"})
        self.assertEqual([(s["id"], s["listed_price_cpl"], s["history"]) for s in data["stations"]][1], ("B", None, []))
        page = build_site.render_page(m)
        self.assertIn('id="station-B"', page)
        self.assertIn("average listed price of 1 station in range", page)
        # The map script draws a pin for every station in data.js, priced or not.
        self.assertNotRegex(build_site.SCRIPT, r"listed_price_cpl === null\)\s*\{\s*return")
        self.assertIn('"No price"', build_site.SCRIPT)


class Formatting(unittest.TestCase):
    def test_tick_labels_keep_the_step_precision(self):
        self.assertEqual(build_site.fmt_tick(192.5, 2.5), "192.5")
        self.assertEqual(build_site.fmt_tick(200.0, 2.5), "200.0")
        self.assertEqual(build_site.fmt_tick(200.0, 0.5), "200.0")
        self.assertEqual(build_site.fmt_tick(200.25, 0.25), "200.25")
        self.assertEqual(build_site.fmt_tick(200.0, 5), "200")

    def test_flat_series_still_gets_an_axis(self):
        ticks = build_site.nice_ticks(200.0, 200.0)
        self.assertGreater(ticks[-1], ticks[0])


if __name__ == "__main__":
    unittest.main()
