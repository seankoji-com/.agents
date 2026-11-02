# .agents

Seventeen skills for coding agents. Each skill is a folder. The agent reads
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
- `grilling` links to `review` for its stop-condition check and `design-chooser` for UI implementation
- `grilling` and review's deferred-bug procedure use `raise-issue` for issue filing
- `review-loop`, `raise-pr`, `babysitter`, `challenge` and `focus-group` use `review`
- `ship` links to `review-loop` and `babysitter`
- `review-loop`, `ship` and `babysitter` link to `raise-pr`
- `implement` uses `review-loop` and `review` before returning reviewed commits

Helpers, where a skill has one, need Python 3.10 or newer and the standard
library only. Reading a skill needs no install step.

These instructions were written against T3 Code and Codex. Another host can
follow them when it can read files, run commands, and perform the actions the
skill names. Follow each skill's fallback rules when a named tool is missing.
`implement` and asynchronous `raise-issue` require T3 delegation; an unavailable
route is a reported blocker unless the user explicitly requests inline issue work.

`review` selects a reviewer from a different model family than the coordinator
and every model that materially authored the reviewed work. It tries these in
order: **Sol, Opus, Wonder Full, Argon, Grok 4.7**, using exact identities from
the host. A named same-family reviewer is a conflict, not an exception.
`review-loop` participants apply that shared rule and the evidence requirements
on every review round. `grilling` obtains a second opinion on its stop condition
before handing off; unresolved material decisions return to the interview.

Confirmed bugs left unfixed must have verified tracking issues, including
non-blocking SEV3 bugs. The coordinator validates and files them under review's
shared rules; reviewers return findings. Invoking `implement`, `ship` or
`babysitter` includes this task-related issue filing unless explicitly limited.
Final handoffs link each deferred bug to its issue or identify blocked tracking.

`raise-issue` delegates preparation and authorised filing asynchronously through
T3. The top-level workflow owner owns those jobs, including an independently
launched repository or PR owner; child delegates return filing requests to it.
Already non-blocking bugs may merge while filing is pending, and the overall
workflow remains active until the issue URLs are verified. Issue writers reuse
validated evidence rather than restarting a thorough investigation by default.

`implement` moves coding into a working-lead T3 delegate in an isolated
worktree. It selects task-appropriate models for expected total cost, with one
evidenced automatic model/effort upgrade across the task. Its reviews use the
same cost-aware selection while preserving cross-lineage eligibility; other
workflows keep the reviewer order above. It returns reviewed local commits for
the main thread to integrate and ship. It requires T3 delegation support.

`design-chooser` asks one to three models, each from a different family, for two
or three mockups each. It uses the same model order and shows each mockup inline
in T3 Code, then waits for you to pick one.

`ship` and `babysitter` may commit, push and merge after you invoke them.
Read those two before you use them. Limits you set in the request still apply.

In T3 Code, the main thread presents longer reports through the host HTML preview.
Delegates return complete plain text to their coordinator. Other hosts get the
same content as text.

## Skills

| Skill | What you use it for |
| --- | --- |
| [implement](skills/implement/SKILL.md) | Delegate implementation into an isolated T3 worktree and return reviewed commits |
| [babysitter](skills/babysitter/SKILL.md) | Watch pull requests, repair them, and merge when the gates pass |
| [raise-pr](skills/raise-pr/SKILL.md) | Create or update PRs with templates, screenshots, agent attribution and independent review |
| [review-loop](skills/review-loop/SKILL.md) | Implement, then repeat an independent review and repair within a set limit |
| [review](skills/review/SKILL.md) | Obtain cross-lineage review, record evidence and classify consequential findings |
| [challenge](skills/challenge/SKILL.md) | Ask another model family to pressure-test an idea, without implementing it |
| [focus-group](skills/focus-group/SKILL.md) | Run a product study with invented personas |
| [design-chooser](skills/design-chooser/SKILL.md) | Choose between UI designs when settled product decisions leave a material visual or interaction choice unresolved |
| [agent-tuneup](skills/agent-tuneup/SKILL.md) | Inspect or change agent configuration, permissions and skill discovery |
| [agent-docs](skills/agent-docs/SKILL.md) | Write, edit or audit skills and AGENTS.md/CLAUDE.md so agents follow them the same way each run |
| [test-writer](skills/test-writer/SKILL.md) | Add tests that catch real failures, and keep required CI under ten minutes |
| [raise-issue](skills/raise-issue/SKILL.md) | Prepare, file or follow up on bugs, features and tasks in owned, organisation or upstream repositories |
| [unslop](skills/unslop/SKILL.md) | Rewrite text that reads like model output |
| [ship](skills/ship/SKILL.md) | Carry an explicit "ship" through tests, review and a merged pull request |
| [grilling](skills/grilling/SKILL.md) | Settle decisions through questions and produce an implementation brief |
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
