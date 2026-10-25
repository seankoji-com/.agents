# Deterministic org triage

Run one read-only sweep at entry or on a host wake:

```sh
python3 PKG/scripts/org_scan.py --org <owner>
```

For a writable admitted org run, the coordinator prepares the frozen configuration
once, then uses `--execute --run-config <RUN.json>` as described in
`PKG/references/org-execution.md`. This enables auto-merge without a question and
launches repair agents deterministically. The remainder of this file describes the
read-only report and its shared scan limits.

Python 3.10+ and authenticated `gh` are required. It emits one JSON object. Exit 0
means a complete observation; 2 means invalid arguments; 3 means incomplete.
Retain JSON even on exit 3. Never interpret a command failure or empty `dispatch`
array as a healthy org. Inspect `complete`, `gaps`, and each PR's `unknowns`.

The scan enumerates every repository visible to this credential, then all open PR
pages, without search's result cap. It excludes drafts, includes all authors and
forks, and sorts by repository and number. It cannot see repositories the credential
cannot access. Apply the run's saved exclusions, fork policy, auto-merge override
and sibling ownership before admission or writes. Forks remain visible even when
the run cannot repair them. `complete` describes accessible API coverage, never org
administrator inventory or merge acceptance.

## Decisions for a small coordinator

Each `prs` row names the exact `head_sha`, `action`, `reasons`, `unknowns`,
`coordinator_actions`, failing/pending checks and unresolved thread IDs.
`summary` counts actions; `dispatch` contains the sorted repair-candidate URLs.

- `dispatch`: a conflict, failed check, unresolved review thread, or requested
  changes. Include every reason in one PR's brief. Queued checks never hide a known
  failure. All observed failures, including optional checks, qualify for this org
  triage policy; this does not change the separate landing gate's required checks.
- `coordinator`: enable auto-merge, update a behind branch, obtain a required review,
  or inspect an otherwise unexplained merge gate. Auto-merge alone needs no model
  repair task. Follow the existing guarded quick pass within recorded authority.
- `waiting`: only queued/running checks, auto-merge enabled, no known blocker.
- `healthy`: auto-merge enabled, resolved review threads, no observed failed or
  pending checks, no conflicts and no other observed gate. It does not mean merged.
- `unknown`: missing/changed/incomplete evidence or GitHub has not computed
  mergeability. Re-read that PR with a targeted reader; never launch a code repair
  solely because evidence is unknown.

Known repair evidence takes priority over unknown evidence or coordinator actions;
all remain on the row. `complete: false` prevents an all-clear claim, including when
a known dispatch candidate also has a truncated thread/check page. A budget gap
leaves unvisited PRs absent, so do not remove them from the existing ledger.

Completed `SUCCESS`, `NEUTRAL` and `SKIPPED` checks are accepted. Cancelled, timed
out, stale, startup failure and action-required conclusions are failures. Pending
check/status states are allowed; unrecognized states are unknown. `checks: none`
means no reported check contexts, not that configured required checks passed.
The scan reads the PR head rollup, never an older commit's checks. It does not
enumerate branch rules or certify a test merge/merge-group commit. Recheck those
through the existing landing workflow.

"Resolved comments" means every GitHub review thread has `isResolved: true`,
including outdated threads. Ordinary PR conversation comments have no resolution
flag; this script cannot decide whether their prose needs action. The scan fetches
IDs and flags only. Fetch comments for the selected PR when preparing its brief,
verify the fix and reply before resolving, as in `maintain.md`.

Before dispatch, reconcile the saved host handles and sibling ownership. Recheck the
PR's current head, prepare the existing per-PR job and immutable brief, then reserve
the fixer through `continuous.py dispatch --kind fixer --reserve` before
`delegate_task`. Attach its returned task ID. A repeated `observation_key` means
unchanged triage evidence, not permission to launch again; live reservations and
receipts control duplicates, retries and competing writers. The hash excludes
observation timestamps. It does not replace fresh landing/acceptance evidence.

## API budget and recurring wakes

The helper runs once and exits. Use T3's host scheduler for explicitly requested
periodic coverage, for example a 900-second cadence through `continuous.py start
--cadence-seconds 900`, `schedule-plan`, the returned `schedule_task` arguments and
`schedule-record`. The existing default stays 600 seconds. Do not add a shell loop,
another scheduler or `pr-events.sh`. Continue native PR watches for linked PRs.

Every sweep observes fresh checks and thread flags. PR `updatedAt` is deliberately
not a cache key: unchanged PR metadata does not prove unchanged CI or resolution.
Repositories are read 100 at a time; PRs are read 25 at a time in batches of up to
10 repositories. Thread and check pages contain at most 100 nodes each, and every
tail is followed. No comment bodies, logs or per-job REST calls are fetched.

Requests are serial with at least one second between starts. Defaults stop at 100
requests, a 200-point budget, 180 elapsed seconds or a 500-point remaining reserve.
The helper reads `rateLimit` first and with every response, checking a conservative
query-cost estimate before the next call. `api` reports returned costs, conservative
charges for failed requests or mutations without rate data, and the last reset time.
GitHub can change its cost formula; these are bounds on requests/estimated
admission, not a guarantee about server billing. Transient 502/503/504 and timeouts
get at most three attempts within the same budgets; rate limits and permission
errors stop immediately. GraphQL errors invalidate partial response data.

`--max-requests`, `--max-cost`, `--reserve`, `--deadline` and `--spacing` tune these
limits. Increase budgets only after inspecting usage. Four scans an hour with the
default cost ceiling admit at most about 800 points an hour, plus formula drift
and other clients' consumption. Budget exhaustion is explicit incomplete coverage.
An exclusive per-org lock under the XDG state directory prevents overlapping scans
on the same host. `--state-dir` overrides that directory. There is no cached result.

This JSON is a triage report, not the full `continuous.py observe` input. Continue
targeted `list-prs.sh --repo <owner/name> --pr <N>` reads for that ledger, queue-age
diagnosis, briefs, mutations and acceptance. Keep those reads due under the existing
continuous policy; this scan does not supply queued-job clocks or diagnose stalls.

API semantics: [pagination](https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api),
[limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api),
[review threads](https://docs.github.com/en/graphql/reference/pulls#pullrequestreviewthread)
and [check states](https://docs.github.com/en/graphql/reference/checks#checkconclusionstate).
