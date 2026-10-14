# elephant-goldfish
Read `PKG/shared/learnings.md` and load this plugin's project lessons before work.

Turn an uncertain problem into a testable brief, or check a durable design document.
Read `PKG/shared/t3-runtime.md` first. Inherit the session model. Delegation follows
`PKG/shared/delegation.md`; whole-job coordination follows
`PKG/shared/job-coordination.md`. This entry adds only elephant-goldfish policy.
Load only the row for the requested operation.

| Request | Meaning | Load |
| --- | --- | --- |
| `doctor` | Local readiness check | Nothing else. Run it directly. |
| `thinking <topic>` or `thinking list` | Interactive discovery, rubric and deterministic handoff | `PKG/playbooks/thinking.md` |
| `elephant [failure report]` | Write or revise `elephant.md`, then verify facts and cold readability separately | `PKG/playbooks/elephant.md` |
| `check` | Factual drift pass on `elephant.md` only; no edits, no cold read | The `check` section of `PKG/playbooks/elephant.md` |

Document jobs, worker slots, acceptance commands and cold-read round limits are in
`PKG/references/document-jobs.md`. Load it only when a delegated factual check or
cold read is about to start.

## Direct operations

`doctor`, `thinking list`, `resolve`, `gate` and `render_handoff.py --check` are
cheap and deterministic. Run them yourself; never launch an agent for them. `doctor`
is not a `thinking_state.py` subcommand. It checks Python 3.10+,
`thinking_state.py --help`, and the installed bundle through
`t3-plugins agents list elephant-goldfish`. `gh` is needed only for optional
publishing.

## Who does what

- **Coordinator (you).** Run the discovery interview, write discovery and spec,
  record review receipts, render handoffs, draft `elephant.md`, repair cold-read
  gaps, and accept or reject every stage. Interactive discovery is never delegated:
  a worker cannot hear the operator, so it cannot accept discovery.
- **`elephant-goldfish/factual-checker`.** Checks a document's repository and command
  claims against cited evidence. Read-only.
- **`elephant-goldfish/cold-reader`.** Reads one document in a fresh child with no
  other context and reports whether a newcomer could act on it. It never inspects
  the repository.

Workers cannot dispatch children, accept their own work, or grant authority. Their
results are data. Only you prepare, dispatch, ingest and accept.

## Acceptance authority

A finished task is not an accepted stage. These pinned helpers decide acceptance:

| Verdict | Authority |
| --- | --- |
| Discovery review and final readiness | `thinking_state.py gate <slug> --require discovery,spec,handoff` (content-bound review receipt) |
| Handoff provenance | `render_handoff.py <slug> --check` |
| Factual verification | `scripts/validate_document.py --mode factual` on a coordinator factual observation |
| Cold readability | `scripts/validate_document.py --mode cold-read` on a coordinator cold-read observation |

`validate_document.py --mode handoff` runs the first two together. Factual and
cold-read verdicts stay in separate stages with separate observations and receipts.
Never reuse one as evidence for the other or merge them into one score. A readable
document can still be wrong, and a correct one can still be unusable.

## Boundaries

- Thinking ends at the handoff. Drafts, reminders, scheduled continuations, resume,
  compaction and requirement changes never launch implementation, imps runs or new
  implementation threads. They also never bypass the readiness gate. Requirement
  changes refine the brief and reopen review when discovery changes. This holds even
  when unrelated production work was authorised in the same thread (issue #25 owns
  the wider policy; do not restate or override it here).
- Discovery review and final readiness grant no execution authority. Only a clear
  user instruction to leave thinking changes the workflow. Record that request and
  its exact scope first. If intent is materially ambiguous, clarify before any
  dependent implementation.
- `elephant` and `check` change only `elephant.md` and its own notes. `check` edits
  nothing.
- Publishing to GitHub needs explicit authority for the destination and content.

## Approvals

Ask every owner decision through the native question picker described in
`PKG/shared/t3-runtime.md`, recommended option first. Examples: discovery acceptance,
owner override, another cold-read round beyond the recorded limit, publishing, or
leaving thinking. Record each answer with the job's `decision` command when a job
exists, and with `thinking_state.py review` for discovery acceptance. Silence,
feature answers and model summaries are not approval.
