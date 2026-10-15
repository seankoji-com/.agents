# Document jobs: factual checks and cold reads

Load when `elephant`, `check` or `thinking` delegates a review. Generic protocol:
`PKG/shared/job-coordination.md`; helpers: `job_cli.py`, `job_acceptance_cli.py`;
validator: `PKG/scripts/validate_document.py`.

## Plan

Create one job per review and declare every stage up front. Set
`validator_dependency` to the elephant-goldfish pin.

| Operation | Stages (in order) | Final acceptance |
| --- | --- | --- |
| `check` | `factual` | `validate-final` over `factual` |
| `elephant` | `factual`, then `cold-read` | `validate-final` over both |
| `thinking` (only when a cold read of `handoff.md` is authorised) | `handoff` (direct), then `cold-read` | `validate-final` over both |

Each factual or cold-read stage's `validator_contract` names absolute `root`, `slug`,
`mode`, `document_path` and `document_sha256`. The document sits under `root/slug`.
For `elephant.md`, root is the repository's parent and slug is its directory name.
The handoff stage uses `execution_mode: direct` and `{root, slug, mode: handoff}`;
acceptance uses the same descriptor.

Keep `R-FACT` and `R-COLD` in separate stages. Never let one stage cover both.

## Slots

- **Factual slot.** Use `elephant-goldfish/factual-checker` with
  `coordinator-only` write scope. The brief names the document/hash, revision, claims
  and read-only authority. Its
  contract sets `independent_of_author: true`; the host-observed identity must be
  verified before acceptance.
  `review_verdict` is null, or `adverse` beside any blocker or major finding; such a
  result is ingested and findings retained; the stage stays unaccepted.
- **Cold-read slot.** Worker `elephant-goldfish/cold-reader` with `role: review`,
  `context_policy: document-only`, a document descriptor, the same descriptor in
  `reviewed_documents`, and `coordinator-only` write scope. Review the document, not
  another task; omit `reviewed_task_ids`.
  `prepare` and acceptance re-hash the document; edits make the verdict stale. Its
  contract sets `independent_of_author: true`; unknown author
  or reviewer lineage fails closed. Author records are keyed by document SHA-256 and
  imported only when the current hash matches. A missing record means unknown authorship.
  The helper strips the objective, predecessors, requirements, resources and task
  contract. Do not pass them another way. The dispatch message contains only the brief path, its
  SHA-256 and the instruction to read the brief and named document. Never add planning notes, factual findings, repository answers or earlier cold-read reports. Start every
  cold read in a fresh child; never use a follow-up.

T3 workspace access is not a sandbox. Document-only isolation is an instruction
boundary and a brief filter. Report it that way.

## Author records and identity

New jobs set `policy.identity: observed`. Acceptance requires verified host identity
for required reviewers, their subjects and author-independent slots. Legacy jobs
without the marker keep target-only rules.

Author identity comes from a fresh `orchestrator_capabilities` response passed as
`--capabilities FILE`. Require inherited provider, model and parent thread, with the
model in that provider's catalog. A checker never adds itself as an author. Handoff
authorship includes its renderer and both source hashes; an unrecorded source makes
authorship unknown. These host facts are transcribed by the coordinator; the helper
cannot prove freshness.
After writing discovery or spec, run `thinking_state.py author <slug> <document.md>
--capabilities FILE`. Render with `render_handoff.py <slug> --capabilities FILE`.
Record `elephant.md` with `scripts/record_document_author.py <path> --capabilities
FILE`. Repairs use `job_cli.py document-revision --capabilities FILE`; it updates
affected author-independent slots. `job_cli.py direct-execution` records every start
or resume of a zero-slot factual stage. `check` imports authors only for the checked
hash and never records the checker. It proceeds without provenance and reports
`author unrecorded`.

An owner `lineage-waiver:task:<task-id>` binds the target, authors, full slot contract
and document hash. A zero-slot direct factual stage uses
`lineage-waiver:stage:<stage-id>` bound to its latest executor identity. Waivers skip
no requirement. Changes to target, authors, contract, document or executor need a new
decision.

## Verdicts

The cold reader returns one worker result. Its `conclusion` starts with
`VERDICT: READY` or `VERDICT: NOT READY`. Map READY to `review_verdict: approve` and
`ready-for-acceptance`; map NOT READY to `adverse`, `failed` and failed `R-COLD`. Each gap is a
finding: `blocker` when it stops a newcomer, `minor` otherwise. Any blocker forces NOT
READY. A missing, failed or ambiguous verdict is `unavailable` or a failed result,
never READY.

