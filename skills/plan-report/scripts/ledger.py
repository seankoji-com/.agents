"""Validated plan-ledger arithmetic. Python 3.10+, standard library only."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
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
        "%d %b %Y %H:%M %Z (UTC%z)")


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
        text_fields(allocation, IDENTITY, f"{label}.allocation")
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
    order, visiting = [], set()

    def visit(tid):
        require(tid in by_id, f"unknown dependency id: {tid}")
        require(tid not in visiting, f"dependency cycle at {tid}")
        if tid in order:
            return
        visiting.add(tid)
        for dep in by_id[tid]["dependencies"]:
            visit(dep)
        visiting.remove(tid)
        order.append(tid)

    for tid in by_id:
        visit(tid)
    for collection in ("milestones", "events", "needs_owner", "rebaselines"):
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
    for item in data.get("needs_owner", []):
        text_fields(item, ("question", "owner", "status"), "needs_owner item")
        require(isinstance(item.get("tasks"), list)
                and all(isinstance(x, str) and x in by_id for x in item["tasks"]), "needs_owner has unknown task id")
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


def task_end(task, as_of):
    if task["status"] in {"done", "cancelled"} and task["segments"]:
        return max(timestamp(s["end"]) for s in task["segments"])
    return max(timestamp(task["forecast"]["end"]), timestamp(as_of))


def critical_path(data):
    """Longest remaining dependency chain, weighted by forecast wall minutes."""
    tasks = {t["id"]: t for t in data["tasks"]}
    now, memo = timestamp(data["project"]["as_of"]), {}

    def chain(tid):
        if tid in memo:
            return memo[tid]
        task = tasks[tid]
        if task["status"] in {"done", "cancelled"}:
            return (0, [])
        previous = max((chain(dep) for dep in task["dependencies"]), default=(0, []), key=lambda x: x[0])
        duration = max(0, (timestamp(task["forecast"]["end"]) - max(now, timestamp(task["forecast"]["start"]))).total_seconds())
        memo[tid] = (previous[0] + duration, previous[1] + [tid])
        return memo[tid]

    return max((chain(tid) for tid in tasks), default=(0, []), key=lambda x: x[0])[1]


def event_affects(event, task):
    scope = event["scope"]
    providers = {task["owner"]["provider"]} | {s["provider"] for s in task["segments"]}
    return (scope.get("all") is True or task["id"] in scope.get("tasks", [])
            or scope.get("provider") in providers)


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
            comparable = bool(data.get("approval")) and set(estimated) == set(actual)
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
