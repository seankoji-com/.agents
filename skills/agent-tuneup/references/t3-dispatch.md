# T3 dispatch preflight

Read before starting a T3 session or delegate, including reviewers, designers,
implementation workers and issue writers. If [binaric](../../binaric/SKILL.md)
is installed, apply its audience rule to each brief, send and requested reply.
Either way, give each new delegate a self-contained brief.

## Choose the provider by score, then the model by role

1. Before launching a T3 thread or delegate, look for the read-only
   `limits_snapshot` MCP tool, which the gateway may prefix as
   `limits-limits_snapshot`. Call it with `detail: "brief"` through the host's
   configured connection. Record a missing tool, rejected snapshot credential
   or failed observation as a distinct reason for unknown capacity. Connection
   settings belong to the host owner. Keep credentials and personal endpoints
   out of briefs and library source.
2. Apply the hard gates first: lineage independence from every material author,
   explicit model choices, permission and runtime mode, tool support, and the
   models the provider actually offers. Lineage follows the model family, not the
   provider alias: Opus and Sonnet stay Anthropic when routed through AGY.
3. Exclude routes with a confirmed spend cap, rejected upstream credential or
   exhausted quota. Scope the refusal to the affected route or pool. Reopen it
   only when a fresh observation confirms capacity or access. For a pinned
   route, preserve the checkpoint and report the blocker and next check time
   if known.
4. Rank the remaining routes by `providers[].paceScore`. Higher means spend
   that subscription sooner: −100 exhausted, 0 even pace, +100 unused quota
   about to expire. A score of −100 covers only the scored accounts. The snapshot
   leaves model-to-pool eligibility unknown. Rank only scored providers when
   any have scores. Use the caller's static order when every remaining score
   is `null`, and record capacity as unknown.
5. Then match the model to the role's difficulty, never the reverse. Bounded
   mechanical work with deterministic checks takes the provider's smaller model.
   Ambiguous behaviour, shared interfaces, security and state/concurrency work
   take the stronger one. Never choose a model the provider does not offer.
6. Use high effort. Set it through the host's effort or thought-level control
   wherever one exists. Where a route exposes none, as Gemini can, select the
   model variant whose name carries the high reasoning setting. With neither
   control nor variant, keep the provider default and record effort as not
   applicable. A smaller model never means lower effort. High stays the
   default: go to xhigh only on the operator's explicit approval, as in
   Hillclimb's panel-entry upgrade, and never to max.
7. Read `paceBasis` with the number. `upper-bound` comes from a stale reading or a
   missing shorter window, so the true score can only be lower. `headroomNow` is
   the best usable account's smallest remaining fraction and answers whether a
   long task fits now, which the score does not. `availableAt` gives an exhausted
   provider's return, and a predicted reset alone does not establish capacity.
8. Quota evidence never authorises paid overage, a mid-task provider switch, a
   model outside the provider's catalogue, or a threshold you invented. Unknown,
   stale, unsupported and source-failure states all mean unknown capacity; none
   proves exhaustion or healthy headroom.
9. Reuse one snapshot for a dispatch batch, and refresh before later batches,
   retries or replacements. Account for running children; a snapshot is not a
   reservation. Record the observation time, the chosen provider's score and
   basis, and the reason, not the raw account inventory.

## Permission workarounds

These host workarounds were reported by the owner on 2 November 2026, not as
general properties of the underlying models. Retire them only after the affected
routes have been verified fixed. Check the linked issues before relying on or
retiring each rule.

### Choose a permitted permission mode

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
