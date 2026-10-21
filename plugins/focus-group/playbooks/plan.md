# Plan a study

`plan` prepares one exact, approvable revision. It writes only study records under
the private job root. It never prepares a brief, calls `delegate_task`, schedules
anything or changes the product.

## 1. Record the brief

Write a draft from `PKG/templates/study-draft.example.json`. Record the intended
audience, the decision the study should inform, the target URL or supplied pack,
the target environment (`fixture`, `staging` or `live`), the permitted journeys and
actions, excluded actions and exclusions. Excluded actions become gaps, never
attempted transactions. Credential entry is unsupported.

For `plan <study>`, start from the current revision's draft. Change only what the
operator asks for.

## 2. Suggest an editable panel

Save a fresh `orchestrator_capabilities` response, then:

```sh
python3 PKG/scripts/study.py suggest --input draft.json --capabilities caps.json
```

Write four invented personas yourself, each with one goal, priorities, relevant
experience and constraints, marked `invented: true`. Describe one person; for a
time-poor parent, say what this parent needs, not what parents want. The helper
refuses a few common phrasings of a group preference ("all parents want",
"parents always prefer", a clause opening "Parents want"); it is a narrow lint, so
read every persona yourself. `suggest` fills
missing participant models with the first runnable model of the first two known
catalog lineages, the analyst with the first participant model, and the reviewer
with a model of a different known lineage. It writes nothing. Show the operator the
panel and let them edit personas, models and options, the capture profile and
limits. If the operator picks models from one lineage, keep the matrix and show the
reduced diversity.

## 3. Capture, validate and inspect material

Combined mode requires a URL target for live journeys. For a supplied pack target,
choose `capture-only`; the helper refuses a combined pack-target plan before creating it.

Plan-time capture is read-only and happens before approval. Follow
`PKG/playbooks/capture.md`: capture in a safe context or take a supplied pack, look
at every image and text file yourself, and validate the pack with
`evidence.py pack`. Copy its `stimulus` into the draft and set
`coordinator_inspected: true` only after you have inspected everything. Approval
is refused until the pack is `cleared` and matches the draft exactly. Never use a
personal or saved browser profile.

## 4. Set limits and sharing

Record `max_concurrency`, `max_attempts_per_slot`, `participant_repairs`,
`analysis_repairs`, `review_repairs`, the UTC `deadline` and whether a hard runtime
stop is required. Record one sharing grant per provider instance with its consumers
(`participant`, `analysis`, `review`) and material classes (`stimulus`, `persona`,
`participant-response`, `journey-evidence`, `analysis-report`). Ask the operator
which provider instances may receive each class; do not assume.

## 5. Present the revision

```sh
python3 PKG/scripts/study.py plan --state-root ROOT --study ID --input draft.json \
  --capabilities caps.json [--observations observations.json]
```

`--observations` lists capability facts you read from tool schemas before dispatch
(`image_delivery`, `browser_tools`, `isolation`, `hard_stop`, each `available` or
`unavailable` with its source). Never record `verified`; only a pilot verifies.

Show the operator, without paraphrasing the numbers:

- the revision hash and every cell with its persona, provider, model, options and
  pilot flag, plus the analyst and reviewer targets;
- the complete first-attempt and maximum task counts, including pilots (which
  occupy normal cells), every participant stage, one analysis stage, fidelity
  review and each repair pool. Eight combined-mode cells need sixteen participant
  attempts before analysis and review;
- the expected mode (`combined`, `capture-only` or `blocked`), journey tasks that
  depend on unknown capability, and every limitation;
- diversity, reviewer independence and sharing gaps;
- for a revision, `carry_forward` entries and `budget_change`.

Counts are synthetic tasks, not a human sample size, and a task ceiling is not a
dollar cap.

## 6. Obtain approval

If the revision is `blocked`, revise it; approval is refused. Otherwise, if no
recorded approval already covers this exact revision, ask through the native
question picker with the recommended option first. Use the helper's
`approval_instruction` as the approving option label, so the instruction names the
revision and its ceiling. Save the verbatim answer to a private file outside the
job directory and record it:

```sh
python3 PKG/scripts/study.py approve --state-root ROOT --study ID --input approval.json
```

`approval.json` holds `revision`, `message_ref`, `statement`, `source` and
`source_sha256`. The statement must be exactly the instruction. Save only the
owner's single answer as the source: one line, `Selected option:`, `Answer:` or
`Reply:` followed by exactly the instruction, or the instruction alone. Do not save
the question or option list with it. A rejection, negation, quotation or
qualification is refused. Any other content, such as a second answer, a condition
or a cancellation, is refused as ambiguous. If the owner's reply adds anything to
the selection, ask again; never trim it to the approving line. The helper also
checks that the material is unchanged and inspected, and that sharing covers every planned consumer. A raised
repair pool is covered only by an approval of the revision that raises it; charged
counters are never reset.

When `plan` shows an earlier approval as `insufficient`, charges made under
another revision have raised this revision's ceiling past what the owner approved.
Ask again with the new `instruction`; the helper appends an amendment and keeps the
earlier approval.

Stop after approval. `run` is a separate operation.
