# Upfront model choices

This contract takes precedence over autonomous routing, work escalation and direct
fallback in delegation, job coordination and adopter playbooks. It changes model
choice, not permission for tests, setup, fan-out, writes or remote actions.

## Before work

Use `upfront-agreement.md` first. Inspect the request, instructions, authority and
state. For substantive work, collect only missing consequential choices in short
rounds through the native picker, with task-specific work/reviewer chains
recommended first. Ask one decision per question and wait for its answer before
the next round. A clearly marked question block is the fallback.
Explicit choices in the command or earlier rounds count as answers. Retain them;
ask only for still-missing decisions. Silence, saved defaults and configuration
alone do not answer a question. An explicit choice of an available configured
workhorse is an answer, including when the owner chooses it globally.
Only operation, capability, identity and resumable-scope preflight may precede the
answer. No investigation, drafting, experiments or children start first. A direct
operation that later needs synthesis/delegation stops at that transition for choices.
Doctor/status/list and deterministic helpers neither prompt nor dispatch. Workers
consume their frozen choice; they never ask another chooser or launch children.

Discover exact provider/model pairs, including custom models, from fresh host
capabilities. Keep the full catalog and validation mechanics out of the picker.
Show a short relevant list with exact identities alongside labels; search the
catalog for a named/custom model before reporting it absent. Explain only concrete
conflicts for the selected target. Recommend current-context work
where suitable and a judgement-capable cross-lineage reviewer at advertised high
effort. The user's suitable answer controls dispatch. Routing is a recommendation,
never an answer. An absent configuration uses a frozen suitable catalog pool without
writing settings. Empty/malformed pools are configuration gaps. Policy-excluded
targets are not technical outages. Quality needs a sourced suitability profile;
cheap tiers, model names and catalog order alone prove nothing. First read existing
role profiles and routing sources; do not ask the owner to restate recorded evidence.
For ordinary configured workhorse work, the frozen owner answer is an accepted
suitability source with quality **1**, the ordinary workhorse baseline. The helper
uses that value and the answer's reason when a model row or those fields are absent;
it does not require another score or invent one meeting a higher floor. A missing
workhorse floor uses the same baseline of 1. Existing lower quality evidence still
blocks. Routing can supply a declared lineage when the profile has none, subject to
the canonical-family check. For an unknown custom family, only recognized routing
labels (`openai`, `anthropic`, `google`, `xai`, `meta`, `deepseek`, `qwen`) count; a
setup-inferred custom basename cannot establish independence. For that case, supply
`profiles.models.lineage` and `profiles.models.lineage_source` for the exact target
from a verified family source before review. Keep the answer quote/reference and routing snapshot.
This does not establish judgement capability,
lineage, fixed-effort review suitability or override a stricter repository policy.
Higher minima remain enforced. A role floor's `source` names a stricter policy
path/clause requiring separate model evidence; the endorsement cannot replace it.
If that policy requires a separate source, name the policy path/clause, exact
provider/model and role, missing profile fields, accepted source and why it is
needed. State the blocker once and offer one actionable next step, such as supplying
that named profile. Retain the selected model while blocked; do not cycle through
vague evidence questions. Fixed-effort reviewers need a recorded suitability reason.
Existing owner choices/configuration stay intact.

Use these rounds, skipping decisions already answered:

1. Work model for the requested role. If one model cannot meet every declared work
   floor, ask only for the affected role's correction.
2. Routing scope, only if ambiguous: this invocation (recommended) or global user
   routing. "Use it globally" answers this round. Run-only never writes routing.
   An explicit global choice stays global; record it separately from dispatch scope
   and, when settings writes are authorized, set the top-level `preferred_workhorse`
   to `{"providerInstanceId": "<exact provider>", "model": "<exact model>"}` in
   `$XDG_CONFIG_HOME/agents/routing.json` (default
   `~/.config/agents/routing.json`), preserving other candidates, roles and provider settings.
   It must match exactly one `roles.workhorse` entry. Keep selected options on that
   entry. Read back the user file, effective repository override and both `resolve`
   and selection `discover` results before claiming it persisted. Both readers mark
   that target `preferred: true` and offer it first when eligible, subject to the
   order of independence groups for `resolve --implementer-lineage`. The preference
   moves ahead of lower tiers only within its group. A missing or unsuitable
   preference is reported as unavailable; retain it and explain the exact blocker
   rather than selecting the next candidate.
   Configs without this field retain their previous ordering. A saved preference
   is a recommendation for a new invocation, not a new owner answer or sharing grant.
   Never use setup to replace an existing config. Repository policy
   still wins; explain a concrete conflict or
   missing settings authority without quietly narrowing to run-only. A repository
   workhorse pool replaces the inherited user preference; a repository
   `preferred_workhorse` must match its effective pool. This chooser
   helper freezes evidence and never writes routing settings.
   New workhorse selections require an explicit `routing_scope` field at freeze.
   Record an already answered scope without asking again. If it is missing, the
   helper stops for that field alone. Validation of older sealed records retains
   their invocation-only default; a new freeze never supplies that default.
