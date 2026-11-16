#!/usr/bin/env python3
"""Render a private plan ledger to self-contained HTML; Python 3.10+ stdlib."""
import argparse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from html import escape
import json
import math
import re
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

KINDS = {"build", "review"}
STATUSES = {"planned", "ready", "running", "review", "blocked", "done", "cancelled"}
IDENTITY = ("provider", "model", "effort")
METRICS = ("tokens", "turns", "usd")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def timestamp(value):
    """Normalize before subtraction so DST never changes elapsed durations."""
    require(isinstance(value, str), "timestamp must be an ISO 8601 string with offset")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.utcoffset() is not None, "timestamp needs a UTC offset")
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"invalid timestamp {value!r}: {exc}") from exc


def display_time(value):
    return timestamp(value).astimezone(ZoneInfo("Australia/Sydney")).strftime(
        "%d %b %Y %H:%M")


def text_fields(record, fields, label):
    require(isinstance(record, dict), f"{label} must be an object")
    for field in fields:
        require(isinstance(record.get(field), str) and record[field].strip(),
                f"{label}.{field} must be nonempty text")


def number(value, label, integer=False):
    require(type(value) in ((int,) if integer else (int, float))
            and math.isfinite(value) and value >= 0, f"{label} must be a finite nonnegative number")


def interval(record, label, as_of=None):
    start = timestamp(record.get("start"))
    end = timestamp(record["end"]) if record.get("end") is not None else as_of
    require(end is not None, f"{label}.end is required")
    require(end >= start, f"{label} ends before it starts")
    return start, end


def baseline(record, label):
    require(isinstance(record, dict), f"{label} must be an object")
    timestamp(record.get("start"))
    number(record.get("review_rounds"), f"{label}.review_rounds", integer=True)
    allocations = record.get("allocations")
    require(isinstance(allocations, list) and allocations, f"{label}.allocations must be nonempty")
    for allocation in allocations:
        text_fields(allocation, (*IDENTITY, "kind"), f"{label}.allocation")
        require(allocation.get("kind") in KINDS, f"{label}.allocation.kind must be build or review")
        number(allocation.get("minutes"), f"{label}.allocation.minutes")


def validate_cost(cost, label):
    require(isinstance(cost, dict), f"{label} must be an object")
    require(set(cost) <= set(METRICS), f"{label}: unknown cost metric")
    for metric, observation in cost.items():
        if observation == "unknown":
            continue
        text_fields(observation, ("source", "basis"), f"{label}.{metric}")
        number(observation.get("value"), f"{label}.{metric}.value", integer=metric != "usd")
        require(observation["basis"] in {"reported", "host-estimate"},
                f"{label}.{metric}.basis must be reported or host-estimate")


def validate(data):
    require(isinstance(data, dict) and type(data.get("version")) is int and data["version"] == 1,
            "ledger version must be 1")
    project = data.get("project")
    text_fields(project, ("name", "status", "timezone"), "project")
    require(project["timezone"] == "Australia/Sydney", "project.timezone must be Australia/Sydney")
    start, now = timestamp(project.get("start")), timestamp(project.get("as_of"))
    require(now >= start, "project.as_of precedes run start")
    approval = data.get("approval")
    if approval is not None:
        text_fields(approval, ("approver",), "approval")
        require(timestamp(approval.get("at")) <= now, "approval is after as_of")
    tasks = data.get("tasks")
    require(isinstance(tasks, list) and tasks, "tasks must be a nonempty list")
    by_id = {}
    for task in tasks:
        text_fields(task, ("id", "title", "stream", "status"), "task")
        if 'value' in task:
            text_fields(task, ('value',), 'task')
        if 'thread' in task:
            text_fields(task, ('thread',), 'task')
            require(LINK.fullmatch(task['thread']), f"{task['id']}.thread must be a link such as https://… or t3-thread://…")
        tid = task["id"]
        require(tid not in by_id, f"duplicate task id: {tid}")
        by_id[tid] = task
        require(task["status"] in STATUSES, f"{tid}: invalid status")
        text_fields(task.get("owner"), IDENTITY, f"{tid}.owner")
        deps = task.get("dependencies")
        require(isinstance(deps, list) and all(isinstance(x, str) for x in deps),
                f"{tid}.dependencies must be task ids")
        require(len(deps) == len(set(deps)), f"{tid}: duplicate dependency")
        for ref in ("issues", "prs"):
            require(isinstance(task.get(ref, []), list)
                    and all(isinstance(x, str) for x in task.get(ref, [])), f"{tid}.{ref} must be text list")
        if approval:
            require(task.get("baseline") is not None, f"{tid}: missing approved baseline")
        if task.get("baseline") is not None:
            baseline(task["baseline"], f"{tid}.baseline")
        require(isinstance(task.get("forecast"), dict), f"{tid}.forecast must be an object")
        interval(task["forecast"], f"{tid}.forecast")
        segments = task.get("segments")
        require(isinstance(segments, list), f"{tid}.segments must be a list")
        ids = set()
        for segment in segments:
            text_fields(segment, ("id", "host_id", "kind", *IDENTITY), f"{tid}.segment")
            require(segment["id"] not in ids, f"{tid}: duplicate segment id")
            ids.add(segment["id"])
            require(segment.get("kind") in KINDS, f"{tid}: segment kind must be build or review")
            number(segment.get("round"), f"{tid}.segment.round", integer=True)
            require(segment["kind"] != "review" or segment["round"] >= 1,
                    f"{tid}: review round must be positive")
            a, b = interval(segment, f"{tid}.segment", now)
            require(start <= a <= b <= now, f"{tid}: segment outside observed run")
            require(task["status"] not in {"done", "cancelled"} or segment.get("end") is not None,
                    f"{tid}: terminal task has an open segment")
            validate_cost(segment.get("cost", {}), f"{tid}.segment.cost")
        validate_cost(task.get("cost", {}), f"{tid}.cost")
        # A task total and its segment totals may cover the same consumption.
        for metric in METRICS:
            require(task.get("cost", {}).get(metric, "unknown") == "unknown"
                    or all(s.get("cost", {}).get(metric, "unknown") == "unknown" for s in segments),
                    f"{tid}: {metric} supplied at both task and segment scope")
    dependency_order(tasks)
    for collection in ("milestones", "events", "needs_owner", "decisions", "rebaselines"):
        require(isinstance(data.get(collection, []), list), f"{collection} must be a list")
    marker_ids = set()
    for marker in data.get("milestones", []):
        text_fields(marker, ("id", "name", "status", "kind"), "milestone")
        require(marker["id"] not in marker_ids, "duplicate milestone id")
        marker_ids.add(marker["id"])
        require(marker["kind"] in {"milestone", "gate"}, "marker kind must be milestone or gate")
        timestamp(marker.get("target"))
        require(isinstance(marker.get("required_reviewers"), list)
                and all(isinstance(x, str) for x in marker["required_reviewers"]), "required_reviewers must be text list")
        require(isinstance(marker.get("tasks"), list)
                and all(isinstance(x, str) and x in by_id for x in marker["tasks"]), "milestone has unknown task id")
    for event in data.get("events", []):
        text_fields(event, ("kind", "note", "source"), "event")
        a, b = interval(event, "event", now)
        require(start <= a <= now, "event start outside observed run")
        scope = event.get("scope")
        require(isinstance(scope, dict) and len(scope) == 1, "event scope needs all, provider or tasks")
        require(scope == {"all": True}
                or (set(scope) == {"provider"} and isinstance(scope["provider"], str) and bool(scope["provider"]))
                or (set(scope) == {"tasks"} and isinstance(scope["tasks"], list)
                    and bool(scope["tasks"]) and all(isinstance(x, str) and x in by_id for x in scope["tasks"])), "invalid event scope")
    for collection in ('needs_owner', 'decisions'):
        for item in data.get(collection, []):
            text_fields(item, ("question", "owner", "status"), f"{collection} item")
            require(isinstance(item.get("tasks"), list)
                    and all(isinstance(x, str) and x in by_id for x in item["tasks"]), f"{collection} has unknown task id")
            for field in ('answer','rationale','source','recommendation','id'):
                if field in item:
                    text_fields(item, (field,), f'{collection} item')
            for field in ('asked_at','decided_at'):
                if item.get(field, 'unknown') != 'unknown':
                    require(timestamp(item[field]) <= now, f'{collection}.{field} is after as_of')
            if item.get('asked_at','unknown') != 'unknown' and item.get('decided_at','unknown') != 'unknown':
                require(timestamp(item['decided_at']) >= timestamp(item['asked_at']), 'decision precedes question')
            if collection == 'decisions':
                text_fields(item, ('id',), 'decision')
                require(item['status'] in {'pending','decided'}, 'decision status must be pending or decided')
                answered = item.get('answer','unknown') != 'unknown'
                require(answered == (item['status']=='decided'), 'decided record needs an actual answer; pending answer must be unknown')
                require(item['status']=='decided' or item.get('decided_at','unknown')=='unknown', 'pending decision cannot have decided_at')
    last = start
    for change in data.get("rebaselines", []):
        text_fields(change, ("reason", "approver"), "rebaseline")
        at = timestamp(change.get("at"))
        require(approval is not None and timestamp(approval["at"]) <= at <= now and at >= last,
                "rebaseline must follow approval, be chronological and not after as_of")
        last = at
        require(isinstance(change.get("tasks"), dict) and change["tasks"], "rebaseline.tasks must be nonempty")
        for tid, replacement in change["tasks"].items():
            require(tid in by_id, f"rebaseline: unknown task id {tid}")
            baseline(replacement, f"rebaseline.{tid}")
    return data


