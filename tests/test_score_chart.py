"""Tests for skills/review/scripts/render_score_chart.py."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/review/scripts/render_score_chart.py"
EXAMPLE = ROOT / "skills/review/examples/score-ledger.json"

SPEC = importlib.util.spec_from_file_location("render_score_chart", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def load_example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class ScoreChartTests(unittest.TestCase):
    def test_example_renders_all_required_elements(self) -> None:
        data = load_example()
        html = MOD.render_html(data)
        self.assertIn("<!doctype html>", html.lower())
        self.assertIn("Checkout Flow Hillclimb", html)
        self.assertIn("NO SCORE · NOT 0", html)
        self.assertIn("Recovery · 9.0 → 8.5", html)
        self.assertIn("9.0 orig", html)
        self.assertIn("8.5 rev", html)
        self.assertIn("min 8.4", html)
        self.assertIn("min 8.7", html)
        self.assertIn("gate n/a · t/o", html)
        self.assertIn("sc-retry-ring", html)
        self.assertIn("Rubric v1 · historical", html)
        self.assertIn("sc-hist-fill", html)
        self.assertNotIn("sc-hatch-hist", html)
        self.assertIn("sc-dim-gain", html)
        self.assertIn("sc-dim-loss", html)
        # Sol Clarity dropped 9 -> 8 between P1 and P2; Opus Control rose 6 -> 8 between B0 and R1
        self.assertIn('"delta": -1.0', html)
        self.assertIn('"delta": 2.0', html)
        self.assertIn("Score table (6 rounds)", html)
        # No outer page background or vh/height:100% on html/body
        self.assertNotIn("100vh", html)
        self.assertIn("html, body {\n  margin: 0;\n  padding: 0;\n  background: transparent;", html)

    def test_single_reviewer_without_dimensions_or_recovery(self) -> None:
        ledger = {
            "version": 1,
            "run": {
                "title": "Parser Refactor Loop",
                "id": "rl-01",
                "skill": "review-loop",
                "status": "passed",
                "scale": {"min": 0, "max": 10, "precision": 1},
            },
            "reviewers": [{"id": "sol", "label": "Sol 6.2", "role": "Primary"}],
            "eras": [{"id": "v1", "label": "Contract", "target": 9.0, "historical": False}],
            "rounds": [
                {
                    "id": "R0",
                    "label": "Baseline",
                    "era": "v1",
                    "phase": "review",
                    "expected_reviewers": ["sol"],
                    "status": "scored",
                    "scores": [
                        {
                            "reviewer": "sol",
                            "score": 2.5,
                            "bullets": [
                                "Unhandled EOF panics on truncated input.",
                                "Missing unit tests for nested quotes.",
                                "Error messages omit byte offsets.",
                            ],
                        }
                    ],
                },
                {
                    "id": "R1",
                    "label": "Fix",
                    "era": "v1",
                    "phase": "review",
                    "expected_reviewers": ["sol"],
                    "status": "scored",
                    "scores": [
                        {
                            "reviewer": "sol",
                            "score": 9.2,
                            "bullets": [
                                "EOF handling returns typed parse errors cleanly.",
                                "Added regression tests for nested quotes and escapes.",
                                "All errors now include line and byte offset.",
                            ],
                        }
                    ],
                },
            ],
        }
        html = MOD.render_html(ledger)
        self.assertIn("Parser Refactor Loop", html)
        # Dynamic y-axis must cover low score 2.5 (not hardcoded to 6-10)
        self.assertIn("axis 1–10", html)
        self.assertNotIn('<line class="sc-recovery-line"', html)
        self.assertIn("9.0 target", html)

    def test_incomplete_panel_never_sets_gate_score(self) -> None:
        data = load_example()
        model = MOD.validate(data)
        p1 = next(r for r in model["rounds"] if r["id"] == "P1")
        self.assertEqual(p1["status"], "incomplete")
        self.assertIsNone(p1["gate_score"])
        self.assertEqual(p1["missing_reviewers"], ["hydrogen"])

        # Even if only 1 of 3 panel judges scored, gate must stay None
        data2 = copy.deepcopy(data)
        data2["rounds"][4]["status"] = "scored"
        data2["rounds"][4]["scores"] = [data2["rounds"][4]["scores"][0]]
        model2 = MOD.validate(data2)
        p1_single = next(r for r in model2["rounds"] if r["id"] == "P1")
        self.assertEqual(p1_single["status"], "incomplete")
        self.assertIsNone(p1_single["gate_score"])

    def test_non_comparable_era_breaks_polylines_while_comparable_keeps_them(self) -> None:
        base = {
            "version": 1,
            "run": {"title": "Comparability Test", "id": "cmp-1", "skill": "review-loop", "status": "in-progress"},
            "reviewers": [{"id": "opus", "label": "Opus 5.5"}],
            "eras": [
                {"id": "e1", "label": "Run 1", "target": 9.0, "historical": True, "comparable_to_prev": False},
                {
                    "id": "e2",
                    "label": "Retry 1",
                    "target": 9.0,
                    "historical": False,
                    "comparable_to_prev": False,
                    "recovery": {
                        "kind": "automatic",
                        "label": "Recovery",
                        "trigger": "Stagnation",
                        "diagnosis": "Broken fixture",
                        "fix": "Fixed fixture",
                    },
                },
            ],
            "rounds": [
                {
                    "id": "R0",
                    "label": "Base",
                    "era": "e1",
                    "phase": "primary",
                    "expected_reviewers": ["opus"],
                    "status": "scored",
                    "scores": [{"reviewer": "opus", "score": 7.0, "bullets": ["a", "b", "c"]}],
                },
                {
                    "id": "R1",
                    "label": "After",
                    "era": "e2",
                    "phase": "primary",
                    "expected_reviewers": ["opus"],
                    "status": "scored",
                    "scores": [{"reviewer": "opus", "score": 8.5, "bullets": ["a", "b", "c"]}],
                },
            ],
        }
        html_broken = MOD.render_html(base)
        self.assertNotIn('<polyline class="sc-series-line"', html_broken)

        comparable = copy.deepcopy(base)
        comparable["eras"][1]["comparable_to_prev"] = True
        comparable["eras"][0]["historical"] = False
        html_connected = MOD.render_html(comparable)
        self.assertIn('<polyline class="sc-series-line"', html_connected)

    def test_validation_rejects_invalid_ledgers(self) -> None:
        # Fewer than 3 bullets
        bad_bullets = load_example()
        bad_bullets["rounds"][0]["scores"][0]["bullets"] = ["only one", "only two"]
        with self.assertRaisesRegex(ValueError, "3 to 5"):
            MOD.validate(bad_bullets)

        # More than 5 bullets
        too_many = load_example()
        too_many["rounds"][0]["scores"][0]["bullets"] = ["1", "2", "3", "4", "5", "6"]
        with self.assertRaisesRegex(ValueError, "3 to 5"):
            MOD.validate(too_many)

        # Retried without retry_note
        bad_retry = load_example()
        bad_retry["rounds"][1]["scores"][0]["retry_note"] = ""
        with self.assertRaisesRegex(ValueError, "retry_note"):
            MOD.validate(bad_retry)

        # Unscored round with numeric score
        bad_unscored = load_example()
        bad_unscored["rounds"][2]["scores"] = [
            {"reviewer": "opus", "score": 5.0, "bullets": ["a", "b", "c"]}
        ]
        with self.assertRaisesRegex(ValueError, "unscored"):
            MOD.validate(bad_unscored)

    def test_html_and_script_escaping(self) -> None:
        data = load_example()
        data["run"]["title"] = "XSS </script><img src=x onerror=alert(1)>"
        data["rounds"][0]["scores"][0]["bullets"][0] = "Payload </script><b>bold</b>"
        html = MOD.render_html(data)
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("Payload </script>", html)
        self.assertIn(r"<\/script>", html)

    def test_relocated_cli_from_foreign_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            copied_script = tmp_path / "relocated" / "render_score_chart.py"
            copied_script.parent.mkdir(parents=True)
            shutil.copy2(SCRIPT, copied_script)

            foreign_cwd = tmp_path / "foreign-cwd"
            foreign_cwd.mkdir()
            ledger_copy = tmp_path / "input" / "ledger.json"
            ledger_copy.parent.mkdir()
            shutil.copy2(EXAMPLE, ledger_copy)
            output_html = tmp_path / "out" / "chart.html"

            proc = subprocess.run(
                [sys.executable, "-B", str(copied_script), str(ledger_copy), "--output", str(output_html)],
                cwd=foreign_cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(output_html.is_file())
            rendered = output_html.read_text(encoding="utf-8")
            self.assertIn("Checkout Flow Hillclimb", rendered)
            self.assertIn("NO SCORE · NOT 0", rendered)


if __name__ == "__main__":
    unittest.main()
