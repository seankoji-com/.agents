# Maintain pull requests

Require upfront named-model or bounded-class consent in the frozen selection for
`PKG/shared/supplemental-reviews.md`. Require: coordinator checkout is already at the reviewed PR HEAD.
Never change checkouts merely to enable extras.

The coordinator owns discovery, watches, merges, resolutions and acceptance. Children
repair one PR. Follow `PKG/references/job-plan.md`'s repair cycle.

1. Apply the entry's auto-merge default or explicit override without a question;
   record it with `job_cli.py decision`; under **ignore**, exclude PRs with an
   armed request. Inspect the roster with
   `bash PKG/scripts/list-prs.sh --all-authors --repo <owner/name>` / `--org <owner>`.
   Read warnings: a partial page is not the whole roster. Follow
   `PKG/references/scope.md`: include all authors and bots; exclude drafts and forks
   unless included by the operator. Run the sibling-work check in
   `PKG/shared/t3-runtime.md` per PR; a PR another active thread maintains stays
   visible as owned elsewhere. Read-only runs skip this check.
   Record scope and link each admitted PR with `link_pull_request`. An
   inspect-only run skips step 2's helper, posts step 3's table, and stops; deep triage
   may plan `read` only maintainer slots, whose named-blocker `blocked` results are a
   complete triage answer, never an acceptance.
2. Quick pass, in this thread, before any child: for each unowned PR with no fixer in
   flight run `bash PKG/scripts/merge-pr.sh --repo <owner/name> --pr <N> --no-auto`, or
   `--arm-always` under **enable**. It merges, updates behind branches, and arms
   auto-merge only with complete, resolved threads. Record each `MERGED` line and
   each `BLOCKED` line's whole `blockers=` list, not just `reason=`.
   `automerge=preexisting` is someone else's armed request and withholds nothing.
   Record the merge dispatch and receipt at its exact head; `armed` is pending, never
   merged. If the operator asked for review before landing, every PR is review-gated:
   skip this helper, read state with `list-prs.sh`, and give every unmerged PR a job
   (step 4) even without repair work.
3. Keep the PR table in this thread. Post it after the quick pass and at the end of
   every turn:

   | PR | Description | Not merged because |
   |---|---|---|
   | [owner/repo#12](https://github.com/owner/repo/pull/12) | PR title | 3 unresolved threads; failing check `lint`; fixer round 2 (candidate 1) |

   Emit each job's compact overview checklist; never stream raw logs.
4. Classify each unmerged PR from `blockers=`. Child work: conflicts, a branch the
   helper could not update, failing checks, unresolved threads that need code, and
   requested changes. Coordinator work: threads needing only an answer (step 7).
   Waiting only: checks running at the current head. A required human review with
   nothing left to fix is `needs human:` (step 8). Every PR with child work gets a
   fixer now, with no concurrency cap and no question. Create one job per such PR with
   `PKG/references/job-plan.md`.
5. Prepare each fixer's worktree with `bash PKG/scripts/pr-workspace.sh`. Recommend
   the cheapest suitable tier within role floors; use upfront selected work
   target/options and approved replacements. Show live-catalog choices without routing.
   Never infer an answer; report `unavailable` entries.
6. Dispatch per `PKG/shared/job-coordination.md`: `job_cli.py prepare`, launch
   `babysitter/pr-maintainer` with `delegate_task`, and record the handle with
   `task-observation`. Reserve it with `continuous.py dispatch --kind fixer`; a second
   fixer or a live-fixer merge is refused. The immutable brief carries PR context:
   URL, worktree, head, the complete `blockers=` list, every unresolved thread's ID and
   comments,
   prior findings and authorized actions. Task text carries current coordinator-owned
   `retry_usage`. Finish with every listed blocker cleared at a pushed head,
   local verification and thread dispositions, or `blocked` naming the human-only
   decision. Children never run `merge-pr.sh` merge, arm, or resolve modes.
7. Before landing or watching, inspect every unresolved thread at the current head,
   including all pages. Verify fixes there or establish why no change applies. Post
   and resolve each disposition with `bash PKG/scripts/merge-pr.sh
   --repo <owner/name> --pr <N> --resolve-thread <ID> --verified-head <head>
   --reply-file <file>`. Record its dispatch and receipt after ingestion; a live fixer
   blocks it. Re-read to confirm resolution. Actionable minor findings need fixes too;
   severity alone never justifies an answer. A refused resolution is inspected and
   recovered within authority; ask only for a human-only action.
8. On a scheduled sweep, wake or child completion, refresh scope discovery (step 12),
   read `task_status`, ingest completed results with `job_cli.py result`, verify the
   claimed push against the PR head, and record the outcome with `continuous.py
   fixer-done` or `receipt`; a replay clears no newer guard. perform step 7 before
   attempting to land. Fresh: a check from an older SHA proves nothing. Rerun step 2's
   helper for that PR unless its fixer is in flight or it is review-gated; a
   review-gated PR merges only through its land stage's pinned command. Then reconcile
   every child through `task_status` and refill: each PR with child work and no child in
   flight gets its next round now through `job_cli.py retry` with the prior findings
   (`needs-followup` follows `PKG/references/job-plan.md`). A child returning
   `blocked`, a malformed result or a repeated blocker does not authorise escalation:
   use only the approved work chain or obtain a new choice. Rounds share the finite `max_repair_cycles` allowance;
   raising exhausted limits needs a recorded owner decision. Call `watch_pull_request`
   for every unmerged PR after available repair/resolution. Children cannot watch;
   this thread owns every watch.
9. Before ending any turn, refresh scope discovery and record each PR's next
   action/deadline with `continuous.py observe`; on a host wake pass `--wake-kind
   schedule`. Every unmerged row needs a child in flight, current checks running,
   confirmed ownership elsewhere, or a concrete external blocker with a next check.
   Diagnose stalls within authority; never raise timeouts, rerun an unchanged failure
   or report an armed watch as progress. Anything else is acted on now. A health or
   ledger failure stops writes and is `needs human:`. Never end a turn on "auto-merge
   armed" alone. Then post the table and end the turn.
10. Accept merged jobs from fresh observations: rebind and publish per
    `PKG/references/job-plan.md`, then `job_acceptance_cli.py accept-stage` with the
    pinned `validate_pr.py`. Update the table and `unwatch_pull_request`.
11. If `delegate_task` is unavailable, record it. Direct fixing needs approved
    authority or a new choice. Keep the visible fallback marker. A failed candidate
    alone grants no target substitution.
12. Refresh org/repo discovery at entry, every wake/completion, and before yielding
    or handing off. Admit new matches without asking; quick-pass under step 2's skip
    rules (in-flight fixer, review-gated), then return to the caller. Callers run
    step 4 for newly admitted PRs with child work or requested review before yielding.
    Never re-enter step 8 from discovery. Follow `PKG/references/scope.md` and
    `PKG/references/continuous.md`. Persistent scheduled discovery uses the host
    scheduler only when requested; report its ID and coverage.
13. Hand off only after a fresh complete discovery has no untreated eligible PRs;
    every row must be merged, owned elsewhere or `needs human:`. Run `job_acceptance_cli.py
    validate-final` per job with fresh observations, unwatch PRs, confirm every child
    stopped through `task_status`, and remove only clean, task-owned worktrees. Post the
    table. Do not run `pr-events.sh` in T3.

Written strategies require `PKG/shared/adopter-planning.md`.
