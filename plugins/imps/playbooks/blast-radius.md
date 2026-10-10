# Trace a change beyond its diff

Read `PKG/shared/t3-runtime.md`. This operation is read-only; do not fix findings.

Resolve the target as a PR, exact commit range, file paths, or working-tree/index diff
against HEAD. State the base/head and changed-file count. Infer intent and the most
important invariants from code and evidence; mark unknown intent explicitly.

For each changed public symbol, schema, command, setting, or lifecycle hook, trace
real consumers. Include persisted data, migrations, generated artifacts, CLI/API/UI
callers, caches, retries, ordering, cleanup, and optional paths. A text match is a lead,
not proof. Read enough surrounding code to establish the actual path.

Grade each claim: text match, source path, concrete failure path, or executable proof.
Use only existing verification known to be read-only. Do not run scripts that write
caches, generated data, or remote state. When execution cannot be read-only, provide
the smallest proposed check and label the risk unproven.

Report change/invariants, confirmed consumers, risks with severity and proof level,
cleared edges, and remaining pre-merge verification. A missing harness is not a proven
product defect; passing unit tests do not clear untested consumers.
