# Discovery: imps-t3, a provider-neutral imps for T3 Code

Date: 9 Oct 2026 (Australia/Sydney). Source spec, preserved verbatim: `thinking/imps-t3/source-spec.md` (written from a Codex point of view, dated the same day). This document records where that spec was confirmed, corrected or overridden. Where they disagree, this document wins.

## 1. The problem or decision

The operator now works mainly in **T3 Code**, a desktop app that runs Codex, Claude, OpenCode, Antigravity, Grok and other providers in one thread UI. Their main orchestration plugin, **imps** (in `seankoji-com/claude-plugins`), only runs at full strength inside Claude Code: it depends on Claude's `Workflow` tool, `Agent` types and a 2,620-line Claude-only runner script. There is a Codex-only translation, but it uses native Codex subagents that T3 cannot see, and the operator has barely used it.

The goal is a T3-native imps. Any authenticated T3 provider can follow the same workflow from one entry document. Delegated work goes through T3's own orchestration tools, so it appears as T3 task cards and can be cancelled from T3. Workflow state and evidence rules live in a small Python core that runs without a model. imps-t3 is also meant as the **first plugin of a new `t3-plugins` repo**. **babysitter** is named as the second, so the core must be shared and plugin-agnostic from day one.

Drivers, in priority order: (1) T3 is the operator's daily driver, so imps must work well in a T3 thread; (2) cost and quota, so work can run on whichever subscription has headroom; (3) model diversity for review; (4) escaping Claude-only lock-in.

## 2. Requirements and constraints

**Scope: the source spec stays whole.** Every required item in its §5 and all 16 tests in its §14 remain in v1, including delegated implementation, verification-init and the 3x live conformance matrix. The changes below are corrections, relocations and added decisions, not cuts.

**Location (overrides spec §6).** Build in a new repo at `/Users/seankoji/repos/t3-plugins` (currently an empty folder holding only `.claude/`, not yet a git repo), not at `claude-plugins/plugins/imps/t3/`. Layout:

```text
t3-plugins/
  core/              # host-neutral: state, transitions, acceptance/readiness, evidence, path safety, schemas, CLI
  plugins/imps/      # entry.md, playbooks/, references/, templates/, roles schema, imps config defaults
  scripts/install.py # installs any plugin under plugins/
  tests/
```

- **Core purity is enforced.** `core/` must not import from `plugins/` or contain imps vocabulary: playbook names, `implementer`/`reviewer`/`researcher`, bug-fix steps. A test enforces this, so babysitter can consume `core/` unchanged.
- **The core is fresh, not vendored.** It is written to the spec's richer contract: generations, a single run record, a content-hashed dirty-tree snapshot, and fixed ownership. The existing `workflow-evidence.py` copies in claude-plugins stay untouched; the two lines diverge on purpose. Reusing its *ideas* is expected (see §6).
- **Python 3, stdlib only.** No runtime dependencies; schemas are validated by hand-written validators that match the published JSON Schemas. Tests use `python3 -m unittest discover`, matching claude-plugins' convention (`tests/run-python.sh`).

**T3 runtime facts.** These were verified against `https://raw.githubusercontent.com/pingdotgg/t3code/main/docs/orchestration-v2/orchestrator-mcp-server.md` on 9 Oct 2026. Installed locally: `/Applications/T3 Code (Nightly).app`, version `0.0.46-nightly.20261009.2861`. The orchestration surface appears only in nightly and preview tags; no stable release carries it. **Decision: accept the nightly coupling, pin the tested T3 version in the compatibility report, and treat breakage on a T3 update as expected and visible.**
- `orchestrator_capabilities` takes no input. It returns the inherited provider and model, provider instances with advertised models, child-task eligibility, unavailable-provider reasons (disabled, missing executable, missing auth) and feature flags for polling, cancellation and batch thread creation.
- `delegate_task` input is `{task, target?{providerInstanceId, driverKind, model}, title, role: implementation|research|review|design|test|general, mode: async|wait, timeoutMs, clientRequestId, runtimeMode, interactionMode}`. It requires an active parent run, and an explicit `providerInstanceId` fails if unavailable, with no silent substitution. A wait timeout sets `waitTimedOut` and **does not cancel** the child. The result has `taskId`, `childThreadId`, `status`, `workState: working|waiting_for_children|result_available`, a prose `summary` and `resultContextTransferId`. **There is no workspace or worktree parameter, so children inherit the parent's checkout.**
- `task_status` is parent-scoped and rejects IDs from other parents. `task_cancel` stops the child, everything it delegated and its PR watches. Published results stay readable.
- Each review round is a **new** `delegate_task` call with a distinct `clientRequestId`, stable across retries of that round. Never use `t3_thread_send` to the `childThreadId`. This rule comes straight from the T3 doc and the spec already matches it.
- Transport is authenticated HTTP MCP at `127.0.0.1:<port>/mcp` (server key `t3-code`), injected per provider. Env vars: `T3_MCP_BEARER_TOKEN`, plus `T3_MCP_URL` for Pi.

