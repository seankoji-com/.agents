# Count the invoker's existing recommendation

Read when a `vote` invocation comes from Opus, Sol or Neon and the thread may
already contain that model's recommendation. The rule lets the invoker's
existing view fill its own seat instead of asking it to vote again.

## Check the invoker's model

Use the host's thread configuration or execution metadata to confirm the
invoker is the exact panel model for one seat: Opus 5.5, Sol 6.2 or Neon 4. Do
not infer it from the prose or from a provider alias. A different Anthropic
model, such as Sonnet or Fable, is not the Opus seat. The DeepSeek substitute is
not eligible for this shortcut.

## Count only a qualifying recommendation

All of these must hold:

1. The thread contains an explicit recommendation on this decision, not a
   hedge. "I recommend X", "X is the better choice" or "we should do X" counts.
   "I lean X" or "X might work" does not.
2. It is the latest explicit recommendation before the vote request. If earlier
   recommendations conflict and no latest is clear, do not count it.
3. It names exactly one packet option for a closed vote, or one concrete action
   for an open vote. The action must be inside the invoker's authority.
4. Its rationale addresses the same decision, options and material constraints
   as the packet. A recommendation made before a material option or constraint
   was added does not count.

If any condition fails, leave `invokerSeat` out of the packet so the workflow
starts a fresh voter. Do not ask the invoker to restate or defend its view.

## Mark and disclose

- Put the recommendation in the packet's `invokerSeat`, with `source` naming
  the thread message that supplies it. The workflow then starts no voter for
  that seat and counts the recommendation as its ballot.
- The workflow marks the seat `invoker-existing` and `not blind`, checks the
  recommendation turn's recorded model against the seat, and names the seat in
  the result line when the majority rests on it. Keep those labels when you
  report the vote, and say it had two blind seats and one invoker seat.
- Never call the invoker seat blind. The invoker framed the packet and may have
  seen other opinions.

## Why this is narrow

Three blind seats are the independence guarantee. This exception is deliberate:
it avoids asking the invoker to repeat a view it already stated, without
turning the invoker into a fourth vote or letting the orchestrator count a
tentative remark. Never use it to count a recommendation the orchestrator
supplied to itself, or one made after seeing another voter's ballot.
