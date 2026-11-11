# careynas.net profile

Apply this after the generic workflow. Verify every dated fact against the live
repository before relying on it.

## Labels and triage

Every issue needs one `type:*` label. `priority:P0`–`P3` is required on
`type:incident`, `type:bug` and `type:security`; `severity:SEV1`–`SEV3` describes
impact, not scheduling. `complexity:trivial|low|medium|hard` drives model
routing. See `runbooks/issue-routing.md`.

The org Project board is the stated source of truth for columns, but the available
GitHub credential may lack `read:project`. When that happens, use issue state,
labels, assignees and open PRs, and report the board as unread rather than
guessing a column.

## Protected issues

Never auto-fold or close without explicit owner confirmation: anything labelled
`type:security`, `area:hardware`, `area:resilience`, `priority:P0` or
`priority:P1`, or carrying `wontfix`. The `blocked` and `blocked-external` labels
exist but do not close an issue; they are status, not a terminal state. Duplicate folding fails closed on any
of these. A source-only merge does not close a live incident.

## Review and merge gates

- The required context is `gatekeeper / all-checks-passed`. Squash only; linear
  history; every review thread resolved; no direct pushes to `main`.
- When the implementation model is DeepSeek, the Grumpy Engineer bot is the same
  family and is not the independent review. It is not the review gate. Choose the
  reviewer under `review`'s eligibility rules; do not pin a model. Opus 5.5
  (`claudeAgent`, effort medium) is the working choice only when the user names
  it or it is the first eligible option, and a stronger model is appropriate for
  `complexity:hard`. Never choose a reviewer that shares the coordinator's or a
  material author's lineage.
- If the required gatekeeper context is missing or stuck `in_progress`, run the
  supported recovery:
  `gh workflow run call-reusable-pr-gatekeeper.yml --repo seankoji-com/careynas.net --ref main -f head_sha=<sha>`.
- If the gate reports “waiting for review dispatch” and no reconcile sweep is
  queued, run
  `gh workflow run persona-review-reconcile.yml --repo seankoji-com/.github-private --ref main -f retry_failed=false`.
  Distinguish no recent trigger from a queued or failed sweep.
- A push dismisses stale approvals. Re-review the new head; never treat an
  approval of an older head as current.

## Runner contention

The ClickHouse integration job has a 10-minute cap and runs on the shared
self-hosted pool. Recent successful runs took roughly 5–10.5 minutes. Serialise
PRs that touch `tests/test_nas_llm_usage_chain.py`,
`tests/test_llm_usage_clickhouse.py` or
`.github/workflows/validate-llm-usage-clickhouse.yml`. A job cancelled near the
cap is capacity contention: rerun it, do not change code. The `setpriv`/dialler
tests are environment-sensitive and may fail once on a runner; rerun and report a
recurrence instead of expanding the PR.

## Editing and hooks

The OpenCode formatter rewrites `.sh` and Python files on tool writes. For shell
files, edit from the shell (heredoc, `python3`, `sed`) and diff every change; the
formatter can rewrite unquoted associative-array keys. Prefer shell-side edits
for small repairs so the PR diff stays scoped. A stale
`/home/seankoji/repos/careynas.net/.git/config.lock` can block branch-config
writes; use an explicit `HEAD:refs/heads/...` refspec and verify the remote SHA.

## Live changes

- NAS stack deploys run through `.github/workflows/portainer-redeploy.yml` on
  push to `main`, or its `workflow_dispatch`. Do not use Portainer
  Pull-and-redeploy. The push path is not universal: `nas-deploy-controller`,
  `nas-public-mcp`, `nas-ai`, `nas-hermes`, `pc-*` and `carey-mac-development`
  are excluded, and of `stacks/configs/**` only `pi-alloy` and `pi-mail` are
  mapped. Other config directories warn "not deployed". A merge that does
  auto-deploy is covered by standing merge; name the affected stacks and the
  revert path. Excluded targets do not share one fallback; use the target's
  documented path and ask before a manual action: `nas-ai` is a
  maintenance-window stack redeploy; `nas-public-mcp` uses its named manual
  dispatch after the image digest and secret are ready; `nas-hermes` is retired
  and must not be redeployed; `pc-*` use Portainer or the Mint management-machine
  path the deploy script requires; `nas-deploy-controller` is refused by the
  deploy script; and `carey-mac-development` uses its own runner path. Unmapped
  configs are not deployed by this workflow: `cliproxy` is synced by
  `sync-monitoring-configs.yml`, `public-mcp` and `pi-onebitemore` have named
  procedures (copy the file to the Pi first for `pi-onebitemore`), and other
  directories need the service page. A blanket `workflow_dispatch` is not a valid
  fallback; report "merged, not deployed" and ask. Other push-triggered
  workflows (n8n, image builds) may also run; identify them from the changed
  paths before merging.
- Pi stacks use a Portainer content `PUT`; the records are not git-backed.
- Mint application stacks use the endpoint named `Mint Server` with a content
  `PUT`; runner recovery has its own runbook.
- Secrets live under `/volume1/docker/secrets/<stack>.env` and appear as
  `/secrets/<stack>.env` in containers. Never copy them into an issue, PR or
  ledger.
- Read `known-live-issues.md` before changing or accepting the health of an
  affected host or service. Do not close monitoring, backup, auth or certificate
  findings on a source change or old pass.

## Delivery conventions

Ground Rule 5 in `AGENTS.md` still applies: propose wiki page updates explicitly
and do not silently edit pages. Confirmation means the owner personally wrote the
request, not merely an issue filed under the owner's account; otherwise ask. Bots and alerting can file new
issues during a run, so a zero target moves. Report the count at a stated time and
list issues opened during the run. Add `changelog.d/YYYY-MM-DD-<slug>.md`, never
edit `changelog.md`. Keep branches rebased on `origin/main`; never add a merge
commit. Duplicate folding shares the org-wide ten-per-day maintenance budget in
`runbooks/issue-routing.md`; treat it as a ceiling unless the owner confirms it
applies only to Hermes. Verify the current runbook's scope before applying it to
autonomous triage closures, completed or not-planned; pending clarification, count
them against the same ceiling.
When the budget is exhausted, record pending closures and the next budget trigger,
or ask about its scope. This is unfinished work, not an owner hold or a closure.
File confirmed delivery-review bugs
with `raise-issue` and the repository's labels before declaring the parent
complete. Report local checks, hosted CI, merge, deployment and live acceptance
separately.
