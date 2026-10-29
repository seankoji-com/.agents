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

## Local maintenance

Edit in VS Code, then validate without committing:

```sh
python3 scripts/maintain.py check
```

For one-command publishing, copy `scripts/maintain.example.json` to the ignored
`.maintain.json`. An empty `message_command` uses your authenticated Codex CLI in
an ephemeral, read-only session outside the checkout, with user configuration,
project instructions, shell, apps and delegation disabled. No model is pinned.
To use another AI tool, set `message_command` to its argv array. It receives a
prompt and the complete staged diff on stdin and must print
only a commit message to stdout. Configure that tool for text generation without
tools or file writes. Its normal authentication and billing apply. No model or
provider is selected by this repository. Do not put secrets in command arguments.
Diffs larger than 1 MiB need splitting. Binary content is included in the diff.

Add each receiver to `hosts`, for example
`{"ssh": "receiver-alias", "path": "/srv/skill-library"}`. Use aliases from your
SSH config and absolute POSIX paths for the existing WSL and Mint checkouts.
The hosts need Python 3.10+, Git, noninteractive SSH/Git authentication, the same
origin URL as this checkout, and a clean `main` branch. Configure host aliases and
native skill discovery through dotfiles. To refresh discovery after delivery, add
`"refresh_skills": true` to the host. This requires its checkout at `~/.agents`
and runs `~/.dotfiles/scripts/t3-workflow-skills.py install` followed by `check`.
It preserves the registrar's existing ownership checks and vendor-skill handling.
There is no plugin package to reinstall.

```sh
python3 scripts/maintain.py
```

This validates, stages **all nonignored edits, additions and deletions**, generates
and prints the AI message, commits with your existing Git identity/hooks/signing,
pushes `HEAD` to `origin/main`, and fast-forwards each configured host to that exact
commit. Running `publish` is authorization for all those actions; there is no
second confirmation. Review your diff and ignored files first. The AI receives
the staged diff through the command you configured. Failed generation retains
staging. Files changed during validation or generation stop publication.

Resolve a behind or diverged author branch yourself, then rerun. A rejected push
retains the local commit; rerunning `publish` retries it without another message
or commit when the tree is clean. Delivery attempts every host and reports partial
failure. Retry host delivery alone with:

```sh
python3 scripts/maintain.py sync
```

Receivers reject dirty trees, another origin, another branch or a moved remote
tip. They never stash, reset, force-push or reinstall anything. After updating, each
host runs the checker and tests. A host check failure leaves the received commit
in place and returns failure. Empty `hosts` means no delivery. Host checks do not
prove that fresh agent sessions loaded the skills.

Optional local pre-commit validation:

```sh
python3 scripts/maintain.py install-hook
```

This installs the same checks for fully staged changes, using the current
Python interpreter. It refuses existing hooks or a custom hooks directory. Add
`python3 scripts/maintain.py hook` to your existing manager instead. Reinstall if
the interpreter moves. Remove the generated `pre-commit` file to uninstall it.
Publishing with the hook installed runs validation again at commit time.
If your manager forwards to the common Git hooks directory, as dotfiles' t3-guard
does, use `install-hook --forwarded-hooks`. This preserves the global dispatcher
and its push guard. Never use this flag for a manager that does not forward there.

Owner maintenance publishes directly to `main`; `master` is historical. Pull
requests are disabled for this repository. Direct publication needs the owner-run
`.agents` exceptions in GitHub's inherited PR, gatekeeper and CodeQL rulesets,
with repository-level history protections retained. Repository admin access alone
does not establish bypass of every inherited rule. This script neither changes
rules nor attempts an override, and stops on push rejection. Keep mandatory
organization workflows. Local validation is separate from hosted CI.

The dotfiles t3-guard also needs its exact `.agents` fast-forward exception.
That exception accepts only existing `main` from checked-out `main` at the
canonical GitHub endpoint. It retains the other environment, URL and hook checks
and does not allow force pushes, deletion or creation. Installing the validation
hook alone does not change push policy.

## Security

Report vulnerabilities through the repository's
[private advisory form](https://github.com/seankoji-com/.agents/security/advisories/new).
If unavailable, follow the [organization security policy](https://github.com/seankoji-com/.github/blob/main/SECURITY.md).
Keep secrets and private logs out of public reports.
