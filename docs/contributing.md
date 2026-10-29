# Contributing

## Start small

Reproduce the problem and identify the owning layer before changing it. An agent
misreading a playbook, a helper accepting an unsafe path, and a T3 capability being
unavailable are different bugs. Include the evidence that distinguishes them.

Clone the repository, create a branch, and run:

```sh
python3 scripts/run_tests.py
```

The runtime has no package dependencies. Tests use temporary repositories and mock
external services; a loopback HTTP fixture verifies product behavior. Do not point
fixtures at production systems or authenticated model endpoints.

## Add or change a plugin

Write the canonical body and frontmatter in `skills/<kebab-case-name>/SKILL.md`.
Put its routing manifest in `plugins/<kebab-case-name>/plugin.json`, operations in
`playbooks/`, deterministic helpers in `scripts/`, and optional detail in
`references/` under that plugin. The source resolver materializes the pinned skill
and its package for execution outside the source checkout. Do not maintain a second
source entry body in the plugin directory.

Keep entries under 1,500 words. Load only the requested playbook. Put shared T3
instructions in `shared/t3-runtime.md`, not repeated paragraphs in every entry.
Model and provider choices come from the live host catalog. Tests enforce the core's
independence from plugin vocabulary and imports.

A plugin that delegates whole stages declares its workers in the manifest's `workers`
list and writes each definition to `agents/<worker>.md`, with no model IDs. Acceptance
belongs in a deterministic `scripts/validate_*.py` that reads coordinator
observations, never a worker's readiness claim. The entry adds only that plugin's
policy to `shared/job-coordination.md`. Record kept, changed and removed surfaces in
a stage shard under `migration/rebuild/compat-map.d/`.

Add tests for observable behavior and plausible failures: interruption, stale
evidence, missing files, malformed input, denied capabilities, and paths with spaces.
Do not add a test that merely repeats a constant from the implementation.

## Work on the site

Read [the design system](https://github.com/seankoji-com/.agents/blob/main/DESIGN.md)
before changing layout or styling. Use its existing colour, type and spacing tokens.

```sh
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r requirements-docs.txt
.venv-docs/bin/python -m mkdocs serve
```

Before submitting:

```sh
python3 scripts/check_docs.py
.venv-docs/bin/python -m mkdocs build --strict
```

Check navigation, search, code copying and diagrams at 390px, 768px and 1280px,
in light and dark mode, with keyboard focus, reduced motion and 200% zoom.
Tables and diagrams may scroll inside their frames; the page itself must not overflow.
`python3 scripts/capture_site.py --site site --out /tmp/shots` screenshots the key
pages at 1440px and 390px in both schemes with headless Chrome, and exits 1 if any
page overflows horizontally. Add `--zoom 200 --controls --width 1440` for the 200%
check: it sets Chrome's own page zoom (not a smaller window), then opens the
navigation, runs a search and copies a code block with real mouse and keyboard input,
saving a screenshot of each. Screenshots should show the actual rendered artifact,
use synthetic data, and state what they demonstrate. Never substitute an
illustration for live acceptance evidence.

The homepage, the plugin pages, and the sightings table are generated at build time
by the `scripts/field_guide.py` hook from `plugins/*/plugin.json`, `docs/field-guide.json`,
and `conformance/compatibility.json`. Adding a plugin means adding its entry to
`docs/field-guide.json` and a mark under `docs/assets/specimens/`; the build fails
if either is missing.

The terminal recording comes from real runs. `python3 scripts/capture_terminal.py`
runs the quickstart commands in an empty temporary home directory, replaces machine
paths with `~` and `<checkout>`, refuses to write if anything private survives, and
saves `docs/assets/recordings/*.json` and `*.txt`. `python3 scripts/render_demo.py`
turns the quickstart transcript into `docs/assets/demo.svg`; add `--video` (needs
headless Chrome and ffmpeg) to refresh `quickstart.mp4`, `quickstart.webm` and the
poster `quickstart-terminal.png`. A test fails when the committed SVG is stale. Never
hand-edit a transcript.
Fonts are bundled under `docs/assets/fonts/` (SIL OFL 1.1) so pages make no
third-party requests. Theme overrides live in `overrides/`.

## Open a PR

Describe the problem, resulting behavior, and verification. State live-provider gaps
plainly. The organization supplies issue forms and the PR template through its public
[`.github` repository](https://github.com/seankoji-com/.github). We intentionally have
no local template files that would shadow those defaults.

GitHub's [inheritance rules](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)
apply per file type; adding a local issue-template directory replaces the inherited
set. Keep common template changes in the organization repository.

Fork PR tests run on disposable GitHub-hosted runners, without repository secrets.
The organization gatekeeper remains required. Maintainers review agent-generated
changes under the same evidence standards as other contributions.
