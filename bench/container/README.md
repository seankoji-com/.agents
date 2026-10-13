# Issue 28 S1b container

This directory contains the isolated runtime and deterministic preflight for the
issue 28 v2 benchmark. It does not start any of the 24 quality runs.

`benchctl.py up` stages only this directory's runtime files and the pinned T3
program into `/tmp/t3-issue28-container-results/<run-id>/build-context`, then
builds a fresh image. It creates one internal network for the agent and synthetic
GitHub fixture. The agent has no external network. The model gateway is the only
container attached to both the internal network and an external bridge; it accepts
only Anthropic Messages or OpenAI Responses requests with the exact IDs discovered
from that isolated server and frozen in its private per-run manifest. Provider TLS remains verified on both sides. The
agent trusts only the generated gateway certificate for requests to that gateway.

The runtime env file is checked for regular-file type, owner and mode, then passed
directly to Docker as `--env-file`. This program never reads or prints its values.
The image and build context contain no provider credentials, provider homes,
owner settings or transcripts. Every run gets fresh provider/XDG state, workspace,
T3 state, and raw-results directories. A task-local npm cache may be created under
the isolated home; it is directed to `/tmp` and contains no owner data. The resource manifest and private logs
are mode 0600 beneath a mode 0700 results directory.

Run the offline fixtures before `up`. `up` starts the no-model environment only;
the T3 endpoint remains container-local and is not published on the host. Then run
`smoke <run-id>` to check the input digest, assigned write and helper, synthetic
GitHub route, gateway TLS, direct provider egress denial, host-loopback exclusion
against a temporary loopback fixture and the headless T3 response. Each negative
needs its container-side positive from the same run: the same TCP probe must reach
the gateway, and `host.docker.internal` must resolve to a non-loopback address.
The smoke also checks the gateway recorded zero provider requests of any kind,
token estimation included. Use
`down <run-id>` to stop its three containers and remove its two networks. Do not
run the quality plan from this stage.

`driver.py --catalog-only` obtains the container's live T3 catalog through its
supported MCP HTTP endpoint using an OAuth PKCE client session approved with a
locally minted one-time pairing credential. It discovers the exact Haiku and Luna
IDs and low/standard options from that isolated catalog, then the host freezes
them in a private read-only per-run manifest and restarts the gateway against it.
The stage compatibility shard is not executable runtime policy. The launch driver
requires the live launch schema to carry all policy and authority fields; missing
model, options, runtime mode or workspace fields block before dispatch. The network
gateway remains the outbound enforcement boundary for parent, child, retry, repair
and resume API requests, including native provider children.

The server starts from `/bench/ws` with its boolean auto-bootstrap flag and a
synthetic Git repository. If project listing is still empty, the driver uses the
server's supported pairing-code OAuth decision with `full-access` for one isolated
project-create setup call, then verifies there is exactly one project before launch.
Canary launches keep `runtimeMode=auto` and `interactionMode=default`.
`driver.py --project-preflight` runs this project check without dispatching a model.

The Codex CLI config uses its supported `model_providers.*.base_url` setting for
the gateway. Claude Code uses `ANTHROPIC_BASE_URL`. If either CLI or T3 ignores
those endpoints, canary work stops. No TLS verification bypass or direct-network
fallback is permitted.

Repair6 keeps every earlier attempt. The controller requires current source hashes
matching the freshly built image before dispatch. Expected websocket upgrades are
refused without forwarding or locking HTTPS fallback, and are recorded separately
from policy violations.

Parent/user messages are selected by their documented message type. The outside
OAuth client cannot call thread-owned `task_status`; the canary parent must obtain
complete terminal results using its authenticated tools before finishing. The
controller takes a read-only SQLite backup of the pinned isolated T3 projection,
then copies it outside all worker mounts and checks the actual structured tool
records, exact targets, pending work and visible descendants. Unknown storage
layouts stay blocked. This adapter neither dispatches tasks nor modifies app state.
Provider-native lifecycle coverage remains explicitly unverified when no independent
observation exists; app-owned task records do not prove that hidden native channels
are absent.