def baseline_end(plan):
    return timestamp(plan["start"]) + timedelta(minutes=sum(a["minutes"] for a in plan["allocations"]))


def segment_minutes(segment, as_of):
    a, b = interval(segment, "segment", timestamp(as_of))
    return (b - a).total_seconds() / 60


def dependency_order(tasks):
    """Topological order without a recursion-depth limit on long runs."""
    counts = {t["id"]: len(t["dependencies"]) for t in tasks}
    children = defaultdict(list)
    for task in tasks:
        for dep in task["dependencies"]:
            require(dep in counts, f"unknown dependency id: {dep}")
            children[dep].append(task["id"])
    ready = deque(tid for tid, count in counts.items() if not count)
    order = []
    while ready:
        tid = ready.popleft()
        order.append(tid)
        for child in children[tid]:
            counts[child] -= 1
            if not counts[child]:
                ready.append(child)
    require(len(order) == len(tasks), "dependency cycle")
    return order


def task_end(task, as_of):
    if task["status"] in {"done", "cancelled"} and task["segments"]:
        return max(timestamp(s["end"]) for s in task["segments"])
    return max(timestamp(task["forecast"]["end"]), timestamp(as_of))


def critical_path(data):
    """Longest remaining dependency chain, weighted by forecast wall minutes."""
    tasks = {t["id"]: t for t in data["tasks"]}
    now, memo = timestamp(data["project"]["as_of"]), {}

    for tid in dependency_order(data["tasks"]):
        task = tasks[tid]
        if task["status"] in {"done", "cancelled"}:
            memo[tid] = (0, [])
            continue
        previous = max((memo[dep] for dep in task["dependencies"]), default=(0, []), key=lambda x: x[0])
        duration = max(0, (timestamp(task["forecast"]["end"]) - max(now, timestamp(task["forecast"]["start"]))).total_seconds())
        memo[tid] = (previous[0] + duration, previous[1] + [tid])
    return max(memo.values(), default=(0, []), key=lambda x: (x[0], len(x[1])))[1]


def event_affects(event, task):
    scope = event["scope"]
    providers = {task["owner"]["provider"]} | {s["provider"] for s in task["segments"]}
    return (scope.get("all") is True or task["id"] in scope.get("tasks", [])
            or scope.get("provider") in providers)


def decision_records(data):
    """Keep appended history; only the last snapshot per question is current."""
    records = []
    for index, item in enumerate(data.get('needs_owner', [])):
        record = dict(item, id=item.get('id', f'legacy-{index+1}'))
        resolved = item['status'] in {'done','decided','closed','answered','resolved','cancelled'}
        record['status'] = ('decided' if item.get('answer','unknown')!='unknown' else 'unknown') if resolved else 'pending'
        records.append(record)
    records.extend(dict(item) for item in data.get('decisions', []))
    latest = {record['id']: index for index,record in enumerate(records)}
    return [(record, latest[record['id']]==index) for index,record in enumerate(records)]


def cost_totals(data):
    """Return sourced known subtotals and missing observations, never assumed zero."""
    totals = defaultdict(lambda: {metric: {"known": 0, "missing": 0, "sources": [], "estimated": False}
                                  for metric in METRICS})
    for task in data["tasks"]:
        for metric in METRICS:
            task_value = task.get("cost", {}).get(metric, "unknown")
            observations = [(task["owner"], task_value)] if task_value != "unknown" else [
                (segment, segment.get("cost", {}).get(metric, "unknown")) for segment in task["segments"]]
            if not observations:
                observations = [(task["owner"], "unknown")]
            # Task totals cannot be attributed across multiple actual identities.
            models = {(s["provider"], s["model"]) for s in task["segments"]}
            if task_value != "unknown" and len(models) > 1:
                observations = [({"provider": "unattributed", "model": "task total"}, task_value)]
            elif task_value != "unknown" and len(models) == 1:
                provider, model = next(iter(models))
                observations = [({"provider": provider, "model": model}, task_value)]
            for identity, observation in observations:
                row = totals[(identity["provider"], identity["model"])][metric]
                if observation == "unknown":
                    row["missing"] += 1
                else:
                    row["known"] += observation["value"]
                    row["sources"].append(observation["source"])
                    row["estimated"] |= observation["basis"] == "host-estimate"
    return dict(totals)


def calibration(data):
    """Completed tasks only; a changed identity invalidates that task/kind pair."""
    grouped, comparisons, rounds = {}, [], []
    for task in data["tasks"]:
        if task["status"] != "done" or task.get("baseline") is None:
            continue
        plan = task["baseline"]
        rounds.append({"task": task["id"], "planned": plan["review_rounds"],
                       "actual": len({s["round"] for s in task["segments"] if s["kind"] == "review"})})
        for kind in sorted(KINDS):
            estimated, actual = defaultdict(float), defaultdict(float)
            for allocation in plan["allocations"]:
                if allocation["kind"] == kind:
                    estimated[tuple(allocation[x] for x in IDENTITY)] += allocation["minutes"]
            for segment in task["segments"]:
                if segment["kind"] == kind:
                    actual[tuple(segment[x] for x in IDENTITY)] += segment_minutes(segment, data["project"]["as_of"])
            if not estimated and not actual:
                continue
            comparable = (bool(data.get("approval")) and set(estimated) == set(actual)
                          and all("unknown" not in identity for identity in estimated))
            comparisons.append({"task": task["id"], "kind": kind, "comparable": comparable,
                                "estimated_minutes": sum(estimated.values()), "actual_minutes": sum(actual.values())})
            if not comparable:
                continue
            for identity, minutes in estimated.items():
                key = (*identity, kind)
                row = grouped.setdefault(key, {"estimated_minutes": 0, "actual_minutes": 0})
                row["estimated_minutes"] += minutes
                row["actual_minutes"] += actual[identity]
    for row in grouped.values():
        row["ratio"] = row["actual_minutes"] / row["estimated_minutes"] if row["estimated_minutes"] else None
    return {"groups": grouped, "comparisons": comparisons, "rounds": rounds, "costs": cost_totals(data)}


