# Implementation and evaluation loop

At each issued evaluation round, the coordinator may add free supplemental reviews
under `PKG/shared/supplemental-reviews.md`, using one optional ledger for the round.
Dispatch the mandatory evaluator first. Extras require host-owned
`isolation: "worktree"` and clean committed scope; otherwise skip them without a
shared-checkout fallback. Keep extras out of this helper's evaluator
records and attempt budget. Close and request cancellation when the mandatory round
ends; never wait for extras. Verify concrete findings and save bound dispositions
in that ledger. Use its **Confirmed findings in Ralph** stop/report/rerun procedure;
this helper cannot append supplemental findings to an evaluator verdict. Preserve
the old verdict, carry remaining attempts into the replacement brief and require
fresh full-scope review. Supplemental workspace drift uses the existing fresh
evaluation path at the same attempt, with extras disabled. Required independence, fresh full-scope
acceptance and pending-run gates stay unchanged.

## Start and pin the contract

Inspect repository instructions, branch, working tree and intended PR base. Preserve
unrelated work. Use the current task worktree throughout; if the checkout cannot
safely hold this work, establish a task worktree before initialization and record
its absolute path. All writers run sequentially there. Do not create a worktree per
attempt, reset it, stash unrelated edits, or discard previous attempts.
Before initialization, run the sibling-work check in `PKG/shared/t3-runtime.md`
for this worktree and branch. Writers here run one at a time, so another active
thread on the same worktree or branch needs an owner decision before dispatch.

Discover T3's live schemas and call `orchestrator_capabilities`. If tools are absent,
try bounded discovery and the host's documented ACP transport before declaring
unavailable. Use only `delegate_task`, `task_status` and `task_cancel` for children,
with a fresh `delegate_task` for every agreement-bound review round.
Do not use `t3_thread_send` to continue a new agreement-bound review.

Use `PKG/shared/upfront-agreement.md` to inspect context and recommend exact work
and independent reviewer chains/options in one scoped agreement. Supplied choices
are answers. Preserve separate finite work/reviewer backups and all actual authors.
Only reconciled unavailability permits replacement; adverse feedback requires repair.
Ralph never degrades its different-lineage full evaluator requirement.

Show each target's resolved runtime mode during this interaction. The helper
validates advertised modes and records the broadest supported mode within the
parent boundary, or uses T3's `inherit` when supported modes are unadvertised.
OpenCode must explicitly use `full-access` to avoid the host's permission-stall
bug. If the parent is narrower or support is unadvertised, initialization stops;
the owner must select Full Access for a narrower parent before starting. If support
is still unadvertised, reconcile the fresh catalog or host version; do not infer
Full Access from the parent alone. Keep reviews
read-only regardless of their runtime mode. Cross-provider eligibility is checked
against the invoking provider, including when both targets share a gateway.

Pin the goal verbatim, observable acceptance criteria, verification commands,
verbatim repository constraints, ownership, unrelated dirty paths, authorization,
intended PR base and shared runtime instructions in the brief. Refresh the intended
remote base before evaluation when preparing a PR. The evaluator must challenge
the design and identify every finding, including blocker/major findings, against
that base and the full task diff. A mandatory repository review route still applies.
Check its constraints before the model-choice interaction. The selected evaluator
must satisfy both Ralph's independence rule and that route. If the chosen pair
cannot meet the repository gate, explain the conflict and ask for an eligible pair
before dispatch. If the gate requires a route Ralph cannot track with this pair,
report it as blocked.

Choose a writable checkpoint directory OUTSIDE the worktree, for example an
approved XDG state directory or task-specific temporary directory. Report its path.
Create `init.json` with `goal`, `brief`, `worktree`, `maxAttempts` (default 20),
`implementer`, `evaluator`, `admission` from `scripts/plan_review.py admit`, and
`capabilities` (the fresh structured T3 response).
Each target needs `providerInstanceId`, `model`, `lineage`, `lineageSource`, and
optional `options`. Options are an object map of advertised option ID to chosen
string or boolean value, not the catalog's option-definition array. Omitted or
null options mean no overrides. For example, the selected implementer portion is:

