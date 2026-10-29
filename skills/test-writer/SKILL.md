---
name: test-writer
description: "Use when writing or reviewing tests, choosing regression coverage, or assessing test value, reliability and CI runtime."
---

# Write tests worth running

## Philosophy

Prefer high-value tests over high coverage. Every test should catch a plausible,
consequential failure and justify its runtime, maintenance and debugging cost.
Coverage percentages, test counts and test-level ratios are not quality targets.

Fast feedback is part of code quality. Tests that push routine CI feedback past
ten minutes (600 seconds) defeat their purpose by delaying correction and
discouraging frequent validation. Treat that as a design problem to solve, not an
acceptable price for more coverage.

## Workflow

1. Read the behavior, repository test rules and existing protection. Name the
   consequential failure and the gap each new test addresses. Prioritize regressions,
   important user behavior, rejection and recovery. Skip additions when existing
   protection suffices or a low-impact edit has no meaningful behavior to protect.
2. Choose the cheapest level that detects the real failure. Use small, deterministic
   fixtures, observable assertions and independently derived expected results. Mock
   unstable boundaries without mocking away the behavior under test. Avoid duplicates,
   implementation mirrors and snapshots that cannot be usefully reviewed.
3. For regressions, verify failure before the fix and success afterward when feasible.
   Run required checks and relevant failure cases. Investigate flakes instead of
   hiding them with retries, longer timeouts or weaker assertions. Report verification
   gaps plainly.
4. Keep required CI feedback within ten minutes, including setup, build, tests and
   reporting. Measure per-job runtime, elapsed time, queue delay and total runner cost
   separately; do not sum parallel durations as elapsed time. If over budget, repair
   the bottleneck within authority. Preserve meaningful assertions and required gates.

Read the [audit reference](references/suite-audit.md) for suite-wide reviews or costly
test removal; establish retained and lost detection before recommending removal.
The optional [timing helper](scripts/summarize_timings.py) summarizes observations,
not elapsed CI time or causal speedup.

## Outputs

Report protection added, checks/results, runtime impact and gaps in the requested
format. A short answer can stay in chat. Distinguish local timings, current-head
hosted CI and estimates. Unmeasured CI cost does not prove budget compliance.

## Boundaries

Reuse existing authority and follow repository and host rules. Auditing alone does
not authorize test deletion, runner spending, CI policy changes or publication.
Preserve unrelated work. Efficiency must preserve useful protection.
