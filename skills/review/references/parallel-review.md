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
   the code authors. When DeepSeek Flash V4.1 wrote material code in the reviewed
   scope, run this lane on Qwen 3.8 Flash (`qwen3.8-flash`) at high model effort
   instead. Select it per run with `--provider`/`--model` on an authorised
   provider that offers it and sends high reasoning effort; do not change global
   configuration to get there. If that route is unavailable or lineage-ineligible,
   report the missing lane rather than falling back to DeepSeek's backend. For
   any other ineligible backend, use an authorised per-run `--provider`/`--model`
   override or report the missing lane; never dispatch DeepSeek directly as a
   substitute. Unlisted OCR backends need user authority.
2. Set `--timeout` on every live run. It is the whole-run task budget in minutes,
   covering LLM requests and retries. It is a CLI flag only: `ocr config set timeout`
   is rejected (`unknown config key: timeout`), so nothing in `ocr config` persists
   it. It is distinct from the per-request limit (`llm.timeout_sec` or
   `providers.<name>.timeout_sec`, overridable with `OCR_LLM_TIMEOUT`). Raising
   `timeout_sec` does nothing when requests already return in seconds. Choose the
   budget from scope and `--effort`. Name **60** for a high-effort review of a
   handful of files: on 2026-11-20 AEDT a frozen 4-file, 178-line diff at
   `--effort high` on `qwen3.8-flash` used 14m52s, 92 requests and 3,975,237
   tokens, then the 15-minute default cancelled it mid-round. Scale up for a
   larger diff or higher concurrency; `0` means unlimited and needs a reason.
   `ocr review --help` remains the source for the installed default (15 on 1.13.13).
3. Write JSON with `--output` and capture the log beside it. The CLI's reason
   line goes to the terminal, so the log is the only copy once the process is
   gone. On a long run, keep the CLI's stdout and stderr off `tail`, `head` and
   `grep`. Those filters buffer until EOF, so a kill, hang or budget cancellation
   leaves a 0-byte capture and drops the reason line; only the JSON file survives.
   Read the tail of the log after the process exits. For frozen workspace scope:

   ```sh
   ocr review --repo /path/to/repo --effort high --timeout 60 --format json \
     --output /path/to/ignored/ocr.json > /path/to/ignored/ocr.log 2>&1
   ```

   Use workspace mode only for explicitly authorised, frozen dirty scope; it
   includes staged, unstaged and untracked changes. For committed
   scope, add `--from <base-sha> --to <head-sha>`. Supply the request and acceptance
   criteria with `--background-file <brief.md>`. Check `--preview` and exclusions
   against the intended scope before the live run.
4. `--effort high` controls OCR's review depth, not the backend's reasoning effort.
   Report those separately; do not claim an unverified model-effort mapping.
   Read the JSON before treating the exit code as the result. Check `status`,
   `manifest.terminal_state`, `manifest.coverage` and `retry_report`. Exit zero,
   empty comments, partial coverage or an empty selection alone do not establish
   completed review. Record failed, skipped and unsupported files explicitly.
   Classify a non-zero run from the JSON:

   - **Budget expiry.** `cancelled_requests > 0` with `failed_requests: 0`,
     attempt `error_class: cancelled`, `failure_phase: context`, HTTP 200 and a
     short `duration_to_headers_ms` (about two seconds in the 2026-11-20 run).
     The server answered; the client cancelled because `--timeout` elapsed.
     `manifest.terminal_state: failed` and a message such as
     `Review failed (cancelled)` can still accompany usable findings. Keep those
     findings as evidence. The lane is incomplete and cannot carry a score.
   - **Provider failure.** `failed_requests > 0`, or attempts whose
     `failure_phase` is the request itself, with a non-200 status or an error
     class other than `cancelled`. That is a backend fault. Findings from such
     a run stay evidence only; the lane stays incomplete.
   - **Token budget.** `--max-tokens-budget` is separate. Help text on 1.13.13
     says a budget-only partial review with usable coverage exits 0, while an
     operational failure (timeout or provider error) exits non-zero. Do not
     treat a token-budget exit 0 as this wall-clock expiry.

   On budget expiry, rerun once on the same frozen revision with a larger
   `--timeout` (double the expired budget, still chosen from the remaining
   scope). If that rerun also expires or fails, report the lane unavailable.
   One rerun is the bound: no retry loop, and no swap to an ineligible backend
   or to DeepSeek when this lane required Qwen 3.8 Flash.
5. Preserve source/HEAD during the run. Handle findings under review's normal
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
