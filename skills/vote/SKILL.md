---
name: vote
description: "Settle a framed binary, multi-option or open decision by 2/3 vote from three blind, distinct model families, or return the split. Use when asked to vote, poll models, or break a deadlock; think frames an unframed decision."
---

# Settle a decision by vote

Use this for a framed choice that needs three independent models. It does not
frame the question: when the question or constraints are unclear, use
[think](../think/SKILL.md) first. For findings or visual options, use challenge
or choose-design.

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

2. **Resolve the three seats.**
   The fixed roster is Opus, Sol and Neon: `claude-opus-5-5`, `gpt-6.2-sol` and
   `gemini-4-neon`. Apply the
   [T3 dispatch preflight](../agent-tuneup/references/t3-dispatch.md) before
   resolving routes for its permission, lineage and capacity checks; its
   score-driven model choice does not replace the fixed roster. Use high effort
   on every seat.
   - Opus: native Claude (`claudeAgent`) or Antigravity.
   - Sol: Codex or the pi API-credit alias.
   - Neon: Antigravity, the burner Antigravity route or the pi API-credit alias.
   A seat is unavailable when it cannot start or return: quota, authentication,
   permission, timeout or a missing model. Find the named model on another
   eligible route before treating the seat as unavailable. Only an operator's
   cross-provider request authorises the roster's API-credit aliases; an agent
   invocation treats a paid alias as unavailable unless the operator already
   authorised it. Record whether a route is subscription or API credit, and do
   not use paid overage for any other model.
   If the invoker is Opus, Sol or Neon and the thread already contains its
   recommendation, apply the [invoker-seat rule](references/invoker-seat.md)
   before dispatching that seat. Otherwise use a fresh non-fork delegate; never
   use a fork as a voter.
   Done when each seat has a startable route, or the vote is held.

3. **Write one packet.**
   The packet contains:
   - The question in neutral wording.
   - The options verbatim, for a closed vote. Add no options, including a status
     quo, unless the operator asks for one.
   - Constraints, evidence, definitions and the authority boundary.
   - The exact ballot format and the seat's deadline.
   - What a 2/3 majority authorises.
   Do not state the invoker's preference, the expected answer or another voter's
   answer. Done when every seat can answer from the packet alone.

4. **Dispatch the blind voters in parallel.**
   Use the host's model-addressable task tool. In T3 Code that is
   `delegate_task`; use one fresh delegate per seat that still needs a voter and
   keep each `taskId`. Dispatch them all before reading any result. Voters use
   only the packet: no file reads, no tools, no delegation and no invoking
   `vote`. Blind means separate sessions that receive only the packet; it does
   not require a filesystem sandbox. Do not poll; follow the host's completion
   wake. Done when every seat has a ballot or a failure is recorded.

   Ballot format:
   - Closed vote: exactly one listed option label.
   - Open vote: one imperative sentence naming the verb, object and every
     material parameter, plus a short label.
   - Then a two-to-four sentence rationale and the key assumption.

   A ballot that hedges, abstains, asks for more information, or names anything
   other than exactly one listed option in a closed vote is invalid. Give that
   seat one blind re-ask with a format correction and the same packet.

5. **Validate and bound each seat.**
   A dispatched seat has a five-minute deadline, or the request's shorter
   deadline, including the route retry and one re-ask. Record the target model,
   any `executedModel`, requested effort and confirmation, route type, and any
   substitution.
   A non-null `executedModel` that conflicts with the target invalidates the
   seat. A null `executedModel` is target-confirmed and execution-unverified; it
   does not by itself invalidate the ballot. A voter's own conflicting model
   claim invalidates its ballot. Missing effort evidence is reported, not fatal.
   Done when every seat has a valid ballot or is recorded as failed.

6. **Tally.**
   A 2/3 majority needs three valid ballots with two identical choices.
   For a closed vote, compare exact option labels.
   For an open vote, two ballots match only when verb, object and every material
   parameter agree, and neither omits or rules out a step the other has. A
   material parameter is any parameter either sentence states; wording and
   rationale do not matter. If matching needs argument, or one ballot is a
   superset, they do not match. Never merge labels yourself.
   Two matching ballots plus one invalid or failed seat is incomplete, not a
   majority. Done when the tally is a majority or a recorded split.

7. **Act or return.**
   On a majority, the result is binding: execute the voted action without asking
   again, within the invoker's existing authority; a user invocation authorises
   the action named in the request. A child invoker returns the result to its
   parent. If a required permission, check or hard constraint blocks the action,
   report the blocker; do not substitute. On no majority, return the neutral
   split and stop. The operator may override a majority at any time; the
   no-re-vote and no-reframing limits apply to invokers. Done when the action is
   executed, returned or reported blocked.

## Branches

| Case | Action |
| --- | --- |
| Binary or multi-option | Close the ballot to the listed options. |
| Open-ended | Use the imperative-sentence ballot and the strict matching rule. |
| One seat unavailable after route search | Substitute DeepSeek Flash V4.1 high (`litellm/deepseek-v4.1-flash`) once. Record the substitution and lineage. |
| The DeepSeek seat fails | Retry it once, then hold and report. Never substitute twice. |
| Two seats unavailable | Hold and report; ask the operator. |
| A voter returns a non-ballot | One blind re-ask, then treat the seat as failed. |
| No 2/3 | Return the tally, rationales and crux; add no recommendation. |
| Agent-invoked | Ballot only actions within the agent's authority; return reserved decisions to the operator. |
| Invoker is a panel model with a qualifying recommendation | Count it as that seat; mark `invoker-existing`, `not blind`; dispatch the rest. |
| Host cannot reach three lineages | Hold and report; do not simulate a vote. |
| Explicit operator voter override | Allow only from the operator; still require three distinct lineages and record it. An unavailable named voter holds the vote. |

## Exits

- Fewer than three valid ballots: hold and report; never claim 2/3.
- No eligible route and no DeepSeek seat: report the missing lineages and stop.
- A majority action is blocked: report the blocker and stop; do not re-vote.
- The host cannot start separate voter sessions: report the gap and stop.

## Output

```text
Vote: <decision>
Result: <option> — 2/3 majority | No majority
Seats:
- Opus (<route>, <effort evidence>): <choice> — <rationale> [verified | unverified]
- Sol (<route>, <effort evidence>): <choice> — <rationale> [verified | unverified]
- Neon (<route>, <effort evidence>): <choice> — <rationale> [verified | unverified]
Packet: <verbatim packet>
Grouping (open only): <matched sentences side by side, or "not needed">
Action: <executed | returned to operator | blocked: reason>
```

Mark an invoker seat `invoker-existing, not blind`. On a split, replace
`Result` with `No majority`, add
`Crux: <the point the disagreement turns on>`, and give each seat's choice and
rationale. Do not add the orchestrator's preference. If a majority depends on an
execution-unverified seat, say so in the result line.

## Boundaries

- The vote settles a choice within the invoker's authority; it never creates
  authority.
- Keep secrets and unrelated private data out of the packet. A user invocation
  authorises sending the packet to the roster; an agent invocation may send only
  material already authorised for those providers, and otherwise returns the
  packet to the operator. Invoking the skill does not authorise widening the
  share.
- Do not add options, merge labels or recommend on a split.
- Record every substitution, route type and metadata gap. A vote with a gap is
  still reported as a vote, not as a cleaner result than it is.
- Stop task-owned delegates when the vote is complete or held.
