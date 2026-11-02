# T3 dispatch preflight

Read before starting a T3 session or delegate, including reviewers, designers,
implementation workers and issue writers. This is a host workaround reported by
the owner on 2 November 2026, not a general property of the underlying models.
Retire it only after the affected routes have been verified fixed.

## Choose a permitted permission mode

Inspect the parent provider and effective runtime mode, then the target's exact
provider identity and supported modes through the exposed T3 contracts. Observe
the host's discovery frequency. Availability is not authority to use a mode.

- OpenCode, Grok and Muse can fall back from `auto` to `ask`, stopping unattended
  work. For authorised new sessions on these providers, explicitly request
  `runtimeMode: 'full-access'` when the parent and host permit it. Do not use
  `auto`, `inherit` or another narrower mode as a fallback. An explicit cap
  below full access makes the route incompatible; apply the filtering or
  named-model conflict rules below. Read-only is a task constraint, not an
  approval mode: brief reviewers to make no writes even on full-access routes.
  This owner-adopted workaround overrides the tool's default guidance to omit
  `runtimeMode`, for these affected routes only and within the parent's ceiling.
- T3 forbids a child with broader permissions than its parent. In particular,
  a Codex/ChatGPT parent in `auto` cannot create a `full-access` child. Filter
  out the affected provider routes before dispatch; do not make a known-invalid
  request, retry it, or route through another launcher or thread to evade this.
- If the model is not fixed by the user, choose an otherwise eligible provider
  route within the parent's permissions. Preserve model-family independence,
  capability and budget rules. For a named or otherwise required model, report
  the specific conflict and propose an eligible alternative or an operator-started
  session with sufficient permissions. Do not substitute silently or create a
  new top-level thread without the user's request.
- Codex/ChatGPT in `full-access` can encounter an approval route mapped to
  `never`. Human decisions and tool approvals are separate: use supported
  question tools, or plain text for non-secret decisions, then yield for the
  answer. Use the host's secret-input tool for secrets. If an action requires
  an approval the session cannot obtain, preserve progress and report that
  gate; do not loop on an impossible approval or bypass it.
  Children still return decisions to their parent when their assigned role
  requires that handoff, rather than asking the operator directly.

These names identify T3 provider/driver routes, not model lineages. A model
served through a different driver needs route-specific evidence; an OpenCode
route remains affected regardless of the model it hosts.

Preserve explicit narrower limits. Do not change an existing thread's mode or
global permissions to hide the problem. If no compatible route exists, complete
independent work and report the blocked action. The operator may need to start
or resume work in an appropriate session through T3's supported controls.
After dispatch, verify any exposed effective mode; record unavailable verification
instead of treating a successful launch as proof of usable permissions.

## Keep the execution trace addressable

Record returned task and child-thread IDs, provider/model/options, requested and
verified mode, role and owned scope. Retain failed and cancelled attempts too.
For ship-owned work, include the parent task item and execution start boundary.
Require coordinating delegates to return their complete descendant task/thread
manifest and evidence locations, not just successful coding-worker handles.
Before cleanup, preserve required operational evidence in an authorised parent
artifact location and verify access, or finish its coverage review first.
Keep the manifest's evidence locations current while following host worktree
cleanup rules. Never delete the only copy before it is covered. Never copy credentials or private reasoning
into briefs or public issues. Follow T3's returned `next`; this record does not
authorise polling or further delegation.