The gateway records only response model IDs and numeric usage fields from complete
provider envelopes. Missing, malformed or mismatched response identity fails the
model audit; missing usage stays null with a reason (see Pass 12). Request counts are never token
usage. Transcript availability is reported separately. Synthetic fixtures prove the
parser only; live runs must supply their own observations. Native Haiku startup is
pinned to thinking off with the pinned CLI's supported controls and independently
checked at the API boundary. No guard, TLS check or model tier is relaxed.

Repair7 retains all earlier failures and adds exactly one declared native read/hash child per provider canary. Inheritance uses the frozen parent model/options; the gateway checks every inference before forwarding. The host snapshot must show exactly that native probe, its actual model/options, terminal state, expected input hash and no pending approvals or unexpected descendants. Missing native evidence blocks acceptance. App-owned children must be reconciled through their authenticated parent; cancellation is recorded separately from successful boundary output.

Format-only `output_config` accepts the documented JSON-schema shape and empty/default configuration while thinking=false continues to reject effort, task budgets and other output controls. Token estimates receive the same model/options checks, are labelled separately and never contribute inference usage. SSE bytes and heartbeats are relayed as received; started, complete and failed requests are correlated. Incomplete streams leave usage unverified. Private raw transport exports use an owned container read into host-owned0600 observations outside worker mounts.

Pass 8 retains all earlier slots and adds a pre-dispatch observation boundary gate.
Network smoke does not establish that a native worker cannot rewrite T3's store.
The pinned runtime currently has no verified native denial probes for that store;
`observer_boundary_preflight` therefore remains unverified and canary dispatch is
blocked. A successful unit fixture, permission-mode name, or copied database must
not set this gate to passed. Establish the supported process/filesystem boundary
and actual native positive/negative controls before any new inference.

Real provider keys are injected only into the gateway container. Agent programs
receive synthetic client credentials; the gateway strips client authentication
and supplies its own provider header. Primary `/v1/models/<selected-id>` metadata
is fetched without inference and frozen before dispatch. Response IDs are compared
exactly with that record; absent metadata blocks dispatch. No prefix matching or
model substitution is used for response acceptance.

The exact pinned native token-count query is allowed as token estimation, with
all option guards retained. Other query forms are rejected. Upstream failures,
downstream stream cancellation and policy rejection have distinct metadata; a
transport failure retains incomplete accounting and does not silently retry.
Only successfully completed children can pass the quality gate. Wait timeouts
retain the accepted identity and permit wait/read recovery only.

Pass 10 (13 October 2026) changes:

- The gateway accepts only documented top-level request fields for each route
  (`/v1/messages`, `/v1/messages/count_tokens`, `/v1/responses`). Any other
  field is rejected and locks the gateway; the event logs field names only, never
  values. `speed` and `inference_geo` keep their premium-control reason, premium
  `anthropic-beta` and `openai-beta` tokens are rejected, and the option guards are
  unchanged. Pass 11 adds a check on nested tool definitions (below). The
  list comes from provider documentation and the pinned CLIs' known request
  shapes, not a live capture, so a field the pinned CLI sends that is missing
  from the list fails the canary closed.
- Preflight checks that the running T3 server resolves its default and configured
  `claude`/`codex` commands to `native_exec.py`. Canary acceptance reads the
  coordinator-only `native-launches.jsonl` and needs at least one new worker-UID
  shim launch of the provider CLI under test. A missing, unreadable or malformed
  log fails closed. If T3 reuses a provider process started before the canary,
  the check stays unverified.
- Each app-owned child's projected thread and run `modelSelection` must match
  the frozen target exactly. The parent's `delegate_task` input alone does not pass.
- A refused or unsupported tracked continuation is recorded but
  never counts as a pass, even when the host observed the original summary unchanged.
