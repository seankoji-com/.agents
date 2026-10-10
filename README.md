# t3-plugins

**Change the model. Keep the workflow.**

[![Tests](https://github.com/seankoji-com/t3-plugins/actions/workflows/test.yml/badge.svg)](https://github.com/seankoji-com/t3-plugins/actions/workflows/test.yml)
[![Documentation](https://github.com/seankoji-com/t3-plugins/actions/workflows/docs.yml/badge.svg)](https://seankoji-com.github.io/t3-plugins/)
[![MIT license](https://img.shields.io/badge/license-MIT-16786a)](LICENSE)

Seven practical plugins for [T3 Code](https://github.com/pingdotgg/t3code): plan a
change, research an approach, implement it, and check the result. Portable entries
inherit your active provider. Local tools handle deterministic work. T3 owns tasks,
browser previews, and PR watches.

**[Read the docs](https://seankoji-com.github.io/t3-plugins/)** ·
[Architecture](docs/architecture.md) · [Compatibility](docs/compatibility.md) ·
[Contributing](CONTRIBUTING.md)

[![Documentation homepage, captured from the built site](docs/assets/docs-preview.png)](https://seankoji-com.github.io/t3-plugins/)

## Install

```sh
brew install seankoji-com/tap/t3-plugins
t3-plugins install
t3-plugins doctor
t3-plugins prompt imps doctor
```

Paste the printed prompt into a T3 thread. No Claude marketplace or provider-specific
slash command is required. Install on the machine where your provider executes tools.
[Source installation, upgrades, and rollback](docs/getting-started.md) are documented too.

## Pick a job

| Plugin | What it does |
| --- | --- |
| [imps](docs/plugins/imps.md) | Implements bounded changes with revision-bound evidence, recovery, and independent review |
| [elephant-goldfish](docs/plugins/elephant-goldfish.md) | Turns uncertain problems into testable briefs and checks durable design documents |
| [prompt-builder](docs/plugins/prompt-builder.md) | Builds reusable prompts and compares them against frozen cases |
| [ape](docs/plugins/ape.md) | Finds transferable ideas in open-source code, with source-pinned evidence |
| [babysitter](docs/plugins/babysitter.md) | Maintains authorized PRs through review, CI, conflicts, and merge |
| [agent-tuneup](docs/plugins/agent-tuneup.md) | Audits agent configuration with explicit provider-format support |
| [offload-sidecar](docs/plugins/offload-sidecar.md) | Transforms files by path and returns small receipts with output hashes |

A direct prompt or short shell command is often enough. Use a plugin when its saved
artifacts, checks, or recovery behavior help. [Try your first workflow](docs/first-workflow.md).

## How it fits together

![T3 thread to plugin entry, then local helpers or T3 host tools; imps additionally uses a shared state core.](docs/assets/architecture.svg)

The Python runtime uses only the standard library. Small entries load focused
playbooks. The shared core owns imps state, claims, generations, and evidence, with
no plugin-specific imports. Versioned installs preserve local edits and keep run
state separate. [Read the design and tradeoffs](docs/architecture.md).

Provider-neutral is a design contract, not a claim that every model behaves the same.
New ports are experimental. The existing imps [live conformance ledger](conformance/compatibility.md)
records partial results, exact versions, failures, and artifacts.

## Develop

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_docs.py
```

Python 3.10+; no runtime package installation. Some optional adapters require Python
3.11+. Documentation uses a separate pinned [MkDocs build](docs/contributing.md#work-on-the-site).
Tests cover stale evidence, ownership, path safety, interrupted tasks, installed
artifacts, malformed outputs, and permission-audit receipts. See [testing](docs/testing.md).

## Project

Built by [Sean Carey](https://github.com/seankoji). Ported from
[claude-plugins](https://github.com/seankoji-com/claude-plugins), with the source
revision and behavioral changes in the [migration guide](docs/migration.md).

Issue forms and the PR template are inherited from
[seankoji-com/.github](https://github.com/seankoji-com/.github).
[Security reporting](SECURITY.md) · [MIT license](LICENSE)
