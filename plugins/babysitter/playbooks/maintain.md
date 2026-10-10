# Maintain pull requests

1. Resolve the exact scope and endstate. Inspect the roster through GitHub tools or
   `bash PKG/scripts/list-prs.sh --repo <owner/name>` / `--org <owner>`.
   For a named PR add `--pr <number>`. Read the helper's filter and pagination warnings;
   a partial page is not the whole roster. Exclude drafts, forks, and other authors
   unless the operator includes them. Freeze and report the eligible roster.
2. Link each PR through T3. Inspect current head/base, required checks, review threads,
   merge requirements, and branch drift. A check from an older SHA cannot clear a blocker.
3. Work in an isolated checkout for each PR. The bundled `pr-workspace.sh` supports
   explicit `--repo`, `--pr`, `--branch`, and `--root`. Preserve dirty user changes.
   T3 children may work on independent PRs when authorized; retain every task ID.
4. Triage evidence before editing. Separate code failures from unavailable external
   review services. Fix valid findings, test the changed behavior, inspect the diff,
   and push only the named branch. Reply to and resolve handled threads only when
   communication is in scope, with evidence at the current head. Rejected findings
   need a reason. Do not resolve a thread merely to make the merge button available.
5. Refresh head and requirements before attempting the repository's permitted merge
   method. Prefer host GitHub tools. `merge-pr.sh` is an optional CLI adapter with
   guarded current-head operations; inspect its help before using it. Never use admin
   bypass, dismiss reviews, weaken checks, or force-push shared history to get green.
6. For ongoing monitoring, register each PR with T3 `watch_pull_request` and yield.
   Do not run `pr-events.sh` in T3; it is retained only as a legacy standalone adapter.
   On wake, recheck live evidence. Report auto-merge as queued until merge is observed.
7. Org/repo discovery of future PRs needs an explicitly authorized T3 scheduled sweep;
   watching today's PRs does not discover tomorrow's. Use the host scheduler only
   when requested, with a bounded scope and cadence. Report its ID and stop command.
8. At handoff, unwatch PRs and stop task-owned children. Remove only clean, task-owned
   worktrees when authorized. Report merged, open, and blocked PRs separately, including
   exact remaining blockers. Never claim all landed from an empty or partial response.
