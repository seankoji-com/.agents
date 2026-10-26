# Deterministic org execution

After the org run's authorization and model selection are frozen, run:

```sh
python3 PKG/scripts/org_execute.py --advance --run-config RUN.json --bridge
```

Execution enables native auto-merge on every admitted non-draft PR that lacks it.
There is no auto-merge question or preference picker. Drafts and saved scope
exclusions stay excluded. The read-only command without `--execute` changes nothing.
Repositories that disallow auto-merge return a named failure; do not change their
settings or use bypass to make the flag appear.

Arming is independent of CI or thread resolution. GitHub controls when native
auto-merge fires. On a branch without a conversation-resolution rule, it can merge
with open threads. The scanner still reports those threads for repair. The existing
direct-merge and acceptance gates remain stricter and are not bypassed by this helper.

## Once per admitted org run

The coordinator writes a private `RUN.json` outside jobs and PR worktrees, using its
existing frozen org selection and authorization. No new model choice is made by the
executor. The configuration contains:

| Field | Source |
| --- | --- |
| `org` | Lowercase organization from the authorized scope |
| `run_id`, `thread_id`, `continuous_state` | Existing `continuous.py start` state and its absolute path |
| `authorization_source`, `authorization_sha256` | Saved owner request and its SHA-256 |
| `package` | Absolute immutable installed babysitter package directory |
| `prefix`, `agents_root`, `jobs_root` | Existing installation and private job-state roots |
| `execution_dir` | Absolute private directory for snapshots, receipts, lock and PR workspaces |
| `caller` | Existing coordinator identity: actor, installation ID, workflow `babysitter/org`, package digest |
| `job_template` | Fresh, unlaunched org job plan with the frozen selection, one stage and one `babysitter/pr-maintainer` slot |
| `semantic_verifications` | Optional PR URL to coordinator-owned evidence reference: absolute `path`, `sha256`, `bytes` |
| `external_blockers` | Optional PR URL to named dependency holds, each with `name`, `dependency`, `detail`, `next_check_at`, `reopen_when`; remove explicitly when reopened |

The template is the ordinary plan from `references/job-plan.md`, including its
selection/admission records and constraints. It must authorize `read`, `push`,
`communicate` and `merge`; it must not contain launched work or a requested final
review. The executor gives each matching PR its own deterministic job ID, exact PR
authorization, initial head, requirement and bound triage snapshot. Existing jobs
are resumed through their pins. It calls the installed `job_cli.py create`,
`overview` and `prepare`; missing choices, stale admissions, altered packages or
ledger failures stop that PR before writes. It never fabricates an admission,
replaces a broken job, or marks a stage accepted.

For all non-draft PRs including forks, the saved continuous scope must include forks
(`continuous.py start --include-forks`). A previously narrower scope is still
enforced. Explicitly requested final review uses the normal coordinator path;
arming auto-merge could otherwise land an unreviewed head.

## Host transport

T3 calls stay in the active harness's native tool runtime. An adapter can call the Python
`execute(report, api, host, jobs, config)` function with `host.call(name, arguments)`
bound to those tools. Normal MCP structured/text results are unwrapped without
starting a shell MCP client or provider process. Without an enclosing adapter, the
CLI reports `t3-machine-transport-unavailable` before scanning or writing.

Codex code mode has a shipped adapter, `PKG/scripts/org_bridge.js`. Load that trusted
file in `functions.exec` and supply its `tools` object and literal argv. For example,
with absolute `packagePath`, `runConfig` and `workdir` already resolved:

```javascript
const quote = s => "'" + s.replace(/'/g, "'\\''") + "'";
const source = await tools.exec_command({
  cmd: "cat " + quote(packagePath + "/scripts/org_bridge.js"), workdir,
  max_output_tokens: 5000
});
if (source.exit_code !== 0 || source.original_token_count > 5000)
  throw new Error("Read the complete bridge source before evaluating it.");
const invoke = new Function("tools", "options", source.output);
text(await invoke(tools, {
  argv: ["python3", packagePath + "/scripts/org_execute.py", "--advance",
    "--run-config", runConfig, "--bridge"],
  workdir
}));
```

