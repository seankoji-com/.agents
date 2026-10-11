"""Acceptance tests for out/: recompute every rule from data/ without using the
generator, then check the published files against the output contract."""
from __future__ import annotations

import filecmp
import json
import math
import re
import unittest
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"


def haversine(lat1, lon1, lat2, lon2, radius=6371.0):
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def expected():
    stations = json.loads((ROOT / "data" / "stations.json").read_text())
    prices = json.loads((ROOT / "data" / "prices.json").read_text())
    centre = stations["centre"]
    e10 = [r for r in prices["records"] if r["fuel"] == "E10"]
    # Order by instant; on an equal instant the record later in the file wins.
    e10 = [dict(r, _seq=i) for i, r in enumerate(e10)]
    when = lambda r: (datetime.fromisoformat(r["recorded_at"]), r["_seq"])  # noqa: E731
    in_range, out_of_range = {}, set()
    for s in stations["stations"]:
        d = haversine(centre["lat"], centre["lon"], s["lat"], s["lon"])
        if d <= 10.0:
            history = sorted((r for r in e10 if r["station_id"] == s["id"]), key=when)
            in_range[s["id"]] = dict(s, distance=d, history=history, listed=history[-1]["price_cpl"])
        else:
            out_of_range.add(s["id"])
    best = min(in_range.values(), key=lambda s: s["listed"])["id"]
    overall = []
    for day in sorted({r["recorded_at"][:10] for r in e10}):
        latest = [max((r for r in s["history"] if r["recorded_at"][:10] <= day), key=when)["price_cpl"]
                  for s in in_range.values() if any(r["recorded_at"][:10] <= day for r in s["history"])]
        overall.append((day, sum(latest) / len(latest)))
    return {"in_range": in_range, "out_of_range": out_of_range, "best": best, "overall": overall}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.stylesheets, self.recommended, self.items = [], [], [], {}
        self._item, self._capture = None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and "src" in attrs:
            self.scripts.append(attrs["src"])
        if tag == "link" and "stylesheet" in (attrs.get("rel") or "").split():
            self.stylesheets.append(attrs.get("href"))
        if "data-recommended-station" in attrs:
            self.recommended.append(attrs["data-recommended-station"])
        if tag == "li" and "data-station-id" in attrs:
            self._item = attrs["data-station-id"]
            self.items[self._item] = {"price": "", "dist": "", "rows": 0, "spark": False}
        if self._item:
            cls = (attrs.get("class") or "").split()
            if "st-price" in cls:
                self._capture = "price"
            elif "st-dist" in cls:
                self._capture = "dist"
            elif "spark" in cls:
                self.items[self._item]["spark"] = True
            if tag == "tr":
                self.items[self._item]["rows"] += 1

    def handle_endtag(self, tag):
        if tag == "span":
            self._capture = None
        if tag == "li":
            self._item = None

    def handle_data(self, data):
        if self._item and self._capture:
            self.items[self._item][self._capture] += data


class OutputContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exp = expected()
        cls.data = json.loads((OUT / "data.json").read_text(encoding="utf-8"))
        cls.html = (OUT / "index.html").read_text(encoding="utf-8")
        cls.page = PageParser()
        cls.page.feed(cls.html)

    def test_fixture_has_the_cases_the_rules_cover(self):
        self.assertTrue(self.exp["out_of_range"], "fixture should include out-of-range stations")
        self.assertEqual(len(self.exp["in_range"]), 21)

    def test_stations_are_exactly_the_in_range_set(self):
        self.assertEqual({s["id"] for s in self.data["stations"]}, set(self.exp["in_range"]))
        self.assertEqual(len(self.data["stations"]), len(self.exp["in_range"]))

    def test_station_fields_distance_price_and_full_history(self):
        for s in self.data["stations"]:
            want = self.exp["in_range"][s["id"]]
            self.assertEqual(set(s), {"id", "name", "lat", "lon", "distance_km", "listed_price_cpl", "history"})
            self.assertEqual((s["name"], s["lat"], s["lon"]), (want["name"], want["lat"], want["lon"]))
            self.assertAlmostEqual(s["distance_km"], want["distance"], places=9)
            self.assertLessEqual(s["distance_km"], 10.0)
            self.assertEqual(s["listed_price_cpl"], want["listed"])
            self.assertEqual(s["history"], [{"recorded_at": r["recorded_at"], "price_cpl": r["price_cpl"]}
                                            for r in want["history"]])

    def test_recommendation_is_lowest_listed_price(self):
        self.assertEqual(self.data["recommendation"], {"station_id": self.exp["best"]})
        lowest = min(s["listed_price_cpl"] for s in self.data["stations"])
        best = next(s for s in self.data["stations"] if s["id"] == self.exp["best"])
        self.assertEqual(best["listed_price_cpl"], lowest)

    def test_overall_history(self):
        got = [(p["date"], p["mean_price_cpl"]) for p in self.data["overall_history"]]
        self.assertEqual([d for d, _ in got], [d for d, _ in self.exp["overall"]])
        for (_, mean), (_, want) in zip(got, self.exp["overall"]):
            self.assertAlmostEqual(mean, want, places=9)
        for p in self.data["overall_history"]:
            self.assertEqual(set(p), {"date", "mean_price_cpl"})

    def test_data_js_matches_data_json(self):
        text = (OUT / "data.js").read_text(encoding="utf-8")
        match = re.fullmatch(r"window\.E10_DATA = (.*);\n", text, re.S)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), self.data)

    def test_leaflet_copied_unchanged(self):
        src, dst = ROOT / "vendor" / "leaflet", OUT / "vendor" / "leaflet"
        src_files = sorted(p.relative_to(src) for p in src.rglob("*") if p.is_file())
        dst_files = sorted(p.relative_to(dst) for p in dst.rglob("*") if p.is_file())
        self.assertEqual(src_files, dst_files)
        for rel in src_files:
            self.assertTrue(filecmp.cmp(src / rel, dst / rel, shallow=False), rel)

    def test_only_local_scripts_and_stylesheets(self):
        self.assertIn("vendor/leaflet/leaflet.css", self.page.stylesheets)
        self.assertIn("vendor/leaflet/leaflet.js", self.page.scripts)
        for ref in self.page.scripts + self.page.stylesheets:
            self.assertNotRegex(ref, r"^(?:[a-z]+:|//|/)", ref)
            self.assertTrue((OUT / ref).is_file(), ref)
        self.assertNotRegex(self.html, r"@import")

    def test_osm_tiles_and_attribution(self):
        self.assertIn("https://tile.openstreetmap.org/{z}/{x}/{y}.png", self.html)
        self.assertIn("© OpenStreetMap contributors", self.html)

    def test_exactly_one_recommended_marker(self):
        self.assertEqual(self.page.recommended, [self.exp["best"]])
        self.assertEqual(self.html.count("data-recommended-station"), 1)

    def test_every_in_range_id_is_on_the_page(self):
        loaded = self.html + "".join((OUT / src).read_text(encoding="utf-8")
                                     for src in self.page.scripts if (OUT / src).is_file())
        for sid in self.exp["in_range"]:
            self.assertIn(sid, self.html)
            self.assertIn(sid, loaded)

    def test_list_shows_price_distance_and_history(self):
        self.assertEqual(set(self.page.items), set(self.exp["in_range"]))
        for sid, item in self.page.items.items():
            want = self.exp["in_range"][sid]
            self.assertEqual(item["price"].strip(), f"{want['listed']:.1f} c/L")
            self.assertEqual(item["dist"].strip(), f"{want['distance']:.2f} km")
            self.assertTrue(item["spark"], sid)
            self.assertEqual(item["rows"], len(want["history"]) + 1, sid)  # header row + one per record

    def test_overall_history_is_on_the_page(self):
        for day, mean in self.exp["overall"]:
            self.assertIn(f"{mean:.2f}", self.html, day)

    def test_no_out_of_range_id_anywhere_in_out(self):
        for path in OUT.rglob("*"):
            if path.is_file():
                blob = path.read_bytes()
                for sid in self.exp["out_of_range"]:
                    self.assertNotIn(sid.encode(), blob, f"{sid} in {path.relative_to(ROOT)}")


if __name__ == "__main__":
    unittest.main()
