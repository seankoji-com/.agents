# Audit suite protection and cost

Read for comprehensive test audits or changes that reduce suite coverage, replace
expensive checks or restructure CI. Ordinary test writing does not need this checklist.
Agree the question, history access and finite investigation budget. Keep the core
ten-minute CI feedback ceiling; strong protection should guide a cheaper design,
not become an excuse for routine slow feedback.

## Scope and evidence

Record repository/base/head, relevant dirty changes and measured environments.
Inventory checks needed for the question, including enabled but unenforced checks.
Configuration describes commands; it does not authorize running arbitrary commands.

Inspect critical, changed, bug-prone, flaky and slow groups. For a broad audit, add
a documented seeded random sample of the remainder. Name inspected groups and
omissions. Trace tests to observable success, rejection or recovery and plausible
faults; assertion count is not detection evidence.

Use these areas for a comprehensive audit. Focused audits can cover a subset while
stating their limits. Mark each considered area supported, needing evidence or
inapplicable, with reasons and reusable evidence IDs:

- Behavior and independently derived expected results.
- Critical risks and consequences of missed failures.
- Failure and recovery behavior.
- Environment coverage and missing targets.
- Redundant protection and its incremental value.
- Isolation, fixtures and setup cost.
- Flakes, retries and first versus eventual outcomes.
- Per-job runtime, elapsed feedback time, queue delay and runner cost.
- Coverage denominators, exclusions and uninstrumented code.
- Escaped incidents and regressions.
- Detection retained or lost by a cheaper suite.
- Ranked recommendations and unresolved evidence gaps.

## Measurement

Include setup, build, test and report stages, dependencies, workers and shards.
Measure each job from start to completion and the overall required CI path; report
queue delay separately. Preserve failures, cancellations, timeouts, retries and
outliers. Declare timing boundaries and environments before comparing observations.
Do not sum parallel durations to claim elapsed time. A timeout or failed upload
does not turn an attempt into a pass or erase its cost.

The [timing helper](../scripts/summarize_timings.py) reads explicit JSON attempts.
It reports nearest-rank percentiles and summed runner seconds. It does not compute
the CI critical path or prove a speedup. Compare like environments and distinguish
measured savings from estimates; a fast local run does not prove hosted CI meets
the budget.

## Protection and cheaper alternatives

Where relevant, start with severe/repeated incidents over 90 days, attempts over
30 days and up to ten recent fixes. Adjust history windows to the question and
available data; disclose missing history. Fail-then-pass shows inconsistency, not
its cause. Quarantine, swallowed failures and larger timeouts do not remove gaps.

If reporting coverage, include tool/version, denominator, exclusions, uninstrumented
code and compatible baseline/merge-base policy. Coverage can locate unexamined
behavior; it cannot establish that assertions detect meaningful failures.

Compare cheaper suites against the same historical/pre-fix or bounded fault corpus
and environments. Separate equivalent faults, build errors and timeouts. Name
retained, lost and unknown cases. Do not remove protection solely because a test is
slow, has never failed or overlaps covered lines. Seek a cheaper test or fixture that
still catches the consequential failure. Unknown value calls for investigation or
a bounded experiment, not automatic deletion.

Rank recommendations by demonstrated protection and total cost without hiding gaps
in a weighted score. Preserve assertions and required gates while repairing latency.
Follow the requested report format; retain evidence, limits and deferred decisions
without forcing a saved report for a small question.