**Corrections to the source spec's T3 assumptions:**
- **`acp-mcp-call` does not exist** in the doc. Drop the spec §9 fallback-transport paragraph. If the MCP tools are not callable, report the capability `unavailable`.
- **`preview_status` / `preview_open` are not documented.** The doc mentions a "preview toolkit" without listing its tools. Discover them by semantics at runtime; if none is found, report browser verification `unavailable` and use a documented alternative.
- **`link_pull_request` is an action of `t3_thread_update`**, not a standalone tool.
- **T3 exposes no PR-watcher tools.** Never claim to use one. Remote PR outcomes are confirmed by direct observation (for example `gh pr view`/checks) at the moment completion is claimed.
- **The structured child result is not returned by T3.** Decision: the child ends its final message with one fenced JSON result block. The parent reads it from `summary`/`t3_thread_read`, writes it as an artifact into run state, and validates it through the core. Claimed changed files and commits are then checked against the actual worktree. This avoids needing the child to write into `~/.local/state`, which its sandbox may forbid.

**Delegated-implementation isolation (unknown, must be live-tested first).** Because children inherit the parent's checkout, the spec's "parent creates task-owned worktrees and passes absolute paths" is the only way to parallelise code tasks. Whether a child provider's sandbox may write to a sibling worktree outside the parent's workspace root is **unknown**. v1 must ship both paths: parallel writers in separate worktrees when a probe shows it works, and otherwise serialised code-writing children in one task worktree, with only read-only work running in parallel. The probe result is recorded per provider.

**Installer (decided).** `scripts/install.py` copies a versioned snapshot of a plugin, **with its own copy of `core/`**, to `~/.local/share/t3-plugins/<plugin>/<version>/`. It writes an ownership manifest and atomically repoints a `current` symlink. The path pasted into T3 is the absolute expansion of `~/.local/share/t3-plugins/imps/current/entry.md`, which stays the same across upgrades. Upgrade = `git pull` then re-run the installer. Rollback = repoint `current`. It supports dry-run and uninstall; uninstall removes only manifest-owned files and never touches run state. Run state lives at `~/.local/state/t3-plugins/imps/runs/<run-id>/`, an adjustment of the spec's `~/.local/state/imps-t3/` to fit the multi-plugin repo. An explicit state root is accepted for tests.

**Review policy default (decided, reduces stalls).** Ship a default fallback chain in imps config. The reviewer is the first available catalog provider that is not the implementer; if none is available, a fresh isolated same-provider reviewer is dispatched through `delegate_task`. The fallback fires **only** on `unavailable`, **never** on an adverse verdict, and the report records which reviewer ran and why. Repository policy that names a specific reviewer overrides this default.

**Cleanup policy (decided).** On success, remove every task-owned worktree, branch, server and watcher. On failure or block, preserve them, and the report lists each one with one exact cleanup command. Evidence under the state dir is never removed by cleanup.

**Blocked states must be actionable.** Every `blocked` result names the precise reason, the exact task IDs involved, and a single copy-pasteable resume step. Independent work continues past a block where the spec allows it.

**Build session and authorisations granted in this session:**
- The build runs **inside a T3 thread on Claude (Opus 5.5)**, as dogfooding. It may use `delegate_task` for its own parallel work, since it runs in T3.
- It may `git init` `t3-plugins`, **create a private GitHub repo `seankoji-com/t3-plugins`**, push a branch and open a PR.
- **Pre-PR gate:** an adversarial review of the branch diff, delegated through `delegate_task` to **Codex** (role `review`, new `clientRequestId` per round). Repair blocker and major findings and re-review before the PR is created. This replaces the spec's `cc:adversarial-review` (a Codex-side rule from `~/.codex/AGENTS.md:16`, which doesn't govern a Claude build).
- It may **install for real** into `~/.local/share/t3-plugins` and `~/.local/state/t3-plugins`. Uninstall tests use temp dirs only.
- It may run the **full live conformance matrix**: every enabled and authenticated provider, critical cases ×3. For conformance only, it may open one top-level T3 thread per provider (`create_threads`/`t3_thread_launch`) so each provider runs as a parent. This exception does not extend to the package's own runtime, where those tools stay banned for child work.

