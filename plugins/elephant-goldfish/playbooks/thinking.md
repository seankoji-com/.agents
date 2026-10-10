# Discover, specify, hand off

1. Run `python3 PKG/scripts/thinking_state.py list`. With `thinking list`, display and
   stop. For an existing slug, use `resolve <slug>` and resume its `next_phase`.
2. For a new topic, settle output type (`implementation` or `research`) and a kebab-case
   slug. Default to local storage. Use
   `init <slug> --output-type <type> --title <title> --github none`.
   GitHub issue/discussion publishing is optional and requires explicit authorization
   for the destination and content. The helper `gh_publish.py` supports `ensure` and
   `post`; inspect its help before use. A publishing failure must not lose local work.
3. Load only `PKG/templates/probes.<type>.md`. Ask a few questions at a time and follow
   dependencies between decisions. Find repo facts yourself. Challenge assumptions
   with concrete counterexamples. Name unresolved decisions and their owners. Explore
   doing nothing, simpler alternatives, failure consequences, and reversibility.
   Continue while the operator finds it useful; respect their request to stop.
4. Synthesize `thinking/<slug>/discovery.md` using `discovery.skeleton.md`. Preserve
   agreed constraints verbatim. Distinguish facts, hypotheses, preferences, and open
   questions. Review the discovery with the operator before building the rubric.
5. Load `spec.skeleton.md`. Define observable acceptance criteria with stable
   `[REQ-...]` IDs, test methods, failure conditions, and explicit out-of-scope work.
   Settle which unknowns block execution. Save `thinking/<slug>/spec.md`.
6. Run `thinking_state.py gate <slug> --require discovery,spec`, then
   `render_handoff.py <slug>` and `render_handoff.py <slug> --check`.
   The renderer copies source documents verbatim and records hashes. Never replace
   that deterministic step with a model-written summary.
7. Deliver `handoff.md`, its manifest, remaining unknowns, and the intended next step.
   The user can give it to a fresh T3 thread or imps. Do not start that work here.
