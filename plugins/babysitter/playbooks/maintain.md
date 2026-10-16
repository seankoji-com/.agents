# Maintain pull requests

At final-head PR review, use `PKG/shared/supplemental-reviews.md` only when the
coordinator checkout is already at the reviewed PR HEAD; otherwise skip.
Never change checkouts merely to enable extras. Keep extras outside mandatory
slots; close with primary review and verify findings before fixer repair.

This thread is the coordinator. It owns the roster, the PR table, every watch, every
merge, and every acceptance. Children own one PR's repair or review at a time. The
review gate in the entry binds every step below: a review-gated PR gets no
merge-capable call until its review stage is accepted at the exact current head.

1. Ask the auto-merge posture through the picker and record it with `job_cli.py
   decision` (entry); under **ignore**, exclude any roster PR that already carries an
   armed request. Then resolve the scope and endstate; inspect the
   roster through GitHub tools or `bash PKG/scripts/list-prs.sh --repo <owner/name>` /
   `--org <owner>`.
   For a named PR add `--pr <number>`. Read the helper's filter and pagination warnings;
   a partial page is not the whole roster. Exclude drafts, forks, and other authors
   unless the operator includes them. On a writable run, run the sibling-work check in
   `PKG/shared/t3-runtime.md` per PR number and head branch; a PR another active
   thread maintains leaves the roster unless the owner keeps it. An inspect-only
   run skips the check and keeps every eligible PR, since reading cannot collide.
   Freeze the eligible roster and link each PR
   through T3 with `link_pull_request`. An inspect-only run skips step 2's helper,
   posts step 3's table from read-only evidence, and stops; for deep triage of many
   PRs it may plan `read` only maintainer slots, whose `blocked` results with named
   blockers are a complete triage answer, never an acceptance.
2. Quick pass, in this thread, before any child: for every roster PR run
   `bash PKG/scripts/merge-pr.sh --repo <owner/name> --pr <N> --no-auto`, or
   `--arm-always` under **enable**. It merges only a PR whose current head is CLEAN
   with green checks and resolved threads, which no babysitter change has touched yet;
   `--arm-always` also arms auto-merge, so a PR blocked only on a pending check lands
   on its own. If the operator asked for review before landing,
   every PR is review-gated: skip this helper and read state with `list-prs.sh`
   instead. Record each `MERGED` or `BLOCKED reason=... automerge=...` line.
   `automerge=preexisting` is someone else's armed request: it changes nothing here
   and withholds no fixer push or merge. Inspect the helper's help first.
