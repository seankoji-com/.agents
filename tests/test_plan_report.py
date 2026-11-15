"""Synthetic plan reporting arithmetic and rejection cases; no host/model calls."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("plan_ledger", ROOT / "skills/plan-report/scripts/ledger.py")
ledger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ledger)


def fixture():
    return json.loads((ROOT / "skills/plan-report/examples/long-run.json").read_text())


class Ledger(unittest.TestCase):
    def test_original_approved_allocations_calibrate_exactly(self):
        data = ledger.validate(fixture())
        result = ledger.calibration(data)
        build = result["groups"][("synthetic-build", "Builder A", "high", "build")]
        review = result["groups"][("synthetic-review", "Reviewer B", "high", "review")]
        self.assertEqual(build, dict(estimated_minutes=420, actual_minutes=630, ratio=1.5))
        self.assertEqual(review, dict(estimated_minutes=240, actual_minutes=270, ratio=1.125))
        self.assertEqual(result["rounds"][6], dict(task="T07", planned=1, actual=2))
        changed = next(x for x in result["comparisons"] if x["task"] == "T04" and x["kind"] == "build")
        self.assertEqual(changed, dict(task="T04", kind="build", comparable=False,
                                     estimated_minutes=60, actual_minutes=90))
        self.assertNotIn(("synthetic-build", "Builder C", "high", "build"), result["groups"])
        self.assertEqual(result["costs"][("synthetic-build", "Builder A")]["tokens"]["known"], 24000)
        self.assertAlmostEqual(result["costs"][("synthetic-review", "Reviewer B")]["usd"]["known"], 0.48)
        self.assertTrue(result["costs"][("synthetic-review", "Reviewer B")]["usd"]["estimated"])
        self.assertGreater(result["costs"][("synthetic-review", "Reviewer B")]["usd"]["missing"], 0)

    def test_effort_change_is_not_comparable_and_round_splits_count_once(self):
        data = fixture()
        task = data["tasks"][0]
        task["segments"][0]["effort"] = "low"
        split = copy.deepcopy(task["segments"][1])
        split.update(id="split", start="2026-10-03T00:00:00Z", end="2026-10-03T00:05:00Z")
        task["segments"].append(split)
        result = ledger.calibration(ledger.validate(data))
        self.assertFalse(next(x for x in result["comparisons"] if x["task"] == "T01" and x["kind"] == "build")["comparable"])
        self.assertNotIn(("synthetic-build", "Builder A", "low", "build"), result["groups"])
        self.assertEqual(result["rounds"][0]["actual"], 1)

    def test_rebaseline_preserves_original_and_unapproved_has_no_ratios(self):
        data = fixture()
        original = copy.deepcopy(data["tasks"][8]["baseline"])
        ledger.validate(data)
        self.assertEqual(data["tasks"][8]["baseline"], original)
        self.assertEqual(ledger.baseline_end(original).isoformat(), "2026-10-03T13:30:00+00:00")
        data["approval"] = None
        data["rebaselines"] = []
        self.assertEqual(ledger.calibration(ledger.validate(data))["groups"], {})

    def test_unknown_cost_and_task_total_attribution(self):
        data = fixture()
        task = data["tasks"][3]
        for segment in task["segments"]:
            segment["cost"] = {}
        task["cost"] = {"usd": dict(value=2, source="synthetic task receipt", basis="reported")}
        result = ledger.cost_totals(ledger.validate(data))
        self.assertEqual(result[("unattributed", "task total")]["usd"]["known"], 2)
        unknown = result[("synthetic-build", "Builder C")]["tokens"]
        self.assertEqual(unknown["sources"], [])
        self.assertEqual(unknown["missing"], 1)

    def test_invalid_dependency_reversed_segment_and_approved_baseline(self):
        for mutation, error in [
            (lambda d: d["tasks"][0]["dependencies"].append("missing"), "unknown dependency id: missing"),
            (lambda d: d["tasks"][0]["segments"][0].update(end="2026-10-02T21:00:00Z"), "ends before it starts"),
            (lambda d: d["tasks"][0].pop("baseline"), "missing approved baseline"),
            (lambda d: d["tasks"][0]["dependencies"].append("T02"), "dependency cycle"),
            (lambda d: d["tasks"][0]["segments"][0]["cost"].update(usd={"value": 3}), "source"),
            (lambda d: d["tasks"][0].update(cost={"usd":dict(value=1,source="synthetic",basis="reported")}), "both task and segment"),
            (lambda d: d["rebaselines"][0].update(approver=""), "approver"),
        ]:
            with self.subTest(error=error):
                data = fixture()
                mutation(data)
                with self.assertRaisesRegex(ValueError, error):
                    ledger.validate(data)

    def test_dst_display_and_elapsed_time_use_real_instants(self):
        before = ledger.display_time("2026-10-04T01:30:00+10:00")
        after = ledger.display_time("2026-10-04T03:30:00+11:00")
        self.assertEqual(before, "04 Oct 2026 01:30 AEST (UTC+1000)")
        self.assertEqual(after, "04 Oct 2026 03:30 AEDT (UTC+1100)")
        self.assertEqual(ledger.segment_minutes(dict(start="2026-10-04T01:30:00+10:00", end="2026-10-04T03:30:00+11:00"),
                                               "2026-10-04T05:00:00+11:00"), 60)
        self.assertEqual(ledger.segment_minutes(dict(start="2026-04-05T01:30:00+11:00", end="2026-04-05T03:30:00+10:00"),
                                               "2026-04-05T05:00:00+10:00"), 180)

    def test_scoped_events_and_remaining_critical_path(self):
        data = ledger.validate(fixture())
        event = data["events"][1]
        self.assertTrue(ledger.event_affects(event, data["tasks"][9]))
        self.assertFalse(ledger.event_affects(event, data["tasks"][8]))
        self.assertEqual(ledger.critical_path(data), ["T09"])


if __name__ == "__main__":
    unittest.main()
