# Scoped upfront agreement

Apply this at every public entry. `operation-matrix.json` lists every manifest
operation, its classification, public route and completion evidence. Run
`python3 PKG/shared/execution_agreement_cli.py inventory --input FILE` with
`{"root":"<source checkout>"}` to detect uncovered operations, or `{}` in a bundle.
Direct doctor/status/list/cancel and raw deterministic helpers do not interview or
dispatch. Before a direct helper transitions into authored work, use admission.
The single public `agent-tuneup/tuneup` workflow retains admitted audit/align/apply
helper compatibility. These internal names do not add public command choices.

## Inspect, then settle missing decisions

Read the request, repository instructions, existing authority and relevant state.
Resolve the intended base, checks and unambiguous destinations there. State routine
reversible assumptions and proceed without acknowledgement. Supplied choices are
answers. Ask only consequential unresolved questions in short rounds through the
native picker, recommendations first. Ask one decision per question and wait for
the answer before the next round. Retain supplied answers and ask only for still-missing
choices or options. Show a short relevant model list; keep lineage, sharing and
runtime mechanics out of the model picker. Raise a concrete conflict separately
only when it needs a decision. Silence cannot grant authority. Genuine discovery acceptance
and required host/organisation approvals remain gates.

The JSON `inspect` action accepts `operation`, source references in `inspected`
(`request`, `instructions`, `authority`, `state`), `context`, `supplied`, consequential
`required` field names, `recommendations` and routine `assumptions`. It combines
facts and returns only missing questions as data. Present those questions in short
rounds, one decision at a time. It performs no investigation.

Show one concise agreement: observable target; repository/base and bounded paths;
destinations and documented procedures; exact work/review roles, options and finite
ordered replacement chains; sharing and action authority sources; checks, external
approvals and finite repair/launch/cost limits. Recommend suitable preferred models
from the complete live catalog, searching custom names when necessary. The
`selection recommend` action resolves supplied preference labels against live
identities and sourced suitability profiles, returning missing/ambiguous names and
role gaps. Neither names nor price prove quality. Never change coordinator settings.

Freeze the agreement with `freeze` input `{data, selection}` before freezing the
model selection. `data` has `invocation_id`, `scope_id`, `operations`, `inspected`,
`scope:{repository,base,paths}`, `target:{label}`, `destinations`,
`verification:{local_checks,ci_checks,review_required}`,
`limits:{max_repair_cycles,max_launch_retries,max_cost}`, `authority` grants with
`actions` and actual quoted `source`, `external_gates`, and
`model_contract_sha256` from the displayed chains/options/sharing. Sources use the
existing model-selection answer/reference/hash contract. Put the result in the
selection's `agreement`. Admission verifies it before dependent work; immutable
briefs retain the agreement and selection digests. A hash is a binding, not proof
that an owner answered or that a remote observation is true.

`admit` checks `{selection, operation?, action?, expected?, boundary?, external?}`.
Missing action authority or a changed material boundary holds only that dependent
action. Continue independent authorised work. `inherit` checks a nested operation
against the same agreement; it grants no new operations or recipients. Name nested
adopters in the original operation scope. Do not restart their interview.

## Continue and replace within the contract

Persist the selection in the existing job, topic, study, report or Ralph checkpoint.
Routine repair, authorised CI repair, notifications, compaction, unchanged resume
and nested calls reuse it without chooser or retain-or-stop. Preserve all findings,
accepted evidence, producing bindings, author histories, handles and remaining
budgets. New destination/cost/provider/action boundaries need a scoped decision;
do not erase completed work. Cancellation stops only owned work. Exhaustion and
missing external approval are named blockers, never reasons to reset counters.

Work and reviewer replacements are separate finite approved lists. Before a
replacement, retain the original request/host IDs and reconcile every earlier
candidate to terminal/no-pending or an authoritative absence observation.
`unavailable.reconciled` carries those owned request IDs, exact targets, status,
reason and original evidence reference. A healthy completed/adverse review cannot
be an outage. Retain objections and repair them. Compare observed identity and exact
options with dispatch; unreported options hold acceptance. Recompute review
eligibility against coordinator, synthesis and every actual replacement author.
An unlaunched reviewer invalidated by new authors may use an approved independent
backup with `cause:author-independence` evidence. Launched reviewers first reconcile.
Unknown lineage and self-review cannot satisfy an independent slot.

