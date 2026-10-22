# Maintain pull requests

Require upfront named-model or bounded-class consent in the frozen selection for `PKG/shared/supplemental-reviews.md`.
Require: coordinator checkout is already at the reviewed PR HEAD.
Never change checkouts merely to enable extras.

The coordinator owns discovery, watches, merges, resolutions and acceptance.
Children repair one PR each.
Follow `PKG/references/job-plan.md`'s repair cycle, including its health stop rule.

1. Apply the entry's auto-merge default or explicit override without a question;
   record it with `job_cli.py decision`; under **ignore**, exclude PRs with an
   armed request. Inspect the roster with
   `bash PKG/scripts/list-prs.sh --all-authors --repo <owner/name>` / `--org <owner>`, adding
   `--pr <number>` for a named PR. Read warnings; a partial
   page is not the whole roster. Follow `PKG/references/scope.md`: include all authors
   and bots; exclude drafts and forks unless included by the operator. Run the sibling-work check in
   `PKG/shared/t3-runtime.md` per PR number and head branch; a PR another active
   thread maintains stays visible as owned elsewhere. Read-only runs skip this check. Record scope and
   link each admitted PR with `link_pull_request`. An inspect-only run skips
   step 2's helper,
   posts step 3's table from read-only evidence, and stops; for deep triage it may plan
   `read` only maintainer slots, whose `blocked` results with named blockers are a
   complete triage answer, never an acceptance.
2. Quick pass, in this thread, before any child: for each unowned PR with no fixer in flight run
   `bash PKG/scripts/merge-pr.sh --repo <owner/name> --pr <N> --no-auto`, or
   `--arm-always` under **enable**. It merges CLEAN PRs and UNSTABLE PRs whose required
   checks all succeeded, updates behind branches, and arms auto-merge only with complete,
   resolved threads. Record each
   `MERGED` line and each `BLOCKED` line's whole `blockers=` list, not just `reason=`.
   `automerge=preexisting` is
   someone else's armed request and withholds nothing. If the operator asked for review
   before landing, every PR is review-gated: skip this helper, read state with
   `list-prs.sh`, and give every unmerged PR a job (step 4) even without repair work.
3. Keep the PR table in this thread. Post it after the quick pass and at the end of
   every turn:

   | PR | Description | Not merged because |
   |---|---|---|
   | [owner/repo#12](https://github.com/owner/repo/pull/12) | PR title | 3 unresolved threads; failing check `lint`; fixer round 2 (candidate 1) |

   List blockers, auto-merge state and children; put merged rows last. Emit each
   job's `job_cli.py overview --compact` checklist, following `next_cursor` for omitted
   obligations; never stream raw logs.
4. Classify each unmerged PR from `blockers=`. Child work: conflicts, a branch the
   helper could not update, failing checks, unresolved threads that need code, and
   requested changes, from bots or humans. Coordinator work: threads whose fix already
   landed or that need only an answer (step 7). Waiting only: checks running on the
   current head. A required human review with nothing left to fix is `needs human:`
   (step 8). Every PR with
   child work gets a fixer now, all at once, with no concurrency cap and no question.
   Create one job per such PR with `PKG/references/job-plan.md`; PRs without child work
   need no job.
5. Prepare each fixer's worktree with `bash PKG/scripts/pr-workspace.sh`. Recommend
   the cheapest suitable tier within role floors; use upfront selected work
   target/options and approved replacements. Show live-catalog choices without
   routing. Never infer an answer; report `unavailable` entries.
6. Dispatch per `PKG/shared/job-coordination.md`: `job_cli.py prepare`, launch
   `babysitter/pr-maintainer` with `delegate_task`, and record the handle with
   `task-observation`. The immutable brief carries PR context: URL, worktree, head,
   the complete `blockers=` list, every unresolved thread's ID and comments,
   prior findings and authorized actions. Task text carries current coordinator-owned
   `retry_usage`. Finish with every listed blocker cleared at a pushed head,
   local verification and thread dispositions, or `blocked` naming the human-only decision. Children never run
   `merge-pr.sh` merge, arm, or resolve modes.
7. Before landing or watching, inspect every unresolved thread at the current head,
   including all pages. Verify fixes there or establish why no change applies. Post
   each disposition and resolve it with `bash PKG/scripts/merge-pr.sh
   --repo <owner/name> --pr <N> --resolve-thread <ID> --verified-head <head>
   --reply-file <file>`. Re-read to confirm resolution. Actionable minor findings need
   fixes too; severity alone never justifies an answer. If the host
   refuses a resolution, inspect the failure and recover within authority; ask only
   for a remaining human-only action.
8. On a wake or child completion, refresh scope discovery (step 12), read `task_status`, ingest completed results with
   `job_cli.py result`, verify the claimed push against the PR head, and perform step 7
   before attempting to land. Read fresh state; a check from an older SHA proves nothing.
   Rerun step 2's helper for that PR unless its fixer is in flight or it is review-gated;
   a review-gated PR merges only through its land stage's pinned command. Then
   reconcile every child through `task_status` and refill:
   each PR with child work and no child in flight gets its next round now through
   `job_cli.py retry` with the prior findings (`needs-followup` follows
   `PKG/references/job-plan.md`). A child returning `blocked`, a malformed result or a
   repeated blocker does not authorise escalation: use only the approved work chain
   or obtain a new choice. Review replacement authority is separate. Re-request
   malformed results within budget, naming the schema error. Rounds share the
   finite `max_repair_cycles` allowance; raising exhausted limits needs a recorded owner decision.
   Repeated failure changes diagnosis, not authorization; ask only for human-only actions.
   Call `watch_pull_request` for every unmerged PR after taking available repair and
   resolution actions. Children cannot watch; this thread owns every watch.
9. Before ending any turn, refresh scope discovery and check for dead ends. Every
   unmerged row needs a child in flight, current-head checks running, confirmed
   ownership elsewhere, or a concrete human-only blocker. Diagnose stalled queues;
   repair what is authorized. Anything else is acted on now.
   A health or ledger failure stops writes and is `needs human:`.
   Never end a turn on "auto-merge armed" alone. Then post the
   table and end the turn.
10. Accept merged PR jobs from fresh observations: rebind and
    publish per `PKG/references/job-plan.md`, then `job_acceptance_cli.py
    accept-stage` with the pinned `validate_pr.py`. Update the table and
    `unwatch_pull_request`. Unobserved merges stay pending.
11. If `delegate_task` is unavailable, record it. Direct fixing needs approved work
    authority or a new choice. Keep the brief, actions, counters and visible fallback marker.
    A failed candidate alone grants no target substitution.
12. Refresh org/repo discovery at entry, every wake/completion, and before yielding
    or handing off. Admit new matches without asking; quick-pass under step 2's skip
    rules (in-flight fixer, review-gated), then return to the caller. Callers run
    step 4 for newly admitted PRs with child work or requested review before
    yielding. Never re-enter step 8 from discovery. Follow `PKG/references/scope.md`.
    Persistent scheduled discovery uses the host scheduler only when requested;
    report its ID and stop command.
13. Hand off only after a fresh complete discovery has no untreated eligible PRs;
    every row must be merged, owned elsewhere or `needs human:`. Run `job_acceptance_cli.py
    validate-final` per job with fresh observations, unwatch PRs, confirm every child
    stopped through `task_status`, and remove only clean, task-owned worktrees. Post the
    final table. Do not run `pr-events.sh` in T3.

Written strategies require `PKG/shared/adopter-planning.md`.
