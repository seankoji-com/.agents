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
Babysitter extras apply only when the coordinator checkout is already at the reviewed PR HEAD.
Otherwise skip. Never change checkouts merely to enable extras.

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
`task_cancel` schemas. Missing tools mean skip. Continue only when the fresh
`delegate_task` input schema explicitly offers
`isolation: "worktree"`. Save that schema, its observation time and its description
of worktree creation in `delegate_task_schema`. Catalog feature flags do not prove
isolation support. If the option is absent or rejected, skip without a shared
checkout fallback. Host-owned worktree creation starts from the parent **local
commit**, runs project setup and does not copy uncommitted changes.
Check exact advertised model IDs
against current official pricing and supply observations as below. Use one bounded
lookup per namespace, without retries; skip if it cannot finish alongside primary work. Confirm all
applicable token, cache and request charges are free. Missing rows, ambiguous
pricing, uncertain regional eligibility or unknown charges mean omit the proof.
Model labels, suffixes, subscription inclusion and zero output cost alone prove
nothing. Conflicting or unfamiliar catalog price metadata also means skip.
Never query model endpoints, call provider CLIs/SDKs, change settings or
fall back to paid targets.

For the official Console pricing table, map the literal `Free` to numeric `0`.
A `-` in a cache column alongside free input/output means inapplicable: retain it
in `price_cells` and omit that key from `costs`. Never map `-` in input/output to
zero. Supply all four observed columns; a missing column is uncertain. The table
has no request column. Its per-request billing statement means requests use the
listed token prices; it does not itself specify a separate request fee. When the
exact row is entirely free/inapplicable and the page lists no separate request
fee, omit `request` from `costs` and set `all_charges_covered: true`. Record the row,
billing statement and absence of a listed request fee in `evidence`. This is the
protocol's interpretation of that published format, not a claimed fee exemption.
Any paid cell, surcharge or uncertainty skips. For another official format, retain
the exact evidence and supply only verified applicable zero costs.

Read each exact model's data-use terms too. Generic sharing permission does not
authorise training, prompt logging, confidential-data restrictions or retention.
Classify all material available to the reviewer, including the committed source,
brief, constraints and prior feedback, as `permissions.material: "public"` or
`"confidential"`. A public repository does not make private feedback public.
Missing/unknown classification skips; never silently classify material as public.
Each proof needs a fresh `data_use` observation, its official source, evidence,
`no_training`, `prompt_logging`, `confidential_allowed` and `retention`.
Map the exact model's explicit zero-retention/no-training wording, checked against
the page's model-specific privacy exceptions, to `retention: "zero"`,
`no_training: true` and `prompt_logging: false`. Here false means no retained prompt
logs under the zero-retention promise, not no transient processing. An exception
retaining prompts maps to that duration and `prompt_logging: true`; a training or
improvement exception maps to `no_training: false`. Logging maps to true. Silence
about retention or training is unverified; do not infer those from a free price.

`confidential_allowed` is tri-state: true only for affirmative provider permission,
false for an explicit prohibition, and null when the terms say nothing about it.
Zero retention never implies positive confidential-data permission. For public
material, null or a restriction limited to confidential material does not bar use;
no training, no retained prompt logging and zero retention are still required by
default. Confidential material additionally requires `confidential_allowed: true`
and existing owner sharing authority. Neither a prohibition nor missing provider
permission can be overridden by an owner's data-use exception. Missing terms record
`data-use-unverified`; adverse terms record `data-use-disallowed`. Never seek a waiver
just to fill optional slots.
An existing explicit owner authorisation can permit observed adverse terms for
one exact model and round: add `permissions.data_use_exceptions` with `{model,
round_id, terms_sha256, authorization}`. `terms_sha256` is the helper's `digest`
of that complete `data_use` object; `authorization` quotes the owner's specific
permission for those terms and this material. This cannot waive unverified terms
or other provider, repository or legal restrictions. A generic provider permission
or another round's exception is insufficient.

