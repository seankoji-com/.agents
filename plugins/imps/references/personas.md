# Optional review perspectives

Load this only for `--personas` or an explicit panel request. Before `init`, set
`policy.review.required` to true and add these briefs to
`policy.review.perspectives`. Preserve any repository-required perspectives:
The core permits at most ten additional perspectives, excluding its default review.
Check the merged policy before `init`; if the panel exceeds that cap, report the
conflict rather than dropping repository-required perspectives.

```json
{
  "solution-architect": "Challenge boundaries, contracts, coupling, callers and migrations. Does the proposed design serve the stated outcome?",
  "grumpy-engineer": "Review each changed line for concrete inputs, errors, edge cases and missing regression coverage.",
  "sre": "Trace interruption, retries, dependency outages, exhausted resources, recovery and operator-visible failures.",
  "business-analyst": "Map every stated acceptance criterion to evidence. Flag omitted requirements and unrequested behavior.",
  "ux-designer": "Inspect the real user flow, accessibility and mobile rendering when a UI exists. Otherwise explain why the UI lens is not applicable, and review any CLI or operator interface that changed."
}
```

The core retains its default independent review and then dispatches one fresh
read-only T3 review per additional perspective, using the configured reviewer role
and the live catalog. Follow the normal entry loop. Do not dispatch extra reviewers
outside it. Reviews run sequentially; this keeps the existing task scheduler and
ownership rules. The core retains each handle, issues distinct request IDs, binds
verdicts to the dispatch revision, reconciles cancellation and blocks readiness until
all required reviews approve the same current tree.

Any blocker or major is adverse, including a contradictory approval verdict. Adverse
findings enter the existing bounded review repair process, never reviewer fallback.
An edit stales approvals; a repair invalidates all evidence and repeats the panel.
Unavailable targets follow the configured availability chain. If none remains, the
run blocks. A waiver requires explicit operator authorization and is reported as
waived, never passed; repository policy may prohibit it.

Personas do not post to GitHub or impersonate separate accounts. Unit tests exercise
the gates and lifecycle, but do not prove live panel behavior across every provider.
