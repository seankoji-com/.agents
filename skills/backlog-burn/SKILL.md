---
name: backlog-burn
description: Burn a repository's open issues and pull requests down to zero, or launch one run per repository for a named organisation. Use for backlog reduction, clearing open PRs, unblocking owner decisions or dispatching issue fixes. Prefer evidence-based closure and useful delegation up to 20.
---

# Burn the backlog to zero

The backlog is the scope's open issues and PRs. Close what is delivered or no
longer worth doing, never for the count alone. Run fixes in parallel while you
triage the rest.

## The turn rule

- A turn does a full pass (steps 2–7). It does not stop after the first PR,
  the first watch or the first dispatch.
- `watch_pull_request` tells you to end your turn. So call it **last**, in
  step 8, after the pass. Never watch a PR and then stop with untriaged items,
  free slots or unasked questions.
- A watch wakes you only for that PR. Triage the issues this turn.
- Stop early only when a tool forces it or context is nearly full. Write the
  ledger's resume record first and name the next step.

## Scope and authority

Issues and PRs share one scope: the current repository, unless the owner names
an organisation. For an organisation, read [org mode](references/org-mode.md)
and follow it instead of this file.

- A burn-down request ("clear", "burn down", "get to zero") authorises:
  implementing through delegates, pushing scoped branches, opening PRs,
  requesting cross-lineage review, squash-merging when the repository's gates
  are green, babysitting unowned open PRs, closing PRs unmerged under
  [the PR rules](references/pull-requests.md), and closing ordinary issues
  under [the classification rubric](references/classification.md).
- Merging includes any automatic post-merge deployment; name it in the report.
- "Inventory", "triage only" or "ask me" requests propose actions only: no
  closures, dispatch or merges.
- Always ask the owner first for: protected issues (security, hardware,
  resilience, P0/P1), accepting a material risk, closing a draft or a PR whose
  changes exist nowhere else, and every manual deployment, live host, secret or
  destructive-data action (one approval per action).
- Explicit read-only, no-merge, no-close or release holds override all of the
  above. Never bypass a required approval or force-push a shared branch.

## 1. Set up (once per run)

1. Read the repository's `AGENTS.md`, contribution guide and known-live-issues
   index. For careynas.net, also read [its profile](references/careynas-net.md).
2. Create the ledger from [the ledger template](references/ledger.md) in an
   ignored directory, such as `out/backlog-burn/ledger.md`. Confirm with
   `git check-ignore`.
3. Inventory with these exact commands (repeat them on every wake):

   ```sh
   gh pr list --repo OWNER/REPO --state open --limit 1000 \
     --json number,title,author,headRefName,headRefOid,isDraft,updatedAt,url
   gh issue list --repo OWNER/REPO --state open --limit 1000 \
     --json number,title,labels,assignees,updatedAt,url
   ```

   Record both counts and every ID. If a connector tool fails twice, use `gh`.
4. Call `orchestrator_capabilities` once. Record the model, effort, providers
   and any concurrency limit in the ledger header.

Load other skills only when first needed (steps 3 and 5).

## 2. Triage every item from headers

Give **every** open PR and issue a provisional class from its title, labels,
draft flag, linked PRs and dates. Do this for the whole list in one pass and
write it to the ledger. Headers only; no bodies yet.

