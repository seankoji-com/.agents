> Historical guide for the packaged 1.0 migration. Commands and paths below describe that release. For the editable source migration, use [getting started](getting-started.md) and [legacy compatibility](cli.md#legacy-compatibility).

# Upgrading to plugin 1.0

## Whole-job coordination

The five workflow plugins now hand whole stages to managed workers and accept each
stage through a validator. The commands you type keep their names and meanings:

| Plugin | Operations |
| --- | --- |
| imps | `doctor`, `run`, `resume`, `status`, `cancel`, `verification-init`, `blast-radius`, `audit`, `issues`, `prs`, `checklist`, `discussion` |
| ape | `doctor`, `forage`, `study`, `clean` |
| elephant-goldfish | `doctor`, `thinking`, `elephant`, `check` |
| babysitter | `doctor`, `pr`, `repo`, `org` |
| agent-tuneup | `doctor`, `audit`, `align`, `apply`, `scan` |

Skill adapters still point at the same entries. Routing config, learnings, thinking
topics and imps major-version-2 runs stay where they are and remain readable.
ralph is unchanged.

What changes:

- `install` and `setup` also write worker bundles under the agents root. Run
  `t3-plugins setup` after upgrading; `doctor` reports `worker_bundle_missing` for a
  package installed without one.
- Substantive multi-stage work creates a job under `$XDG_STATE_HOME/t3-plugins/jobs`.
  Job metadata sits beside, not inside, existing plugin state. imps gate runs keep
  their format, and `validate` stays their authority.
- Each stage gets an initial attempt and three repairs unless
  [`workers.json`](cli.md#overrides-and-limits) sets another limit.
- Every approval and owner decision uses the host's native question picker.
- New elephant-goldfish topics allow four cold-read rounds in total. Existing topics
  keep their recorded limit. A topic with no recorded limit keeps the earlier
  five-round policy, minus the rounds already performed.

Unfinished work:

- An imps run without a job keeps the entry's legacy `status`, `resume` and
  `cancel` paths.
- A package installed before worker bundles existed still runs its own operations,
  but it cannot create or resume a job.
- `t3-plugins activate PLUGIN VERSION` selects a package and its bundle together.
  A running job keeps its pins whatever `current` points to; resume it through
  [`--job JOB path PLUGIN`](cli.md#pinned-job-paths).
- No migration converts old state or records acceptance on its behalf.

The maintainer ledger of every kept, changed and removed surface is the
[compatibility map](https://github.com/seankoji-com/t3-plugins/blob/master/migration/rebuild/compat-map.md).

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
