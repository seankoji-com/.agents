# Live conformance procedure

Opt-in. It runs real providers through T3 and spends their quota. Run it from a T3 thread that is authorised to open one top-level thread per provider under test. That exception covers conformance only; imps itself never creates top-level threads for child work.

## 1. Prepare

```bash
python3 scripts/install.py
python3 scripts/conformance.py setup --dest "$TMPDIR/imps-conformance-fixture"
```

`setup` builds the wordstat fixture repository with one branch per critical case (`conformance/cases.json`). Each branch carries the case's repository policy in `.t3-plugins/imps.json`.

Call `orchestrator_capabilities` and list every provider instance. A provider with `canRunChildTask: false` is recorded as `unavailable` with its catalog reasons. Never log in, install or enable anything to make it run.

## 2. Probe child writes

From the conformance thread, start a delegated imps run whose plan pins one writing task to each available provider (`target`). `next` creates a sibling worktree per provider under the state root and dispatches a probe child to write a nonce there. The core then reads the marker itself and records `probes.<provider>.sibling_write`. Cancel the run afterwards and run the cleanup commands its report lists. Evidence: `conformance/probes/<t3-version>/`.

## 3. Run the critical cases

For each available provider, launch one top-level thread (`t3_thread_launch`, `scratch: true`, that provider's model, runtime mode no broader than the caller's). In that thread, send each case three times as separate messages:

```text
Case <case>, repeat <n>. Setup: in your working directory run `git clone -q -b <branch> <fixture> <case>-<n>` and work only inside that clone.

Then: <the case prompt from conformance/cases.json, with {entry} replaced by the absolute path of ~/.local/share/t3-plugins/imps/current/entry.md>
```

Wait for the thread to settle with `t3_thread_wait`. A delegated child wakes the parent through T3; wait again until no turn is running. For `pending-task`, follow the case's `interrupt` instruction: once the survey task has a host task ID in run state (`conformance.py find-run --worktree <clone>`), call `t3_thread_interrupt`, then send the resume message. An intervention is any other message sent to the thread; record each one.

## 4. Collect and grade

```bash
python3 scripts/conformance.py find-run --worktree <absolute clone path>
python3 scripts/conformance.py collect --run-id <run> --provider <id> --model <model> --case <case> --repeat <n> \
  --t3-version <server version> --thread-id <thread> --transcript <excerpt.md> --elapsed <seconds>
```

`collect` copies the core's JSON and Markdown report, the child result artifacts, a sanitised transcript excerpt (home directory replaced by `~`) and usage. It grades the repeat from run state, never from the model's prose. Repeats are never overwritten. A failure stays recorded; it is not rerun until it passes.

## 5. Classify

Update `conformance/compatibility.json`, then run `python3 scripts/conformance.py compile` to regenerate `compatibility.md`.

- `verified`: every critical case passed 3/3 repeats, with zero interventions and no false completion.
- `partial`: a critical case passed 1 or 2 of 3, or a case could not run.
- `unavailable`: the catalog says the provider cannot run (disabled, not installed, unauthenticated).
- `not tested`: available but not run, with the reason.

Unknown usage and cost stay `null`. An advertised model is not a verified one, and mocked tests prove nothing about a model.
