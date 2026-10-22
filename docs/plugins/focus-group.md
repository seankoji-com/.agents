# focus-group

focus-group tests a product or prototype with a small panel of invented personas
across several models. Each persona has its own goal, priorities, experience and
constraints, and works in a fresh task without seeing the others. The answers are
synthetic product-use hypotheses: useful for deciding what to fix, build or keep,
never evidence of what real customers want or how many of them want it.

!!! note "Experimental"
    focus-group is not in a release yet. It plans studies, records approval of each
    exact revision, enforces limits and data sharing before any task starts,
    validates the shared material, pilots each model, recovers interrupted runs from
    what T3 recorded, and turns accepted evidence into a reviewed report and local
    issue drafts. It has been checked with invented fixtures and a relocated install,
    not with a live study. Whether a given model can view images or drive a browser
    is still a live check.


Before substantive planning or execution, choose the planner, each participant
model, the analyst and reviewers together. The exact study revision needs a real
planning-review receipt before owner approval or panel work. Changed revisions
reopen that review while retaining prior findings, budgets and unchanged evidence.
Explicit resume shows pinned choices and asks retain-or-stop.

The final report retains its separate fidelity gate: a fresh reviewer of a
different known lineage checks the exact bundle against accepted inputs, citations,
counts, omitted contradictions and dissent. That stronger existing gate is the
operation matrix's concrete exception to a duplicate final planning assessment.
It cannot be relabelled as a planning fallback pass.

## Try it

```text
$t3-focus-group plan https://staging.example/welcome first-run experience for busy parents
```

Other forms:

```text
$t3-focus-group plan pantry-planner-onboarding
$t3-focus-group run pantry-planner-onboarding
$t3-focus-group resume pantry-planner-onboarding
$t3-focus-group status pantry-planner-onboarding
$t3-focus-group cancel pantry-planner-onboarding
$t3-focus-group doctor
```

`plan`, `status` and `doctor` never start a task. `plan` with an existing study ID
proposes a revision and shows which accepted results carry forward. `doctor` also
checks the installed package against its install receipt: file digests, the worker
bundle and which prefix owns them.

## An invented example

Pantry Planner is a made-up meal-planning prototype used in this guide and in the
tests. The study `pantry-planner-onboarding` asks one question: should the first
screen ask for dietary needs before it shows any recipes? The audience is people who
plan weekly family meals on a phone.

1. `plan` proposes four invented personas on two model lineages from T3's live
   catalog: eight cells, sixteen participant tasks if journeys run. You cut it to
   two personas, a time-poor parent of two and a student cooking on a tight budget,
   and change the student's priorities. That is a new revision with its own hash.
2. The agent captures the welcome screen, two more views and the page text in a
   fresh anonymous browser context, then inspects them. A page that shows anything
   resembling a secret or personal data is held back until a cleaned copy is made
   and approved.
3. You approve the revision through the question picker: "Approve focus-group
   revision 1a2b3c4d5e6f (ceiling 14 tasks)", with your own revision's hash and
   ceiling. Nothing has started yet.
4. `run` pilots each model with its first cell. Once a pilot's answer is accepted,
   that model's other cells run. Each cell gives a first impression from the
   captures, then tries the journey "plan three weeknight dinners" in its own
   browser context.
5. An analyst model writes the synthesis, a reviewer from a third lineage checks
   it, and the export lands in a folder you choose. In the fixture run, one persona
   could not find "add to plan" below the fold. That blocker outranks a colour
   complaint three cells shared, and the reason is printed beside it.

## Decisions you make in `plan`

The plan records each of these before anything runs, and shows them again with the
revision hash:

- **Target.** A URL or a supplied capture pack, and whether it is a fixture,
  staging or live environment. Captures happen in a fresh anonymous context, or in
  an isolated test context that already holds a test login. The agent never uses
  your own browser profile and never types credentials.
- **Actions.** The journeys and the actions each may take, such as "browse recipes"
  and "add recipes to a plan", and the ones it must not, such as "create an account"
  or "place a grocery order". An excluded action becomes a gap in the report.
- **Models.** One model per cell column, plus the analyst and the reviewer. The
  reviewer's lineage must differ from every author of the synthesis. An explicitly
  selected runtime mode stays bound to the target and report request; changing it
  needs a new reviewed revision and approval. An unreported observed mode stays
  unknown, and modes of one model do not count as different models.
