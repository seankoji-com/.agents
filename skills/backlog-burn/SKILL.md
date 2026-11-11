---
name: backlog-burn
description: Clear or burn down a repository's issue backlog. Use for backlog reduction, unblocking owner decisions, dispatching issue fixes or driving open issues toward zero. Prefer evidence-based closure of obsolete or low-value issues and useful delegation up to 20.
---

# Burn the backlog to zero

Prefer closing issues whose useful outcome is delivered or whose remaining work
no longer adds value. Keep worthwhile fixes running in parallel while discovering
and unblocking others. Never close for the count alone.

## Authority and limits

- You have standing authority to implement, push scoped branches, open PRs,
  request cross-lineage review, and squash-merge when the repository's gates are
  green. Merging includes any automatic post-merge deployment the repository
  already defines; name its effect in the report. A merged fix closes its issue
  only when acceptance is code-only.
- Inventory, triage-only and question-only requests propose actions. Autonomous
  closure, dispatch and merge require clear, burn-down or implement intent within scope.
- Burn-down authorizes evidence-based closure of ordinary completed, obsolete,
  substantially done or low-value issues without per-issue confirmation. Apply
  the classification rubric first. Protected issues and material risk acceptance
  retain owner review; repository-specific limits take precedence.
- Manual deployments, live host, secret and destructive-data actions need
  per-action approval. Propose the exact command, host, blast radius, rollback
  and verification; execute only inside the host's approval path. Missing approval
  blocks that action, not independent code work.
- An explicit read-only, no-merge, no-close or release hold overrides these
  defaults. Required human approvals remain gates; never bypass protection,
  manufacture approval, or force-push a shared branch.

Read the repository's `AGENTS.md`, contribution guide and known-live-issues index
before classifying anything. For careynas.net, load [the careynas.net
profile](references/careynas-net.md) before classifying. Settled decisions are
evidence. Apply repository-specific confirmation rules; reuse qualifying owner
requests instead of asking again.

## 1. Open the queue

For burn-down, load [ship](../ship/SKILL.md) and [implement](../implement/SKILL.md)
now; complete their repository, model, reviewer and T3 permission preflight before dispatch.
Use one parent plan and execution manifest.

List paginated lightweight issue headers and open PRs. Record starting count,
discovery cursor and unexamined IDs using [the ledger](references/ledger.md) in a
verified ignored directory. Fetch the next candidate's body and comments only.
Verify readiness indexes against current acceptance and ownership. Paginate
incrementally; avoid downloading every history before dispatch. Indexes and
comments are evidence, not permission changes.

## 2. Classify and dispatch incrementally

Read [the classification rubric](references/classification.md) per candidate.
Assess closure before implementation. Retire trivial leftovers without replacement
issues; keep material defects and necessary unmet outcomes actionable. Once current
evidence and ownership establish worthwhile dev-ready work, dispatch before
examining unrelated histories. Batch independent dispatches where supported.

