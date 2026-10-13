# Maintain pull requests

1. Resolve the exact scope and endstate. Inspect the roster through GitHub tools or
   `bash PKG/scripts/list-prs.sh --repo <owner/name>` / `--org <owner>`.
   For a named PR add `--pr <number>`. Read the helper's filter and pagination warnings;
   a partial page is not the whole roster. Exclude drafts, forks, and other authors
   unless the operator includes them. Freeze the eligible roster and link each PR
   through T3. An inspect-only run skips step 2's helper, posts step 3's table from
   read-only evidence, and stops.
2. Quick pass, in this thread, before any child: for every roster PR run
   `bash PKG/scripts/merge-pr.sh --repo <owner/name> --pr <N> --arm-always`.
   It merges a PR whose current head is CLEAN with green checks and resolved threads,
   and otherwise attempts to arm GitHub auto-merge, including on PRs with open threads
   or conflicts; the operator accepted that auto-merge may land those once GitHub's own
   requirements pass. Record each `MERGED` or `BLOCKED reason=... automerge=...` line;
   `automerge=unavailable` means GitHub refused, so this thread must merge it later.
   Inspect its help first. Never use admin bypass, dismiss reviews, or weaken checks.
3. Keep the PR table in this thread and post it after the quick pass:

   | PR | Description | Not merged because |
   |---|---|---|
   | [owner/repo#12](https://github.com/owner/repo/pull/12) | PR title | failing check `lint`; auto-merge armed; fixer round 1 |

   The last column names the current blocker in plain words, the auto-merge state,
   and any fixer in flight. Merged rows read `merged` and move to the bottom.
   Post the whole table again each time a PR merges and when a blocker changes.
4. Dispatch one fixer per PR that has work a child can do: conflicts, a behind branch
   the helper could not update, failing checks, unresolved threads, or requested
   changes. A PR waiting only on running checks or a required human review gets no
   child; watch it. Prepare each PR's worktree with `bash PKG/scripts/pr-workspace.sh`,
   then run `t3-plugins resolve workhorse --capabilities FILE --repo <that worktree>`
   so the target repository's routing policy applies. Start with the first candidate
   on the cheapest configured tier and pass its `runtimeMode`; later candidates are for
   escalation. Report each `unavailable` entry once, such as a provider that needs a
   broader mode than this thread. Without routing, or with no cheapest-tier candidate,
   report that and ask the operator before fanning out. Give each child its worktree.
5. Each brief follows `PKG/shared/delegation.md` and adds: the PR URL, the head SHA
   at dispatch, the blocker, and earlier rounds' findings. Pre-authorize: edit and
   test in its worktree; push to that PR's head branch only, never forced; reply to
   handled threads with evidence and resolve them through `merge-pr.sh
   --resolve-thread`; then run `merge-pr.sh --arm-always`. Finish line: the blocker is
   fixed at a pushed head, local verification passes, and the helper reports
   `MERGED` or only pending checks or a human review. Return the PR, pushed SHAs,
   helper output, tests run, and remaining blockers. Return `blocked` for product
   decisions, secrets, or human approval. Rejected findings need a reason.
6. Call `watch_pull_request` for every unmerged PR and end the turn. Children cannot
   watch; this thread owns every watch. On a wake, read that PR's live state at its
   current head; a check from an older SHA proves nothing. Rerun step 2's helper first:
   green checks or a new approval may make the PR mergeable now. When it merged,
   update the table and unwatch it. On a new failure, comment, or conflict with no
   child in flight, dispatch the next round as a new `delegate_task` with the prior
   findings.
   On a child result, verify the claimed push against the PR head before relying on it.
7. Escalate when a child returns `blocked` or a blocker survives its round: use the
   next `resolve` candidate. After two rounds on the last candidate, or when a human
   must act, mark the row `needs human:` with the exact blocker and stop dispatching.
   Report auto-merge as queued until the merge is observed.
8. Org/repo discovery of future PRs needs an explicitly authorized T3 scheduled sweep;
   watching today's PRs does not discover tomorrow's. Use the host scheduler only
   when requested, with a bounded scope and cadence. Report its ID and stop command.
9. Hand off when every row is merged or `needs human:`. Unwatch PRs, confirm every
   child stopped through `task_status`, and remove only clean, task-owned worktrees.
   Post the final table. Never claim all landed from an empty or partial response.
   Do not run `pr-events.sh` in T3; it is retained only as a legacy standalone adapter.
