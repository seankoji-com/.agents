# Trigger evals: backlog-burn

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Clear the backlog.
2. Burn down the open issues and PRs in this repo.
3. Get our issues to zero.
4. Run a backlog burn across the example-org organisation.
5. Clear every open pull request and issue.

## Should not fire

1. File an issue for this bug. (expect: raise-issue)
2. Babysit PR #3. (expect: babysitter)
3. List the open issues. (expect: none)
4. Fix issue #20. (expect: none)
5. Ship this change. (expect: ship)
