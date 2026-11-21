# Trigger evals: github-writing

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Draft a comment on issue #8 explaining the fix.
2. Write the release notes for v2.1.
3. Edit my PR description to be clearer.
4. Post a reply to the review on PR #3.
5. Write a GitHub discussion post announcing the change.

## Should not fire

1. Write a Slack message to the team. (expect: none)
2. Write a commit message. (expect: none)
3. Update the README install section. (expect: none)
4. Open a PR for this branch. (expect: raise-pr)
5. Review PR #3 for bugs. (expect: review)