- The canary summary rejects duplicate keys and non-finite numbers.
- An oversize provider stream is recorded as `upstream-failure`.
- If the replacement gateway's identity cannot be recorded after three attempts,
  containers matching the run labels and exact name are force-removed and the
  command fails. The bootstrap identity moves to `retired_resources` first.
- Limitation kept: any provider non-2xx locks the gateway. A transient 429 or 529
  therefore ends the finite canary as unverified; it is never retried.
- Unverified: smoke shows that the agent network cannot reach the task-owned host
  loopback fixture. It does not prove that every host-network service is
  unreachable.

Pass 11 (13 October 2026) changes:

- Every `tools` value must be a list of client-executed tools. Anthropic tools
  need no `type` or `type: "custom"`; OpenAI tools must be `function`, `custom` or
  `local_shell`. Server tools (web search or fetch, image generation, computer
  use, code execution or interpreter, file search, MCP, tool search) and unknown
  types are rejected before upstream and lock the gateway. The event logs tool
  type names only. Claude Code 2.1.296 sent 25 tools without a `type` in an
  offline capture.
- The bench Codex config sets `web_search = "disabled"` and turns off the
  default-on `image_generation`, `computer_use`, `fast_mode`, `ultrafast_mode`
  and `browser_use` features that the pinned Codex 0.162.1 lists.
- The pinned T3 projects one thread but no run rows for provider-native children
  (3 of 3 completed native children in a live store had none). The native probe
  therefore records `native_runs_projected` (`none` or a count) and does not
  claim run evidence it lacks. It still needs the completed subagent row,
  `completedAt`, the exact hash and the child thread's exact selection
  (`native_thread_selection`). Any projected native run must be completed with
  the exact selection (`native_runs_terminal_if_projected`).
- App-owned children always have runs. Each child thread needs at least one
  projected run, one `completed` run, and no run outside completed, failed,
  interrupted or cancelled. No observed descendant thread may have an active
  run. A cached terminal `task_status` does not override a live run.
- The canary summary also rejects numbers that overflow to infinity, such as
  `1e999`, at any depth.
- A manifest write error (`OSError`) while recording the replacement gateway
  counts as a failed recording. The scoped label-and-name cleanup still runs,
  even if its receipt cannot be written.

Pass 12 (13 October 2026) changes:

- `smoke_helper.py` opens each directory below `/bench/ws` and the output file
  with `O_NOFOLLOW`. It refuses a symlinked output or ancestor and any output
  that is not a single-link regular file. Canary acceptance applies the same
  rule: `assigned_helper_output_valid` needs a non-link `helper.json` whose
  resolved parent is the physical `canary/<provider>/task-1` directory, and no
  link may exist below `canary/<provider>/`. `workspace_write_scope_valid`
  rejects any added or changed symlink and any symlink in the assigned directory.
- Every resource-manifest write goes through `write_manifest`. It writes a
  same-directory temporary file, flushes and fsyncs it, sets mode 0600, replaces
  the manifest with `os.replace` and fsyncs the directory. A failed write removes
  the temporary file and leaves the last good manifest byte-identical, so `down`
  can still read it. `configure_gateway` no longer rewrites the manifest after
  the replacement identity is recorded.
- `usage_complete` needs `input_tokens` and `output_tokens` on every Anthropic
  Messages and OpenAI Responses inference row. Rows keep whatever counters were
  observed. `usage_reason` is `usage-absent` when no row has usage and
  `usage-partial` when any row lacks a required counter; `reason` carries it once
  response identity is verified.

Pass 13 (13 October 2026) changes:

- `workspace_inventory` records every entry below the workspace by type without
  following links: directories, regular files with a SHA-256, symlinks with their
  target, and FIFOs, sockets, devices or other types by kind. A directory that
  cannot be listed is marked `unlisted`. `workspace_changes_since` reports each
  added, deleted, modified or type-changed entry with its before and after
  record. `workspace_write_scope_valid` accepts changes below
  `canary/<provider>/task-1/` only when they are files or directories. Outside
  that directory it accepts only the creation of `canary`, `canary/<provider>`
  and `canary/<provider>/task-1` as directories. An empty `.git/index.lock`
  directory, a FIFO, or a removed or retyped entry fails the canary. The no-model
  smoke applies the same type-aware rule to `smoke/task-1`.
