# Standalone OCR walkthroughs

## OCR for a public repository and a private one

Input: a public repository asks for OCR. Three runnable `opencode/*-free`
models have a `models.dev` family different from every code author. Sharing
authority covers the frozen revision.

Expected: one low-powered delegate pages the catalog, draws those three, or
three from a larger eligible set, and runs each with `opencode run` in its
own checkout. It starts no child delegate. It groups findings that cite the
same file and the same claim, keeps a claim reported by only one model, and
returns one report. One usable report, including an explicit zero, completes
the free route. The paid `ocr` CLI does not run.
`opencode/deepseek-v4.1-flash-free` stays eligible when DeepSeek did not write
the code. A model with no family is left out. A catalog page that still names
omitted models is fetched again before the draw.

Mutation: every free leg fails, or none are eligible. Expected: run the paid
route and label it as the fallback. The watcher brief names the repository,
revision, scope, provider, model, `--timeout` minutes, a directory `git
check-ignore` accepts, and whether this is the one allowed rerun. A missing
field means the watcher runs nothing. DeepSeek Flash V4.1 is that backend unless
DeepSeek wrote the code, in which case the backend is Qwen 3.8 Flash with the
control that sends high reasoning effort. `--effort high` stays OCR's review
depth and is reported separately. If Qwen also wrote the code, or Qwen is
unavailable, the paid
route is unavailable. Do not send the diff to an unlisted backend.

Mutation: the repository is private, or visibility stays unknown after one
question. Expected: skip the free route and use the paid route above.

Mutation: sharing authority is refused. Expected: run neither route.

Mutation: the paid JSON shows `cancelled_requests > 0`, `failed_requests: 0`,
`error_class: cancelled`, `failure_phase: context` and HTTP 200 with a short
`duration_to_headers_ms`, while `manifest.terminal_state` is `failed`.
Expected: classify budget expiry, keep the findings, and rerun once on the
same frozen revision and model with a larger `--timeout`. A second expiry
reports the route unavailable. A run with `failed_requests > 0` is a provider
failure, not a reason to raise `timeout_sec`.