CSS = """
:root{color-scheme:light dark;font-family:var(--font-sans,Arial,sans-serif)}
html,body{margin:0;padding:0;background:transparent}
*{box-sizing:border-box}body{font-size:13px;line-height:1.5}
.report{--paper:#edf2f7;--panel:#fff;--ink:#192d45;--quiet:#536579;--line:#bdcad8;
--red:#a62b46;--amber:#805400;--wash:#fff3d2;--ghost:#dbe4ed;--link:#275f8e;
background:var(--paper);color:var(--ink);border-radius:12px;padding:16px;min-width:0;overflow-wrap:anywhere}
.report.dark{--paper:#172334;--panel:#202e40;--ink:#e5edf7;--quiet:#b0bfd1;--line:#536579;
--red:#ff9eae;--amber:#f3cb76;--wash:#3c3322;--ghost:#34475b;--link:#9ccaff}
@media(prefers-color-scheme:dark){.report.auto{--paper:#172334;--panel:#202e40;--ink:#e5edf7;--quiet:#b0bfd1;--line:#536579;--red:#ff9eae;--amber:#f3cb76;--wash:#3c3322;--ghost:#34475b;--link:#9ccaff}}
h1{font-size:29px;line-height:1.2;letter-spacing:-.7px;margin:8px 0}h2{font-size:17px;margin:0 0 10px}
h3{font-size:14px;margin:12px 0 6px}p{margin:6px 0}a{color:var(--link)}small,.muted{color:var(--quiet);font-size:11px}
header{padding-bottom:16px;border-bottom:1px solid var(--line)}.topline,.key{display:flex;gap:8px 16px;flex-wrap:wrap;align-items:center}
.facts{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}.facts strong{display:block;font-size:11px;color:var(--quiet)}
.critical{grid-column:1/-1;border-left:3px solid var(--red);padding-left:10px}.critical a,.critical .task-ref{display:inline-block;padding:1px 5px;border:1px solid var(--line);border-radius:3px;margin:2px}
section{padding-top:22px}.chip{display:inline-block;border:1px solid var(--line);padding:1px 5px;border-radius:4px;font-size:10px;font-weight:650;background:var(--panel)}
.chip.running,.chip.review{border-color:var(--link);color:var(--link)}.chip.blocked,.chip.ready,.chip.planned{color:var(--amber);border-color:var(--amber)}
.decision-strip{padding:10px 12px;border:1.5px solid var(--amber);border-radius:4px;background:var(--wash);margin-top:14px}
.decision-strip p+p{border-top:1px solid var(--line);padding-top:8px}
.progress{margin-top:16px}.progress p{margin:0 0 6px}.progress strong{font-size:20px;font-variant-numeric:tabular-nums}
.pbar{display:flex;height:12px}.pbar i{display:block;height:100%;width:var(--w)}.pbar .done{background:var(--ink)}
.pbar .active{background:repeating-linear-gradient(135deg,var(--ink) 0 2px,transparent 2px 5px);border:1px solid var(--ink)}
.pbar .todo{flex:1;width:auto;border:1px solid var(--line);background:var(--ghost)}
.plabels{display:flex;font-size:11px;color:var(--quiet);margin-top:3px}.plabels span{min-width:var(--w);padding-right:12px;white-space:nowrap}
.key{font-size:11px;margin:14px 0}.key i{display:inline-block;width:18px;height:10px;vertical-align:middle;margin-right:4px}
.swatch{background:var(--c)}.review-key{background:var(--quiet);background-image:repeating-linear-gradient(135deg,transparent 0 3px,var(--paper) 3px 5px)}.projection-key{border:1.5px dashed var(--quiet)}
.chart-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--panel)}
.chart{--label:232px;--cost:58px;min-width:620px;padding:0 12px 10px;font-size:12px;line-height:1.35}
.chart-row{display:grid;grid-template-columns:var(--label) minmax(0,1fr) var(--cost);align-items:start;min-height:22px;position:relative;z-index:1}
.label{position:sticky;left:0;z-index:6;background:var(--panel);padding-right:8px;line-height:22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.label a{color:inherit;text-decoration:underline;text-decoration-color:var(--quiet);text-underline-offset:2px}
.label small{font-weight:400}.status{display:inline-block;width:15px;font-size:10px;color:var(--quiet)}
.task-row.running .status,.task-row.review .status{color:var(--ink)}
.track{position:relative;height:calc(22px + var(--lanes,0)*14px)}
.cost{line-height:22px;text-align:right;font-size:11px;font-variant-numeric:tabular-nums;white-space:nowrap;background:var(--panel)}
.plot{position:relative}.grid{position:absolute;top:0;bottom:0;left:var(--label);right:var(--cost);pointer-events:none}
.grid i{position:absolute;top:0;bottom:0;left:var(--x)}.gridline{border-left:1px solid var(--line);opacity:.55}
.cut{width:var(--w);background:repeating-linear-gradient(135deg,transparent 0 3px,var(--line) 3px 4px)}
.far{width:var(--w);background:var(--ghost);opacity:.5}.now{border-left:1.5px solid var(--ink)}
.bar{position:absolute;left:var(--x);width:var(--w);top:calc(5px + var(--lane,0)*14px);height:11px;background:var(--c);min-width:2px}
.bar.review{background-image:repeating-linear-gradient(135deg,transparent 0 3px,var(--panel) 3px 5px)}
.bar.open{box-shadow:1px 0 0 1px var(--ink)}.bar.projection{background-color:transparent;border:1.5px dashed var(--c)}
.bar.review.projection{background-color:color-mix(in srgb,var(--c) 45%,transparent)}
.note,.eta{position:absolute;top:4px;font-size:10px;color:var(--quiet);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.marker{position:absolute;left:var(--x);top:11px;width:8px;height:8px;transform:translate(-50%,-50%) rotate(45deg);border:1.5px solid var(--ink);background:var(--panel);z-index:3}
.marker.gate{background:var(--ink)}.group{border-top:1px solid var(--line);margin-top:4px}.group .label,.group .cost{font-weight:650}
.axis .track{height:30px}.tick{position:absolute;left:var(--x);top:14px;font-size:10px;color:var(--quiet);transform:translateX(-50%);white-space:nowrap}
.tick.top{top:0}.tick.nowtick{color:var(--ink);font-weight:650}.axis .label,.axis .cost{color:var(--quiet);font-size:11px;line-height:30px}
.total{border-top:1.5px solid var(--ink);margin-top:6px;padding-top:3px}.total .label{font-weight:650}.total .cost{font-weight:650;font-size:13px}
.split{position:absolute;left:0;top:5px;height:11px;width:36%;display:flex}.split i{height:100%;width:var(--w);background:var(--c)}
.total .note{left:calc(36% + 8px);font-size:11px}.total .note.plain{left:0}.chart-note{font-size:11px;color:var(--quiet);margin-top:8px}
.tables{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 24px}.wide{grid-column:1/-1}.table-scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;text-align:left;font-size:12px}th{font-size:10px;color:var(--quiet);font-weight:500}td,th{padding:8px 8px 8px 0;border-bottom:1px solid var(--line);vertical-align:top}td small{display:block}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}.ratio-plot{min-width:120px;position:relative;height:14px;background:var(--ghost)}.ratio-bar{display:block;height:100%;width:var(--w);background:var(--link)}
.ratio-one{position:absolute;left:var(--one);top:-3px;bottom:-3px;border-left:2px solid #101820;box-shadow:1px 0 #fff,-1px 0 #fff}details{margin:0}summary{cursor:pointer;font-weight:650;padding:8px 0;border-bottom:1px solid var(--line)}summary h2{display:inline;font-size:17px;margin:0}summary:focus-visible{outline:2px solid var(--link);outline-offset:3px}.section-body{padding-top:10px}footer{font-size:11px;color:var(--quiet);border-top:1px solid var(--line);margin-top:22px;padding-top:10px}
@media(max-width:600px){.facts,.tables{grid-template-columns:minmax(0,1fr)}h1{font-size:24px}.report{padding:12px}.table-scroll table{min-width:450px}.chart{--label:150px}}
"""

