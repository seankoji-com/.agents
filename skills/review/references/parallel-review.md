# Run the primary and companion together

Read before starting a review or recheck. Keep the primary selected under
model-selection.md; these companions are additional, not replacements.
Hillclimb uses these companions for formal delivery review. Its scoring
assignments use its own confirmed roster.

1. Classify the reviewed scope by behavior, not filename. The primary reviews the
   whole scope, including UI/visual behavior, and captures its own screenshots.
   Code, configuration, plans and prose without UI/visual changes also qualify
   for the `opencodereview` lane. UI/visual changes add Hydrogen high as a second
   visual review. Mixed changes add Hydrogen and, when that lane applies, OCR for
   the code part. Editing documentation-site copy alone is prose, not a visual
   redesign. A plan or decision brief with no repository changes needs no
   diff-based OCR lane; mark it not applicable instead of inventing a diff or
   blocking discussion.
2. Determine the repository's PR path before adding OCR. A repository is PR-less
   when its delivery policy requires direct publication or the host reports pull
   requests unavailable, such as GitHub's `has_pull_requests: false`. In a PR-less
   repository, OCR is the required companion for code, configuration and mixed
   code scope. A repository that accepts PRs does not add or suggest OCR; the
   primary review alone covers the change there, and OCR runs only when the user
   asks for it. If neither the delivery policy nor the host setting can
   be read, keep the OCR lane and report the gap rather than silently dropping it.
   Visual companions are unaffected by the PR path.
3. Start the primary and required companions in parallel against the same frozen
   revision and acceptance criteria. Reserve the necessary host capacity. Collect
   every required report before accepting review; a missing or failed companion
   remains incomplete. Keep findings and coverage from each report distinct.
   Companions supply evidence and findings, not a score unless assigned a rubric.
4. Apply code-author lineage restrictions only to code review. A matching
   orchestrator is irrelevant. Visual judgments have no lineage exclusion; they
   cannot stand in for independent review of the underlying code.

## opencodereview

Run this lane only where step 2 requires it, or when the user asks. Apply the
[OCR skill](../../ocr/SKILL.md). Pass the frozen revision, every material
code-author lineage, repository visibility, and the sharing decision. That
skill chooses the free or paid route, runs the review, and returns the
findings. It writes logs only in a directory `git check-ignore` confirms is
ignored. Keep this lane's report separate from the primary. Handle findings
under review's severity and disposition rules.

## Hydrogen high

Discover the exact Hydrogen high model and route through the host. Dispatch a
fresh read-only visual reviewer with the assigned-reviewer card and the same
revision, flows and acceptance criteria as the primary. Require direct UI
inspection and screenshots of key states and findings. Observe host browser and
device rules. The primary still reviews the same UI behavior and captures its own
evidence; this companion adds a second visual review, not a replacement. Missing
access or screenshots makes visual coverage incomplete.
If the primary is already Hydrogen, retain a separate companion task; it adds
another review, not another model family. An unavailable required companion is
reported, not silently replaced.