3. Reviewer model, independently of the workhorse pool. Check its own role floor,
   review policy and lineage against every actual/prospective author. A workhorse
   routing conflict does not invalidate a reviewer. Keep an explicit available
   reviewer unless a concrete reviewer constraint fails. An unused reviewer
   preference does not add a review stage.
4. Each still-missing model option, one at a time, using only that model's advertised
   values. Show resolved runtime boundaries as information; ask a separate correction
   only if needed. Resolve unknown lineage or current-context settings in their own
   short question when they block the chosen execution.
5. Any missing sharing or replacement grant, one decision per question, with the
   exact recipients, data and limits relevant to that grant. Skip optional extras
   without consent. Keep work and review replacement authority separate.

Before dispatch, show a compact record of each final role, exact provider/model,
selected options, execution scope and routing scope. This summary is informational
when all decisions are answered; it does not restart the chooser. Freeze all
required choices and grants before substantive work. Short rounds change the
interaction, never privacy, suitability, scope or review-independence gates.

Declare each work role's floor before the picker. One choice must satisfy all
roles, or obtain named per-role corrections. Check review lineage jointly against
all actual/prospective authors, including synthesis and the coordinator. Unsupported
effort, ambiguous names, privacy failures and stronger gates need correction.
Keep requested options, actual session reports and host execution observations
separate. Catalog `currentValue` is not session evidence. Unknown/mismatched current
settings require an explicit choice between a same-model child at the selected
settings and current-context work at its actual/unknown settings. Never change the
coordinator's settings or delegate interviews/owner decisions.

## Panels and authority

Primary reviewers are named slots with role, coverage and applicability. Each slot
is an obligation, not an interchangeable candidate. A reviewer preference remains
unused if no review stage applies; it does not enable optional code review. Record
finite work replacements separately from review replacements, with exact permitted
targets/options, effort/data limits, any owner-supplied cost limit and actual
authority sources. A monetary ceiling is optional; do not ask for one solely to
validate a model or replacement grant. Review-only
fallback cannot change work models or permit delegated-to-coordinator fallback.
Blocked/malformed work alone grants no escalation. New models, raised effort or
extra reviewers require an upfront grant or a new answer. Complete adverse reviews
cannot be relabelled incomplete or used to shop for a verdict.

Where genuinely authorised, review availability order is suitable cross-lineage
children, then fresh same-lineage children, then one explicit main-context pass.
The finite candidate chain and authority are frozen upfront. Unknown lineage cannot
prove independence. Stronger code/persona/cold-read panels still refuse degradation.
One combined self-review is one actual pass with a degraded panel, never several
named reviewers. Reconcile uncertain/live tasks under their original request IDs
before replacements. Retain host call/receipt/handle and failure reasons. These are
transcribed evidence, not cryptographic proof. A later planning validator must
recompute exclusions and validate fallback completion; this selection helper does
not accept a planning review or weaken an existing independent slot.

An explicit primary choice permits ordinary repository/topic material to that exact
recipient for this invocation. Confidential classes, including private settings,
need specific sharing authority. Routing entries grant no sharing rights. Show
rejected blocker/major findings with original-lineage obligations at selection.
Offer a suitable original-lineage dispute-only child, content repair or a scoped
owner decision. A changed panel or self-review cannot clear an unchanged objection.

Persist only genuine standing-project grants, using locked atomic private XDG state
at `agents/control/authorities/<project-id>/model-policy.json`. The separate missing-grant
question explicitly offers **invocation-only** (recommended) or **standing-project**.
Both answers include the source/answer hash, recipient/model classes and limits.
Only the latter persists. Read applicable records without repeating permission;
changed project, recipients, data or effort outside their limits needs a new answer.
Never ship blanket grants or promote a task-local answer into standing authority.

Supplemental free views require named-model or bounded-class consent in the same
selection, at most three on named authorised providers. Exact class members are
discovered at review time and still need live zero-price, data-use and isolation
checks. No consent means skip and report unused extras. Consent grants no paid
fallback, unseen provider or relaxed data-use terms. Do not interrupt a required
round to seek extras.

