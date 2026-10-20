# Maintain pull requests

At an operator-requested final-head PR review, use `PKG/shared/supplemental-reviews.md`
only when the coordinator checkout is already at the reviewed PR HEAD; otherwise skip.
Never change checkouts merely to enable extras. Keep extras outside mandatory slots.

This thread owns the roster, PR table, watches, merges, resolutions and acceptance.
Every PR with fixable work gets a child each turn.
Follow `PKG/references/job-plan.md`'s repair cycle, including its health stop rule.

1. Ask the auto-merge posture through the picker unless the request names one, and
   record it with `job_cli.py decision` (entry); under **ignore**, exclude PRs with an
   armed request. Inspect the roster with
   `bash PKG/scripts/list-prs.sh --repo <owner/name>` / `--org <owner>`, adding
   `--pr <number>` for a named PR. Read its filter and pagination warnings; a partial
   page is not the whole roster. Exclude drafts, forks, and other authors unless the
   operator includes them. On a writable run, run the sibling-work check in
   `PKG/shared/t3-runtime.md` per PR number and head branch; a PR another active
   thread maintains leaves the roster unless the owner keeps it. An inspect-only run
   skips the check and keeps every eligible PR. Freeze the
   eligible roster and link each PR with `link_pull_request`. An inspect-only run skips
   step 2's helper,
   posts step 3's table from read-only evidence, and stops; for deep triage it may plan
   `read` only maintainer slots, whose `blocked` results with named blockers are a
   complete triage answer, never an acceptance.
2. Quick pass, in this thread, before any child: for every roster PR run
   `bash PKG/scripts/merge-pr.sh --repo <owner/name> --pr <N> --no-auto`, or
   `--arm-always` under **enable**. It merges CLEAN PRs and UNSTABLE PRs whose required
   checks all succeeded, updates behind branches, and arms auto-merge only with complete,
   resolved threads. Record each
   `MERGED` line and each `BLOCKED` line's whole `blockers=` list, not just `reason=`;
   one reason can hide threads or red checks behind it. `automerge=preexisting` is
   someone else's armed request and withholds nothing. If the operator asked for review
   before landing, every PR is review-gated: skip this helper, read state with
   `list-prs.sh`, and give every unmerged PR a job (step 4) even without repair work.
3. Keep the PR table in this thread. Post it after the quick pass and at the end of
   every turn:

   | PR | Description | Not merged because |
   |---|---|---|
   | [owner/repo#12](https://github.com/owner/repo/pull/12) | PR title | 3 unresolved threads; failing check `lint`; fixer round 2 (candidate 1) |

   The last column lists every current blocker in plain words, the auto-merge state,
   and any child in flight. Merged rows read `merged` and move to the bottom. Emit the
   checklist from `job_cli.py overview` for each job beside it; never stream raw logs.
4. Classify each unmerged PR from `blockers=`. Child work: conflicts, a branch the
   helper could not update, failing checks, unresolved threads that need code, and
   requested changes, from bots or humans. Coordinator work: threads whose fix already
   landed or that need only an answer (step 7). Waiting only: checks running on the
   current head. A required human review with nothing left to fix is `needs human:`
   (step 8). Every PR with
   child work gets a fixer now, all at once, with no concurrency cap and no question.
   Create one job per such PR with `PKG/references/job-plan.md`; PRs without child work
   need no job.
5. Route each fixer: prepare its worktree with `bash PKG/scripts/pr-workspace.sh`,
   then run `t3-plugins resolve workhorse --capabilities FILE --repo <that worktree>`.
   Start on the cheapest configured tier and record the ordered escalation. Without
   routing or a candidate, choose the cheapest suitable model from the saved
   `orchestrator_capabilities` yourself and record why; never ask. Report each
   `unavailable` entry once.
6. Dispatch per `PKG/shared/job-coordination.md`: `job_cli.py prepare`, launch
   `babysitter/pr-maintainer` with `delegate_task`, and record the handle with
   `task-observation`. The brief carries the PR URL, its worktree, the head at
   dispatch, the complete `blockers=` list, every unresolved thread's ID and comments,
   earlier rounds' findings, and that PR's recorded actions. Finish line: every listed
   blocker cleared at a pushed head with local verification, and a disposition for
   every thread; or `blocked` with what only a human can decide. Children never run
   `merge-pr.sh` merge, arm, or resolve modes.
7. Before landing or watching, inspect every unresolved thread at the current head,
   including all pages. Verify fixes there or establish why no change applies. Post
   each disposition and resolve it with `bash PKG/scripts/merge-pr.sh
   --repo <owner/name> --pr <N> --resolve-thread <ID> --verified-head <head>
   --reply-file <file>`. Re-read to confirm resolution. Actionable minor findings need
   fixes too; severity alone never justifies an answer. If the host
   refuses a resolution, ask through the picker at once and mark the row
   `needs human:`.
8. On a wake or child completion, read `task_status`, ingest completed results with
   `job_cli.py result`, verify the claimed push against the PR head, and perform step 7
   before attempting to land. Read fresh state; a check from an older SHA proves nothing.
   Rerun step 2's helper for that PR unless its fixer is in flight or it is review-gated;
   a review-gated PR merges only through its land stage's pinned command. Then
   reconcile every child through `task_status` and refill:
   each PR with child work and no child in flight gets its next round now through
   `job_cli.py retry` with the prior findings (`needs-followup` follows
   `PKG/references/job-plan.md`). Escalate to the next candidate when a child returns
   `blocked` or a malformed result, or the same blocker survives two rounds; re-request
   a malformed result immediately, naming the schema error. Rounds
   are not capped. Mark a row `needs human:` and ask through the picker only when the
   same blocker survives the strongest candidate twice or only a human can clear it.
   Call `watch_pull_request` for every unmerged PR after taking available repair and
   resolution actions. Children cannot watch; this thread owns every watch.
9. Before ending any turn, check for dead ends. Every unmerged row must have a child in
   flight, checks running on its current head, or a picker question already asked.
   A check queued 30 minutes with no runner is a `needs human:` blocker. Anything
   else is acted on now. A health or ledger failure stops writes and is `needs human:`.
   Never end a turn on "auto-merge armed" alone. Then post the
   table and end the turn.
10. Accept merged PR jobs from fresh observations: rebind and
    publish per `PKG/references/job-plan.md`, then `job_acceptance_cli.py
    accept-stage` with the pinned `validate_pr.py`. Update the table and
    `unwatch_pull_request`. Unobserved merges stay pending.
11. If `delegate_task` itself is unavailable, record it and run the fixer directly in
    this thread under the same brief and actions, with a visible fallback marker. A
    failed candidate is not unavailability; escalate instead.
12. Org/repo discovery of future PRs needs an explicitly authorized T3 scheduled sweep;
    watching today's PRs does not discover tomorrow's. Use the host scheduler only
    when requested, bounded in scope and cadence. Report its ID and stop command.
13. Hand off when every row is merged or `needs human:`. Run `job_acceptance_cli.py
    validate-final` per job with fresh observations, unwatch PRs, confirm every child
    stopped through `task_status`, and remove only clean, task-owned worktrees. Post the
    final table. Empty or partial responses prove nothing. Do not run
    `pr-events.sh` in T3; it is retained only as a legacy standalone adapter.
