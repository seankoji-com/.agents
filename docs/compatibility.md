# Compatibility and evidence

There are three different questions: can a provider read the entry, can the helper
execute on that machine, and does the model complete the workflow correctly?
Only a live workflow run answers the third.

## Helper coverage and historical workflows

| Surface | Status | Evidence |
| --- | --- | --- |
| Five-plugin catalog | Deterministic install and invocation tests | `tests/test_catalog.py` |
| Portable workflow entries | Experimental ports | Entry/path contracts and manual review; no full provider matrix yet |
| imps | Historical partial live conformance for `0.1.0+ga50f506cd178` | [Recorded matrix](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/compatibility.md) |
| agent-tuneup | Known-pattern audit adapters | Claude JSON, OpenCode JSON/JSONC, Codex TOML tests |

The historical imps ledger covers plugin `0.1.0+ga50f506cd178` and records T3 `0.0.46-nightly.20261008.2849`, exact model IDs, repeat
counts, interventions, failures, and artifacts. Codex and Claude completed repeated
bug-fix cases; other cases and providers remain partial or unavailable. These are
historical observations, not certification of the migrated catalog or current T3.

## What provider-neutral means

Entries inherit the active session model. Delegation uses discovered T3 provider
instances. No Claude marketplace, Claude command expansion, or fixed model name is
needed to invoke the workflows. Permission restrictions still apply.

Settings adapters inspect the *target configuration format*, which may differ from
the provider executing the audit. Calling agent-tuneup from Codex can inspect a Claude
settings file without turning it into a Codex configuration file.

## Report a compatibility result

Include plugin version, T3 build, provider instance type, exact model ID, OS, operation,
expected behavior, observed behavior, and a minimal redacted transcript. Record
interventions and missing capabilities. Do not include credentials or private source.
Follow the [live conformance procedure](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/procedure.md).

A successful installation, passing unit test, or plausible agent answer is not a
live provider pass. Failed attempts belong in the ledger too.
