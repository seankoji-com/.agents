---
name: ocr
description: "Run OpenCodeReview on a frozen diff. A public repository draws up to three free OpenCode reviewers and returns one grouped report; a private one runs the ocr CLI through one watcher."
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

The free route is not the `ocr` CLI. Dispatch one async delegate on a
low-powered model. That delegate owns the draw, the three reviewers, and the
single report. It is not a reviewer, so its family does not matter. The caller
receives nothing until that report.

The delegate pages `orchestrator_capabilities` until `omittedModels` is 0 or the
page repeats. A model is eligible when the host can run it, its id is
`opencode/*-free`, `tool_call` is true, and `https://models.dev/api.json`
gives the `opencode` provider a `family` for it that differs from every
material code author. Reuse that record for 24 hours. It is a family lookup,
not a quality ranking. A null or missing family is ineligible. DeepSeek Flash
stays eligible when DeepSeek did not write the code. `litellm/*-free` names
are not this route.

Draw up to three eligible models at random and record the draw against the
frozen revision. Reuse it for that revision. A new revision draws again.
Fewer than three eligible models: run all of them. None eligible: return that
fact so the caller starts the paid route.

The delegate runs the reviewers itself. It starts no child delegate and no
child agent. Each leg is one `opencode run` in the frozen checkout.
Write each log under a directory that `git check-ignore` confirms is ignored.
A directory that check does not accept is not an output path.

```sh
opencode run --model opencode/<model>#<variant> --auto --format json \
  "<review brief>" > /path/ignored/<model>.log 2>&1
```

Use `#high` when that model exposes a high variant. Otherwise omit `#variant`.
Confirm the flag in `opencode run --help` before the first live run. The
brief contains the [assigned-reviewer card](../review/references/assigned-reviewer.md)
text, the scope, the revision, and the acceptance criteria, and it tells the
model to run a check only when a finding depends on that check. Do not pipe
the command through `tail`, `head`, or `grep`. A killed process drops a
buffered pipe, and the log is the only copy of the report.

Run each leg as a background shell and wait for it with `t3_background_wait`
on its shell ID. Do not hold one foreground shell open for the whole budget.
Budget 60 minutes per leg for a high-effort review of a handful of files, so
three sequential legs need 180 minutes. Run the three commands in parallel
when the host allows three concurrent processes. Record each shell ID and PID.
On cancel, stop those PIDs only. If the host exposes no `t3_background_wait`,
set the shell wait to the whole leg budget instead.

A usable log names the assigned revision and required scope, and either lists
findings or says there are none. A wrong revision, a missing scope, a non-zero
exit, a cancellation, or an empty log is a failed leg. Read each log after
its process exits.

Group findings that cite the same file and the same claim. Keep every
distinct claim, including a claim from only one model, and name the models
that reported it. Record a leg that found nothing and a leg that failed. Do
not change a severity and do not drop a claim. One usable report makes the
free route succeed. When every leg fails, say so. The caller then starts the
paid route. The delegate does not.

## Paid route

Dispatch one async delegate on a low-powered model. It is a watcher, not a
reviewer, so its family does not matter. Give it the
[OCR watcher card](references/ocr-watcher.md) at its absolute path. The brief
names the repository, the frozen revision, the scope, the provider, the model,
the `--timeout` minutes, an output directory that `git check-ignore` confirms
is ignored, and whether this invocation is the one allowed rerun. A missing
field is a gap, and the watcher runs nothing. It runs the
`ocr` CLI as a background shell, waits with `t3_background_wait` on its shell
ID, and returns one report. The orchestrator gets nothing until that report,
including the one budget rerun.
Dispatch it with `delegate_task` in `async` mode. A `wait` call returns
within 45 seconds and does not stop the child.

The backend is DeepSeek Flash V4.1 on an authorised configured provider.
When DeepSeek Flash V4.1 wrote material code in the scope, use Qwen 3.8 Flash
(`qwen3.8-flash`) and the control that sends high reasoning effort. `--effort
high` is OCR's review depth, not that reasoning effort. Record the two
separately, and do not claim a reasoning effort the run did not verify. If
Qwen also wrote that code,
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
