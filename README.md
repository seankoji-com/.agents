# t3-plugins

**Six workflows for coding agents in [T3 Code](https://github.com/pingdotgg/t3code).
Each one ends in something you can check.**

[![Tests](https://github.com/seankoji-com/t3-plugins/actions/workflows/test.yml/badge.svg)](https://github.com/seankoji-com/t3-plugins/actions/workflows/test.yml)
[![Documentation](https://github.com/seankoji-com/t3-plugins/actions/workflows/docs.yml/badge.svg)](https://seankoji-com.github.io/t3-plugins/)
[![MIT license](https://img.shields.io/badge/license-MIT-2f6b4f)](LICENSE)

Ask an agent to "fix the bug" and you usually get a confident summary. With imps you
get a run ID and a report showing which checks passed on the exact files you were
handed; edit a file afterwards and the report says the evidence is stale. The other
five workflows leave similar records for briefs, research, pull requests, provider
settings and implement-then-grade loops.

## Install (macOS or Linux)

The tap's stable formula is still v0.4.0, which predates ralph and several commands
in these docs. Until the next release, install the HEAD build from `master`:

```sh
brew install --HEAD seankoji-com/tap/t3-plugins
t3-plugins setup      # installs the workflows and their slash-menu skills
t3-plugins doctor     # checks the installed files; expect "ok": true per plugin
```

Update a HEAD install with `brew upgrade --fetch-HEAD t3-plugins`, then run
`t3-plugins setup` again.

In T3, open **Settings > General**, turn on **Show skills in slash menu**, and restart
the agent session. Then send this in a thread attached to your repository:

```text
$t3-imps doctor
```

Type `/` and pick **t3-imps** to insert the `$t3-imps` mention. The agent checks
Python, Git, its state directory and T3's live provider list, then reports what it
can run. It changes no files.

<p align="center">
  <img src="docs/assets/demo.svg" alt="Terminal recording: t3-plugins list, setup, doctor, the installed skills, and the prompt for T3. Real output in an empty home directory." width="760">
</p>
<p align="center"><sub>Real output from an empty home directory, recorded 13 Oct 2026 (<a href="docs/assets/quickstart.mp4">MP4</a>, <a href="docs/assets/recordings/quickstart.txt">transcript</a>). Only the typing is simulated.</sub></p>

Homebrew on Linux installs and runs the formula (checked on x86_64), and the tap's CI
installs and tests it on macOS. Without Homebrew, install from source with Python
3.10+:

```sh
git clone https://github.com/seankoji-com/t3-plugins.git && cd t3-plugins
python3 bin/t3-plugins setup && python3 bin/t3-plugins doctor
```

## Pick a workflow

| When you want to… | Send in T3 | You get back |
| --- | --- | --- |
| Fix a bug you can describe | `$t3-imps run fix the date parser: reject 31 April` | The diff, a run ID, and checks and review tied to that revision |
| Turn a vague idea into a task | `$t3-elephant-goldfish thinking retry-policy` | `discovery.md`, `spec.md` with acceptance criteria, and `handoff.md` |
| See how another repo solved it | `$t3-ape study https://github.com/python/cpython how are parser errors tested?` | A report pinned to a commit, with line citations and one small experiment |
| Get a PR through review and CI | `$t3-babysitter pr https://github.com/OWNER/REPO/pull/12` | Fixes pushed to the PR branch, an independent review at the final head, then a merge, plus a table of what still blocks each PR |
| Check provider permissions and MCPs | `$t3-agent-tuneup audit --provider claude --settings .claude/settings.json` | Finding codes and locations, never the setting values |
| Have one model build and another grade | `$t3-ralph fix the parser and add regression coverage` | Fresh attempts until the grader has no feedback (five by default), then a PR |

Each workflow has a guide with a full example:
[imps](docs/plugins/imps.md) ·
[elephant-goldfish](docs/plugins/elephant-goldfish.md) ·
[ape](docs/plugins/ape.md) ·
[babysitter](docs/plugins/babysitter.md) ·
[agent-tuneup](docs/plugins/agent-tuneup.md) ·
[ralph](docs/plugins/ralph.md).
For a one-line edit, skip all of this and ask the agent directly.

## Try one without a model

agent-tuneup's audit helper runs locally. This is real output:

```console
$ printf '%s\n' '{"permissions":{"allow":["Bash(*)"]}}' > example-settings.json
$ python3 "$(dirname "$(t3-plugins path agent-tuneup)")/scripts/audit.py" --provider claude --settings example-settings.json
{"ok": true, "provider": "claude", "findings": [{"code": "broad_execution_allow", "location": "permissions.allow[0]"}], "scope": "known-pattern audit; not a complete permission evaluation", "writes": 0}
```

It exits 1 because it found something. Exit 0 means no known findings.

## What it does not claim

- `t3-plugins doctor` checks installed files. It does not call T3 or a model.
- The unit tests run helpers against temporary repositories and loopback fixtures. They
  don't prove that a given model follows a workflow. The
  [compatibility page](docs/compatibility.md) separates the two, and the live provider
  results it publishes cover an earlier imps gate, not imps 1.0.
- A local pass is not CI, CI is not a merge, and a merge is not a deployment. The
  workflows report each one only after observing it.

## Docs

[![The documentation site's homepage](docs/assets/docs-preview.png)](https://seankoji-com.github.io/t3-plugins/)

[First ten minutes](docs/getting-started.md) ·
[Slash commands per provider](docs/slash-commands.md) ·
[CLI reference](docs/cli.md) ·
[Architecture](docs/architecture.md) ·
[Safety and data](docs/safety.md) ·
[Troubleshooting](docs/troubleshooting.md)

## Contribute

Runtime code is Python 3.10+ with the standard library only; the Codex TOML helpers
need 3.11+.

```sh
python3 scripts/run_tests.py
python3 scripts/check_docs.py
```

[Contributor guide](CONTRIBUTING.md) · [Testing](docs/testing.md) ·
[Security reporting](SECURITY.md) · [MIT license](LICENSE)