```json
{
  "implementer": {
    "providerInstanceId": "<chosen provider instance>",
    "model": "<chosen exact catalog model>",
    "lineage": "<verified model family>",
    "lineageSource": "owner-confirmed",
    "options": {"<advertised option ID>": "<chosen advertised value>"}
  }
}
```

Replace the placeholders from the live catalog and user selections; the evaluator
has the same shape. Initialize with `init --state FILE --input init.json`.
Only the parent writes checkpoints; never delegate access to this directory.

## One tracked task at a time

Call `next --state FILE`. Its `tool` names the T3 tool and its `dispatch` object is
that tool's complete input. A `delegate_task` dispatch pins `mode: async`, role,
target, a stable `clientRequestId` and a compact title (`R2 impl`, `R2 delta`,
`R2 review`) before dispatch. The task brief includes the goal, contract,
existing worktree, the latest implementation summary and evaluator report, every
failed task's summary, every recovery reason, and EVERY prior verdict, evaluation
gap and invalidation without truncation. Older completed reports stay in the
checkpoint, so the brief does not grow by a full report each round.
Every implementation and review round in a new agreement-bound run uses a fresh
`delegate_task`, including delta review. Delta passes still require full review.
Older pinned packages retain their historical continuation contract.

Retain the returned `taskId` immediately: `attach --state FILE --input FILE`, where
the JSON contains `clientRequestId` and the unmodified T3 response, including
`taskId`, its `childThreadId` or `threadId`, and any echoed `providerInstanceId`/`model`.
A thread other than the issued one is rejected. Discover the live schema;
never fill absent identity fields from the request. A lost response is uncertain
dispatch. Reconcile using the same request ID and exact arguments; never generate
a replacement task. A saved attached task means read its status, never redispatch.
Yield after dispatch unless independent work remains. T3's completion notification
wakes the parent; do not poll in a loop, sleep-wait, or start a watcher process.

On notification or resume, read `task_status` for the saved ID. Pass its structured
response to `observe --state FILE --input FILE`. A terminal task with pending child
runs still blocks the next stage. Reconcile those runs before proceeding. Failed,
interrupted or cancelled tasks block this run; preserve their summaries and IDs.
Later pending runs temporarily block a consumed round. Observe every saved task
again once those runs end; the helper restores the previous phase when identities
are verified and every consumed task is quiescent. A running delta follow-up shows
as a pending run on the earlier review that owns its thread; observe that review
again after the follow-up ends.

An unreported `model` is retained as unreported. The helper can verify it against
an exact target in the saved authoritative delegation receipt, only when T3 echoed
both exact provider and model. A receipt without identity fields or with a null
model only retains the handle; use `task_status` to reconcile identity. Without that proof,
or with a present mismatched ID, it records an identity blocker. Reconcile the
receipt/status; never guess a normalized ID or waive that blocker.
The live `task_status` schema requires a non-null `providerInstanceId`, while
`model` is nullable. Every observation must report the exact chosen provider;
an absent, null or mismatched provider blocks identity verification even when a
receipt exists. Reconcile the host/status response before proceeding. `attach`
can retain a task handle from a partial receipt so the parent can query or cancel
it; that partial receipt does not waive the status provider requirement.

Unchanged resume uses `resume --state FILE` with the saved agreement, without a
chooser or retain-or-stop. Reconcile owned tasks before work. A resolved failure
uses `recover` with a reason; it preserves identities, findings and attempt limits.
A confirmed outage may use `replace --input FILE` with role (`implementer` or
`evaluator`), exact approved `target` and original `unavailable.reconciled` evidence.
The checkpoint verifies original request/host IDs and terminal/no-pending state.
Replacement consumes the retained attempt budget. If an implementor replacement
invalidates the unlaunched reviewer, use an approved independent reviewer backup
or report a blocker. A healthy adverse review never permits replacement.
Keep legacy state pinned; a new endpoint or chain needs a separately admitted
restart after reconciliation, carrying prior findings and remaining limits.