SCRIPT = """
function revealTarget(hash){let target;try{target=document.getElementById(decodeURIComponent(hash.slice(1)));}catch{return;}
 if(!target)return;let revealed=false;for(let node=target.parentElement;node;node=node.parentElement){if(node.tagName==='DETAILS'&&!node.open){node.open=true;revealed=true;}}
 const detail=target.firstElementChild;if(target.tagName==='SECTION'&&detail&&detail.tagName==='DETAILS'&&!detail.open){detail.open=true;revealed=true;}
 if(revealed)requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));}
document.querySelectorAll('.report a[href^="#"]').forEach(link=>link.addEventListener('click',()=>revealTarget(link.hash)));
window.addEventListener('hashchange',()=>revealTarget(location.hash));
window.addEventListener('load',()=>revealTarget(location.hash));
"""

# Provider families: light-theme shades, then dark-theme shades. Hue names the
# provider; shade separates that provider's models.
FAMILIES = {
    "orange": (("#d4502a", "#a61e4d", "#b8690b", "#7c2d12"), ("#ff8a5c", "#ff7a98", "#f5b041", "#ffc9a8")),
    "green": (("#1f8a5b", "#4d7c0f", "#0f766e", "#166534"), ("#4ade80", "#a3e635", "#2dd4bf", "#86efac")),
    "blue": (("#2f6fd6", "#1e40af", "#0e7490", "#4f46e5"), ("#7fb0ff", "#a5b4fc", "#67d8ef", "#bfdbfe")),
    "purple": (("#7c3aed", "#a21caf", "#6d28d9", "#86198f"), ("#c4a1ff", "#f0a6f5", "#d8b4fe", "#e879f9")),
    "slate": (("#475569", "#1f2937", "#64748b", "#334155"), ("#cbd5e1", "#94a3b8", "#e2e8f0", "#a8b3c4")),
    "teal": (("#0d7d87", "#155e75", "#0f766e", "#134e4a"), ("#46c7cf", "#7dd3fc", "#5eead4", "#a5f3fc")),
    "pink": (("#be185d", "#9d174d", "#c026a3", "#831843"), ("#f9a8d4", "#fb7fb5", "#f0abfc", "#fbcfe8")),
}
FAMILY_HINTS = (("orange", ("anthropic", "claude")), ("green", ("openai", "codex", "gpt")),
                ("blue", ("deepseek",)), ("purple", ("google", "gemini")), ("slate", ("xai", "grok")))
SPARE_FAMILIES = ("teal", "pink", "purple", "slate", "blue", "green", "orange")
SYDNEY = ZoneInfo("Australia/Sydney")
TERMINAL = {"done", "cancelled"}
ACTIVE = {"running", "review"}
REFERENCE = re.compile(r"(?<![&\w])#\d+")
LINK = re.compile(r"[a-z][a-z0-9+.-]*://\S+")
CUT_MINUTES, FAR_SHARE, TICK_STEPS = 60, 0.22, (15, 30, 60, 120, 180, 360, 720, 1440)


def esc(value):
    return escape(str(value), quote=True)


def fmt(value):
    return f"{value:g}"


STATUS_SYMBOLS = {"done": "✓", "running": "▶", "review": "▶", "blocked": "⊘", "planned": "◷",
                  "ready": "◷", "cancelled": "×"}


def chip(status):
    css = status if status in STATUSES else "planned"
    return f'<span class="chip {css}">{STATUS_SYMBOLS.get(status, "◷")} {esc(status)}</span>'


def section_html(title, body, section_id, wide=False, collapsed=True):
    heading = f'<h2>{esc(title)}</h2>'
    if collapsed:
        body = f'<details><summary>{heading}</summary><div class="section-body">{body}</div></details>'
    else:
        body = heading + body
    return f'<section id="{section_id}" class="{"wide" if wide else ""}">{body}</section>'


def table(title, headers, rows, section_id, wide=False, note=None):
    content = ''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows)
    if not content:
        return ''
    body = ('<div class="table-scroll"><table><thead><tr>' +
            ''.join(f'<th scope="col">{esc(h)}</th>' for h in headers) +
            f'</tr></thead><tbody>{content}</tbody></table></div>')
    if note:
        body += f'<p class="muted">{esc(note)}</p>'
    return section_html(title, body, section_id, wide)


def identity_label(item):
    return f'{esc(item["model"])} · {esc(item["effort"])}<small>{esc(item["provider"])}</small>'


def decision_table(records):
    def observed_time(value):
        return 'unknown' if value == 'unknown' else display_time(value)

    rows = []
    for record, current in records:
        state = {'pending':'Awaiting answer', 'decided':'Decided', 'unknown':'Answer not recorded'}[record['status']]
        if not current:
            state = 'Earlier decision' if record['status']=='decided' else 'Earlier question'
        question = f'{esc(record["id"])} · {esc(record["question"])}<small>{esc(record["owner"])}</small>'
        if record.get('recommendation'):
            question += f'<small>Recommendation: {esc(record["recommendation"])}</small>'
        answer = esc(record.get('answer','unknown'))
        if record.get('rationale'):
            answer += f'<small>{esc(record["rationale"])}</small>'
        times = f'Asked: {esc(observed_time(record.get("asked_at","unknown")))}<small>Decided: {esc(observed_time(record.get("decided_at","unknown")))}</small>'
        affected = esc(', '.join(record['tasks'])) + f'<small>Source: {esc(record.get("source","unknown"))}</small>'
        rows.append([question, state, answer, times, affected])
    return table('Decision record', ['Question / owner','Record','Actual answer / rationale','Asked / decided','Affected work / source'], rows, 'owner', True,
                 note='The coordinator asks through the host input tool and records actual replies here. Pending records are not decisions; recommendations are not answers. Earlier records remain in the history.')


def projection(task, now):
    if task["status"] in {"done", "cancelled"}:
        return []
    a, b = max(now, timestamp(task["forecast"]["start"])), timestamp(task["forecast"]["end"])
    if b <= a:
        return []
    allocations = task.get("baseline", {}).get("allocations", [dict(kind="build", minutes=1, **task["owner"])])
    if task["status"] == "review" or any(s["kind"] == "review" and s.get("end") is None for s in task["segments"]):
        allocations = [x for x in allocations if x["kind"] == "review"]
    total = sum(x["minutes"] for x in allocations)
    duration = b-a
    output = []
    for index, allocation in enumerate(allocations):
        end = a + duration * allocation["minutes"] / total if total else a + duration/len(allocations)
        item = dict(allocation, start=a.isoformat(), end=min(end, b).isoformat(),
                    round=max([s["round"] for s in task["segments"] if s["kind"] == "review"] or [1]) if allocation["kind"] == "review" else 0,
                    id=f"forecast-{index}")
        if item["kind"] == "build":  # whoever is building now keeps building
            builder = next((s for s in reversed(task["segments"]) if s["kind"] == "build"), task["owner"])
            item.update({field: builder[field] for field in IDENTITY})
        output.append(item)
        a = min(end, b)
    return output


def segment_rows(task, now):
    """Pack actual intervals without closing gaps or covering concurrent work."""
    entries = [(s, False, f'a{i}') for i, s in enumerate(task['segments'])]
    entries += [(s, True, f'f{i}') for i, s in enumerate(projection(task, now))]
    entries.sort(key=lambda entry: (*interval(entry[0], 'segment', now), entry[2]))
    rows, ends = [], []
    for entry in entries:
        start, end = interval(entry[0], 'segment', now)
        row = next((i for i, finish in enumerate(ends) if finish <= start), len(rows))
        if row == len(rows):
            rows.append([])
            ends.append(end)
        rows[row].append(entry)
        ends[row] = end
    return rows


def model_palette(identities):
    """Give each provider family a hue and each of its models a shade."""
    def hinted(text):
        return next((family for family, words in FAMILY_HINTS if any(word in text.lower() for word in words)), None)

    families = {key: hinted(key[1]) or hinted(key[0]) for key in identities}
    free = [family for family in SPARE_FAMILIES if family not in families.values()] or list(SPARE_FAMILIES)
    spare, shades, names, light, dark = {}, defaultdict(int), {}, '', ''
    for index, key in enumerate(sorted(identities)):
        family = families[key] or spare.setdefault(key[0], free[len(spare) % len(free)])
        shade = shades[family] % 4
        shades[family] += 1
        names[key] = f'var(--m{index})'
        light += f'--m{index}:{FAMILIES[family][0][shade]};'
        dark += f'--m{index}:{FAMILIES[family][1][shade]};'
    css = f'.report{{{light}}}.report.dark{{{dark}}}@media(prefers-color-scheme:dark){{.report.auto{{{dark}}}}}'
    return names, css


