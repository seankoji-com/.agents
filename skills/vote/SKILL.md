---
name: vote
description: "Settle a framed binary, multi-option or open decision by 2/3 vote from three blind, distinct model families, or return the split. Use when asked to vote, poll models, or break a deadlock; think frames an unframed decision."
---

# Settle a decision by vote

Use this for a framed choice that needs three independent models. It does not
frame the question: when the question or constraints are unclear, use
[think](../think/SKILL.md) first. For findings or visual options, use challenge
or choose-design.

The T3 workflow `workflows/vote.ts` runs the vote. Its code defines the roster
and routes, each seat's runtime mode, the shared seat deadline, ballot checks,
the one blind re-ask, the DeepSeek substitute, the host model checks and the
tally. This skill keeps the judgment: framing, authority, the packet, the
invoker seat and what to do with the result.

## Requires T3 Workflows

Before anything else, confirm all three:

- The host is T3 Code with Workflows turned on, and its scratch project
  (`~/.t3/scratch`) exists; `t3_project_list` shows it.
- `~/.t3/workflows/vote.ts` exists.
- `~/.config/t3-workflows/vote.curl` exists; it holds the hook URL and token.
  Host delivery writes it. If only this file is missing, run
  `python3 ~/.dotfiles/scripts/t3-workflows.py hooks --source ~/.agents/workflows`
  once, outside any sandbox, and check again. It writes the file without
  printing the hook URL. Without that helper, the README's "Use vote on T3
  Workflows" section has the manual steps.

If any is still missing, report `vote needs T3 Workflows: <what is missing>` and
stop. Do not dispatch voters yourself, simulate a vote, read hook tokens or run
the `t3 workflow` CLI yourself.

## Inputs

- The decision in the operator's words.
- For binary and multi-option votes, the options verbatim, in the operator's order.
- Constraints, evidence and the action a majority authorises.
- The invoker's authority for that action.
- Any deadline or urgency limit.

If the decision or, for a closed vote, the options are missing, ask for them and
stop. Do not invent options.

## Steps

1. **Check the decision is framed and authorised.**
   Confirm the question is answerable, every option is within the invoker's
   authority, and the action after a majority is named. If an option is outside
   the invoker's authority, return it to the operator; do not ballot it. An
   agent may not ballot a decision reserved for the operator, or an
   outward-facing, spending or destructive action it is not already authorised
   to take. A user invocation may ballot those only when the request authorises
   the action. Done when the packet has a question, an option set or an open
   scope, and an authorised action.

2. **Decide the invoker seat.**
   If you are Opus 5.5, Sol 6.2 or Neon 4 and this thread already holds your
   recommendation on this decision, read the
   [invoker-seat rule](references/invoker-seat.md) before writing the packet.
   Include the seat only when every condition there holds. Otherwise leave it
   out and the workflow starts a fresh voter. Done when the seat is in or out.

3. **Write one packet** as a JSON file in a Git-ignored directory of your
   worktree:
   - `invokerThread`: your T3 thread ID, from `printenv T3CODE_THREAD_ID`.
   - `maxRuntimeMode`: your thread's `runtimeMode`, as `t3_thread_read`
     shows it. No voter runs in a broader mode. Voters open in T3's scratch
     project, not your repository; set `project` only when this host's
     scratch project is not `~/.t3/scratch`.
   - `kind`: `closed` or `open`, and `question` in neutral wording.
   - `options`: verbatim, in order, closed votes only. Add none, including a
     status quo, unless the operator asks for one.
   - `context`: constraints, evidence, definitions and the authority boundary.
   - `authorises`: what a 2/3 majority authorises.
   - Optional `deadlineMinutes` (at most 5) for the request's shorter limit.
   - `paidRoutes: true` only when the operator authorised the API-credit
     aliases: in this request for a user invocation, or already, before an
     agent invocation. Otherwise leave it out.
   - `invokerSeat` from step 2: `seat`, `choice` (or `action` and `label`),
     `rationale`, `assumption` and `source` naming the message.

   Do not state your preference, the expected answer or another voter's answer.
   Keep secrets and unrelated private data out; a user invocation authorises
   sending the packet to the roster, and an agent invocation may send only
   material already authorised for those providers. Never set `test`: test
   fields are for acceptance runs and mark the result as not a vote.

4. **Start the run, then end your turn.**

   ```sh
   curl -sS --noproxy '' -K ~/.config/t3-workflows/vote.curl \
     -H 'content-type: application/json' \
     -H 'idempotency-key: vote-<short thread id>-<slug>' \
     --data-binary @<packet>.json
   ```

   HTTP 202 with a `runId` means it started. The same key returns the same run,
   so reuse a key only to retry the same start. `404 hook_not_found` means the
   workflow or hook is missing: report it and stop. Do not poll; the workflow
   writes to this thread.

5. **Answer the receipt turn.**
   The workflow asks for host receipts before it tallies. For each listed
   thread, read it with `t3_thread_read` and report, from `recentRuns`, the
   ballot turn's ID, `executedModel` and `completedAt`, and the thread's run
   count as `turns`. For an invoker seat,
   report the `executedModel` of the turn that made the recommendation. Submit
   exactly what the host shows, with null where it shows nothing. Do nothing
   else in that turn; the vote is not decided yet.

6. **Act or return.**
   The result turn gives the outcome, each seat's status and the labels. On a
   2/3 majority the result is binding: execute the voted action without asking
   again, within the invoker's existing authority, and at most once per run ID.
   A child invoker returns the result to its parent. If a required permission,
   check or hard constraint blocks the action, report the blocker; do not
   substitute. On `No majority`, complete split or incomplete, return the
   neutral result and stop. A test or rejected packet is reported only. The
   operator may override a majority at any time; the no-re-vote and
   no-reframing limits apply to invokers. Done when the action is executed,
   returned or reported blocked.

## Branches

| Case | Action |
| --- | --- |
| Workflows, workflow file or hook config missing | Report what is missing and stop. |
| Packet rejected | Fix the packet; start again with a new idempotency key. |
| Incomplete (fewer than three valid ballots) | Return it as held; never claim 2/3. |
| A majority rests on a not-blind or unverified seat | Keep that label in your report. |
| A route needs a broader runtime mode than yours | The workflow skips it and reports why; the seat may go to the substitute. |
| Request to swap a named voter | Retired by owner decision on 23 November 2026: the roster is fixed in the workflow. Say so; do not hand-dispatch a voter. |
| A majority action is blocked | Report the blocker and stop; do not re-vote. |

## Output

```text
Vote: <decision>
Result: <the workflow's result line, labels included>
Seats: <the workflow's seat lines>
Packet: <path to the packet file>
Run: <run ID>
Action: <executed | returned to operator | blocked: reason>
```

On a split, add `Crux: <the point the disagreement turns on>` and give each
seat's choice and rationale. Do not add your own preference.

## Boundaries

- The vote settles a choice within the invoker's authority; it never creates
  authority.
- Do not add options, merge labels or recommend on a split.
- Report every substitution, route, unverified model and metadata gap the
  result shows. A vote with a gap is still reported as a vote, not as a cleaner
  result than it is.