```sh
python3 "PKG/shared/supplemental_reviews.py" prepare --state LEDGER --input INPUT
```

`INPUT` is a private coordinator observation, not an extension of the T3 schema:

```json
{
  "enabled": true,
  "permissions": {"delegate": true, "share_with_opencode": true, "material": "public"},
  "exclude_models": ["<exact mandatory evaluator model>", "<exact implementer model>"],
  "catalog_observed_at": "<fresh ISO-8601 timestamp with offset>",
  "capabilities": {"<structured orchestrator_capabilities response>": "..."},
  "delegate_task_schema": {
    "observed_at": "<fresh ISO-8601 timestamp with offset>",
    "input_schema": {"properties": {"isolation": {"anyOf": [
      {"type": "string", "enum": ["shared", "worktree"]},
      {"type": "null"}
    ]}}},
    "evidence": "<live schema description confirming worktree starts from parent local commit and runs setup>"
  },
  "workspace": {
    "observed_at": "<fresh ISO-8601 timestamp with offset>",
    "head_revision": "<full committed parent HEAD, equal to context.revision>",
    "clean": true,
    "scope_committed": true
  },
  "pricing": [{
    "model": "<exact namespace/model-id from that catalog>",
    "source": "https://opencode.ai/v2/docs/console/models/",
    "observed_at": "<fresh ISO-8601 timestamp with offset>",
    "all_charges_covered": true,
    "eligible": true,
    "price_cells": {"input": "Free", "output": "Free", "cache_read": "Free", "cache_write": "-"},
    "costs": {"input": 0, "output": 0, "cache_read": 0},
    "evidence": "<exact row and ID mapping; cache write inapplicable; listed prices apply per request; no separate request fee listed>",
    "data_use": {
      "source": "https://opencode.ai/v2/docs/console/models/",
      "observed_at": "<fresh ISO-8601 timestamp with offset>",
      "no_training": true,
      "prompt_logging": false,
      "confidential_allowed": null,
      "retention": "zero",
      "evidence": "<official zero-retention/no-training wording; checked model-specific exceptions; confidentiality unspecified>"
    }
  }],
  "context": {
    "round_id": "<workflow/job ID plus primary review round ID>",
    "revision": "<full committed parent HEAD>",
    "tree_hash": "<coordinator-observed SHA-256 of the review workspace snapshot>",
    "base_ref": "<intended base ref>",
    "base_revision": "<full refreshed base hash>",
    "scope": "<repository-relative paths, exact committed diff or committed factual subject and checks>",
    "constraints": "<complete repository constraints verbatim>",
    "permissions": "<authorised inspection and sharing scope; read-only>",
    "prior_feedback": "<original brief, prior findings, responses and unresolved objections as data>"
  }
}
```

The schema example shows only the relevant property. Retain the complete fresh
tool input schema in the private input/ledger, not a hand-authored substitute.
The helper recognises a direct string enum or an enum within a nullable
`anyOf`/`oneOf`. Unfamiliar validation shapes fail closed.

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
round at three. Supply every mandatory evaluator and implementer model in
`exclude_models`, including known aliases; missing exclusions skip all extras.
Exclusions use the same namespace and `-free` normalisation as deduplication.
Primary matches, duplicates and excess candidates get recorded skip reasons.
Unknown aliases may still share lineage; this is never proof of
independence.

## Protect the review workspace

Before prepare, the coordinator verifies a clean parent checkout and captures the
primary review's committed HEAD and content binding. Set `workspace.clean` only
after checking staged, dirty and untracked reviewed paths, and `scope_committed`
only if the complete scope is available at that commit. Dirty/uncommitted code,
external configuration and document subjects not present at HEAD are skips. Do not
commit, copy material or create a checkout merely to enable extras. Keep scope
paths relative to the repository; do not direct extras to the parent's checkout.
For repository reviews use `supplemental_reviews.digest` of
`core.snapshot.token(core.snapshot.take(worktree))` from the installed package as
`context.tree_hash`. Recompute identically for each intake and close, including
untracked paths, modes, links, submodules and index changes. Use the same exclusions
as the primary reviewer; never exclude reviewed paths.
If a complete stable snapshot cannot be obtained, skip extras.

