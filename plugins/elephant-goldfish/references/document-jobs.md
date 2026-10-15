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
  contract sets `independent_of_author: true`; if author or reviewer lineage is
  unknown, the job stops because it cannot check independence. Author records use the document SHA-256 and
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
After writing discovery or spec, use `thinking_state.py author` with fresh capabilities.
Render with `render_handoff.py --capabilities FILE`. Record `elephant.md` with
`record_document_author.py <path> --capabilities FILE`. Repairs use
`job_cli.py document-revision --capabilities FILE`. `direct-execution` records each
zero-slot factual start or resume. `check` imports matching authors, never the checker,
and reports `author unrecorded` when provenance is missing.

`elephant-goldfish/thinking` and `elephant-goldfish/elephant` enable
`policy.author_independence`. `elephant-goldfish/check` stays read-only. If the checked
hash has authors, its factual worker needs verified identity and a different canonical
lineage. Otherwise the report says author independence is unverified. Until provenance
is verified, report `lineage per routing config (labels unverified)`.

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

1. Record each finding as `fixed`, `rejected` with evidence, or `deferred`. Deferred
   blockers keep the stage blocked.
2. Run `document-revision` with the cold-read slot and new `{path, sha256}`. Within
   budget, it rebinds affected contracts and slots, then marks those stages and
   successors stale.
3. Retry the factual slot and accept the new hash. Then retry and dispatch a fresh
   cold reader. Retries charge the stage budget. Findings stay in history and are not
   sent to the new reader.

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
- **Legacy topics with no recorded limit.** Record a limit of five and the rounds already performed. Set `max_repair_cycles` to remaining rounds minus one.
  Stop if none remain. If the count is unknown, ask the owner instead of guessing.

For thinking topics, `init` records the four-round default and `resolve` reports the
remaining rounds. `set` records legacy limits and refuses lower counts or increases
without an owner decision. For `elephant.md`, resume the existing job. Budget fields
do not change readiness or grant execution authority.

When the budget is spent, report the document as NOT READY with its unresolved gaps.
Raising a limit is an owner decision through the picker, recorded with `decision`.

## Fallback

If T3 cannot run a factual stage under `elephant-goldfish/elephant`, run it yourself
under the same contract and counters. Set stage `independent_of_author: true`, record
each start with fresh capabilities, and get an owner `lineage-waiver:stage:<stage-id>`
bound to the latest executor, authors, document and stage contract. Unknown authorship
blocks acceptance because independence cannot be checked. Show
`fallback: direct, same-lineage (waived)` in the checklist. A cold read cannot fall back to you. Report it as unreviewed and keep `R-COLD` blocked.

## Report

Report factual verification and cold readability as two separate results with their
receipts. A plausible document is not proof of working software.
