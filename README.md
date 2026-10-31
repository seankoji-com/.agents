# .agents

Sixteen skills for coding agents. Each skill is a folder. The agent reads
`SKILL.md`, and any notes, templates or helpers live in that same folder.

## Use a skill

Clone the repository into a new directory.

```sh
git clone https://github.com/seankoji-com/.agents.git
```

Point your agent's skill discovery at `skills`, or copy the skill folders you
need into the directory it already scans. Name the skill the way that host
expects. Some hosts use a slash command, and others accept the skill name in
the request.

Keep the `skills` directory together. A few skills link to siblings:

- `ketchup` links to `bro`
- `imps`, `babysitter` and `review-loop` link to `review-evidence`
- `full-send` links to `review-loop` and `babysitter`

Helpers, where a skill has one, need Python 3.10 or newer and the standard
library only. Reading a skill needs no install step.

These instructions were written against T3 Code and Codex. Another host can
follow them when it can read files, run commands, and perform the actions the
skill names. If a named tool is missing, the skill says to report that and use
the host's own equivalent, or plain text.

`review-loop` and `challenge` ask a second model from a different provider
family to review the work. They try Sol, then Opus, Wonder Full, Argon and
Grok 4.7, and they take the model id from the host. They do not swap in a
model from the same family.

`design-chooser` asks one to three models, each from a different family, for two
or three mockups each. It uses the same model order and shows each mockup inline
in T3 Code, then waits for you to pick one.

`full-send` and `babysitter` may commit, push and merge after you invoke them.
Read those two before you use them. Limits you set in the request still apply.

In T3 Code, longer reports use the host HTML preview. Other hosts get the same
content as text.

## Skills

| Skill | What you use it for |
| --- | --- |
| [imps](skills/imps/SKILL.md) | Implement, investigate, audit or review a scoped change |
| [plan](skills/plan/SKILL.md) | Write a specification and a handoff |
| [babysitter](skills/babysitter/SKILL.md) | Watch pull requests, repair them, and merge when the gates pass |
| [review-loop](skills/review-loop/SKILL.md) | Implement, then repeat an independent review and repair within a set limit |
| [review-evidence](skills/review-evidence/SKILL.md) | Record what a review saw, and rate findings SEV1, SEV2 or SEV3 |
| [challenge](skills/challenge/SKILL.md) | Ask another model family to pressure-test an idea, without implementing it |
| [focus-group](skills/focus-group/SKILL.md) | Run a product study with invented personas |
| [design-chooser](skills/design-chooser/SKILL.md) | Compare mockups from up to three model families and pick one before building |
| [agent-tuneup](skills/agent-tuneup/SKILL.md) | Inspect or change agent configuration, permissions and skill discovery |
| [test-writer](skills/test-writer/SKILL.md) | Add tests that catch real failures, and keep required CI under ten minutes |
| [file-upstream-bug](skills/file-upstream-bug/SKILL.md) | Reproduce a defect and report it to the project that owns it |
| [unslop](skills/unslop/SKILL.md) | Rewrite text that reads like model output |
| [full-send](skills/full-send/SKILL.md) | Carry an explicit "full send" through tests, review and a merged pull request |
| [grilling](skills/grilling/SKILL.md) | Interview you about the decisions that would change the plan |
| [ketchup](skills/ketchup/SKILL.md) | Catch you up on this chat, including decisions still waiting on you |
| [bro](skills/bro/SKILL.md) | Restate the last reply in plain language |

## Check a clone

```sh
python3 -B scripts/check_library.py
python3 -B -m unittest discover -s tests -v
```

The checks cover skill metadata, local links and helper behavior. They do not
call a model, and a pass does not prove that your host loaded the skills.
People changing a skill should also read [AGENTS.md](AGENTS.md).

Releases through v0.13.2 attach `t3-plugins` archives from an earlier package,
including its launcher. For the skills in this README, use the `skills` folders
in the current tree.

## Files that stay off this public repository

`.gitignore` keeps local configuration out of a clone. That includes MCP
settings, synced skill copies, marketplace state, the local plugin registry
and dotfiles wiring. Do not force-add ignored paths.

## Author maintenance

This section is only for the owner of `seankoji-com/.agents`. Do not run it
from a fork or a fresh clone.

```sh
python3 scripts/maintain.py        # test, commit, push main, update the owner's other checkouts
python3 scripts/maintain.py check  # tests only
python3 scripts/maintain.py sync   # retry the other checkouts
```

The publish command stages the current changes, asks the local Codex CLI for a
commit message, and fast-forwards `main`. It then updates `~/.agents` on the
SSH hosts named `wsl` and `mint`. It stops if checks fail, files change during
the run, the push is rejected, or a checkout on those hosts is dirty. Pull
requests are disabled on this repository. Organization workflows still run.

In T3, import `t3.json` and use the Publish action to run the same command.

## Security

Report vulnerabilities through the repository
[private advisory form](https://github.com/seankoji-com/.agents/security/advisories/new).
If that form is unavailable, use the
[organization security policy](https://github.com/seankoji-com/.github/blob/main/SECURITY.md).
Keep secrets and private logs out of public reports.
