# Working on .agents

Read README.md and the relevant `skills/<name>/SKILL.md`. Keep each skill independently
usable, with name/description metadata, clear triggers and an entrypoint under 1,500
words. Supporting references, templates and helpers belong inside that skill.

Write for a strong coordinator and cheap children. A dispatched child reads a
role card under `skills/review/references/`, never a whole skill; cards stay
under 600 words and link to nothing. When a skill links a file, say when to read
it. Prefer numbered steps and one rule per bullet over long paragraphs. Run
`python3 scripts/check_library.py --stats` before and after an edit to see the
words each skill loads.

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
requests for this repository. Use `python3 scripts/maintain.py check` for validation
alone. The default command generates a commit message, commits, pushes and delivers
to configured hosts only within existing publication authority. Before publishing
or syncing, follow README.md's owner-maintenance setup for the repository-local
`.env`. Keep personal destinations and config backups untracked; use synthetic
values in the checked-in `.env.example` and fixtures. Checks and hooks need no
local host configuration.
Keep the repository-only direct-publish exceptions narrow; never force-push.

Dotfiles owns external configuration. Preserve installed skills, active jobs,
credentials, ignored settings and marketplace state. The README is the reference documentation. `site/index.html`
is the user-facing GitHub Pages site and `site/workflows.html` is its workflow guide;
keep the skill list, diagrams and plain-language copy in step with skill changes.
`pages.yml` is the only Pages workflow; a second one would overwrite the site. Report
local checks, hosted CI, review, merge, deployment and fresh-session acceptance separately.
