# .agents

Editable skills and workflows for [T3 Code](https://github.com/pingdotgg/t3code).
The canonical bodies are `skills/<name>/SKILL.md`. Edit a body or helper, then start
a new invocation to try the uncommitted change. Existing jobs keep their pins.

## Install

Use Python 3.10+; native TOML configuration helpers need 3.11+. For a new home:

```sh
git clone --branch main https://github.com/seankoji-com/.agents.git "$HOME/.agents"
python3 "$HOME/.agents/bin/agents" self-install --profile author
"$HOME/.local/bin/agents" adopt --from-source "$HOME/.agents"
"$HOME/.local/bin/agents" status
```

An existing nonempty `~/.agents` needs the [inventory and adoption procedure](docs/getting-started.md),
including the companion dotfiles guard. Do not replace the directory or clone over it.
This project no longer publishes Homebrew releases. Its retained compatibility runtime
serves inventoried old jobs; the tap remains available for unmigrated hosts. The
[quickstart recording](docs/assets/quickstart.mp4) ([transcript](docs/assets/recordings/quickstart.txt))
shows that former Homebrew `t3-plugins` flow, recorded 13 Oct 2026; the steps above replace it.

In T3, enable **Show skills in slash menu**, restart the agent session, then send
`$imps doctor`. Use an explicit skill mention to disambiguate `plan` from a builtin.
The agent first runs the stable launcher, then reads the returned immutable body,
manifest, helpers and worker definitions.

## Pick a workflow

| When you want to… | Send in T3 | You get back |
| --- | --- | --- |
| Fix a bug you can describe | `$imps run fix the date parser: reject 31 April` | The diff, a run ID, and checks and review tied to that revision |
| Turn a vague idea into a task | `$plan retry-policy` | `discovery.md`, `spec.md` with acceptance criteria, and `handoff.md` |
| See how another repo solved it | `$ape https://github.com/python/cpython how are parser errors tested?` | A report pinned to a commit, with line citations and one small experiment |
| Get a PR through review and CI | `$babysitter pr https://github.com/OWNER/REPO/pull/12` | Fixes pushed to the PR branch, an independent review at the final head, then a merge, plus a table of what still blocks each PR |
| Check and align all agent wiring | `$agent-tuneup` | A complete audit, private usage analysis, reviewed proposals and verification of approved changes |
| Have one model build and another grade | `$ralph fix the parser and add regression coverage` | Fresh attempts until the grader has no feedback (five by default), then a PR |
| Try a product on invented personas | `$focus-group plan https://staging.example/welcome first-run experience for busy parents` | A reviewed report of synthetic hypotheses, a ranked backlog and local issue drafts; nothing is posted |
| Inspect test protection and validation cost | `$tests-omg audit` | Twelve findings, ranked recommendations and private HTML/JSON; unknown evidence stays visible |
| Report a suspected upstream defect | `$bug-report investigate the error above` | Evidence, routing, a separate reporting thread and a fixed 30-minute follow-up window; uncertain cases stay private |

Each workflow has a guide with a full example:
[imps](docs/plugins/imps.md) ·
[plan](docs/plugins/plan.md) ·
[ape](docs/plugins/ape.md) ·
[babysitter](docs/plugins/babysitter.md) ·
[agent-tuneup](docs/plugins/agent-tuneup.md) ·
[ralph](docs/plugins/ralph.md) ·
[focus-group](docs/plugins/focus-group.md) ·
[bug-report](docs/plugins/bug-report.md) ·
[tests-omg](docs/plugins/tests-omg.md).
For a one-line edit, skip all of this and ask the agent directly.

## Verify and recover

`agents status` reports the source and installed infrastructure separately.
`agents permissions` prints grants for jobs, snapshots and locks. Updater code,
active pointers, ownership receipts, launchers and service units stay outside them.
The Mac uses the author profile with automatic receiving disabled. Linux receivers
use exact commits and an optional systemd user timer. See the [CLI](docs/cli.md).

Local tests, independent review, hosted CI, merge, installation and live provider
loading are separate observations. The [compatibility ledger](docs/compatibility.md)
retains historical results; a unit test is not a live provider result.

```sh
python3 scripts/run_tests.py
python3 scripts/check_docs.py
```

[Architecture](docs/architecture.md) · [Safety](docs/safety.md) ·
[Contributing](CONTRIBUTING.md) · [MIT license](LICENSE)
