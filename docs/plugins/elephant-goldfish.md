# elephant-goldfish

Prepare a brief that a fresh session can use.

## When to use it

You know something needs improving but cannot yet give an implementation agent a
clear task. It also checks whether an existing design document is still accurate.

## Try it

After [installation](../getting-started.md), run in your terminal:

```sh
t3-plugins prompt elephant-goldfish doctor
```

Paste the printed line into a T3 thread attached to your project. Once readiness is
clear, generate a task prompt:

```sh
t3-plugins prompt elephant-goldfish thinking retry-policy
```

Paste that output into T3. Replace the sample task or path with your own.
If you installed [skill adapters](../slash-commands.md), select **t3-elephant-goldfish**
from `/` and append the same request instead.

## Operations

`doctor`, `thinking`, `elephant`, `check`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/elephant-goldfish/entry.md) names the file to load for each operation.

## What you get

Local `thinking/<topic>/discovery.md`, `spec.md`, `handoff.md` and a provenance
manifest. Discovery records decisions and unknowns; the specification gives stable
requirement IDs and observable acceptance criteria. The handoff copies the source
verbatim with hashes. The agent presents refined discovery for your review before
finalising the rubric. Your acceptance is recorded against that content's hash;
editing discovery reopens review. A complete handoff still needs a separate instruction
to start implementation or research.

## Review and drafts

`thinking list` and `resolve` show `discovery_review` and a reason when acceptance
evidence is missing, malformed, or stale. Old topics need review too. A review
receipt stores your actual statement and its source reference, with scope
`finalise-brief`. It records evidence, not cryptographic proof of human intent.
An explicit owner override records `owner_override` for that same scope. It does
not claim acceptance or grant implementation authority.
The review command accepts a statement file or literal stdin so shell calls do not
interpolate your words. Topics with unreadable metadata or artifacts appear individually
at `topic_repair` in `list`; other topics remain visible.

You can ask for an incomplete draft or stop the interview at any time. Draft specs
carry `<!-- thinking:draft -->` and a visible non-executable label. The renderer's
`--draft` option writes `handoff.draft.md` and `handoff.draft.manifest.json`, without
an execution prompt. Draft output never completes a topic.
Standalone draft markers or labels below a heading also hold final readiness.
Quoted and code-fenced examples stay inert. Finalise a draft discovery before review.
Use the exact unindented standalone comment as the machine-readable status for incomplete
discovery and specs; styled headings or labels cannot replace it.

The final renderer and `thinking_state.py gate <topic> --require discovery,spec,handoff`
enforce current review/readiness. `render_handoff.py <topic> --check` verifies saved
source/output hashes only. Provenance does not establish approval or permission to
execute. After source changes, review discovery again if needed and re-render.
Final readiness also binds the handoff to its render-time review receipt. Replacing
acceptance with an owner override, or changing the recorded evidence, requires re-rendering.

Requirement changes such as "switch to the official API" refine the brief. Resumes,
scheduled reminders, and unrelated production authorisation keep the thinking
boundary. A clear request to leave thinking records the request and authorised scope
before execution. Named licence, budget, identity, credential, and authorisation
blockers retain owners and next actions; dependent work waits for resolution.
`has_execution_request` makes a saved transition visible. The agent-writable record
is unvalidated context; an implementer must inspect the actual user instruction.
The flag is `null` when malformed metadata makes the saved request unknowable.

## Jobs and workers

Discovery is never delegated: a worker cannot hear you. `doctor`, `thinking list`,
`resolve` and `render_handoff.py --check` stay direct. Delegated checks use two
workers:

- `elephant-goldfish/factual-checker` verifies repository and command claims.
- `elephant-goldfish/cold-reader` sees only the document and says whether a newcomer
  could act on it.

Factual and cold-read verdicts are separate stages with separate validator receipts.
New topics allow four cold-read rounds in total; older topics keep their recorded
limit. Another round, an owner override or leaving thinking is asked through the
question picker.

## Limits

Thinking stops at the handoff. A cold-reader pass establishes readability and completeness, not factual correctness. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
Helpers check receipt structure, content binding, and provenance. They cannot judge
interview quality, authenticate an operator statement, or prevent every unauthorised
agent action.

## Continue planning

Use `thinking retry-policy` again to resume the same topic, or `thinking list` to
inspect saved topics. `elephant` checks a durable design document against repository
facts and runs a separate cold-reader review; `check` runs the factual drift check.
A readable brief can still be factually wrong, so those verdicts stay separate.
GitHub publication is optional and requires explicit authorization.
