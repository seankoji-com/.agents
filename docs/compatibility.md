# Compatibility and evidence

There are three different questions: can a provider read the entry, can the helper
execute on that machine, and does the model complete the workflow correctly?
Only a live workflow run answers the third.

## Coverage and historical results

| Surface | Status | Evidence |
| --- | --- | --- |
| Plugin catalog | Deterministic install and invocation tests | `tests/test_catalog.py`, `tests/test_skill_adapters.py` |
| Portable workflow entries | Readable with local file access | Entry/path contracts and manual review; no full provider matrix yet |
| imps 1.0 evidence gate | Deterministic tests; live provider matrix pending | `tests/test_snapshot.py`, `tests/test_review.py`, `tests/test_readiness.py`, `tests/test_gate_boundaries.py` |
| Previous imps gate | Historical partial live conformance for `0.1.0+ga50f506cd178` | [Recorded matrix](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/compatibility.md) |
| agent-tuneup | Audit, alignment inventory and approved native settings writes | Claude JSON, OpenCode JSON/JSONC, Codex TOML; Antigravity MCP JSON/JSONC fixtures. Effective policy and live loading need separate checks. |
| ralph | Deterministic lifecycle, recovery and installed-artifact tests; live goal loop pending | `tests/test_ralph.py`, `tests/test_learnings.py`; see [Ralph's verification limits](plugins/ralph.md#compatibility). |

The historical imps ledger covers plugin `0.1.0+ga50f506cd178` and records T3 `0.0.46-nightly.20261008.2849`, exact model IDs, repeat
counts, interventions, failures, and artifacts. Codex and Claude completed repeated
bug-fix cases; other cases and providers remain partial or unavailable. These are
historical observations, not certification of imps 1.0 or current T3.

## What provider-neutral means

Entries inherit the active session model. Delegation uses discovered T3 provider
instances. Use a discovered skill adapter or a generated prompt. Child models come
from the live catalog and your routing configuration. Permission restrictions still apply.

Settings adapters inspect the *target configuration format*, which may differ from
the provider executing the audit. Calling agent-tuneup from Codex can inspect a Claude
settings file without turning it into a Codex configuration file.

## Report a compatibility result

Include plugin version, T3 build, provider instance type, exact model ID, OS, operation,
expected behavior, observed behavior, and a minimal redacted transcript. Record
interventions and missing capabilities. Do not include credentials or private source.
The linked [historical conformance procedure](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/procedure.md)
describes the old gate. Current-gate reports must exercise the named submission API;
do not replay removed dispatcher commands as current verification.

A successful installation, passing unit test, or plausible agent answer is not a
live provider pass. Failed attempts belong in the ledger too.
