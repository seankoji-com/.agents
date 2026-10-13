# ape

Find ideas that transfer to your project.

## When to use it

You have a specific local gap and want to compare an approach with working source.
Use `study` for one named GitHub repository; use `forage` to discover candidates.

## Try it

After [installation](../getting-started.md), run in your terminal:

```sh
t3-plugins prompt ape doctor
```

Paste the printed line into a T3 thread attached to your project. Once readiness is
clear, generate a task prompt:

```sh
t3-plugins prompt ape study https://github.com/python/cpython 'How are parser error cases tested? Compare with this project and propose a small experiment.'
```

Paste that output into T3. Replace the sample task or path with your own.
If you installed [skill adapters](../slash-commands.md), select **t3-ape**
from `/` and append the same request instead.

## Operations

`doctor`, `forage`, `study`, `clean`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/ape/entry.md) names the file to load for each operation.

## What you get

A report pinned to the source commit, with Provenance, Overlap, Adopt, Adapt, Reject
and Command case sections. Each recommendation names local target files, effort,
tradeoffs and a bounded experiment. An empty Adopt section is a valid result.
The agent returns the source revision and report path; proposed experiments are
not measured improvements.

## Jobs and workers

`study` and `forage` run as one [job](../architecture.md#whole-jobs); `doctor` and
`clean` stay direct. Before the job starts, the agent pins each candidate's source
text at its resolved commit with `scripts/snapshot_source.py`.

- `ape/source-researcher` compares one pinned candidate with your project: one slot
  for `study`, up to five for `forage`. A `study` slot may use one follow-up on the
  same source and focus.
- `ape/synthesizer` compares the accepted `forage` reports and proposes bounded
  experiments.

A report is accepted only when `scripts/validate_report.py` finds its sections, pinned
revisions and snapshot hashes, line-numbered citations, coverage of every candidate
and the coordinator's inspection receipts in the actual files. That proves the
evidence trail, not that a recommendation is right. A proposal never authorizes
implementation or running the experiment; that needs a separate request.

## Limits

Cleanup accepts only workspaces carrying a matching `.ape-workspace.json` marker
from the initializer. Unmarked legacy folders are left untouched; inspect and archive
them manually before creating a new workspace. Initialization does not adopt existing data.

Research stays read-only in the current project. It never executes third-party code or silently starts implementing recommendations. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