## 3. Tradeoffs discussed and how each was resolved

- **Primary driver.** Daily-driver use favours direct mode; cost/quota seemed to favour delegation fan-out. The point raised: T3 lets the operator pick the *thread's* provider, so direct mode on Codex or OpenCode already spends their quota. The operator still chose to keep delegated implementation in v1. Resolved as: direct mode is primary and must be excellent; delegation ships too.
- **Shared core now vs. extract later.** The case against: designing a platform from one example. The case for: babysitter is a real second consumer, and imps and babysitter already share a byte-identical `workflow-evidence.py` in claude-plugins. Resolved: shared core from day one, with purity enforced by a test.
- **Which repo owns the core.** Options were vendoring the claude-plugins helper with a sync check, writing a fresh t3-plugins core that claude-plugins adopts later, or a fresh core with deliberate divergence. Resolved: **fresh core, deliberate divergence.** The existing helper can't meet the spec anyway (see §6).
- **Nightly API.** Options: wait for stable, abstract the tool surface, or accept and pin. Resolved: accept and pin, recording the T3 version in every compatibility row.
- **Installer depth.** Options: clone-and-point, symlink, or copy plus manifest. The operator wanted whatever is most elegant to install and keep current. Resolved: a versioned copy plus a `current` symlink (§2), which gives a stable entry path, standalone installs and trivial rollback.
- **Stalls vs. fail-closed review.** The operator dislikes stalls at gates, but the spec forbids bypassing adverse verdicts. Resolved: keep fail-closed semantics, ship a default availability fallback chain, and make every block actionable.
- **Litter vs. evidence preservation.** Resolved: clean on success, preserve and list on failure, never delete evidence.
- **Child result transport.** File written by the child vs. JSON in the final message. Resolved: final-message JSON, written to state by the parent (§2).
- **Build provider.** It started as Codex and was changed by the operator to Claude Opus 5.5, for available credits. Consequences: the Codex AGENTS.md gate no longer applies, so the gate became a Codex review via `delegate_task`; the handoff is a plain paste, not `/imps:imps` (§4).

## 4. Alternatives considered and ruled out, with reasons

- **`claude-plugins/plugins/imps/t3/` as the home** (source spec §6). Ruled out by the operator: t3-plugins is to be a multi-plugin T3 repo. Consequence: claude-plugins' `build/generate.py`, `dist/` regeneration and version-bump bot don't apply to this work, and claude-plugins must not be modified by v1.
- **Vendoring `workflow-evidence.py` from claude-plugins.** Ruled out: it has an ownership hole and no dirty-content hash (§6), and the operator chose a fresh core.
- **Building on the existing Codex imps skill** (`claude-plugins/plugins/imps/codex-skills/imps/SKILL.md`, symlinked into `~/.codex/skills/imps` and `~/.agents/skills/imps`). Ruled out: it is Codex-only and its native subagents are invisible to T3. Its fate is **retire later**, as a separate claude-plugins change after imps-t3 proves out. v1 does not touch it.
- **Cutting delegated implementation, verification-init, the 3x matrix or the installer from v1.** Proposed and declined; the operator kept the spec whole. *Superseded, not disproven*: the cost argument (four extra tests, worktree and integration machinery) still holds. Do not re-propose these cuts.
- **`acp-mcp-call` fallback transport, standalone `link_pull_request`, PR-watcher tools, named `preview_*` tools.** Ruled out: not in T3's documented surface (§2).
- **Waiting for a stable T3 release, or an abstraction layer over T3 tool names.** Ruled out in favour of pin-and-record.
- **Starting the build with `/imps:imps` or Codex `$imps`.** `/imps:imps` needs Claude Code's Workflow tool, which T3's Claude provider is not known to expose. `$imps` orchestrates with native Codex subagents, the pattern this package bans. The build is started by pasting the handoff into a T3 thread.
- **`cc:adversarial-review` as the PR gate.** Replaced by a Codex review through `delegate_task` once the build provider became Claude. A same-provider Claude reviewer was rejected for lacking engine diversity.
- **Reviewer fallback that fires on adverse verdicts, or a fixed reviewer with no fallback.** The first is forbidden by the spec; the second was rejected as maximising stalls.