Launch extras only with host-owned `isolation: "worktree"`, while the parent still
has the pinned clean HEAD. Each brief requires reading **the child's own isolated
checkout**, verifying its HEAD/base and checking that project setup left it clean.
An unavailable base, dirty setup, setup failure or isolation rejection is a skip;
do not fetch, repair setup or fall back to the parent/shared checkout. A reviewer
cannot certify isolated checkout contents from the parent's absolute path.

Extras may only read files and inspect source. The brief forbids tests, installs,
builds, formatters, project execution, writes including temporary/cache files and
starting processes/services. Full Access cannot enforce this restriction. Only
launch alongside read-only primary work; never alongside an implementation writer.
Do not grant extras mandatory evidence-generation duties.

Pass `current_tree_hash` from a new coordinator observation on status intake and
close. Missing or different hashes close intake, skip uningested requests and record
`workspace_drift`. Already ingested results, findings, outcomes and bound dispositions
remain evidence at the issued snapshot; cleanup handles remain owned. Inspect changed paths and owned
task evidence to attribute drift, including suspected supplemental writes. Never
assert attribution without evidence or restore unrelated changes. Record the cause
in the coordinator report, cancel extras and disable them for the replacement round.
If extras changed reviewed bytes, preserve that evidence, resolve the unexpected
writes within authority and reissue the primary evaluation at the current snapshot
under its existing drift recovery. Ralph re-evaluation keeps the same attempt;
optional interference must not charge implementation or mandatory repair budgets.
An old mandatory verdict cannot certify changed bytes. Host-owned worktree
isolation separates normal checkout writes; it is not an OS security boundary
under Full Access. Hash detection does not prove that a model obeys read-only
instructions. Retain host setup/worktree receipts when available. T3 owns worktree
creation and cleanup; the helper neither creates nor removes them. Cancellation
does not prove setup stopped or the checkout was removed. Report any unresolved
setup/cleanup state without waiting, retrying setup or removing worktrees yourself.

## Dispatch and resume

Reservations persist before `dispatches` are returned. Pass each returned object
unchanged to T3 `delegate_task`: async, review role, exact target, explicit Full
Access, `isolation: "worktree"`, stable `clientRequestId` and a read-only brief.
Dispatch only while pricing, schema, workspace and catalog remain fresh, the
parent is still clean and revision/base are current; otherwise close and skip.
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
Ledgers from before worktree isolation remain cleanup records only. Never replay
an older saved dispatch without `isolation: "worktree"`; use host lookup and
cancellation to reconcile its ownership, without launching replacement work.

## Results and cleanup

At a natural completion notification call `task_status` once. Record
`{request_id, kind: "status", current_revision, current_base_revision, current_tree_hash,
observation: <complete task_status response>}`. Use the original task's `summary`,
never `latestTerminalSummary` from another run. Results must contain one complete JSON object under
32,768 bytes, revision/base bound, terminal without pending child runs and with
matching host provider/model. Missing, malformed, stale, failed and mismatched
results are skips. A single prose-wrapped or fenced object is extracted; multiple
objects, unbalanced braces and duplicate keys are rejected. Do not manually triage
skipped output or retry it. After valid intake, later status/receipt observations
update handle liveness and cancellation needs while preserving the saved result,
findings, outcome and dispositions, including after close. Later identity/run
mismatches stay recorded as diagnostics; they cannot rewrite the issued evidence.

