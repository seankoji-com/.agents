# Keep one rolling report

Maintain one HTML report per run at a stable, accessible path. Start with the
evaluation contract and baseline. Append sections for each evaluation, repair
round and stop, including failures and declines. Give each section an anchor
and identify the current round and selected candidate near the top. Preserve the
run record, original evidence and earlier results in authorised storage.

## Show the evidence

- Record phase, round, parent and candidate identities, environment, evaluated
  scope and coverage, and the actual implementer and judge models and options.
  At panel entry, record the approved primary choice and the new baseline.
- Include what changed, why it helps, any regressions and finding dispositions.
  Preserve stable finding IDs and original observations. Append new evidence and
  record fixes, rejections with reasons, deferrals and unverified outcomes.
- Record dimension scores, weighted totals, the current phase metric, historical
  best, repair base, below-high count and limit consumption. Use
  `not evaluated` for missing results and explain the gap.
- Report required check methods, thresholds and results separately from judge
  scores. Link reproducible evidence, such as logs, measurements or artifact
  excerpts. Distinguish local validation, hosted CI and live acceptance.
- Record goal status, stop reason where applicable, unresolved gates and next
  action. Label any evidence that covers an earlier or different candidate.

## Add UI evidence in UI mode

Show the original baseline and any relevant reference anchors. Use matching
live before-and-after screenshots for each visible change or finding. Compare
against the round's actual parent. Label the source revision, build, state,
device or viewport and capture date. Explain missing views or differing
conditions.

Keep unaltered originals. Place numbered callouts over a displayed copy or in
an HTML overlay and map each number to its finding or change ID. Use coordinates
that stay aligned when the image scales. Keep enough surrounding context to
evaluate the finding and offer the readable full-size image. Caption each
capture with what it shows and the outcome it supports.

## Present and hand off the report

Inspect the updated sections, images, links and callouts. Use portable HTML
with inline CSS and embedded or portable local images. Escape product text and
exclude secrets, personal data and product scripts.

The coordinator gives the score, changes, outstanding checks and a link to the
new report section after each round. Link the [score graph](../../review/references/score-chart.md)
produced by `review-loop`. In T3 use `html_preview` then `html_render` for the
rolling report. Provide an accessible HTML link if inline display is unavailable.
Keep the combined report out of judge briefs so prior judgments stay independent.

Before PR creation or cleanup, preserve evidence needed for the handoff in a
destination authorised for its intended readers. Follow `raise-pr` for
attachments and access verification. Disclose any report or image unavailable
to PR readers and preserve its authorised copy.
