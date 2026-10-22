# Continuing scope and routine decisions

Read with `PKG/playbooks/maintain.md`. The request defines a selection, not a fixed
list of PR IDs. `pr` selects one PR; `repo` and `org` select eligible open PRs in
that repository or organization throughout the active run. Preserve explicit user
restrictions, including inspect-only mode and exclusions.

## Discovery and admission

- Discover at entry, every wake or child completion, and before yielding or final
  handoff. Reuse the same scope and filters. Repo/org runs pass `--all-authors` to
  `list-prs.sh`: human and bot PRs qualify. Drafts and forks stay excluded unless
  explicitly included; do not treat an author's identity as an extra exclusion.
  Admission uses the helper's eligibility filters. Add `--include-drafts` or
  `--include-forks` only when the operator includes those PRs.
- A new matching PR needs no renewed authorization. Link it, add its row, record
  its per-PR actions from the saved request before mutations, run the quick pass,
  and create a separate job if repairs are needed. Never rewrite an existing job's
  PR identity, immutable brief, evidence or model choices to add another PR.
  A refresh only admits new matches and quick-passes them under step 2's skip rules
  (no in-flight fixer, review gate or competing owner), then returns to its caller.
  It never invokes step 8 recursively or reconciles existing jobs. After return,
  the caller runs step 4 for every newly admitted PR with child work or requested
  review, creating its job and dispatching its fixer through steps 5–6 before
  yielding. Existing jobs reconcile once through step 8.
  Every merge-helper invocation skips a PR with a fixer in flight,
  including during discovery refresh and the quick pass.
- Complete discovery matters. If the helper warns about a partial search page,
  finish discovery with supported paginated GitHub reads or nonoverlapping narrower
  queries covering the scope. For an org, enumerate every repository page and each
  repository's open-PR pages if search is capped. Deduplicate by PR URL. A denied or
  incomplete read is a named discovery gap, never evidence that all PRs are done.
- Recheck eligibility and the current head before writes. Keep previously admitted
  PRs visible if they close, become drafts, lose access or acquire another owner;
  report that state and stop disallowed actions. Closed without merge is not merged.
- Confirmed active ownership elsewhere prevents duplicate writers; keep that row
  and owner visible and continue other PRs. Such rows are read-only: skip the merge
  helper, fixer dispatch, replies/resolutions and watches for them. Never claim them
  completed by this run. Ask only if transferring ownership is
  necessary to finish. A new commit alone proves no active writer: fetch, integrate,
  test and continue in the isolated worktree, with pinned leases for rewritten heads.

Native PR watches wake for linked PR changes, not new PR discovery. Refresh before
arming them and on each wake; do not invent an org watch, shell event loop or second
scheduler. If discovery cannot run while idle, state that gap. Persistent discovery
after handoff needs an explicitly requested host schedule, bounded in scope and
cadence. Active-run discovery never needs that extra authorization.

## Retry limits

For an unchanged transient failure, use at most 3 attempts or 5 minutes, whichever
comes first; stricter helper limits take precedence. Count attempts across repair
rounds, not afresh on each wake. After the limit, change the diagnosis and repair a
cause within scope. Do not reset the counter to repeat the same failing operation.
An unresolved external prerequisite stays a named blocker.

The coordinator owns cross-round accounting. Keep per-PR, per-failure `retry_usage`
in coordinator notes in this thread: operation/failure key, attempts used, first
attempt time, and remaining attempts/time. Reconcile coordinator actions and worker
`commands` evidence before every dispatch; recover missing history from prior
results instead of resetting it. Include that current `retry_usage` in each round's
dispatch task text alongside the immutable brief. Never edit a sealed brief or the
job ledger to store counters. Workers consume the supplied remaining allowance and
report their new attempts; they do not persist state between rounds.

## Decide from the brief before asking

Existing authorization and explicit answers persist. Record policy defaults as
derived from the original request, not as a user answer. Before any question,
identify the exact missing fact or authority and why no authorized default resolves
it. If there is none, act and report the choice.

| Situation | Autonomous action |
|---|---|
| Through-merge request without an auto-merge preference | Enable auto-merge when gates permit; honor any explicit override. |
| New eligible PR appears in the requested repo/org | Admit and maintain it under the same request. |
| Target head moves without confirmed competing ownership | Fetch, integrate, revalidate and continue; preserve unrelated work. |
| CI downloads fail repeatedly | Stop identical retries, inspect logs and repair safe in-scope setup; verify the repair. |
| A child returns blocked or a queue stalls | Diagnose available alternatives and keep authorized repair moving; the label or elapsed time does not itself require a question. |
| Transient host failure or ambiguous reply outcome | Read fresh state before a bounded retry to avoid duplicate mutations. |

Ask only for material product choices not settled by the brief, genuinely missing
access/secrets, ownership transfer when required, or actions beyond the authorized
scope. Use the private secret flow for credentials. Preserve package/ledger health
stops, worktree isolation, branch protection, exact-head verification and selected
model/replacement boundaries. Never bypass them to avoid a question. Report an
external outage without asking the user to choose a retry they cannot repair; name
the missing prerequisite and any required human action precisely.
