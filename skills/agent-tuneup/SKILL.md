---
name: agent-tuneup
description: "Audit, troubleshoot or change agent configuration, permissions, hooks, MCP connections or native skill discovery when the user asks."
---

# Diagnose agent setup

Trace observed agent behavior back to the setting and owner that control it.
Apply minimal changes at the owning source only when authorized, then verify
the live result.

## Inputs

Confirm three items before acting: the target host or agent, the symptom or
audit scope, and whether edits or live rollout are authorized. If authority is
unstated, stay read-only and propose the minimal change.

## Branches

| Task | Path |
| --- | --- |
| Audit permissions or config | Inventory → trace ownership → optionally scan relevant authorized config files (host-local) → audit report with failure scenarios |
| Troubleshoot skills, MCP, hooks, permissions or T3 startup | Inventory → check symptom list (and T3 dispatch preflight for T3 issues) → trace ownership → root-cause report |
| Authorized source-only edit | Trace ownership → edit owning source & regenerate workspace outputs or dry-run only (defer live-writing generators to authorized cutover) → source, schema and repo checks (no live-cutover backup) |
| Authorized live cutover | Trace ownership → edit owning source & pass source/schema/repo checks → restricted host-local before-state backup & restore map → apply live rollout → fresh-session verification |

## Workflow

1. **Inventory scope and precedence.** Inspect the affected host, versions,
   configuration roots, aliases, MCP settings, hook definitions, skill paths
   and working tree. Expand only as needed to answer the request and preserve
   unrelated work. Read [dispatch preflight](references/t3-dispatch.md) when
   diagnosing T3 startup or delegation permissions. Read
   [diagnostic checklist](references/diagnostic-checklist.md) when
   troubleshooting skill discovery, MCP connections, hooks or permission
   precedence. Done when the relevant config sources, precedence chain and
   dirty state are recorded.
2. **Trace ownership and separate behavior.** Map each effective setting to its
   owning source or generator, and separate intended policy, configured
   permissions and observed runtime behavior. Consult current official host
   docs when provider semantics are uncertain; leave generated copies untouched.
   When auditing relevant authorized JSON, JSONC or TOML permission files,
   optionally run the [config scanner](scripts/scan_config.py) to flag broad
   permissions and prompt-suppression policies without printing values. Keep
   scanner output host-local because pointers may still be private, treat flags
   as investigation prompts rather than automatic fixes, exclude credentials
   and transcripts by default, and remember observed tool calls do not prove
   approval. Done when every relevant behavior maps to a verified owner or is
   marked unknown.
3. **Edit source and validate before rollout.** Skip this step for read-only
   tasks. Edit only the owning source and regenerate workspace outputs (or run
   a dry run) through its owner; defer any generator that writes live installed
   files until step 4. Respect explicit permission choices and preserve deny
   rules, ownership guards, private overrides, vendor skills, credentials and
   active jobs. Inspect generated workspace results and run relevant
   schema/fixture tests plus owning-repository checks and review before any
   live rollout. Done when owning sources are updated and pre-rollout source
   validation has an explicit status.
4. **Back up, roll out and verify live.** Skip this step for read-only or
   source-only tasks. Before writing live files, write a restricted host-local
   backup of the exact managed before-state with a restore map; keep
   live-cutover ceremony off source-only edits. Apply the authorized live
   rollout or generator, then verify effective permissions, hooks, MCP or skill
   discovery in fresh sessions. Installed files and passing fixtures alone do
   not establish live compatibility. Done when rollback artifacts exist, live
   rollout is applied and fresh-session acceptance has an explicit status.

## Exits

- **Unknown ownership:** Stop dependent edits and report the ownership gap.
- **Missing edit authority:** Stop after read-only diagnosis and propose the
  minimal change.
- **Missing rollout authority:** Stop after source edits and validation, and
  report rollout as not authorized.
- **Fresh-session check unavailable:** Report live compatibility as unverified.

## Outputs

Scale detail to the task and keep source validation, rollout and fresh-session
acceptance separate:

```text
Result: <summary>
Affected paths & ownership: <path -> owning source/generator | unknown>
Checks:
- Source validation: <pass | fail | not run> (<command/evidence>)
- Rollout: <applied | source-only | not authorized>
- Fresh-session acceptance: <verified | unverified (<reason>) | not applicable>
Audit findings & failure scenarios: <omit when not auditing>
Rollback map: <restricted backup path -> live target; omit for read-only/source-only>
Unresolved gaps / unknowns: <unknown precedence, semantics or unverified runtime behavior>
```

Delegates return complete plain-text reports to their coordinator. In T3 Code,
only the main-thread coordinator uses `html_preview` then `html_render` for
substantive audit findings and configuration comparisons; use readable text when
native HTML is unavailable or the result is brief.

## Boundaries

Use native tools. Keep private configuration and pointers out of shared reports
and external prompts without sharing authority. Never broaden access merely to
suppress prompts. This skill grants no extra authority to edit, publish,
broaden access or deploy.
