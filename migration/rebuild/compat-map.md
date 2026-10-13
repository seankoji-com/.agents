# Compatibility map for issue #28

The machine-readable ledger is [compat-map.json](compat-map.json) plus the stage shards in
[compat-map.d/](compat-map.d/). `tests/test_rebuild_compat_map.py` merges them and fails
when any current plugin operation, CLI subcommand, helper/instruction/schema file,
manifest field, persisted format, test module or test class lacks exactly one recorded
fate. Each disposition names its reason and owning stage. Test entries map each test
class's surviving assertions to requirement or guarantee IDs; a removed test must keep
that map and point to replacement coverage.

`keep` preserves behavior and coverage; `change` assigns an explicit migration while
retaining named guarantees; `remove` requires replacement coverage or a reason the
surface is obsolete.

## Final map (Stage 5)

The merged map (base plus shards) records every surface as `keep` or `change`, plus new
files as `added` with their coverage. No entry is `remove`: every operation keeps its name
and meaning, and old state stays readable. `load()` in the map test returns the merged
map; this page does not copy its counts because later shards change them. imps major-version-2
runs, thinking topics, learnings, skill-adapter markers and v1 install receipts (legacy
packages without bundles) keep compatible paths; job metadata lives outside them.

The ledger maps operation-level guarantees: imps evidence and legacy behavior, ape
read-only research and authorized cleanup, elephant-goldfish discovery and
factual/cold-read separation, babysitter exact-head and communication boundaries, and
tune-up report-first authorization. It also tracks optional scoped learnings, provider
adapters and rollback.

## Shards

Shards stay separate. The merge appends shard inventory and rejects duplicate keys, so
folding shard facts into `compat-map.json` while the shards exist would fail as
duplicates, and deleting another stage's shard is outside Stage 5 ownership.

| Shard | Owner | Records |
|---|---|---|
| `stage-1b.json` | S1b | Bench container and canary files |
| `stage-2.json` | 2 | Registry, installation, pins, overrides, `agents` CLI |
| `stage-3.json` | 3 | Jobs, briefs, results, acceptance adapters and their tests |
| `stage-4-*.json` | 4 | Coordinator entries, worker definitions, workflow tests |
| `stage-5-upstream.json` | 5 | Master additions after the issue base (tune-up align/apply, ralph) |
| `stage-5.json` | 5 | Installed-artifact, cross-stage and legacy-migration tests |

Stage 5 assertion selectors in `stage-5.json`:

- `tests/test_rebuild_installed.py`: installed routing of every operation, bundles,
  shared contract, pinned digests, `agents list/show`, doctor, owned uninstall
  (REQ-COMPAT, REQ-REGISTRY, REQ-DELIVERY).
- `tests/test_rebuild_integration.py`: five-stage restart from the overview, stage-3
  regression rejected by the final gate, initial-plus-three repair budget and imps to
  babysitter pin stability (REQ-JOB, REQ-VISIBILITY, REQ-EVIDENCE, REQ-REPAIR).
- `tests/test_rebuild_migration.py`: legacy runs, topics and bundle-less packages; no
  migration creates acceptance (REQ-COMPAT, REQ-REGISTRY, G-IMPS-LEGACY).

## Gates outside the ledger

The host-native approval picker is mandatory for every approval and owner decision
(`REQ-APPROVAL-PICKER`). All live parent/worker/reviewer/canary/retry/repair/resume work
uses only Haiku and Luna (`REQ-TEST-MODELS`); S1b enforces exact live-catalog targets,
zero-dispatch rejection for forbidden targets, and transcript model audits.

This map is local compatibility evidence, not provider compatibility. Container canaries
belong to S1b and live workflow acceptance belongs to Stage 6. See [design](design.md) for
the interfaces, stage ownership, integration order, proof tests and open decisions.
