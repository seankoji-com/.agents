# Native task lists

Supplied with issue #305 on 16 November 2026 AEDT (UTC+11) from T3 Code Nightly
and the provider harnesses. The rows below were not independently re-verified
before publication. Provider support and configuration drift, so confirm the
row against the current host before relying on it and update this file when it
changes, as [host cost evidence](../../plan-report/references/host-costs.md)
does for cost data.

T3 Code exposes no MCP tool that writes a thread's step list. The Tasks row above
the composer is a projection of each provider's native todo stream, normalised
into `todo_list` items (`plan.updated` and `turn_item.updated`).

| Host | Tool | Observed host setting (information only) | Visibility caveat |
| --- | --- | --- | --- |
| Codex | Built-in `update_plan` | None; no environment toggle | T3 hides the Tasks row once the turn settles, even when items are unfinished |
| Claude (`claudeAgent`) | `TodoWrite`, or `TaskCreate`, `TaskUpdate` and `TaskList` | `CLAUDE_CODE_ENABLE_TODO_TOOLS="1"` | No reported caveat |
| OpenCode | `todowrite` | `experimental.todo: true` in `opencode.json` | No reported caveat |
| Cursor, Grok, Muse and other ACP v2 agents | The provider's own plan update | None reported | Normalised only when the provider emits `plan` or `plan_update` updates with `type: "items"` |
| Antigravity (`antigravity-acp`) | None exposed | Not applicable | Emits no ACP `plan` updates and exposes no todo or plan tool; `manage_task` covers only backgrounded shell or cron jobs, and `task_boundary` is not exposed over ACP |

## Discover the tool

Find the tool the current host actually exposes: `update_plan`, `TodoWrite` or
the `Task*` family, `todowrite`, or an ACP plan update. Do not assume one exists
because another host has it, and do not assume this table is current. Outside T3
use the host's visible planning mechanism with the same text fallback.

## Rules

- **Optional and best-effort progress UI.** Writing the list is optional. A list
  update is never a precondition for completing, merging, handing off or
  reporting. If the tool is missing,
  disabled or errors, report the gap, continue, and use the text status fallback
  at each phase change. Do not retry a failing call indefinitely. Never claim the
  Tasks row or an MCP list updated unless a tool call succeeded.
- **Never the source of truth.** Durable state stays where it lives: the
  `plan-report` ledger, git and PR state, ship's recovery record, review-loop's
  recorded scores and counters, and the explicit handoff text. Reuse the same
  list on resume, but do not rebuild state from it; read the durable records.
- **Transient visibility.** The row may disappear when the turn settles. Anything
  the operator must see afterwards, such as unfinished items, blockers and owner
  questions, goes in the final message or handoff text, not only in the list.
- **No config changes to get a tool.** Do not set `CLAUDE_CODE_ENABLE_TODO_TOOLS`,
  edit `opencode.json` or change other settings to enable a missing tool. Report
  it as not exposed and use the fallback. A settings change needs its own
  authority; the settings column above is information, not an instruction.
- **Granularity and cadence.** Items track phases and gates, not every tool call.
  Keep completed, active and blocked items current at phase changes, handoffs
  and failures. The list is cheap and
  independent of `plan-report`'s render cadence, so a list update never triggers
  a report render.
- **Owner of the list.** The coordinator writes its own thread's list. A
  delegate's internal list does not replace the parent's, and neither is a
  substitute for the other's recovery record.

## Tool mechanics

Record item IDs only where returned. Put owner, dependency and evidence
references in item text when the tool has no fields for them. For whole-list
updates, resend the complete current list with its existing statuses; never
invent IDs. Never invent tools or create delegate jobs, schedules or threads
merely as checklist items.

## Where this applies

| Skill | Use |
| --- | --- |
| `ship` | Initialise before implementation when the host exposes a tool; its phase set stays in the skill. |
| `implement` | The main thread tracks the dispatched lead and its phases. The lead's own list stays separate. |
| `review-loop` | Items for the baseline, each review round, repair and final verification. Scores and stagnation counters stay in the recorded state. |

The other multi-step skills do not point here:

- `design-loop`: its 1,486-word entry leaves about 14 words, and its run record
  already tracks rounds, candidates and scores; a list would show a competing
  progress view.
- `backlog-burn`: the queue spans turns, so a whole-queue list would not stay
  readable, and an active-batch list duplicates `plan-report`'s compact rows.
- `babysitter`: per-PR items duplicate the native PR watch, and ship's parent
  list already covers delivery phases.
- `plan-report`: complementary. The list shows live phase state; the report
  shows timeline and calibration at its own boundaries. The list never feeds the
  ledger.
- `think`, `review`, `raise-issue`, `raise-pr`, `github-writing`, `test-writer`
  and `challenge`: short or single-shot runs, or they already use a question tool
  or a reviewer role card.
