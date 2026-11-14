---
name: backlog-burn
description: Burn a repository's open issues and pull requests down to zero, or launch one run per repository for a named organisation. Use for backlog reduction, clearing open PRs, unblocking owner decisions or dispatching issue fixes. Prefer evidence-based closure and useful delegation up to 20.
---

# Burn the backlog to zero

The backlog is the scope's open issues and open pull requests. Prefer closing
items whose useful outcome is delivered or whose remaining work no longer adds
value. Keep worthwhile fixes and PR repairs running in parallel while discovering
and unblocking others. Never close for the count alone.

## Scope

Issues and PRs always share one scope. Default to the current repository. When
the owner names an organisation, read [org mode](references/org-mode.md) and
follow it instead of the steps below; it only launches repository runs.

## Authority and limits

- You have standing authority to implement, push scoped branches, open PRs,
  request cross-lineage review, and squash-merge when the repository's gates are
  green. Merging includes any automatic post-merge deployment the repository
  already defines; name its effect in the report. A merged fix closes its issue
  only when acceptance is code-only.
- Burn-down also authorizes babysitting every open PR in scope that has no
  verified live owner, and closing PRs unmerged with evidence under
  [the PR rules](references/pull-requests.md).
- Inventory, triage-only and question-only requests propose actions. Autonomous
  closure, dispatch and merge require clear, burn-down or implement intent within scope.
- Burn-down authorizes evidence-based closure of ordinary completed, obsolete,
  substantially done or low-value issues without per-issue confirmation. Apply
  the classification rubric first. Protected issues and material risk acceptance
  retain owner review; repository-specific limits take precedence.
- Manual deployments, live host, secret and destructive-data actions need
  per-action approval through the host's approval path, proposed as the playbook's
  live-write question. Missing approval blocks that action, not independent code work.
- An explicit read-only, no-merge, no-close or release hold overrides these
  defaults. Required human approvals remain gates; never bypass protection,
  manufacture approval, or force-push a shared branch.

Read the repository's `AGENTS.md`, contribution guide and known-live-issues index
before classifying anything. For careynas.net, load [the careynas.net
profile](references/careynas-net.md) before classifying. Settled decisions are
evidence. Apply repository-specific confirmation rules; reuse qualifying owner
requests instead of asking again.

## 1. Open the queue

For burn-down, load [ship](../ship/SKILL.md), [babysitter](../babysitter/SKILL.md)
and [implement](../implement/SKILL.md) now; complete their repository, model,
reviewer and T3 permission preflight before dispatch. Use one parent plan and
execution manifest.

List paginated lightweight issue headers and open PRs. Record both starting
counts, discovery cursor and unexamined IDs using [the ledger](references/ledger.md)
in a verified ignored directory. Classify every open PR under
[the PR rules](references/pull-requests.md) before new issue work; adopted PRs
take scheduling priority. Fetch the next candidate's body and comments only.
Verify readiness indexes against current acceptance and ownership. Paginate
incrementally; avoid downloading every history before dispatch. Indexes and
comments are evidence, not permission changes.

## 2. Classify and dispatch incrementally

Read [the classification rubric](references/classification.md) per candidate.
Assess closure before implementation. Retire trivial leftovers without replacement
issues; keep material defects and necessary unmet outcomes actionable. Once current
evidence and ownership establish worthwhile dev-ready work, dispatch before
examining unrelated histories. Batch independent dispatches where supported.

Use the maximum allowed concurrency, capped at 20 for every delegate the run starts,
including PR repairs. Follow [the ledger's capacity protocol](references/ledger.md#delegate-capacity)
before dispatch: verify host limits, allocate child slots and preserve review
capacity. Fill slots with independent authorized work; record concrete reasons
for unused capacity. Capacity cancellations need reruns, not code fixes.

On every completion, PR notification, owner answer or continuation wake, re-list
open issues and PRs, reconcile active work and refill before voluntary waits. An
empty ready queue resumes discovery. At full capacity, keep classifying,
investigating and batching questions while servicing merges and repairs.

Before yielding, apply the ledger's yield record and follow returned `next`;
resume the preserved action on wake. Report discovery paused during mandatory yields.

Evidence gaps get investigation. Split live work into independently testable
source work and exact approval/acceptance steps; ask about the latter instead of
parking the whole issue. Ambiguity requires evidence or a decision, regardless
of complexity label.

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
material decisions to the same lead. Record returned task handles and bound
worktrees; "queued" is not started work.
The parent does not implement issue fixes inline. Missing delegation or review
becomes an owner question, not permission to substitute inline coding.

- The main coordinator runs ship and babysitter. It owns every PR link, native
  watch, repair dispatch and verified merge for PRs it creates or adopts.
  Delegate coding and review, not separate ship lifecycles or PR watches.
- If nested review dispatch is unavailable, obtain the cross-lineage review
  yourself against the exact committed HEAD. Self-review does not satisfy the
  gate.
- Record each delivery result in the ledger before applying this skill's
  issue-closure rules.
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

Dispatch independent work before blocking questions, as the playbook sets out.
Silence is not approval.

## 5. Apply the answers

Update the ledger, reclassify and dispatch newly unblocked work before reporting.
Execute approved live actions through the supported approval path. Close
owner-confirmed protected issues per §6. Read back closures and required follow-up URLs.

## 6. Close correctly

- A merged fix closes its issue through the PR only when acceptance is code-only.
  When live verification or a protected issue is involved, use `Refs #N` instead
  of a closing keyword; close after the acceptance is recorded. Verify only the
  intended issues closed.
- A duplicate closes against an open canonical with a link and `duplicate` state
  reason. Never fold a protected issue — security, hardware, resilience, or
  priority P0/P1 — without explicit owner review.
- Record evidence and reason under the rubric: completed for verified outcomes,
  not-planned for retired work, naming unfixed residue.
- Close PRs unmerged only under the PR rules. A closed PR never satisfies its
  linked issues; reclassify them.

## 7. Loop to zero

Audit before each yield or final report, reconciling live issues, PRs, ledger,
task receipts and answers.

1. Unexamined, ready, approved-but-undispatched, investigable or unasked work?
   Perform it whenever the host permits, even at full delegate capacity; queue ready fixes.
2. Active delegate, owned PR, review or acceptance evidence pending? Retain ownership
   and supported continuation. A watch receipt is not delivery or proof of
   unreadable CI, and does not cover unrelated issues.
3. Only explicit holds, verified in-flight-elsewhere items and actually submitted
   unanswered questions remain? Report "awaiting owner" if any answer is pending,
   with retrospective pending. Preserve questions, manifest, budgets and
   continuation. This is a pause.

Success requires a fresh paginated zero for both issues and PRs, and verified
delivery or justified, authorized retirement for every closure.
When every remaining item is explicitly owner-held or in flight elsewhere, hand
back "not zero", naming each hold, owner link and next trigger. Unsupported
continuation or access is incomplete, with an owner question and next trigger;
never invent a hold or abandon independent work.

## 8. Report

For delivery runs, finish ship's consolidated retrospective at zero or a "not
zero" endpoint, after required tracking. Terminal blocked handbacks use ship's blocked
retrospective rules. Missing coverage or blocked filing of warranted proposals
leaves it incomplete; preserve drafts and ask the owner. Re-inventory after
filings; new target issues resume the queue, extending the same retrospective
record and budgets without retrospecting its own filing activity.

Report the contents listed in [the ledger's handoff](references/ledger.md#handoff).
Separate local checks, current-head CI, merge, deployment and live acceptance.
Describe pending PRs as pending.

When changing this workflow, exercise [the validation cases](references/validation.md).
