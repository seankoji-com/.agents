# Delegated mode

Load this when the plan uses `"execution": {"mode": "delegated"}`.

## When to delegate

Delegate a task only when it resolves a distinct unknown or produces an output you can check independently: a read-only survey, a fix in a separate module, a second implementation to compare. Do not split a change to fill a roster. Default concurrency is 4. Lower it in the plan when the work is tightly coupled.

## Plan tasks

```json
"tasks": [
  {"id": "fix-parser", "purpose": "fix tokenising of quoted fields", "files": ["src/parser.py", "tests/test_parser.py"],
   "requirement_ids": ["REQ-QUOTED"], "acceptance": ["tests/test_parser.py passes"],
   "verification": "python3 -m unittest tests.test_parser", "expected_output": "a commit on the task branch"},
  {"id": "callers", "purpose": "list every caller of parse_row and how it handles errors", "kind": "read"}
]
```

- `files` is the task's ownership, as globs. Changes outside it make the core reject the result.
- `kind: read` tasks may not write. They run in parallel with anything else.
- `target` (`{"providerInstanceId", "model"}` from the live catalog) pins a provider. A pinned target that is unavailable blocks the task instead of being swapped. Without `target`, the implementer role chain picks one (default: your own provider and model).
- `depends_on` orders tasks. Integration follows the same order.

The core writes each child's brief from these fields, the run's constraints and the requirement wording. The child cannot see this conversation, so put everything it needs into the task fields.

## Isolation

T3 children inherit the parent's checkout and have no worktree parameter. Before the first writing task, `next` runs a probe for each writer provider. It creates a sibling worktree under the state root, asks a child to write a nonce file there, and then reads the file itself.

- **Probe passed** (the child can write outside your checkout): writers run in parallel, each in its own worktree and branch `t3p/<run-id>/<task-id>`.
- **Probe failed:** writers run one at a time in a single shared worktree (`t3p/<run-id>/shared`). Read-only tasks still run in parallel.

The result is stored per provider in the run's `probes` and shown in the report.

## Results

Each child ends its final message with one fenced block tagged `json t3-result`. The core extracts it from the observation, stores it as an artifact and validates it. Claimed files and commits must exist in the task worktree, and the child may not touch constraints, authorisation or completion. Malformed output gets exactly one correction round, a new `delegate_task` call with a new `clientRequestId`. If the correction is also malformed, the task blocks with the raw output kept.

## Integration and repair

When the writers are accepted, `next` offers `integrate` actions (`git merge --no-ff` into your checkout) in dependency order. A failed merge blocks the run and keeps every worktree and branch. The report lists each one with its cleanup command. A review repair creates a `repair-N` task: in parallel mode it gets a new worktree from the integrated HEAD; in serial mode it reuses the shared worktree.

## Waiting

After a dispatch, end your turn unless other actions are ready. T3 wakes this thread when a child finishes. Do not poll in a loop or start watcher processes.
