# Ralph

Give Ralph a goal. Choose an implementer and an evaluator from different model
lineages. Ralph starts a fresh T3 implementation task, then a fresh evaluation task.
Every feedback item sends the work back to a new implementation task using the
original model and existing worktree.

```text
/t3-ralph fix the parser and add regression coverage
/t3-ralph --max-attempts 8 implement the export endpoint
/t3-ralph resume /path/to/ralph-state.json
/t3-ralph status /path/to/ralph-state.json
/t3-ralph cancel /path/to/ralph-state.json
```

Selecting `t3-ralph` from T3's slash menu inserts the portable skill mention.
`$t3-ralph <goal>` invokes the same entry.

## Choose the pair

Each new run asks for both models from the live T3 catalog, including custom models
and their available settings. Ralph keeps that pair throughout the run. A provider
can host several model lineages, so choosing different providers alone does not
establish independence. Unknown lineage labels need your confirmation. If the pair
cannot be verified as independent, the run cannot start.

Install the command with the usual [setup workflow](../slash-commands.md):

```sh
python3 bin/t3-plugins setup ralph
```

Run this from a source checkout containing Ralph. For a packaged catalog, first
check that `t3-plugins list` includes `ralph`, then use `t3-plugins setup ralph`.
Restart the agent session after setup. The installed adapter points to the versioned
Ralph package, which includes its checkpoint helper and shared T3 instructions.
Runtime modes are resolved per provider within the parent's boundary and shown
alongside the model choices. OpenCode requires Full Access because other modes can
stall on T3 permission requests. If you choose OpenCode from a narrower parent mode,
Ralph stops before dispatch and asks you to select Full Access for the parent.

## Feedback and stopping

The default limit is five implementation attempts, including the first. Use
`--max-attempts N` to change it. The evaluator reports whether the observable goal
was achieved, every feedback item, and the evidence it inspected. Success requires
both an achieved goal and no feedback. Even a minor suggestion triggers another
attempt. A failure verdict without feedback also triggers another attempt.

Children receive only the supplied brief. Ralph carries the original goal,
constraints, acceptance criteria, prior results, and all feedback into each new
task. Code remains in the same worktree. It does not resume a child's conversation,
discard previous attempts, or swap models after criticism.

A saved checkpoint keeps request IDs, task IDs, chosen targets, the worktree, and
round results across completion notifications and parent turns. T3 runs the tasks;
the helper only stores observations and prepares the next request. A lost dispatch
response stays uncertain until reconciled with the same request ID. No replacement
child starts while an earlier task or its descendants are still running.

Missing evidence, malformed evaluation, unavailable models and permission failures
stay visible. Changes during evaluation invalidate its verdict and require a fresh
evaluation. Exhausting the attempt limit reports the remaining feedback and the
checkpoint path. It never becomes a success claim.

Malformed verdicts and terminal provider failures record a recoverable blocker,
the raw result, and the saved task ID. After addressing the cause, `resume` records
a recovery reason and creates a fresh task with the same pair and worktree.
Implementation retries still count against the limit. Temporary pending child runs
clear after their terminal statuses are observed, restoring the earlier stage.
Missing model identity needs an exact saved T3 delegation receipt or authoritative
status; Ralph never guesses aliases or accepts an unverified model as success.

## PR delivery

Successful runs that produce code changes normally finish by opening a normal PR.
Ralph may edit, test, commit owned paths, push the task branch, and open that PR.
Your narrower instructions take precedence. It follows repository checks and
pre-PR review requirements, uses the intended base, and verifies the PR head.
It does not merge, deploy, release, or send messages without separate authority.
Runs with no code changes return the evaluated result without an empty PR.

The evaluator reviews committed output before publication. A subsequent edit or
commit requires fresh evaluation. Unrelated dirty work stays outside the commit.
The checkpoint reports paths changed since the run started. The parent still
checks ownership and whether those paths are code changes before opening a PR.
If publication fails, Ralph reports the evaluated result and the separate PR
delivery blocker. Current-head CI, merge, deployment and live acceptance remain
separate outcomes.

Cancellation stops only this run's tracked children. Ralph waits for T3 to confirm
they and their pending turns have stopped; requesting cancellation is not proof.
Keep the checkpoint until you are finished with the run. It can contain private
goal text and feedback, so store it outside the repository and do not commit it.
Checkpoint format 2 is separate from the original experimental format. Resume
older checkpoints using their original installed snapshot rather than rewriting them.

## Compatibility

Ralph is experimental. Behavioral tests cover checkpoints, feedback decisions,
revision invalidation, cancellation and installed helpers without live model calls.
They do not establish live provider compatibility or a completed model-driven run.
