# Architecture

t3-plugins has three execution paths. Instructions guide the current agent. Local
helpers do deterministic work. T3 owns delegated tasks and browser/PR interactions.
The repository does not implement another model client or task scheduler.

<!-- inline-svg: assets/architecture.svg -->

## Package boundaries

| Directory | Responsibility | Dependency rule |
| --- | --- | --- |
| `plugins/<name>/` | Entry, selected playbooks, helper scripts, templates | May use the shared runtime contract and core |
| `shared/` | T3 contract, optional learning storage and harvest helpers | Standard library; no provider SDK or executable orchestration |
| `core/` | imps run state, atomic storage, evidence, readiness | Python standard library; no plugin imports or vocabulary |
| `bin/` | Source-checkout launcher for the catalog CLI | Thin wrapper over `scripts/catalog.py` |
| `scripts/` | Catalog, installation, conformance, release, and site-build tooling | Finds plugins through their manifests |
| `packaging/` | Homebrew formula template | Calls the same installer used from source |
| `tests/` | Deterministic regression tests and fixtures | No paid models or live GitHub mutations |
| `conformance/` | Dated live-provider observations and the pre-merge review rounds under `review/` | Separate from unit-test success |
| `thinking/` | The discovery notes and handoff the port was built from | Historical record, not instructions |
| `docs/` | Human guides and GitHub Pages source; the field guide data and bundled fonts | Documentation dependencies are build-time only |
| `overrides/` | MkDocs Material templates for the homepage and page metadata | Reads only `config.extra` filled by the site hook |
| `launch/` | Announcement drafts and repository-settings commands | Not installed, not published |
| `migration/` | Original source revision and copied-file hashes | Audit trail, not a second source tree |

## Progressive instruction loading

An entry is a routing document, not a book. The agent reads the shared T3 contract
once and then the requested playbook. Helpers are invoked by path; their source is
loaded only when needed for inspection or debugging. Entry budgets are tested.

This reduces routine context use without hiding the behavior. All instructions ship
as readable files, and all deterministic decisions have local source and tests.

## The imps evidence gate

The agent plans and performs the work. The core stores major-version-2 run contracts,
checks, artifacts, review evidence and child observations with atomic writes and
process locks. It does not schedule tasks or issue permitted actions.

Capture a binding before verification. It covers HEAD, dirty and staged bytes,
untracked files, file modes, symlinks, submodules, requirements, constraints and
verification policy. Submissions retain that binding and hashes of their copied
artifacts. `validate` recomputes readiness against the current tree. Pending child
runs prevent readiness, including descendants of a terminal child.

```text
plan → implement → capture binding → verify → submit evidence → validate
                      ↑                                        │
                      └──────── repair and reverify ────────────┘
```

The other plugins use their own completion criteria: research produces a report
and planning produces a handoff. T3 owns their child tasks too.

## Optional learnings

Every installed package includes the shared learning helpers. They load only the
current plugin's project lessons from the XDG state root, maintain versioned entries
transactionally and report storage failures without blocking the task. Harvest
screens local drafts and requires owner approval before external publication.
See [learnings and harvest](learnings.md) for storage and sandbox boundaries.

## Installation and ownership

The installer builds a content manifest, copies a versioned package, and atomically
repoints `current`. Each package includes shared files and the core. That duplicates
some small files, but makes rollback independent of a changing shared installation.

Uninstall follows the manifest, preserves modified and user-added files, and leaves
run state alone. Installation of the whole catalog is per-plugin, not one global
transaction. Receipts make partial completion visible.

## Provider boundary

The active provider supplies the agent's reasoning and shell/file tools. T3 supplies
capability discovery, children, task status/cancellation, previews, and PR watches.
Provider/model IDs come from the live catalog. A plugin never assumes that a role
like "reviewer" means a particular model.

## Tradeoffs

Instructions are portable but model adherence varies. Unit tests prove helper and
state behavior, not that every model follows a playbook. T3 tool schemas also evolve.
The compatibility ledger records this uncertainty rather than treating provider
logos as proof. See [compatibility](compatibility.md) and [testing](testing.md).
