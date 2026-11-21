# Trigger evals: raise-issue

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. File a bug for the login timeout.
2. Open an issue for adding dark mode.
3. Draft a GitHub issue describing this crash.
4. Investigate this error and raise an issue for it.
5. Follow up on issue #31 with what we found.

## Should not fire

1. Open a PR for this fix. (expect: raise-pr)
2. Clear all open issues in this repo. (expect: backlog-burn)
3. Turn this idea into a brief. (expect: think)
4. Fix the bug in issue #31 directly. (expect: none)
5. Show the plan on a timeline. (expect: plan-report)
