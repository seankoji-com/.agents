# Trigger evals: babysitter

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Babysit PR #412 until it merges.
2. Watch my open pull request and fix CI if it breaks.
3. Merge PR 88 once the checks pass.
4. Keep an eye on the review comments on my PR and address them.
5. Monitor PR #7 but don't merge it; I'll do that.

## Should not fire

1. Open a pull request for this branch. (expect: raise-pr)
2. Review the diff in PR #412 for bugs. (expect: review)
3. Ship this fix all the way to production. (expect: ship)
4. Close out this thread, we're done. (expect: settle)
5. Clear every open PR and issue in this repo. (expect: backlog-burn)