- Every resource that `up` creates (image, both networks, the bootstrap gateway,
  the GitHub sidecar and the agent) and the replacement gateway go through one
  recorder. It inspects the object, checks the exact name and run labels, and
  commits the immutable ID to the manifest. It makes up to three attempts. If the
  ID is still not committed, or the create command itself fails, the recorder
  removes whatever matches the run labels and exact name, saves a receipt when
  it can, and fails. The last committed manifest stays valid for `down`.
- `write_manifest` raises only for failures before `os.replace`; in that case the
  old manifest is unchanged and nothing new is recorded. If only the directory
  fsync after `os.replace` fails, the new manifest is committed. The writer adds a
  `manifest_durability_uncertain` note, rewrites once on a best-effort basis, and
  returns `False`. Callers treat the identity as recorded. A log-file error after
  the commit no longer turns a recorded identity into a failure.
- `down` marks a recorded object as `already-absent`, not as a mismatch, when
  Docker inspect reports that exact immutable ID as missing. An inspect timeout
  or another unreadable result marks only that resource
  `inspection-failed-preserved`, and cleanup of the rest continues. The
  short-lived `--rm` provenance probe containers now carry the run labels.
- Live risk: the stricter workspace rule also counts directories that T3 or a
  provider CLI creates in the workspace during a canary. No live run has checked
  this yet.

Pass 14 (13 October 2026) changes:

- Every inventoried workspace entry, and the workspace root itself (key `.`),
  now carries its mode bits, owner UID and GID; regular files also carry their
  link count. A chmod or chown anywhere outside `canary/<provider>/task-1/`
  (`.git` set to 0555, the root, a Git file) fails the canary, as does a hard
  link made to a file outside that directory. Inside it, entries may be added or
  deleted; of the entries that already existed, only `helper.json` may change,
  and only as a regular file. The smoke snapshot records the same metadata,
  rejects an unreadable entry outside `smoke/task-1`, and lets only its own
  `result.json` change.
- Before each create, `up` commits a write-ahead intent (`pending_resources`:
  kind, exact name, run labels); if that write fails nothing is created. The
  committed identity clears the intent in the same write. Cleanup receipts now
  keep the exact labels, name, kind and every matched and removed immutable ID.
- `down` reconciles every intent and receipt (`pending_resources`,
  `unrecorded_resources`, `gateway_replacement_unrecorded`) by run labels and
  the role's exact name: lookup, removal, then a second lookup that must come
  back empty. An entry naming another kind, name, run or label set blocks
  `down`. A final label-only lookup across containers, networks and images must
  also be empty; it reports leftovers, such as an interrupted provenance probe,
  but removes nothing. Until all of this holds, the status stays
  `cleanup-failed`.
- An unavailable `docker logs` result is no longer read as zero: the smoke fails,
  a canary is blocked before its slot is used when either baseline count is
  unavailable, and a missing count after the run fails the GitHub and gateway
  gates. The preflight passes only with every named profile and CLI check
  present and exactly `true`.

Pass 15 (13 October 2026) changes:

- The first manifest that `up` saves already holds empty `created_resources`,
  `pending_resources` and `unrecorded_resources` maps. A controller killed right
  after the first image intent therefore leaves a manifest that `down` accepts.
  `down` also treats a missing `created_resources` map as "nothing recorded", so
  a pending-only manifest written by an older controller is reconciled the same
  way. A recovery map of the wrong type still blocks `down` before any Docker call.
