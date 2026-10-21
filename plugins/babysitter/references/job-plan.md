# Babysitter job plan

Read this when step 4 of `PKG/playbooks/maintain.md` creates a job. Field
authority is `PKG/shared/agents/jobs-contract.md`; mechanics are in
`PKG/shared/job-coordination.md`. This file adds only babysitter choices.

## Shape

One job per PR that needs a child, so one PR's ledger, failures and revisions never
stall or bloat another's. A PR that merges without a child needs no job; the table
and the observed merge are its record.

## Repair cycle

Run this cycle on initial triage, every PR wake and every fixer completion. A watch
or an armed auto-merge request never substitutes for an available action.

1. Before PR writes, check the installed package and worker bundle with
   `t3-plugins doctor babysitter` and `t3-plugins agents list babysitter`. For an
   existing job, read `job_cli.py overview` from its pinned package and reconcile
   owned handles. A package, bundle or ledger integrity failure stops writes for
   that PR, including replies, resolutions, pushes and merge/auto-merge mutations.
   Report the exact command, exit code and error as `needs human:`. Never edit the
   ledger by hand, create a replacement job to evade it, or fall back to untracked
   GitHub mutations. Direct fallback applies only to unavailable delegation.
2. Ingest a completed fixer result before retrying a merge. Read the live PR head
   and every page of unresolved review threads, including outdated threads. Compare
   IDs with the result's dispositions. A missing disposition or a newly arrived
   thread needs inspection now; it cannot disappear from the work list.
3. Verify each claimed fix at that head with its changed paths and test evidence.
   For no-change findings, verify the evidence explaining why the concern does not
   apply. Severity, an approval, an outdated marker or a worker's `fixed` label is
   insufficient. Reply and resolve through step 7, then re-read the thread to confirm
   it is resolved. If the head changes, re-verify before resolving. If a reply or
   resolution fails, report the exact failure and stop writes for that PR. For an
   ambiguous reply outcome, inspect the thread before retrying so no duplicate is
   posted. Never mark resolution complete from a reply alone.
4. Dispatch remaining actionable threads, merge conflicts and failing checks to the
   fixer with the complete blocker list. Conflicts require integrating the current
   base, resolving files and testing the combined result. Failing checks require
   reading current-head logs, repairing the cause and verifying the repair. Retry
   infrastructure failures within a bounded attempt count; missing access or an
   external outage becomes a named blocker. Local success does not prove hosted CI.
5. Read four independent landing gates at the current head: thread resolution,
   latest review state, required checks and mergeability. Resolve addressed threads
   even while CI is red or a new review is required. A resolved thread does not clear
   `CHANGES_REQUESTED`; request the reviewer's re-review and wait for the required
   approval without dismissing their review. Never land with an actionable blocking
   thread open. Retry the guarded merge helper only after available resolutions;
   then repair remaining blockers before watching. Report the gaps separately.

## Before `create`

- Save the operator's request verbatim to an owner-source file outside the job
  directory and every PR worktree, for example
  `$XDG_STATE_HOME/t3-plugins/babysitter/requests/<run-id>.txt`. Decisions quote it.
- Freeze the roster (step 1) and run the quick pass (step 2) first, so the stage is
  declared at the head this thread actually observed.
- Record the auto-merge posture (step 1) as a `decisions` entry quoting the operator's
  picker answer, or the saved request when it named the posture, so the quick pass,
  each wake, and the merge share one mode.

## Job fields

- `job_id`: unique per PR and run, such as `<run-id>-<repo>-<number>`.
- `workflow`: `babysitter/pr`, `babysitter/repo` or `babysitter/org`, matching the
  operation.
- `requirements`: `PR-12`: "<owner/repo>#12 reaches <endstate> at an observed head
  with every required check". Requirements are never dropped to make a run finish;
  an unreachable PR stays a named blocker.
- `authorization`: `actions` and `prs` for this PR only, from `read`, `push`,
  `communicate` and `merge`. Inspect-only runs record `read` alone.
- `constraints`: the target repository's instructions verbatim, plus "Push only to
  the PR head branch" and "Publish a rewritten branch only with --force-with-lease
  pinned to the head SHA last fetched".
- `policy.max_repair_cycles`: `1000`. Rounds are uncapped in practice; the playbook's
  stop rule decides when a human is needed.
- `dependencies`: `{"key": "babysitter", "plugin": "babysitter"}`. A calling imps job
  declares babysitter in its own plan instead.

## Stage

One stage `pr-<number>` that sets `validator_dependency: "babysitter"`, `revision:
"<stage-id>@<head12>"`, and a `validator_contract` that `validate_pr.py` checks
against the published input:

- `pr`: the PR URL.
- `head_sha`: the full 40-character head this thread observed.
- `required_contexts`: the required check names from branch protection or rulesets.
- `optional_contexts`: other observed checks; their failures stay visible.
- `allow_empty_required_contexts`: `true` only when the stage explicitly permits a
  PR with no required checks and the latest host observation confirms that policy.
- `authorized_endstate`: `{"requested": E, "observed": E, "authorization_ref": ID}`
  where E is `merged`, `mergeable` for an operator-requested review stage, or `open`
  for inspect-only, and ID names the recorded owner
  decision for that scope.

