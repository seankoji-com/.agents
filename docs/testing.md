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
`--timeout` seconds (default 600) is stopped and fails. On 2026-10-11, on a 16-core
Linux machine, the 700 or so tests took about a minute in parallel and four minutes serially.

Line coverage of `core/`, `scripts/`, and the plugin helpers was 87% on the same date,
measured with coverage.py across the child processes the tests start. coverage.py is
not a dependency; install it in a scratch environment to measure again. That figure
predates the Stage 2 retirement of two plugins. `run_imps.py` reads as 0% because it replaces its process with `os.execv`
before coverage can save; its behavior is tested in `test_catalog.py`.

The suite tests behavior across boundaries, not just successful return values:

| Risk | Evidence |
| --- | --- |
| Stale evidence accepted after an edit | Core snapshot, readiness, and review regression suites |
| Two owners mutate one run | Claim/generation and ownership tests |
| A child is dispatched twice after interruption | Task reconciliation and delegated-run tests |
| Installer damages local files or neighbors | Install, uninstall, rollback, path, and catalog tests |
| A copied helper only works in the source tree | Installed settings audit run from a separate directory under `python3 -I` |
| Settings audit prints sensitive values | Valid and malformed settings receipt tests |
| Handoff silently changes its source brief | Literal rendering and provenance/hash tests |
| The site drifts from the catalog or the ledger | Field-guide hook tests: every plugin has a plate, numbers come from `compatibility.json`, HTML is escaped |
| Conformance evidence names the machine it ran on | `collect` replaces the home and per-user temporary directories; a contract test scans every tracked file |
| The compatibility page drifts from its ledger | `conformance.py compile` output is compared with the committed page |
| A publish to GitHub half-succeeds | Scripted `gh` tests: URL parsing, category choice, GraphQL errors behind a zero exit, no metadata on failure |
| The homepage recording goes stale or unsafe | Recording generator tests: committed SVG matches the generator, no scripts or external references |

External model calls are mocked. Shell helpers use synthetic fixtures and stubbed
GitHub/Git responses. The suite needs a local loopback socket for its HTTP product
fixture; a sandbox that forbids socket creation cannot run that case.

## CI and release artifacts

The test workflow checks supported Python versions on Linux and a macOS lane.
The documentation workflow checks navigation and builds the site strictly. The
Homebrew formula tests a fresh installation, catalog, integrity doctor, and imps CLI.
Runtime packages do not depend on documentation dependencies.

Coverage is useful when it identifies a missing failure scenario. A percentage alone
does not establish that a workflow works. The [test map](https://github.com/seankoji-com/t3-plugins/blob/master/tests/README.md)
links the core's original requirements to tests; the newer suites name their boundary
and failure mode directly.

## Live provider conformance

Run the [conformance procedure](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/procedure.md)
in disposable fixture repositories. Record exact T3/provider/model versions,
repetitions, artifacts, interventions, and failures. Keep credentials out of commits.
No unit-test result upgrades a provider's compatibility status automatically.

Live runs consume model resources and may create host tasks. Run them only within
the operator's authorization, with bounded retries and task cleanup.
