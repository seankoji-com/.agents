# Testing

## Deterministic regression suite

```sh
python3 -m unittest discover -s tests -v
```

The suite tests behavior across boundaries, not just successful return values:

| Risk | Evidence |
| --- | --- |
| Stale evidence accepted after an edit | Core snapshot, readiness, and review regression suites |
| Two owners mutate one run | Claim/generation and ownership tests |
| A child is dispatched twice after interruption | Task reconciliation and delegated-run tests |
| Installer damages local files or neighbors | Install, uninstall, rollback, path, and catalog tests |
| A copied helper only works in the source tree | Installed sidecar execution from a separate directory |
| Cloud-default operation transmits without opt-in | One-shot adapter consent tests |
| Settings audit prints sensitive values | Valid and malformed settings receipt tests |
| A prompt comparison uses changed inputs or models | Frozen-suite evaluator tests |
| Handoff silently changes its source brief | Literal rendering and provenance/hash tests |
| File transform accepts malformed output | Imported sidecar validator and engine failure tests |

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
