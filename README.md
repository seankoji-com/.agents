# .agents

Ten Markdown skills for engineering and agent workflows. Read a skill's `SKILL.md`
directly or expose its folder through native skill discovery. Each folder carries
its instructions and local helpers. No launcher, installed workflow package, job
engine, provider SDK or documentation build is needed.

| Skill | Use it for |
| --- | --- |
| [imps](skills/imps/SKILL.md) | Implementation, investigation, audits and reviews |
| [plan](skills/plan/SKILL.md) | Discovery, specification and reviewed handoff |
| [ape](skills/ape/SKILL.md) | Commit-pinned open-source research |
| [babysitter](skills/babysitter/SKILL.md) | Authorized PR repairs and native watches |
| [ralph](skills/ralph/SKILL.md) | Bounded implementation/evaluation cycles |
| [focus-group](skills/focus-group/SKILL.md) | Synthetic persona studies |
| [agent-tuneup](skills/agent-tuneup/SKILL.md) | Configuration and permission inspection |
| [tests-omg](skills/tests-omg/SKILL.md) | Test protection and validation cost |
| [bug-report](skills/bug-report/SKILL.md) | Reproduction and upstream reporting |
| [unslop](skills/unslop/SKILL.md) | Plain, specific writing |

## Direct use and updates

Clone `https://github.com/seankoji-com/.agents.git` into your chosen source location.
Open the Markdown and follow it using native tools. For discovery configure the
host's documented skill root or link individual folders into it. Invocation names
and support vary by host. Never overwrite existing skills or vendor directories
to make an alias. Each skill folder can also be copied elsewhere independently.

Use needs a Markdown-capable agent and the task's native tools, such as Git/GitHub
access. Delegated workflows need authorized native tasks; Ralph also needs distinct
verified work/review lineages. Report unavailable capabilities rather than silently
substituting a broker. Python 3.10+ is needed only for optional stdlib helpers and
library checks. Helper input formats are in `--help`. The JSON configuration scanner
omits values but its key pointers can still be private; the timing summarizer reads
attempts without executing tests. Planning templates need no renderer.

For updates inspect `git status`, preserve local changes/untracked skills, fetch
the intended remote and review the incoming revision. Use an ordinary fast-forward
Git update only when compatible with the checkout. There is no automatic receiver
or self-update. Record `git rev-parse HEAD` when provenance matters.

## Cutover and rollback

This source retires the runtime and site build. Before updating an active checkout,
inventory native roots/aliases, generated registrations, shell startup, bootstrap,
receiver services, context pins and live role callers. External configuration must
change through its owning repository with required review/checks. The companion
dotfiles change replaces acquisition/registration with Git/native discovery and
removes live role dependencies; pair those reviewed changes in delivery. The small
[planning reference](references/planning.md) remains for global callers.
The root `.agents-source.json` is retained byte-for-byte as compatibility data for
existing dotfiles ownership guards. Standalone skills do not read it or use its
historical bootstrap fields. Remove it only after those guards no longer need it.

Checkpoint source HEAD/status and tracked patches plus selected untracked source
files before cutover. Verify reconstruction, including Git archive exclusions.
Back up each changed managed configuration/alias host-locally with restricted
access, before revision/target, restore location and exact restore map. Record
service enabled/active state without enabling disabled receivers. Coordinate
active jobs before changing callers. Preserve old installations, jobs, credentials,
vendor skills, synchronized skill buckets, ignored settings, registry locks and
marketplace metadata in place. Source deletion authorizes no local-state deletion.
Never blanket-copy an archive over a live checkout.

Deploy only reviewed merged source through permitted checks/merge paths. Then
confirm source revision and all ten folders in fresh native sessions on each
target, run helper/relocation checks, inspect remaining managed callers and verify
preserved state. Static aliases and fixtures do not prove this. Rollback restores
only recorded managed files/aliases and reviewed source revision, preserving
unrelated/ignored state and prior service status. Retain old installations until
rollback needs are resolved; never blindly invoke retired bootstrap machinery.
Removing site source does not alter the published website; its disposition needs
a separate owner decision.

## Retired guarantees

Git history replaces immutable package pinning; readable notes/native handles
replace opaque jobs/receipts. Native capabilities replace a model registry; normal
Git updates replace source receiving. Software-enforced evidence freshness,
acceptance and historical runtime compatibility are gone. Markdown does not retain
these guarantees. Host permissions, organization reviews, current-head checks and
honest evidence remain necessary.

## Verification

```sh
python3 scripts/check_library.py
python3 -m unittest discover -s tests -v
```

CI checks the library/helpers on supported Python versions and retains organization
readiness, gatekeeper, static-analysis and Dependabot controls. Tests use synthetic
fixtures, never live models or GitHub writes. Local checks, independent review,
current-head CI, merge, installed revision and fresh-session live acceptance are
separate gates. See [contributing](CONTRIBUTING.md) and [security](SECURITY.md).
