# t3-plugins

**Give your T3 agent a repeatable way to fix bugs, plan work and finish PRs.**

[![Tests](https://github.com/seankoji-com/t3-plugins/actions/workflows/test.yml/badge.svg)](https://github.com/seankoji-com/t3-plugins/actions/workflows/test.yml)
[![Documentation](https://github.com/seankoji-com/t3-plugins/actions/workflows/docs.yml/badge.svg)](https://seankoji-com.github.io/t3-plugins/)
[![MIT license](https://img.shields.io/badge/license-MIT-2f6b4f)](LICENSE)

Six workflows for [T3 Code](https://github.com/pingdotgg/t3code). Pick the job,
give it to your agent, and get a result you can inspect: a verified change, a usable
brief, cited research, a PR carried through CI, a settings audit, or a PR opened
after every feedback item is repaired.
Switch models without rewriting the workflow.

**[Get started](https://seankoji-com.github.io/t3-plugins/getting-started/)** ·
[Choose a workflow](https://seankoji-com.github.io/t3-plugins/plugins/) ·
[CLI reference](https://seankoji-com.github.io/t3-plugins/cli/)

## Pick your job

| You want to… | Use | What comes back |
| --- | --- | --- |
| Fix a bug or ship a bounded change | [imps](docs/plugins/imps.md) | A change with checks and review tied to the current revision |
| Work out what to build | [elephant-goldfish](docs/plugins/elephant-goldfish.md) | A testable brief ready for a fresh thread |
| Learn how another project solved a problem | [ape](docs/plugins/ape.md) | Source-pinned recommendations and small proposed experiments |
| Get an authorized PR through review and CI | [babysitter](docs/plugins/babysitter.md) | Fixes, current-head check status and observed merge state |
| Inspect your agent permissions | [agent-tuneup](docs/plugins/agent-tuneup.md) | A read-only findings report without exposing setting values |
| Implement through repeated independent evaluation | [ralph](docs/plugins/ralph.md) | Fresh tasks repair every feedback item before opening a PR |

## Install and try it

Install the current catalog from source on the machine where your provider executes tools:

```sh
git clone https://github.com/seankoji-com/t3-plugins.git
cd t3-plugins
python3 bin/t3-plugins setup
python3 bin/t3-plugins doctor
python3 bin/t3-plugins prompt imps doctor
```

Paste the last command's output into a T3 thread. The shell `doctor` checks installed
files; the agent's `doctor` checks workflow readiness. To use the picker, enable
**Show skills in slash menu** in T3, restart the agent session, then select **t3-imps**
from `/` and append your task.

[Source installation](docs/getting-started.md#from-source) ·
[Provider skill roots](docs/slash-commands.md) ·
[Your first workflow](docs/first-workflow.md) ·
[Troubleshooting](docs/troubleshooting.md)

## Why use a workflow?

imps keeps evidence with the work. An edit after a check or review makes that evidence
stale, so an earlier pass cannot certify the change you receive. A blocked result
names what is missing and how to resume. Publishing, CI, merge and deployment each
need their own observations.

The other workflows save the outputs you usually have to ask for again: acceptance
criteria, source citations, review blockers and permission findings. For a trivial
edit, a direct agent request is enough.

Instructions are readable Markdown. Local helpers use Python 3.10+ and the standard
library; Codex TOML adapters need 3.11+. T3 owns delegated tasks, previews and watches.
[Architecture](docs/architecture.md) · [Safety and data](docs/safety.md)

## Compatibility

The catalog is designed for T3 providers with local file and shell access. Provider
skill discovery and available host tools vary. Install tests do not prove that a
model follows the workflow. The [compatibility guide](docs/compatibility.md) separates
current helper coverage from historical provider observations. imps 1.0's new gate
has not yet completed a live provider matrix.

## Contribute

```sh
python3 scripts/run_tests.py
python3 scripts/check_docs.py
```

[Contributor guide](CONTRIBUTING.md) · [Testing](docs/testing.md) ·
[Security reporting](SECURITY.md) · [MIT license](LICENSE)
