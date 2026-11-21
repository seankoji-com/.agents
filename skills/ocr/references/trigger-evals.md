# Trigger evals: ocr

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Run OCR on this diff.
2. Get an OpenCodeReview of this branch.
3. Use OpenCodeReview with the free reviewers on this public repo.
4. Review this change with OCR; the repository has no PR.
5. Run the ocr CLI on the frozen diff.

## Should not fire

1. Extract the text from this scanned image. (expect: none)
2. Review this PR. (expect: review)
3. Read the text in this screenshot. (expect: none)
4. Challenge this design. (expect: challenge)
5. Write tests for the diff. (expect: test-writer)
