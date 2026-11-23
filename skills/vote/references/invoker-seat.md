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

If any condition fails, treat the seat as having no recommendation and dispatch
a fresh non-fork voter. Do not ask the invoker to restate or defend its view.

## Mark and disclose

- Dispatch no voter for that seat. Count the recommendation as its ballot.
- Mark the seat `invoker-existing` and `not blind` in the result, with the
  model, route and the thread message or excerpt that supplies it.
- Say the vote had two blind seats and one invoker seat. If the majority depends
  on the invoker seat, say so in the result line.
- Never call the invoker seat blind. The invoker framed the packet and may have
  seen other opinions.

## Why this is narrow

Three blind seats are the independence guarantee. This exception is deliberate:
it avoids asking the invoker to repeat a view it already stated, without
turning the invoker into a fourth vote or letting the orchestrator count a
tentative remark. Never use it to count a recommendation the orchestrator
supplied to itself, or one made after seeing another voter's ballot.
