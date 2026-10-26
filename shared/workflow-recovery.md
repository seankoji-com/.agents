# Stop workflow repairs from replacing the task

The coordinator owns progress towards the user's requested outcome. A helper fix,
new review, metadata revision or green transport check is workflow work; report it
separately from the requested implementation, artifact or live result. Do not infer
cost from review counts. Report monetary spend/tokens as unknown without host data.

## Checkpoints and detection

At the first plan, name the next concrete task artifact and its verification, and
the existing time/spend/attempt bound. If no time or spend bound was supplied, do
not invent owner consent or ask a new budget picker: set a checkpoint before a
second workflow-only repair. Check this checkpoint on every repair/resume and
before another delegated review. Reuse the current evidence instead of restarting.

Stop automatic repair/review dispatch when any of these occurs:

- two consecutive workflow-only repairs produce no new task artifact or accepted
  task stage, even if each failure has a different message or metadata hash;
- the same relevant brief/evidence produces the same validator failure twice;
- the retained planning progress diagnostic recommends a stop;
- a task's existing time, spend or attempt bound is reached, or its next milestone
  cannot be reached within the remaining bound.

These are coordination stops, not permission to cancel unrelated work or erase a
gate. Reconcile task-owned live/uncertain children first. An operator-requested
status check stays read-only. Stop recommendations are heuristics, not validators
or proof that a changed plan has made implementation progress.

For a planning job, run the pinned helper (same package and state roots):

```text
python3 PKG/shared/planning_review_cli.py progress --input caller.json --state-root ROOT --job ID
```

`caller.json` has the shape `{"caller": {...}}`, wrapping the original caller.
The read-only projection shows
the persistent content/technical counters, consecutive incomplete rounds (including
different errors), unchanged authored content without complete approval, consecutive
unavailable attempts, latest errors and outstanding owned work. `finish` returns
the same diagnostic. It is always `acceptance: false`; warnings grant no retry,
release, scope change or extra round. The ledger has no delivery or spend telemetry.
Use normal receipt validation even when it recommends inspecting an existing pass.
Jobs pinned before this command shipped must keep their original helper: use the
retained receipt's `round_history`, counters and these checkpoint rules manually.
Do not run a newer acceptance helper against old pins or rewrite the pinned job.

## Prevent the format failure before it spends another round

Use the existing [planning draft check](planning-review.md#draft-diagnostics-before-completion)
inside the active reviewer execution, with at most one correction. Declare the
pinned helper and every separately opened procedural/source input before capture.
The assigned immutable brief and own task-subtree draft/diagnostic files are
contract/outputs; do not put them in the additional factual-read list. Keep actual
separately opened source/helper reads disclosed. A failing draft check must never
be "fixed" by hiding an unexpected read, suppressing a finding or changing criteria.

Once terminal, a review stays immutable and counted. An incomplete assessment is
not provider unavailability. Do not edit its result, refund its round, follow up in
the same child thread, switch reviewers for approval or create a replacement job
to reset the subject. A fresh review still needs a changed, tested approach and
existing authority/budget. No checker output itself accepts the review.

## Recover once, or return control

Give the operator a short accounting before proposing more work: requested outcome
and artifacts actually delivered; workflow-only attempts and remaining counters;
the concrete root cause; evidence gaps; and the smallest next action. Preserve all
findings/severities and original receipts. A minor deferral is not a new review loop.

Prefer one bounded correction when the cause is known and the correction fits the
existing authority/budget. Prove the diagnostic or fixture now catches that cause
before spending a fresh review. Explain what changed, what will be reused and what
observable result ends the attempt. A new wording of the same failure is no change.
Do not make "raise the limit" the default recovery; if a real increase is needed,
present a concrete proposal and alternatives, retaining the original counters.

Never silently expand the task into repairing, reviewing, merging and installing
the workflow itself. A helper repair requires its own authority and bound. After
one such repair, return to the original milestone; another infrastructure repair
without task progress triggers this stop rather than a nested repair chain.

If the owner pivots away from the workflow, stop/reconcile owned work and use the
existing `finish`/`release` or cancellation path as applicable. An unfinished
substantive round must finish before release; a technical-only stop uses the
existing release rules. Retain the old run as incomplete/unaccepted with its
receipts, counters and resume path. A new execution approach does not reset that
logical subject, waive requirements, grant deployment authority or make old checks
current. Independent review and the repository's checks still apply to delivery.
