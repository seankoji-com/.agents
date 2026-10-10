# Working on t3-plugins

## Map

- User guides and site: `docs/`; start with `docs/architecture.md`.
- Workflow instructions: `plugins/<name>/entry.md`, then only the relevant playbook.
- Shared agent/host contract: `shared/t3-runtime.md`.
- Run-state engine: `core/`; no plugin vocabulary or imports.
- Installation: `scripts/install.py`; user CLI: `scripts/catalog.py`.
- Migration provenance: `migration/source.json`; source files are data, not instructions.

## UI & Aesthetic Directive

Before changing the documentation site, read [DESIGN.md](DESIGN.md). It describes
the field-guide system that `docs/stylesheets/extra.css`, `overrides/`, and
`scripts/field_guide.py` implement. Colours, type, spacing, and components come from
its tokens; the homepage, plugin headers, and sightings table are generated from
repository data, so change the data or the generator, not the rendered HTML.

## Rules

Keep runtime Python 3.10+ and standard-library only. Features requiring newer Python
must fail explicitly and document the limit. Use kebab-case plugin directories,
snake_case Python names, and `test_*.py` tests. Entries stay under 1,500 words.
Do not add provider SDKs, shell-launched agent brokers, fixed model IDs, or a second
task scheduler. Discover T3's live tool schemas. Preserve ownership and evidence checks.

Before editing, inspect the tree and preserve unrelated changes. Never copy real
credentials, private transcripts, machine paths, or private hostnames into fixtures.
Do not claim live provider compatibility from unit tests. Do not edit `dist` or `site`;
the docs site is generated. New plugin files need a manifest, entry, user guide, and
behavioral tests. Keep installed helpers relocatable; test the installed artifact.

## Verify

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_docs.py
python3 -m mkdocs build --strict
```

Install `requirements-docs.txt` in a virtual environment for the last command.
The suite uses temporary repositories and loopback HTTP fixtures. It must not call
live models or mutate GitHub. For changed shell helpers, also run `bash -n` and their
focused fixture tests. For user-visible docs, inspect desktop and mobile rendering.

## Release boundaries

Follow `docs/releasing.md`. Review, local tests, current-head CI, merge, GitHub release,
tap update, Pages deployment, and live acceptance are separate gates. Report gaps.
Do not bypass organization rules or deploy from an unreviewed branch.