- **Sharing.** Which provider instance may receive which material: the captures,
  personas, participant answers, journey evidence and the report. A task whose
  provider lacks the grant is refused before it starts.
- **Limits.** Concurrency, attempts per cell, the participant, analysis and review
  repair allowances, and a deadline.

One approval covers one exact revision. If an existing approval already covers the
same inputs and actions, `plan` reuses it and does not ask again. Updating the run's
task list to follow an approved revision, or adding a journey slot that revision
already declares, is recorded under that existing approval. Anything that adds
headroom, such as a higher limit or a new provider grant, is a new revision and
needs your approval.

## Edit the panel before it runs

The agent suggests four invented personas across two model lineages taken from T3's
live model catalog. You can change the personas, the models and their options, the
common capture profile (a phone viewport by default) and the limits. A persona
describes one person. "A parent with ten minutes before school pick-up" works;
"parents want fewer taps" is refused, because a persona cannot speak for a group.
The check catches a few common phrasings like that one, not every group claim, so
the agent still reads each persona.

If you pick models from a single lineage, the plan says so. Those are different
models, not independent model families. A model, provider or option that is missing
from the catalog stops planning; the agent never swaps in another one.

## What the plan shows

Before you approve, the plan shows:

- every cell (one persona on one model), and the analyst and reviewer models;
- the task ceiling: for eight cells in combined mode, 16 participant tasks, one
  analysis and one review, plus the repair allowances you set;
- the expected mode: combined, capture-only, or blocked;
- what is still unknown. Image delivery, browser tools and isolation stay
  "unknown until pilot" until a pilot proves them;
- which provider may receive which material, for participant, analysis and review
  work.

You approve one exact revision by its hash and ceiling, by choosing the approving
option itself; a rejection or a quoted instruction is not approval. If you add a
condition or a change of mind to your answer, the approval is held and you are
asked again. Any later change to the personas, models, material, prompts, journeys,
sharing or limits is a new revision. If you return to an approved revision after
other work has been charged, its ceiling may have grown, and you are asked to
approve the new ceiling. A task ceiling is not a dollar cap; cost is reported as
unavailable.

## Combined and capture-only results

A combined study has two stages per cell. The first impression comes from the
shared captures: every cell sees the same files at the same viewport. The journey
is hands-on: the participant's own task drives a browser context bound to that
cell, and the agent never drives or relays it.

Journeys need browser tools in the participant's task and a context whose cookies,
local storage and session storage are verified as separate from every other cell's.
A new tab in a shared browser profile does not count. When a model lacks either,
its cells still give first impressions and its journeys show as gaps. You can then
revise the study to capture-only: accepted first impressions carry forward, journey
results are set aside, and the report says the combined study is incomplete. A
capture-only result never counts as a completed combined study.

## Limits and deadlines

Concurrency, attempts per task, the participant, analysis and review repair
allowances, and a deadline are set before anything runs. Resume, replacement and
repair draw on the same allowances, and nothing resets a used count. No task starts
after the deadline. Tasks still running at the deadline are cancelled at the next
wake or resume, and stay listed as pending until T3 confirms they stopped.

## Pilots, model identity and interruptions

Each participant receives the approved capture files through exact paths and
SHA-256 hashes in its prepared brief, with explicit read authority. Missing or
changed local material blocks admission before another attempt is charged.
Generated instructions state the payload types and distinguish the study document
hash from the outer result's brief correlation. The trace check permits those two
exact briefs and the approved pack; it still rejects other participants' evidence,
unrelated job files and product source. Shell commands remain opaque.

Image delivery needs host evidence. A successful OpenCode image-read receipt can
verify delivery; missing receipts stay unknown. Codex activity that omits image-view
events cannot verify image delivery. Text-only answers may be retained with that
limitation and cannot support visual claims.

Each model's first cell is its pilot, and it counts as a normal cell. That model's
other first impressions wait until the pilot's answer is accepted and the host
reports the model you asked for. Its other journeys wait for its pilot journey,
which needs browser tools and a verified, separate browser context. A model whose
journeys are unavailable still gives first impressions; the journeys show as gaps.

