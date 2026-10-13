# How the workflows help

A workflow is useful when it saves you from reconstructing the same instructions
or asking for missing evidence after the agent says it has finished.

## Get a change you can check

[imps](plugins/imps.md) turns a bounded task into requirements, implementation and
verification. Checks and reviews carry a binding to the files and contract they
verified. If the code changes afterward, the gate reports stale evidence.

You receive a run ID and a report showing current readiness. An interrupted run can
resume with its recorded artifacts and child handles. Missing tools or a failed
review stay visible rather than becoming a completion claim.

## Stop planning from evaporating between threads

[elephant-goldfish](plugins/elephant-goldfish.md) captures decisions, constraints,
unknowns and acceptance criteria. Its handoff copies the source documents verbatim
and records their hashes, so a fresh session receives the agreed brief.

It stops at the handoff. You decide when implementation starts.

## Borrow an approach with evidence

[ape](plugins/ape.md) studies another repository against a gap in yours. Recommendations
cite source at a resolved commit, name local target files and include a small
experiment with success and abandon conditions. Research does not execute the
third-party code or start changing your project.

## Keep PR work moving

[babysitter](plugins/babysitter.md) checks reviews and CI against the current PR head,
fixes authorized problems and uses T3 watches for later events. It reports actual
merge state and exact blockers. Protected-branch requirements still apply.

## Inspect settings without changing them

[agent-tuneup](plugins/agent-tuneup.md) reports known broad permissions and duplicate
rules in explicitly supplied settings. It emits finding codes and locations rather
than values. The report is a starting point for inspection, not a complete permission
simulator.

## When a direct request is enough

A one-line edit rarely needs saved run state or delegated review. Use the smallest
workflow that earns its overhead. All entries and their local helpers ship as
readable files; [architecture](architecture.md) explains their boundaries.
