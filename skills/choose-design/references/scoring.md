# Score every design option

Read before dispatching design reviewers and when presenting their scores.

## Roster

Apply the [T3 dispatch preflight](../../agent-tuneup/references/t3-dispatch.md),
then choose among these subscription routes with the preflight's provider score,
one read-only delegate per seat:

- **Neon** — an Antigravity Neon route, `thought_level: high`.
- **Sol** — Codex `gpt-6.2-sol`, `reasoningEffort: high`.

A paid API-credit alias for either seat needs the user's explicit acceptance.
Both seats review every option from every designer against the base brief and
existing baseline. Give them the option HTML and the coordinator's rendered
captures. They must not see each other's scores before returning. They do not
edit, render, delegate or choose a winner. Record each reviewer's observed model,
route and effort.

A seat is complete only when it returns a scorecard for every option. If a seat
cannot start or cannot complete every option, substitute Fable high on the
Claude route (`claude-fable-5-2`, `effort: high`) for that seat. If Fable is
unavailable or also incomplete, use DeepSeek Flash high on the OpenCode route
(`litellm/deepseek-v4.1-flash`). Record every substitution. If either seat is
incomplete after its fallbacks, present the options with the gap marked and
report the run as incompletely scored; the user must accept that gap before the
comparison counts as complete. Do not silently substitute another model. Treat
direct DeepSeek Flash dispatch here as an explicit exception to the review
skill's removal of it from direct review.

## Sharing

The invoking request names this roster and authorises the base brief, option HTML
and rendered captures needed to score the designs. Send only that packet. Redact
secrets and unrelated private data; never attach raw repository files or private
screens beyond the approved brief. Fallbacks receive the same packet under the
same authority. If the permitted material is insufficient for a seat to score an
option, leave that seat incomplete and report the gap rather than widening
sharing without the user's acceptance.

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
