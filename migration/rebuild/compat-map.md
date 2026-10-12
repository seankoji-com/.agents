# Compatibility map for issue #28

The machine-readable ledger is [compat-map.json](compat-map.json). It covers every current
plugin operation, CLI operation, helper/instruction/schema file, manifest field, persisted
format and test module. Each disposition names its reason and owning stage. Test entries
map each test class's surviving assertions to requirement or guarantee IDs; removed tests
must retain that map and point to replacement coverage.

`keep` preserves behavior and coverage; `change` assigns an explicit migration while
retaining named guarantees; `remove` requires replacement coverage or a reason the surface
is obsolete. The ledger maps operation-level guarantees including imps evidence/legacy
behavior, ape read-only research and authorized cleanup, elephant-goldfish discovery and
factual/cold-read separation, babysitter exact-head and communication boundaries, and
tune-up report-first authorization. It also tracks optional scoped learnings, provider
adapters, and rollback.

Stage 2 owns registry/installation and its `compat-map.d/stage-2.json` additions. Stage 3
owns generic jobs, briefs, results, validators and its shard. Stage 4 owns coordinator
entries, worker definitions and approval routing. Stage 5 owns migration, integrated
regressions and its shard. Shards are merged by the map test, allowing Stage 2 and 3 to
work independently without racing edits to this file.

The host-native approval picker is mandatory for every approval and owner decision
(`REQ-APPROVAL-PICKER`). All live parent/worker/reviewer/canary/retry/repair/resume work
uses only Haiku and Luna (`REQ-TEST-MODELS`); S1b must enforce exact live-catalog targets,
zero-dispatch rejection for forbidden targets, and transcript model audits. These gates
supplement the exhaustive requirement IDs in the JSON ledger.

Stage 1 compatibility evidence does not claim provider compatibility. Container canaries
belong to S1b and live workflow acceptance belongs to Stage 6. See [design](design.md) for
the concrete interfaces, stage ownership, integration order, proof tests, and open decisions.
