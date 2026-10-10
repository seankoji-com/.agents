# Architecture

t3-plugins has three execution paths. Instructions guide the current agent. Local
helpers do deterministic work. T3 owns delegated tasks and browser/PR interactions.
The repository does not implement another model client or task scheduler.

![A T3 thread reads a plugin entry, loads one playbook, then uses local helpers or T3 host tools. imps records revision-bound evidence in the shared core.](assets/architecture.svg){ .diagram }

## Package boundaries

| Directory | Responsibility | Dependency rule |
| --- | --- | --- |
| `plugins/<name>/` | Entry, selected playbooks, helper scripts, templates | May use the shared runtime contract and core |
| `shared/` | Provider-neutral agent instructions for using T3 | No provider SDK or executable orchestration |
| `core/` | imps run state, ownership, transitions, evidence, readiness | Python standard library; no plugin imports or vocabulary |
| `scripts/` | Catalog, installation, conformance, release tooling | Finds plugins through their manifests |
| `packaging/` | Homebrew formula template | Calls the same installer used from source |
| `tests/` | Deterministic regression tests and fixtures | No paid models or live GitHub mutations |
| `conformance/` | Dated live-provider observations | Separate from unit-test success |
| `docs/` | Human guides and GitHub Pages source | Documentation dependencies are build-time only |
| `migration/` | Original source revision and copied-file hashes | Audit trail, not a second source tree |

## Progressive instruction loading

An entry is a routing document, not a book. The agent reads the shared T3 contract
once and then the requested playbook. Helpers are invoked by path; their source is
loaded only when needed for inspection or debugging. Entry budgets are tested.

This reduces routine context use without hiding the behavior. All instructions ship
as readable files, and all deterministic decisions have local source and tests.

## The imps state machine

The core persists runs, plans, observations, and evidence. A claim token identifies
the owner; a generation check refuses stale writes. Readiness is recomputed from
the recorded evidence at the current repository snapshot. An edit invalidates prior
verification instead of silently inheriting its green status.

```text
plan → claim → next action → execute → record → next action
                    ↑                            │
                    └────────────────────────────┘
                                  ↓
                     verified report or explicit blocker
```

The other plugins do not pretend to use this state machine. Research produces a
report; planning produces a handoff; file tools produce a receipt. Their completion
criteria are specific to those outputs.

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

The sidecar's optional Ollama/agy backends are a separate processing service. A T3
provider can invoke its deterministic path without either backend. Choosing a cloud
sidecar tier crosses a data boundary and requires explicit authorization.

## Tradeoffs

Instructions are portable but model adherence varies. Unit tests prove helper and
state behavior, not that every model follows a playbook. T3 tool schemas also evolve.
The compatibility ledger records this uncertainty rather than treating provider
logos as proof. See [compatibility](compatibility.md) and [testing](testing.md).