- The host snapshot now records command executions and `file_change` items for
  every thread in the tree, the parent included, without output or file content.
  `helper_invocation_observed` resolves the primary task to the child thread the
  parent dispatched (its subagent rows and `task_status` must agree on one
  thread) and requires exactly one helper run, which must be in that thread and
  succeed. A helper run by the parent, a boundary reader, the native probe, a
  follow-up in another thread, a grandchild or an unknown thread fails the check.
  The new `host_recorded_writes_bound` gate fails the canary when any thread
  other than the primary records a file change.
- Remaining limits: writes made through shell commands and GitHub requests are
  not attributed to a thread (the sidecar sees one container), and a follow-up of
  the primary task shares the primary's thread, so a helper run made only during
  that follow-up is indistinguishable by thread.

Pass 16 (13 October 2026) changes:

- Before dispatch the controller freezes a finite role protocol under the
  host-only `protocol/` directory (mode 0700, file 0600) and records its SHA-256
  in the canary attempt. The protocol names every finite role, its exact marker
  line (`ISSUE28_CANARY_ROLE=primary`, `...=summary-32767|32768|32769`,
  `...=native-probe`), the exact scope token an app child's task or the native
  prompt must carry (the helper command or the fixture path), and the complete
  frozen assignment literal: the `task` string for each app child and the `prompt`
  string for the native probe. The canary prompt embeds every literal verbatim and
  tells the parent to dispatch it byte for byte, with no added, removed, quoted or
  reformatted text. `frozen_protocol_is_valid` rejects a role whose template is
  missing or that does not carry its own declared marker line and scope token.
- Acceptance binds every finite role to the *captured dispatch assignment*: the
  host's recorded `delegate_task` input for each accepted task (its `task` must
  equal the frozen literal exactly, and its `target` must equal the frozen target
  with identical raw types, so a boolean option is never an integer) and the
  captured provider-native subagent row (its `prompt` must equal the frozen prompt
  exactly; a missing projection fails closed). Missing, duplicated, conflicting,
  quoted, extra-text or mis-scoped assignments fail closed, and a captured
  continuation (which carries a `childThreadId`) is not a fresh role dispatch.
  This is exact equality of the complete frozen literal, not a marker line plus a
  substring, and it does not use the final report, thread ownership alone or a
  worker-written receipt to classify a role.
- The reported `primary_task_id`, each `summary_boundary_task_ids` value and the
  `tracked_followup` identity must equal that captured assignment authority, so a
  consistent swap of the primary and a boundary reader fails even though the
  unordered set of owned terminal task IDs is unchanged. The helper run and
  file-change gates use the authority primary. The controller retains the
  captured assignments, frozen digest and report mapping in
  `observations/canary-role-audit-<provider>.json` (0600).
- Live risk: the protocol is frozen before launch, so a live run still needs the
  parent to emit the exact marker lines; and a follow-up authored with the same
  marker text as a fresh dispatch would be rejected as duplicated.

Pass 18 (13 October 2026) changes:

- The gateway runs every connection on its own handler thread. One mutex
  (`LOCK_GUARD`) now serializes every lock writer with the single upstream
  admission point (`GatewayHandler._admit_upstream`). The admission point is the
  one place a fully read and validated request is allowed to begin provider work;
  it is taken under the same mutex every lock writer uses, so a request that
  observes an already-set lock is refused before any provider connection, and no
  request can begin upstream work after the lock is set. A request admitted
  before a later lock keeps its already-started `forward-started` accounting.
  Every lock writer uses the mutex: policy rejections and the endpoint/method
  rejections (`_reject(..., lock=True)`), and the non-2xx provider response. A
  bare unsynchronized re-read would not provide this ordering. Immediate SSE
  relay, the provider timeout and the no-automatic-retry rule are unchanged.
- Continuation and owned-task target dictionaries are compared with the strict
  `raw_equal`, so a boolean option is never equal to the integer `0` in
  `CapturedTaskClient.followup_observation` or `verify_owned_tasks`. A
  continuation or accepted task whose `target` differs from the frozen/original
  target only by a `bool`/`int` type no longer matches.