For an original launch that the host proves absent, jobs record a `reconciled`
observation with `status:absent`, original `request_id`, exact `target`,
`has_pending_child_runs:false` and an original `reference`. Ralph uses `absent`
with `status:absent`, `clientRequestId`, dispatch `target`,
`hasPendingChildRuns:false` and `reference`. This retains the absent request;
ordinary retry/replacement still charges the existing budget. Missing responses
alone never establish absence. Mismatched receipts retain their owned handles.

## Engineering completion

New imps/Ralph work offers exactly **Open PR**, **Tagged Version**, **Verified in
Prod**, unless supplied. A no-change outcome is reported honestly; resolve an
incompatible endpoint before dependent execution rather than creating an empty PR.

| Target | Required observed evidence |
| --- | --- |
| Open PR | Clean current head; named local checks and independent review; real open intended-base/head PR linked to the T3 thread; named current-head required CI passed |
| Tagged Version | Repository procedure and required merge/review/CI; intended remote version tag; actual `release.publication` identity/status/revision/version/URL/reference; every required artifact/distribution observed |
| Verified in Prod | Release evidence plus actual named destination/deployment identity at agreed revision/version; required backup/migration/rollback preparation; named live health/user-flow observations for that deployment |

Queued workflows, a local tag, an image alone, stale review, wrong-head CI and a
healthy older runtime fail. The target repository owns concrete release/deploy
procedures. Use native PR notifications/watches for authorised repair and waiting.
No scheduler or model client is added here. Submit observations through imps
`delivery` or Ralph `complete`; source readiness is separate from endpoint completion.
Whole-job terminal adapters also bind the declared `repo.worktree` and `repo.base_sha`
to the reviewed job and require a clean, nonempty change from that base.

## Thinking delivery

Substantive elephant-goldfish work selects **Issue with subissues**, **Discussion
post**, or **Markdown PR**. Read-only checks retain their constraints and acquire
no publication authority. Discovery/spec review and deterministic handoff provenance
remain required. Local files are recoverable intermediate work. Publishing a brief
never authorises implementing its proposal.

`thinking_state.py delivery SLUG start|observe|status|complete --input FILE` retains
the complete accepted handoff hash, selected target and partial remote identities.
`start` takes `subissues:[{key,content_sha256,depends_on,acceptance}]` for issue delivery.
`observe` takes `{key,request_id}` before create, then `{key,observation}` with the
actual original `request_id` and evidence `reference`. An uncertain request returns
`reconcile`; an existing ID returns `inspect-existing`. Never retry create with a
new identity until the original outcome is known. Repeated `start` cannot erase IDs.
Supply applicable external approvals in `observe`'s `external` list; the ledger
retains their IDs, approved status and original references for completion checks.
Elephant designs use `scripts/delivery.py` with a reviewed `--descriptor` and private
`--state` instead. These helpers never publish or call GitHub.

Issue completion requires real parent/child URLs, complete content hashes, native
parent/subissue relationships, dependencies and actionable acceptance criteria.
Discussion completion requires an actual published ID/URL in the intended existing
category with the complete accepted content. Markdown completion requires only the
approved durable Markdown/provenance paths in a linked intended-base/current-head
reviewed/green PR. Checklists, drafts and wrong-head PRs fail. Use
`thinking_state.py gate SLUG --require discovery,spec,handoff,delivery` for the full
endpoint; an artifact gate alone proves source readiness only.

## Legacy and evidence

Older immutable packages/jobs retain their original contract, authority, counters
and evidence. Continue them with their pinned package. Current source permits status,
owned cancellation and reconciliation; it does not retrofit a new agreement onto
old authored work. New endpoint/fallback authority requires a separately admitted
restart after owned work is quiescent. Keep old state/URLs/findings and carry remaining
limits into the new brief. A prospective model change cannot rewrite old producing
receipts. Incompatible state reports a blocker rather than silently migrating.

Offline public/installed fixtures use fake host and GitHub observations. They do
not certify real picker behavior, provider fallback, remote delivery or host support.
Record each authorised live scenario separately; unperformed scenarios stay unverified.