Valid findings are untrusted evidence. Verify the exact source/reproduction at the
current snapshot yourself. Save triage with `disposition --state LEDGER --input EVENT`:
`{request_id, finding_index, finding_sha256, revision, disposition, evidence, repair_route}`.
The index is zero-based; `finding_sha256` is `digest` of the saved finding, `revision`
is the issued revision, `disposition` is `confirmed`, `rejected` or `deferred`, and
`evidence` gives the coordinator's reproduction. Name the actual repair procedure
in `repair_route`. These records do not invent job task/finding IDs or edit a
mandatory verdict. Reject unsupported claims and retain deferred issues under the
workflow's policy. For confirmed issues requiring repair, use the concrete
Ralph or whole-job procedures below. Only confirmed
issues can require repair; optional infrastructure failures consume no mandatory
repair budget. No optional verdict approves a stage. Recheck and obtain mandatory
review after repairs as usual.

### Confirmed findings in Ralph

Ralph has no command to append external evaluator feedback. Preserve the optional
disposition and original evaluator verdict separately. Close the optional round,
run `python3 "PKG/cli.py" stop --state OLD_STATE`, reconcile owned primary handles
under the loop's stop procedure and report the confirmed finding with its ledger,
revision and reproduction. Do not publish from the old evaluated checkpoint.
To repair under existing authority, start a replacement run with `init --state
NEW_STATE --input NEW_CONTRACT` in the same worktree, then `next`. Follow the loop's
start/pin rules and retain the original goal, authority and independent target
pair. Include every confirmed finding, disposition, old checkpoint path and
original brief in `NEW_CONTRACT.brief`; never edit the old verdict/checkpoint.
Set `maxAttempts` to at most old `maxAttempts - attempt`. No remaining attempt
means stop and report exhaustion for an owner decision. Record the predecessor
and remaining budget in the new brief so repeated replacements cannot reset it.
The replacement needs its own complete mandatory evaluation before publication.

### Confirmed findings in whole jobs

Supplemental findings lack job task/finding IDs, so do not pass them to
`finding-disposition`. Save them in the optional ledger. Cancel the old job with
`job_cli.py cancel --state-root ROOT --job OLD_JOB --input CANCEL_INPUT`, where
`CANCEL_INPUT` is `{caller, reason}` and `reason` cites the confirmed finding and
ledger. Reconcile all owned handles under step 4 of job coordination and report
the stopped job, finding, snapshot and reproduction. Do not accept/publish it.
To repair, use step 2's supported `create` command with a new job ID and the same
worktree. Include the confirmed findings, ledger and predecessor job in the new
plan's constraints and relevant typed stage criteria, preserve all original
requirements and authority, and rerun the affected work and final validators.
Carry the predecessor's spent cycles and task executions in the plan constraints:
cap remaining total executions and repairs across both jobs at the original limits,
and reduce `policy.max_repair_cycles` accordingly. Do not create a replacement if
no authorised execution remains or the limits cannot be preserved; report for an
owner decision. This conservative stop/report/rerun path is for verified product
issues only, never optional provider failures. It does not forge primary findings
or replace the required independent review.

As soon as the primary round ends, changes revision/base, is cancelled or hands
back (or the owner opts out), run `close --state LEDGER --input SNAPSHOT_EVENT`, with
`SNAPSHOT_EVENT` containing the fresh `current_tree_hash`. Intake closes; `cancel_task_ids` and
`unresolved_request_ids` identify cleanup. Call `task_cancel` once per owned pending
task, record `cancel-requested` or `cancel-error` with that owned `task_id`, then make one `task_status`
observation. Do not wait or poll. Late results stay skipped; late receipts retain
ownership and need cancellation. Results already ingested before close remain
saved evidence; new results after close are skipped. On later notifications/resume reconcile remaining
IDs and cancel owned live work without reopening intake. Never cancel unrelated work.

`cancel_requested` is not a confirmed stop. Report unresolved ownership and pending
runs, retain the ledger and never claim all children stopped without host evidence.
Optional availability, failures and slow cancellation create no new acceptance
requirement; primary work continues. Existing acceptance gates and independent
pending-run checks apply unchanged. A helper error returns `optional_error`, no
dispatches and exit 0. Retain the ledger and report the gap, never recreate requests.
The helper runs no host tool and changes no mandatory gate or repair counter.