def short_clock(at, now):
    local, reference = at.astimezone(SYDNEY), now.astimezone(SYDNEY)
    days = abs((local.date() - reference.date()).days)
    return f'{local:%H:%M}' if not days else f'{local:%a %H:%M}' if days < 7 else f'{local:%d %b %H:%M}'


def span_text(minutes):
    return f'{round(minutes)}m' if minutes < 90 else f'{minutes/60:.1f}h'


def task_weight(task):
    """Estimated wall minutes: the approved baseline, else the current forecast."""
    if task.get("baseline"):
        return sum(a["minutes"] for a in task["baseline"]["allocations"])
    a, b = interval(task["forecast"], "forecast")
    return (b - a).total_seconds() / 60


def task_tokens(task):
    """Known tokens by (provider, model) and the count of unreported observations."""
    whole = task.get("cost", {}).get("tokens", "unknown")
    models = {(s["provider"], s["model"]) for s in task["segments"]}
    if whole != "unknown":
        key = (next(iter(models)) if len(models) == 1 else ("unattributed", "task total") if models
               else (task["owner"]["provider"], task["owner"]["model"]))
        return {key: whole["value"]}, 0
    known, missing = defaultdict(int), 0
    for segment in task["segments"]:
        observation = segment.get("cost", {}).get("tokens", "unknown")
        if observation == "unknown":
            missing += 1
        else:
            known[(segment["provider"], segment["model"])] += observation["value"]
    return dict(known), missing


def mtoks(known, missing):
    """Millions of tokens; unknown stays a dash and a partial sum is marked."""
    if not known:
        return '<span class="muted" title="No token usage reported">–</span>'
    value = sum(known.values()) / 1e6
    text = '&lt;0.01' if 0 < value < 0.005 else f'{value:.2f}' if value < 10 else f'{value:.1f}'
    if missing:
        return f'<span title="Known subtotal; {missing} observation{"s" if missing != 1 else ""} unreported">{text}+</span>'
    return text


def progress_html(data):
    tasks = [t for t in data["tasks"] if t["status"] != "cancelled"]
    now = timestamp(data["project"]["as_of"])
    weights = {t["id"]: task_weight(t) for t in tasks}
    counted = sum(weights.values()) > 0
    if not counted:
        weights = {tid: 1 for tid in weights}
    total = sum(weights.values()) or 1
    share = lambda *statuses: sum(weights[t["id"]] for t in tasks if t["status"] in statuses) / total * 100
    count = lambda *statuses: sum(t["status"] in statuses for t in tasks)
    done, active = share("done"), share(*ACTIVE)
    finished = all(t["status"] == "done" for t in tasks)
    finish = max((task_end(t, data["project"]["as_of"]) for t in tasks), default=now)
    measure = (f'of estimated work done · {span_text(done*total/100)} of {span_text(total)}' if counted
               else f'of tasks done · {count("done")} of {len(tasks)}')
    waiting = len(tasks) - count("done") - count(*ACTIVE)
    return (f'<div class="progress"><p><strong>{done:.0f}%</strong> {measure} · '
            f'{"finished" if finished else "forecast finish"} <b>{esc(short_clock(finish, now))}</b></p>'
            f'<div class="pbar" role="img" aria-label="{done:.0f}% done, {active:.0f}% running">'
            f'<i class="done" style="--w:{done:.3f}%"></i><i class="active" style="--w:{active:.3f}%"></i><i class="todo"></i></div>'
            f'<div class="plabels"><span style="--w:{done:.3f}%">{count("done")} done</span>'
            f'<span style="--w:{active:.3f}%">{count(*ACTIVE)} running</span><span>{waiting} waiting</span></div></div>')


def build_axis(spans, squeeze_from=None):
    """Clock axis without dead time: idle gaps are cut and the far future is compressed."""
    pad = timedelta(minutes=10)
    blocks = []
    for a, b in sorted((a - pad, b + pad) for a, b in spans):
        if blocks and (a - blocks[-1][1]).total_seconds() < CUT_MINUTES * 60:
            blocks[-1][1] = max(blocks[-1][1], b)
        else:
            blocks.append([a, b])
    pieces = []
    for index, (a, b) in enumerate(blocks):
        if index:
            pieces.append(dict(kind="cut", a=blocks[index-1][1], b=a))
        if squeeze_from is not None and a < squeeze_from < b:
            pieces += [dict(kind="time", a=a, b=squeeze_from), dict(kind="far", a=squeeze_from, b=b)]
        else:
            pieces.append(dict(kind="far" if squeeze_from is not None and a >= squeeze_from else "time", a=a, b=b))
    minutes = lambda p: (p["b"] - p["a"]).total_seconds() / 60
    near = sum(minutes(p) for p in pieces if p["kind"] == "time")
    far = sum(minutes(p) for p in pieces if p["kind"] == "far")
    scale = min(1, FAR_SHARE * near / ((1 - FAR_SHARE) * far)) if near and far else 1
    cuts = sum(p["kind"] == "cut" for p in pieces)
    cut_width = min(0.03, 0.3 / cuts) if cuts else 0
    total = near + far * scale or 1
    x = 0
    for piece in pieces:
        if piece["kind"] == "far" and scale == 1:
            piece["kind"] = "time"
        width = cut_width if piece["kind"] == "cut" else (
            (1 - cut_width * cuts) * minutes(piece) * (scale if piece["kind"] == "far" else 1) / total)
        piece.update(x0=x, x1=x + width)
        x += width

    def fraction(at):
        for piece in pieces:
            if at <= piece["b"]:
                length = (piece["b"] - piece["a"]).total_seconds()
                part = (at - piece["a"]).total_seconds() / length if length else 0
                return piece["x0"] + (piece["x1"] - piece["x0"]) * max(0, min(1, part))
        return 1

    return pieces, fraction


def axis_ticks(pieces, fraction):
    ticks, last_x, last_day = [], -1, None
    for piece in pieces:
        if piece["kind"] == "cut":
            continue
        minutes = (piece["b"] - piece["a"]).total_seconds() / 60
        width = (piece["x1"] - piece["x0"]) * 100
        step = next((s for s in TICK_STEPS if s / minutes * width >= 7), None)
        if step is None:
            continue
        local = piece["a"].astimezone(SYDNEY)
        offset = local.hour * 60 + local.minute + local.second / 60
        at = piece["a"] + timedelta(minutes=math.ceil(offset / step) * step - offset)
        while at <= piece["b"]:
            x, local = fraction(at), at.astimezone(SYDNEY)
            if x - last_x >= 0.055:
                text = f'{local:%H:%M}' if local.minute or step < 60 else f'{local:%H}'
                if last_day is not None and local.date() != last_day:
                    text = f'{local:%a} {text}'
                ticks.append((x, text))
                last_x, last_day = x, local.date()
            at += timedelta(minutes=step)
    return ticks


def short_name(task):
    found = REFERENCE.search(task["title"])
    return found.group(0) if found else ' '.join(re.split(r'[:,(]', task["title"])[0].split()[:3])


def title_html(task):
    """Issue numbers in a title link to the task's thread when the ledger has one."""
    text, href = esc(task["title"]), task.get("thread")
    if not href:
        return text
    link = lambda label: f'<a href="{esc(href)}">{label}</a>'
    return REFERENCE.sub(lambda m: link(m.group(0)), text) if REFERENCE.search(text) else link(text)


