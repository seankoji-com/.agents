# .agents

Fourteen skills for engineering and agent workflows. Each folder contains
its instructions and any supporting references, templates or helpers.

| Skill | Use it for |
| --- | --- |
| [imps](skills/imps/SKILL.md) | Implementation, investigation, audits and reviews |
| [plan](skills/plan/SKILL.md) | Planning, specifications and handoffs |
| [babysitter](skills/babysitter/SKILL.md) | PR review, CI repairs and native watches |
| [review-loop](skills/review-loop/SKILL.md) | Implementation with bounded independent review and repair |
| [focus-group](skills/focus-group/SKILL.md) | Synthetic persona studies |
| [agent-tuneup](skills/agent-tuneup/SKILL.md) | Agent configuration, permissions and discovery |
| [test-writer](skills/test-writer/SKILL.md) | High-value tests and CI feedback within ten minutes |
| [file-upstream-bug](skills/file-upstream-bug/SKILL.md) | Reproduction and upstream reporting |
| [unslop](skills/unslop/SKILL.md) | Plain, specific writing |
| [full-send](skills/full-send/SKILL.md) | Autonomous implementation, verification, PR review and merge |
| [sol-loop](skills/sol-loop/SKILL.md) | Bounded Sol review and repair loops |
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
- `sol-loop` needs a host route to Sol through T3 delegation or a native Sol agent.
  It reports a blocker when neither route is available.
- `ketchup` uses the included `bro` and host-provided visualization tools. It reuses
  existing captures and marks missing screenshots rather than starting an app.

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

## Security

Report vulnerabilities through the repository's
[private advisory form](https://github.com/seankoji-com/.agents/security/advisories/new).
If unavailable, follow the [organization security policy](https://github.com/seankoji-com/.github/blob/main/SECURITY.md).
Keep secrets and private logs out of public reports.
