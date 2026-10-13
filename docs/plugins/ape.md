# ape

You have a specific gap and a hunch that someone else has solved it. ape reads their
source, compares it with yours, and writes a report where every recommendation cites
lines at a pinned commit and comes with one small experiment to try. It never runs the
other project's code and never edits yours.

## Try it

Study one repository you already have in mind:

```text
$t3-ape study https://github.com/python/cpython How are parser error cases tested? Compare with this project and propose a small experiment.
```

Or let it find candidates: `$t3-ape forage` followed by the gap you want to close.
`study` reads one named GitHub repository; `forage` searches GitHub and compares up to
five. Send `$t3-ape doctor` first on a new machine or provider.

## What you get

A report pinned to the source commit, with these sections: Provenance, Overlap, Adopt,
Adapt, Reject and Command case. Each recommendation names the local files it would
touch, its effort and tradeoffs, and a bounded experiment with conditions for keeping
or abandoning it. An empty Adopt section is a valid answer. The agent returns the
source revision and the report path. A proposed experiment is a suggestion, not a
measured improvement.

Research happens in a workspace of cloned repositories outside your project.
`$t3-ape clean` removes it.

## Operations

`doctor`, `forage`, `study`, `clean`. The
[entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/ape/entry.md)
names the file the agent loads for each one.

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

`clean` removes only workspaces that carry the `.ape-workspace.json` marker written
when the workspace was created. Older unmarked folders are left alone; inspect and
archive them yourself before creating a new workspace. Creating one never adopts
existing data.

ape stays read-only in your project. It never executes third-party code, and it never
starts implementing a recommendation without a separate request. Unit tests don't show
how a given model behaves; see [compatibility](../compatibility.md).
