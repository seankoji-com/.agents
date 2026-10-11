# Upgrading to plugin 1.0

## Plugin version 1.0.0

Version 1.0 keeps revision-bound evidence, locking and atomic storage while
changing the imps state API and removing two workflow plugins. Upgrade snapshots and
adapters together; keep the previous package for unfinished old runs.

| Removal | Reason | Upgrade step |
| --- | --- | --- |
| offload-sidecar, including deterministic transforms and receipts | Local transforms now use the agent’s tools directly. | Use local tools for deterministic transforms and T3 delegation for judgement. Run `t3-plugins setup` to remove owned, unmodified retired adapters; modified or unrelated files are preserved. Use `t3-plugins uninstall offload-sidecar` for its installed package. |
| prompt-builder | Prompt drafting now uses the active agent. | Use the active agent for drafting. Run `t3-plugins setup` for owned adapter removal and `t3-plugins uninstall prompt-builder` for the retired installed package. |
| imps dispatcher, claims and generation counters | The orchestrator now chooses its next step. The removed action loop encoded the hypothesis that the model needed a second scheduler to direct each action. | Use `snapshot`, named evidence submissions and `validate`; see the [API migration](imps-gate-migration.md). Process locking and atomic storage remain. Old run-state major-version-1 runs require the previous installed package; activate it to inspect, resume or cancel them. No state conversion occurs. |
| Repeated delegation rules | Multiple copies could drift without improving model decisions. | Follow the installed `shared/delegation.md` as the single contract, and discover the live catalog before selecting children. |

Install the new release into your chosen prefix, then run `t3-plugins setup` to refresh
skill adapters. Existing routing configuration is preserved. Review retained modified
adapters yourself before replacing them. Plugin versions and release tags are separate; see the
[release procedure](releasing.md) for publishing details.

The historical compatibility ledger covers imps `0.1.0+ga50f506cd178` on T3
`0.0.46-nightly.20261008.2849`. It does not certify plugin version 1.0.0. See
[compatibility and evidence](compatibility.md) for the distinction between helper
tests and observed model workflows.

Maintainer reference: [source provenance and file hashes](https://github.com/seankoji-com/t3-plugins/blob/master/migration/source.json).
The [MIT license](https://github.com/seankoji-com/t3-plugins/blob/master/LICENSE)
remains in the repository and distribution.