After you inspect the result, freeze a coordinator observation with `observation` and
accept the stage with `accept-stage`:

- Cold read: `{"kind": "cold-read-observation", "document_path", "document_sha256",
  "verdict": "ready" | "not-ready", "evidence": [...]}`. Each evidence row is
  `{"observer": "coordinator", "kind": "cold-read", "source": <host task ID>,
  "content": {"document_sha256", "verdict"}, "sha256": <SHA-256 of canonical content>}`.
- Factual: `{"kind": "factual-observation", "document_path", "document_sha256",
  "claims": [{"claim_id", "outcome": "confirmed" | "refuted" | "unknown",
  "evidence": [...]}]}` with `kind: factual-claim` rows binding
  `{document_sha256, claim_id, outcome}`.

Open evidence behind consequential findings before recording outcomes. The validator
checks provenance, hashes and coverage, not truth; it rejects `unknown`. Repair refuted
claims and check again before final acceptance.

## Repair rounds

You repair cold-read gaps yourself. Workers never edit the document. A repaired
document has a new hash, so:

1. Record each finding's disposition (`fixed`, `rejected` with evidence, or
   `deferred`). Deferred blockers keep the stage blocked.
2. Run `document-revision` with `{caller, task_id: <cold-read slot>, document: {path,
   sha256}, reason}`. Within the round budget this is a declared repair and needs no
   owner decision. It rebinds every stage contract and slot that names the path to the
   new hash and makes those stages and their successors stale.
3. `retry` the factual slot, run it, and accept the factual stage on the new hash.
   Then `retry` the cold-read slot and dispatch a fresh reader. Each retry charges its
   stage budget. The previous findings stay in job history; the new reader never
   sees them.

A `thinking` job has no factual slot. Repair through discovery or spec, re-render the
handoff with `render_handoff.py` and pass `thinking_state.py gate`. The old `handoff`
receipt no longer matches the new bytes, so run `accept-stage` on the `handoff` stage
again (a charged direct pass). Then run `document-revision` with the new `handoff.md`
hash and `retry` the cold-read slot.

When the budget is spent, `document-revision` refuses with `attempt_budget_exhausted`
and `owner_decision_required`. Another round needs the owner, asked through the
question picker with the recommended option first, recorded with `decision`, and a
`plan-revision` that raises the limit. Do not seek another reviewer to overturn an
adverse verdict.

## Round limits

A cold-read round is one executed cold-read slot. The budget belongs to the topic or
document, not to a session, and resume never resets it.

- **New topics and documents.** Four rounds in total: the initial read plus three
  repairs. This is the default job policy (`max_repair_cycles: 3`).
- **Existing topics with a recorded limit.** Keep the recorded limit and count.
- **Legacy topics with no recorded limit** (a cold-read loop started under the older
  five-round instruction). Record a limit of five and the rounds already performed.
  Create the job with `max_repair_cycles` equal to the remaining rounds minus one,
  and quote the limit source in the job constraints. If no rounds remain, stop. If
  the performed count cannot be established, ask the owner through the picker
  instead of guessing.

For thinking topics the topic is the record. `init` records the four-round default;
`resolve` reports `cold_read` with the remaining rounds. Record a legacy budget with
`thinking_state.py set <slug> cold_read.max_rounds=5 cold_read.rounds_performed=<k>
cold_read.limit_source=legacy-five-round-policy`, and update `rounds_performed` after
each round. `set` refuses a decreasing count, a count above the limit, and a raised
limit unless `limit_source=owner-decision` with a `decision_ref`. For `elephant.md`,
the job is the record; resume that job rather than creating a new one. These fields
record the budget; they never affect readiness and grant no execution authority.

When the budget is spent, report the document as NOT READY with its unresolved gaps.
Raising a limit is an owner decision through the picker, recorded with `decision`.

## Fallback

If T3 cannot run a suitable child, run the factual stage yourself under the same
contract with a visible fallback marker. A cold read cannot fall back to you: you
have seen the planning context. Report it as unreviewed and keep `R-COLD` blocked.

## Report

Report factual verification and cold readability as two separate results with their
receipts. A plausible document is not proof of working software.
