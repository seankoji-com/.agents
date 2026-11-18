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

This option invokes the OpenCodeReview library's `ocr` CLI from
`@alibaba-group/open-code-review`, not the unrelated OpenCode coding agent.
Run this lane only where step 2 requires it. Use the installed library directly;
add no wrapper, provider SDK or model task pretending to be OCR.

1. Check `ocr version` and `ocr review --help`. Respect existing sharing authority
   for the provider and scope; exclude secrets and unrelated paths. Reuse covered
   authorization without another per-run question. Use an authorised configured
   provider/backend without printing credentials or changing global configuration.
   DeepSeek Flash V4.1 is permitted inside OCR only. Record the actual backend;
   the OCR tool name is not a model lineage. For code review, verify it against
   the code authors. If the backend is ineligible, use an authorised per-run
   `--provider`/`--model` override or report the missing lane; never dispatch
   DeepSeek directly as a substitute. Unlisted OCR backends need user authority.
2. Put output in a verified ignored task directory. For frozen workspace scope:

   ```sh
   ocr review --repo /path/to/repo --effort high --format json --output /path/to/ignored/ocr.json
   ```

   Use workspace mode only for explicitly authorised, frozen dirty scope; it
   includes staged, unstaged and untracked changes. For committed
   scope, add `--from <base-sha> --to <head-sha>`. Supply the request and acceptance
   criteria with `--background-file <brief.md>`. Check `--preview` and exclusions
   against the intended scope before the live run.
3. `--effort high` controls OCR's review depth, not the backend's reasoning effort.
   Report those separately; do not claim an unverified model-effort mapping.
   Inspect the JSON coverage/terminal state and findings. Exit zero, empty comments,
   partial coverage or an empty selection alone do not establish completed review.
   Record timeouts, failed/skipped files and unsupported scope explicitly.
4. Preserve source/HEAD during the run. Handle findings under review's normal
   severity and disposition rules. Track the process and clean task-owned output
   after the handoff; do not delete durable evidence needed for deferred issues.
   Record OCR's session ID. Its normal session history under
   `~/.opencodereview/sessions/` is application-managed state, not disposable task
   output; preserve it under the user's existing retention settings.

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
