# Run the primary and companion together

Read before starting a review or recheck. Keep the primary selected under
model-selection.md; these companions are additional, not replacements.
Hillclimb uses these companions for formal delivery review. Its scoring
assignments use its own confirmed roster.

1. Classify scope by the behavior that changed. The primary covers the whole
   scope and captures its own screenshots for UI changes. For UI and mixed
   changes, add Hydrogen high to review the visual behavior. Use the primary
   alone for code, configuration, plans and prose without visual changes.
   Documentation-site copy edits alone count as prose.
2. Start the primary and required companion in parallel against the same frozen
   revision and acceptance criteria. Reserve the necessary host capacity. Collect
   every required report before accepting review; a missing or failed companion
   remains incomplete. Keep findings and coverage from each report distinct.
   Companions supply evidence and findings, not a score unless assigned a rubric.
3. Apply the [eligibility rules](model-selection.md) to code and readiness review.
   Visual judgments cannot stand in for independent review of the underlying code.

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