- Live risk: this synchronizes the in-process lock, not a coordinator that
  restarts the gateway; a fresh gateway process starts unlocked by design (the
  isolated probe and canary are separate processes). Offline synthetic tests
  prove the ordering only; no live provider traffic is exercised here.

Pass 19 (13 October 2026) changes:

- `GatewayHandler._admit_upstream` now writes the request's `forward-started`
  event inside the admission critical section. In pass 18 admission returned
  first, so a parallel lock could be logged before that start. Every recorded
  start now precedes any lock, and a refused request records no start. The
  provider connection and SSE relay still run outside the mutex.
- `driver.verify_tracked_followup` requires the resumed continuation's `model`
  and `providerInstanceId` to be strings equal to the launch target's, so an
  integer identity never matches a boolean one.
- Live risk: the start record is written while the mutex is held, so a stalled
  log consumer delays lock writers as it already delays every log line.
  Offline synthetic barrier tests prove the ordering only.

## Quality starts (Stage 6 runner)

Build each package arm once, before the first start of that arm. The arm is made
read-only and later mounted into every start's agent at the same absolute path, so the
rebuilt arm's recorded bundle paths stay valid:

```sh
python3 bench/container/packages.py build --arm baseline --out "$BENCH_PACKAGES/baseline"
python3 bench/container/packages.py build --arm rebuilt --out "$BENCH_PACKAGES/rebuilt"
```

The baseline build installs commit `3cb0d11` with its own installer and fails unless every
digest equals `migration/rebuild/baseline.json`. The rebuilt build refuses uncommitted
changes under `plugins/`, `core/`, `shared/` or `scripts/`. `startctl.py list` prints
the command for all 24 planned starts. One start is:

```sh
python3 bench/container/startctl.py run --scenario engineering-five-stage --arm rebuilt \
    --provider codex --repetition 3 --env-file "$BENCH_ENV_FILE" --results "$BENCH_RESULTS" \
    --packages "$BENCH_PACKAGES/rebuilt" --canary-run "$BENCH_CANARY_RUN_CODEX"
```

Each start gets its own `up`, and `down` always runs. Smoke, preflight and catalog must
pass before launch. Canary evidence is reused only when the linked run has a verified
canary for the provider and the same pinned sources, programs, frozen targets and response
IDs. The parent launches with model-policy role `parent`. For repetition 3 the runner
polls stage-3 commits (baseline) or the job's third stage reaching `accepted` (rebuilt),
interrupts, records whether later work had already landed, and sends `resume` with role
`resume`. The wait has a deadline (default 4 hours). Graders run in a separate
`--network none`, read-only container with `T3_BENCH_ISOLATED_GRADER=1` over copies that
were exported out of the agent. Workflow and negative scenarios need the
`stage_fixtures` adapter; missing delegation also needs `mcp_shim`. Without them the start
is blocked before `up`. The unavailable-review routing seed is built from the linked
canary run's frozen catalog. For babysitter, the sidecar gets its private env file, the
agent trusts one bundle (gateway CA plus synthetic GitHub CA) at its usual CA path, and
`sidecar-observation.json` is written by the runner from the sidecar's own log, never by a
worker. Host aliases such as `github.com` point at the sidecar in the agent container
only, and only when a fixture asks for them. Missing delegation counts only with a
verified `mcp_shim.audit_log`; otherwise the attempt is an infrastructure-invalid candidate.

Private evidence stays under `<results>/<start>/attempt-<n>/private`. `summary.json` and
`attempt-record.json` beside it hold no absolute paths. A second attempt needs
`--retry-infrastructure-invalid REASON` and an attempt 1 marked as an
infrastructure-invalid candidate; the owner still decides whether it qualifies.

Unverified until a live run: T3's `t3_thread_interrupt` and `t3_thread_send` schemas,
the job-state path and stage status names, provider session IDs in projected thread rows
(used to attribute transcripts), and grader access to exported files.
