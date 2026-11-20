---
name: ocr
description: "Run OpenCodeReview on a frozen diff. A public repository draws three free OpenCode reviewers; a private one runs the ocr CLI through one watcher. Relay the findings unchanged."
---

# Run OpenCodeReview

Use this when the user, or another skill, asks to run OpenCodeReview (OCR) on
a diff. Review calls this skill when its companion lane applies, and anyone
may invoke it directly. This skill does not decide that a review must include
OCR. It chooses the backend, runs the review, and returns the findings.

The caller supplies the repository, the frozen revision, the code-author
lineage of every model that materially wrote the scope, and whether the
repository is public or private. Missing lineage: ask once, then stop.
Missing visibility: ask once; if it stays unknown, use the private route.
Public visibility is not permission to send the diff. If sharing authority
is missing, ask once for the smallest packet and the intended roster. A
refusal blocks both routes.

Both routes review the same frozen revision. Committed scope names the base
and head SHAs. An authorised dirty scope names the paths and a fixed snapshot
or a frozen checkout. A child that lacks those changes is a failed leg.

## Choose the route

A public repository tries the free route first, including a dirty workspace.
The free route fails only when every free leg fails. Then run the paid route
and say that it is the fallback. The run fails only when the free legs all
fail and the paid route is also unavailable or fails after its one rerun.

A private repository, or unknown visibility, uses the paid route only.

## Free route

The free route is not the `ocr` CLI. Discover runnable `opencode/*-free`
models with `orchestrator_capabilities`. Read each model's `family` and
`tool_call` from the `opencode` provider at `https://models.dev/api.json`.
Reuse that record for 24 hours. It is a family lookup, not a quality ranking
and not a frozen allowlist. `litellm/*-free` names are not this route.

A model is eligible when the host can run it, `tool_call` is true, `family`
is present, and that family differs from every material code author. A null
or missing family is ineligible; record it. DeepSeek Flash stays eligible
when DeepSeek did not write the code. The bar on dispatching DeepSeek as a
direct reviewer belongs to the review skill, not to this draw.

Draw up to three eligible models at random and record the draw against the
frozen revision. Reuse it for that revision, including a retry. A new
revision draws again. Fewer than three eligible models: run all of them.
None eligible: skip to the paid route.

Respect `max_concurrent_delegates` and the host limit. When fewer than three
slots are free, run waves until three have started or the cap blocks another
start. Request `runtimeMode: full-access` for each OpenCode child when the
parent can grant it. A parent that cannot grant it has no free candidates.
Zero permission-compatible candidates fails the free route. The paid route
then runs only when it is itself permitted and the sharing decision covers
its provider.

Each leg is an async `delegate_task` on the OpenCode provider and the drawn
model, at the high variant when the model exposes one, otherwise the model
default. Give it the [assigned-reviewer card](../review/references/assigned-reviewer.md)
at its absolute path, plus the scope, revision, and acceptance criteria.
These delegates are the reviewers. They do not run `ocr`.

A leg's budget equals the paid route's `--timeout` for the same scope: 60
minutes for a high-effort review of a handful of files. A usable report names
the assigned revision and the required scope, and either lists findings or
says there are none. A wrong revision, a missing scope, an error, a
cancellation, or silence past the budget is a failed leg. Zero findings with
the scope covered is success.

Wait until every started leg returns or hits its budget. One usable report
makes the free route succeed, and the other legs still finish. Start the
paid route only after every free leg has failed. The final report includes
every leg, its model, and whether the paid route ran. Relay each report
unchanged. Do not merge or re-score findings.

## Paid route

Dispatch one async delegate on a low-powered model. It is a watcher, not a
reviewer, so its family does not matter. Give it the
[OCR watcher card](references/ocr-watcher.md) at its absolute path and the
resolved backend, scope, revision, budget, and output paths. It runs the
`ocr` CLI, follows the process until it exits, and returns one report. The
orchestrator gets nothing until that report, including the one budget rerun.
Dispatch it with `delegate_task` in `async` mode. A `wait` call returns
within 45 seconds and does not stop the child.

The backend is DeepSeek Flash V4.1 on an authorised configured provider.
When DeepSeek Flash V4.1 wrote material code in the scope, use Qwen 3.8 Flash
(`qwen3.8-flash`) at high model effort instead. If Qwen also wrote that code,
or Qwen is unavailable or unauthorised, the paid route is unavailable. Do not
use DeepSeek to review its own code. Select the backend per run with
`--provider` and `--model`. Change no global `ocr` configuration, add no
provider, and add no wrapper or SDK. Unlisted backends need the user's
authority. Record the backend. The `ocr` tool name is not a model lineage.

On budget expiry the watcher reruns once, on the same frozen revision and the
same model, with double the expired `--timeout`. A second expiry or failure
makes the route unavailable. There is no further retry and no swap to an
ineligible backend.

## Report

Return one report to the caller. Include the route, each model's identity,
the revision, which legs failed, and whether the paid fallback ran. Inline
the findings. A path inside a delegate workspace is not enough. A paid-route
report also includes `status`, terminal state, coverage, the retry report,
the session ID, and the budget-expiry classification from the watcher card.
OCR's own post-filter stands. Relaying unchanged means unchanged from that
output.
