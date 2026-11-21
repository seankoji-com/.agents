# Trigger evals: ship

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Ship it.
2. Ship this change and verify it in production.
3. Deliver this fix end to end.
4. Take this branch all the way to merged and deployed.
5. Ship the settings page and give me a retrospective.

## Should not fire

1. Open a draft PR. (expect: raise-pr)
2. Watch PR #5 until it merges. (expect: babysitter)
3. Show me a timeline of the plan. (expect: plan-report)
4. Implement this through delegates and hand back commits. (expect: implement)
5. Review the release notes for mistakes. (expect: review)
