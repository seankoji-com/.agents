# Shared reviewer standard

Review the exact proposed outcome against the verbatim request, accepted decisions,
constraints and domain rubric. Map every source-request clause to a requirement or
explicit non-goal. Cover every assigned requirement and load-bearing decision with
an outcome (supported, contradicted or unverified), evidence and coverage limits.
An empty findings list is valid. Approval without coverage is incomplete; never
invent defects or a numeric plan-quality score.

Test the strongest plausible counterexample, failure/recovery scenario and simpler
alternative. Inspect relevant callers, tests, dependencies and source claims within
the authorised scope. Depth follows uncertainty and consequence. Consequential plans
also need migration, permissions, rollback, integration and observable acceptance.
Retain one integrated assessment when lenses split the work. A source/fixture check
does not establish live provider behaviour, customer demand or deployment success.

The coordinator freezes original request/source, accepted constraints/non-goals,
requirement IDs/rubric, exact subject and attachment hashes, renderer/policy profile,
repository snapshot including dirty/untracked evidence, author identities, selection
digest, requested target/options, allowed actions/sharing boundaries and prior
findings/responses. Bind declared evidence and additional paths actually inspected;
unexpected reads need snapshot reconciliation. Cold readers remain document-only
and do not receive prior objections or repository context.

Consume the coordinator's frozen choices under `shared/model-selection.md`; do not
ask a nested chooser, change models/effort, implement, dispatch children, accept your
own output or grant authority. Recommend judgement-capable, suitable cross-lineage
models at advertised high effort, using real option IDs. Fixed-effort models require
a suitability reason. Requested settings and observed identity are separate.

Use strict result/correlation contracts. Every finding needs a stable ID, severity
(blocker, major, minor, note), concrete scenario, source evidence and smallest useful
correction. Blocker/major dominates a contradictory approval. Incomplete means an
invalid envelope or missing coverage/outcome, not disagreement; retain its findings.
The coordinator records fixed/rejected/deferred dispositions with evidence. Deferrals
name impact, owner and next action. Open blocker/major findings prevent readiness.
Repairs need a fresh pass over changed content and all prior unresolved objections.
A rejected major/blocker on unchanged content requires a counted fresh child from
the original reviewer lineage accepting the rebuttal, or a scoped owner decision.
Author-only evidence/self-review cannot clear it. Explicit waivers stay labelled.

Prefer fresh owned executions whose canonical lineage differs from every actual
author, including synthesis. Read-only critique is not authorship; adopted replacement
prose is contribution and must be recorded. Availability fallback follows only the
finite disclosed authorised chain: other suitable cross-lineage children, fresh
same-lineage children, then one separate main-context pass where the workflow allows
it. Retain attempts, failures, handles and actual mode. Reconcile uncertain launches
before replacements. Adverse results or exhausted substantive budget are never
unavailability. Same-lineage and self-review do not establish independence. Stronger
code/factual/cold/persona gates remain binding; planning fallback cannot relabel them.

Bind acceptance to producing selection/options, exact subjects, request, rubric,
policy and relevant evidence. Later unrelated HEAD changes may be visible without
staling unaffected evidence. New source/criteria or producing-record tampering stales
the affected pass. Keep monotonic substantive rounds (new planning subjects get five), separate
finite technical attempts, all prior objections and one active logical review scope
across repairs, replacement jobs, resumes and model changes. Only an owner decision
raises a budget. Do not replace specialised validators or Ralph's final full evaluation.

The requester report states the original outcome, selected/actual models, substitutions,
actual review mode/coverage, exactly which current content passed, material repairs,
retained/rejected/deferred findings and reasons, blockers with owner/next action,
limits and next step. Keep plan review, owner acceptance, cold readability, local
checks, provider observations and execution authority separate. A final code review
does not replace review of a substantive initial plan before dependent work.

For each cleared blocker/major, report its clearing mode and lineage from the receipt.
A permitted self-certified repair of a foreign-lineage major is labelled
`fixed-by-self-review`; retain the original adverse round and finding provenance.

## Final-round triage

The coordinator marks a review `final` in its brief when it is the planned last
assessment before handoff, merge or launch, or the last remaining substantive
round. Apply this rule even when budget remains. Keep full required coverage, but
only issues that must be resolved before the requested outcome may block it.
For each blocking finding, identify the concrete failure, affected requirement
and evidence showing why waiting until after merge/launch is unsafe or defeats
that outcome. Failed required checks, missing required evidence and unmet acceptance
criteria remain blocking. Security or data loss risks and broken supported behavior
block when the concrete scenario makes deferral unsafe or defeats that outcome.
The final round does not begin another design, cleanup or optional-hardening cycle.

Record safely deferrable improvements as minor/note (Ralph: minor/info), with
impact, why deferral is safe and a proposed next action. They do not make the
verdict adverse or trigger another repair/review round. Preserve every original
finding and severity; a previously recorded major/blocker still needs the existing
reviewer agreement or scoped owner decision to clear it. Never silently downgrade
it, waive a requirement, or call missing verification a nonblocking suggestion.

The coordinator searches for an existing matching repository issue, reuses it or
creates one under the operator's issue-filing authority, and records its URL beside
each deferred finding. Include source finding/revision, reproduction or evidence,
impact, safe-deferral reason, owner, next action and acceptance criteria. Redact
private material. An unavailable issue service leaves an explicit unfiled draft and
filing gap in the operator handoff; it does not turn a safe deferral into a product
blocker or permit a claim that the issue was filed. Do not repeat a review solely
to file or link an issue. Reviewers remain read-only and return proposals to the
coordinator; they never file issues themselves without separate authority.

## Operator visibility and learning

Immediately after each subtask review returns, including optional, adverse,
incomplete and failed reviews, output a summary of at most three sentences in the
main context before dispatching repairs or another review. Name the review/round,
finding themes and concrete examples, which issues block versus can be deferred,
coverage gaps and the next action. A zero-finding review says what it covered.
Keep full source findings and dispositions in the evidence record; the summary
does not replace them. Give the operator a chance to steer through normal input;
do not require an acknowledgement after each summary.

At handoff, summarize all deferred fixes with issue links (or unfiled status),
impact, owners and next actions. Capture a lesson from observed review churn under
`PKG/shared/learnings.md` and the harness memory policy. Name the failure that
escaped, the build/test or task-structure change that would catch it earlier, and
how the next run will verify that change. Prefer a failing reproduction before
implementation, tests at the affected integration boundary, installed-artifact
checks, and batching related fixes before re-review when the evidence supports
them. Do not invent a lesson for a clean run. Report a proposed lesson and storage
gap when persistence is unavailable or not authorised.
