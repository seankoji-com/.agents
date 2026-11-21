# Trigger evals: test-writer

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Write tests for the date parser.
2. Is this test suite worth its CI time?
3. Which regression test should cover this bug?
4. Review these flaky tests.
5. Can we delete these slow integration tests safely?

## Should not fire

1. Review this PR for correctness bugs. (expect: review)
2. Fix the failing CI on PR #9. (expect: babysitter)
3. Implement the parser change. (expect: none)
4. Run the app and take a screenshot. (expect: none)
5. Profile why the build is slow. (expect: none)
