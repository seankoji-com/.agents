# Deterministic org execution

After the org run's authorization and model selection are frozen, run:

```sh
python3 PKG/scripts/org_scan.py --org OWNER --execute --run-config RUN.json --bridge
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
  argv: ["python3", packagePath + "/scripts/org_scan.py", "--org", org,
    "--execute", "--run-config", runConfig, "--bridge"],
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
   frozen target, exact options, async mode and stable request ID. T3 also isolates
   the child from the coordinator checkout; the prompt explicitly names the PR
   workspace as the only writable source checkout. The worker fetches current review
   comments itself and follows its pinned definition.
   After workspace preparation, one additional budgeted lifecycle/head read guards
   every new fixer reservation, even when auto-merge was already enabled. A current
   draft is excluded in the ledger; closed or merged PRs are reconciled. Head drift
   or unavailable validation holds the launch. Existing reservations and accepted
   handles remain retained through exclusion.
5. Persist the host receipt, record the actual task handle in the job, then attach it
   to the writer reservation. On later passes, read retained handles with
   `task_status`; active or result-awaiting work prevents another launch. A lost
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

The executor launches prepared work, not acceptance or semantic finding disposition.
Execution `complete` means the sweep finished without held PRs or terminal tasks
awaiting result reconciliation. It does not mean the org is healthy or merged:
active fixers, queued checks, external ownership and scope exclusions remain explicit
outcomes. Held or result-awaiting work returns exit 3; a completed sweep returns 0.
The existing coordinator ingests terminal results, replies/resolves verified threads,
handles human decisions and charges any retry. It can then use the runner for a new
prepared request. For a retry, retain the PR's coordinator-owned `retry_usage` and
`prior_findings` in the run configuration maps keyed by PR URL; missing records hold
the retry instead of resetting counters. An unknown-only observation never launches
a code fixer.

## Fifteen-minute coverage

Keep the timer in T3 using `continuous.py` and the host scheduler. Use a 900-second
cadence and include this exact execution command in the scheduled prompt:

```sh
python3 PKG/scripts/org_scan.py --org OWNER --execute --run-config RUN.json --bridge --wake-kind schedule --wake-id HOST_WAKE_ID
```

Run that argv through the native bridge above, using the actual wake ID. Record the schedule receipt, next run time and stop operation
through the existing contract. Late scheduled execution after cancellation or
schedule revocation is rejected. A manual command is a manual continuation, not
proof of scheduled coverage. Keep configured queue-age/stall diagnoses in the
coordinator; this smaller scanner supplies no queued-job creation clock.

Offline fixtures cover reservations, default arming, expected-head/draft guards,
duplicate suppression, lost responses, identity retention, and new-PR creation and
preparation through an installed package. They do not prove a live paid-provider
dispatch, isolation permissions, a successful fixer push, or scheduled delivery.
