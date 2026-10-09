# t3-plugins

Plugins for [T3 Code](https://github.com/pingdotgg/t3code), built on a shared core that knows nothing about any one plugin.

| Path | What it is |
| --- | --- |
| `core/` | Workflow-state core: run records, ownership and generations, readiness, evidence, path safety, published JSON Schemas, CLI. Python 3.10+, stdlib only. Contains no plugin vocabulary; `tests/test_contract.py` enforces that. |
| `plugins/imps/` | **imps**: bug fixes and bounded changes in a T3 thread, direct or delegated through T3's own task tools, with revision-bound evidence and independent review. Start at `plugins/imps/entry.md`. |
| `scripts/install.py` | Installs any plugin under `plugins/` together with its own copy of `core/`. |
| `conformance/` | Live provider compatibility results and the procedure that produces them. |
| `tests/` | Deterministic tests; `tests/README.md` maps each source-spec case to its tests. |
| `thinking/imps-t3/` | Design brief, rubric and decisions behind imps v1. |

## Install

```bash
git clone https://github.com/seankoji-com/t3-plugins.git ~/repos/t3-plugins
python3 ~/repos/t3-plugins/scripts/install.py --dry-run
python3 ~/repos/t3-plugins/scripts/install.py
```

The installer copies a versioned snapshot to `~/.local/share/t3-plugins/imps/<version>/`, writes `install-manifest.json` there, and points `~/.local/share/t3-plugins/imps/current` at it. It prints the fully expanded entry path. That path stays the same across upgrades:

```text
~/.local/share/t3-plugins/imps/current/entry.md
```

Upgrade: `git -C ~/repos/t3-plugins pull`, then run the installer again. Roll back: `python3 ~/repos/t3-plugins/scripts/install.py --activate 0.1.0+g6ad2d0b1c5e3` (the installer output and the directory listing name each installed version). A locally edited installed file makes the installer refuse; `--force` overwrites it.

## Use it from a T3 thread

Paste into any T3 thread, on any provider:

```text
Read ~/.local/share/t3-plugins/imps/current/entry.md and run: doctor
```

```text
Read ~/.local/share/t3-plugins/imps/current/entry.md and run: run fix the wordstat count bug: a file with "one two" on line 1 and "three" on line 2 prints 2 instead of 3
```

The run prints its run ID and ends with a report. To pick it up again later, or after an interruption, in the same thread:

```text
Read ~/.local/share/t3-plugins/imps/current/entry.md and run: resume 20261009-131500-5f0c2a
```

```text
Read ~/.local/share/t3-plugins/imps/current/entry.md and run: status 20261009-131500-5f0c2a
```

```text
Read ~/.local/share/t3-plugins/imps/current/entry.md and run: cancel 20261009-131500-5f0c2a
```

The same operations from a shell, without a model:

```bash
python3 ~/.local/share/t3-plugins/imps/current/core/cli.py status --run-id 20261009-131500-5f0c2a
python3 ~/.local/share/t3-plugins/imps/current/core/cli.py report --run-id 20261009-131500-5f0c2a
```

Run state and evidence live in `~/.local/state/t3-plugins/imps/runs/<run-id>/`. Nothing there is removed by cleanup or uninstall. A blocked run's report prints its exact resume command; `conformance/results/` has real examples.

## Test

```bash
cd ~/repos/t3-plugins
python3 -m unittest discover -s tests -v
```

## Uninstall

```bash
python3 ~/repos/t3-plugins/scripts/install.py --uninstall
```

This removes only the files listed in each version's manifest. Files you added, other plugins and `~/.local/state/t3-plugins/` are left alone.

## Compatibility

Live results per provider, with T3 version, model IDs, repeats and artifacts, are in [`conformance/compatibility.md`](conformance/compatibility.md). The promise is identical workflow rules, artifact formats and completion criteria. Model judgment, quality and latency still differ by provider.