The adapter quotes every argv element before starting Python, forwards only the six
allowed native T3 tools, and never interprets PR text as code. It records the helper
PID, bounds the bridge lifetime and stops that exact helper on bridge failure.
Python records write reservations before any tool request. Long capability
responses work through the PTY without echo or canonical line truncation. The small
model runs this fixed program and reads its returned report; it does not choose
which tool to call for each PR.

For a read-only bridge probe, use argv `python3 PKG/scripts/org_execute.py --bridge
--probe`. It calls only `orchestrator_capabilities`, reports the actual parent thread
and dispatch capability, and starts no agents. A live probe succeeded on 25 October 2026;
paid worker execution still needs its own verification.

No provider SDK, provider subprocess, top-level thread, or timer is created.
`delegate_task` is the only agent launcher. Fresh `orchestrator_capabilities` must
match the saved parent, target and supported options. Missing custom models get one
catalog search, never a fallback selection. The host's actual task ID and identity
are retained even if they differ from the requested target.

## One pass

1. Scan fresh state with the same serial request/cost/reserve/deadline limits as
   read-only mode. Mutations share that budget and are never automatically retried.
2. Check sibling threads and saved scope. Possible ownership matches stay read-only;
   a partial sibling page stops execution. Parked linked threads are conservatively
   held for coordinator confirmation rather than interpreted from prose.
3. Admit the per-PR job and verify its immutable brief before any write. Reserve
   `auto-merge` in the existing continuous ledger, recheck open/non-draft state and
   head, then call `enablePullRequestAutoMerge` with `expectedHeadOid`. Choose the
   first permitted method in squash, merge, rebase order. A confirmed arm is a
   completed flag write, never a claim that the PR merged. Proven pre-submit
   failures release the reservation; ambiguous outcomes hold it. At most three arm
   attempts per PR head are recorded across sweeps.
4. For repair candidates, prepare the correct repository's isolated PR workspace
   through `pr-workspace.sh` and persist the dispatch inputs, then reserve `fixer`
   immediately before calling T3 `delegate_task` with the
   frozen target, exact options, async mode and stable request ID. The current live
   delegate schema cannot bind an arbitrary checkout. Use supported `isolation:
   "worktree"` and validate the prepared repository, exact observed commit and local
   HEAD before dispatch. The worker must repeat those checks with `git -C` before
   edits. This is an explicit checkout validation path, not host-enforced cwd
   binding. Host isolation starts from a disposable copy of the coordinator repository;
   all repair commands still belong in the separately prepared PR checkout.
   The worker fetches current review comments and follows its pinned definition.
   After workspace preparation and reservation, one additional budgeted lifecycle/head
   read guards every new fixer launch, even when auto-merge was already enabled. A current
   draft is excluded in the ledger; closed or merged PRs are reconciled. Head drift
   or unavailable validation holds the launch. Existing reservations and accepted
   handles remain retained through exclusion.
   Failed final validation rejects the unlaunched reservation. The next advance
   records byte-bound `not-submitted` evidence and charges an ordinary fresh retry.
   Accepted or uncertain work can never use that recovery. Rejections retain
   repair-attempt accounting. The remote read and T3 launch are separate API
   operations, not an atomic GitHub head lock.
   After that read, local authorization, scope, repair identity and ownership are
   checked again against the retained reservation before calling T3.
5. Persist the host receipt, record the actual task handle in the job, then attach it
   to the writer reservation. On later passes, read retained handles with
   `task_status` using host task IDs, never job/request IDs. Terminal original tasks
   with pending later runs retain their writer exclusion. Ingest each terminal
   `summary` exactly once through the pinned job parser, bind its completion to the
   owned request, then settle that reservation with the retained transport. Missing
   results hold; malformed results are retained as failed executions. A lost
   response holds the reservation and records an uncertain job launch. It never
   starts a replacement to recover output.
6. Arm the coordinator's native PR watches and return JSON. The caller ends its turn;
   T3 owns notifications. No script watches in a loop.

