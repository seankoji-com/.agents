# Your first workflow

Start with a read-only check. After installation, run:

```sh
t3-plugins prompt imps doctor
```

Paste its output into a T3 thread attached to a repository. The agent locates the
plugin, discovers available T3 capabilities, and reports readiness. A missing
capability is a useful result: it tells you what prevents this workflow from running.

## Make a bounded change

Give imps a concrete failure and an observable success condition:

```text
Read ~/.local/share/t3-plugins/imps/current/entry.md and run:
run fix the word counter: "one two" on line 1 and "three" on line 2
currently returns 2; it should return 3. Verify locally, without publishing a PR.
```

Replace that example with a real bug in your repository. The agent records a plan,
implements the change, runs checks, and collects evidence. It inherits your provider
selection. Delegation is optional and uses T3's task APIs when the work warrants it.

The final report distinguishes completed, blocked, and unverified work. Retain its
run ID. A blocked run includes its reason and resume instructions.

## Resume or inspect

```sh
t3-plugins prompt imps status RUN_ID
t3-plugins prompt imps resume RUN_ID
t3-plugins prompt imps cancel RUN_ID
```

Paste the appropriate prompt into the same T3 thread. Run state normally lives under
`~/.local/state/t3-plugins/imps/runs/`. If the sandbox requires another state root,
the agent must report that path and use it consistently on subsequent commands.

## A model-free first result

To try the file tools without a model engine, create `input.txt` and this `request.json`
in a scratch project directory:

```json
{"operation":"sort_lines","input_path":"input.txt","output_path":"sorted.txt"}
```

```sh
python3 ~/.local/share/t3-plugins/offload-sidecar/current/scripts/process.py request.json
```

Inspect `sorted.txt` and the output hash in the receipt. This deterministic path needs
neither Ollama nor cloud authentication.
