# Trigger evals: implement

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Implement this through T3 delegation.
2. Use implement for the search feature.
3. Delegate the implementation to a worker and bring back reviewed commits.
4. Run implement on issue #44.
5. Have a delegate build this and return the commits for integration.

## Should not fire

1. Fix this typo. (expect: none)
2. Ship this feature. (expect: ship)
3. Iterate with independent review until it scores 9. (expect: review-loop)
4. Clear the backlog. (expect: backlog-burn)
5. Think through the design first. (expect: think)
