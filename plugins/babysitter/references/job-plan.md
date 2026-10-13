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
  <endstate> at an observed head with every required check". Requirements are never
  dropped to make a run finish; an unreachable PR stays a named blocker.
- `authorization`: `actions` lists the union, and `prs` maps each PR URL to its own
  actions from `read`, `push`, `communicate` and `merge`. Inspect-only runs record
  `read` alone.
- `constraints`: the target repository's instructions verbatim, plus "Never
  force-push" and "Push only to the PR head branch".
- `dependencies`: `{"key": "babysitter", "plugin": "babysitter"}`. A calling imps job
  declares babysitter in its own plan instead.

## Stages

One stage per roster PR, `id` `pr-<number>` (prefix the repository for `org`). Every
stage sets `validator_dependency: "babysitter"`, `revision: "pr-<number>@<head12>"`,
and a `validator_contract` that `validate_pr.py` checks against the published input:

- `pr`: the PR URL.
- `head_sha`: the full 40-character head this thread observed.
- `required_contexts`: the required check names from branch protection or rulesets.
- `optional_contexts`: other observed checks; their failures stay visible.
- `allow_empty_required_contexts`: `true` only when the stage explicitly permits a
  PR with no required checks and the latest host observation confirms that policy.
- `authorized_endstate`: `{"requested": E, "observed": E, "authorization_ref": ID}`
  where E is `merged`, `mergeable` (merge not authorized) or `open` (inspect-only),
  and ID names the recorded owner decision for that scope.

A PR merged in the quick pass, or one waiting only on checks or a human review, gets
`execution_mode: "direct"` and no slots. A PR with work for a child gets two slots:

- `maintain`: `babysitter/pr-maintainer`, `target` from `resolve workhorse` with
  `providerInstanceId`, `model` and `lineage`, `write_scope` `worker-evidence` under
  `artifacts/tasks/<task-id>`, `review_required: true`, `review_task_ids: [review]`.
- `review`: `babysitter/pr-reviewer`, `role: "review"`, `reviewed_task_ids:
  [maintain]`, and a reviewer target on a different known lineage.

There is no separate integration stage: the PR stages together cover every
requirement, and `validate-final` over all of them at fresh observations is the
final acceptance declared in the initial plan.

## Head changes

The contract binds one head. When a verified push inside the recorded `push` action,
or the author's own push to the same PR, moves the head:

1. Record `job_cli.py decision` with a new ID, the saved request as `quote` and
   `source` (with its SHA-256), and scope `plan:<revision-id>`.
2. Apply `job_cli.py plan-revision` that changes only that stage's `head_sha`,
   `revision`, and newly observed contexts. The stage becomes stale.
3. `retry` the maintainer as a charged verification round at the new head, then
   dispatch the reviewer on the final combined change.

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
