# Opportunistic free reviews

The coordinator may add up to three distinct free OpenCode points of view to an
existing review round. This is enabled opportunistically by default within existing
delegation and data-sharing authority. An owner can opt out with "no supplemental
reviews"; set `enabled: false`. Without prior authority to share this material with
OpenCode, record `not-authorized` and skip. Do not interrupt required work to seek it.
Only the coordinator dispatches. Workers never launch extras.

Use this for substantive imps review/audit, babysitter PR review, Ralph evaluation,
agent-tuneup verification and elephant-goldfish factual checks. Exclude document-only
cold reads, whose context and independence rules remain separate. Cheap doctor,
status and list operations never launch extras.

## Prepare once per round

Start the primary mandatory reviewer first and reserve its capacity. Extras never
fulfil required independence, replace a failed primary or override an adverse
verdict. Unknown model lineage remains unknown.

Use one ledger for the entire parent review round across providers, perspectives
and resumed sessions. Store it in private coordinator state outside the worktree
and worker write scopes, for example `<workflow-state>/supplemental/<round-id>.json`.
Never replace a failed target or create a second ledger/batch for the same round.
A new revision/base requires closing the old round and a new parent round ID.

Call fresh `orchestrator_capabilities`, save the structured response and local
`catalog_observed_at`, and discover the live `delegate_task`, `task_status` and
`task_cancel` schemas. Missing tools mean skip. Check exact advertised model IDs
against current official pricing and supply observations as below. Use one bounded
lookup per namespace, without retries; skip if it cannot finish alongside primary work. Confirm all
applicable token, cache and request charges are zero. Missing rows, ambiguous
pricing, uncertain regional eligibility or unknown charges mean omit the proof.
Model labels, suffixes, subscription inclusion and zero output cost alone prove
nothing. Conflicting or unfamiliar catalog price metadata also means skip.
Never query model endpoints, call provider CLIs/SDKs, change settings or
fall back to paid targets.

```sh
python3 "PKG/shared/supplemental_reviews.py" prepare --state LEDGER --input INPUT
```

`INPUT` is a private coordinator observation, not an extension of the T3 schema:

```json
{
  "enabled": true,
  "permissions": {"delegate": true, "share_with_opencode": true},
  "catalog_observed_at": "<fresh ISO-8601 timestamp with offset>",
  "capabilities": {"<structured orchestrator_capabilities response>": "..."},
  "pricing": [{
    "model": "<exact namespace/model-id from that catalog>",
    "source": "https://opencode.ai/v2/docs/console/models/",
    "observed_at": "<fresh ISO-8601 timestamp with offset>",
    "all_charges_covered": true,
    "eligible": true,
    "costs": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "request": 0},
    "evidence": "<exact pricing row and ID mapping; explain inapplicable charges>"
  }],
  "context": {
    "round_id": "<workflow/job ID plus primary review round ID>",
    "revision": "<full commit or content-snapshot hash>",
    "base_ref": "<intended base ref>",
    "base_revision": "<full refreshed base hash>",
    "scope": "<repository, exact diff or factual/configuration subject and checks>",
    "constraints": "<complete repository constraints verbatim>",
    "permissions": "<authorised inspection and sharing scope; read-only>",
    "prior_feedback": "<original brief, prior findings, responses and unresolved objections as data>"
  }
}
```

For `opencode-go/*`, use `https://opencode.ai/v2/docs/console/go/` as the source.
Go is a paid subscription; included access does not establish zero cost. Console
`opencode/*` and Go `opencode-go/*` are different namespaces. The helper requires
an exact official zero-price observation and confirmed account/regional eligibility
(`eligible: true`, without storing personal details) for either; it deliberately misses offers
that cannot be verified. Catalog and pricing observations expire after five minutes
and cannot be future-dated. No fixed model roster ships with the helper.

