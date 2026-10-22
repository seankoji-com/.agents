# Briefs, first impressions and isolated journeys

Used by `run` and `resume` for participant slots. The helper is
`python3 PKG/scripts/evidence.py`; shapes are in `PKG/references/evidence-contract.md`.
It decides nothing about live provider or browser behaviour. It checks the host
evidence you give it.

## Briefs

Build each participant brief with `evidence.py brief` (`revision`, `cell_id`,
`stage`, `task_id`). It contains only that persona, the approved material as data,
neutral goal-based tasks, the expected payload and fixed boundaries. It never
contains other cells, the owner's decision, source code or a backlog. Never edit a
brief. `job-spec` accepts only recorded, unchanged briefs, and `check-brief` lints
any other text. A lint pass is not sandbox enforcement.

For the no-job route, explicitly grant read access to the generated document and
its listed hash-bound material paths before dispatch. The child returns the
payload path and SHA-256 for `record-acceptance`; it has no prepared JSON brief or
generic worker-result transport. The same payload and host-evidence checks apply.

Each first impression and each journey is a fresh T3 child (`delegate_task`). It is
never a follow-up, never a message to an existing thread, and never the child of another cell or
stage.

## First impressions

1. Dispatch the first-impression brief unchanged. For a generic job, dispatch its
   prepared JSON brief and have the child read the hash-bound `context_files`.
   Without a job, use the explicitly granted material paths above. Read the
   initial viewport first, and derive image delivery (`delivered`, `not-delivered`
   or `unknown`, with its source) from host read receipts. Attachments are neither
   required nor a substitute for those reads. Missing receipts leave delivery
   unknown.
2. Optionally run `evidence.py check-payload` as an advisory pre-check. Then run
   `lifecycle.py ingest` (see `PKG/playbooks/run.md`) with the image-delivery
   evidence. It reaches the only acceptance boundary (`study.py
   record-acceptance` exposes it only without a job): it reopens the exact result, scans it,
   validates it and freezes it in one step. A check-payload pass is not a receipt.
3. `evidence.py freeze-first` only verifies the frozen record. It refuses any
   payload other than the exact accepted result.

The frozen record keeps the initial-viewport reaction apart from the walkthrough.
A text-only response cannot support a visual claim. A later response never
replaces a frozen first impression. Call it a simulated first impression, never a
measured human five-second result.

## Isolation

Before any journey, inspect the participant child's current tools. Save the
child's tool observation and run `evidence.py select-mechanism`. T3 preview tools
are preferred. A provider-native browser is eligible only when the host exposes
and verifies its cell-bound state. The plugin installs no browser runtime,
automation library or broker.

For the cells to be bound, run `evidence.py probe-plan`. Run every `write`
snippet in its own cell context, then every `read` snippet, and keep each reading.
The probe covers cookies, localStorage and sessionStorage at the target origin.
Never clear storage or a shared profile. Then run `evidence.py bind-context` for
each cell with its child tool observation, context reference and boundary. Add the
host's assignment evidence: a host-enforced binding or a host trace, with its
receipt hash. A new tab in a shared profile is not isolation. Without host
evidence that the child uses only its context, the journey is unavailable. After a
resume, bind again; a changed context needs a fresh probe and a new brief.

`evidence_class: fixture` comes from invented or loopback data and binds only a
`fixture` target. Only a real host mechanism receipt with child-context binding
supports a live isolation claim.

## Journeys

Once the first impression is accepted and a binding is verified, build the journey
brief. Goals that need credentials are gaps before dispatch. The child drives its
own browser in its assigned context; never drive or relay a journey yourself.
Before an interaction you control, `evidence.py check-action` refuses excluded and
credential actions.

Before ingesting a journey, view every screenshot it cites. Record what you saw in
`material_inspection`. `record-acceptance` then reopens every cited file (text,
event log, screenshot) in the task scope and checks its hash. It scans each file
whole and binds it to the accepted record. An oversize, non-UTF-8 or non-PNG file
is refused, not cleared. Suspected secrets, cookies, headers or credentials
quarantine the attempt, and their values are never shown. `accept-journey` only
verifies the bound evidence.

When a cell has no browser tool, an unbound or unverified context, or only
credential goals, its journey is a visible gap. Its capture results stay. Check
`evidence.py coverage`; it never reports a combined study complete.

## Traces

When the host exposes a child's tool trace, run `evidence.py inspect-trace` before
`lifecycle.py ingest`. Name the execution exactly: its `task_id`, admitted
`request_id`, generated brief, host task ID and result. The child may read only its
exact hash-bound prepared JSON brief (when present), generated Markdown document, approved pack
files and its own task directory. A journey gets its
earlier response through its brief, never by reading the first task's directory.
Every explicit path an event names is checked, whatever the tool. A shell command
or an unknown tool is opaque: paths it names inside the study are checked, but the
trace stays `unverified`, never clean. One host task runs one execution in the
whole study; a host task reported for two requests contaminates both.
A contaminated execution is kept and never accepted; a later clean trace does not
clear it. A trace found after acceptance stops that record's use and disclosure,
and that of any journey built on it, without rewriting anything. Retry with a new
request and host task, which is judged on its own trace even if it returns the same
bytes. To recover a filled slot, plan a new revision: `coverage` and `disclosure`
then use only that revision's records, its written carry mapping and the first
impressions their journeys name. Without a trace, compliance is `unverified`, not
enforced and not clean.

A goal record is an attempted route: at least one step, with step times inside the
journey's start and end and never running backwards. An achieved or partial goal
also needs an observed event or evidence file. Record a goal the child never
attempted as a gap.
