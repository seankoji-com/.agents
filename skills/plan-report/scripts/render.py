#!/usr/bin/env python3
"""Render a private plan ledger to self-contained HTML; Python 3.10+ stdlib."""
import argparse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from html import escape
import json
import math
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
--model-0:#087c85;--model-1:#7043a4;--model-2:#285fad;--model-3:#986120;--model-4:#a13763;--model-5:#386f43;
background:var(--paper);color:var(--ink);border-radius:12px;padding:16px;min-width:0;overflow-wrap:anywhere}
.report.dark{--paper:#172334;--panel:#202e40;--ink:#e5edf7;--quiet:#b0bfd1;--line:#536579;
--red:#ff9eae;--amber:#f3cb76;--wash:#3c3322;--ghost:#34475b;--link:#9ccaff;
--model-0:#46c7cf;--model-1:#c49bee;--model-2:#82b2ff;--model-3:#deb175;--model-4:#ee94b8;--model-5:#8bce96}
@media(prefers-color-scheme:dark){.report.auto{--paper:#172334;--panel:#202e40;--ink:#e5edf7;--quiet:#b0bfd1;--line:#536579;--red:#ff9eae;--amber:#f3cb76;--wash:#3c3322;--ghost:#34475b;--link:#9ccaff;--model-0:#46c7cf;--model-1:#c49bee;--model-2:#82b2ff;--model-3:#deb175;--model-4:#ee94b8;--model-5:#8bce96}}
h1{font-size:29px;line-height:1.2;letter-spacing:-.7px;margin:8px 0}h2{font-size:17px;margin:0 0 10px}
h3{font-size:14px;margin:12px 0 6px}p{margin:6px 0}a{color:var(--link)}small,.muted{color:var(--quiet);font-size:11px}
header{padding-bottom:16px;border-bottom:1px solid var(--line)}.topline,.key{display:flex;gap:8px 16px;flex-wrap:wrap;align-items:center}
.facts{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}.facts strong{display:block;font-size:11px;color:var(--quiet)}
.critical{grid-column:1/-1;border-left:3px solid var(--red);padding-left:10px}.critical a,.critical .task-ref{display:inline-block;padding:1px 5px;border:1px solid var(--line);border-radius:3px;margin:2px}
section{padding-top:22px}.chip{display:inline-block;border:1px solid var(--line);padding:1px 5px;border-radius:4px;font-size:10px;font-weight:650;background:var(--panel)}
.chip.running,.chip.review{border-color:var(--link);color:var(--link)}.chip.blocked,.chip.ready,.chip.planned{color:var(--amber);border-color:var(--amber)}
.chip.over{color:var(--red);border-color:var(--red)}.decision-strip{padding:10px 12px;border:1.5px solid var(--amber);border-radius:4px;background:var(--wash);margin-top:14px}
.decision-strip p+p{border-top:1px solid var(--line);padding-top:8px}.key{font-size:11px;margin:14px 0}.key i{display:inline-block;width:18px;height:10px;vertical-align:middle;margin-right:4px}
.swatch{background:var(--mc)}.ghost-key{background:var(--ghost);border:1px dashed var(--quiet)}.projection-key{border:1px dashed var(--link)}.over-key{border-top:3px solid var(--red)}
.chart-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--panel)}
.chart{min-width:760px;position:relative;padding:0 12px 12px}.plot{position:relative}.chart-row{display:grid;grid-template-columns:214px minmax(0,1fr);position:relative}
.label{padding:6px 10px 6px 0;min-width:0;position:sticky;left:0;z-index:6;background:var(--panel)}
.task-head .label{font-weight:650}.task-head{border-top:1px solid var(--line)}.task-head .label small{display:block;font-weight:400}
.task-block.critical-task>.task-head{border-left:3px solid var(--red);padding-left:5px}.lane-name{font-size:12px;font-weight:650}.lane-meta{display:block;color:var(--quiet);font-size:11px}
.lane.build .label{border-left:2px solid var(--line);padding-left:8px}.lane.review .label{border-left:2px dashed var(--line);padding-left:8px}
.track{position:relative;min-height:34px;background:repeating-linear-gradient(to right,var(--line) 0 1px,transparent 1px 20%);border-bottom:1px dotted var(--line)}
.task-head .track{min-height:42px}.axis .label{font-size:11px}.axis .track{height:48px;position:relative;background:none;border:0}
.tick{position:absolute;left:var(--x);font-size:10px;line-height:1.2;white-space:nowrap;transform:translateX(-50%);top:6px;color:var(--quiet)}
.tick.first{transform:none}.tick.last{transform:translateX(-100%)}.now{position:absolute;left:var(--x);top:0;bottom:0;border-left:1.5px solid var(--ink);z-index:4;pointer-events:none}
.bar,.baseline,.overrun,.event-band{position:absolute;left:var(--x);width:var(--w)}
.bar{top:10px;height:18px;border:1px solid var(--mc);border-radius:2px;background:var(--mc);z-index:2;min-width:2px}
.bar.review{background-image:repeating-linear-gradient(135deg,transparent 0 4px,#ffffff50 4px 5px)}
.bar.open{outline:2px solid var(--ink);outline-offset:1px}.bar.projection{background:transparent;border:1.5px dashed var(--mc)}
.baseline{top:8px;height:9px;border:1px dashed var(--quiet);background:var(--ghost);min-width:2px}
.overrun{top:27px;border-top:3px solid var(--red);min-width:2px}.overrun.projected{border-top-style:dashed}
.event-band{top:2px;bottom:2px;background:#e4b24238;border:1px dotted var(--amber);z-index:1;min-width:2px}
.marker{position:absolute;left:var(--x);top:12px;width:10px;height:10px;transform:translateX(-50%) rotate(45deg);border:1.5px solid var(--link);background:var(--panel);z-index:3}
.marker.gate{border-color:var(--amber);background:var(--wash)}.marker.rebaseline{border-color:var(--red)}
.connections{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2;overflow:visible}
.dependency{fill:none;stroke:var(--quiet);stroke-width:1.3;stroke-dasharray:3 3;vector-effect:non-scaling-stroke}
.handoff{fill:none;stroke:var(--ink);stroke-width:1.5;vector-effect:non-scaling-stroke}.handoff.projected{stroke-dasharray:3 3}.chart-note{font-size:11px;color:var(--quiet);margin-top:8px}
.tables{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 24px}.wide{grid-column:1/-1}.table-scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;text-align:left;font-size:12px}th{font-size:10px;color:var(--quiet);font-weight:500}td,th{padding:8px 8px 8px 0;border-bottom:1px solid var(--line);vertical-align:top}td small{display:block}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}.ratio-plot{min-width:120px;position:relative;height:14px;background:var(--ghost)}.ratio-bar{display:block;height:100%;width:var(--w);background:var(--link)}
.ratio-one{position:absolute;left:var(--one);top:-3px;bottom:-3px;border-left:2px solid #101820;box-shadow:1px 0 #fff,-1px 0 #fff}details{margin:0}summary{cursor:pointer;font-weight:650;padding:8px 0;border-bottom:1px solid var(--line)}summary h2{display:inline;font-size:17px;margin:0}summary:focus-visible{outline:2px solid var(--link);outline-offset:3px}.section-body{padding-top:10px}footer{font-size:11px;color:var(--quiet);border-top:1px solid var(--line);margin-top:22px;padding-top:10px}
@media(max-width:600px){.facts,.tables{grid-template-columns:minmax(0,1fr)}h1{font-size:24px}.report{padding:12px}.table-scroll table{min-width:450px}}
"""

SCRIPT = """
function connect(){document.querySelectorAll('.chart').forEach(chart=>{
 if(chart.closest('details:not([open])'))return;
 const plot=chart.querySelector('.plot'), svg=chart.querySelector('.connections');
 const box=plot.getBoundingClientRect();if(!(box.width>0&&box.height>0))return;
 const viewBox=`0 0 ${box.width} ${box.height}`;if(svg.getAttribute('viewBox')!==viewBox)svg.setAttribute('viewBox',viewBox);
 const rows=Array.from(plot.querySelectorAll('.task-block'));
 function point(row,finish){const lanes=row.querySelectorAll('.lane .track');
  const track=lanes.length?lanes[finish?lanes.length-1:0]:row.querySelector('.task-head .track');
  const r=track.getBoundingClientRect(), f=Number(row.dataset[finish?'finish':'begin']);
  return [r.left-box.left+f*r.width,r.top-box.top+r.height/2];}
 svg.querySelectorAll('.dependency').forEach(path=>{const a=rows.find(r=>r.dataset.node===path.dataset.from),b=rows.find(r=>r.dataset.node===path.dataset.to);
  if(!a||!b)return;const [x,y]=point(a,true),[u,v]=point(b,false),mid=(y+v)/2;
  path.setAttribute('d',`M${x},${y} V${mid} H${u} V${v}`);});
 svg.querySelectorAll('.handoff').forEach(path=>{const row=rows.find(r=>r.dataset.node===path.dataset.node);
  const lanes=Array.from(row.querySelectorAll('.lane[data-lane]'));
  const a=lanes.find(r=>r.dataset.lane===path.dataset.fromLane), b=lanes.find(r=>r.dataset.lane===path.dataset.toLane);if(!a||!b)return;
  const p=a.querySelector('.track').getBoundingClientRect(),q=b.querySelector('.track').getBoundingClientRect();const x=q.left-box.left+Number(path.dataset.x)*q.width;
  path.setAttribute('d',`M${x},${p.top-box.top+p.height/2} V${q.top-box.top+q.height/2}`);});
 });}
let connectFrame=0;
function scheduleConnect(){if(connectFrame)return;connectFrame=requestAnimationFrame(()=>{connectFrame=0;connect();});}
function revealTarget(hash){let target;try{target=document.getElementById(decodeURIComponent(hash.slice(1)));}catch{return;}
 if(!target)return;let revealed=false;for(let node=target.parentElement;node;node=node.parentElement){if(node.tagName==='DETAILS'&&!node.open){node.open=true;revealed=true;}}
 const detail=target.firstElementChild;if(target.tagName==='SECTION'&&detail&&detail.tagName==='DETAILS'&&!detail.open){detail.open=true;revealed=true;}
 if(revealed)requestAnimationFrame(()=>{connect();target.scrollIntoView({block:'start'});});}
document.querySelectorAll('details').forEach(detail=>detail.addEventListener('toggle',scheduleConnect));
document.querySelectorAll('.report a[href^="#"]').forEach(link=>link.addEventListener('click',()=>revealTarget(link.hash)));
window.addEventListener('hashchange',()=>revealTarget(location.hash));
window.addEventListener('load',()=>{revealTarget(location.hash);scheduleConnect();});window.addEventListener('resize',scheduleConnect);
if(window.ResizeObserver){const observer=new ResizeObserver(scheduleConnect);document.querySelectorAll('.chart-scroll').forEach(chart=>observer.observe(chart));}
"""


def esc(value):
    return escape(str(value), quote=True)


def fmt(value):
    return f"{value:g}"


def chip(status):
    symbols = {"done": "✓", "running": "▶", "review": "▶", "blocked": "⊘", "planned": "◷",
               "ready": "◷", "cancelled": "×"}
    css = status if status in STATUSES else "planned"
    return f'<span class="chip {css}">{symbols.get(status, "◷")} {esc(status)}</span>'


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
        if item["kind"] == "build":
            item.update(task["owner"])
        output.append(item)
        a = min(end, b)
    return output


def timeline(data, name, lo, hi, palette):
    now = timestamp(data["project"]["as_of"])
    span = max(1, (hi-lo).total_seconds())
    tasks = data["tasks"]
    indices = {t["id"]: i for i, t in enumerate(tasks)}

    def fraction(at):
        return max(0, min(1, (at-lo).total_seconds()/span))

    def position(a, b):
        if b <= lo or a >= hi:
            return None
        x, end = fraction(a), fraction(b)
        return f'--x:{x*100:.6f}%;--w:{max(0,end-x)*100:.6f}%'

    def now_line():
        return f'<i class="now" style="--x:{fraction(now)*100:.6f}%" title="As of {esc(display_time(now.isoformat()))}"></i>' if lo <= now <= hi else ''

    ticks = []
    for i in range(6):
        time = lo + (hi-lo)*i/5
        local = time.astimezone(ZoneInfo("Australia/Sydney"))
        ticks.append(f'<span class="tick {"first" if i==0 else "last" if i==5 else ""}" style="--x:{i*20}%">{local:%H:%M}<br>{local:%d %b %Y}</span>')
    rows, visible, handoffs = [], [], []
    critical = critical_path(data)
    for index, task in enumerate(tasks):
        observed = task["segments"]
        future = projection(task, now)
        baseline_plan = task.get("baseline")
        relevant = observed + future
        begin = min([timestamp(s["start"]) for s in observed] or [timestamp(task["forecast"]["start"])])
        end = task_end(task, data["project"]["as_of"])
        task_events = [(ei, e) for ei, e in enumerate(data.get('events', [])) if event_affects(e,task)
                       and timestamp(e['start']) < end and timestamp(e.get('end') or data['project']['as_of']) > begin]
        has_event = any(timestamp(e['start']) < hi and timestamp(e.get('end') or data['project']['as_of']) > lo for _,e in task_events)
        if name == "recent" and task['status'] not in {'blocked','running','review'} and not has_event and not any(timestamp(s["start"]) < hi and timestamp(s.get("end") or data["project"]["as_of"]) > lo for s in relevant):
            continue
        visible.append(index)
        header_marks = ''
        over = 0
        if baseline_plan:
            finish = baseline_end(baseline_plan)
            style = position(timestamp(baseline_plan["start"]), finish)
            if style:
                header_marks += f'<i class="baseline" style="{style}" title="Original {esc(display_time(baseline_plan["start"]))} to {esc(display_time(finish.isoformat()))}"></i>'
            over = max(0, (end-finish).total_seconds()/60)
            for a, b, projected in [(finish, min(end, now), False), (max(finish, now), end, True)]:
                style = position(a, b)
                if b > a and style:
                    header_marks += f'<i class="overrun {"projected" if projected else ""}" style="{style}" title="{fmt(over)}m past original finish"></i>'
        deptext = ', '.join(task["dependencies"]) or 'none'
        over_chip = f'<span class="chip over">+{fmt(over)}m finish</span>' if over else ''
        rows.append(f'<div class="task-block {"critical-task" if task["id"] in critical else ""}" data-node="{index}" data-begin="{fraction(begin)}" data-finish="{fraction(end)}" id="{name}-task-{index}">'
                    f'<div class="chart-row task-head"><div class="label">{esc(task["id"])} · {esc(task["title"])} {chip(task["status"])} '
                    f'{over_chip}'
                    f'<small>{esc(task["stream"])} · Depends on {esc(deptext)}</small></div><div class="track">{header_marks}{now_line()}</div></div>')
        rendered, marked_events = [], set()
        for kind in ("build", "review"):
            lanes = [(s, False, f'a{si}') for si,s in enumerate(observed) if s["kind"] == kind] + [(s, True, f'f{si}') for si,s in enumerate(future) if s["kind"] == kind]
            if not lanes:
                rows.append(f'<div class="chart-row lane {kind}"><div class="label"><span class="lane-name">{kind.title()}</span><span class="lane-meta">No segment recorded</span></div><div class="track">{now_line()}</div></div>')
            for segment, projected, lane_id in lanes:
                a, b = interval(segment, "segment", now)
                if name == "recent" and (b <= lo or a >= hi):
                    continue
                rendered.append((segment, projected, lane_id))
                colour = palette[(segment["provider"], segment["model"])]
                code = f'R{segment["round"]}' if kind == "review" else 'B'
                status = 'planned' if projected else 'running' if segment.get("end") is None else 'done'
                label = f'Projection {code}' if projected else code
                clipped = ' · clipped at window edge' if a < lo or b > hi else ''
                desc = f'{kind.title()} {code} · {segment["model"]} · {segment["effort"]} · {display_time(segment["start"])} to {display_time(b.isoformat())}{clipped}'
                marks = ''
                style = position(a, b)
                if style:
                    marks += f'<span class="bar {kind} {"projection" if projected else "open" if segment.get("end") is None else ""}" style="{style};--mc:{colour}" title="{esc(desc)}" aria-label="{esc(desc)}"></span>'
                event_ids = []
                for ei, event in enumerate(data.get("events", [])):
                    scope = event["scope"]
                    affected = (scope.get("all") is True or task["id"] in scope.get("tasks", []) or scope.get("provider") == segment["provider"])
                    if affected:
                        ea, eb = interval(event, "event", now)
                        ea, eb = max(ea, a), min(eb, b)
                        if eb <= ea:
                            continue
                        style = position(ea, eb)
                        if style:
                            event_ids.append(f'E{ei+1}')
                            marked_events.add(ei)
                            marks += f'<i class="event-band" data-event="E{ei+1}" style="{style}" title="E{ei+1}: {esc(event["kind"]+": "+event["note"])}"></i>'
                result = '' if projected else f'<span class="lane-meta">{esc(segment.get("result", ""))}</span>'
                rows.append(f'<div class="chart-row lane {kind}" data-lane="{lane_id}"><div class="label"><span class="lane-name">{label} · {esc(segment["model"])} · {esc(segment["effort"])}</span> {chip(status)}'
                            f'<span class="lane-meta">{esc(segment["provider"])}{esc(clipped)}{esc(" · events " + ", ".join(event_ids)) if event_ids else ""}</span>{result}</div><div class="track">{marks}{now_line()}</div></div>')
        # Waiting is visible without inventing a build/review segment or cost.
        for ei, event in task_events:
            if ei in marked_events:
                continue
            ea, eb = interval(event, 'event', now)
            style = position(ea, eb)
            if style:
                rows.append(f'<div class="chart-row event-only"><div class="label"><strong>E{ei+1} · {esc(event["kind"])}</strong><span class="lane-meta">{esc(event["note"])} · event only</span></div><div class="track"><i class="event-band" data-event="E{ei+1}" style="{style}"></i>{now_line()}</div></div>')
        for review, projected, review_id in rendered:
            if review['kind'] != 'review' or not lo <= timestamp(review['start']) < hi:
                continue
            builds = [(s,p,lid) for s,p,lid in rendered if s['kind']=='build' and timestamp(s['end'] or data['project']['as_of']) <= timestamp(review['start'])]
            if builds:
                build, build_projected, build_id = max(builds,key=lambda x:timestamp(x[0]['end'] or data['project']['as_of']))
                handoffs.append(f'<path class="handoff{" projected" if projected or build_projected else ""}" data-node="{index}" data-from-lane="{build_id}" data-to-lane="{review_id}" data-x="{fraction(timestamp(review["start"]))}"><title>Build to review handoff</title></path>')
        rows.append('</div>')
    for marker in data.get("milestones", []):
        at = timestamp(marker["target"])
        if name == 'recent' and not lo <= at < hi:
            continue
        rows.append(f'<div class="chart-row marker-row"><div class="label"><strong>{esc(marker["id"])} · {esc(marker["name"])}</strong> {chip(marker["status"])}'
                    f'<span class="lane-meta">{esc(display_time(marker["target"]))} · {esc(", ".join(marker["required_reviewers"]))}{" · outside window" if not lo<=at<=hi else ""}</span></div>'
                    f'<div class="track"><i class="marker {esc(marker["kind"])}" style="--x:{fraction(at)*100:.6f}%" title="{esc(marker["name"])}{" (outside window)" if not lo<=at<=hi else ""}"></i>{now_line()}</div></div>')
    for change in data.get("rebaselines", []):
        at = timestamp(change["at"])
        if lo <= at <= hi:
            rows.append(f'<div class="chart-row rebaseline-row"><div class="label"><strong>Rebaseline · {esc(change["reason"])}</strong><span class="lane-meta">{esc(display_time(change["at"]))} · {esc(change["approver"])}</span></div>'
                        f'<div class="track"><i class="marker rebaseline" style="--x:{fraction(at)*100:.6f}%"></i>{now_line()}</div></div>')
    paths = ''.join(f'<path class="dependency" data-from="{indices[dep]}" data-to="{i}" marker-end="url(#{name}-arrow)"><title>{esc(dep)} → {esc(tasks[i]["id"])}</title></path>'
                    for i in visible for dep in tasks[i]["dependencies"] if indices[dep] in visible)
    paths += ''.join(handoffs)
    body = (f'<p class="muted">{esc(display_time(lo.isoformat()))} – {esc(display_time(hi.isoformat()))}</p>'
            '<p class="muted">Scrollable timeline: swipe or scroll horizontally to see all times. Task and lane labels stay visible.</p>'
            '<div class="chart-scroll" tabindex="0" role="region" aria-label="Scrollable timeline"><div class="chart">'
            '<div class="chart-row axis"><div class="label">Task · lane · model · effort · status</div><div class="track">' + ''.join(ticks) + '</div></div>'
            '<div class="plot">' + ''.join(rows) + f'<svg class="connections" aria-hidden="true"><defs><marker id="{name}-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="var(--quiet)"/></marker></defs>{paths}</svg></div></div></div>'
            '<p class="chart-note">Solid build; striped review. Each segment has its full model, effort, round and status beside it. '
            'Grey ghost: original estimate. Red rail: finish past original (dashed = forecast). Thin navy tick: build/review handoff. Dotted arrows: dependencies. '
            'Amber bands: scoped events; E numbers refer to the events table. Vertical navy line: now. '
            'Dashed bars divide the remaining forecast in proportion to original allocations; they are estimates. Scroll horizontally on narrow screens.</p>')
    return section_html('Whole-run timeline' if name=='whole' else 'Recent timeline', body, name, collapsed=name!='recent')


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


def render(data, mode="report", theme="auto", recent_hours=4):
    validate(data)
    require(mode in {"propose", "report", "final"}, "mode must be propose, report or final")
    require(theme in {"auto", "light", "dark"}, "theme must be auto, light or dark")
    require(type(recent_hours) in {int, float} and math.isfinite(recent_hours) and recent_hours > 0,
            "recent-hours must be positive and finite")
    project, tasks = data["project"], data["tasks"]
    now = timestamp(project["as_of"])
    identities = {(s["provider"], s["model"]) for t in tasks for s in t["segments"]}
    identities |= {(t["owner"]["provider"], t["owner"]["model"]) for t in tasks}
    identities |= {(a["provider"], a["model"]) for t in tasks for a in t.get("baseline", {}).get("allocations", [])}
    palette = {key: f'var(--model-{i % 6})' for i, key in enumerate(sorted(identities))}
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
    content += f'<div class="facts"><div><strong>Next milestone / gate</strong>{next_text}</div><div><strong>Original plan</strong>{"Approved " + esc(display_time(data["approval"]["at"])) + " · " + esc(data["approval"]["approver"]) if data.get("approval") else "Proposal · approval pending"}</div>'
    content += '<div class="critical"><strong>Current critical path · remaining forecast durations</strong>' + (' → '.join(cp_refs) or 'No remaining tasks') + '</div></div></header>'
    stale = [t['id'] for t in tasks if t['status'] not in {'done','cancelled'} and timestamp(t['forecast']['end']) < now]
    if stale:
        content += '<p class="muted">Stale forecasts: ' + esc(', '.join(stale)) + '. Finish overruns are lower bounds at as-of; update forecasts before relying on the schedule.</p>'
    decisions = decision_records(data)
    pending = [record for record,current in decisions if current and record['status']=='pending']
    if pending:
        content += '<aside class="decision-strip" aria-label="Pending decision questions"><strong>Awaiting answer</strong>' + ''.join(f'<p>{esc(d["id"])} · {esc(d["owner"])} · affects {esc(", ".join(d["tasks"]))}</p>' for d in pending) + '<a href="#owner">Decision record</a></aside>'
    content += '<div class="key"><span><i class="ghost-key"></i>Original baseline</span><span><i class="over-key"></i>Overrun</span><span><i class="projection-key"></i>Projection</span>'
    content += ''.join(f'<span><i class="swatch" style="--mc:{colour}"></i>{esc(model)} · {esc(provider)}</span>' for (provider, model), colour in sorted(palette.items())) + '</div>'
    points = [now, timestamp(project["start"])]
    for task in tasks:
        points += [timestamp(task["forecast"]["start"]), timestamp(task["forecast"]["end"])]
        if task.get("baseline"):
            points += [timestamp(task["baseline"]["start"]), baseline_end(task["baseline"])]
    points += [timestamp(m["target"]) for m in data.get("milestones", [])]
    lo, hi = min(points), max(points)
    if hi == lo:
        hi += timedelta(hours=1)
    content += timeline(data, 'recent', now-timedelta(hours=recent_hours), now+timedelta(hours=recent_hours), palette)
    if boundary:
        content += timeline(data, 'whole', lo, hi, palette)
    content += '<div class="tables">'
    content += decision_table(decisions)
    running = [(t,s) for t in tasks for s in t['segments'] if s.get('end') is None]
    content += table('Running now', ['Model / effort', 'Task / lane', 'Observed minutes'],
                     [[identity_label(s), esc(t['id']+' · '+t['title'])+f'<small>{esc(s["kind"])} · round {s["round"]} · {esc(s["host_id"])}</small>', fmt(segment_minutes(s, project['as_of']))] for t,s in running], 'running')
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
    content += '<footer>Private ledger report · forecasts are estimates · original approved allocations remain frozen. Rebaselines record decisions; event bands show exposure, not proven causation.</footer></main>'
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(project['name'])+' · plan report</title><style>'+CSS+'</style></head><body>'+content+'<script>'+SCRIPT+'</script></body></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mode', choices=('propose','report','final'), default='report')
    parser.add_argument('--theme', choices=('auto','light','dark'), default='auto')
    parser.add_argument('--recent-hours', type=float, default=4, help='Hours before and after as-of in the recent timeline (default: 4 each)')
    args = parser.parse_args()
    try:
        require(args.ledger.resolve() != args.output.resolve(), 'output must not overwrite ledger')
        data = json.loads(args.ledger.read_text(encoding='utf-8'))
        html = render(data, args.mode, args.theme, args.recent_hours)
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