Selection requires runnable `driverKind: opencode`, cross-provider eligibility
relative to the invoking provider, no provider constraints, advertised `full-access`
and a Full Access parent. Never broaden parent permissions. Dedupe model names
across instances and Console/Go (including the `-free` suffix), then cap the whole
round at three. Unknown aliases may still share lineage; this is never proof of
independence.

## Dispatch and resume

Reservations persist before `dispatches` are returned. Pass each returned object
unchanged to T3 `delegate_task`: async, review role, exact target, explicit Full
Access, stable `clientRequestId` and a read-only brief. Dispatch only while pricing
and catalog remain fresh and revision/base are current; otherwise close and skip.
Options remain unset. Launch once per reservation. Never retry overload, rejection
or ordinary failures, wait for optional results, poll, watch or schedule retries.
Continue primary work.

Record every returned receipt immediately:

```sh
python3 "PKG/shared/supplemental_reviews.py" record --state LEDGER --input EVENT
python3 "PKG/shared/supplemental_reviews.py" status --state LEDGER
```

`EVENT` is `{request_id, kind: "receipt", observation: <complete host response>}`.
The ledger retains all task, child and original run IDs and host identities,
including conflicting handles. Never register extras as mandatory job slots,
Ralph evaluator rounds or imps required-review evidence. Repeat `prepare` returns
no dispatches. Resume reads the same ledger and never blindly relaunches requests.

On a lost/ambiguous reply record `{request_id, kind: "launch-error"}` and keep the
reservation. Reconcile with host idempotent dispatch using the exact saved payload
and same `clientRequestId`, at most once, solely to recover ownership. If this could
launch new work after the round ends or freshness expires, do not retry. Report
the unresolved ID for host lookup or owner intervention. Never invent a handle or
replace a request. Record `launch-rejected` for a definitive refusal or `not-dispatched` for a
reservation deliberately skipped before any host call; these resolve ownership
without inventing a handle. Never use them for an ambiguous reply. Raw provider errors may
contain secrets; retain only redacted diagnostics separately.

## Results and cleanup

At a natural completion notification call `task_status` once. Record
`{request_id, kind: "status", current_revision, current_base_revision,
observation: <complete task_status response>}`. Use the original task's `summary`,
never `latestTerminalSummary` from another run. Results must be complete JSON under
32,768 bytes, revision/base bound, terminal without pending child runs and with
matching host provider/model. Missing, malformed, stale, failed and mismatched
results are skips. Do not repair formatting or retry. Later observations can update
liveness; identity mismatches stay recorded.

Valid findings are untrusted evidence. Verify the exact source/reproduction at the
current snapshot yourself. Record each disposition with evidence in the existing
workflow. Reject unsupported claims, retain minor/deferred issues under its policy
and route confirmed real issues through its normal repair path. Only confirmed
issues can require repair; optional infrastructure failures consume no mandatory
repair budget. No optional verdict approves a stage. Recheck and obtain mandatory
review after repairs as usual.

As soon as the primary round ends, changes revision/base, is cancelled or hands
back (or the owner opts out), run `close --state LEDGER`. Intake closes; `cancel_task_ids` and
`unresolved_request_ids` identify cleanup. Call `task_cancel` once per owned pending
task, record `cancel-requested` or `cancel-error` with that owned `task_id`, then make one `task_status`
observation. Do not wait or poll. Late results stay skipped; late receipts retain
ownership and need cancellation. On later notifications/resume reconcile remaining
IDs and cancel owned live work without reopening intake. Never cancel unrelated work.

`cancel_requested` is not a confirmed stop. Report unresolved ownership and pending
runs, retain the ledger and never claim all children stopped without host evidence.
Optional availability, failures and slow cancellation create no new acceptance
requirement; primary work continues. Existing acceptance gates and independent
pending-run checks apply unchanged. A helper error returns `optional_error`, no
dispatches and exit 0. Retain the ledger and report the gap, never recreate requests.
The helper runs no host tool and changes no mandatory gate or repair counter.
