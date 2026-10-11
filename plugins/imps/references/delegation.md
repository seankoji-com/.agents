# Delegated mode in imps

Load this when the plan uses `"execution": {"mode": "delegated"}`. The rules for when
to delegate, which model to use and what a child brief holds are in
`PKG/shared/delegation.md`; this file covers only how imps carries them out. The
core runs at most `execution.concurrency` children at once (plan default 4).

## Targets from the routing config

When `t3-plugins resolve <role> --capabilities FILE` returns candidates, put the chosen
one in a task's `target` with its `providerInstanceId`, `model` and `runtimeMode`; the
core passes `runtimeMode` to `delegate_task`. If the candidate carries `owner_action`,
repeat it in the report. For review, run
`t3-plugins resolve reviewer --capabilities FILE --implementer-lineage <lineage>` and
set `roles.reviewer.chain` to one `fixed` entry per candidate, with the same fields, in
the order printed: independent candidates first, then unverified ones (`independent:
null`), then the same lineage. The core advances the chain only when a target is
unavailable. A reviewer that is not `independent: true` leaves independence unverified
in the report. Repository policy in `.t3-plugins/imps.json`
still wins.

Without a routing config there is no lineage data. The default reviewer chain then
picks another catalog provider, which does not establish a different lineage. Say in
the report that reviewer independence is unverified.

## Plan tasks

```json
"tasks": [
  {"id": "fix-parser", "purpose": "fix tokenising of quoted fields", "files": ["src/parser.py", "tests/test_parser.py"],
   "requirement_ids": ["REQ-QUOTED"], "acceptance": ["tests/test_parser.py passes"],
   "verification": "python3 -m unittest tests.test_parser", "expected_output": "a commit on the task branch"},
  {"id": "callers", "purpose": "list every caller of parse_row and how it handles errors", "kind": "read"}
]
```

- `files` is the task's ownership, as globs matched per path segment: `*` stays within one directory (`src/*.py` does not own `src/util/x.py`) and `**` spans directories (`src/**/*.py`). Changes outside it make the core reject the result.
- `kind: read` tasks may not write. They run in parallel with anything else.
- `target` (`{"providerInstanceId", "model"}` from the live catalog) pins a provider. A pinned target that is unavailable blocks the task instead of being swapped. Without `target`, the implementer role chain picks one (default: your own provider and model).
- `depends_on` orders tasks. Integration follows the same order.

The core writes each child's brief from these fields, the run's constraints and the requirement wording. The child cannot see this conversation, so put everything it needs into the task fields.

## Isolation

T3 children inherit the parent's checkout and have no worktree parameter. Before the first writing task, `next` runs a probe for each writer provider. It creates a sibling worktree under the state root, asks a child to write a nonce file there, and then reads the file itself.

- **Probe passed** (the child can write outside your checkout): writers run in parallel, each in its own worktree and branch `t3p/<run-id>/<task-id>`.
- **Probe failed:** writers run one at a time in your own checkout, the one place the child is known to be able to write. Each writer is judged only on the commits it adds after its dispatch. Read-only tasks still run in parallel.

The result is stored per provider in the run's `probes` and shown in the report.

## Results

Each child ends its final message with one fenced block tagged `json t3-result`. The core extracts it from the observation, stores it as an artifact and validates it. Claimed files and commits must exist in the task worktree, and the child may not touch constraints, authorisation or completion. Malformed output gets exactly one correction round, a new `delegate_task` call with a new `clientRequestId`. If the correction is also malformed, the task blocks with the raw output kept.

## Integration and repair

In parallel mode, each accepted writer is integrated as soon as it is ready (`git merge --no-ff` into your checkout, one at a time). A task that depends on a writer starts only after that writer is integrated, so its new worktree contains the prerequisite. Serial mode needs no integration: the writers already worked in your checkout. A failed merge blocks the run and keeps every worktree and branch. The report lists each one with its cleanup command. A review repair creates a `repair-N` task: in parallel mode it gets a new worktree from the integrated HEAD; in serial mode it works in your checkout. The repair limit applies per stage: checks, acceptance and review each allow `repair_limit` repair rounds. After an adverse review, any edit made outside `record --kind repair` still costs a review repair round; it never buys a fresh review.
