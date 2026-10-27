# Testing

## Deterministic regression suite

```sh
python3 scripts/run_tests.py              # every module, in parallel
python3 scripts/run_tests.py test_review  # modules whose names start with test_review
python3 -m unittest discover -s tests -v  # the same tests, one module after another
```

Most tests drive the core CLI and Git in temporary repositories, so the suite spends
its time waiting on child processes. `run_tests.py` gives each module its own process
and prints that module's full output only if it fails. It is stricter than unittest in
two ways: a module that collects no tests fails, and a module still running after
`--timeout` seconds (default 600) is stopped and fails. Use `--jobs N` to bound concurrency on smaller machines. Coverage measurements need
to include the child processes these tests launch; coverage.py is optional tooling,
not a runtime dependency. The launcher replaces its process with `os.execv`; test
its observable behavior rather than relying on launcher line coverage.

The suite tests behavior across boundaries, not just successful return values:

| Risk | Evidence |
| --- | --- |
| Stale evidence accepted after an edit | Core snapshot, readiness, and review regression suites |
| Two owners mutate one run | Locked transaction and concurrent-writer tests |
| A child is dispatched twice after interruption | Recorded child identity and pending-descendant tests; dispatch itself belongs to T3 |
| Installer damages local files or neighbors | Install, uninstall, rollback, path, and catalog tests |
| A copied helper only works in the source tree | Installed settings audit run from a separate directory under `python3 -I` |
| Settings audit prints sensitive values | Valid and malformed settings receipt tests |
| Handoff silently changes its source brief | Literal rendering and provenance/hash tests |
| The site drifts from the catalog or the ledger | Field-guide hook tests: every plugin has a plate, numbers come from `compatibility.json`, HTML is escaped |
| Conformance evidence names the machine it ran on | `collect` replaces the home and per-user temporary directories; a contract test scans every tracked file |
| The compatibility page drifts from its ledger | `conformance.py compile` output is compared with the committed page |
| A publish to GitHub half-succeeds | Scripted `gh` tests: URL parsing, category choice, GraphQL errors behind a zero exit, no metadata on failure |
| The homepage recording goes stale or unsafe | Recording generator tests: committed SVG matches the generator, no scripts or external references |
| A worker bundle, override or job pin drifts | Registry tests with isolated agent roots, two prefixes, corrupt, symlinked and stale files |
| A worker result is half-read or accepts itself | Strict result parser, hostile result fixtures, and validator receipts that ignore worker readiness claims |
| Resume or retry resets a repair budget | Job counter, follow-up and reconciliation tests |
| A workflow loses its boundary or skips the picker | Per-plugin coordinator workflow tests run through installed helpers |

External model calls are mocked. Shell helpers use synthetic fixtures and stubbed
GitHub/Git responses. The suite needs a local loopback socket for its HTTP product
fixture; a sandbox that forbids socket creation cannot run that case.

## CI and release artifacts

The test workflow checks supported Python versions on Linux and a macOS lane.
The documentation workflow checks navigation and builds the site strictly. The
Homebrew formula tests a fresh installation, catalog, integrity doctor, and imps CLI.
Runtime packages do not depend on documentation dependencies.

Coverage is useful when it identifies a missing failure scenario. A percentage alone
does not establish that a workflow works. The [test map](https://github.com/seankoji-com/.agents/blob/main/tests/README.md)
links the current evidence boundaries to tests; the newer suites name their boundary
and failure mode directly.
The [issue #28 test map](stage4-test-map.md) lists which suites prove each
whole-job requirement.

## Live provider conformance

The major-version-1 [conformance procedure](https://github.com/seankoji-com/.agents/blob/main/conformance/procedure.md)
and its collector describe the previous gate. Activate that package to reproduce those dated results. New-gate live compatibility is unverified. Record exact T3/provider/model versions,
repetitions, artifacts, interventions, and failures. Keep credentials out of commits.
No unit-test result upgrades a provider's compatibility status automatically.

The rebuilt whole-job workflows have their own frozen
[benchmark protocol v2](https://github.com/seankoji-com/.agents/blob/main/bench/v2/protocol.md).
`tests/test_bench_v2.py` checks its graders and frozen files offline; it is not a
live run. See [measurement limits](compatibility.md#measurement-limits).

Live runs consume model resources and may create host tasks. Run them only within
the operator's authorization, with bounded retries and task cleanup.

## Planning review conformance protocol

This protocol is a proposal for a separately authorised observation. Reading it,
building these docs or passing fixtures launches no models and grants no spending
or sharing permission. Current live planning-review adherence is unverified.

Before a run, freeze the package/bundle digests, T3 version, live catalog, requested
and actual session settings, authorised recipients/data classes, primary panel and
finite replacement set. Use a disposable public fixture repository. Select exact
supported model/options through the normal chooser. Keep credentials, private paths
and real transcripts outside published artifacts.

Bound one observation to at most three substantive assessments, one launch per
declared candidate per round, and two same-request retries for an uncertain launch.
Declare a wall-clock and cost ceiling with the owner before starting. On reaching
either ceiling, cancel only owned tasks, retain their handles and report incomplete.
Reconcile uncertain/pending children before any replacement. No polling or recursive
delegation is part of this protocol.

Observe these cases within that allowance, or split them into separately authorised runs:

1. A complete cross-lineage review challenges a seeded load-bearing error, covers
   every request clause, cites inspected bytes and tests a counterexample/recovery
   path. Repair the source and verify that the fresh pass retains the original finding.
2. Compare frozen target/options, actual dispatch and host identity/options. Report
   unreported effort as unknown. Try unsupported options locally before dispatch;
   refusal must produce no child. Do not infer depth from the model's label.
3. Exercise a real bounded technical failure only where authorised and observable.
   Retain the tool call, failure receipt and handle if any. Observe the permitted
   cross-lineage, same-lineage and self-review transitions. If a failure cannot be
   observed, mark that branch unverified; do not fabricate an outage or receipt.
4. Supply a complete adverse verdict and verify that it stops fallback. Check that
   unchanged-content self-review cannot clear its major. Tamper with a copy of the
   source, selection or receipt and observe the real parent gate refusing readiness.
5. Confirm the requester report names actual mode, degraded panel, scoped content,
   findings/dispositions, counters, blockers and next action. Owner discovery,
   readability, final code review, execution authority and live observations stay separate.

Store exact argv, cwd, pre-check binding, complete logs and exit codes privately.
Publish only sanitised observations with explicit omissions, repetitions and failures.
Fixture suites `test_plan_review_installed_matrix.py`, `test_planning_review.py` and
`test_model_selection*.py` cover deterministic contracts and relocated public gates;
they cannot upgrade live-provider compatibility or establish model adherence.
