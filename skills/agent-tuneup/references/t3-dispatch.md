# T3 dispatch preflight

Read before starting a T3 session or delegate, including reviewers, designers,
implementation workers and issue writers. This is a host workaround reported by
the owner on 2 November 2026, not a general property of the underlying models.
Retire it only after the affected routes have been verified fixed. Check the
linked issues below before relying on or retiring each rule.

## Choose a permitted permission mode

Inspect the parent provider and effective runtime mode, then the target's exact
provider identity and supported modes through the exposed T3 contracts. Observe
the host's discovery frequency. Availability is not authority to use a mode.

- OpenCode, Grok and Muse can fall back from `auto` to `ask`, stopping unattended
  work. [pingdotgg/t3code#11458](https://github.com/pingdotgg/t3code/issues/11458)
  tracks the OpenCode case. For authorised new sessions on these providers, explicitly request
  `runtimeMode: 'full-access'` when the parent and host permit it. Do not use
  `auto`, `inherit` or another narrower mode as a fallback. An explicit cap
  below full access makes the route incompatible; apply the filtering or
  named-model conflict rules below. Read-only is a task constraint, not an
  approval mode: forbid reviewed-source, GitHub and live-system changes, while
  explicitly scoping permitted tests and scratch writes under the
  [reviewer brief](../../review/references/reviewer-brief.md).
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
  `never`. T3 maps full access to Codex's `approvalPolicy: "never"`, so a command
  matching a Codex rule with `decision = "prompt"` fails before it starts with
  `approval required by policy, but AskForApproval is set to Never`. T3 closed
  [pingdotgg/t3code#12248](https://github.com/pingdotgg/t3code/issues/12248) as
  an upstream fault; [openai/codex#41068](https://github.com/openai/codex/issues/41068)
  tracks it. Report the error as this gate; changing the user's Codex rules or
  mode needs their authority. Human decisions and tool approvals are separate: use supported
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

## Carry sharing authority with the task

Runtime permissions and authority to share context are separate. Before sending
private material to another provider, check the user's task and standing sharing
instructions for the intended recipients and content. Record the actual source
of authority, its scope and any limits in the delegation brief. A child receives
only its task, so a parent saying "authorised" without that source can lose the
evidence needed by approval review.

Reuse consent that covers this task, provider and material. Do not ask again
merely because the repository is private or a new child receives the same
approved brief. Send the minimum necessary context; prefer a design or review
brief and relevant snippets to whole files. Exclude secrets and unrelated data.
The workflow's delegation request does not authorise unrestricted repository
sharing. A clone's presence or a model's availability does not establish consent.

If authority is missing, prepare the concrete minimal packet and intended
provider roster, then ask once for that scope. A child returns that gap to its
parent. If host approval rejects a dispatch, report the action and stated reason;
use an authorised lower-disclosure brief where sufficient, or obtain the missing
authority. Do not change runtime mode or bypass the host to defeat a rejection.

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