3. Keep the PR table in this thread and post it after the quick pass:

   | PR | Description | Not merged because |
   |---|---|---|
   | [owner/repo#12](https://github.com/owner/repo/pull/12) | PR title | failing check `lint`; awaiting review gate; fixer round 1 |

   The last column names the current blocker in plain words, the review-gate or
   auto-merge state, and any fixer in flight. Merged rows read `merged` and move to
   the bottom. Post the whole table again each time a PR merges and when a blocker
   changes. Emit the job's checklist from `job_cli.py overview` beside it at each
   stage, acceptance and integration milestone; never stream raw logs.
4. Plan one job for the run once the quick pass shows which PRs have work a child can
   do: conflicts, a behind branch the helper could not update, failing checks,
   unresolved threads, or requested changes. Follow `PKG/references/job-plan.md`.
   Each such PR gets a review stage (fixer and reviewer, endstate `mergeable`) and a
   land stage that depends on it; the land stage is the only place it may merge. A
   PR waiting only on running checks or a required human review gets one direct
   stage and no child; watch it. PRs merged in the quick pass get a direct stage
   accepted from the observed merge.
5. Route each fixer: prepare its worktree with `bash PKG/scripts/pr-workspace.sh`,
   then run `t3-plugins resolve workhorse --capabilities FILE --repo <that worktree>`
   so the target repository's routing policy applies. Start with the first candidate
   on the cheapest configured tier, pass its `runtimeMode`, and record the target,
   reason and ordered escalation in the slot; later candidates escalate.
   Report each `unavailable` entry once, such as a provider needing a broader mode
   than this thread. Without routing, or with no cheapest-tier candidate, ask the
   operator through the question picker before fanning out; a dispatched child never
   runs above the cheapest tier. Resolve the reviewer with
   `t3-plugins resolve reviewer --implementer-lineage <fixer lineage>`.
6. Dispatch per `PKG/shared/job-coordination.md`: `job_cli.py prepare`, launch
   `babysitter/pr-maintainer` with `delegate_task`, and record the handle with
   `task-observation`. The brief carries the PR URL, its worktree, the head SHA
   at dispatch, the blocker, earlier rounds' findings, and only that PR's recorded
   actions. Finish line: the blocker is fixed at a pushed head and local verification
   passes, or the result is `blocked` with what a human must decide. Children never
   run `merge-pr.sh` merge or arm modes; only `--resolve-thread` when that PR records
   `communicate`.
7. Call `watch_pull_request` for every unmerged PR and end the turn. Children cannot
   watch; this thread owns every watch. On a PR wake, read that PR's live state at its
   current head; a check from an older SHA proves nothing. For a PR that is not
   review-gated, rerun step 2's helper first: green checks or a new approval may make
   it mergeable now. A review-gated PR gets no helper run on a wake until its review
   stage is accepted. On a child completion, read `task_status`, ingest with
   `job_cli.py result`, and verify the claimed push against the PR head.
   A verified new head is rebound as `PKG/references/job-plan.md`
   describes. Dispose every finding with evidence.
8. After the fixer's final push, dispatch `babysitter/pr-reviewer` on the final
   combined change at that exact head. An `adverse` verdict returns its findings to
   the next fixer round; never switch reviewers to reverse it. With an `approve`
   verdict, accept the review stage (step 10) at that head with endstate `mergeable`.
9. On a new failure, comment, or conflict with no child in flight, start the next
   round with `job_cli.py retry` and the prior findings. Escalate to the next
   recorded candidate when a child returns `blocked` or a blocker survives its round;
   escalation never resets counters. When the stage's repair budget is spent, or when
   a human must act, mark the row `needs human:` with the exact blocker and stop
   dispatching for that PR. More rounds need an owner decision through the picker.
10. Accept each stage from a fresh coordinator observation: publish it with
    `job_cli.py observation`, then `job_acceptance_cli.py accept-stage` with the
    pinned `validate_pr.py`. Only after a review stage is accepted, and only with
    `merge` recorded, does its land stage run `merge-pr.sh --no-auto --expected-head
    <accepted head>`, always passing the head the review stage was accepted at. A
    `reason=expected_head_mismatch` or a moved head goes back through step 7's rebind
    and a fresh review. Accept the land stage from the observed merge, update
    the table and `unwatch_pull_request`. Report a merge as pending until observed.
11. If `delegate_task` or a suitable target is unavailable, record it and run the
    fixer stage directly in this thread under the same brief, actions,
    counters and gate, with a visible fallback marker. A missing independent reviewer
    stays a blocker for that PR; direct work cannot stand in for it or merge it.
12. Org/repo discovery of future PRs needs an explicitly authorized T3 scheduled sweep;
    watching today's PRs does not discover tomorrow's. Use the host scheduler only
    when requested, bounded in scope and cadence. Report its ID and stop command.
13. Hand off when every row is merged or `needs human:`. Run `job_acceptance_cli.py
    validate-final` with fresh observations, unwatch PRs, confirm every child stopped
    through `task_status`, and remove only clean, task-owned worktrees. Post the final
    table and checklist. Never claim all landed from an empty or partial response.
    Do not run `pr-events.sh` in T3; it is retained only as a legacy standalone adapter.
