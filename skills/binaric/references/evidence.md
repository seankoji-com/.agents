# What agent-to-agent text costs

Measured over 155 hours of T3 Code work in November 2026: 2,402 agent-written
messages joined to 55,026 gateway calls in 688 native sessions.

## Method

- Each message is re-read by every later call on its session's main model line,
  in both the sender's and the receiver's session.
- Calls far below the current context size are side calls and are skipped. A
  drop that persists for three calls is a compaction and ends the count.
- Tokens are estimated at four characters per token, with 3.3–5 as sensitivity.
- Prices use each call's observed mix of cache reads, cache writes and fresh
  input. All-cache and all-fresh pricing are scenarios, not bounds: a cache
  write can cost more than fresh input.

## Findings

| Message kind | Share of re-read tokens | Mean re-reads (receiver / sender) |
| --- | --- | --- |
| Completion report | 53% | 168 / 27 |
| Dispatch brief | 36% | 44 / 170 |
| Follow-up to a child | 9% | 88 / 183 |

The host adds a header line to each completion report, about 5% of its text.
Only the child-written part can be shortened.

- All agent-written text was 2.9% of prompt tokens in those sessions and 4% of
  their output tokens.
- About 90% of re-reads hit the cache, so list-price cost is small. The gain is
  quota headroom and writing time: a slow model writes about 34 tokens a
  second, so every 1,000 tokens cut from a report saves about 30 seconds.
- A 35% cut saves an estimated 0.10–0.16 billion re-read tokens and 0.5–0.8
  million output tokens over those 155 hours, net of the skill's estimated load
  on dispatching sessions.
- On four real messages of matched scope, rewriting with these rules cut
  37–54% (44% overall). Cold reads by a fresh low-cost model passed 3 of 5
  rewrites first time. A fresh brief dropped its base revision and a numeric
  limit, and a dispatch dropped a conditional exception. Both were restored
  and passed on re-read, which is why rule 2 names the exact base and rule 5
  lists conditions and exceptions.
- A dispatch brief is re-read in the coordinator's own context about four
  times as often as in the child's, so long briefs cost the writer most.

## Limits

- Message tokens are inferred from timestamps and session joins, not observed
  in prompts. Summaries kept after compaction are not counted.
- Writing time comes from median output speed, not timed handoffs.
- The fixed context each delegate loads before any work was projected at about
  19% of delegate prompt tokens, roughly four times all agent-written text.
  Trimming it is a separate, larger lever.