def timeline(data, name, colours, recent_hours):
    now = timestamp(data["project"]["as_of"])
    tasks = data["tasks"]
    by_id = {t["id"]: t for t in tasks}
    indices = {t["id"]: i for i, t in enumerate(tasks)}
    critical = set(critical_path(data))
    recent = name == "recent"
    remaining = [t for t in tasks if t["status"] not in TERMINAL]
    floor = None
    if not recent:
        shown = list(tasks)
    elif remaining:
        shown = remaining
    else:  # nothing left to do: fall back to what finished lately
        floor = now - timedelta(hours=recent_hours)
        shown = [t for t in tasks if any(interval(s, "segment", now)[1] > floor for s in t["segments"])]
    shown_ids = {t["id"] for t in shown}
    lanes, spans = {}, [(now, now)]
    for task in shown:
        lanes[task["id"]] = segment_rows(task, now)
        for lane in lanes[task["id"]]:
            for segment, _, _ in lane:
                a, b = interval(segment, "segment", now)
                if floor is None or b > floor:
                    spans.append((a if floor is None else max(a, floor), b))
    earliest = min(a for a, _ in spans)
    streams = list(dict.fromkeys(t["stream"] for t in tasks))
    homes, loose = defaultdict(list), []
    for marker in data.get("milestones", []):
        at = timestamp(marker["target"])
        if recent and not (shown_ids.intersection(marker["tasks"]) or (not marker["tasks"] and at >= now)):
            continue
        if not recent or at >= earliest:
            spans.append((at, at))
        if marker["tasks"]:
            homes[max(streams, key=lambda s: sum(by_id[tid]["stream"] == s for tid in marker["tasks"]))].append(marker)
        else:
            loose.append(marker)
    # Once work has been observed, a long forecast must not squash it.
    observed = any(t["segments"] for t in tasks)
    pieces, fraction = build_axis(spans, now + timedelta(hours=recent_hours) if observed else None)
    lo, hi = pieces[0]["a"], pieces[-1]["b"]
    pct = lambda value: f'{value*100:.4f}%'

    def place(a, b):
        if b < lo or a > hi:
            return None
        x = fraction(a)
        return f'--x:{pct(x)};--w:{pct(max(0, fraction(b) - x))}'

    def marker_html(marker):
        at = timestamp(marker["target"])
        label = f'{esc(marker["kind"])} {esc(marker["id"])} · {esc(marker["name"])} · target {esc(display_time(marker["target"]))} · {esc(marker["status"])}'
        if not lo <= at <= hi:
            return f'<span class="note" style="left:6px" title="{label}">target {esc(short_clock(at, now))}, outside this view</span>'
        x = fraction(at)
        side = f'right:calc({pct(1 - x)} + 9px)' if x >= 0.25 else f'left:calc({pct(x)} + 9px)'
        return (f'<span class="note" style="{side}">target {esc(short_clock(at, now))}</span>'
                f'<i class="marker {esc(marker["kind"])}" style="--x:{pct(x)}" title="{label}"></i>')

    ticks = axis_ticks(pieces, fraction)
    grid = ''.join(f'<i class="gridline" style="--x:{pct(x)}"></i>' for x, _ in ticks)
    axis = ''.join(f'<span class="tick" style="--x:{pct(x)}">{esc(text)}</span>' for x, text in ticks)
    for piece in pieces:
        middle = pct((piece["x0"] + piece["x1"]) / 2)
        if piece["kind"] == "cut":
            idle = span_text((piece["b"] - piece["a"]).total_seconds() / 60)
            grid += f'<i class="cut" style="--x:{pct(piece["x0"])};--w:{pct(piece["x1"] - piece["x0"])}"></i>'
            axis += f'<span class="tick top" style="--x:{middle}" title="{idle} with no work, cut from the axis">{idle} cut</span>'
        elif piece["kind"] == "far":
            grid += f'<i class="far" style="--x:{pct(piece["x0"])};--w:{pct(piece["x1"] - piece["x0"])}"></i>'
            axis += f'<span class="tick top" style="--x:{middle}" title="More than {fmt(recent_hours)}h ahead, drawn at a smaller scale">later, compressed</span>'
    if lo <= now <= hi:
        grid += f'<i class="now" style="--x:{pct(fraction(now))}" title="As of {esc(display_time(now.isoformat()))}"></i>'
        axis += f'<span class="tick top nowtick" style="--x:{pct(fraction(now))}">now</span>'

    rows, totals, unreported = [], defaultdict(int), 0
    for stream in streams:
        members = [t for t in tasks if t["stream"] == stream]
        visible = [t for t in members if t["id"] in shown_ids]
        known, missing = defaultdict(int), 0
        for task in members:
            task_known, task_missing = task_tokens(task)
            missing += task_missing
            for key, value in task_known.items():
                known[key] += value
                totals[key] += value
        unreported += missing
        done = sum(t["status"] == "done" for t in members)
        hidden = len(members) - len(visible)
        tag = f'{done}/{len(members)}' + (f' · {hidden} finished hidden' if hidden and visible else '')
        if visible:
            marks = ''.join(marker_html(m) for m in homes[stream])
        else:
            last = max(task_end(t, data["project"]["as_of"]) for t in members)
            marks = f'<span class="note" style="left:6px">✓ {len(members)} finished, last at {esc(short_clock(last, now))}</span>'
        rows.append(f'<div class="chart-row group"><div class="label">{esc(stream)} <small>{tag}</small></div>'
                    f'<div class="track">{marks}</div><div class="cost">{mtoks(known, missing) if known else ""}</div></div>')
        first = lambda t: min([timestamp(s["start"]) for s in t["segments"]] or [timestamp(t["forecast"]["start"])])
        for task in sorted(visible, key=first):
            marks, projected, packed = '', [], lanes[task["id"]]
            for lane_index, lane in enumerate(packed):
                for segment, forecast, _ in lane:
                    a, b = interval(segment, "segment", now)
                    style = place(a, b) if floor is None or b > floor else None
                    if not style:
                        continue
                    if forecast:
                        projected.append((a, b))
                    kind = segment["kind"]
                    code = f'R{segment["round"]}' if kind == "review" else 'B'
                    desc = (f'{"Forecast " if forecast else ""}{kind.title()} {code} · {segment["model"]} · {segment["effort"]} · '
                            f'{segment["provider"]} · {display_time(segment["start"])} to {display_time(b.isoformat())}'
                            f'{"" if forecast or segment.get("end") else " (running)"}'
                            f'{" · " + segment["result"] if segment.get("result") else ""}'
                            f'{" · clipped at window edge" if a < lo or b > hi else ""}')
                    state = 'projection' if forecast else '' if segment.get("end") else 'open'
                    marks += (f'<span class="bar {kind} {state}" style="{style};--lane:{lane_index};'
                              f'--c:{colours[(segment["provider"], segment["model"])]}" title="{esc(desc)}" aria-label="{esc(desc)}"></span>')
            if task["status"] in ACTIVE:
                if projected:
                    x = fraction(max(b for _, b in projected))
                    if x <= 0.88:
                        marks += (f'<span class="eta" style="left:calc({pct(x)} + 5px)" title="ETA {esc(display_time(task["forecast"]["end"]))}">'
                                  f'{esc(short_clock(timestamp(task["forecast"]["end"]), now))}</span>')
                else:
                    marks += f'<span class="note" style="left:calc({pct(fraction(now))} + 5px)">past its forecast</span>'
            elif task["status"] not in TERMINAL:
                pending = [by_id[dep] for dep in task["dependencies"] if by_id[dep]["status"] not in TERMINAL]
                text = ('after ' + ', '.join(short_name(t) for t in pending[:2]) + (f' +{len(pending) - 2}' if len(pending) > 2 else '')
                        if pending else 'blocked' if task["status"] == "blocked" else '')
                if text:
                    start = fraction(min(a for a, _ in projected)) if projected else fraction(now)
                    finish = fraction(max(b for _, b in projected)) if projected else start
                    # Sit on whichever side of the forecast has more room; the rest is on hover.
                    side = (f'right:calc({pct(1 - start)} + 4px);max-width:calc({pct(start)} - 8px)' if projected and start >= 1 - finish else
                            f'left:calc({pct(finish)} + 5px);max-width:calc({pct(1 - finish)} - 8px)')
                    waits = ', '.join(f'{t["id"]} {t["title"]}' for t in pending)
                    marks += f'<span class="note" style="{side}" title="{esc("Waiting on " + waits if waits else "Blocked")}">{esc(text)}</span>'
            index = indices[task["id"]]
            hover = f'{task["id"]} · {task["title"]} · {task["status"]}{" · on the critical path" if task["id"] in critical else ""}'
            rows.append(f'<div class="chart-row task-row {task["status"]}{" critical-task" if task["id"] in critical else ""}" id="{name}-task-{index}">'
                        f'<div class="label" title="{esc(hover)}"><span class="status">{STATUS_SYMBOLS.get(task["status"], "◷")}</span>{title_html(task)}</div>'
                        f'<div class="track" style="--lanes:{max(0, len(packed) - 1)}">{marks}</div><div class="cost">{mtoks(*task_tokens(task))}</div></div>')
    for marker in loose:
        rows.append(f'<div class="chart-row marker-row"><div class="label" title="{esc(marker["status"])}"><span class="status">◆</span>{esc(marker["name"])}</div>'
                    f'<div class="track">{marker_html(marker)}</div><div class="cost"></div></div>')
    grand = sum(totals.values())
    if grand:
        order = sorted(totals.items(), key=lambda item: -item[1])
        split = ''.join(f'<i style="--w:{value/grand*100:.3f}%;--c:{colours.get(key, "var(--quiet)")}" title="{esc(key[1])} · {esc(key[0])}"></i>' for key, value in order)
        detail = ' · '.join(f'{esc(key[1])} {mtoks({key: value}, 0)}' for key, value in order)
        if unreported:
            detail += f' · {unreported} unreported'
        middle = f'<span class="split">{split}</span><span class="note">{detail}</span>'
    else:
        middle = '<span class="note plain">No token usage reported by the host</span>'
    rows.append(f'<div class="chart-row total"><div class="label">Project total <small>all {len(tasks)} tasks</small></div>'
                f'<div class="track">{middle}</div><div class="cost">{mtoks(totals, unreported)}</div></div>')
    title = 'Whole-run timeline' if not recent else 'Remaining work' if remaining else 'Recent work'
    body = (f'<div class="chart-scroll" tabindex="0" role="region" aria-label="{title}, scrolls sideways on narrow screens"><div class="chart">'
            f'<div class="chart-row axis"><div class="label">{esc(display_time(lo.isoformat()))} – {esc(display_time(hi.isoformat()))}</div>'
            f'<div class="track">{axis}</div><div class="cost" title="Millions of tokens reported by the host">mtoks</div></div>'
            f'<div class="plot"><div class="grid" aria-hidden="true">{grid}</div>{"".join(rows)}</div></div></div>'
            '<p class="chart-note">One row per task: solid build, hatched review, dashed outline for the forecast, split between build and review in proportion to the original allocations. '
            'Hover a bar for model, effort, round, times and result. '
            + ('Finished tasks are hidden and the view starts where the oldest unfinished task began. ' if recent and remaining else '')
            + 'Idle stretches over an hour are cut from the axis'
            + (f', and time more than {fmt(recent_hours)}h ahead is drawn at a smaller scale. ' if any(p["kind"] == "far" for p in pieces) else '. ')
            + 'mtoks is millions of tokens the host reported; a dash means none reported and + marks a partial sum.</p>')
    return section_html(title, body, name, collapsed=not recent)


