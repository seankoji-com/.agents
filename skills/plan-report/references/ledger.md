# Ledger version 1

Read before writing a ledger or interpreting its calculations. The coordinator
is the sole writer. JSON must contain finite numbers; timestamps use ISO 8601
with an explicit UTC offset or `Z`. All displayed times use Australia/Sydney,
absolute dates, AEST/AEDT and UTC offset. Elapsed arithmetic uses UTC, including
across daylight-saving transitions. Durations are minutes.

## Objects

| Object | Fields |
| --- | --- |
| Root | `version: 1`, `project`, `approval` (null before approval), nonempty `tasks`; arrays `milestones`, `events`, `needs_owner`, `rebaselines` (default empty). |
| Project | `name`, `timezone: "Australia/Sydney"`, `start`, `as_of`, human-readable `status`. As-of is the observation boundary. |
| Approval | `at`, `approver`. Every task then requires an original `baseline`. Preserve approved values. |
| Task | Unique `id`, `title`, `stream`, `dependencies` (task IDs), `owner` identity, `status`, `forecast`, `segments`, optional `baseline`, `cost`, `issues` and `prs` (text reference arrays). Status: planned, ready, running, review, blocked, done, cancelled. |
| Identity | Nonempty `provider`, `model`, `effort`. Record actual identities; use the literal `unknown` where unexposed. |
| Baseline | `start`, `allocations` (nonempty), `review_rounds` (nonnegative integer). The baseline finish is start plus allocation minutes. The original is immutable by convention; a standalone file cannot prove its own edit history. |
| Allocation | `kind` (build/review), `minutes` (nonnegative), identity fields. Multiple allocations allow known model changes. Use sequential wall-clock budgets; do not hide parallel work in one task. |
| Forecast | `start`, `end`, both required and ordered. Current expectations are separate from approved estimates. |
| Segment | Unique task-local `id`, `start`, `end` (null while open), `kind`, `round` (build: 0; review: positive integer), identity fields, `host_id`, optional `result` text and `cost`. All observed segments lie between run start and as-of. Terminal tasks have no open segments. Split segments at identity changes and pauses. |
| Milestone/gate | Unique `id`, `name`, `kind` (milestone/gate), `target`, human-readable `status`, `required_reviewers` (text array), `tasks` (task IDs). Targets may be future. |
| Event | `start`, optional `end`, `kind`, `note`, `source`, `scope`. Kind examples: outage, rate limit, credit exhaustion, host bug, user away, waiting on decision, other external. Scope is exactly one of `{"all": true}`, `{"provider": "provider-id"}`, `{"tasks": ["task-id"]}`. Provider scope covers tasks owned by or containing segments from that provider. Events annotate exposure, not proven causation or automatic deductions. |
| Needs owner | `question`, `owner`, human-readable `status`, `tasks` (task IDs). Optional `recommendation` text. |
| Rebaseline | `at`, `reason`, `approver`, `tasks` mapping task IDs to complete replacement baseline objects. Append chronologically after approval. Preserve the original task baseline and every previous entry; update the task forecast separately. |

Dependencies must name tasks in this ledger and form a directed acyclic graph.
They describe finish-to-start ordering. The critical path is the longest
remaining dependency chain weighted by remaining forecast duration; completed
and cancelled tasks contribute zero. This is a forecast, not a scheduler or a
resource-constrained finish guarantee. Unfinished forecasts behind as-of are
stale and should be updated by the coordinator.

## Cost observations

`cost` is an object with optional `tokens`, `turns`, `usd`. Each metric is either
the literal `"unknown"` (also the default for omitted metrics) or:

```json
{"value": 1200, "source": "synthetic host event 7: scoped total tokens", "basis": "reported"}
```

Values are nonnegative; tokens/turns are integers. `basis` is `reported` or
`host-estimate`. Every known value needs a source, including zero. See
[host evidence](host-costs.md) before collecting usage. For each metric choose
task scope or segment scope; supplying both is invalid. Task totals spanning
multiple actual provider/model pairs stay in an unattributed bucket. Known
subtotals with missing observations are partial; unknown never becomes zero.

## Calibration and schedule

Final calibration includes only done tasks with original baselines. For each
task/kind, compare the set of planned `(provider, model, effort)` identities
with actual segments. Any mismatch, including an added model or changed effort,
makes that pair **not comparable**. Keep its original estimate and observed
duration visible and exclude it from like-for-like ratios. Unapproved plans
also have no comparable ratios. For comparable identities, sum original
allocation minutes and segment elapsed minutes. Ratio is actual / estimate;
a zero estimate has no defined ratio. Costs are reported independently of
comparability. Actual review rounds count distinct positive review round numbers,
so a paused round split into several segments counts once. Unknown identities
are excluded from comparable ratios even when both sides say `unknown`.

Baseline ghosts and overruns always use the original finish, even after a
rebaseline. Projected or observed finish past it is labelled accordingly. Final
accuracy uses segment duration, not the task's start-to-finish span, so recorded
waiting time does not inflate model performance metrics. Overlapping delegates
do not make their summed minutes a project wall-clock duration.

The renderer adopts the Lane Ledger design: separate labelled build/review
lanes, status chips and an owner-decision strip above both charts. Full identities
sit outside bars so short or clipped segments remain readable. Provider events
shade only matching-provider lanes during intersecting segment times; task/all
events likewise intersect those lanes. Model colour is supported by explicit text.
Milestones and rebaseline markers each get a separate row to avoid label collisions.
Forecast bars divide the remaining forecast interval in proportion to original
allocations (review only during an active review); they do not infer new budgets.

The synthetic example under `examples/long-run.json` exercises multi-stream
work, model changes, unknown costs, rebaselines, outages and owner gates. Copy it
only as a structural starting point; replace all invented observations before use.
