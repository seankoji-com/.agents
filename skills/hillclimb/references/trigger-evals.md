# Trigger evals: hillclimb

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Hillclimb the onboarding flow.
2. Keep improving this prompt until it scores 9 out of 10.
3. Improve the report layout over several judged rounds.
4. Iterate on the CLI help text until the judges are happy.
5. Raise this workflow's score against our rubric.

## Should not fire

1. Iterate with independent code review until the PR is clean. (expect: review-loop)
2. Compare three design options. (expect: choose-design)
3. Review this once. (expect: review)
4. Optimise this SQL query. (expect: none)
5. Pressure-test this idea. (expect: challenge)
