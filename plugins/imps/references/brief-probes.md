# Refine a brief before planning

Inspect the repo before asking for facts available in code, configuration, or tests.
A useful brief names the observable change, its acceptance, and any constraints that
must hold across tasks. Keep an already concrete brief intact. For missing decisions,
ask a small batch and continue independent work.

Choose probes for the actual unknown:

- What is the smallest outcome that counts as done? What is out of scope?
- Which cross-task contract must stay identical: field names, API shape, persisted
  data, compatibility bounds, or forbidden paths?
- Which caller or stored record would break if this were subtly wrong?
- What output or command proves the result? What would make the operator reject it?
- Which external action is authorized: local edits, publication, merge, deployment,
  or a message? Which necessary access remains unavailable?

Copy constraints verbatim into `brief.constraints`. Give acceptance stable requirement
IDs and kinds in the core plan. Put discoverable facts in the brief with their evidence.
Do not invent a fixed question count or turn vague wishes into unchecked acceptance.
Before substantial delegated work, challenge the plan for incompatible task boundaries,
missing prerequisites, and untestable outcomes. Independent plan review, when required
by the repo or operator, uses a tracked read-only T3 task before implementation. Keep
its findings and revised plan in scratch; it does not replace the core's diff review.