- PR classes: `in-flight-elsewhere`, `adopt`, `retire`, `ask`.
- Issue classes are listed in [the ledger](references/ledger.md#table).
- Mark issues covered by an open PR as `in-flight` and link the PR.

Steps 3 and 4 check each item before you act.

## 3. Settle each PR's owner

For each open PR, decide whether someone else is actively working on it:

1. `gh pr view N --json commits,comments,reviews,updatedAt,autoMergeRequest`.
2. `t3_thread_search` with the PR number (for example `#4540`), then with its
   head branch. For each hit, `t3_thread_read` it.
3. The PR is **in flight elsewhere** when either is true:
   - a T3 thread that is not archived or settled has a pending watch on this
     PR, is running, or acted on this PR's current head in the last 24 hours;
   - a person commented or reviewed on the current head in the last 24 hours.
     Agents often post under the owner's account; a comment or PR body marked
     as agent-written is not a person.
4. Otherwise it is unowned. An assignee, an old branch, a recent push, bot
   activity or enabled auto-merge alone is not ownership.

Record the evidence. For in-flight-elsewhere PRs, record the owner link and add
no watch, push or review request. Classify unowned PRs as adopt, retire or ask
under [the PR rules](references/pull-requests.md).

Load [babysitter](../babysitter/SKILL.md) before you act on the first adopted
PR. Do the actionable work now: update a stale branch, fix failing checks
through a repair delegate, answer review threads, merge when gates are green.
Do not watch it yet.

## 4. Check issues and close what is done

Work through issues in batches of about ten, writing the ledger after each
batch. For each issue, read the body and comments, then the minimum current
code or docs needed. Apply [the classification rubric](references/classification.md):

- Already done, obsolete or not worth the remaining work: close it with an
  evidence comment and read back the state. Protected issues become questions.
- Missing evidence: investigate in the code first. Ask only when the evidence
  is out of reach.
- Live work: split the source change (may be dev-ready) from the exact live
  action (becomes an approval question).
- Dev-ready: add it to the ready queue and go to step 5 as soon as a slot is
  free. Do not finish triaging every issue before dispatching.

## 5. Dispatch ready work

Load [implement](../implement/SKILL.md) and [ship](../ship/SKILL.md) before the
first dispatch, and run their preflight once.

- Use up to 20 delegates for the whole run, repairs and reviewers included,
  under [the capacity protocol](references/ledger.md#delegate-capacity).
- Start one implement lead per issue in its own worktree. The brief names the
  repository, base, issue, acceptance criteria, authority, child-slot budget
  and required skills.
- State the main thread's exact model and effort in each brief for leads and
  coding workers. Reviewers keep implement's cross-lineage rules. Owner
  choices override both.
- Record each returned task ID and worktree; no receipt means not dispatched.
- Never implement an issue fix in this thread. If delegation is unavailable,
  ask the owner. If a lead cannot start its own reviewer, get the
  cross-lineage review yourself against the exact committed head; self-review
  never counts.
- The main thread owns every PR link, watch and merge. Delegates never watch.
- One issue, one PR. Use `Refs #N` instead of a closing keyword when acceptance
  needs live verification or the issue is protected.

On a delegate result: integrate, open or update the PR under ship, and refill
the slot.

## 6. Ask the owner, in one batch

Ask every decision the code cannot settle together through the question tool,
per [the question playbook](references/questions.md): up to 10 per round, one
decision each, recommendation, tradeoff, issue numbers and evidence. Do not ask what the code, issue,
comments or earlier owner answers already settle. Dispatch independent ready
work before you ask a question that pauses the turn.

Every blocker becomes a question: access, approval paths, outside parties.
After two failed attempts to diagnose missing access, stop and ask for it; keep
local implementation and review moving meanwhile. Only the owner can declare a
hold. Silence is not approval.

When answers arrive: record them, dispatch unblocked work, run approved live
actions through the host's approval path and close confirmed issues.

## 7. Check before ending the turn

Re-run the step 1 inventory commands. Then answer each line in the ledger:

1. Any PR or issue not yet triaged? Triage it.
2. Any adopted PR with work you can do now? Do it.
3. Any ready issue and a free slot? Dispatch it.
4. Any blocker without a submitted question? Ask it.
5. Any closure not read back? Read it back.

Continue until all five answers are "no".

## 8. Watch, then end the turn

Now call `watch_pull_request` once for each adopted PR that is waiting on
checks or reviews. Skip PRs already watched and in-flight-elsewhere PRs. Then
end the turn with a status message containing these counts:

```text
PRs: N open, N triaged, N adopted (N watched), N in flight elsewhere, N closed, N merged
Issues: N open, N triaged, N closed, N ready, N dispatched (task IDs), N awaiting answers
Next: <what wakes this run and the first action on wake>
```

On every wake, rerun step 1's inventory, then resume from the ledger.

## Finish

- **Zero:** a fresh inventory shows no open issues or PRs, and every closure
  has verified delivery or authorised retirement.
- **Not zero:** every remaining item is owner-held, in flight elsewhere or
  waiting on a submitted question. Name each with its owner link and trigger.
- **Not finished:** anything else. Keep working.

A closed PR never satisfies its linked issues. At zero or not zero, finish
ship's consolidated retrospective, then report per
[the ledger's handoff](references/ledger.md#handoff), keeping local checks, CI,
merge, deployment and live acceptance separate.

When changing this workflow, exercise [the validation cases](references/validation.md).
