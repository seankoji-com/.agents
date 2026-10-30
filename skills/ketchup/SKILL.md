---
name: ketchup
description: Catch the user up on changes in this chat and every decision still waiting on them. Use for /ketchup.
disable-model-invocation: true
---

# Catch up

Use the plain voice of [bro](../bro/SKILL.md). Assume the user remembers their
last message before `/ketchup`, but nothing after it. Notifications and child
results are not user messages.

Keep this turn read-only apart from presentation. Collect changes since that
message, including child results, and verify the current state of relevant PRs,
checks and tasks. Carry forward earlier decisions still waiting on the user.
Do not start an app, change code, launch work or post externally to prepare a
catch-up. Reuse existing screenshots and recordings; state when visible behavior
has not been inspected.

Deliver:

- What changed for the user, what remains unfinished and any consequential defect.
- Every pending owner decision, with the recommendation, alternatives, evidence,
  tradeoff, prerequisites and link needed to decide it from this report alone.
- Any work you can still do yourself and its next action. It is not an owner decision.

Group shared decisions, but retain each affected item and its individual risk.
Do not invent decisions or hide unknowns. Leave out implementation identifiers
unless the user needs one to act. Scale detail to the actual changes and calls;
if nothing changed and nothing needs the user, say so and stop.

## Presentation

In T3 Code, present substantive catch-ups as native inline HTML: check the HTML
with `html_preview`, inspect the result, then show it with `html_render`. Use the
host's theme and responsive layout guidance. Present related changes, evidence
and decisions together with working links; diagrams and existing captures can
explain relationships or visible changes. HTML tables and decision cards are
valid presentation. Avoid decorative dashboards and invented progress metrics.

Use another host's native presentation tools or readable text when T3 HTML is
unavailable. A short no-change reply needs no HTML. Do not start a server or add a
rendering helper. Keep the full decision context in the report, rather than making
the user reconstruct it from earlier messages or linked logs.
