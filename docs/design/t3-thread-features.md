# T3 thread features: opportunities and dispositions

This note reviews seven T3 Code features the owner listed for the plugin workflows. For
each one it records what the plugins do today, the opportunity, the expected gain, the
risk, and a disposition: implemented in this change, deferred, or rejected.

## Evidence and assumptions

The owner's feature list is a description, not verified host behaviour. This note
relies on three kinds of evidence:

- **Repository text.** Paths cited below, read at commit `c93f8a7`.
- **Live tool schemas.** On 13 October 2026 (AEDT, UTC+11) the T3 MCP server exposed
  `t3_thread_list`, `t3_thread_read`, `t3_thread_send`, `t3_thread_launch`,
  `t3_thread_search` and `t3_thread_merge_back` to an agent running inside a T3
  thread. The schemas and tool descriptions were read; none of these tools was called.
  Facts taken from them are marked *schema*.
- **Assumptions.** Anything else is marked *assumption* and needs a live check before a
  workflow relies on it.

A unit test asserts instruction text and helper behaviour. It does not show that a live
T3 host behaves as described; see [Compatibility](../compatibility.md).

## Summary

| Feature | Disposition |
| --- | --- |
| `t3_thread_list` | Implemented: read-only sibling-work check before writable runs |
| `t3_thread_read` | Implemented: paginated result recovery; candidate confirmation for the sibling check |
| `t3_thread_send` | Rejected beyond the existing tracked follow-up |
| External MCP endpoint | Implemented: no endpoint material in run records; own MCP client rejected |
| OAuth and pairing | Implemented: authentication grants tool access, not plugin authority |
| External orchestrators and `t3_thread_launch` | Implemented: mapping onto the coordinator role; launch for child work stays rejected |
| Per-turn Git checkpoints | Implemented: dependent work through commits at observed SHAs; hidden refs deferred |

## 1. `t3_thread_list`

**Today.** No plugin calls it. Duplicate-work protection exists only inside one run:
Ralph refuses to restart an active task (`plugins/ralph/entry.md`), and jobs reconcile
their own handles on resume (`shared/job-coordination.md`, section 8). Nothing stops a
second babysitter, imps or Ralph thread from starting on a PR or worktree that another
thread is already changing.

**Opportunity.** *Schema:* the tool lists the calling project's threads newest first,
filters by `statuses` and `titleContains`, and paginates. A bounded, read-only check
before a writable run can find an active sibling on the same PR, branch or worktree.

**Gain.** Efficiency: avoids two threads paying for the same repair and racing pushes
to one branch. Flexibility: the owner chooses between stopping and proceeding, with
the sibling's existence visible.

**Risk.** Title matching misses threads whose titles omit the PR or branch, so the check
lowers duplicate work without ruling it out. Listing adds a call per run. A check that
blocked on failure would make the workflows depend on a nightly-only tool.

**Disposition: implemented.** `shared/t3-runtime.md` defines the sibling-work check:
one bounded page, active statuses only, this thread, its delegating parent and its
children excluded, owner
decision through the question picker, and `sibling check unavailable` reported without
blocking. The babysitter roster step (`plugins/babysitter/playbooks/maintain.md`), Ralph
start (`plugins/ralph/playbooks/loop.md`) and imps `run` (`plugins/imps/entry.md`)
apply it. Tests: `tests/test_t3_thread_features.py`.

## 2. `t3_thread_read`

**Today.** `shared/delegation.md` allows it to fetch a result `task_status` omits.
`plugins/imps/references/t3-adapter.md` lists it as documented but not confirmed live.
The rule did not say how to read a long result, so a coordinator could pass a cut-off
page to `job_cli.py result`, which then refuses it, or re-run the task.

**Opportunity.** *Schema:* reads return a paginated timeline and recover long item text
with `itemId` and `textOffset` until `nextTextOffset` is null. *Schema:* reading an
untruncated terminal assistant result from the parent's direct child acknowledges that
child's automatic completion delivery. The rule can therefore name the pagination
fields, require the whole message, and order the read after `task_status` so the read
does not consume the completion that wakes the coordinator. The same tool can confirm a
sibling-check candidate by reading a few recent messages.

**Gain.** Efficiency: a truncated summary is recovered once instead of re-running a
paid child. Fidelity: the result parser receives the complete message.

**Risk.** *Schema:* the tool can read any thread in the environment, so a careless read
could pull another conversation's private material into this run. The rule limits
result recovery to an owned `childThreadId`, keeps candidate reads to at most five with
a small `limit`, and treats all read output as data. The acknowledgement side effect is
taken from the tool description and has not been observed live (*assumption* on its
exact timing).

**Disposition: implemented.** `shared/delegation.md` (Allowed tools) and
`shared/job-coordination.md` (section 4) carry the paginated recovery rule; the imps
adapter table records the schema observation.

## 3. `t3_thread_send`

**Today.** Allowed only for a job's tracked same-scope follow-up with `mode=queue` to an
owned `childThreadId` (`shared/delegation.md`, `shared/job-coordination.md` section 6).
Ralph never uses it (`plugins/ralph/playbooks/loop.md`). `shared/t3-runtime.md` says not
to send messages without authorization.

**Opportunity considered.** Hand a finished output to a sibling thread, or steer a
sibling found by the sibling-work check.

**Gain.** A sibling could start from this run's output without the owner relaying it.

