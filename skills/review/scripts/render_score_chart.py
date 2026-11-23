#!/usr/bin/env python3
"""Render a score-based iterative review ledger to self-contained inline HTML; Python 3.10+ stdlib."""
from __future__ import annotations

import argparse
from html import escape
import json
import math
from pathlib import Path
import sys

RUN_STATUSES = {
    "in-progress",
    "passed",
    "passed-revised",
    "goal-not-met",
    "stopped",
    "blocked",
}
ROUND_STATUSES = {"scored", "unscored", "incomplete"}
PHASES = {"primary", "panel", "review"}
RECOVERY_KINDS = {"automatic", "continuation", "rebaseline"}
CHART_VARS = (
    "--chart-1",
    "--chart-2",
    "--chart-3",
    "--chart-4",
    "--chart-5",
    "--chart-6",
)
CHART_FALLBACKS = (
    "#5b8def",
    "#2dd4bf",
    "#f5b942",
    "#c084fc",
    "#fb7185",
    "#38bdf8",
)
SHAPES = ("circle", "square", "diamond", "triangle", "hex", "ring")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def nonempty_str(value: object, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be nonempty text")
    return value.strip()


def finite_num(value: object, label: str, *, integer: bool = False) -> int | float:
    if integer:
        require(type(value) is int, f"{label} must be an integer")
        return value  # type: ignore[return-value]
    require(type(value) in (int, float) and math.isfinite(value), f"{label} must be a finite number")
    return value  # type: ignore[return-value]


def fmt_score(value: float, precision: int) -> str:
    return f"{value:.{precision}f}"


def validate(data: object) -> dict:
    require(isinstance(data, dict), "ledger must be a JSON object")
    require(type(data.get("version")) is int and data["version"] == 1, "ledger version must be 1")

    run = data.get("run")
    require(isinstance(run, dict), "run must be an object")
    title = nonempty_str(run.get("title"), "run.title")
    run_id = nonempty_str(run.get("id"), "run.id")
    skill = nonempty_str(run.get("skill", "review-loop"), "run.skill")
    status = nonempty_str(run.get("status", "in-progress"), "run.status")
    require(status in RUN_STATUSES, f"run.status must be one of {sorted(RUN_STATUSES)}")

    scale = run.get("scale", {"min": 1, "max": 10, "precision": 1})
    require(isinstance(scale, dict), "run.scale must be an object")
    s_min = float(finite_num(scale.get("min", 1), "run.scale.min"))
    s_max = float(finite_num(scale.get("max", 10), "run.scale.max"))
    require(s_max > s_min, "run.scale.max must exceed run.scale.min")
    precision = int(finite_num(scale.get("precision", 1), "run.scale.precision", integer=True))
    require(0 <= precision <= 3, "run.scale.precision must be between 0 and 3")

    reviewers_raw = data.get("reviewers")
    require(isinstance(reviewers_raw, list) and len(reviewers_raw) >= 1, "reviewers must be a nonempty list")
    reviewers = []
    reviewer_ids: dict[str, dict] = {}
    for idx, rev in enumerate(reviewers_raw):
        require(isinstance(rev, dict), f"reviewers[{idx}] must be an object")
        rid = nonempty_str(rev.get("id"), f"reviewers[{idx}].id")
        require(rid not in reviewer_ids, f"duplicate reviewer id: {rid}")
        rlabel = nonempty_str(rev.get("label"), f"reviewers[{idx}].label")
        role = rev.get("role", "")
        if role is not None:
            require(isinstance(role, str), f"reviewers[{idx}].role must be text")
        item = {
            "id": rid,
            "label": rlabel,
            "role": (role or "").strip(),
            "color_var": CHART_VARS[idx % len(CHART_VARS)],
            "color_fallback": CHART_FALLBACKS[idx % len(CHART_FALLBACKS)],
            "shape": SHAPES[idx % len(SHAPES)],
            "index": idx,
        }
        reviewers.append(item)
        reviewer_ids[rid] = item

    eras_raw = data.get("eras")
    require(isinstance(eras_raw, list) and len(eras_raw) >= 1, "eras must be a nonempty list")
    eras = []
    era_ids: dict[str, dict] = {}
    for idx, era in enumerate(eras_raw):
        require(isinstance(era, dict), f"eras[{idx}] must be an object")
        eid = nonempty_str(era.get("id"), f"eras[{idx}].id")
        require(eid not in era_ids, f"duplicate era id: {eid}")
        elabel = nonempty_str(era.get("label"), f"eras[{idx}].label")
        target = float(finite_num(era.get("target"), f"eras[{idx}].target"))
        require(s_min <= target <= s_max, f"eras[{idx}].target must be within scale [{s_min}, {s_max}]")
        orig_target = era.get("original_target")
        if orig_target is not None:
            orig_target = float(finite_num(orig_target, f"eras[{idx}].original_target"))
            require(s_min <= orig_target <= s_max, f"eras[{idx}].original_target out of scale")
        historical = era.get("historical", False)
        require(isinstance(historical, bool), f"eras[{idx}].historical must be boolean")
        comparable = era.get("comparable_to_prev", idx > 0)
        require(isinstance(comparable, bool), f"eras[{idx}].comparable_to_prev must be boolean")
        note = era.get("note", "")
        require(isinstance(note, str), f"eras[{idx}].note must be text")
        rec = era.get("recovery")
        recovery_clean = None
        if rec is not None:
            require(isinstance(rec, dict), f"eras[{idx}].recovery must be an object")
            rkind = nonempty_str(rec.get("kind", "automatic"), f"eras[{idx}].recovery.kind")
            require(rkind in RECOVERY_KINDS, f"eras[{idx}].recovery.kind must be one of {sorted(RECOVERY_KINDS)}")
            recovery_clean = {
                "kind": rkind,
                "label": nonempty_str(rec.get("label"), f"eras[{idx}].recovery.label"),
                "trigger": nonempty_str(rec.get("trigger"), f"eras[{idx}].recovery.trigger"),
                "diagnosis": nonempty_str(rec.get("diagnosis"), f"eras[{idx}].recovery.diagnosis"),
                "fix": nonempty_str(rec.get("fix"), f"eras[{idx}].recovery.fix"),
            }
        eitem = {
            "id": eid,
            "label": elabel,
            "target": target,
            "original_target": orig_target,
            "historical": historical,
            "comparable_to_prev": comparable if idx > 0 else True,
            "note": note.strip(),
            "recovery": recovery_clean,
            "index": idx,
        }
        eras.append(eitem)
        era_ids[eid] = eitem

    rounds_raw = data.get("rounds")
    require(isinstance(rounds_raw, list) and len(rounds_raw) >= 1, "rounds must be a nonempty list")
    rounds = []
    seen_round_ids: set[str] = set()
    era_order_seen = -1
    for r_idx, rnd in enumerate(rounds_raw):
        require(isinstance(rnd, dict), f"rounds[{r_idx}] must be an object")
        rid = nonempty_str(rnd.get("id"), f"rounds[{r_idx}].id")
        require(rid not in seen_round_ids, f"duplicate round id: {rid}")
        seen_round_ids.add(rid)
        rlabel = nonempty_str(rnd.get("label"), f"rounds[{r_idx}].label")
        cand = rnd.get("candidate", "")
        require(isinstance(cand, str), f"rounds[{r_idx}].candidate must be text")
        eid = nonempty_str(rnd.get("era"), f"rounds[{r_idx}].era")
        require(eid in era_ids, f"rounds[{r_idx}].era unknown: {eid}")
        e_order = era_ids[eid]["index"]
        require(e_order >= era_order_seen, f"rounds[{r_idx}].era moves backwards from earlier era")
        era_order_seen = e_order

        phase = nonempty_str(rnd.get("phase", "primary"), f"rounds[{r_idx}].phase")
        require(phase in PHASES, f"rounds[{r_idx}].phase must be one of {sorted(PHASES)}")
        rstatus = nonempty_str(rnd.get("status", "scored"), f"rounds[{r_idx}].status")
        require(rstatus in ROUND_STATUSES, f"rounds[{r_idx}].status must be one of {sorted(ROUND_STATUSES)}")

        exp = rnd.get("expected_reviewers")
        require(isinstance(exp, list) and len(exp) >= 1, f"rounds[{r_idx}].expected_reviewers must be nonempty")
        exp_clean = []
        for er in exp:
            er_id = nonempty_str(er, f"rounds[{r_idx}].expected_reviewers")
            require(er_id in reviewer_ids, f"rounds[{r_idx}].expected_reviewers unknown reviewer: {er_id}")
            require(er_id not in exp_clean, f"rounds[{r_idx}].expected_reviewers duplicate: {er_id}")
            exp_clean.append(er_id)

        failure_note = rnd.get("failure_note", "")
        require(isinstance(failure_note, str), f"rounds[{r_idx}].failure_note must be text")
        if rstatus in {"unscored", "incomplete"}:
            nonempty_str(failure_note, f"rounds[{r_idx}].failure_note")

        scores_raw = rnd.get("scores", [])
        require(isinstance(scores_raw, list), f"rounds[{r_idx}].scores must be a list")
        scores_by_rev: dict[str, dict] = {}
        for s_idx, sc in enumerate(scores_raw):
            require(isinstance(sc, dict), f"rounds[{r_idx}].scores[{s_idx}] must be an object")
            rev_id = nonempty_str(sc.get("reviewer"), f"rounds[{r_idx}].scores[{s_idx}].reviewer")
            require(rev_id in reviewer_ids, f"rounds[{r_idx}].scores[{s_idx}].reviewer unknown: {rev_id}")
            require(rev_id not in scores_by_rev, f"rounds[{r_idx}] duplicate score for {rev_id}")
            raw_val = sc.get("score")
            if raw_val is None:
                s_note = nonempty_str(
                    sc.get("failure_note", failure_note),
                    f"rounds[{r_idx}].scores[{s_idx}].failure_note",
                )
                s_stat = nonempty_str(sc.get("status", "not-evaluated"), f"rounds[{r_idx}].scores[{s_idx}].status")
                scores_by_rev[rev_id] = {
                    "reviewer": rev_id,
                    "score": None,
                    "status": s_stat,
                    "retried": bool(sc.get("retried", False)),
                    "retry_note": str(sc.get("retry_note", "")).strip(),
                    "failure_note": s_note,
                    "bullets": [],
                    "dimensions": [],
                }
            else:
                val = float(finite_num(raw_val, f"rounds[{r_idx}].scores[{s_idx}].score"))
                require(s_min <= val <= s_max, f"rounds[{r_idx}].scores[{s_idx}].score out of scale [{s_min}, {s_max}]")
                bullets_raw = sc.get("bullets")
                require(
                    isinstance(bullets_raw, list) and 3 <= len(bullets_raw) <= 5,
                    f"rounds[{r_idx}].scores[{s_idx}].bullets must have 3 to 5 items",
                )
                bullets = [nonempty_str(b, f"rounds[{r_idx}].scores[{s_idx}].bullets[{bi}]") for bi, b in enumerate(bullets_raw)]
                retried = sc.get("retried", False)
                require(isinstance(retried, bool), f"rounds[{r_idx}].scores[{s_idx}].retried must be boolean")
                retry_note = str(sc.get("retry_note", "")).strip()
                if retried:
                    nonempty_str(retry_note, f"rounds[{r_idx}].scores[{s_idx}].retry_note")
                dims_raw = sc.get("dimensions", [])
                require(isinstance(dims_raw, list), f"rounds[{r_idx}].scores[{s_idx}].dimensions must be a list")
                dims = []
                for di, dm in enumerate(dims_raw):
                    require(isinstance(dm, dict), f"rounds[{r_idx}].scores[{s_idx}].dimensions[{di}] must be an object")
                    dname = nonempty_str(dm.get("name"), f"rounds[{r_idx}].scores[{s_idx}].dimensions[{di}].name")
                    dval = float(finite_num(dm.get("score"), f"rounds[{r_idx}].scores[{s_idx}].dimensions[{di}].score"))
                    require(s_min <= dval <= s_max, f"dimension score out of scale for {dname}")
                    dweight = dm.get("weight")
                    if dweight is not None:
                        dweight = float(finite_num(dweight, f"dimension weight for {dname}"))
                        require(dweight > 0, f"dimension weight must be positive for {dname}")
                    dims.append({"name": dname, "score": dval, "weight": dweight})
                scores_by_rev[rev_id] = {
                    "reviewer": rev_id,
                    "score": val,
                    "status": "scored",
                    "retried": retried,
                    "retry_note": retry_note,
                    "failure_note": "",
                    "bullets": bullets,
                    "dimensions": dims,
                }

        if rstatus == "unscored":
            require(
                all(s["score"] is None for s in scores_by_rev.values()),
                f"rounds[{r_idx}] is unscored but contains a numeric score",
            )

        # Compute gating score strictly from expected_reviewers
        expected_scored = [
            scores_by_rev[er]
            for er in exp_clean
            if er in scores_by_rev and scores_by_rev[er]["score"] is not None
        ]
        missing_expected = [
            er for er in exp_clean if er not in scores_by_rev or scores_by_rev[er]["score"] is None
        ]
        gate_score: float | None = None
        gate_reviewers: list[str] = []
        if rstatus != "unscored" and not missing_expected and expected_scored:
            gate_score = min(s["score"] for s in expected_scored)
            gate_reviewers = [s["reviewer"] for s in expected_scored if s["score"] == gate_score]
        elif rstatus == "scored" and missing_expected:
            # Normalize: if an expected reviewer is missing, gate is unavailable (incomplete)
            rstatus = "incomplete"
            if not failure_note:
                failure_note = f"Missing score from {', '.join(reviewer_ids[m]['label'] for m in missing_expected)}; gating score unavailable."

        rounds.append(
            {
                "index": r_idx,
                "id": rid,
                "label": rlabel,
                "candidate": cand.strip(),
                "era": eid,
                "phase": phase,
                "status": rstatus,
                "expected_reviewers": exp_clean,
                "missing_reviewers": missing_expected,
                "failure_note": failure_note.strip(),
                "scores": scores_by_rev,
                "gate_score": gate_score,
                "gate_reviewers": gate_reviewers,
                "is_panel": len(exp_clean) > 1 or phase == "panel",
            }
        )

    return {
        "run": {
            "title": title,
            "id": run_id,
            "skill": skill,
            "status": status,
            "scale": {"min": s_min, "max": s_max, "precision": precision},
        },
        "reviewers": reviewers,
        "reviewer_map": reviewer_ids,
        "eras": eras,
        "era_map": era_ids,
        "rounds": rounds,
    }


def _svg_shape(shape: str, cx: float, cy: float, r: float, fill: str, stroke: str, sw: float = 1.6) -> str:
    if shape == "square":
        s = r * 1.65
        return (
            f'<rect x="{cx - s/2:.2f}" y="{cy - s/2:.2f}" width="{s:.2f}" height="{s:.2f}" '
            f'rx="1.5" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
        )
    if shape == "diamond":
        d = r * 1.25
        pts = f"{cx:.2f},{cy - d:.2f} {cx + d:.2f},{cy:.2f} {cx:.2f},{cy + d:.2f} {cx - d:.2f},{cy:.2f}"
        return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    if shape == "triangle":
        d = r * 1.25
        pts = f"{cx:.2f},{cy - d:.2f} {cx + d:.2f},{cy + d*0.85:.2f} {cx - d:.2f},{cy + d*0.85:.2f}"
        return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    if shape == "hex":
        pts = " ".join(
            f"{cx + r*1.18*math.cos(math.radians(60*k - 30)):.2f},{cy + r*1.18*math.sin(math.radians(60*k - 30)):.2f}"
            for k in range(6)
        )
        return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    if shape == "ring":
        return f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="var(--card, #14171f)" stroke="{fill}" stroke-width="{sw + 1.0}"/>'
    return f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def _compute_y_bounds(model: dict) -> tuple[float, float, list[float]]:
    s_min = model["run"]["scale"]["min"]
    s_max = model["run"]["scale"]["max"]
    vals: list[float] = []
    for era in model["eras"]:
        vals.append(era["target"])
        if era["original_target"] is not None:
            vals.append(era["original_target"])
    for rnd in model["rounds"]:
        for sc in rnd["scores"].values():
            if sc["score"] is not None:
                vals.append(sc["score"])
    if not vals:
        lo, hi = s_min, s_max
    else:
        lo_raw = min(vals)
        hi_raw = max(vals)
        span = max(1.0, hi_raw - lo_raw)
        step = 1.0 if (s_max - s_min) <= 15 else max(1.0, round((s_max - s_min) / 5.0))
        lo = max(s_min, math.floor((lo_raw - span * 0.18) / step) * step)
        hi = min(s_max, math.ceil((hi_raw + span * 0.15) / step) * step)
        if hi - lo < step * 2:
            lo = max(s_min, hi - step * 2)
            if hi - lo < step * 2:
                hi = min(s_max, lo + step * 2)
    # Build 4-6 clean ticks
    rng = hi - lo
    tick_step = 1.0
    if rng > 10:
        tick_step = math.ceil(rng / 5.0)
    elif rng <= 2:
        tick_step = 0.5
    ticks = []
    cur = lo
    while cur <= hi + 1e-9:
        ticks.append(round(cur, 2))
        cur += tick_step
    if ticks[-1] < hi - 1e-9:
        ticks.append(round(hi, 2))
    return lo, hi, ticks


def render_html(data: dict) -> str:
    model = validate(data)
    run = model["run"]
    prec = run["scale"]["precision"]
    reviewers = model["reviewers"]
    rev_map = model["reviewer_map"]
    eras = model["eras"]
    era_map = model["era_map"]
    rounds = model["rounds"]

    y_lo, y_hi, y_ticks = _compute_y_bounds(model)

    # Geometry: fluid width up to 728px, expands cleanly for >8 rounds via horizontal scroll
    n_rounds = len(rounds)
    left_pad = 44.0
    right_pad = 86.0
    slot_w = max(84.0, min(110.0, (712.0 - left_pad - right_pad) / max(n_rounds, 1)))
    plot_w = max(580.0, slot_w * n_rounds)
    svg_w = left_pad + plot_w + right_pad

    top_band_h = 28.0
    plot_top = 42.0
    plot_h = 216.0
    plot_bottom = plot_top + plot_h
    off_axis_top = plot_bottom + 10.0
    off_axis_h = 30.0
    x_label_y = off_axis_top + off_axis_h + 18.0
    svg_h = x_label_y + 30.0

    def x_of(idx: int) -> float:
        return left_pad + (idx + 0.5) * (plot_w / n_rounds)

    def y_of(val: float) -> float:
        frac = (val - y_lo) / max(y_hi - y_lo, 1e-6)
        return plot_bottom - frac * plot_h

    # Group contiguous rounds by era
    era_spans: list[dict] = []
    for r in rounds:
        if not era_spans or era_spans[-1]["era"] != r["era"]:
            era_spans.append({"era": r["era"], "start": r["index"], "end": r["index"]})
        else:
            era_spans[-1]["end"] = r["index"]

    col_w = plot_w / n_rounds

    # Header summary chips
    last_era = era_map[rounds[-1]["era"]]
    last_scored = next((r for r in reversed(rounds) if r["gate_score"] is not None), None)
    verdict_chips = []
    if last_scored is not None:
        g_val = last_scored["gate_score"]
        g_str = fmt_score(g_val, prec)
        t_val = last_era["target"]
        t_str = fmt_score(t_val, prec)
        orig_t = last_era["original_target"]
        if g_val >= t_val and run["status"] in {"passed", "passed-revised"}:
            verdict_chips.append(
                f'<span class="sc-chip sc-chip-pass">✓ Pass · gate {g_str} ≥ {t_str}</span>'
            )
        elif g_val >= t_val:
            verdict_chips.append(
                f'<span class="sc-chip sc-chip-info">Gate {g_str} ≥ {t_str}</span>'
            )
        else:
            verdict_chips.append(
                f'<span class="sc-chip sc-chip-warn">Gate {g_str} · target {t_str}</span>'
            )
        if orig_t is not None and g_val < orig_t:
            verdict_chips.append(
                f'<span class="sc-chip sc-chip-warn">⚑ Below original {fmt_score(orig_t, prec)}</span>'
            )
    else:
        verdict_chips.append(f'<span class="sc-chip sc-chip-fail">No completed gate yet</span>')

    # Build SVG layers & interactive mark payloads
    svg_parts: list[str] = []
    marks: list[dict] = []

    # Defs: hatch pattern for unscored build-fail column
    svg_parts.append(
        """<defs>
  <pattern id="sc-hatch-fail" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
    <line x1="0" y1="0" x2="0" y2="7" stroke="var(--destructive, #ef4444)" stroke-width="1.6" opacity="0.45"/>
  </pattern>
</defs>"""
    )

    # Era background bands & top era labels (B1-F2 style)
    for sp_idx, sp in enumerate(era_spans):
        era = era_map[sp["era"]]
        x0 = left_pad + sp["start"] * col_w
        x1 = left_pad + (sp["end"] + 1) * col_w
        w = x1 - x0
        if era["historical"]:
            svg_parts.append(
                f'<rect class="sc-hist-fill" x="{x0:.2f}" y="{plot_top:.2f}" width="{w:.2f}" height="{plot_h:.2f}"/>'
            )
        band_cls = "sc-era-hist" if era["historical"] else "sc-era-curr"
        tag_text = f"{era['label']} · historical" if era["historical"] else f"{era['label']} · current"
        if w < 120:
            tag_text = era["label"]
        svg_parts.append(
            f'<rect class="{band_cls}" x="{x0 + 2:.2f}" y="8" width="{max(w - 4, 24):.2f}" height="20" rx="5"/>'
        )
        svg_parts.append(
            f'<text class="sc-era-text" x="{x0 + 9:.2f}" y="21.5">{escape(tag_text)}</text>'
        )

    # Horizontal gridlines & Y ticks
    for tv in y_ticks:
        yy = y_of(tv)
        svg_parts.append(
            f'<line class="sc-grid" x1="{left_pad:.2f}" y1="{yy:.2f}" x2="{left_pad + plot_w:.2f}" y2="{yy:.2f}"/>'
        )
        svg_parts.append(
            f'<text class="sc-axis-y" x="{left_pad - 8:.2f}" y="{yy + 3.5:.2f}" text-anchor="end">{fmt_score(tv, prec if prec > 0 and tv % 1 else 0)}</text>'
        )

    # Unscored failure full-height hatched columns (B1-F6 style)
    for r in rounds:
        if r["status"] == "unscored":
            cx = x_of(r["index"])
            bx = cx - col_w * 0.36
            bw = col_w * 0.72
            svg_parts.append(
                f'<rect x="{bx:.2f}" y="{plot_top:.2f}" width="{bw:.2f}" height="{plot_h:.2f}" '
                f'fill="var(--destructive-surface, rgba(239,68,68,0.10))" stroke="var(--destructive, #ef4444)" '
                f'stroke-opacity="0.35" stroke-width="1"/>'
            )
            svg_parts.append(
                f'<rect x="{bx:.2f}" y="{plot_top:.2f}" width="{bw:.2f}" height="{plot_h:.2f}" '
                f'fill="url(#sc-hatch-fail)"/>'
            )
            svg_parts.append(
                f'<text class="sc-noscore-label" x="{cx:.2f}" y="{plot_top + plot_h/2:.2f}" '
                f'transform="rotate(-90 {cx:.2f} {plot_top + plot_h/2:.2f})" text-anchor="middle">NO SCORE · NOT 0</text>'
            )

    # Off-axis "Not scored" lane (A1-F7)
    svg_parts.append(
        f'<rect class="sc-off-lane" x="{left_pad:.2f}" y="{off_axis_top:.2f}" width="{plot_w:.2f}" height="{off_axis_h:.2f}" rx="6"/>'
    )
    svg_parts.append(
        f'<text class="sc-off-label" x="{left_pad + 8:.2f}" y="{off_axis_top + 18.5:.2f}">Not scored · off-axis</text>'
    )

    # Stepped dotted target line + ghost original target (A1-F4)
    prev_tx = None
    prev_ty = None
    for sp_idx, sp in enumerate(era_spans):
        era = era_map[sp["era"]]
        x0 = left_pad + sp["start"] * col_w
        x1 = left_pad + (sp["end"] + 1) * col_w
        ty = y_of(era["target"])
        if prev_tx is not None and prev_ty is not None and abs(prev_ty - ty) > 0.5:
            svg_parts.append(
                f'<line class="sc-target-step" x1="{x0:.2f}" y1="{prev_ty:.2f}" x2="{x0:.2f}" y2="{ty:.2f}"/>'
            )
        svg_parts.append(
            f'<line class="sc-target" x1="{x0:.2f}" y1="{ty:.2f}" x2="{x1:.2f}" y2="{ty:.2f}"/>'
        )
        if era["original_target"] is not None and abs(era["original_target"] - era["target"]) > 1e-6:
            gy = y_of(era["original_target"])
            svg_parts.append(
                f'<line class="sc-target-ghost" x1="{x0:.2f}" y1="{gy:.2f}" x2="{x1:.2f}" y2="{gy:.2f}"/>'
            )
            if sp_idx == len(era_spans) - 1:
                svg_parts.append(
                    f'<text class="sc-target-tag-ghost" x="{x1 + 8:.2f}" y="{gy + 3.5:.2f}">{fmt_score(era["original_target"], prec)} orig</text>'
                )
        prev_tx, prev_ty = x1, ty

    # Right-gutter active target pill
    final_ty = y_of(last_era["target"])
    target_tag = f'{fmt_score(last_era["target"], prec)} {"rev" if last_era["original_target"] is not None else "target"}'
    svg_parts.append(
        f'<rect class="sc-target-pill" x="{left_pad + plot_w + 6:.2f}" y="{final_ty - 10:.2f}" width="72" height="20" rx="5"/>'
    )
    svg_parts.append(
        f'<text class="sc-target-pill-text" x="{left_pad + plot_w + 42:.2f}" y="{final_ty + 3.5:.2f}" text-anchor="middle">{escape(target_tag)}</text>'
    )

    # Recovery vertical dividers & badges (A1-F3 / B1-F4)
    for sp_idx in range(1, len(era_spans)):
        sp = era_spans[sp_idx]
        era = era_map[sp["era"]]
        vx = left_pad + sp["start"] * col_w
        svg_parts.append(
            f'<line class="sc-recovery-line" x1="{vx:.2f}" y1="28" x2="{vx:.2f}" y2="{off_axis_top + off_axis_h + 6:.2f}"/>'
        )
        rec = era.get("recovery")
        if rec:
            mid = f"recovery-{sp_idx}"
            lbl = rec["label"]
            bw = max(92.0, min(195.0, len(lbl) * 6.5 + 22.0))
            bx = max(left_pad + 4, min(left_pad + plot_w - bw - 4, vx - bw / 2))
            marks.append(
                {
                    "id": mid,
                    "kind": "recovery",
                    "round_id": rounds[sp["start"]]["id"],
                    "title": rec["label"],
                    "subtitle": f"{rec['kind'].capitalize()} recovery · {era['label']}",
                    "era_note": (
                        "Scores before this divider are historical and non-comparable."
                        if not era["comparable_to_prev"]
                        else "Same evaluation contract; scores remain comparable."
                    ),
                    "bullets": [
                        f"Trigger: {rec['trigger']}",
                        f"Diagnosis: {rec['diagnosis']}",
                        f"Fix: {rec['fix']}",
                    ],
                    "dimensions": [],
                }
            )
            svg_parts.append(
                f'<g class="sc-mark" data-mark-id="{mid}" tabindex="-1" role="button" aria-label="{escape(lbl)}">'
                f'<rect class="sc-recovery-badge" x="{bx:.2f}" y="29" width="{bw:.2f}" height="20" rx="10"/>'
                f'<text class="sc-recovery-text" x="{bx + bw/2:.2f}" y="42.5" text-anchor="middle">↻ {escape(lbl)}</text>'
                f"</g>"
            )

    # Helper to compute x offset per reviewer when multiple reviewers share a round
    def rev_offset(rnd: dict, rev_id: str) -> float:
        scored_revs = [er for er in rnd["expected_reviewers"] if er in rnd["scores"] and rnd["scores"][er]["score"] is not None]
        if len(scored_revs) <= 1:
            return 0.0
        pos = scored_revs.index(rev_id) if rev_id in scored_revs else 0
        spread = min(14.0, (col_w * 0.32) / max(len(scored_revs) - 1, 1))
        return (pos - (len(scored_revs) - 1) / 2.0) * spread

    # Reviewer polyline segments (break across unscored rounds AND non-comparable era boundaries)
    for rev in reviewers:
        rid = rev["id"]
        segments: list[list[tuple[float, float]]] = []
        cur_seg: list[tuple[float, float]] = []
        prev_era_id = None
        for r in rounds:
            era = era_map[r["era"]]
            if prev_era_id is not None and r["era"] != prev_era_id and not era["comparable_to_prev"]:
                if len(cur_seg) >= 2:
                    segments.append(cur_seg)
                cur_seg = []
            prev_era_id = r["era"]
            sc = r["scores"].get(rid)
            if sc is not None and sc["score"] is not None:
                cur_seg.append((x_of(r["index"]) + rev_offset(r, rid), y_of(sc["score"])))
            else:
                if len(cur_seg) >= 2:
                    segments.append(cur_seg)
                cur_seg = []
        if len(cur_seg) >= 2:
            segments.append(cur_seg)

        stroke = f"var({rev['color_var']}, {rev['color_fallback']})"
        for seg in segments:
            pts = " ".join(f"{px:.2f},{py:.2f}" for px, py in seg)
            svg_parts.append(
                f'<polyline class="sc-series-line" data-reviewer="{escape(rid)}" '
                f'points="{pts}" fill="none" stroke="{stroke}" stroke-width="2.1" stroke-linejoin="round" stroke-linecap="round"/>'
            )

    # Gating-minimum line across comparable multi-reviewer rounds + gate bars on panel rounds
    gate_segments: list[list[tuple[float, float]]] = []
    cur_gate: list[tuple[float, float]] = []
    prev_era_id = None
    prev_is_panel = None
    for r in rounds:
        era = era_map[r["era"]]
        if prev_era_id is not None and (
            (r["era"] != prev_era_id and not era["comparable_to_prev"])
            or (prev_is_panel is not None and r["is_panel"] != prev_is_panel)
        ):
            if len(cur_gate) >= 2:
                gate_segments.append(cur_gate)
            cur_gate = []
        prev_era_id = r["era"]
        prev_is_panel = r["is_panel"]
        if r["gate_score"] is not None and r["is_panel"]:
            cur_gate.append((x_of(r["index"]), y_of(r["gate_score"])))
        else:
            if len(cur_gate) >= 2:
                gate_segments.append(cur_gate)
            cur_gate = []
    if len(cur_gate) >= 2:
        gate_segments.append(cur_gate)
    for seg in gate_segments:
        pts = " ".join(f"{px:.2f},{py:.2f}" for px, py in seg)
        svg_parts.append(
            f'<polyline class="sc-gate-line" points="{pts}" fill="none"/>'
        )

    # Precompute per-reviewer previous dimension scores so bars show improvement/decline deltas
    last_dims_by_rev: dict[str, dict[str, float]] = {}
    enriched_dims: dict[tuple[int, str], list[dict]] = {}
    for r in rounds:
        for rev_id, sc in r["scores"].items():
            if sc["score"] is None:
                continue
            prev_map = last_dims_by_rev.get(rev_id, {})
            cur_enriched = []
            next_map = dict(prev_map)
            for dm in sc["dimensions"]:
                prev_val = prev_map.get(dm["name"])
                delta = round(dm["score"] - prev_val, prec) if prev_val is not None else None
                cur_enriched.append(
                    {
                        "name": dm["name"],
                        "score": dm["score"],
                        "weight": dm["weight"],
                        "prev_score": prev_val,
                        "delta": delta,
                    }
                )
                next_map[dm["name"]] = dm["score"]
            enriched_dims[(r["index"], rev_id)] = cur_enriched
            last_dims_by_rev[rev_id] = next_map

    # Plot marks: panel gate bars, reviewer points, and off-axis unscored/timeout markers
    default_pin_id = None
    for r in rounds:
        cx = x_of(r["index"])
        era = era_map[r["era"]]

        # Gate bar for completed panel rounds (full-bar hit target!)
        if r["is_panel"] and r["gate_score"] is not None:
            gy = y_of(r["gate_score"])
            gid = f"gate-{r['index']}"
            min_rev_id = r["gate_reviewers"][0]
            min_rev = rev_map[min_rev_id]
            min_sc = r["scores"][min_rev_id]
            panel_summary = " · ".join(
                f"{rev_map[er]['label']} {fmt_score(r['scores'][er]['score'], prec)}"
                for er in r["expected_reviewers"]
                if er in r["scores"] and r["scores"][er]["score"] is not None
            )
            gate_bullets = [
                f"Gating minimum across {len(r['expected_reviewers'])} judges: {fmt_score(r['gate_score'], prec)} (set by {min_rev['label']}).",
                f"Panel scores: {panel_summary}.",
            ] + min_sc["bullets"][:3]
            marks.append(
                {
                    "id": gid,
                    "kind": "gate",
                    "round_id": r["id"],
                    "title": f"Gating minimum · {fmt_score(r['gate_score'], prec)}",
                    "subtitle": f"{r['id']} {r['label']}" + (f" · {r['candidate']}" if r["candidate"] else "") + f" · {era['label']}",
                    "score_display": fmt_score(r["gate_score"], prec),
                    "target_display": fmt_score(era["target"], prec),
                    "original_target_display": fmt_score(era["original_target"], prec) if era["original_target"] is not None else None,
                    "passed": r["gate_score"] >= era["target"],
                    "historical": era["historical"],
                    "reviewer_label": f"Min set by {min_rev['label']}",
                    "bullets": gate_bullets[:5],
                    "dimensions": enriched_dims.get((r["index"], min_rev_id), min_sc["dimensions"]),
                }
            )
            default_pin_id = gid
            bar_w = min(46.0, col_w * 0.52)
            svg_parts.append(
                f'<g class="sc-mark sc-gate-mark" data-mark-id="{gid}" tabindex="-1" role="button" '
                f'aria-label="Gate minimum {fmt_score(r["gate_score"], prec)} in {escape(r["id"])}">'
                f'<rect x="{cx - bar_w/2 - 4:.2f}" y="{gy - 11:.2f}" width="{bar_w + 8:.2f}" height="22" fill="transparent"/>'
                f'<line class="sc-gate-bar" x1="{cx - bar_w/2:.2f}" y1="{gy:.2f}" x2="{cx + bar_w/2:.2f}" y2="{gy:.2f}"/>'
                f'<text class="sc-gate-lbl" x="{cx:.2f}" y="{gy + 14:.2f}" text-anchor="middle">min {fmt_score(r["gate_score"], prec)}</text>'
                f"</g>"
            )

        # Reviewer score points
        for er in r["expected_reviewers"]:
            sc = r["scores"].get(er)
            if sc is None or sc["score"] is None:
                continue
            rev = rev_map[er]
            px = cx + rev_offset(r, er)
            py = y_of(sc["score"])
            mid = f"score-{r['index']}-{er}"
            marks.append(
                {
                    "id": mid,
                    "kind": "score",
                    "reviewer": er,
                    "reviewer_label": rev["label"],
                    "reviewer_role": rev["role"],
                    "round_id": r["id"],
                    "title": f"{rev['label']} · {fmt_score(sc['score'], prec)}",
                    "subtitle": f"{r['id']} {r['label']}" + (f" · {r['candidate']}" if r["candidate"] else "") + f" · {era['label']}",
                    "score_display": fmt_score(sc["score"], prec),
                    "target_display": fmt_score(era["target"], prec),
                    "original_target_display": fmt_score(era["original_target"], prec) if era["original_target"] is not None else None,
                    "passed": sc["score"] >= era["target"],
                    "historical": era["historical"],
                    "retried": sc["retried"],
                    "retry_note": sc["retry_note"],
                    "bullets": sc["bullets"],
                    "dimensions": enriched_dims.get((r["index"], er), sc["dimensions"]),
                }
            )
            if not r["is_panel"]:
                default_pin_id = mid
            fill = f"var({rev['color_var']}, {rev['color_fallback']})"
            retry_ring = ""
            if sc["retried"]:
                retry_ring = (
                    f'<circle class="sc-retry-ring" cx="{px:.2f}" cy="{py:.2f}" r="9.5"/>'
                    f'<text class="sc-retry-glyph" x="{px + 9.5:.2f}" y="{py - 7.5:.2f}">↻</text>'
                )
            svg_parts.append(
                f'<g class="sc-mark sc-score-mark" data-mark-id="{mid}" data-reviewer="{escape(er)}" '
                f'tabindex="-1" role="button" aria-label="{escape(rev["label"])} scored {fmt_score(sc["score"], prec)} in {escape(r["id"])}">'
                f'<circle cx="{px:.2f}" cy="{py:.2f}" r="12" fill="transparent"/>'
                f"{retry_ring}"
                f'{_svg_shape(rev["shape"], px, py, 5.2, fill, "var(--card, #14171f)", 1.6)}'
                f"</g>"
            )

        # Off-axis markers for unscored rounds or incomplete panels
        off_cy = off_axis_top + off_axis_h / 2.0
        if r["status"] == "unscored":
            fid = f"fail-{r['index']}"
            marks.append(
                {
                    "id": fid,
                    "kind": "failure",
                    "round_id": r["id"],
                    "title": f"{r['id']} · {r['label']} (Not scored)",
                    "subtitle": (f"{r['candidate']} · " if r["candidate"] else "") + f"{era['label']} · off-axis",
                    "historical": era["historical"],
                    "bullets": [r["failure_note"]],
                    "dimensions": [],
                }
            )
            svg_parts.append(
                f'<g class="sc-mark sc-fail-mark" data-mark-id="{fid}" tabindex="-1" role="button" '
                f'aria-label="{escape(r["id"])} unscored failure">'
                f'<rect x="{cx - 42:.2f}" y="{off_cy - 11:.2f}" width="84" height="22" rx="5" class="sc-fail-pill"/>'
                f'<text class="sc-fail-pill-text" x="{cx:.2f}" y="{off_cy + 3.5:.2f}" text-anchor="middle">✕ {escape(r["label"][:12])}</text>'
                f"</g>"
            )
        elif r["status"] == "incomplete":
            iid = f"inc-{r['index']}"
            miss_labels = ", ".join(rev_map[m]["label"] for m in r["missing_reviewers"])
            inc_bullets = [r["failure_note"]]
            for m in r["missing_reviewers"]:
                msc = r["scores"].get(m)
                if msc and msc.get("failure_note") and msc["failure_note"] != r["failure_note"]:
                    inc_bullets.append(f"{rev_map[m]['label']}: {msc['failure_note']}")
            marks.append(
                {
                    "id": iid,
                    "kind": "incomplete",
                    "round_id": r["id"],
                    "title": f"{r['id']} · Gate unavailable ({miss_labels} missing)",
                    "subtitle": (f"{r['candidate']} · " if r["candidate"] else "") + f"{era['label']} · incomplete panel",
                    "historical": era["historical"],
                    "bullets": inc_bullets[:5],
                    "dimensions": [],
                }
            )
            svg_parts.append(
                f'<g class="sc-mark sc-inc-mark" data-mark-id="{iid}" tabindex="-1" role="button" '
                f'aria-label="{escape(r["id"])} incomplete panel, gate unavailable">'
                f'<rect x="{cx - 48:.2f}" y="{off_cy - 11:.2f}" width="96" height="22" rx="5" class="sc-inc-pill"/>'
                f'<text class="sc-inc-pill-text" x="{cx:.2f}" y="{off_cy + 3.5:.2f}" text-anchor="middle">gate n/a · t/o</text>'
                f"</g>"
            )

        # X-axis labels
        lbl_cls = "sc-axis-x sc-axis-x-fail" if r["status"] == "unscored" else "sc-axis-x"
        svg_parts.append(
            f'<text class="{lbl_cls}" x="{cx:.2f}" y="{x_label_y:.2f}" text-anchor="middle">{escape(r["id"])}</text>'
        )
        svg_parts.append(
            f'<text class="sc-axis-sub" x="{cx:.2f}" y="{x_label_y + 13.5:.2f}" text-anchor="middle">{escape(r["label"])}</text>'
        )

    if default_pin_id is None and marks:
        default_pin_id = marks[-1]["id"]

    # Legend HTML (clean flex wrap, reviewer highlight buttons + semantic cues)
    legend_items = []
    for rev in reviewers:
        color = f"var({rev['color_var']}, {rev['color_fallback']})"
        swatch = (
            f'<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">'
            f'{_svg_shape(rev["shape"], 7, 7, 4.5, color, "none", 0)}'
            f"</svg>"
        )
        role_txt = f' <span class="sc-leg-role">{escape(rev["role"])}</span>' if rev["role"] else ""
        legend_items.append(
            f'<button type="button" class="sc-leg-btn" data-rev-filter="{escape(rev["id"])}" aria-pressed="false">'
            f"{swatch}<span>{escape(rev['label'])}{role_txt}</span></button>"
        )
    legend_cues = [
        '<span class="sc-leg-cue"><span class="sc-cue-gate"></span>Gate (panel min)</span>',
        '<span class="sc-leg-cue"><span class="sc-cue-target"></span>Target</span>',
        '<span class="sc-leg-cue"><span class="sc-cue-retry">↻</span>Retried</span>',
        '<span class="sc-leg-cue"><span class="sc-cue-fail">✕</span>Unscored</span>',
    ]

    # Collapsible HTML data table (A1-F10)
    table_headers = "".join(f"<th>{escape(rev['label'])}</th>" for rev in reviewers)
    table_rows = []
    for r in rounds:
        era = era_map[r["era"]]
        cells = []
        for rev in reviewers:
            sc = r["scores"].get(rev["id"])
            if sc is None:
                cells.append("<td>—</td>")
            elif sc["score"] is None:
                cells.append(f'<td class="sc-td-muted">{escape(sc["status"])}</td>')
            else:
                retry_tag = " ↻" if sc["retried"] else ""
                cells.append(f'<td>{fmt_score(sc["score"], prec)}{retry_tag}</td>')
        gate_cell = fmt_score(r["gate_score"], prec) if r["gate_score"] is not None else "n/a"
        table_rows.append(
            "<tr>"
            f"<td><strong>{escape(r['id'])}</strong> {escape(r['label'])}</td>"
            f"<td>{escape(era['label'])}</td>"
            f"<td>{fmt_score(era['target'], prec)}</td>"
            + "".join(cells)
            + f"<td><strong>{gate_cell}</strong></td>"
            f"<td>{escape(r['status'])}</td>"
            "</tr>"
        )

    payload_json = json.dumps(
        {"marks": marks, "defaultPin": default_pin_id, "precision": prec, "scaleMax": run["scale"]["max"]},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(run['title'])} · {escape(run['id'])}</title>
<style>
:root {{
  --sc-fg: var(--foreground, #eceef2);
  --sc-muted: var(--muted-foreground, #9aa3b2);
  --sc-card: var(--card, #14171f);
  --sc-secondary: var(--secondary, rgba(255,255,255,0.06));
  --sc-border: var(--border, rgba(255,255,255,0.12));
  --sc-primary: var(--primary, #5b8def);
  --sc-success: var(--success, #34d399);
  --sc-warning: var(--warning, #f5b942);
  --sc-warning-bg: var(--warning-surface, rgba(245,185,66,0.12));
  --sc-danger: var(--destructive, #ef4444);
  --sc-danger-bg: var(--destructive-surface, rgba(239,68,68,0.12));
  --sc-radius: var(--radius, 10px);
  --sc-sans: var(--font-sans, system-ui, -apple-system, sans-serif);
  --sc-mono: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
}}
@media (prefers-color-scheme: light) {{
  :root {{
    --sc-fg: var(--foreground, #111827);
    --sc-muted: var(--muted-foreground, #4b5563);
    --sc-card: var(--card, #f9fafb);
    --sc-secondary: var(--secondary, rgba(17,24,39,0.05));
    --sc-border: var(--border, rgba(17,24,39,0.14));
  }}
}}
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{
  margin: 0;
  padding: 0;
  background: transparent;
  color: var(--sc-fg);
  font-family: var(--sc-sans);
}}
.sc-root {{
  container-type: inline-size;
  width: 100%;
  font-size: 13px;
  line-height: 1.45;
}}
.sc-head {{
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px 12px;
  margin-bottom: 10px;
}}
.sc-title-row {{
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 8px;
}}
.sc-title {{
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}}
.sc-run-id {{
  font-family: var(--sc-mono);
  font-size: 11px;
  color: var(--sc-muted);
}}
.sc-sub {{
  margin: 2px 0 0 0;
  font-size: 12px;
  color: var(--sc-muted);
}}
.sc-chips {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}
.sc-chip {{
  font-family: var(--sc-mono);
  font-size: 11px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid var(--sc-border);
  white-space: nowrap;
}}
.sc-chip-pass {{
  color: var(--sc-success);
  border-color: color-mix(in srgb, var(--sc-success) 45%, transparent);
  background: color-mix(in srgb, var(--sc-success) 12%, transparent);
}}
.sc-chip-warn {{
  color: var(--sc-warning);
  border-color: color-mix(in srgb, var(--sc-warning) 45%, transparent);
  background: var(--sc-warning-bg);
}}
.sc-chip-fail {{
  color: var(--sc-danger);
  border-color: color-mix(in srgb, var(--sc-danger) 45%, transparent);
  background: var(--sc-danger-bg);
}}
.sc-chip-info {{
  color: var(--sc-primary);
  border-color: color-mix(in srgb, var(--sc-primary) 45%, transparent);
  background: color-mix(in srgb, var(--sc-primary) 12%, transparent);
}}
.sc-legend {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  margin-bottom: 10px;
  font-size: 12px;
}}
.sc-leg-group {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}}
.sc-leg-btn {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px 2px 6px;
  border-radius: 999px;
  border: 1px solid var(--sc-border);
  background: var(--sc-secondary);
  color: var(--sc-fg);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
  transition: opacity 0.15s ease, border-color 0.15s ease;
}}
.sc-leg-btn[aria-pressed="true"] {{
  border-color: var(--sc-primary);
}}
.sc-leg-btn.sc-dim {{
  opacity: 0.42;
}}
.sc-leg-role {{
  color: var(--sc-muted);
  font-size: 11px;
}}
.sc-leg-cues {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  color: var(--sc-muted);
  font-size: 11.5px;
}}
.sc-leg-cue {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
}}
.sc-cue-gate {{
  display: inline-block;
  width: 14px;
  height: 3px;
  border-radius: 2px;
  background: var(--sc-fg);
}}
.sc-cue-target {{
  display: inline-block;
  width: 14px;
  border-top: 2px dotted var(--sc-fg);
}}
.sc-cue-retry {{
  color: var(--sc-warning);
  font-weight: 700;
}}
.sc-cue-fail {{
  color: var(--sc-danger);
  font-weight: 700;
}}
.sc-chart-wrap {{
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--sc-border);
  border-radius: var(--sc-radius);
  background: var(--sc-card);
  padding: 6px 6px 4px 6px;
  margin-bottom: 10px;
}}
.sc-svg {{
  display: block;
  width: 100%;
  min-width: {min(svg_w, 640):.0f}px;
  height: auto;
  user-select: none;
}}
.sc-grid {{ stroke: var(--sc-border); stroke-width: 1; opacity: 0.7; }}
.sc-axis-y {{ fill: var(--sc-muted); font-family: var(--sc-mono); font-size: 10.5px; }}
.sc-axis-x {{ fill: var(--sc-fg); font-family: var(--sc-mono); font-size: 11px; font-weight: 700; }}
.sc-axis-x-fail {{ fill: var(--sc-danger); }}
.sc-axis-sub {{ fill: var(--sc-muted); font-size: 10px; }}
.sc-era-hist {{ fill: var(--sc-secondary); stroke: var(--sc-border); stroke-width: 1; }}
.sc-hist-fill {{ fill: color-mix(in srgb, var(--sc-muted) 9%, transparent); }}
.sc-era-curr {{ fill: color-mix(in srgb, var(--sc-primary) 16%, transparent); stroke: color-mix(in srgb, var(--sc-primary) 42%, transparent); stroke-width: 1; }}
.sc-era-text {{ fill: var(--sc-muted); font-family: var(--sc-mono); font-size: 10px; font-weight: 600; }}
.sc-noscore-label {{ fill: var(--sc-danger); font-family: var(--sc-mono); font-size: 9.5px; font-weight: 700; letter-spacing: 0.08em; opacity: 0.9; }}
.sc-off-lane {{ fill: var(--sc-secondary); stroke: var(--sc-border); stroke-width: 1; stroke-dasharray: 3 3; }}
.sc-off-label {{ fill: var(--sc-muted); font-family: var(--sc-mono); font-size: 10px; }}
.sc-target {{ stroke: var(--sc-fg); stroke-width: 1.6; stroke-dasharray: 2.5 4; opacity: 0.85; }}
.sc-target-step {{ stroke: var(--sc-primary); stroke-width: 1.4; stroke-dasharray: 2.5 3.5; opacity: 0.75; }}
.sc-target-ghost {{ stroke: var(--sc-muted); stroke-width: 1.2; stroke-dasharray: 2 5; opacity: 0.55; }}
.sc-target-tag-ghost {{ fill: var(--sc-muted); font-family: var(--sc-mono); font-size: 10px; opacity: 0.8; }}
.sc-target-pill {{ fill: var(--sc-secondary); stroke: var(--sc-border); stroke-width: 1; }}
.sc-target-pill-text {{ fill: var(--sc-fg); font-family: var(--sc-mono); font-size: 10.5px; font-weight: 600; }}
.sc-recovery-line {{ stroke: var(--sc-primary); stroke-width: 1.8; }}
.sc-recovery-badge {{ fill: var(--sc-primary); }}
.sc-recovery-text {{ fill: var(--primary-foreground, #ffffff); font-family: var(--sc-mono); font-size: 10px; font-weight: 700; }}
.sc-gate-line {{ stroke: var(--sc-fg); stroke-width: 2.6; opacity: 0.45; }}
.sc-gate-bar {{ stroke: var(--sc-fg); stroke-width: 3.2; stroke-linecap: round; }}
.sc-gate-lbl {{ fill: var(--sc-fg); font-family: var(--sc-mono); font-size: 10px; font-weight: 700; paint-order: stroke; stroke: var(--sc-card); stroke-width: 4px; stroke-linejoin: round; }}
.sc-retry-ring {{ fill: none; stroke: var(--sc-warning); stroke-width: 1.7; stroke-dasharray: 3 2.5; }}
.sc-retry-glyph {{ fill: var(--sc-warning); font-size: 10.5px; font-weight: 700; }}
.sc-fail-pill {{ fill: var(--sc-danger-bg); stroke: var(--sc-danger); stroke-width: 1; }}
.sc-fail-pill-text {{ fill: var(--sc-danger); font-family: var(--sc-mono); font-size: 10px; font-weight: 700; }}
.sc-inc-pill {{ fill: var(--sc-warning-bg); stroke: var(--sc-warning); stroke-width: 1; stroke-dasharray: 3 2; }}
.sc-inc-pill-text {{ fill: var(--sc-warning); font-family: var(--sc-mono); font-size: 10px; font-weight: 700; }}
.sc-mark {{ cursor: pointer; outline: none; transition: opacity 0.15s ease; }}
.sc-mark.sc-active {{ filter: drop-shadow(0 0 4px var(--sc-primary)); }}
.sc-series-line {{ transition: opacity 0.15s ease; }}
.sc-dimmed {{ opacity: 0.18; }}

.sc-inspector {{
  border: 1px solid var(--sc-border);
  border-radius: var(--sc-radius);
  background: var(--sc-card);
  padding: 12px 14px;
  margin-bottom: 10px;
}}
.sc-inspector.sc-previewing {{
  border-style: dashed;
  border-color: var(--sc-primary);
}}
.sc-insp-head {{
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 6px 10px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--sc-border);
}}
.sc-insp-title {{
  font-size: 13.5px;
  font-weight: 700;
}}
.sc-insp-sub {{
  font-family: var(--sc-mono);
  font-size: 11px;
  color: var(--sc-muted);
}}
.sc-insp-controls {{
  display: flex;
  align-items: center;
  gap: 6px;
}}
.sc-insp-state {{
  font-family: var(--sc-mono);
  font-size: 10.5px;
  color: var(--sc-muted);
}}
.sc-step-btn {{
  border: 1px solid var(--sc-border);
  background: var(--sc-secondary);
  color: var(--sc-fg);
  border-radius: 6px;
  padding: 2px 8px;
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}}
.sc-insp-body {{
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 12px 16px;
}}
.sc-insp-body.sc-single-col {{
  grid-template-columns: 1fr;
}}
@container (max-width: 540px) {{
  .sc-insp-body {{
    grid-template-columns: 1fr;
  }}
}}
.sc-insp-note {{
  font-size: 12px;
  padding: 6px 9px;
  border-radius: 6px;
  margin-bottom: 8px;
  background: var(--sc-warning-bg);
  border: 1px solid color-mix(in srgb, var(--sc-warning) 40%, transparent);
  color: var(--sc-fg);
}}
.sc-insp-sec {{
  font-family: var(--sc-mono);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--sc-muted);
  margin: 0 0 6px 0;
}}
.sc-bullets {{
  margin: 0;
  padding-left: 16px;
  font-size: 12.5px;
}}
.sc-bullets li {{
  margin-bottom: 4px;
}}
.sc-dim-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
}}
.sc-dim-table td {{
  padding: 3px 4px;
  vertical-align: middle;
}}
.sc-dim-bar-cell {{
  width: 72px;
}}
.sc-dim-track {{
  position: relative;
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: var(--sc-secondary);
  overflow: hidden;
}}
.sc-dim-fill {{
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  border-radius: 3px;
  background: var(--sc-primary);
}}
.sc-dim-gain {{
  position: absolute;
  top: 0;
  height: 100%;
  background: var(--sc-success);
  border-radius: 0 3px 3px 0;
}}
.sc-dim-loss {{
  position: absolute;
  top: 0;
  height: 100%;
  background: var(--sc-danger);
  opacity: 0.8;
  border-radius: 0 3px 3px 0;
}}
.sc-delta-up {{
  color: var(--sc-success);
  font-weight: 600;
}}
.sc-delta-down {{
  color: var(--sc-danger);
  font-weight: 600;
}}
.sc-delta-flat {{
  color: var(--sc-muted);
  opacity: 0.55;
}}
.sc-dim-num {{
  font-family: var(--sc-mono);
  text-align: right;
  white-space: nowrap;
}}
.sc-dim-total td {{
  border-top: 1px solid var(--sc-border);
  padding-top: 5px;
  font-weight: 700;
}}
.sc-hint {{
  font-size: 11px;
  color: var(--sc-muted);
  margin: 0 0 8px 0;
}}
.sc-kbd {{
  font-family: var(--sc-mono);
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid var(--sc-border);
  background: var(--sc-secondary);
}}
.sc-details summary {{
  cursor: pointer;
  font-size: 12px;
  color: var(--sc-muted);
  user-select: none;
}}
.sc-table-wrap {{
  overflow-x: auto;
  margin-top: 8px;
  border: 1px solid var(--sc-border);
  border-radius: var(--sc-radius);
}}
.sc-data-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
}}
.sc-data-table th, .sc-data-table td {{
  padding: 6px 8px;
  text-align: left;
  border-bottom: 1px solid var(--sc-border);
  white-space: nowrap;
}}
.sc-data-table th {{
  font-family: var(--sc-mono);
  font-size: 10.5px;
  color: var(--sc-muted);
  background: var(--sc-secondary);
}}
.sc-td-muted {{ color: var(--sc-muted); font-style: italic; }}
</style>
</head>
<body>
<div class="sc-root" id="sc-root">
  <header class="sc-head">
    <div>
      <div class="sc-title-row">
        <h1 class="sc-title">{escape(run['title'])}</h1>
        <span class="sc-run-id">{escape(run['skill'])} · {escape(run['id'])}</span>
      </div>
      <p class="sc-sub">Score by round · scale {fmt_score(run['scale']['min'], 0)}–{fmt_score(run['scale']['max'], 0)} (axis {fmt_score(y_lo, 0)}–{fmt_score(y_hi, 0)}) · {n_rounds} rounds · {len(reviewers)} reviewer{"s" if len(reviewers) != 1 else ""}</p>
    </div>
    <div class="sc-chips">{"".join(verdict_chips)}</div>
  </header>

  <div class="sc-legend" aria-label="Chart legend">
    <div class="sc-leg-group">{"".join(legend_items)}</div>
    <div class="sc-leg-cues">{"".join(legend_cues)}</div>
  </div>

  <div class="sc-chart-wrap">
    <svg class="sc-svg" viewBox="0 0 {svg_w:.1f} {svg_h:.1f}" role="img" aria-label="Review score line graph for {escape(run['title'])}">
      {"".join(svg_parts)}
    </svg>
  </div>

  <section class="sc-inspector" id="sc-inspector" aria-live="polite"></section>

  <p class="sc-hint">Hover or focus any score, gate, failure or recovery badge to preview its rationale and dimensions. Click or press <span class="sc-kbd">Enter</span> to pin, <span class="sc-kbd">←</span> <span class="sc-kbd">→</span> to step marks, <span class="sc-kbd">Esc</span> to reset.</p>

  <details class="sc-details">
    <summary>Score table ({n_rounds} rounds)</summary>
    <div class="sc-table-wrap">
      <table class="sc-data-table">
        <thead><tr><th>Round</th><th>Era</th><th>Target</th>{table_headers}<th>Gate</th><th>Status</th></tr></thead>
        <tbody>{"".join(table_rows)}</tbody>
      </table>
    </div>
  </details>
</div>

<script>
(() => {{
  const DATA = {payload_json};
  const marksById = new Map(DATA.marks.map(m => [m.id, m]));
  const markOrder = DATA.marks.map(m => m.id);
  const inspector = document.getElementById("sc-inspector");
  const svgMarks = Array.from(document.querySelectorAll(".sc-mark"));
  const revButtons = Array.from(document.querySelectorAll(".sc-leg-btn"));
  let pinnedId = DATA.defaultPin || (markOrder[0] || null);
  let activeId = pinnedId;
  let activeRev = null;

  function esc(s) {{
    return String(s).replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));
  }}

  function setRovingFocus(id) {{
    svgMarks.forEach(el => {{
      const isTarget = el.dataset.markId === id;
      el.setAttribute("tabindex", isTarget ? "0" : "-1");
      el.classList.toggle("sc-active", isTarget);
    }});
  }}

  function renderInspector(id, isPreview) {{
    const m = marksById.get(id);
    if (!m) return;
    activeId = id;
    setRovingFocus(id);
    inspector.classList.toggle("sc-previewing", Boolean(isPreview));
    const idx = markOrder.indexOf(id);
    const hasDims = Array.isArray(m.dimensions) && m.dimensions.length > 0;

    let noteHtml = "";
    if (m.retried && m.retry_note) {{
      noteHtml += `<div class="sc-insp-note"><strong>↻ Retried evaluation:</strong> ${{esc(m.retry_note)}}</div>`;
    }}
    if (m.era_note) {{
      noteHtml += `<div class="sc-insp-note">${{esc(m.era_note)}}</div>`;
    }}
    if (m.historical && m.kind !== "recovery") {{
      noteHtml += `<div class="sc-insp-note">Historical rubric era — not directly comparable to later revised contracts.</div>`;
    }}

    const bulletsHtml = (m.bullets || []).map(b => `<li>${{esc(b)}}</li>`).join("");
    let dimsHtml = "";
    if (hasDims) {{
      const hasWeights = m.dimensions.every(d => d.weight !== null && d.weight !== undefined);
      const hasAnyDelta = m.dimensions.some(d => d.delta !== null && d.delta !== undefined);
      let weightedSum = 0;
      const rows = m.dimensions.map(d => {{
        const curPct = Math.max(0, Math.min(100, (d.score / DATA.scaleMax) * 100));
        const hasPrev = d.prev_score !== null && d.prev_score !== undefined;
        const prevPct = hasPrev ? Math.max(0, Math.min(100, (d.prev_score / DATA.scaleMax) * 100)) : curPct;
        const delta = d.delta;
        let barInner = `<div class="sc-dim-fill" style="width:${{curPct.toFixed(1)}}%"></div>`;
        let deltaCell = "";
        if (hasAnyDelta) {{
          if (delta !== null && delta !== undefined && delta > 0) {{
            barInner = `<div class="sc-dim-fill" style="width:${{prevPct.toFixed(1)}}%"></div>`
              + `<div class="sc-dim-gain" style="left:${{prevPct.toFixed(1)}}%;width:${{(curPct - prevPct).toFixed(1)}}%"></div>`;
            deltaCell = `<td class="sc-dim-num sc-delta-up">+${{delta}}</td>`;
          }} else if (delta !== null && delta !== undefined && delta < 0) {{
            barInner = `<div class="sc-dim-fill" style="width:${{curPct.toFixed(1)}}%"></div>`
              + `<div class="sc-dim-loss" style="left:${{curPct.toFixed(1)}}%;width:${{(prevPct - curPct).toFixed(1)}}%"></div>`;
            deltaCell = `<td class="sc-dim-num sc-delta-down">−${{Math.abs(delta)}}</td>`;
          }} else {{
            deltaCell = `<td class="sc-dim-num sc-delta-flat">·</td>`;
          }}
        }}
        if (hasWeights) {{
          const pts = (d.score * d.weight) / 100;
          weightedSum += pts;
          return `<tr><td>${{esc(d.name)}}</td><td class="sc-dim-bar-cell"><div class="sc-dim-track">${{barInner}}</div></td><td class="sc-dim-num">${{d.score}}</td>${{deltaCell}}<td class="sc-dim-num">×${{d.weight}}%</td><td class="sc-dim-num">${{pts.toFixed(2)}}</td></tr>`;
        }}
        return `<tr><td>${{esc(d.name)}}</td><td class="sc-dim-bar-cell"><div class="sc-dim-track">${{barInner}}</div></td><td class="sc-dim-num">${{d.score}}</td>${{deltaCell}}</tr>`;
      }}).join("");
      const totalColspan = hasAnyDelta ? 5 : 4;
      const totalRow = hasWeights
        ? `<tr class="sc-dim-total"><td colspan="${{totalColspan}}">Weighted total</td><td class="sc-dim-num">${{weightedSum.toFixed(2)}}</td></tr>`
        : "";
      dimsHtml = `<div><div class="sc-insp-sec">Component dimensions</div><table class="sc-dim-table"><tbody>${{rows}}${{totalRow}}</tbody></table></div>`;
    }}

    inspector.innerHTML = `
      <div class="sc-insp-head">
        <div>
          <div class="sc-insp-title">${{esc(m.title)}}</div>
          <div class="sc-insp-sub">${{esc(m.subtitle)}}${{m.reviewer_label && m.kind === "gate" ? " · " + esc(m.reviewer_label) : ""}}</div>
        </div>
        <div class="sc-insp-controls">
          <span class="sc-insp-state">${{isPreview ? "Preview" : "Pinned"}} · ${{idx + 1}}/${{markOrder.length}}</span>
          <button type="button" class="sc-step-btn" data-step="-1" aria-label="Previous mark">‹</button>
          <button type="button" class="sc-step-btn" data-step="1" aria-label="Next mark">›</button>
        </div>
      </div>
      ${{noteHtml}}
      <div class="sc-insp-body ${{hasDims ? "" : "sc-single-col"}}">
        <div>
          <div class="sc-insp-sec">${{m.kind === "failure" || m.kind === "incomplete" ? "Failure details" : (m.kind === "recovery" ? "Recovery details" : "How the score was reached")}}</div>
          <ul class="sc-bullets">${{bulletsHtml}}</ul>
        </div>
        ${{dimsHtml}}
      </div>
    `;
    inspector.querySelectorAll(".sc-step-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        const delta = Number(btn.dataset.step);
        const nextIdx = (markOrder.indexOf(activeId) + delta + markOrder.length) % markOrder.length;
        pinnedId = markOrder[nextIdx];
        renderInspector(pinnedId, false);
      }});
    }});
  }}

  svgMarks.forEach(el => {{
    const id = el.dataset.markId;
    el.addEventListener("mouseenter", () => renderInspector(id, id !== pinnedId));
    el.addEventListener("mouseleave", () => {{ if (pinnedId) renderInspector(pinnedId, false); }});
    el.addEventListener("focus", () => renderInspector(id, id !== pinnedId));
    el.addEventListener("click", () => {{
      pinnedId = id;
      renderInspector(pinnedId, false);
    }});
    el.addEventListener("keydown", e => {{
      const cur = markOrder.indexOf(id);
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {{
        e.preventDefault();
        const nextId = markOrder[(cur + 1) % markOrder.length];
        const target = svgMarks.find(x => x.dataset.markId === nextId);
        renderInspector(nextId, nextId !== pinnedId);
        if (target) target.focus();
      }} else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {{
        e.preventDefault();
        const prevId = markOrder[(cur - 1 + markOrder.length) % markOrder.length];
        const target = svgMarks.find(x => x.dataset.markId === prevId);
        renderInspector(prevId, prevId !== pinnedId);
        if (target) target.focus();
      }} else if (e.key === "Enter" || e.key === " ") {{
        e.preventDefault();
        pinnedId = id;
        renderInspector(pinnedId, false);
      }} else if (e.key === "Escape") {{
        e.preventDefault();
        pinnedId = DATA.defaultPin || markOrder[0];
        renderInspector(pinnedId, false);
      }}
    }});
  }});

  function applyRevFilter(revId) {{
    activeRev = revId;
    revButtons.forEach(btn => {{
      const match = revId && btn.dataset.revFilter === revId;
      btn.setAttribute("aria-pressed", match ? "true" : "false");
      btn.classList.toggle("sc-dim", Boolean(revId && !match));
    }});
    document.querySelectorAll(".sc-series-line, .sc-score-mark").forEach(el => {{
      const match = !revId || el.dataset.reviewer === revId;
      el.classList.toggle("sc-dimmed", !match);
    }});
  }}

  revButtons.forEach(btn => {{
    const rid = btn.dataset.revFilter;
    btn.addEventListener("click", () => applyRevFilter(activeRev === rid ? null : rid));
  }});

  if (pinnedId) renderInspector(pinnedId, false);
}})();
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a score-based iterative review ledger to self-contained inline HTML."
    )
    parser.add_argument("ledger", help="Path to the JSON score ledger file.")
    parser.add_argument("--output", "-o", required=True, help="Path to write the rendered HTML file.")
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger)
    output_path = Path(args.output)
    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        html_out = render_html(raw)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
