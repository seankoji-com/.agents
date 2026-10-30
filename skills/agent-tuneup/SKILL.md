---
name: agent-tuneup
description: "Use when the user asks to audit, troubleshoot or change agent configuration, permissions, MCP connections or native skill discovery."
---

# Inspect and align agent wiring

## Workflow

1. Inspect the affected host, versions, configuration files and working tree.
   Follow relevant instruction roots, aliases, MCP settings and precedence; expand
   the inventory only as needed to answer the request. Preserve unrelated work.
2. Trace effective settings to their owning source or generator. Distinguish the
   user's intended policy, configured permissions and observed runtime behavior.
   Consult current official formats where needed; do not assume provider semantics
   or hand-edit generated copies. Unknown ownership blocks dependent changes.

   The optional [JSON scanner](scripts/scan_config.py) flags broad permission
   strings without printing values. Use only selected authorized files; pointers
   may still be private. It does not evaluate precedence or provider semantics.
   Flags prompt investigation, not automatic fixes. Observed calls do not prove
   approval. Do not scan credentials or transcripts by default.
3. Make minimal authorized changes at the owning source and regenerate through
   its owner. Respect explicit permission choices and preserve deny rules,
   ownership guards, private overrides, vendor skills, credentials and active jobs.
   Never broaden access merely to suppress prompts. Before live cutover, back up
   the exact managed before-state host-locally with restricted access and a restore
   map; do not impose live-cutover procedures on ordinary source-only edits.
4. Inspect generated results and run relevant schema/fixture checks plus required
   owning-repository checks and review before rollout. After authorized rollout,
   verify effective permissions and discovery in fresh sessions. Installed files
   and passing fixtures alone do not establish live compatibility.

## Outputs

Scale the report to the task: result, affected paths, checks and unresolved gaps.
For audits, include evidence and failure scenarios; for live changes, include
rollback details. Mark unknown precedence, semantics and unverified runtime behavior
plainly. Keep source validation, rollout and fresh-session acceptance separate.
In T3 Code, use `html_preview` then `html_render` for substantive audit findings
and configuration comparisons; use readable text when native HTML is unavailable
or the result is brief.

## Boundaries

Use native tools and follow host permissions and sharing rules. Keep private
configuration out of reports and external prompts without sharing authority.
This skill grants no extra authority to edit, publish, broaden access or deploy.
