# Score every design option

Read before dispatching design reviewers and when presenting their scores.

## Roster

Apply the [T3 dispatch preflight](../../agent-tuneup/references/t3-dispatch.md),
then use Neon high and Sol high, one read-only delegate each. Both review every
option from every designer against the base brief and existing baseline. Give
them the option HTML and the coordinator's rendered captures. They must not see
each other's scores before returning. They do not edit, render, delegate or
choose a winner. Record each reviewer's observed model and effort.

If a named reviewer is unavailable or incompatible, substitute Fable high for
that slot. If Fable is also unavailable, use DeepSeek Flash high. This fallback
is explicit: record the substitution and treat direct DeepSeek Flash dispatch as
an exception to the review skill's removal of it from direct review.
If both named reviewers and the fallbacks cannot run, present the options with
the gap marked and report the run as incompletely scored. Do not silently
substitute another model.

## Dimensions

Score every option from 1 to 10 on each dimension; 10 is best.

- **Brief fit** — satisfies the stated requirements, content, states and fixed
  baseline.
- **Usability** — the main task is clear, findable and efficient at the target
  width.
- **Visual craft** — hierarchy, spacing, typography and consistency are
  deliberate.
- **Implementation fit** — uses existing tokens and components without
  disproportionate new complexity.

Do not average dimensions or declare a winner.

## Return

For each option:

- The label.
- One line: `Brief fit n · Usability n · Visual craft n · Implementation fit n`.
- Two or three strengths, one sentence each.
- Two or three weaknesses, one sentence each.

Cite a feature ID where it makes the note concrete. Return one plain-text report
to the coordinator.

## Present

For each option, show each reviewer's identity with its four scores, then its
strengths and weaknesses. Keep Neon and Sol separate; do not merge or average
them. State every substitution and any missing review. The user chooses the
option or a hybrid.
