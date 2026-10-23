# plan

Turn an uncertain problem into a reviewed plan that a fresh thread can execute.
Invoke `$t3-plan <topic or problem>`. There are no public subcommands. With no text,
use the relevant conversation context and ask only for a missing topic. A request
to list or resume plans uses the state helper directly, without an operation menu.

`PKG` is the directory containing this entry. Apply
`PKG/shared/model-selection.md` before substantive work. Read
`PKG/shared/t3-runtime.md`, `PKG/shared/learnings.md` and this plugin's project
lessons. Delegation follows `PKG/shared/delegation.md`; separate review jobs follow
`PKG/shared/job-coordination.md`. Load `PKG/playbooks/plan.md`.

## Workflow

1. Resolve existing plans with `python3 PKG/scripts/plan_state.py list`. Resume a
   named plan rather than creating duplicate work. New plans live in
   `plans/<slug>/`; old elephant-goldfish topics are not migrated automatically.
2. Establish whether the output supports implementation or research. Ask about
   the actual problem, current workaround, consequences, alternatives and concrete
   success or failure examples. Inspect relevant repository facts yourself.
   There is no required interview length. Do not ask questions whose answers are
   already available or turn a request for a quick assessment into a formal plan.
3. Draft discovery with the user's constraints verbatim. Separate facts,
   assumptions and unresolved decisions. Present that content for acceptance.
   Feature choices and silence are not discovery acceptance.
4. Write a testable specification with stable requirement IDs, observable
   acceptance criteria, verification methods, exclusions and blocking unknowns.
5. Review the exact discovery/spec and declared repository evidence through
   `PKG/references/source-plan-review.md`. Repair findings and reopen discovery
   acceptance only when its content changes. Keep actual review receipts and
   finding dispositions, including rejected and deferred findings.
6. Run the readiness gate and deterministic renderer. Deliver the handoff, its
   provenance manifest, actual review coverage, unresolved questions and next steps.

## Ownership and acceptance

The coordinator conducts the interview, drafts documents, records decisions and
accepts stages. The `plan/plan-reviewer` independently challenges the exact source
plan read-only. It cannot interview the user, accept its own work or grant authority.
Deterministic list, resolve, gate and rendering operations launch no workers.

`plan_state.py gate <slug> --require discovery,spec,plan_review,handoff` decides
readiness. `render_handoff.py <slug> --check` verifies provenance, and
`validate_document.py --mode handoff --slug <slug> --root plans` runs both checks.
A plausible document, completed child, boolean or old receipt is not acceptance.
Helpers locate bundled shared contracts and remain usable after installation moves.

## Boundary

Planning ends at the handoff. Do not implement, launch imps or start implementation
threads from a plan, including on resume, compaction or scheduled continuations.
Only a clear user instruction to leave planning changes that scope; retain the exact
request and its source reference before proceeding. Other work authorized in the
same conversation grants no implementation authority for this plan.

Drafts and requests to stop remain available without acceptance. Preserve their
non-executable markers and report unresolved decisions. GitHub publication requires
explicit authority for the destination and content. Ask actual owner decisions
through the host's native question picker, recommended answer first; never ask the
user to select a command mode.
