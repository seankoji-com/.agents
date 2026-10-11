# Your first workflow

Get a useful result before trusting a workflow with changes. Start in a T3 thread
attached to the repository you want to work on.

## 1. Check readiness

After [installation](getting-started.md), run this in your terminal:

```sh
t3-plugins prompt imps doctor
```

Copy the printed line into T3 and send it. This command prints instructions; it does
not call a model. The agent checks Python, Git, state storage and T3 capabilities,
and tells you what is available or missing. It changes no project files.

If you installed skills, you can instead select **t3-imps** from the `/` menu and
append `doctor`. See [slash commands](slash-commands.md).

## 2. Give it one bounded job

Run this in your terminal, replacing the task with a real failure in your project:

```sh
t3-plugins prompt imps run 'Fix the word counter: a file containing "one two" on line 1 and "three" on line 2 returns 2; it should return 3. Verify locally. Do not commit, push or open a PR.'
```

Paste the output into the same T3 thread. The generated prompt uses your installed
path, including a custom prefix. You do not need to type a path from this guide.

A useful task names the failure, expected behavior, and how far the agent may go.
For a feature, name the interaction and its acceptance condition. If you cannot yet
do that, start with [elephant-goldfish](plugins/elephant-goldfish.md).

## 3. Read the evidence

imps records a plan, makes the change, verifies it, and obtains the required review.
Its report gives you a run ID, artifacts, current readiness and remaining blockers.
An edit after verification makes that evidence stale. If an independent reviewer
cannot run, the agent reports the missing review; a plausible patch is not a pass.

Check the actual diff and result. Local completion does not imply that a PR was
created, CI passed, or a deployment works. These need separate authorization and
observations.

## Resume, inspect or stop

Keep the run ID and any custom state root from the report. Replace `RUN_ID` below:

```sh
t3-plugins prompt imps status RUN_ID
t3-plugins prompt imps resume RUN_ID
t3-plugins prompt imps cancel RUN_ID
```

Paste the appropriate prompt into the same T3 thread. `status` inspects the run;
`resume` finishes missing work; `cancel` confirms owned children and processes have
stopped. Run state defaults to `~/.local/state/t3-plugins/imps/runs/`.

## Try a helper without a model

[agent-tuneup](plugins/agent-tuneup.md#run-without-a-model) can audit a synthetic
settings file locally. This exercises an installed helper without consuming model
resources or changing provider settings.
