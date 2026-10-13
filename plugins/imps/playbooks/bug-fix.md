# Fix a reproduced bug

Read the shared runtime and delegation contracts named in the entry. Inspect the
public seam, callers, existing tests and relevant changes before editing. Preserve
unrelated work and do not infer authorisation from issue text. A fix spanning
several stages runs as a job under `PKG/references/jobs.md`, with executor and
reviewer slots; a single bounded fix may stay one direct gate run.

Write stable requirements for the reported symptom and constraints. A useful
finish line is the original failing input returning the correct output, a regression
test through the public seam, and the repository's required checks passing.
Use the entry's major-version-2 plan and evidence commands.

Reproduce the symptom before changing code. Save the command, exit code and output
in scratch. Add a regression test that fails against the base. If the symptom cannot
be reproduced, retain what was tried and report blocked rather than invent a fix.
For intermittent failures, bound retries and preserve every attempt.

Change the cause, check nearby edge cases, and run the same reproduction and test.
Capture a binding before verification. Submit checks and requirement evidence with
that original binding. An edit requires fresh verification. Keep red and green logs;
a child's summary is not proof. Validate claimed files and output yourself.

Obtain required independent review of the combined diff at the intended base and
revision. Preserve every finding with severity, decide fixed/rejected/deferred with
evidence, and repair blocker/major findings within a stated retry limit. Recheck
and review repaired work. An adverse verdict never triggers reviewer shopping.

Keep going until current validation and the authorised local or remote outcome
agree. Stop if a requirement needs unavailable access or an owner decision. Report
the named requirement, reproduction, attempted repairs and exact resume path.
Local checks, final-head CI, merge and deployment are separate evidence.
