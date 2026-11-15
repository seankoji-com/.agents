# Host usage evidence

Investigated on **15 November 2026 AEDT (UTC+11)** using exposed tool contracts
and official documentation. No model run was purchased for this investigation.
These are capability observations, not proof of data exposed in every session.
Read-only version probes found OpenCode v2.3.0, codex-cli 0.169.0 and Claude Code
2.1.325. Version/help probes do not establish live usage or billing accuracy.
The renderer reads only its ledger; it does not scrape transcripts, call providers
or calculate a bill from a model price table.

| Host | Evidence and available granularity | Ledger treatment |
| --- | --- | --- |
| T3 delegate tasks | The live `delegate_task`, `task_status` and `t3_thread_read` output schemas expose task/thread identity, model, state and timing, but advertise no token, turn-usage or USD fields. `recentRuns` is run history, not billable turns. | Use notification times and exposed identity. Tokens, turns and USD stay `unknown` unless another supported host surface actually supplies a scoped observation. This schema finding does not prove T3 has no internal usage data. |
| Claude Code | [Claude Code costs](https://code.claude.com/docs/en/costs) documents session usage and subscription distinctions. [Agent SDK cost tracking](https://code.claude.com/docs/en/agent-sdk/cost-tracking) exposes assistant-message token usage, per-model `modelUsage` / `model_usage`, and cumulative `total_cost_usd`. SDK USD fields are client estimates and may differ from billing. | Record observed token components and the exact aggregation in the source. Mark SDK USD as `host-estimate`. A session total cannot be assigned to a child segment without matching scope. Subscription allowance is not a task USD amount. No SDK installation is needed by this skill. |
| Codex | [Official OpenAI documentation: non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) documents `codex exec --json` and `turn.completed.usage`: input, cached input, output and reasoning output tokens. That event's documented example has no USD field. | Record scoped usage when the host exposes it. Preserve component definitions: cached input is a subset of input, and reasoning may be part of output; do not add subsets twice. USD stays `unknown` without a reported scoped amount. JSONL availability in the CLI does not establish its exposure through T3. |
| OpenCode | [Current CLI commands](https://opencode.ai/docs/cli/commands/#stats) document `stats --cost --json`, model/project filters and `session export`. Local v2.3.0 help confirms those commands. The official [V1 SDK docs](https://opencode.ai/v1/docs/sdk/) link to [v1.19.4 generated types](https://github.com/anomalyco/opencode/blob/v1.19.4/packages/sdk/js/src/gen/types.gen.ts), where `AssistantMessage` and `StepFinishPart` have `cost` and token fields (input, output, reasoning, cache read/write). These fields are V1 evidence, not proof of the v2 export shape. | Record observed message or step totals, not both. Treat catalog-derived USD as `host-estimate`, not invoice data. Verify the installed version/export shape and attribution before copying. A numeric zero alone does not prove a known free task; unrecognized pricing remains `unknown`. No private session was exported; v2 per-task attribution remains unverified. |

For every observation retain a short source such as host version, event/message
ID, field name and scope. Record a documented aggregate as reported; if only
components are available, name the arithmetic and inclusion rules. Do not copy
raw session content or credentials into the ledger, fixtures or reports. Do not
start a new model session merely to discover whether cost reporting exists.

Counters vary by host. State what a reported turn count means; do not substitute
tool calls, T3 run ordinals or transcript messages. Do not sum cumulative totals
from successive updates. If attribution across models is unavailable, keep a
task total unattributed and explain the missing coverage.
