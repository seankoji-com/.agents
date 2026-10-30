# .agents

Fourteen skills for engineering and agent workflows. Each folder contains
its instructions and any supporting references, templates or helpers.

| Skill | Use it for |
| --- | --- |
| [imps](skills/imps/SKILL.md) | Implementation, investigation, audits and reviews |
| [plan](skills/plan/SKILL.md) | Planning, specifications and handoffs |
| [babysitter](skills/babysitter/SKILL.md) | PR review, CI repairs and native watches |
| [review-loop](skills/review-loop/SKILL.md) | Implementation with bounded independent review and repair |
| [challenge](skills/challenge/SKILL.md) | Read-only cross-lineage pressure testing of ideas and designs |
| [focus-group](skills/focus-group/SKILL.md) | Synthetic persona studies |
| [agent-tuneup](skills/agent-tuneup/SKILL.md) | Agent configuration, permissions and discovery |
| [test-writer](skills/test-writer/SKILL.md) | High-value tests and a hard ten-minute CI execution cap |
| [file-upstream-bug](skills/file-upstream-bug/SKILL.md) | Reproduction and upstream reporting |
| [unslop](skills/unslop/SKILL.md) | Plain, specific writing |
| [full-send](skills/full-send/SKILL.md) | Autonomous implementation, verification, PR review and merge |
| [grilling](skills/grilling/SKILL.md) | Stress-testing plans, decisions and ideas through questions |
| [ketchup](skills/ketchup/SKILL.md) | Catching up on chat progress and pending decisions |
| [bro](skills/bro/SKILL.md) | Restating the last response in plain language |

## Use

Read a skill's `SKILL.md` directly or expose its folder through the host's native
skill discovery. Each folder can be copied independently. Preserve existing and
vendor skills when configuring discovery. Native tool and delegation support varies
by host; report unavailable capabilities. Optional helpers need Python 3.10+ only.

Skills use their own section layouts; validation checks metadata and nonempty
instructions rather than fixed headings. Their prerequisites vary:

- `full-send` uses the included `review-loop` and `babysitter`, with native tools
  to create the PR.
- `review-loop` and `challenge` need native delegation to a model from another
  lineage. They preserve explicit choices and otherwise select in this order:
  Sol, Opus, Wonder Full, Argon, Grok 4.7. Model IDs come from host discovery.
- `ketchup` uses the included `bro` and native presentation tools. In T3 Code,
  catch-ups and substantive reports use `html_preview` then `html_render` for
  readable comparisons, findings and decisions. Other hosts use their native
  presentation tools or readable text. No rendering server is needed.

Slash-command invocation syntax depends on the host's native skill discovery.

Dotfiles owns host configuration and skill registration. Its migration to the revised
library is tracked in [dotfiles#601](https://github.com/seankoji-com/.dotfiles/issues/601).
Preserve ignored local settings and active jobs.

## Contribute and verify

Read [AGENTS.md](AGENTS.md), edit the owning skill and keep helpers relocatable and
stdlib-only. Use synthetic fixtures. Run:

```sh
python3 -B scripts/check_library.py
python3 -B -m unittest discover -s tests -v
```

Checks cover metadata, links, helper behavior and relocation. They do not establish
native provider compatibility or live acceptance. Keep organization workflows and
report local validation, hosted CI, review and delivery separately.

## Local maintenance

Edit in VS Code, then run:

```sh
python3 scripts/maintain.py        # Test, AI commit message, commit, push, update hosts
python3 scripts/maintain.py check  # Tests only
python3 scripts/maintain.py sync   # Retry host updates only
```

The script stages all nonignored changes, uses your authenticated Codex CLI for
the message, and pushes `main`. It then updates `~/.agents` through `ssh wsl` and
`ssh mint`, runs their tests and refreshes skill discovery through dotfiles.
It stops on failed checks, changed files, push rejection or dirty host checkouts.
A failed push keeps the local commit; rerunning retries without another commit.
The existing local pre-commit hook remains supported.
In T3's project Actions settings, import `t3.json`, then click **Publish**.

Pull requests are disabled. The repo-only dotfiles and GitHub rule exceptions
must permit direct fast-forward pushes. Mandatory organization workflows remain;
local tests do not establish hosted CI or fresh-session skill loading.

## Security

Report vulnerabilities through the repository's
[private advisory form](https://github.com/seankoji-com/.agents/security/advisories/new).
If unavailable, follow the [organization security policy](https://github.com/seankoji-com/.github/blob/main/SECURITY.md).
Keep secrets and private logs out of public reports.
