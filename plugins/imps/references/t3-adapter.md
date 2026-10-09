# T3 adapter

Load this when a T3 tool is missing, errors, or behaves unexpectedly.

## Pinned surface

- Contract: [orchestrator MCP server](https://github.com/pingdotgg/t3code/blob/main/docs/orchestration-v2/orchestrator-mcp-server.md), read on 9 October 2026.
- Tested T3 version: server `0.0.46-nightly.20261008.2849` (Linux desktop build, CLI `0.0.46-nightly.20261007.2787`). The orchestration tools exist only in nightly and preview builds. A T3 update can break this adapter; when it does, the break shows up as `unavailable` or a schema error, never as a silent fallback.
- Transport: authenticated HTTP MCP under the server key `t3-code`. Harnesses add their own prefixes (`mcp__t3-code__delegate_task` and so on), so match tools by base name. The package never reads `T3_MCP_BEARER_TOKEN`, stores credentials, or runs its own MCP client.

| Tool | Source | Used for |
| --- | --- | --- |
| `orchestrator_capabilities` | doc, confirmed live | `discover`: parent thread, inherited provider/model, catalog, feature flags |
| `delegate_task` | doc, confirmed live | every `dispatch`: arguments come verbatim from `next` |
| `task_status` | doc, confirmed live | `query_task` and `confirm_stop` |
| `task_cancel` | doc, confirmed live | `cancel_task` |
| `t3_thread_read` | doc | `collect_result` when the summary lacks the result block |
| `t3_thread_update` | doc | action `link_pull_request` (repository, number, URL) for an authorised PR |
| `create_threads`, `t3_thread_launch` | doc | prohibited for child work: they create top-level threads |
| `t3_thread_send` | doc | never sent to a child thread; a new round is a new `delegate_task` |

## Observed behaviour at the tested version

- `delegate_task` returns `taskId`, `childThreadId`, `status` (`running`, `completed`, `interrupted`), `workState` (`working`, `waiting_for_children`, `result_available`), `hasPendingChildRuns`, `summary` and `waitTimedOut`. The same `clientRequestId` returns the same task.
- `summary` holds the child's final message, so the fenced result block normally arrives with the observation. When it does not, `next` offers `collect_result`.
- `task_cancel` answers `cancel_requested`. That is not a confirmed stop. A later `task_status` showing `interrupted` with `result_available` and no pending child runs is a confirmed stop.
- `mode: wait` with `timeoutMs` ends only the parent's wait. The child keeps running, and `next` never dispatches it again.
- `task_status` is scoped to the parent: another thread cannot read or cancel these tasks. A run resumed from a different thread blocks with a handoff instead.

## When something is missing

- **Tools not callable at all:** record `capabilities` with `{"response": {"unavailable": true, "reason": "<what you saw>"}}`. Delegated mode and independent review become `unavailable`, and the run blocks with a resume command. Direct work that needs neither still runs. There is no fallback transport.
- **A provider cannot run child tasks:** the catalog reason is kept and classed as `disabled`, `not_installed`, `unauthenticated` or `other`. Do not try to log in, install or enable anything.
- **`delegate_task` errors:** record `dispatch` with `{"action_id", "error": {"code", "message"}}`. Unavailable targets advance only an explicit fallback chain; a named target blocks instead.
- **Argument errors:** fix the call. Never swap in a different tool.

## Preview toolkit (browser checks)

The pinned doc says T3 registers a preview toolkit but does not list its tools. Find them at runtime by description: tools that open an in-app browser preview of a local URL, navigate, click, type, take a snapshot, and report preview status. Use the live schema of whatever you find. If no such tools exist, record the runtime requirement as `unavailable`, say what you looked for, and use a documented alternative (a scripted HTTP request, or the project's own end-to-end harness). A browser check you did not run is never `passed`.

## Pull requests

T3's documented surface has no PR-watcher tools, so the package never relies on one. When the operator asked for a PR, the publish step pushes and opens it with native tools, then links it with `t3_thread_update` (`link_pull_request`). `confirm_remote` observes it with `gh pr view <url> --json state,headRefOid,url,number` at the moment completion is claimed.
