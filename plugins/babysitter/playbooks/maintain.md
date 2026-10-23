# Maintain pull requests

Require upfront named-model or bounded-class consent in the frozen selection for
`PKG/shared/supplemental-reviews.md`: coordinator checkout is already at the reviewed PR HEAD.
Never change checkouts merely to enable extras.

The coordinator owns discovery, watches, merges, resolutions and acceptance; children
repair one PR. Follow `PKG/references/job-plan.md`'s repair cycle.
Writable runs initialise `continuous.py` state per `PKG/references/continuous.md`;
use event-only without scheduler authority.

1. Apply the entry's auto-merge default or explicit override without a question;
   record it with `job_cli.py decision`; under **ignore**, exclude PRs with an
   armed request. Inspect the roster with
   `bash PKG/scripts/list-prs.sh --all-authors --repo <owner/name>` / `--org <owner>`.
   Read warnings: a partial page is not the whole roster. Follow
   `PKG/references/scope.md`: include all authors and bots; exclude drafts and forks
   unless included by the operator. Run the sibling-work check in
   `PKG/shared/t3-runtime.md` per PR; another active thread's PR stays
   visible as owned elsewhere. Read-only runs skip this check.
   Record scope and link each admitted PR with `link_pull_request`. An
   inspect-only run skips step 2's helper, posts step 3's table, and stops; deep triage
   may plan `read` only maintainer slots, whose `blocked` results answer triage but
   never an acceptance.
2. Quick pass, in this thread, before any child: refresh with `continuous.py observe`;
   reserve current `merge` or `update-branch` with
   `continuous.py dispatch --kind <kind> --reserve --head <head>` before
   `bash PKG/scripts/merge-pr.sh --repo <owner/name> --pr <N>`.
   For `update-branch`, add `--update-only --expected-head <head>`; record `UPDATED`,
   refresh new-head gates before any merge reservation. For `merge`, add
   `--expected-head <head>` and `--arm-always` under **enable**, otherwise `--no-auto`.
   Record `MERGED` and each `BLOCKED` line's whole `blockers=` list, not just `reason=`.
   `automerge=preexisting` is someone else's armed request and withholds nothing.
   Record reservation/head receipts; `armed` is pending, never
   merged. If the operator asked for review before landing, every PR is review-gated:
   skip this helper, read state with `list-prs.sh`, and give every unmerged PR a job
   (step 4) even without repair work.
3. Post it after the quick pass and at the end of every turn:

   | PR | Description | Not merged because |
   |---|---|---|
   | [owner/repo#12](https://github.com/owner/repo/pull/12) | PR title | 3 unresolved threads; failing check `lint`; fixer round 2 (candidate 1) |

   Emit each job's compact overview checklist; never stream raw logs.
4. Classify each unmerged PR from `blockers=`. Child work: conflicts, an
   unupdatable branch, failing checks, unresolved threads needing code, requested
   changes. Coordinator work: threads needing only an answer (step 7).
   Waiting only: checks running at the current head. A required human review with
   nothing left to fix is `needs human:`. Every PR with child work gets a
   fixer now, no concurrency cap and no question, one job each with
   `PKG/references/job-plan.md`.
5. Prepare each fixer's worktree with `bash PKG/scripts/pr-workspace.sh`. Recommend
   the cheapest suitable tier within role floors; use upfront selected work
   target/options and approved replacements. Show live-catalog choices without routing.
   Never infer an answer; report `unavailable` entries.
6. Dispatch per `PKG/shared/job-coordination.md`: `job_cli.py prepare`, reserve with
   `continuous.py dispatch --kind fixer --reserve` before launching
   `babysitter/pr-maintainer`, then attach the handle with `--host-task-id`. Close a
   confirmed refusal with `receipt --status rejected`. A lost response is `uncertain`;
   retain the reservation until host reconciliation finds the handle or proves refusal.
   The immutable brief carries URL, worktree, head, the complete `blockers=` list,
   every unresolved thread's ID and comments, prior findings, authorised actions and
   coordinator-owned `retry_usage`. Finish with every listed blocker cleared at a pushed head,
   local verification and thread dispositions, or `blocked` naming the human-only
   decision. Children never run `merge-pr.sh` merge, arm, or resolve modes.
7. Before landing or watching, inspect every unresolved thread at the current head,
   including all pages. Verify fixes there or establish why no change applies. Reserve
   `continuous.py dispatch --kind resolution --reserve --head <head>`
   before posting and resolving each disposition with `bash PKG/scripts/merge-pr.sh
   --repo <owner/name> --pr <N> --resolve-thread <ID> --verified-head <head>
   --reply-file <file>`. Record the receipt afterward; any reserved write blocks another.
   Re-read to confirm resolution. Actionable minor findings need fixes too;
   severity alone never justifies an answer. Recover a refused resolution within authority;
   ask only for a human-only action.
8. On a scheduled sweep, wake or child completion, refresh scope discovery (step 12),
   read `task_status`, ingest results with `job_cli.py result`, verify the
   claimed push against the PR head, and record the outcome with `continuous.py
   fixer-done` or `receipt`, naming the writer's handle and job-retained result transport.
   The helper verifies ingestion and terminal host identity before closing writer guards;
   `armed` is merge-only and replays clear no newer guard; perform step 7 before landing;
   a check from an older SHA proves nothing. Rerun step 2's
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
9. Before yielding, refresh discovery and each PR's next action/deadline with
   `continuous.py observe` (`--wake-kind schedule` on wakes). Every unmerged row
   needs a worker, current checks, confirmed owner or concrete blocker/next check.
   Report live resolution request/host identities until matching terminal receipts.
   Diagnose stalls within authority; never raise timeouts, rerun unchanged failures or
   count armed watches as progress. Anything else is acted on now. Health/ledger failures stop
   writes as `needs human:`. Never end a turn on "auto-merge armed" alone.
   Then post the table and end the turn.
10. Accept merged jobs from fresh observations: rebind and publish per
    `PKG/references/job-plan.md`, then `job_acceptance_cli.py accept-stage` with the
    pinned `validate_pr.py`; update the table and `unwatch_pull_request`.
11. If `delegate_task` is unavailable, record it. Direct fixing needs approved
    authority or a new choice. Keep the visible fallback marker. A failed candidate
    alone grants no target substitution.
12. Refresh discovery at entry, every wake/completion, and before yielding
    or handing off. Admit new matches without asking; quick-pass under step 2's skip
    rules (in-flight fixer, review-gated), then return to the caller. Callers run
    step 4 for newly admitted PRs with child work or requested review before yielding.
    Never re-enter step 8 from discovery. Follow `PKG/references/scope.md` and
    `PKG/references/continuous.md`. Persistent scheduled discovery uses the host scheduler only
    when requested; report its ID and coverage.
13. Hand off only after a fresh complete discovery has no untreated eligible PRs;
    every row must be merged, owned elsewhere or `needs human:`. Run `job_acceptance_cli.py
    validate-final` per job with fresh observations, unwatch PRs, confirm every child
    stopped through `task_status`, and remove only clean, task-owned worktrees. Post the
    table. Do not run `pr-events.sh` in T3.

Written strategies require `PKG/shared/adopter-planning.md`.
