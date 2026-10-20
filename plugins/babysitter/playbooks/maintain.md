# Maintain pull requests

At an operator-requested final-head PR review, use `PKG/shared/supplemental-reviews.md` only with consent and when the coordinator checkout is already at the reviewed PR HEAD.
Never change checkouts merely to enable extras.

The coordinator owns the roster, PR table, watches, merges, resolutions and acceptance.
Children repair one PR at a time. Every PR with fixable work has a child each turn.

1. Ask the auto-merge posture through the picker unless the request names one, and
   record it with `job_cli.py decision` (entry); under **ignore**, exclude any roster PR that already carries an
   armed request. Then resolve the scope; inspect the roster with
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
   checks all succeeded, updates behind branches, and arms auto-merge. Record each
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
5. Prepare each fixer's worktree with `bash PKG/scripts/pr-workspace.sh`. Recommend
   the cheapest suitable tier within role floors; use upfront selected work
   target/options and approved replacements. Show live-catalog choices without
   routing. Never infer an answer; report `unavailable` entries.
6. Dispatch per `PKG/shared/job-coordination.md`: `job_cli.py prepare`, launch
   `babysitter/pr-maintainer` with `delegate_task`, and record the handle with
   `task-observation`. The brief carries the PR URL, its worktree, the head at
   dispatch, the complete `blockers=` list, every unresolved thread's ID and comments,
   earlier rounds' findings, and that PR's recorded actions. Finish line: every listed
   blocker cleared at a pushed head with local verification, and a disposition for
   every thread; or `blocked` with what only a human can decide. Children never run
   `merge-pr.sh` merge, arm, or resolve modes.
7. Threads: once a push is verified at the PR head, or for a thread that needs only an
   answer, post each disposition and resolve it with `bash PKG/scripts/merge-pr.sh
   --repo <owner/name> --pr <N> --resolve-thread <ID> --verified-head <head>
   --reply-file <file>`. Minor or note findings on an otherwise mergeable PR get a
   reasoned reply and resolution, never a push that restarts review. If the host
   refuses a resolution, ask through the picker at once and mark the row
   `needs human:`.
8. Call `watch_pull_request` for every unmerged PR. Children cannot watch; this thread
   owns every watch. On a PR wake, read that PR's live state at its current head; a
   check from an older SHA proves nothing. Rerun step 2's helper for that PR unless its
   fixer is in flight or it is review-gated; a review-gated PR merges only through its
   land stage's pinned command. On a child completion, read `task_status`, ingest with
   `job_cli.py result`, verify the claimed push against the PR head, and dispose every
   finding with evidence. Then reconcile every child through `task_status` and refill:
   each PR with child work and no child in flight gets its next round now through
   `job_cli.py retry` with the prior findings (`needs-followup` follows
   `PKG/references/job-plan.md`). A child returning `blocked`, a malformed result or a
   repeated blocker does not authorise escalation: use only the approved work chain
   or obtain a new choice. Review replacement authority is separate. Re-request
   a malformed result immediately, naming the schema error. Rounds
   are not capped. Mark a row `needs human:` and ask through the picker only when the
   same blocker survives the strongest candidate twice or only a human can clear it.
9. Before ending any turn, check for dead ends. Every unmerged row must have a child in
   flight, checks running on its current head, or a picker question already asked.
   A check queued 30 minutes with no runner is a `needs human:` blocker. Anything
   else is acted on now. Never end a turn on "auto-merge armed" alone. Then post the
   table and end the turn.
10. Accept each merged PR's job from a fresh coordinator observation: rebind and
    publish per `PKG/references/job-plan.md`, then `job_acceptance_cli.py
    accept-stage` with the pinned `validate_pr.py`. Update the table and
    `unwatch_pull_request`. Report a merge as pending until observed.
11. If `delegate_task` is unavailable, record it. Direct fixing needs approved work
    authority or a new choice. Keep the brief, actions, counters and visible fallback marker.
    A failed candidate alone grants no target substitution.
12. Org/repo discovery of future PRs needs an explicitly authorized T3 scheduled sweep;
    watching today's PRs does not discover tomorrow's. Use the host scheduler only
    when requested, bounded in scope and cadence. Report its ID and stop command.
13. Hand off when every row is merged or `needs human:`. Run `job_acceptance_cli.py
    validate-final` per job with fresh observations, unwatch PRs, confirm every child
    stopped through `task_status`, and remove only clean, task-owned worktrees. Post the
    final table. Never claim all landed from an empty or partial response. Do not run
    `pr-events.sh` in T3; it is retained only as a legacy standalone adapter.

Written strategies require `PKG/shared/adopter-planning.md`.