Auto-merge writes, branch updates, resolutions and fixers exclude competing writes
through the same continuous ledger. An active fixer can temporarily defer re-arming
if GitHub removed the flag; the executor does not race its writer.
Lightweight GitHub sweeps preserve coordinator-owned human and authorization holds.
Only an explicit coordinator observation can clear them. Exhausted repair and
wait-for-review decisions hold both arming and launch. Fixer reservations map the
job request to the ledger's failure fingerprint, attempt and review-triage status;
new per-PR jobs cannot reset that history. Reservations recheck these gates under
the ledger lock.
Same-head reviewer detail omitted by the org reader also survives the sweep, so
switching from a detailed observation cannot reset the repair fingerprint. An
explicit reviewer list, including an empty list, replaces that detail; a new head
does not inherit it.
Any PR with unknown or incomplete evidence is held before arming or launch. Its
partial row stays in scan JSON but cannot replace the continuous ledger's last
observation: an explicit discovery gap preserves its failure identity and blocks
writers until a complete read returns. Other fully observed PRs can still proceed.

Every advance reconciles known PRs omitted by open-only discovery with targeted
lifecycle reads. Draft, scope and ownership changes keep existing task/result history.
PRs rotate at the start of each wake, so bounded API exhaustion cannot always starve
the last repository. A failed PR does not stop reconciliation/refill for other PRs.

Retries derive counters and findings from the existing job and continuous ledger;
no model-maintained maps are needed. Preserved local commits and dirty worktrees
are handed back to the worker for fetch/integrate/revalidate, never reset to recover
from ordinary head movement. Update and merge actions execute `merge-pr.sh` under
the same reservations. An update requires fresh gates; a merge command still needs
an authoritative later lifecycle read. Unknown helper writes retain their holds.

`needs-semantic-verification` returns the exact head, base, subject digest, request
ID, findings and result transport. The coordinator inspects those concerns and
supplies a referenced JSON object with `pr`, `head_sha`, `base_sha`,
`subject_sha256`, `request_id`, nonempty `verification`, `findings` and `threads`.
Each finding disposition names `finding_id`, `finding_sha256`, and `disposition`.
Each verified thread names `id` and an evidence-backed `reply`. Evidence lives
outside jobs and PR workspaces; its hash/size and current subject must match. The
executor records those dispositions and invokes guarded reply/resolution commands.
Set `repair_required: true` for a verified concern needing another repair round.
The ledger retains that concern across observation and thread changes. A successful
repair result or head/base movement requests fresh semantic verification, preserving
the concern and repairing request ID. Only a current-head/base/subject/latest-request
coordinator proof with `repair_required: false` clears it, including author-pushed
fixes that need no worker. Repair and verification run before thread resolution.
Worker assertions alone never dispose findings or resolve a conversation. Head,
base or producing-result changes invalidate affected judgments.

Execution `complete` means a bounded advancement finished without holds, outstanding
semantic requests or a missing requested schedule receipt. Active fixers, queued
checks, scope exclusions and event-only gaps remain explicit. This is neither stage
acceptance nor proof that the scope merged. Final acceptance still uses `validate_pr.py`.

## Fifteen-minute coverage

Keep the timer in T3 using `continuous.py` and the host scheduler. After one explicit
`--run-config` advance binds the configuration path and digest, `schedule-plan`
generates exactly one pinned command:

```sh
python3 PKG/scripts/org_execute.py --advance --continuous-state STATE.json --wake-kind schedule --bridge
```

Run that argv through the native bridge above; append the actual host wake ID when
available. A changed configuration needs one explicit `--run-config` advance.
Record the schedule receipt, next run time and stop operation
through the existing contract. Late scheduled execution after cancellation or
schedule revocation is rejected. A manual command is a manual continuation, not
proof of scheduled coverage. Keep configured queue-age/stall diagnoses in the
coordinator; this smaller scanner supplies no queued-job creation clock.

Offline fixtures cover multi-wake dispatch, completion, ingestion, verified
disposition, current-head CI and observed merge, concurrent PRs, duplicates, drift,
unknown outcomes, missing results and a relocated installed package. They do not
prove live paid-provider execution, checkout permissions, fixer pushes or scheduled delivery.
