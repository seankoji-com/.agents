# Settle foreseeable blockers once

Read at ship start, before the first dispatch, and when a new material blocker
appears. Ship owns the up-front batch, including questions discovered by its
supporting skills. Reuse settled decisions and existing authority.

1. Inspect the intended endpoint, repository rules, host capabilities and known
   dependencies. Identify concrete owner-only acceptance checks, human or tool
   approvals, provider/sharing authority, release and deployment gates, secrets
   and processes the run did not start. Use the host's secret-input tool for
   secrets; never ask for their values in a normal question.
2. Batch currently answerable unresolved questions through the host question
   tool, recommendation first with tradeoffs and the affected work. Name actual
   missing authority rather than asking for a blanket future grant. When nothing
   is unsettled, record that and proceed without a ceremonial question.
3. Continue independent authorized work. Ask later only when new evidence
   introduces a material decision; the initial batch cannot predict every gate.
   Silence is not an answer. Tool approval does not supply owner authority.

## Owner-only acceptance after delivery

An owner may agree in that batch to perform an owner-only manual acceptance
step after merge or launch, when no repository or release rule requires it
earlier. Record its timing, owner and affected release. This does not defer a
known defect, essential correctness/safety proof, required human approval or
repository gate. A check that reveals a defect returns to normal release rules.

Within the agreed filing authority, use raise-issue to file a follow-up **task**
with exact steps, prerequisites, acceptance criteria and ownership. Obtain its
verified URL and report **unverified, tracked at URL**. Merge, deployment and
live acceptance remain separate states. A draft or pending filing is not tracked
completion; preserve the request and retain ownership until read-back succeeds.

## Processes belonging to another run

Before stopping a process this run did not start, obtain a real owner answer.
The question names its PID, process owner, verified working directory, why it
blocks this task and the proposed action. Refresh identity before acting and
follow the host's PID/port ownership rules. Prior permission for a different
process or a reused PID is insufficient. Continue work that does not need it stopped.
