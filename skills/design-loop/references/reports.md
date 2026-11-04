# Show each round's changes

Produce a baseline/reference gallery and one HTML report per change round, even
when a candidate fails or scores decline. Keep an index linking the full history.
Store reports, original screenshots and run records in the verified artifact
directory; name files by run, phase and round so later results append history.

## Evidence and annotations

Capture matching before/after states with real UI screenshots. The round's before
is its actual parent candidate, which may be the phase best rather than the last
attempt. Also offer the original baseline for comparison. Label source revision,
tested build, state, viewport/device and capture date on each pair. Explain missing
images or incomparable conditions. Mockups and old captures cannot prove a fix.

Keep unaltered originals. Put numbered callouts over a displayed copy or in an HTML
overlay, with an adjacent legend mapping each number to a stable finding/change ID.
Use normalized image coordinates or another method that stays aligned when the
image scales. Do not paint over the defect or crop away context needed to assess
it. Make the report usable at narrow and wide widths, with readable full-size images.

Each annotation states what changed, why it helps the scoped task, its evidence,
and its status: proposed, observed fixed, rejected with reason, deferred or still
unverified. Include newly introduced regressions, not just improvements. Separate
confirmed behavior from hypotheses and taste preferences. Preserve original finding
IDs, severities and captures; append new results instead of rewriting history.

## Contents of every round report

- Run/phase/round, parent and candidate revisions, build/environment and evaluated
  flows/states/viewports; exact implementor/judge identities and options.
- Comparable before/after screenshot pairs with callouts and explanatory legend.
- Implemented changes and reasons, finding dispositions and any regressions.
- Per-dimension scores, weighted sums/overall scores, per-judge findings and coverage.
  Use `not evaluated` for missing results, never a made-up number.
- Required check methods, thresholds, results and evidence links, separate from
  model judgments. Distinguish local validation from hosted CI and live acceptance.
- Current phase metric, historical best score and candidate identity, qualifying or
  accepted candidate and current repair base when different, consecutive
  non-improvement count, any explicit user limits and their consumption, and next
  action. Explain why the counter changed or did not.
- Goal status, stop reason when relevant, unmet criteria, access/evidence gaps and
  links to original captures, reference gallery and prior reports.

For a failed round, show available evidence and explain every unavailable result.
Do not use the previous round's screenshot as a passing capture for this candidate.

## Presentation and transport

Inspect the report's images, captions, callout alignment and links. Use portable
HTML with inline CSS, no remote dependencies and embedded or portable local image
assets. Escape product text; reports should not execute scripts from the product
or reference sites. Keep private data and credentials out of captures and HTML.

The coordinator presents the report to the operator after each round. In T3, use
`html_preview` then `html_render` with the report HTML. Do not start a web server
for a report. If native HTML presentation is unavailable, return an accessible
HTML file link and disclose the presentation gap. Delegates return raw findings,
captures and paths; the main thread owns the combined operator report. Judges
receive their own findings and change summary rather than this combined report,
which exposes other judges' scores.

Before PR creation, preserve reports in a destination authorized for the intended
readers. Follow `raise-pr` for actual screenshot attachment and access verification.
A local path is not a GitHub attachment. Include the final report plus history
where accessible; explicitly disclose reports/images that remain local or could
not be uploaded. Do not commit evidence merely to host it, expose private captures
on public hosting, or delete the sole copy while an authorized handoff needs it.