It holds one `maintain` slot: `babysitter/pr-maintainer`, `target` from `resolve
workhorse` with `providerInstanceId`, `model` and `lineage`, and `write_scope`
`worker-evidence` under `artifacts/tasks/<task-id>`. Each round is a `retry` of that
slot. The maintainer reports unfinished work as `failed`, never `needs-followup`; if
one still arrives it gets the slot's one tracked follow-up. A review slot cannot be
followed up. Any later `needs-followup`, or one from a review slot, escalates: an
owner-sourced plan revision (as below) moves the slot's `target` to another candidate
(the next, or back down the list from the strongest), which stales it, then `retry`.
With a single candidate, the row is `needs human:`. In every round the `delegate_task`
text adds the round's head, `blockers=` list, thread IDs and prior findings beside the
brief path. In a job without operator-requested review, never rebind the head between
rounds: rebinding stales the slot and forces a round that only re-verifies. A
review-gated job rebinds both stages to each pushed head, which stales the slot too;
that verification round is the cost of the requested review.

## Merge and acceptance

For a job without operator-requested review, after the merge is observed, dispose
every finding with evidence, then record
`job_cli.py decision` with a new ID, the saved request as `quote` and `source` (with
its SHA-256), and scope `plan:<revision-id>`. Apply `job_cli.py plan-revision` that
sets `head_sha` and `revision` to the merged head, records newly observed contexts,
sets `execution_mode: "direct"`, and removes the settled `maintain` slot. Then
publish the observation and accept the stage. A slot is settled once no handle is
live and its last result is ingested; a `needs-followup` result first gets its
tracked follow-up, and a blocker or major finding needs a recorded disposition.

Never use this route for new PRs, extra actions, a different endstate or fewer
required contexts. Those widen scope: ask through the question picker and quote the
operator's answer instead.

## Operator-requested review

Only when the operator asked for review before landing, and then for every unmerged
roster PR: the stage above becomes a review stage with endstate `mergeable`, its `maintain` slot sets `review_required:
true` and `review_task_ids: [review]`, and a `review` slot (`babysitter/pr-reviewer`,
`role: "review"`, `reviewed_task_ids: [maintain]`, a reviewer target on a different
known lineage) joins it. A direct land stage `pr-<number>-land` with endstate
`merged`, `depends_on: ["pr-<number>"]` and the same `head_sha` is the only place it
merges, with `merge-pr.sh --no-auto --expected-head <head_sha>`; never pass a
review-gated PR to the quick-pass helper. A PR with no repair work keeps the `maintain`
slot as a verification round that pushes nothing, so the review has its subject.
The pinned land command merges only the reviewed head, so after the merge accept the
land stage directly; never apply the post-merge rebind above to a review job. Each head move rebinds both stages and needs a fresh
review. No stage that holds a `review` slot may
request `merged`.

## Example

One PR (12) with fixer work. Angle-bracket strings are placeholders.

```json
{
  "schema_version": 1, "job_id": "<job-id>", "installation_id": "<installation-id>",
  "workflow": "babysitter/repo", "owner": {"id": "operator"},
  "objective": "Land owner/repo#12.",
  "requirements": {
    "PR-12": "owner/repo#12 reaches merged at an observed head with every required check"
  },
  "authorization": {"actions": ["read", "push", "communicate", "merge"], "prs": {
    "<pr-12-url>": ["read", "push", "communicate", "merge"]}},
  "constraints": ["Push only to the PR head branch.",
    "Publish a rewritten branch only with --force-with-lease pinned to the head SHA last fetched."],
  "dependencies": [{"key": "babysitter", "plugin": "babysitter"}], "pins": {},
  "policy": {"max_repair_cycles": 1000, "max_artifact_bytes": 16777216},
  "result_contract": {"schema_version": 1},
  "stages": [
    {"id": "pr-12", "depends_on": [], "requirements": ["PR-12"], "status": "pending",
     "validator_dependency": "babysitter", "revision": "pr-12@<head-12-short>",
     "validator_contract": {"pr": "<pr-12-url>", "head_sha": "<head-12>", "required_contexts": ["ci"],
       "optional_contexts": [], "allow_empty_required_contexts": false,
       "authorized_endstate": {"requested": "merged", "observed": "merged", "authorization_ref": "<decision-id>"}}}
  ],
  "tasks": [
    {"task_id": "pr-12-maintain", "stage_id": "pr-12", "logical_slot_id": "maintain",
     "request_id": "<job-id>-pr-12-maintain", "worker_id": "babysitter/pr-maintainer",
     "dependency_key": "babysitter", "target": "<workhorse-target>",
     "write_scope": {"mode": "worker-evidence", "path": "artifacts/tasks/pr-12-maintain"}}
  ],
  "decisions": [], "history": [], "metrics": {}
}
```

## Acceptance input

Build the validator input only from host reads this thread made (GitHub tools or
`list-prs.sh`), never from a worker result. It repeats the contract fields and adds
`required_checks` (`context`; `conclusion` lowercased from GitHub's uppercase values,
where `success`, `neutral` and `skipped` pass, the set `merge-pr.sh` treats as green;
and `head_sha`), `review_threads` (one entry per
thread with its host `id`, `resolved` and `head_sha`), `review_thread_count`
(GitHub's total, which must equal the number of distinct IDs), and `host_observations`: one or more
coordinator records with `observer: "coordinator"`, `kind: "pr-state"`, `source`, the
full `content`, its canonical SHA-256 and, for several reads, strictly increasing
`sequence` numbers. Publish it with `job_cli.py observation` and pass the returned
path to `accept-stage` and `validate-final`.

The recorded SHA-256 covers canonical bytes: sorted keys, `,` and `:` separators,
`ensure_ascii=False`, UTF-8, and one trailing newline. Hashing the same object
without that newline is rejected as changed bytes.

`validator_argv` is `[PKG/scripts/validate_pr.py, "--input", OBSERVATION]`, whose
first element must resolve to that script inside the stored pinned package. Never
pass the pin's `compatible_pinned_argv`: that one is the recovery invocation
(`t3-plugins --job JOB.json path babysitter`), and `accept-stage` refuses it.
