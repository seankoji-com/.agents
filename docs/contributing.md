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

Use `plugins/<kebab-case-name>/` with `plugin.json` and `entry.md`. Route operations to
small files under `playbooks/`; put deterministic helpers in `scripts/` and optional
detail in `references/`. A plugin must install and run outside the source checkout.

Keep entries under 1,500 words. Load only the requested playbook. Put shared T3
instructions in `shared/t3-runtime.md`, not repeated paragraphs in every entry.
Model and provider choices come from the live host catalog. Tests enforce the core's
independence from plugin vocabulary and imports.

Add tests for observable behavior and plausible failures: interruption, stale
evidence, missing files, malformed input, denied capabilities, and paths with spaces.
Do not add a test that merely repeats a constant from the implementation.

## Work on the site

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

Check navigation, search, code copying, diagrams, and mobile layout. Screenshots
should show the actual rendered artifact, use synthetic data, and state what they
demonstrate. Never substitute an illustration for live acceptance evidence.

The homepage, the plugin pages, and the sightings table are generated at build time
by the `scripts/field_guide.py` hook from `plugins/*/plugin.json`, `docs/field-guide.json`,
and `conformance/compatibility.json`. Adding a plugin means adding its entry to
`docs/field-guide.json` and a mark under `docs/assets/specimens/`; the build fails
if either is missing. The terminal recording is `docs/assets/demo.svg`, written by
`python3 scripts/render_demo.py`; a test fails when the committed file is stale.
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
