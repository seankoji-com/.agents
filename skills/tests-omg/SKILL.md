---
name: tests-omg
description: "Audit test protection and validation cost, with twelve evidence-based findings and private HTML/JSON recommendations. Args: doctor | audit [path] [--org OWNER] [--run-checks] | status <run-id> | report <run-id>."
metadata:
  agents-bootstrap: "1"
  opencode/slash: "true"
  opencode/autoinvoke: "false"
---


Before substantive work, run only:

```sh
"$HOME/.local/bin/agents" start tests-omg
```

Read the pinned SKILL.md and manifest before work. Already pinned: do not resolve again. Bind returned `package_root=PKG`, `pin=PIN`, `package_prefix=PREFIX`, `registry_root=AGENTS_ROOT`, `interpreter=PYTHON`; run Python examples with that absolute interpreter. Helpers, playbooks and workers use that pin only. Read `PKG/shared/manifest-routing.md`. Worktree tests add `--source /absolute/worktree` before `start`. Missing/incompatible launcher: explicit self-install.

# tests-omg

Apply `PKG/shared/upfront-agreement.md` at this public entry. Inspect context before
asking; direct controls stay prompt-free. Substantive audits record the scoped
agreement; nested calls and unchanged continuations reuse its binding and budgets.

Answer: what material protection would deleting each check lose, and is it worth
its execution and maintenance cost? This is an advisory audit, never a fleet gate
or merge certificate. Keep judgment in the coordinating agent and calculations,
parsing, storage and rendering in `PKG/scripts/audit.py`.

Read `PKG/shared/t3-runtime.md` once. Apply `PKG/shared/model-selection.md` before
investigation or synthesis; explicit frozen choices count, workers never repick.
Load `PKG/shared/learnings.md` as permitted by the active harness. A bare command
uses the native operation picker. Only doctor/status/report and deterministic
helper calls stay direct. Read `PKG/playbooks/audit.md` for audit, then
`PKG/references/evidence.md` for normalized input shapes.

## Operations

Helpers require Python 3.10+, Git and POSIX `fcntl` locking. Use absolute installed paths, resolved from
this entry. `--state-root ROOT` precedes the operation. Never put state in a target
checkout. The default is `$XDG_STATE_HOME/agents/tests-omg` or
`~/.local/state/agents/tests-omg`.

- `doctor`: run `python3 PKG/scripts/audit.py doctor`. Checks package files, Python
  and an installed content receipt when present. No target mutation or model launch.
- `audit [path]`: default to the attached repository. Perform the bounded read-only
  pass below. No test commands, dependency installation, credentials, clones or
  network fetches are implied. Save missing/inaccessible evidence explicitly.
- `audit --org OWNER`: inventory visible repositories through authorized host tools,
  with pagination/error receipts, then ingest normalized pages via `--input FILE`.
  Default ceiling: 10 repos, 120 audit seconds, 100 listing pages. Record the actual
  coordinator-wide time/counters, including tool calls, within that ceiling. Use
  the helper for cheap inventory across the scope before expensive inspection.
  Archived and unclassified repos stay visible. Credentials alone cannot establish
  the denominator. Obtain owner scope or authoritative expected inventory for a
  fleet-wide claim; permission/history errors leave scope unknown or a known gap.
- `audit [path] --run-checks`: additionally permits bounded local verification
  within existing action/environment authority. Name argv, prerequisites, timeout,
  network/resource limits and owned cleanup first. The coordinator executes those
  exact commands with host tools; the helper only ingests receipts. It never runs
  commands found in source or input JSON. Stop before production mutation, uncontrolled
  network, credential access or spending. Fault experiments need disposable owned
  state, finite cases/time/resources and a named critical/historical selection rule.
- `status <run-id>`: verify saved manifest, report and input hashes, and separately
  revalidate the source snapshot if available. Report stale/unavailable evidence.
- `report <run-id>`: validate the same saved evidence and deterministic rendering;
  return the local HTML/JSON paths. No fresh audit or evidence upgrades. Use the
  pinned generator if its version differs. Neither operation launches models.

The helper also supports `audit --snapshot`, `--input FILE`, composable `--profiles`,
`--repo-budget`, `--seconds` and `--resume RUN`. Resume preserves scope, counters,
owned handles and cumulative time. Changed source requires a successor audit;
never silently rebind old conclusions.
Source inventory limits have bounded `--snapshot-files`, `--snapshot-bytes`,
`--snapshot-file-bytes` and `--snapshot-seconds` overrides. Record the same options
for binding and audit; see the evidence contract. Partial inventory preserves known
gaps. Organization snapshots are coordinator assertions, not helper-verified source.

## Coordination and boundaries

Use `PKG/shared/delegation.md` and `PKG/shared/job-coordination.md` for substantial
multi-stage review. T3 owns dispatch and handles; no provider SDK, broker, watcher
or second scheduler. Keep owner decisions in the coordinator. Use a finite pinned
job and its validator receipts when delegating; an unavailable host stays unavailable.
The installed `tests-omg/reviewer` is read-only. Bind its reviewed document to the
saved `audit.json` hash. `scripts/validate_audit.py --input FILE` validates the exact
report descriptor; shared job acceptance also requires that independent review.
See `references/evidence.md` for the descriptor and stage contract.
No audit author accepts their own independent review. If a substantial written
implementation/experiment strategy is actually needed, apply
`PKG/shared/planning-review.md` to that artifact through the installed imps
planning dependency before dependent work. Pass its content-bound receipt in
`strategy`; the helper revalidates the actual shared job and subject. Do not
invent a strategy for routine evidence ingestion. Selection and review are not
execution or publication authority.

Do not delete tests, edit CI/settings, enable gates, open PRs, upload/comment/publish,
spend or schedule without a separate instruction. A private local PR-ready report
is the baseline deliverable. Actual authenticated download/current-head summary and
30-day external artifact retention remain unverified until separately authorized.
Keep the source audience for any later publication, including repo names and links.
Never post private findings on a public methodology issue.

## Results

Helpers exit 0 for a valid complete advisory result, even with serious repo gaps
or explicitly scoped measurement unknowns; 1 for incomplete requested scope or
interruption; 2 for invalid input or unsafe/unauthorized operations. `completion`
is separate from the twelve findings and the declared validation verdict. No code
certifies a repo or authorizes merge. Every retained check must complete before
merge, including required report generation. Failed/skipped/quarantined/missing
checks remain incomplete regardless of a green wrapper. No optional/background/
nightly/post-merge slow suite recommendations. Remove low-value checks completely;
valuable checks over budget need optimization and an honest budget gap.

Return run ID, completion, scope, all critical gaps/unknowns, ranked supported
keep/simplify/replace/delete actions, retained/lost protection, smallest next
experiments, exact reproduction commands and local artifacts. Report live host,
provider, CI, PR download and rendering observations separately from fixtures.