The model you request and the model T3 reports are recorded separately. A missing,
different or unrecognised model is shown beside the cell and does not count as
verified. That holds even after the answer is accepted: if T3 later reports a
different model for the same task, the cell and any journey built on it stop being
used until you decide. You can accept that exact difference: you see every
provider and model pair T3 reported for the task, including conflicting reports, and
your answer must name all of them. The cell then shows the difference wherever it is
used and never carries into a later revision. A further report that pairs a provider
and model differently, or changes which one T3's status names, needs a new decision;
your earlier answer no longer matches. If T3 never reported a complete provider and
model, the cell stays on hold with the missing part shown. A model from one report is
paired with a provider only when T3's status report names that provider, following
the shared identity rules.

If a run is interrupted, `resume` first reads what T3 recorded for every task, then
lists only the cells that still need work. Accepted cells and running tasks are not
started again, a lost dispatch response is retried under the same request, and used
allowances are not reset. A new attempt for a cell waits until T3 confirms the
previous one ended. A task that says it is done but still has running child work, an
unanswered question or an unconfirmed cancellation keeps the study open. A provider
that fails mid-task is recorded as a provider failure, not as product friction, and
a retry comes from the repair allowance.

After a workflow fix, an existing study still pins its original package. Package
recovery uses an explicit, owner-approved upgrade with exact old-state and new
package hashes, followed by an approved study revision and job revision. An
exhausted pilot also needs headroom in both its per-slot limit and shared repair
budget before a charged retry. The installed run playbook describes the sequence.
Earlier transports, trace verdicts, charges and approval history stay on record;
installing an update never resets them or accepts a rejected response.

## Reading the evidence

A delegated analyst model writes the synthesis from accepted evidence only. Its task
can read exact copies of the approved screenshots, page text and journey notes, and
nothing else. A fresh reviewer from a different model lineage gets the same files and
checks the synthesis before the report counts as reviewed. An adverse review keeps
the report unreviewed until its findings are answered and a new round approves. If
the agent edits a finding, it becomes an author too, so the reviewer must differ
from it as well.

`report.md` opens with a short answer to your decision question ("inconclusive" is a
valid answer) and the reminder that these are synthetic hypotheses, then first
impressions, goal outcomes and frictions, feature ideas, things to keep, dissent,
environment problems, model errors, coverage and a ranked backlog. When you read it:

- A first impression is simulated. It is not a measured five-second test with a
  person, and a text-only answer never supports a claim about how a screen looks.
- Each finding quotes the exact participant text and links to the accepted answer
  it came from. Persona reactions, observed browser events and the analyst's
  inferences are kept apart, and an idea the analyst inferred is labelled as an
  unverified suggestion.
- Support is counted as unique cells, personas and model lineages, never as
  percentages. Two quotes from one cell are one cell.
- A blocker seen in one cell can rank above a cosmetic preference seen in many, and
  the reason is shown. Implementation effort stays unknown unless you supply an
  authorised assessment.
- "Could not find a feature that exists", "the feature is absent", "the test
  environment failed" and "the model's claim contradicts the captures" are separate
  categories. Only the first two are product findings.
- Coverage shows journey gaps and unverified model identity. If the capture context
  already held test state, such as a returning test user, the first impressions say
  so.

## The export, and the step before imps

The export is a folder you can move anywhere: the report, structured findings and
backlog, one issue draft per backlog item, copies of the cited screenshots and notes,
and the accepted participant answer each quote comes from, so every quote can be
checked against its source after the folder moves. Its review status comes from the
study's current records.

Nothing is posted, and no fix or imps run starts. Each issue draft states the
requested change, the evidence, the uncertainty, how to verify it and any product
decision still open. Deciding which drafts become issues, and asking imps to build
one, is a separate request with its own authorisation.

## Revising a study

When a revision changes only limits, the deadline or the reviewer, accepted
participant results carry forward unchanged. Changing one persona re-runs only that
persona's cells. Changing the target URL, environment or journey browser context
re-runs journeys but keeps first impressions; changing the captured material or its
capture record re-runs both. A result whose file changed after acceptance never
carries forward. A capture-only revision keeps first impressions, drops journey
results and never counts as a completed combined study.
