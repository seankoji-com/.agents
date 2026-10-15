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

New jobs set `policy.identity: observed`; acceptance verifies reviewers, subjects
and author-independent slots. Legacy jobs without the marker keep target-only rules.
`thinking` and `elephant` also set `policy.author_independence`.

Record each author from fresh `orchestrator_capabilities` using `--capabilities FILE`.
The response needs inherited provider, model and parent thread; the model must be in
that provider's catalog. Use `thinking_state.py author` for discovery/spec,
`render_handoff.py --capabilities FILE` for handoffs,
`record_document_author.py <path> --capabilities FILE` for `elephant.md`, and
`job_cli.py document-revision --capabilities FILE` for repairs. A handoff includes
its renderer and source-hash authors; missing source records leave it unknown. A
checker never becomes an author. These are host facts transcribed by the coordinator;
shape and hash checks cannot prove freshness or detect a forged file.

`check` stays read-only. Its factual slot must name the validated stage document. If
its hash has authors, the worker needs verified identity and a different canonical
lineage. Unknown extra subjects preserve this requirement and fail closed. A direct
check with recorded authors needs `direct-execution` and a stage-scoped waiver bound
to the latest executor. With no author record, it may proceed with author independence
reported as unverified; a waiver cannot establish missing authorship. Direct factual
authoring with unknown authorship stays blocked. Report routing labels as
`lineage per routing config (labels unverified)` until provenance is verified.

An owner `lineage-waiver:task:<task-id>` binds the target, author list, slot contract
and document hash. Direct factual stages use `lineage-waiver:stage:<stage-id>` bound
to the latest executor. Waivers skip no requirement; changes to bound values need a
new decision. Plan revisions re-import authors for changed or added slots and check
each slot against its stage document.

An edited copy recorded at a temporary path and moved into place inherits authors
recorded for the destination path. A first record of an unrecorded document cannot
identify earlier authors; that history stays outside the trust boundary.

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

When spent, report NOT READY. `document-revision` refuses with
`attempt_budget_exhausted` and `owner_decision_required`. Another round needs an owner
decision through the question picker and a `plan-revision` that raises the limit. Do not seek
another reviewer to overturn an adverse verdict.

## Round limits

A cold-read round is one executed slot. Its budget belongs to the topic or document;
resume never resets it.

- **New topics and documents.** Four rounds in total: the initial read plus three
  repairs (`max_repair_cycles: 3`).
- **Existing topics with a recorded limit.** Keep the recorded limit and count.
- **Legacy topics with no recorded limit.** Record a limit of five and the rounds already performed. Set `max_repair_cycles` to remaining rounds minus one. Stop if none remain; ask the owner if the count is unknown.

For thinking topics, `init` sets the default and `resolve` reports remaining rounds.
`set` records legacy limits and refuses changes without an owner decision. For
`elephant.md`, resume the existing job. Budget fields do not change readiness.

## Fallback

If T3 cannot run a factual stage under `elephant-goldfish/elephant`, run it yourself
under the same contract and counters. Set stage `independent_of_author: true`, record
each start with fresh capabilities, and get an owner `lineage-waiver:stage:<stage-id>`
bound to the latest executor, authors, document and stage contract. Unknown authorship
blocks acceptance because independence cannot be checked. Show
`fallback: direct, same-lineage (waived)` in the checklist. A cold read cannot fall back to you. A direct cold-read stage cannot be accepted from the coordinator. Report it as unreviewed and keep `R-COLD` blocked.

## Report

Report factual verification and cold readability as two separate results with their
receipts. A plausible document is not proof of working software.
