# Ledger version 1

Read before writing a ledger or interpreting its calculations. The coordinator
is the sole writer. JSON must contain finite numbers; timestamps use ISO 8601
with an explicit UTC offset or `Z`. Displayed absolute dates and local clocks
convert to Australia/Sydney but omit zone names and offsets, including tooltips
and axes. Source timestamps and literal sources keep their original offsets/text.
Elapsed arithmetic uses UTC across daylight-saving transitions. Durations are minutes.

## Objects

| Object | Fields |
| --- | --- |
| Root | `version: 1`, `project`, `approval` (null before approval), nonempty `tasks`; arrays `milestones`, `events`, `decisions`, `rebaselines` (default empty). Legacy `needs_owner` is still accepted. |
| Project | `name`, `timezone: "Australia/Sydney"`, `start`, `as_of`, human-readable `status`. As-of is the observed clock boundary, never later than the renderer's clock. Historical boundaries are valid. |
| Approval | `at`, `approver`. Every task then requires an original `baseline`. Preserve approved values. |
| Task | Unique `id`, `title`, `stream`, `dependencies` (task IDs), `owner` identity, `status`, `forecast`, `segments`, optional `value` (nonempty one-sentence stakeholder benefit), optional `thread` (a link with a scheme, such as `https://…` or `t3-thread://…`, to the task's own thread), `baseline`, `cost`, `issues` and `prs` (text reference arrays). Status: planned, ready, running, review, blocked, done, cancelled. Running now uses Model, Task ID and Value columns, falling back to title when value is absent. Effort remains in segment detail and calibration. |
| Identity | Nonempty `provider`, `model`, `effort`. Record actual identities; use the literal `unknown` where unexposed. |
| Baseline | `start`, `allocations` (nonempty), `review_rounds` (nonnegative integer). The baseline finish is start plus allocation minutes. The original is immutable by convention; a standalone file cannot prove its own edit history. |
| Allocation | `kind` (build/review), `minutes` (nonnegative), identity fields. Multiple allocations allow known model changes. Use sequential wall-clock budgets; do not hide parallel work in one task. |
| Forecast | `start`, `end`, both required and ordered. Current expectations are separate from approved estimates. |
| Segment | Unique task-local `id`, `start`, `end` (null while open), `kind`, `round` (build: 0; review: positive integer), identity fields, `host_id`, optional `result` text and `cost`. All observed segments lie between run start and as-of. Terminal tasks have no open segments. Split segments at identity changes and pauses. |
| Milestone/gate | Unique `id`, `name`, `kind` (milestone/gate), `target`, human-readable `status`, `required_reviewers` (text array), `tasks` (task IDs). Targets may be future. |
| Event | `start`, optional `end`, `kind`, `note`, `source`, `scope`. Kind examples: outage, rate limit, credit exhaustion, host bug, user away, waiting on decision, other external. Scope is exactly one of `{"all": true}`, `{"provider": "provider-id"}`, `{"tasks": ["task-id"]}`. Provider scope covers tasks owned by or containing segments from that provider. Events annotate exposure, not proven causation or automatic deductions. |
| Decision record | Stable question `id`, `question` (actual prompt), `owner`, `status` (pending/decided), `tasks` (task IDs). `answer`, `asked_at`, `decided_at` default to `"unknown"`; known timestamps need offsets. Decided records require the actual nonempty answer. Pending records have unknown answer/decision time. Optional `recommendation`, `rationale`, `source` text. Append snapshots with the same ID for replies or amendments; earlier snapshots stay in history and the last is current. |
| Legacy owner item | `needs_owner` entries retain `question`, `owner`, human-readable `status`, `tasks`, optional `recommendation`. Decision metadata above may be added. A closed legacy item without an actual answer is shown as answer not recorded, never a fabricated decision. Add a stable `id` before appending a corresponding `decisions` snapshot. |
| Rebaseline | `at`, `reason`, `approver`, `tasks` mapping task IDs to complete replacement baseline objects. Append chronologically after approval. Preserve the original task baseline and every previous entry; update the task forecast separately. |

Dependencies must name tasks in this ledger and form a directed acyclic graph.
They describe finish-to-start ordering. The critical path is the longest
remaining dependency chain weighted by remaining forecast duration; completed
and cancelled tasks contribute zero. This is a forecast, not a scheduler or a
resource-constrained finish guarantee. Unfinished forecasts behind as-of are
stale and should be updated by the coordinator.

## Asking and recording decisions

The coordinator batches material questions with its recommendation first through
the host-native input/question tool and records the real prompt and observed time.
It checks current records before asking, continues independent authorised work
while pending, then appends the actual reply and decision time when observed.
Keep old records; a changed answer is another snapshot, not an overwritten decision.
Unknown metadata stays unknown. Recommendations and silence are not replies.
The renderer neither asks questions nor calls a model, input API or scheduler.
A render never substitutes for prompting the owner. The report calls this section
**Decision record** and distinguishes pending questions from recorded answers.

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

Overruns always use the original finish, even after a
rebaseline. Projected or observed finish past it is labelled accordingly. Final
accuracy uses segment duration, not the task's start-to-finish span, so recorded
waiting time does not inflate model performance metrics. Overlapping delegates
do not make their summed minutes a project wall-clock duration.

## Chart

1. Each task is one 22px row under its stream. Solid bars are build, hatched
   bars are review, and real gaps stay empty. Overlapping work stacks inside
   the row; durations are never summed or serialized.
2. Model, effort, round, times and result are on each bar's hover text and
   accessible label, not printed beside it. The task ID is on the row's hover.
3. Titles show as written. Each `#123` in a title links to the task's `thread`;
   a title without a number becomes the link. Without `thread` nothing links.
4. Hue follows the provider (Claude orange/red, OpenAI green, DeepSeek blue,
   Google purple, xAI slate, others teal or pink); shade separates its models.
   The key names every model, so colour is never the only cue.
5. Forecast bars are dashed outlines. They divide the remaining forecast in
   proportion to original allocations (review only during an active review)
   and do not infer new budgets. The build share keeps the model now building.
   Running tasks show their ETA clock; waiting tasks name what they wait on.
6. Idle stretches over an hour are cut from the axis and labelled. Once work
   has been observed, time more than `--recent-hours` ahead (default four) is
   compressed to at most 22% of the width and shaded.
7. The progress chart hides finished tasks and starts where the oldest
   unfinished task began. Stream headers count what is hidden. When nothing
   remains it shows work that ran in the last `--recent-hours` instead.
8. The mtoks column is millions of reported tokens per task, with stream
   subtotals and a project total split by model. Unreported is a dash, never
   zero; `+` marks a known subtotal. Totals always cover every task.
9. The bar above the chart is estimated work done, weighted by baseline minutes
   (forecast minutes without a baseline); cancelled tasks are excluded.
10. Milestone and gate targets are diamonds on the stream that holds most of
    their tasks. Baselines, overruns, events and rebaselines are in their
    tables, not on the chart.

The header has a compact pending-question indicator linked to Decision record,
rather than a prompt form. The progress chart is first and expanded. Each later user-facing section has its own
closed native disclosure when it contains data; empty sections are omitted, including
their headings and notes. Task rows with neither baseline nor issue/PR references
do not populate the original-baseline section. Opening one disclosure does not open
the others. Whole-run appears only in `propose` and `final`; `report` omits it entirely,
including its task links. Rendered section IDs remain stable.
Refresh active forecasts at every coordinator update.
Report mode omits Recently completed; final mode retains completion detail and
calibration. Future-fixture replay requires an explicit flag and visible warning;
it is never live evidence.

The synthetic example under `examples/long-run.json` exercises multi-stream
work, model changes, unknown costs, rebaselines, outages and owner gates. Copy it
only as a structural starting point; replace all invented observations before use.
