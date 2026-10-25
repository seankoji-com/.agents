# Babysitter org sweep delivery

Deliver a pull request for deterministic org triage and T3 fixer dispatch. Keep
auto-merge enabled by default for admitted non-draft PRs without a preference
question. The delivery endpoint is an open PR against the refreshed default branch;
merge, release, live paid-agent execution and recurring activation are outside scope.

## Acceptance and verification

- [x] Enumerate accessible repositories and all open non-draft PR pages; report
  unresolved threads, failed checks, conflicts and unknown or incomplete evidence.
  Verify: pagination and classification fixtures in `test_babysitter_org_scan.py`.
- [x] Bound API requests, cost, elapsed time and overlap; keep queued checks separate
  from repair candidates. Verify: budget fixtures and a read-only live scan.
- [x] Use frozen authorization/model choices and native T3 tools for dispatch;
  retain handles and prevent competing or uncertain writers from relaunching.
  Verify: executor/bridge fixtures, installed job gates and native capability probe.
- [x] Preserve existing landing, acceptance, scope and ownership gates.
  Verify: continuous-state, workflow and installed-package tests.
- [ ] Review the exact final commit with the t3-imps reviewer protocol and address
  blocking findings before publishing the PR. Record same-lineage review honestly.
- [ ] Commit explicit paths, push the branch, create and link the PR, and report
  current-head hosted checks separately from local validation.

Local validation from implementation covered all 159 test modules in four shards.
Two modules failed during the changing-tree run; contract and installed-artifact
reruns passed. The final focused run passed 73 tests; docs link/budget checks,
strict MkDocs build and desktop/mobile rendering were checked. A live scan used
eight requests and 44 GraphQL points across 53 accessible repositories; a later
scan retained an unknown mergeability state. These observations do not certify
live fixer execution, host deduplication, a fixer push or scheduled delivery.

PR preparation refreshes the base and binds review to a committed snapshot.
Any review repairs require focused revalidation and a fresh review of changed
content. No existing finding may be silently dropped or downgraded.

PR #148 is draft. Review round 1 at `903140a` returned two major blockers:
`F-REPAIR-BUDGET` (executor bypassed persisted repair exhaustion) and
`F-AUTH-REVOCATION` (lightweight observations erased authorization holds).
Repairs preserve holds under the ledger lock, require its repair decision, and map
job requests to its attempt accounting. Regression checks and a fresh review remain
required before marking the PR ready.