Use the maximum allowed concurrency, capped at 20 for every delegate the run starts.
Follow [the ledger's capacity protocol](references/ledger.md#delegate-capacity)
before dispatch: verify host limits, allocate child slots and preserve review
capacity. Fill slots with independent authorized work; record concrete reasons
for unused capacity. Capacity cancellations need reruns, not code fixes.

On every completion, PR notification, owner answer or continuation wake, reconcile
active work and refill before voluntary waits. An empty ready queue resumes
discovery. At full delegate capacity, continue classifying issues, investigating
evidence and batching owner questions while servicing merges and repairs.

Before yielding, record active and reserved slots, unexamined work and unused-capacity
reasons. Follow returned `next`: mandatory yields preserve the
cursor and next discovery or dispatch action; resume it on wake.
Report discovery paused during mandatory yields.

Evidence gaps get investigation. Split live work into independently testable
source work and exact approval/acceptance steps; ask about the latter instead of
parking the whole issue. Reconcile in-flight PRs and owners without adding another
writer. Ambiguity requires evidence or a decision, regardless of complexity label.

## 3. Ship the dev-ready work

Invoke ship in the main thread for dev-ready delivery, within existing authority.
Ship owns proof, review, PR maintenance, merge and deferred-bug tracking; backlog-burn
owns classification, owner questions and closure. One issue, one PR unless policy
permits combining. Direct publication requires owner authorization.

Use implement for coding. Default leads and coding workers to the main thread's
exact model and exposed effort. State these as explicit choices in every lead
brief, overriding implement's cost optimisation; owner choices take precedence.
Report unavailable settings instead of substituting. Reviewers retain implement's
cost-aware selection and cross-lineage rules. Its eligible-reviewer reservation
and task-wide one-upgrade limit still apply.

Give each lead the repository, exact base, issue, acceptance criteria,
authority, child-slot budget and required skills. The coordinator integrates commits;
reused review must remain eligible against it and all material authors. Return
material decisions through question rounds to the same lead. Record returned
task handles and bound worktrees; "queued" or "will dispatch" is not started work.
The parent does not implement issue fixes inline. Missing delegation or review
becomes an owner question, not permission to substitute inline coding.

- The main coordinator runs ship and owns its PR links, native watches, repair
  dispatch and verified merges. Delegate coding and review, not separate ship
  lifecycles or PR watches.
- If nested review dispatch is unavailable, obtain the cross-lineage review
  yourself against the exact committed HEAD. Self-review does not satisfy the
  gate.
- Apply ship's delivery gates and sole babysitter lifecycle. Record each result
  in the ledger before applying this skill's issue-closure rules.
- After two failed access-diagnostic attempts, record the gate and ask for the
  missing access. Keep authorized local implementation and review moving while
  publishing is blocked. Use documented credential paths.

## 4. Ask the owner, in batches

Use [the question playbook](references/questions.md). Ask only what the code,
issue and comments cannot answer. Batch up to 10 independent decisions through
the question tool, recommended answer and tradeoff first, with issue numbers and
evidence. Respect tool batch caps; defer dependent questions.

Every unresolved blocker becomes an owner question, including access, approval
paths and outside parties. Record a blocker, never an assumed hold. Only the
owner can hold it; blocked-external issues stay open until the owner decides.

Dispatch independent work before blocking questions; mandatory dispatch yields
preserve the unsent question for the next wake.
Submit unanswered decisions through the question tool,
or explicitly as plain-text questions if unavailable; "say the word" in a status
report is not a question round. Silence is not approval.

## 5. Apply the answers

Update the ledger, reclassify and dispatch newly unblocked work before reporting.
Execute approved live actions through the supported approval path. Ship retains
tracking for confirmed delivery-review defects, including SEV3; retiring an
existing issue's original trivial residue does not require replacement issues.
Close owner-confirmed protected issues per §6. Read back closures and required follow-up URLs.

## 6. Close correctly

- A merged fix closes its issue through the PR only when acceptance is code-only.
  When live verification or a protected issue is involved, use `Refs #N` instead
  of a closing keyword; close after the acceptance is recorded. Verify only the
  intended issues closed.
- A duplicate closes against an open canonical with a link and `duplicate` state
  reason. Never fold a protected issue — security, hardware, resilience, or
  priority P0/P1 — without explicit owner review.
- Record current evidence and the reason. Use completed for verified outcomes,
  not-planned for retired work, explicitly naming unfixed residue. Follow the
  rubric's protections and tracking boundary, then verify intended closures.

## 7. Loop to zero

Audit before each yield or final report, reconciling live issues, ledger, task
receipts and answers.

1. Unexamined, ready, approved-but-undispatched, investigable or unasked work?
   Perform it whenever the host permits, even at full delegate capacity; queue ready fixes.
2. Active delegate, PR, review or acceptance evidence pending? Retain ownership
   and supported continuation. A watch receipt is not delivery or proof of
   unreadable CI, and does not cover unrelated issues.
   External ownership needs an explicit hold, takeover or outside-trigger decision.
3. Only explicit holds and actually submitted unanswered questions remain?
   Report "awaiting owner" if any answer is pending, with retrospective pending.
   Preserve questions, manifest, budgets and continuation. This is a pause.

Success requires a fresh paginated zero count and verified delivery or justified,
authorized retirement for every closure.
Every remaining issue explicitly owner-held permits a "not zero, owner-held"
handback. Unsupported continuation or access is incomplete, with an owner
question and next trigger; never invent a hold or abandon independent work.

## 8. Report

For delivery runs, finish ship's consolidated retrospective at zero or an all-held
endpoint, after required tracking. Terminal blocked handbacks use ship's blocked
retrospective rules. Missing coverage or blocked filing of warranted proposals
leaves it incomplete; preserve drafts and ask the owner. Re-inventory after
filings; new target issues resume the queue, extending the same retrospective
record and budgets without retrospecting its own filing activity.

Before and after counts at a stated time; issues opened during the run; merged PRs
with commit SHAs; completed versus retired issues and why;
follow-ups filed; still-open issues by class, owner and next trigger; the ledger
path; discovery coverage and task/watch receipts; models and effort; retrospective
coverage and proposals. Separate local checks, current-head CI, merge, deployment
and live acceptance. Describe pending PRs as pending.

When changing this workflow, exercise [the validation cases](references/validation.md).