## 5. Explicit non-goals

- No changes to `seankoji-com/claude-plugins` in v1: not imps, not babysitter, not the Codex skill, not `dist/`.
- No babysitter port in v1. The core must merely be consumable by it, which is enforced by the purity test.
- Everything in source-spec §5 "Deferred" stays deferred: T3 marketplace or upstream T3 changes, daemons or schedulers, org-wide babysitting, stacked PRs, deployment automation, transcript mining or memory updates, mandatory design races, a dashboard, cross-thread automatic recovery, distribution to harnesses outside T3.
- No PR-watcher implementation, because T3 has no tools for one.
- No generic MCP client, credential handling or token storage.
- No claim of identical model judgment, quality or latency across providers.

## 6. Prior art

- **`claude-plugins/plugins/imps/scripts/workflow-evidence.py`** (307 lines; byte-identical copy in `plugins/babysitter/scripts/`, more copies in `dist/agy` and `dist/opencode`). Its ideas are worth reusing: `atomic_json` (mkstemp, fsync file, `os.replace`, fsync dir, lines 25–43); flock on `<state>.lock` with a uuid4 owner token and deadline (`state_operation`, 187–240); `recover` requiring `--confirmed-dead` and never heartbeat age; requirement-ID parsing from a "## Definition of done" checklist with `[ID]` prefixes, `[verify:…]` tags, duplicate-ID errors and progress-box exclusion (`contract`, 53–79); `gate_plan`/`gate_record` (123–184), which validate argv, forbid inline interpreters, require a fresh log, and never execute commands. **Defects not to copy:** line 212's `if owner and (not token or …)` lets `patch` write with no claim when no owner file exists; `snapshot` (82–113) records only `clean: not dirty`, with no hash of dirty content.
- **`claude-plugins/plugins/imps/scripts/imps-run.workflow.js`** (2,620 lines, Claude Workflow-tool only). It holds review invalidation (`sameRevision`, 477–479: repo, head, base, spec_hash, policy_hash, clean) and requires `clean === true` (471). The new core ports these *rules*.
- **`claude-plugins/plugins/imps/references/workflow-contract.md`, `diagnosis-loop.md`, `task-sizing.md`, `web-verification.md`.** These are the source vocabulary for requirement kinds (`inspection|command|runtime|manual`) and the diagnosis loop the bug-fix playbook reuses.
- **`claude-plugins/tests/evals/workflow-cases.json`.** 24 orchestration cases with thresholds `candidate_false_completion: 0`, `candidate_regressions: 0`; a useful model for scripted false-completion fixtures.
- **`docs/plugin-value-review.md`** (claude-plugins) rates imps "Conditional": durable state helps substantial work, but a projected ~39k-token invocation overhead makes it costly for small tasks. This is the strongest existing case against the lean: a heavy entry path kills direct-mode usefulness. The spec's `entry.md` < 1,500 words limit and load-on-demand playbooks are the mitigation.
- **Non-Claude ports already on this machine:** the Codex imps skill (above) and `~/.agents/skills/babysitter-{pr,repo,org}`. They show earlier porting attempts used host-native subagents, not T3.
- **pstack** (cursor/plugins): verification generator, maintenance, bug-fix playbook. Adapt ideas only; keep license notices if substantial text is copied.

## 7. Open questions

- **Can a delegated child write outside the parent's workspace root?** This is per provider and is the first live probe. Both design paths ship regardless (§2).
- **Does T3's Claude Agent SDK provider load the operator's Claude Code plugins, skills and `~/.claude/CLAUDE.md`?** If it does not, Claude-side global rules may not apply to the build thread. The handoff must therefore state operative rules explicitly rather than rely on them.
- **What are the preview toolkit's real tool names?** Undocumented; discover them live.
- **Which providers are enabled and authenticated in the operator's T3?** Only `~/.t3/userdata/providers/antigravity` exists on disk; the live catalog is authoritative.
- **Does the operator's unticked "false done" and "overhead on small tasks" mean those aren't concerns?** Not confirmed. The spec's evidence rules already cover false completion; treat both as still required.
- **Budget ceiling for the full live matrix.** Authorised without a stated cap. The build must record measured usage and cost per run (null when unknown) and stop to report if a provider's runs fail repeatedly instead of burning retries.
