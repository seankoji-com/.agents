# Score line graph for iterative reviews

For scored `review-loop` runs, including Hillclimb, save a self-contained HTML
score line graph using the bundled Python 3.10+ stdlib renderer
`skills/review/scripts/render_score_chart.py`. Use one cumulative JSON ledger
and one stable HTML output path throughout the run.

## Cadence and ownership

- **Main-thread runs**: update the ledger and regenerate the HTML after every
  completed evaluation, including the baseline and panel entry, after recovery
  and at handback. Append incomplete evaluations with their known scores and
  failure reason. In T3, preview the written file with `html_preview`, then show
  it with `html_render`. Preserve accessible links to the ledger and HTML at
  handback.
- **Isolated `implement` lead delegates**: delegates cannot call `html_render`
  and T3 wakes the parent on pause or completion. The lead maintains the JSON
  score ledger in its verified ignored worktree directory and returns its
  absolute path and structured score history in every pause and handoff report.
  The main thread renders the chart at every lead pause, recovery handback, and
  final handback.
- **Without inline HTML**: use the accessible file links and give a concise
  text summary of round scores, target and failures. If rendering fails, keep
  the ledger and report the chart error separately from the evaluation result.

## CLI usage

Run from any working directory with absolute paths:

```sh
python3 /installed/review/scripts/render_score_chart.py \
  /worktree/ignored/score-ledger.json \
  --output /worktree/ignored/score-chart.html
```

Verify the ledger and output paths with `git check-ignore` before writing inside
a repository worktree. Keep live ledgers and charts untracked and out of GitHub;
checked-in examples and test fixtures must be synthetic.

## Ledger schema (`version: 1`)

See `skills/review/examples/score-ledger.json` for a complete synthetic example.

- `version`: integer `1`.
- `run`: `{ title, id, skill, status, scale: { min, max, precision } }`.
  `precision` is decimal places (0 to 3), matching the run's decimal places.
  - `status`: `in-progress`, `passed`, `passed-revised`, `goal-not-met`,
    `stopped`, or `blocked`.
- `reviewers`: nonempty list of `{ id, label, role? }`. Each reviewer gets a
  stable T3 `--chart-*` colour and distinct marker shape.
- `eras`: nonempty list of `{ id, label, target, original_target?, historical,
  comparable_to_prev, note?, recovery? }`.
  - `recovery` (optional on era transitions): `{ kind, label, trigger,
    diagnosis, fix }` where `kind` is `automatic`, `continuation`, or
    `rebaseline`.
  - Set `comparable_to_prev: false` and `historical: true` on the prior era
    whenever recovery revises the rubric, target, required checks, or roster.
    The chart breaks lines across non-comparable boundaries, hatches historical
    rounds, and steps the dotted target line while keeping a faint ghost of
    `original_target`.
  - A continuation's ledger starts with every earlier run's eras and rounds;
    earlier round ids carry their run's prefix. Its first era has a
    `continuation` recovery and is comparable only when its `fingerprint`
    (contract, phase and scorers as it opens) matches the earlier era's
    `end_fingerprint`. Render that one ledger, not one per run.
- `rounds`: nonempty list in chronological order of `{ id, label, candidate?,
  era, phase, expected_reviewers, status, failure_note?, scores }`.
  - `phase`: `primary`, `panel`, or `review`.
  - `status`: `scored`, `unscored`, or `incomplete`. `unscored` and `incomplete`
    require a nonempty `failure_note`.
  - `scores`: list of `{ reviewer, score, retried?, retry_note?, status?,
    failure_note?, bullets?, dimensions? }`.
    - Every numeric `score` requires `bullets`: **3 to 5** concise bullet
      strings explaining how the score was reached.
    - `dimensions` (optional): list of `{ name, score, weight? }`. When weights
      are present, the inspector displays weighted bars and `score × weight`
      arithmetic.
    - `retried: true` requires `retry_note` and adds a dashed warning ring and
      `↻` badge on the scored point.
    - Missing/timed-out judge entries use `score: null` with `status` and
      `failure_note`.

## Visual and comparability semantics

- **Unscored failures** (e.g., build/run failure) are never plotted as `0`. They
  occupy a full-height hatched `NO SCORE · NOT 0` column and an off-axis failure
  marker, breaking numeric lines.
- **Incomplete panels** plot completed reviewer scores while breaking the gating
  minimum and showing an off-axis `gate n/a` marker.
- **Gating score** is computed strictly across `expected_reviewers`: when every
  expected reviewer has a numeric score in a multi-reviewer round, the gate is
  the minimum score and its inspector includes the minimum-setting reviewer's
  rationale and component dimensions.
- **Interactive inspector**: hovering or focusing any score, gate bar, failure
  pill, or recovery badge previews its 3–5 bullet rationale and component
  dimensions in the docked panel below the chart; clicking or pressing `Enter`
  pins it, arrow keys step marks, and `Esc` resets. A collapsible HTML score
  table provides screen-reader and copy-paste access.