Record observed delegation failures through `PKG/shared/learnings.md` when the
active harness permits that write; otherwise include the proposed lesson in the
handoff. Learning storage errors do not block engineering work.

For a completed implementation, inspect actual changed files, claimed checks and
artifacts. The next call captures the tree and dispatches the evaluator in fresh
context with that binding and the implementation summary.

The helper sets each review's `reviewScope`. A `full` review covers the goal and
the full task diff against the intended base. After a review rejects with
feedback, the next review is `delta`: it checks each `openFeedback` item and every
path in `changedPathsSinceReview` since that review's revision. It continues the
rejecting reviewer's thread when one was recorded, told to re-read changed paths
and re-run cited checks at the new revision, and receives only the history since
its own report. Otherwise it is a fresh task with the full brief. A delta
review cannot finish the run. When it passes, the helper issues a full review of
the same tree without consuming an attempt. Only the latest review decides: if it
was invalidated, malformed or failed, returned no feedback, or the tree drifted
after acceptance, the next review is full. Evaluation is read-only;
it may run suitable checks, inspect artifacts and report gaps, but cannot edit,
commit, push, publish, delegate or change the goal. If required inspection cannot
be performed, the evaluator must return a failure/gap, never infer success.

The evaluator must finish with ONE fenced JSON object marked `ralph-evaluation`:

```ralph-evaluation
{
  "goalAchieved": false,
  "feedback": [{"severity": "major", "message": "Describe the concrete gap and required repair."}],
  "evidence": ["Check or inspected artifact with its observable result"],
  "revision": "Copy the exact revision token supplied in the task"
}
```

Each feedback message must be self-contained, with file, line and reproduction,
because later tasks see only the latest evaluator report in full.
Pass the unmodified structured status and raw summary to `observe`; the helper
extracts the JSON block itself. Malformed, absent, stale, or unsupported output is
a verification gap, not a pass. The helper requires a real boolean, an array of
feedback objects, nonempty evidence, and the issued revision. An invalid verdict
is consumed with its raw summary and explicit gap in a recoverable `blocked` state.
Address the format/evidence cause, then use `recover` with a reason to issue a fresh
evaluation. This does not reuse the malformed verdict or its child context. If the
worktree changed since issuance, the helper instead requires fresh evaluation.
The invalidated round retains `stale: true` and an `invalidation` reason with the
issued and observed revision tokens; fresh tasks receive these in their history.
Before dispatching again, inspect the changed files and identify the cause of
drift, including possible evaluator edits during its read-only task. Preserve the
evidence and resolve unexpected writes before issuing another evaluation.

`goalAchieved: true` AND `feedback: []` from a full review makes the loop
`evaluated`. Any feedback, or `goalAchieved: false`, from either scope means the
next fresh implementer task uses the original pinned target and existing worktree.
Even informational feedback triggers repair. If false has no feedback, the fresh
brief still includes that verdict and asks the implementer to find the unmet goal.
At the limit, report `exhausted`, all outstanding feedback and the checkpoint path.
Never claim success or publish a success PR merely because the limit was reached.

## Selected endpoint and handoff

After the fresh full evaluation, follow `PKG/shared/upfront-agreement.md` for
the exact selected Open PR, Tagged Version or Verified in Prod endpoint.
The target repository owns release/distribution/deployment procedures.
Use authorised CI repair and native notification-driven waiting.
`complete --state FILE --input FILE` records actual endpoint observations
only at the clean current evaluated head. `readyForPublication` is source
readiness; `endpointComplete` is separate. Missing or stale evidence keeps
the chosen target incomplete. Report no-change honestly and resolve an
incompatible endpoint without inventing an empty PR or tag.
