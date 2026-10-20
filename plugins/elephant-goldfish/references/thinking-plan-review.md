# Thinking source-plan review

The coordinator owns discovery, decisions, drafting and repairs. Before substantive
work it uses the shared model-selection contract in the entry; these deterministic
helpers and the reviewer never open another chooser. Use
`PKG/shared/planning-review.md` for the separate planning job and its finite
fallback, finding/disposition and persistent-budget contracts.

## Freeze the source

Before drafting, run `thinking_state.py init <slug> --output-type <type>
--selection <sealed-selection.json> --request-reference <source-message-reference>`.
The selection operation is `elephant-goldfish/thinking`; its scope is the shared
logical output ID derived from that reference and `thinking/<slug>/handoff.md`.
Init seals the admission in metadata. Author recording and source freezing require
it, and planning creation must use its exact producing selection digest.
Missing choices, another scope, tampering and adding choices to existing drafts
are refused. Legacy/status reads remain available; they grant no current readiness.

After content-bound owner discovery acceptance and a final spec, run:

```sh
python3 PKG/scripts/thinking_state.py --root thinking plan-review <slug> --input <inputs.json>
```

The input object supplies `requests`, `decisions`, `requirements`,
`load_bearing_decisions`, `attachments`, `repository_root`, `evidence_paths` and
optionally `declared_paths`. Requests and decisions are separate verbatim UTF-8
files with actual message `reference` and contiguous character-range `clauses`,
each mapping to a requirement or explicit `non_goal`, per the shared capture
contract. An empty decisions list means no additional owner decisions beyond the
bound discovery receipt. Never replace source messages with a coordinator summary.
`requirements` maps exactly every `[REQ-...]` in spec to its acceptance statement.

Attachments and evidence paths are absolute file paths, or `{path, data_class}`
descriptors when material needs a confidential class. Include every path the
reviewer may inspect, including dirty/untracked source bytes; `declared_paths`
names mandatory reads and defaults to every evidence path. If no narrower evidence
set can be justified, enumerate the whole relevant snapshot. Reconcile any extra
reads against pre-review bytes before acceptance. Never include handoff, metadata,
snapshot or receipt outputs as their own input. `--template-dir` freezes an explicit
renderer override when needed.

The helper writes `plan-review.snapshot.json` and a topic-local reference in
`meta.json`. It binds discovery/spec/attachments, request/decisions, the owner
discovery receipt, all source authors (unknown stays unknown), spec/domain rubric
and renderer template. Hashes include relevant dirty/untracked bytes; HEAD is
reported separately. Receipt timestamps and generated output are outside the
source subject, so rerendering cannot create an approval cycle.

## Review and refine

Use that exact returned `snapshot` with the shared planning CLI's `create`, then
`begin`. Set `plugin: elephant-goldfish`, whose pinned manifest declares
`planning-review`, `source-plan` and `elephant-goldfish/plan-reviewer`. Selection
`scope_id` equals the snapshot's stable `logical_output_id`. Retain the returned
`subject_file` and job handle through resume and repairs. Existing code, factual,
cold-read and handoff jobs cannot be relabelled into this policy.

Follow the shared CLI for preparing/dispatching selected slots, recording actual
host observations, ingesting complete results, dispositions and finishing a round.
The coordinator alone dispatches through T3. Every round covers the original
request, rubric and all prior objections. Retain rejected/deferred findings and
their evidence; an unresolved blocker/major prevents readiness in every mode.
Do not start another job to reset rounds or erase findings. Budget and findings
live in the private XDG review-subject record, not the topic's metadata.

Repair discovery/spec/attachments, re-record actual authors, and freeze a new
snapshot for `begin` on the same subject. Bundle discovery-affecting owner decisions
once per round; unchanged discovery needs no repeated approval. Plan review grants
no execution or publication authority. Fallback requires the shared evidence and
mode-specific validation; same-lineage and self-review never claim independence.

## Consume acceptance

After shared `finish` returns `accepted: true`, attach the actual receipt file
named by its `reference.path`:

```sh
python3 PKG/scripts/thinking_state.py --root thinking plan-review <slug> --receipt <receipt.json>
python3 PKG/scripts/validate_document.py --root thinking --slug <slug> --mode plan-review
python3 PKG/scripts/thinking_state.py --root thinking gate <slug> --require discovery,spec,plan_review
python3 PKG/scripts/render_handoff.py <slug> --root thinking --capabilities <capabilities.json>
python3 PKG/scripts/validate_document.py --root thinking --slug <slug> --mode handoff
```

`list`, `resolve` (including resume), gate, rendering and document validation reopen
the actual receipt, producing job/subject, passes, target/options and current source
hashes. A boolean, partial/stale result, absent/tampered receipt or pending child
cannot pass. Request/decision, attachment, rubric/template and relevant source
changes reopen plan review. Discovery edits also reopen owner acceptance. Unrelated
HEAD movement is visible without forcing another review.

The renderer copies source text verbatim and records review, template and rubric
references in schema-3 provenance. `--check` verifies provenance only. Historical
schema-2 completion is labelled `legacy-unreviewed` without modifying old artifacts;
it cannot satisfy `--require plan_review`, the current document validator or a new
final render. Draft/stop output stays non-executable and available without review.
Optional cold readability remains a separate document-only job and budget.

Deliver actual review mode/coverage, chosen models/options and substitutions,
rounds used, changes made and all findings/dispositions with limits and next actions.
Host/owner records are transcribed evidence, not cryptographic proof of intent or
model behaviour. Fixture tests establish local acceptance paths, not live adherence.
