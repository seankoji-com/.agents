# Your first imps run

This page takes one real bug from task to evidence. You need the catalog
[installed](getting-started.md) and a T3 thread attached to the repository with the bug.

## 1. Check readiness

```text
$t3-imps doctor
```

The agent checks Python, Git, its state directory and T3's live provider list, then
says what it can and can't run. It changes no files. If `/` doesn't list `t3-imps`,
run `t3-plugins prompt imps doctor` in a terminal and paste the line it prints. See
[slash commands](slash-commands.md) for provider-specific skill folders.

## 2. Give it one bounded job

Name the failure, the expected behaviour, and how far the agent may go:

```text
$t3-imps run Fix the word counter: a file containing "one two" on line 1 and "three" on line 2 returns 2; it should return 3. Verify locally. Do not commit, push or open a PR.
```

The last sentence sets the endstate. imps defaults to local work, and it won't commit
or open a PR unless you say so. For a feature, describe the interaction and how you'll
know it works. If you can't write that sentence yet, run
[elephant-goldfish](plugins/elephant-goldfish.md) first.

Without the slash menu, generate the same prompt in a terminal:

```sh
t3-plugins prompt imps run 'Fix the word counter: a file containing "one two" on line 1 and "three" on line 2 returns 2; it should return 3. Verify locally. Do not commit, push or open a PR.'
```

## 3. Read the evidence

imps writes a plan with numbered requirements, makes the change, runs the checks it
planned, and gets an independent review. Its report gives you:

- a run ID and the state directory, so you can resume later;
- each requirement with the check or review that covered it, and the revision it ran on;
- paths to the saved check output;
- anything still blocked, and why.

Any edit after a check makes that check stale, and the report says so. The reviewer
comes from a different model lineage when one is available. If none is, imps falls
back to a same-lineage reviewer and records why it chose that reviewer. Without
lineage data in your routing config, reviewer independence is reported as unverified.
The review is listed as missing when no reviewer returned a verdict; a verdict on an
older revision is listed as stale. A repository review policy that asks for more
overrides the fallback. A plausible patch is not a pass.

Read the diff yourself as well. A local pass says nothing about CI, a merge or a
deployment; each needs its own authorization and its own observation.

## Resume, inspect or stop

Keep the run ID from the report. In the same thread:

```text
$t3-imps status RUN_ID
$t3-imps resume RUN_ID
$t3-imps cancel RUN_ID
```

`status` shows the run without changing it. `resume` finishes missing work. `cancel`
confirms that the run's child tasks and processes have stopped. Run state lives in
`~/.local/state/t3-plugins/imps/runs/` unless the report names another state root.

Larger work runs as a job, and the report gives a job ID instead. The same three
operations take it. `status` shows each stage, the current stage, open decisions,
blockers and any `fallback: direct` marker. `resume` reads that overview and checks
every recorded task before starting anything new; see
[resume a job](troubleshooting.md#resume-a-job-after-an-interruption).

## Try a helper without a model

[agent-tuneup](plugins/agent-tuneup.md#run-without-a-model) can audit a synthetic
settings file locally. It uses no model and changes no provider settings.