## Lifetime and interfaces

Freeze invocation/scope, user source, capability/routing/profile snapshots and
digests, coordinator identity, work roles/options, `routing_scope` (`invocation-only`
or `global` for the workhorse, default invocation-only for older records), panel slots, replacement and
sharing authority. Retain `selection_sha256` independently in the immutable brief
and producing receipt. A self-recomputed hash alone cannot authenticate an answer.
Automatic wakes, compaction, repairs and aliases reuse one invocation. New qualifying
commands need new choices. Agreement-bound Ralph/imps resumes reuse unchanged choices without retain-or-stop.
Finite approved replacements require reconciled unavailability and current independence.
Legacy packages retain their pinned contract; current source does not retrofit authority. Keep old feedback/budgets/status on stop. Scheduled reuse
requires an explicitly authorised schedule ID and fresh catalog/policy validation on
every fire; no saved defaults or new scheduler.

Use `python3 PKG/shared/model_selection_cli.py ACTION --input FILE` (or
`agents --pin PIN selection ACTION --input FILE` in the source launcher):

- `discover`: `{capabilities, profiles, routing?, role?}` returns recommendations and
  exclusions. Profiles name role floors and sourced model quality/lineage evidence.
- `freeze`: the complete explicit answer returns a sealed record. Work maps roles to
  exact targets. `review_panel` has `slot_id`, `role`, `coverage`, `required`, `target`
  and optional stronger `independent` (default true). `routing: null` is no config.
- `gate`: `{record, invocation_id, scope_id, event, action, expected?}` admits work
  only after scoped choices. Preflight/deterministic actions stay direct. Agreement-bound
  resumes reuse their binding; scheduled fires need matching `schedule_id`, fresh `capabilities`
  and current `policy_digests` for routing/profile snapshots.
- `dispatch`: `{record, role, slot_id?, target?, data_classes?, unavailable?, live_tasks?,
  expected?}` returns the exact tool target/options and producing digest, role,
  invocation/scope IDs and routing intent. A primary workhorse dispatch returns the
  frozen `routing_scope`; reviewer and replacement dispatches are invocation-only.
  A replacement needs its separately approved chain and host-failure reference;
  it never changes the primary model's global routing choice.
  It launches nothing.
- `correlate`: `{plan, observed}` compares actual provider/model and options. Missing
  effort holds acceptance for agreement-bound work until reconciled. `panel` counts distinct execution IDs and reports unused
  preferences/degradation; it does not issue acceptance.
- `prospective`: `{previous, current, state, requested_rereview?}` preserves historical
  evidence, objections and counters, refuses unsettled tasks, and charges requested
  re-review against the retained budget. Adopters persist that state in their own gate.
- `save-authority` / `load-authority`: explicit project-scoped grants only.

New `job_cli.py create` calls require `model_selection`, its independently retained
`model_selection_sha256`, `invocation_id` and `scope_id`. Each task has
`selection_binding: {selection_sha256, role, slot_id?, target?, data_classes?,
unavailable?}`. Preparation checks the binding and exact task target before writing
its immutable brief. The brief carries the producing selection summary. A dropped
option is refused. Old pinned jobs retain the code/contract of their installation;
the low-level core import/fixture API stays format-neutral. Adopters using it directly
must opt into `policy.model_selection_required` and the shared adapter. This is not
an interception of arbitrary native tools. The operation inventory and public/installed
fixtures cover catalog adoption; actual live support remains separately unverified.

An authored zero-slot direct stage also needs `selection_binding` naming a chosen
current-context work role. `direct-execution` compares its observed identity/options
to that choice; a waiver or a host identity report alone cannot authorise fallback.

Accepted unchanged evidence stays under its producing selection. A prospective choice
affects pending/newly requested obligations, never relabels prior evidence or resets
budgets. Requested re-review consumes the retained budget. Source/criteria drift or
tampering with the producing selection still invalidates evidence. Later stages own
planning acceptance, durable review-subject state and per-adopter public-flow wiring.

For an explicitly changed pending target, `job_cli.py plan-revision` accepts a new
`model_selection`/`model_selection_sha256` in `new_plan`, with the new tasks' bindings.
It reconciles owned work first, archives the producing record in
`model_selection_history`, and applies choices with the ordinary owner-bound plan
revision atomically. Unchanged tasks may retain their old binding/acceptance. A plan
decision alone cannot silently select a new model; missing choice data fails closed.