def calibration_html(data):
    result = calibration(data)
    groups = result["groups"]
    scale = max([2] + [row["ratio"] or 0 for row in groups.values()])
    rows = []
    for (provider, model, effort, kind), row in sorted(groups.items()):
        ratio = row["ratio"]
        ratio_text = fmt(ratio) + '×' if ratio is not None else 'undefined (zero estimate)'
        plot = (f'<div class="ratio-plot" style="--one:{100/scale}%"><i class="ratio-one"></i>'
                f'<span class="ratio-bar" style="--w:{(ratio or 0)/scale*100}%"></span></div>')
        rows.append([f'{esc(model)}<small>{esc(provider)}</small>', esc(effort), esc(kind),
                     fmt(row["estimated_minutes"]), fmt(row["actual_minutes"]), f'{ratio_text}{plot}'])
    content = table('Final calibration', ['Model / provider', 'Effort', 'Kind', 'Original min', 'Actual min', 'Actual / original'], rows, 'calibration', True,
                    note='Completed tasks only; ratios use summed segment minutes for comparable identities. Black/white reference = 1×. Waiting and parallel task spans are not model effort. Incomplete/cancelled tasks are excluded.')
    # Separate dimension summaries keep effort and kind comparisons explicit.
    for dimension, offset in (("model", 1), ("effort", 2), ("kind", 3)):
        totals = defaultdict(lambda: [0, 0])
        for key, row in groups.items():
            label = (key[0] + ' / ' + key[1]) if dimension == "model" else key[offset]
            totals[label][0] += row["estimated_minutes"]
            totals[label][1] += row["actual_minutes"]
        content += table(f'Calibration by {dimension}', [dimension.title(), 'Original min', 'Actual min', 'Actual / original'],
                         [[esc(label), fmt(a), fmt(b), fmt(b/a)+'×' if a else 'undefined'] for label, (a,b) in sorted(totals.items())], f'by-{dimension}', True)
    tasks = {t["id"]: t for t in data["tasks"]}
    comparisons = []
    for row in result["comparisons"]:
        if not row["comparable"]:
            task = tasks[row["task"]]
            before = '; '.join(f'{a["provider"]} / {a["model"]} / {a["effort"]}' for a in task["baseline"]["allocations"] if a["kind"] == row["kind"])
            after = '; '.join(sorted({f'{s["provider"]} / {s["model"]} / {s["effort"]}' for s in task["segments"] if s["kind"] == row["kind"]}))
            comparisons.append([esc(row["task"]), esc(row["kind"]), f'not comparable<small>{"Identity changed" if data.get("approval") else "Plan unapproved"}</small>',
                                f'{fmt(row["estimated_minutes"])} min<small>{esc(before)}</small>', f'{fmt(row["actual_minutes"])} min<small>{esc(after)}</small>'])
    content += table('Comparisons excluded', ['Task', 'Kind', 'Reason', 'Original', 'Actual'], comparisons, 'not-comparable', True)
    content += table('Review rounds', ['Task', 'Planned', 'Actual distinct rounds'],
                     [[esc(r["task"]), str(r["planned"]), str(r["actual"])] for r in result["rounds"]], 'review-rounds', True)
    costrows = []
    for (provider, model), metrics in sorted(result["costs"].items()):
        values = []
        for metric in METRICS:
            row = metrics[metric]
            value = (f'${row["known"]:.4f}' if metric == 'usd' else fmt(row["known"])) if row["sources"] else 'unknown'
            if row["sources"] and row["missing"]:
                value += ' known subtotal'
            if row["estimated"]:
                value += ' (host estimate)'
            value += f'<small>{row["missing"]} unknown observation{"s" if row["missing"]!=1 else ""}</small>'
            if row['sources']:
                value += '<small>' + esc('; '.join(sorted(set(row["sources"])))) + '</small>'
            values.append(value)
        costrows.append([f'{esc(model)}<small>{esc(provider)}</small>', *values])
    return content + table('Cost by model', ['Model / provider', 'Tokens', 'Turns', 'USD'], costrows, 'costs', True)


