# Discover, specify, hand off

## Workflow boundary

The active workflow is thinking. Requirement changes refine this brief. Discovery
acceptance, a final handoff, feature answers, silence, and scheduled reminders do not
authorise implementation. Do not launch implementation children, imps runs, or new
implementation threads from thinking by default. Separately authorised production
work in the same thread does not authorise execution of this topic.

On resume, compaction, and scheduled continuations, resolve the topic and preserve
this boundary in the continuation notes. An old scheduled prompt is context, not a
new user instruction to execute. If intent is materially ambiguous, clarify before
dependent implementation. A clear user request to leave thinking can change the
workflow: record the exact request, source message reference, and authorised scope
under `meta.json`'s `execution_request` using `set`, then follow that scope. The
helper never grants execution authority; that record is for the next agent to inspect.
`resolve` exposes `has_execution_request`; the request itself is in `meta`.
This agent-writable record is unvalidated context, not an authenticated grant. The
next agent must inspect the actual user instruction and scope before acting.

## Procedure

1. Run `python3 PKG/scripts/thinking_state.py list`. With `thinking list`, display and
   stop. For an existing slug, use `resolve <slug>` and resume its `next_phase`.
2. For a new topic, settle output type (`implementation` or `research`) and a kebab-case
   slug. Default to local storage. Use
   `init <slug> --output-type <type> --title <title> --github none`.
   GitHub issue/discussion publishing is optional and requires explicit authorization
   for the destination and content. The helper `gh_publish.py` supports `ensure` and
   `post`; inspect its help before use. A publishing failure must not lose local work.
3. Load only `PKG/templates/probes.<type>.md`. Ask a few questions at a time. Probe
   actual decisions, current workarounds, concrete success/failure examples, consequences,
   alternatives, and material tradeoffs. Follow answers to refine the problem; a
   multiple-choice feature list is not discovery acceptance. Find repo facts yourself.
   Challenge assumptions with concrete counterexamples. Name unresolved decisions,
   owners, and next actions. Explore doing nothing and simpler alternatives. There is
   no minimum question count or interview duration. Respect a request to stop: save
   current notes and report unresolved questions without manufacturing acceptance.
4. Synthesize `thinking/<slug>/discovery.md` using `PKG/templates/discovery.skeleton.md`. Preserve
   agreed constraints verbatim. Distinguish facts, hypotheses, preferences, and open
   questions. Mark incomplete discovery, including notes saved when the user stops,
   with `<!-- thinking:draft -->` and `DRAFT. Non-executable.` on separate lines.
   The exact standalone comment is the required machine-readable draft signal. Keep
   its spacing and do not substitute a decorated heading or label for it.
   Put status lines at column zero, outside quotations and code blocks.
   Present the refined discovery for operator review before finalising the
   rubric. `resolve`/`list` now hold at `discovery_review`. Ask for acceptance of this
   specific content, not another feature choice. Only after a genuine operator response,
   record its verbatim statement and source reference with:

   ```sh
   python3 PKG/scripts/thinking_state.py review <slug> --decision accepted --scope finalise-brief --discovery-sha256 <reviewed-hash> --evidence-ref <user-message-reference> --operator-statement-file thinking/<slug>/review-statement.txt
   ```

   Use the hash of the discovery that was presented, from `resolve`'s artifacts.
   Write the exact acceptance text to the statement file with a structured file tool.
   Treat it as data: never interpolate user text into a shell command or shell `echo`.
   The helper also accepts stdin with `--operator-statement-file -` when a tool can
   supply stdin as literal data. Finalise a draft discovery before requesting review.
   Edits invalidate the receipt. Feature answers, silence, model summaries, scheduled
   reminders, and a request to stop are not acceptance evidence. Never invent a
   statement or reference. A receipt records evidence; it is not cryptographic proof
   of human intent. If the owner explicitly overrides discovery review, use
   `--decision owner_override` with their exact statement and the same scope. This
   permits finalising this brief only, records no acceptance, and grants no execution.
5. Load `PKG/templates/spec.skeleton.md`. Define observable acceptance criteria with stable
   `[REQ-...]` IDs, test methods, failure conditions, and explicit out-of-scope work.
   Settle which unknowns block execution. Save `thinking/<slug>/spec.md`.
   Retain licence, budget, identity, credential, and authorisation gates with owners
   and next actions. Hold dependent work rather than guessing these gates away.
   If the user requests an incomplete draft, put `<!-- thinking:draft -->` and
   `DRAFT. Non-executable.` at the top of `spec.md`. A draft does not require acceptance.
   Standalone status lines also hold a draft when placed below its heading. Code-fenced
   examples and inline quotations of the marker stay inert.
6. Run `thinking_state.py gate <slug> --require discovery,spec`, then
   `render_handoff.py <slug>` and `render_handoff.py <slug> --check`.
   The renderer copies source documents verbatim and records hashes. Never replace
   that deterministic step with a model-written summary.
   For an explicitly requested draft, use `gate <slug> --require discovery,spec --draft`
   and `render_handoff.py <slug> --draft`. It writes `handoff.draft.md` and a separate
   draft manifest, never a final completion. `--check` (or `--draft --check`) verifies
   provenance only; the gate checks current review/readiness independently. Old topics
   without valid evidence need review even when spec and handoff already exist.
   Changing a receipt, including acceptance to an owner override, requires re-rendering
   the final handoff even when discovery content is unchanged.
7. Deliver `handoff.md`, its manifest, remaining unknowns, and the intended next step.
   The user can give it to a fresh T3 thread or imps. Do not start that work here.

## Regression scenarios

- Feature-selection interview: "API, cache, dashboard" selects preferences. Probe a
  current workaround and a failure example, refine discovery, then present it for review.
- New example: "Last week's duplicate charge matters more than latency" adds a
  requirement. Update discovery, reopen review, and only then finalise the rubric.
- Draft request: "Give me what you have so far" produces labelled non-executable drafts,
  with open questions. It does not accept discovery or make the topic complete.
- Stop request: "Stop asking questions" stops the interview and saves notes. Do not
  convert it into discovery acceptance, final readiness, or execution authority.
- Requirement change on resume: "Switch to the official API" refines discovery. An
  old scheduled "continue" prompt and unrelated production authorisation do not turn
  it into permission to launch an implementation child.
- Deliberate transition: "Leave thinking and implement the retry policy in this repo"
  is a new instruction. Record its source and exact scope before starting that work;
  it does not authorise publication, deployment, or unrelated changes.

These instructions guide the agent. The helpers enforce receipt shape, content binding,
draft separation, and provenance. They cannot measure interview quality, authenticate
the supplied statement, or prevent every unauthorised tool call.
