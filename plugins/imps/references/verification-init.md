# verification-init

Creates `.agents/skills/verify-<project>/` in the current repository. It holds a recipe that launches, drives, observes and cleans up the real product. A recipe stays `draft` until one of its features has run end to end and the evidence is stamped into it. Never present a draft as verified.

Do not start production services, send real messages, or use production credentials to prove behaviour. If the only way to exercise the product is against production, stop and report that.

## 1. Discover

Inspect the repository to learn how the product:

- **launches**: a dev server command, CLI entry point or container. Prefer the project's own scripts and test harnesses.
- **reports readiness**: a health URL, a log line, or a file that appears.
- **is driven**: HTTP routes, CLI subcommands, or UI flows. For UI flows, see the preview toolkit section of `PKG/references/t3-adapter.md`.
- **is observed**: response bodies, output files, database rows in a disposable store.
- **is cleaned up**: stopping the process, removing temp data.

Pick up to five user-facing features. Write the facts to `scratch/facts.json` (schema: `PKG/core/schemas/recipe-facts.schema.json`). Use `${NAME}` variables, declared in `variables`, for values chosen at run time such as a free port or a process ID.

## 2. Scaffold

Invoke the core through the launcher, as `PKG/entry.md` says:

```text
python3 PKG/cli.py recipe-scaffold --repo <repo root> --input scratch/facts.json
```

This writes `SKILL.md`, `recipe.json` (status `draft`), `features/index.md` and one document per feature. Run `recipe-check --recipe <dir>/recipe.json`. It rejects placeholder text and undeclared variables.

## 3. Prove one feature

Start a run whose plan has one runtime requirement for the feature, for example `{"id": "REQ-VERIFY-CREATE", "kind": "runtime", "text": "F-CREATE recipe creates a note and lists it"}`, with `review.required: false` unless the operator wants one. Then:

1. Run the recipe's doctor commands.
2. Launch the product as the recipe says, in the background, from a disposable data directory. Record it as `resource` with `kind: process` and its `pid`, so cleanup and cancellation reach it and nothing else.
3. Wait for readiness within the stated timeout.
4. Execute each step, and save every request and response (or command and output) under `scratch/`.
5. Check each `expect` entry against what you captured. Record `acceptance` for the requirement with `kind: runtime`, and attach the captured files.
6. Clean up with the recipe's cleanup commands. Record `cleanup` for the process. Confirm it has stopped and that the captured evidence still exists.
7. Let `next` take the run to `ready` and `completed`. Stamping edits the recipe, so it comes after completion.
8. Stamp the recipe: `recipe-stamp --run-id <id> --recipe <dir>/recipe.json --feature F-CREATE --requirement REQ-VERIFY-CREATE`. This copies the evidence into `<dir>/evidence/<run-id>/` and sets `status: verified`. Run `recipe-check` again.

If any step fails, leave the recipe as `draft`, record the failure, and report what blocked it.

Other providers can load `SKILL.md` by explicit path; this directory is a convention, not a claim that every harness discovers it automatically.