def render(data, mode="report", theme="auto", recent_hours=4, allow_future_fixture=False):
    validate(data)
    require(mode in {"propose", "report", "final"}, "mode must be propose, report or final")
    require(theme in {"auto", "light", "dark"}, "theme must be auto, light or dark")
    require(type(recent_hours) in {int, float} and math.isfinite(recent_hours) and recent_hours > 0,
            "recent-hours must be positive and finite")
    project, tasks = data["project"], data["tasks"]
    now = timestamp(project["as_of"])
    require(allow_future_fixture or now <= datetime.now(timezone.utc),
            'project.as_of is in the future relative to renderer clock')
    identities = {(s["provider"], s["model"]) for t in tasks for s in t["segments"]}
    identities |= {(t["owner"]["provider"], t["owner"]["model"]) for t in tasks}
    identities |= {(a["provider"], a["model"]) for t in tasks for a in t.get("baseline", {}).get("allocations", [])}
    palette, palette_css = model_palette(identities)
    milestone = min((m for m in data.get("milestones", []) if m["status"] not in {"done", "cancelled"}), key=lambda m:timestamp(m["target"]), default=None)
    next_text = (f'{esc(milestone["name"])} · {esc(display_time(milestone["target"]))}' if milestone else 'None pending')
    cp = critical_path(data)
    boundary = mode in {'propose', 'final'}
    cp_refs = []
    for tid in cp:
        index = next(i for i, task in enumerate(tasks) if task['id'] == tid)
        cp_refs.append(f'<a href="#whole-task-{index}">{esc(tid)}</a>' if boundary
                       else f'<span class="task-ref">{esc(tid)}</span>')
    content = f'<main class="report {theme}"><header><div class="topline"><span>Plan report · {mode}</span><span>{esc(project["status"])}</span></div><h1>{esc(project["name"])}</h1><p>As of <strong>{esc(display_time(project["as_of"]))}</strong></p>'
    if allow_future_fixture:
        content += '<p role="note">Synthetic fixture replay, not live evidence.</p>'
    content += f'<div class="facts"><div><strong>Next milestone / gate</strong>{next_text}</div><div><strong>Original plan</strong>{"Approved " + esc(display_time(data["approval"]["at"])) + " · " + esc(data["approval"]["approver"]) if data.get("approval") else "Proposal · approval pending"}</div>'
    content += '<div class="critical"><strong>Current critical path · remaining forecast durations</strong>' + (' → '.join(cp_refs) or 'No remaining tasks') + '</div></div></header>'
    stale = [t['id'] for t in tasks if t['status'] not in {'done','cancelled'} and timestamp(t['forecast']['end']) < now]
    if stale:
        content += '<p class="muted">Stale forecasts: ' + esc(', '.join(stale)) + '. Finish overruns are lower bounds at as-of; update forecasts before relying on the schedule.</p>'
    decisions = decision_records(data)
    pending = [record for record,current in decisions if current and record['status']=='pending']
    if pending:
        content += '<aside class="decision-strip" aria-label="Pending decision questions"><strong>Awaiting answer</strong>' + ''.join(f'<p>{esc(d["id"])} · {esc(d["owner"])} · affects {esc(", ".join(d["tasks"]))}</p>' for d in pending) + '<a href="#owner">Decision record</a></aside>'
    content += progress_html(data)
    content += '<div class="key">' + ''.join(f'<span><i class="swatch" style="--c:{colour}"></i>{esc(model)} · {esc(provider)}</span>' for (provider, model), colour in sorted(palette.items()))
    content += '<span><i class="review-key"></i>Review</span><span><i class="projection-key"></i>Forecast</span><span>◆ Milestone or gate target</span></div>'
    content += timeline(data, 'recent', palette, recent_hours)
    if boundary:
        content += timeline(data, 'whole', palette, recent_hours)
    content += '<div class="tables">'
    content += decision_table(decisions)
    running = [(t,s) for t in tasks for s in t['segments'] if s.get('end') is None]
    content += table('Running now', ['Model', 'Task ID', 'Value'],
                     [[esc(s['model']), esc(t['id']), esc(t.get('value', t['title']))] for t,s in running], 'running')
    overruns = []
    for task in tasks:
        if task.get('baseline'):
            end, original = task_end(task, project['as_of']), baseline_end(task['baseline'])
            if end > original:
                label = 'actual' if task['status']=='done' else 'at least (stale forecast)' if task['id'] in stale else 'forecast'
                overruns.append([esc(task['id']+' · '+task['title']), esc(display_time(original.isoformat())), esc(display_time(end.isoformat())), f'+{fmt((end-original).total_seconds()/60)}m {label}'])
    content += table('Overruns', ['Task', 'Original finish', 'Current finish', 'Past original'], overruns, 'overruns')
    content += table('Events', ['Time / source', 'Event', 'Scope'],
                     [[esc(display_time(e['start']))+f'<small>to {esc(display_time(e["end"]) if e.get("end") else "as of (open)")} · {esc(e["source"])}</small>', f'E{i+1} · {esc(e["kind"])}<small>{esc(e["note"])}</small>', esc(json.dumps(e['scope'],ensure_ascii=False))] for i,e in enumerate(data.get('events', []))], 'events')
    completions = sorted([(t,s) for t in tasks for s in t['segments'] if s.get('end')], key=lambda x: timestamp(x[1]['end']), reverse=True)[:20]
    if mode != 'report':
        content += table('Recently completed', ['Finished', 'Task / lane / round', 'Model / result'],
                     [[esc(display_time(s['end'])), esc(t['id']+' · '+t['title'])+f'<small>{esc(s["kind"])} · round {s["round"]}</small>', identity_label(s)+f'<small>{esc(s.get("result", ""))}</small>'] for t,s in completions], 'recently-completed', True)
    content += table('Milestones and gates', ['Name / status', 'Target', 'Tasks / required reviewers'],
                     [[esc(m['id']+' · '+m['name'])+f'<small>{esc(m["kind"])} · {esc(m["status"])}</small>', esc(display_time(m['target'])), esc(', '.join(m['tasks']))+f'<small>{esc(", ".join(m["required_reviewers"]))}</small>'] for m in data.get('milestones', [])], 'milestones', True)
    content += table('Rebaseline history', ['Time / approver', 'Reason', 'Changed estimates'],
                     [[esc(display_time(c['at']))+f'<small>{esc(c["approver"])}</small>', esc(c['reason']), '<br>'.join(f'{esc(tid)}: {esc(display_time(p["start"]))} · '+esc('; '.join(f'{a["kind"]} {a["model"]} {a["effort"]}: {fmt(a["minutes"])}m' for a in p['allocations'])) for tid,p in c['tasks'].items())] for c in data.get('rebaselines', [])], 'rebaselines', True)
    content += '</div>'
    content += table('Original baseline · task allocations and references', ['Task', 'Original allocations', 'Review rounds / references'],
                     [[esc(t['id']+' · '+t['title']), '<br>'.join(esc(f'{a["kind"]}: {a["provider"]} / {a["model"]} / {a["effort"]} · {fmt(a["minutes"])}m') for a in t.get('baseline',{}).get('allocations',[])) or 'No baseline', esc(str(t.get('baseline',{}).get('review_rounds','unknown')))+f'<small>{esc("; ".join(t.get("issues",[])+t.get("prs",[])))}</small>'] for t in tasks if t.get('baseline') or t.get('issues') or t.get('prs')], 'original', True)
    if mode == 'final':
        content += calibration_html(data)
    content += '<footer>Private ledger report · forecasts are estimates · original approved allocations remain frozen. Rebaselines record decisions; events show exposure, not proven causation.</footer></main>'
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(project['name'])+' · plan report</title><style>'+CSS+palette_css+'</style></head><body>'+content+'<script>'+SCRIPT+'</script></body></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mode', choices=('propose','report','final'), default='report')
    parser.add_argument('--theme', choices=('auto','light','dark'), default='auto')
    parser.add_argument('--recent-hours', type=float, default=4, help='Hours ahead drawn at full scale in the progress timeline, and the lookback once nothing remains (default: 4)')
    parser.add_argument('--allow-future-fixture', action='store_true', help='Allow future synthetic fixtures and visibly mark output as not live evidence')
    args = parser.parse_args()
    try:
        require(args.ledger.resolve() != args.output.resolve(), 'output must not overwrite ledger')
        data = json.loads(args.ledger.read_text(encoding='utf-8'))
        html = render(data, args.mode, args.theme, args.recent_hours, args.allow_future_fixture)
        args.output.write_text(html, encoding='utf-8')
    except (ValueError, OSError, OverflowError, TypeError, KeyError, RecursionError) as exc:
        print(f'plan-report: {exc}', file=sys.stderr)
        return 2
    print(f'Wrote {args.output}')
    return 0


if __name__ == '__main__':
    if sys.version_info < (3,10):
        sys.exit('Python 3.10+ required')
    sys.exit(main())