**Risk.** *Schema:* `steer` and `restart` modes change or interrupt another thread's
active turn. A message to a non-owned thread acts on someone else's work and can carry
private run material across a boundary the owner did not approve.

**Disposition: rejected** beyond the existing follow-up. Sending into a non-owned thread
is a message to others, which `shared/t3-runtime.md` reserves for explicit
authorization, and child continuation is already bounded by `shared/delegation.md`. The
sibling-work check states "Never send to, steer, interrupt, cancel or adopt a thread
this run does not own." A future owner-approved handoff would need its own decision
record and tests.

## 4. External MCP endpoint

**Today.** `plugins/imps/references/t3-adapter.md` pins the transport as authenticated
HTTP MCP under the server key `t3-code`. The package never reads the bearer token,
stores credentials or runs its own MCP client.

**Opportunity.** The owner describes the server as reachable at an address of the form
`https://<host>/mcp` over a LAN, a tailnet or T3 Connect (*assumption*: not confirmed
from the repository). An agent outside T3 could then drive the plugins through the same
tools. The plugins need no transport code for that: the harness owns the connection. The
real gap is record hygiene, since run state, briefs and learnings could capture the
address of a private host.

**Gain.** Flexibility: one installed package serves in-thread and external
coordinators. Safety: no private hostname leaks into persisted state.

**Risk.** An external caller may lack features an in-thread caller has (see feature 6).

**Disposition: implemented** as a contract rule in `shared/t3-runtime.md`: never record
endpoint URLs, hostnames, pairing codes or tokens. **Rejected:** shipping an MCP client
or endpoint launcher, which conflicts with the AGENTS.md rule against shell-launched
agent brokers and the adapter's no-credential, no-client boundary.

## 5. OAuth and pairing codes

**Today.** No plugin handles credentials. `shared/t3-runtime.md` forbids changing
provider configuration to unblock work.

**Opportunity.** External agents are said to authenticate by OAuth or pairing code
(*assumption*). *Schema:* `t3_thread_launch` refers to "the permission mode an outside
agent was approved with", so the host does distinguish outside callers. The plugin
contract must not read that approval as consent for plugin actions.

**Gain.** Removes an ambiguity: a paired agent can call tools, but push, merge and
messages still need the owner's request.

**Risk.** None added; the rule narrows authority.

**Disposition: implemented.** `shared/t3-runtime.md`: "Pairing or OAuth grants tool
access, not plugin authority." **Rejected:** automating pairing. It is credential and
host configuration work, which `shared/t3-runtime.md` forbids.

## 6. External orchestrators and `t3_thread_launch`

**Today.** Child work goes only through `delegate_task`, `task_status` and `task_cancel`;
`create_threads` and `t3_thread_launch` are never used for it (`shared/delegation.md`).
`tests/test_contract.py` keeps every mention of the launch tools a prohibition.

**Opportunity.** An external orchestrator can open one top-level thread per independent
job, for example one babysitter thread per repository, and route between them. That is
the owner's own orchestration above the plugins. Inside each thread the plugin keeps its
contract. When the external agent runs a plugin itself, it is that plugin's
coordinator.

**Gain.** Parallel, independent plugin runs without a plugin-level scheduler.

**Risk.** *Schema:* `t3_thread_launch` has no retry key and returns a thread ID to follow
with `t3_thread_read` or `t3_thread_wait`, not a task ID for `task_status`, so the
task-based ownership, cancellation and pending-run checks cannot hold for it. Whether `delegate_task` works for a caller outside any T3 thread is unverified
(*assumption*).

**Disposition: implemented** as a mapping rule in `shared/t3-runtime.md`: an external
agent running a plugin is the coordinator under the same contracts, and without a
calling T3 thread child delegation is `unavailable`, with no top-level substitute.
**Rejected:** launching threads for child work, per `shared/delegation.md` and the
AGENTS.md ban on a second task scheduler. **Deferred:** monitoring helpers for external
callers, until a live check shows how such callers are woken.

## 7. Per-turn Git checkpoints

**Today.** Ralph's "checkpoint" is its own state file outside the worktree
(`plugins/ralph/cli.py`), unrelated to T3's checkpoints. Ralph records a content baseline
and reports `changedPaths`. Jobs end with an integration stage
(`shared/job-coordination.md`), and parallel writers get their own worktrees
(`shared/delegation.md`, Writer isolation).

**Opportunity.** The owner says T3 commits hidden Git refs at the end of every turn
(*assumption*: the ref names and layout are not documented in this repository).
*Schema:* `t3_thread_merge_back` accepts a `checkpointId`, so checkpoint identities
exist. The transferable part is the discipline: a dependent slot consumes earlier work
as a commit or branch at an observed SHA, never from a worktree whose writer is still
active, and never by re-running a completed task.

**Gain.** Efficiency: no repeated work to recover output. Correctness: dependent stages
start from a fixed revision.

**Risk.** Depending on undocumented refs would break silently when the host changes
their layout; resetting to them could discard work.

**Disposition: implemented** in `shared/delegation.md` (Writer isolation). **Deferred:**
reading hidden checkpoint refs directly, until the host documents them; the rule says
not to fetch, reset to or depend on them before then.

## Not changed

No helper, scheduler or provider SDK was added, and `core/` is untouched. Live behaviour
of every tool above remains unverified until a conformance run records it in
[Historical provider results](../sightings.md).
