# Babysitter job plan

Read this when step 4 of `PKG/playbooks/maintain.md` creates the run's job. Field
authority is `PKG/shared/agents/jobs-contract.md`; mechanics are in
`PKG/shared/job-coordination.md`. This file adds only babysitter choices.

## Before `create`

- Save the operator's request verbatim to an owner-source file outside the job
  directory and every PR worktree, for example
  `$XDG_STATE_HOME/t3-plugins/babysitter/requests/<job-id>.txt`. Decisions quote it.
- Freeze the roster (step 1) and run the quick pass (step 2) first, so each stage is
  declared at the head this thread actually observed.

## Job fields

- `workflow`: `babysitter/pr`, `babysitter/repo` or `babysitter/org`.
- `requirements`: one ID per roster PR, such as `PR-12`: "<owner/repo>#12 reaches
  <endstate> at an observed head with every required check", plus `PR-12-REVIEW`
  for each review-gated PR. Requirements are never dropped to make a run finish; an
  unreachable PR stays a named blocker.
- `authorization`: `actions` lists the union, and `prs` maps each PR URL to its own
  actions from `read`, `push`, `communicate` and `merge`. Inspect-only runs record
  `read` alone.
- `constraints`: the target repository's instructions verbatim, plus "Never
  force-push" and "Push only to the PR head branch".
- `dependencies`: `{"key": "babysitter", "plugin": "babysitter"}`. A calling imps job
  declares babysitter in its own plan instead.

## Stages

Every stage sets `validator_dependency: "babysitter"`, `revision:
"<stage-id>@<head12>"`, and a `validator_contract` that `validate_pr.py` checks
against the published input:

- `pr`: the PR URL.
- `head_sha`: the full 40-character head this thread observed.
- `required_contexts`: the required check names from branch protection or rulesets.
- `optional_contexts`: other observed checks; their failures stay visible.
- `allow_empty_required_contexts`: `true` only when the stage explicitly permits a
  PR with no required checks and the latest host observation confirms that policy.
- `authorized_endstate`: `{"requested": E, "observed": E, "authorization_ref": ID}`
  where E is `merged`, `mergeable` or `open` (inspect-only), and ID names the
  recorded owner decision for that scope.

A PR merged in the quick pass, or one waiting only on checks or a human review, gets
one `pr-<number>` stage with `execution_mode: "direct"` and no slots. A PR with work
for a child is review-gated and gets two stages:

- Review stage `pr-<number>`, endstate `mergeable`, with two slots:
  `maintain` (`babysitter/pr-maintainer`, `target` from `resolve workhorse` with
  `providerInstanceId`, `model` and `lineage`, `write_scope` `worker-evidence` under
  `artifacts/tasks/<task-id>`, `review_required: true`, `review_task_ids: [review]`)
  and `review` (`babysitter/pr-reviewer`, `role: "review"`, `reviewed_task_ids:
  [maintain]`, a reviewer target on a different known lineage).
- Land stage `pr-<number>-land`, `execution_mode: "direct"`, endstate `merged`,
  `depends_on: ["pr-<number>"]`, the same `head_sha`. It is the only stage whose
  work may call `merge-pr.sh`, always with `--expected-head <head_sha>`, and the
  helpers refuse its acceptance until the review stage holds current acceptance at
  that same head.

No stage that holds a `review` slot may request `merged`, and every `merged` stage of
a review-gated PR depends on its review stage. When the operator asked for review
before landing, every roster PR is review-gated, including those with no fixer work:
their review stage holds only a `review` slot reading the PR as it stands. A
direct-stage PR that later needs a fixer is re-planned into review and land stages
through a picker-approved plan revision before any fixer runs.

There is no separate integration stage: the PR stages together cover every
requirement, and `validate-final` over all of them at fresh observations is the
final acceptance declared in the initial plan.

## Example

One fixer PR (12) and one PR (13) merged in the quick pass. Angle-bracket strings
are placeholders.

