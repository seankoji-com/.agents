# Bug-fix playbook

Use this for a bug, regression, flaky behaviour, unexplained failing check or wrong output. It runs inside the loop from `entry.md`. Its job is to stop a plausible theory from standing in for evidence.

## 1. Inspect

Read the repository instructions and `git status`. Note unrelated changes so you leave them alone. Find how the project runs and tests itself: package scripts, Makefile targets, `tests/`, and CI files (read them only to learn the commands).

## 2. Reproduce the original symptom first

Establish one fast command that shows the reported failure on the real surface: a CLI invocation, an HTTP request, a focused test, or a browser assertion when the bug is in a UI. Run it before forming any theory. Save to `<run dir>/scratch/red.log` (the run dir comes from `init`):

```text
argv: <exact command>
cwd: <directory>
revision: <git rev-parse HEAD, plus "dirty" if git status is not clean>
expected: <what should happen>
actual: <what happened, verbatim>
```

If you cannot reproduce it, or need access you lack (credentials, production data, a device), stop the dependent work. Record `block` with code `operator` and a reason naming exactly what is missing. Finish any independent work first. An unreproduced symptom stays `unverified`: never fix it on a guess.

For UI symptoms, look for the T3 preview toolkit by meaning (tools that open, navigate, click and snapshot a preview). If none exists, record the runtime requirement as `unavailable` with what you tried, and use a documented alternative such as a scripted HTTP check. Do not claim a browser check you did not run.

## 3. Diagnose

1. Tighten the signal: assert the exact symptom, and pin time, randomness, filesystem and network where you can. For a flake, raise the reproduction rate first.
2. Minimise the reproducer, one input or dependency at a time. Keep only what the symptom needs.
3. Rank three to five falsifiable hypotheses. For each, name the observation that would tell them apart, then test one variable at a time with a debugger or uniquely tagged log lines.
4. If none is confirmed, check the minimised symptom still reproduces, gather one new discriminator, and rank again. After two unproductive rounds, stop: record a `block` that reports the evidence and the missing access. If the symptom stops reproducing, report the result as inconclusive. Never promote the least-wrong hypothesis to a cause.

Remove temporary instrumentation before you implement.

## 4. Plan the run

Requirements describe observable behaviour, not the diff. A typical bug-fix plan:

```json
{
  "schema_version": 1,
  "brief": {
    "text": "wordstat count prints 2 for a two-line file with three words; expected 3",
    "requirements": [
      {"id": "REQ-REPRO", "text": "the original reproduction prints the expected output", "kind": "command"},
      {"id": "REQ-REGRESSION", "text": "a regression test at the public seam fails before the fix and passes after", "kind": "command"}
    ],
    "constraints": ["Keep the CLI usage text unchanged."]
  },
  "repo": {"worktree": "/absolute/path/to/checkout", "base_ref": "origin/main"},
  "authorization": {"endstate": "local", "local": ["edit", "commit"], "evidence": "operator: fix it locally"},
  "host": {"parent_thread_id": "<from orchestrator_capabilities>"},
  "policy": {"checks": [{"name": "unit", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"], "cwd": "/absolute/path/to/checkout"}]},
  "labels": {"workflow": "bug-fix"}
}
```

Replace every value with real ones from this repository; the core rejects unknown fields. Use `base_ref` to name the branch the fix will merge into. Review is required by default. The first available catalog provider other than you reviews the change; if none is available, a fresh child on your own provider does. Repository policy in `.t3-plugins/imps.json` can name a specific reviewer, mark checks repository-required, or forbid waivers.

Use direct mode for almost every bug fix. Delegate only independent pieces, such as a read-only survey of other callers alongside your own fix.

## 5. Implement

When `next` offers `implement`, write the smallest change that fixes the confirmed cause, plus a regression test at the public seam (the CLI, the HTTP route, the exported function), not at a private helper. Run that test once before the fix to watch it fail. Save the output beside `red.log`.

Then record a `result` for the task. The text ends with one fenced block tagged `json t3-result`, in the shape the brief shows. List only files you actually changed, and the commit only if you committed. The core checks both against the worktree.

## 6. Verify

After `transition` to `verifying`, `next` offers:

- `run_check` for each required check. Run it with your native foreground command tool and its own time limit, and save the full output to `args.log_path`. Record it with the action's `args.snapshot`. A failing check returns you to a bounded repair. An infrastructure failure (exit 124, 126 or 127, or a missing tool) is recorded as `unavailable`, never patched around with product edits.
- `accept` for each requirement. For the reproduction, rerun the original command from `red.log` unchanged and save the new output as `green.log`. Record `passed` only if the actual output matches the expected output. Attach `red.log` and `green.log` together as evidence of before and after.

Machine checks come before review. For a PR endstate, `next` first asks you to commit: a pull request carries commits, so evidence is gathered at the committed revision.

## 7. Review and repair

`next` dispatches the review through `delegate_task`. End your turn; T3 wakes you when it finishes. Then record the observation.

- `approve` at the current revision satisfies review.
- `adverse` is kept. `next` offers `repair` (default limit: two rounds per stage, counted across resumes). Record it, fix the findings you can support, and go round again. Every repair invalidates earlier checks, acceptance and review, so all of them rerun.
- `unavailable` advances the reviewer chain, and the report says who ran and why. When the chain runs out, the run blocks: a missing review is never a pass.

If a finding is wrong, say so in the repair result's `findings` with evidence. The next review round sees it. Do not drop it silently.

## 8. Finish

When `next` offers `transition` to `ready` and then `completed` (or `publishing` for a PR), the core has checked every obligation at this exact revision. Before the report, record notes for the handoff:

- `record --kind note` with `{"key": "cause", "text": "..."}`: the confirmed cause, in one or two sentences.
- `fix`: what changed, and why that change and no larger one.
- `before` and `after`: the red and green observations, with their evidence file names.

Then run `report` and show its Markdown. If the run blocked, the report's Blocked section is the answer: what happened, the task IDs, and the exact resume command.
