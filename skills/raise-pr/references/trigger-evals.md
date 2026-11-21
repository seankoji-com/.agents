# Trigger evals: raise-pr

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Open a PR for this branch.
2. Create a pull request with the screenshots.
3. Update the PR description with the test evidence.
4. Prepare the pull request for review.
5. Raise a PR against the release branch.

## Should not fire

1. Merge PR #12 when the checks pass. (expect: babysitter)
2. Review PR #12. (expect: review)
3. File an issue for this bug. (expect: raise-issue)
4. Ship this all the way. (expect: ship)
5. Write a commit message for these changes. (expect: none)
