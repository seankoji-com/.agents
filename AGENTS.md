# Working on .agents

Read README.md and the relevant `skills/<name>/SKILL.md`. Keep each skill independently
usable, with name/description metadata, clear triggers and an entrypoint under 1,500
words. Supporting references, templates and helpers belong inside that skill.

Prefer native tools. Do not introduce a launcher, runtime engine, model registry,
provider SDK or second scheduler. Exceptional helpers must be relocatable, Python
3.10+ and stdlib-only, with meaningful behavior and relocation tests.

Inspect the tree and preserve unrelated work. Stage explicit paths and inspect the
staged diff before committing. Fixtures must use synthetic data, never credentials,
private transcripts, machine paths or private hostnames.

Run `python3 scripts/check_library.py` and
`python3 -m unittest discover -s tests -v`. Tests must not call live models or mutate
GitHub. Run changed skill helpers from a foreign working directory. Keep mandatory
organization workflows; no package or documentation build is needed.

Owner maintenance publishes by fast-forward pushes to `main`. Do not create pull
requests for this repository. Use `python3 scripts/maintain.py` for validation,
commit-message generation, committing, pushing and configured host delivery.
Keep the repository-only direct-publish exceptions narrow; never force-push.

Dotfiles owns external configuration. Preserve installed skills, active jobs,
credentials, ignored settings and marketplace state until their callers are migrated
through that owner. Source cleanup does not change the published website. Report
local checks, hosted CI, review, merge, deployment and fresh-session acceptance separately.
