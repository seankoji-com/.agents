# elephant-goldfish

You know something should change, but you can't yet hand an agent a clear task.
elephant-goldfish interviews you, writes down what you decided, turns it into
acceptance criteria, and packages a brief that a fresh thread can execute. It never
starts the implementation. It can also check whether an existing design document still
matches the repository.

Factual and cold-read slots set `independent_of_author: true`. Their review lineage
must be canonical and differ from every author recorded for the document SHA-256.
When authorship or lineage is unknown, the job stops because independence cannot be checked. A known same-lineage fallback needs a hash-bound
`lineage-waiver`; it waives no requirement. New jobs require verified host identity
for the reviewer, subject and author-independent slot. Legacy jobs without the
identity policy marker retain target-only acceptance semantics.

Record discovery and spec authors with `thinking_state.py author` using a fresh
`orchestrator_capabilities` file. Render handoffs and repair documents with the same
`--capabilities FILE` input. Handoff authorship includes the renderer and both source
hashes; missing source records remain unknown. `check` is read-only and never records
the checker as an author. `elephant-goldfish/check` imports authors only for a matching
document hash. Its factual slot must name the validated stage document. When authors
are known, its factual worker needs verified identity and a different lineage, even
when the slot lists other subjects. Unknown additional subjects preserve the
requirement and fail closed. If hashes differ or authors are missing, the report says
author independence is unverified. A direct check with unknown authorship may proceed
read-only but cannot use a waiver to establish missing authorship. A direct factual
authoring stage stays blocked when authorship is unknown.

Plan revisions re-import authors and retain the job's existing author records.
The sidecar order rule applies to records in the same directory. Copies or moves across
directories and unrecorded edits are outside the trust boundary. Once enabled, author
independence cannot be disabled by plan revision.
A first record cannot identify earlier authorship for an unrecorded document. Author
records are host evidence transcribed by the coordinator, not proof of freshness.

A zero-slot factual fallback under `elephant-goldfish/elephant` sets stage
`independent_of_author: true` and records each direct execution from fresh capabilities.
Acceptance requires known authorship and an owner
`lineage-waiver:stage:<stage-id>` decision bound to the latest executor, document hash
and stage contract. Resuming under another model needs a replacement decision. Report
`fallback: direct, same-lineage (waived)`. Adding, removing or changing either stage
field through `plan-revision` also needs an owner decision.
A direct cold-read stage cannot fall back to the coordinator; acceptance refuses it
and keeps `R-COLD` blocked until a separate reader completes.

## Try it

In a T3 thread attached to your repository:

```text
$t3-elephant-goldfish thinking retry-policy
```

`retry-policy` is the topic name; use your own. The agent asks questions until the
problem is clear, shows you the refined discovery to accept, then writes the
specification and handoff. Run the same command later to pick the topic up again, or
`thinking list` to see saved topics. Send `$t3-elephant-goldfish doctor` first on a new
machine or provider.

## What you get

Files under `thinking/<topic>/` in your repository:

- `discovery.md`: decisions, constraints and open unknowns;
- `spec.md`: requirements with stable IDs and acceptance criteria you can observe;
- `handoff.md`: the source documents copied verbatim, with their hashes, plus a
  provenance manifest.

Your acceptance of the discovery is recorded against that content's hash, so editing
it reopens review. A finished handoff still needs a separate instruction before anyone
implements or researches it.

Two other operations check durable documents. `elephant` checks a design document
against the repository and has a separate cold reader judge whether a newcomer could
act on it. `check` runs only the factual drift pass. A readable document can still be
wrong, so the two verdicts stay separate.

## Operations

`doctor`, `thinking`, `elephant`, `check`. The
[entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/elephant-goldfish/entry.md)
names the file the agent loads for each one.

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

Thinking stops at the handoff. A cold reader's pass means the brief is readable and
complete, not that its facts are right. The helpers check receipt structure, content
hashes and provenance. They can't judge the quality of the interview, authenticate
who accepted a review, or prevent every unauthorised agent action. Unit tests don't
show how a given model behaves; see [compatibility](../compatibility.md). Publishing
anything to GitHub needs explicit permission.
