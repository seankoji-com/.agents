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
selection. It delegates through T3's task APIs when that pays off, under the
[shared delegation rules](https://github.com/seankoji-com/t3-plugins/blob/master/shared/delegation.md).

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

To try a local helper without a model, audit a copy of a Claude settings file:

```sh
python3 ~/.local/share/t3-plugins/agent-tuneup/current/scripts/audit.py \
  --provider claude --settings settings.json
```

It prints JSON findings with codes and locations, never setting values. Exit `0` means
clean and `1` means findings. The audit reads the file and changes nothing.
