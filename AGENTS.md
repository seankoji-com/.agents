# Working on .agents

This is a Markdown skill library. Start with README.md, then the relevant
`skills/<name>/SKILL.md`. Supporting templates/references/scripts belong inside
that skill. `references/planning.md` remains for global compatibility callers.
There are no generic role files; discover host-native roles only when useful.

Keep ten skills directly loadable with standard name/description metadata, clear
triggers, workflow, outputs and authorization/evidence boundaries. Entries stay
under 1,500 words. Use kebab-case folders, snake_case Python and test_*.py. Do not
introduce a launcher, package registry, job/receipt engine, provider SDK, fixed
model IDs, shell agent broker or second scheduler. Instructions do not enforce
permissions, freshness or acceptance in software.

Inspect the tree before editing; preserve unrelated work/ignored local state.
Stage explicit owned paths and inspect the staged diff before commits. Never copy
credentials, private transcripts, machine paths or private hostnames into fixtures.
Helpers are exceptional: keep them relocatable, Python 3.10+ and stdlib-only with
focused behavior/relocation tests. Prefer native tools. Roughly 1,000 executable
helper lines is a design budget; justify larger additions.

Run `python3 scripts/check_library.py` and
`python3 -m unittest discover -s tests -v`. Tests must not call live models or mutate
GitHub. Keep mandatory organization workflows. No historical fixture fetching,
package build or documentation build is required. Execute copied skill helpers
from a foreign working directory when changing them.

External discovery/configuration belongs to its owning repository. Review/check
that source before host cutover; preserve installations, active jobs, credentials,
vendor skills, ignored settings and marketplace state. Do not alter the published
website from source cleanup. Keep local checks, independent review, current-head
CI, permitted merge, deployment and fresh-session acceptance separate. Fixtures
never prove native provider compatibility.