```json
{
  "schema_version": 1, "job_id": "<job-id>", "installation_id": "<installation-id>",
  "workflow": "babysitter/repo", "owner": {"id": "operator"},
  "objective": "Babysit the frozen owner/repo roster through merge.",
  "requirements": {
    "PR-12": "owner/repo#12 reaches merged at an observed head with every required check",
    "PR-12-REVIEW": "an independent review approved owner/repo#12 at the head that lands",
    "PR-13": "owner/repo#13 reaches merged at an observed head with every required check"
  },
  "authorization": {"actions": ["read", "push", "communicate", "merge"], "prs": {
    "<pr-12-url>": ["read", "push", "communicate", "merge"],
    "<pr-13-url>": ["read", "merge"]}},
  "constraints": ["Never force-push.", "Push only to the PR head branch."],
  "dependencies": [{"key": "babysitter", "plugin": "babysitter"}], "pins": {},
  "policy": {"max_repair_cycles": 3, "max_artifact_bytes": 16777216},
  "result_contract": {"schema_version": 1},
  "stages": [
    {"id": "pr-12", "depends_on": [], "requirements": ["PR-12-REVIEW"], "status": "pending",
     "validator_dependency": "babysitter", "revision": "pr-12@<head-12-short>",
     "validator_contract": {"pr": "<pr-12-url>", "head_sha": "<head-12>", "required_contexts": ["ci"],
       "optional_contexts": [], "allow_empty_required_contexts": false,
       "authorized_endstate": {"requested": "mergeable", "observed": "mergeable", "authorization_ref": "<decision-id>"}}},
    {"id": "pr-12-land", "depends_on": ["pr-12"], "requirements": ["PR-12"], "status": "pending",
     "execution_mode": "direct", "validator_dependency": "babysitter", "revision": "pr-12-land@<head-12-short>",
     "validator_contract": {"pr": "<pr-12-url>", "head_sha": "<head-12>", "required_contexts": ["ci"],
       "optional_contexts": [], "allow_empty_required_contexts": false,
       "authorized_endstate": {"requested": "merged", "observed": "merged", "authorization_ref": "<decision-id>"}}},
    {"id": "pr-13", "depends_on": [], "requirements": ["PR-13"], "status": "pending",
     "execution_mode": "direct", "validator_dependency": "babysitter", "revision": "pr-13@<head-13-short>",
     "validator_contract": {"pr": "<pr-13-url>", "head_sha": "<head-13>", "required_contexts": ["ci"],
       "optional_contexts": [], "allow_empty_required_contexts": false,
       "authorized_endstate": {"requested": "merged", "observed": "merged", "authorization_ref": "<decision-id>"}}}
  ],
  "tasks": [
    {"task_id": "pr-12-maintain", "stage_id": "pr-12", "logical_slot_id": "maintain",
     "request_id": "<job-id>-pr-12-maintain", "worker_id": "babysitter/pr-maintainer",
     "dependency_key": "babysitter", "target": "<workhorse-target>",
     "write_scope": {"mode": "worker-evidence", "path": "artifacts/tasks/pr-12-maintain"},
     "review_required": true, "review_task_ids": ["pr-12-review"]},
    {"task_id": "pr-12-review", "stage_id": "pr-12", "logical_slot_id": "review",
     "request_id": "<job-id>-pr-12-review", "worker_id": "babysitter/pr-reviewer",
     "dependency_key": "babysitter", "target": "<reviewer-target>",
     "write_scope": {"mode": "worker-evidence", "path": "artifacts/tasks/pr-12-review"},
     "role": "review", "reviewed_task_ids": ["pr-12-maintain"]}
  ],
  "decisions": [], "history": [], "metrics": {}
}
```

## Head changes

The contract binds one head. When a verified push inside the recorded `push` action,
or the author's own push to the same PR, moves the head:

1. Record `job_cli.py decision` with a new ID, the saved request as `quote` and
   `source` (with its SHA-256), and scope `plan:<revision-id>`.
2. Apply `job_cli.py plan-revision` that changes only the `head_sha`, `revision`, and
   newly observed contexts of that PR's review and land stages. Both become stale.
3. `retry` the maintainer as a charged verification round at the new head, then
   dispatch the reviewer on the final combined change. The land stage cannot merge
   until the review stage is accepted again at the new head.

Never use this route for new PRs, extra actions, a different endstate, fewer
required contexts or more repair rounds. Those widen scope: ask through the question
picker and quote the operator's answer instead.

## Acceptance input

Build the validator input only from host reads this thread made (GitHub tools or
`list-prs.sh`), never from a worker result. It repeats the contract fields and adds
`required_checks` (`context`, `conclusion`, `head_sha`), `review_threads`
(`resolved`, `head_sha`), and `host_observations`: one or more coordinator records
with `observer: "coordinator"`, `kind: "pr-state"`, `source`, the full `content`, its
canonical SHA-256 and, for several reads, strictly increasing `sequence` numbers.
Publish it with `job_cli.py observation` and pass the returned path to
`accept-stage` and `validate-final`.
