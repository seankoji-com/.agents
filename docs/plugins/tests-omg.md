# tests-omg

Find which checks protect important behavior, which cost too much, and what evidence
would justify keeping, simplifying, replacing or deleting them. The audit writes a
private local HTML report and JSON. It changes no tests, CI or merge protections.

```text
$t3-tests-omg doctor
$t3-tests-omg audit
$t3-tests-omg audit /path/to/repo --run-checks
$t3-tests-omg audit --org OWNER
$t3-tests-omg status omg-RUN
$t3-tests-omg report omg-RUN
```

Install from source with `python3 bin/t3-plugins setup tests-omg`, then restart your
agent session. The slash-menu item `/t3-tests-omg` inserts the same skill mention.
This workflow is experimental and has no live-provider compatibility claim.
Local helpers require Python 3.10+, Git and a POSIX host with `fcntl` file locking.

## What an audit answers

For each coherent check group: what plausible failure would it detect, what would
that failure cost, what independent observation proves the expected result, and
what distinct protection would be lost by deleting it? Being slow, covering the
same lines or never having failed does not establish low value. Rare catastrophic
failures can justify a check. Unsupported conclusions stay `needs_evidence` with a
null action, an owner and a small next experiment.

The report has twelve findings: critical behavior, wallclock, flakiness/retries,
coverage, detection usefulness, learning from bugs, real boundaries, adverse
conditions, reproducibility, cost/maintenance, PR evidence and CI integrity. Each
has `meets`, `gap`, `unknown` or `not_applicable` plus its reason, evidence, owner,
consequence and next action. There is no weighted total or certification.

Profiles compose across web/services, native/mobile/wearables, CLI/TUI/shell,
agent plugins, financial/data workflows, CMS, packaging and infrastructure/recovery.
A financial web app needs both financial and browser evidence; a shell tool does
not need a browser because another repository uses one. Unclassified repositories
remain visible with an owner and classification step.

## Ten minutes means the whole pre-merge path

Setup, dependency installation, builds, execution, retries and required reporting
count toward `T_available <= 600s`. The helper models the actual dependency graph
under explicit numeric runner-pool limits. It keeps observed submission-to-verdict
latency separate from that estimate and shows resource use, phase costs, percentile
rank/sample size and every breach. Missing dependencies or ready/start metadata
make a complete timing claim unknown. More runners cost resources; the audit grants
no purchase or capacity change.

Retained checks are enabled activities in the declared pre-merge assurance set,
even if branch rules fail to enforce them. All must finish before merge, including
required reports. A wrapper exit of zero, retry pass, missing shard, skipped test
or quarantine does not establish readiness. Failed/cancelled/timed-out attempts
remain visible. A valuable 650-second serial check is a budget gap; optimize it
without weakening assertions. Lower-value checks should be removed completely.
The workflow never proposes background, optional, nightly or post-merge slow suites.

## Read-only first, bounded execution by request

`audit` inspects source/configuration and existing evidence. It does not run repo
code, install dependencies, fetch credentials or silently widen scope. It records
inaccessible CI/incident history and unknown measurements. The initial sampling
rules are 30 days of runs, 90 days of severe/repeated incidents and up to ten other
recent fixes. The report states what was actually accessible and inspected.

`--run-checks` lets the coordinating agent perform bounded local verification within
your existing environment and action authority. Commands, prerequisites, finite
limits and cleanup are recorded before execution. Fault experiments use disposable
owned state and named critical/historical cases. No production mutation or
uncontrolled network operation is implied. The helper itself only ingests receipts.

`--org` records paginated visible inventory and a finite repository/time budget,
including archived and unclassified repositories. Default audit limits are 10 repos,
120 seconds and 100 listing pages, separate from the target validation budget.
Credential-visible repositories alone establish a visibility-limited audit. Fleet
coverage requires authoritative expected inventory or scope supplied by the owner.
Missing pages, permission errors and budget exhaustion return partial coverage.
Inventory triage without test-value inspection is explicitly incomplete.

## Reports and deterministic local use

No model is needed to ingest existing evidence and render unknowns. Resolve the
installed entry with `t3-plugins path tests-omg`, then run its sibling helper:

```sh
python3 /installed/tests-omg/scripts/audit.py doctor
python3 /installed/tests-omg/scripts/audit.py audit /path/to/repo --snapshot
python3 /installed/tests-omg/scripts/audit.py --state-root /private/state/tests-omg audit /path/to/repo --input evidence.json --profiles agent-plugins cli-tui-shell
python3 /installed/tests-omg/scripts/audit.py --state-root /private/state/tests-omg report omg-RUN
```

The installed template `templates/evidence.example.json` and
`references/evidence.md` document normalized runner evidence. Bind inputs to the
actual snapshot digest and head SHA. Authored judgments use the existing shared
model-selection admission; substantial review stays in T3's lifecycle, never a
second model client or scheduler. The coordinator chooses and reviews judgments;
helpers calculate and enforce evidence consistency.

State defaults to `$XDG_STATE_HOME/t3-plugins/tests-omg` (or
`~/.local/state/t3-plugins/tests-omg`), outside the target repository. Each private
`runs/ID/` saves input.json, audit.json, report.html and a manifest with content
hashes and generator version. The index records revision/config/history and
predecessor/supersession. Compact sanitized findings stay until owner deletion;
ordinary supporting attachments can expire after 30 days and then become unavailable.
Resume retains source, scope, limits, counters and owned handles. Changed source
requires revalidation in a successor audit.

`status` and `report` verify saved hashes and separately report freshness, expired
references and supersession. Rendering cannot upgrade old evidence.
Status/report exit 1 when diagnostics expired, source is stale/unavailable or the
report was superseded. An interrupted run's original ID follows its single saved
successor; resuming that original checkpoint again is refused.

HTML escapes run-derived text, refuses executable diagnostic URLs and uses a restrictive CSP.
Native interactive reports remain separate untrusted attachments. Sanitize personal
fixture data before ingestion; common credential redaction is defense in depth.

A local report is ready for your review. Authenticated downloadable HTML linked
from a current-head PR summary, external 30-day retention and hosted browsing require
separate authorization and remain unverified until performed. Preserve the original
audience, including repo names, summaries and incident links. The command never
posts private contents to the public methodology issue.

Exit 0 means a valid complete advisory audit, including honest gaps or scoped
unknowns. Exit 1 means incomplete scope or interruption; exit 2 means invalid input
or an unsafe operation. `completion` is separate from repository findings and the
declared validation verdict. No exit code authorizes merge.
