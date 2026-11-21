# Trigger evals: review-loop

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Implement this and keep iterating with an independent reviewer until it scores 9.
2. Run review-loop on the parser refactor.
3. Fix the findings and get it re-reviewed; repeat until clean.
4. Iterate on this change with independent review rounds.
5. Keep implementing and repairing until the reviewer accepts it against the criteria.

## Should not fire

1. Review this plan once and report findings. (expect: review)
2. Improve the onboarding flow until the judges score it 8 out of 10. (expect: hillclimb)
3. Challenge my assumptions about this design. (expect: challenge)
4. Write regression tests for this bug. (expect: test-writer)
5. Delegate this feature through T3 and bring back commits. (expect: implement)
