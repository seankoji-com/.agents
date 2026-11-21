# Trigger evals: review

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Review this PR.
2. Get an independent review of the plan.
3. Check the release against the acceptance criteria.
4. Review the UI of the checkout flow.
5. Do the readiness check for this brief.

## Should not fire

1. Are you sure about this idea? (expect: challenge)
2. Iterate with review until it scores 9. (expect: review-loop)
3. Run OCR on this diff. (expect: ocr)
4. Write tests for this module. (expect: test-writer)
5. Respond to the reviewer's comments on PR #4 and merge it. (expect: babysitter)
