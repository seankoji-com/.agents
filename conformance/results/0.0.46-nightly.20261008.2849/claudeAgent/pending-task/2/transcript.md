# Transcript excerpt: claude parent, case pending-task, repeat 2

Thread `mcp:5e3e1a7e-feeb-48e6-9add-29baf9ad676c` (claudeAgent / claude-sonnet-5-5). Assistant messages verbatim, abridged.

Turn 1
> I've dispatched the `survey` task and ended my turn. [...] request `…:survey:r1` [...] I released my claim.

Driver: `t3_thread_interrupt` returned `no_active_run`; the resume message was sent while r1 was still running.

Turn 2 (resume)
> Run `20261009-135644-b2c5b2` is resumed but not finished. The `survey` child task is still running, so I released my claim and am waiting. **Resume:** I claimed the run, recorded the capabilities, and read the child's state with `task_status`. It reports `running` / `working`, with no result yet. [...] The core's next action is still `query_task` for `survey`, and nothing else is ready.

Turn 3 (woken by the child)
> Run `20261009-135644-b2c5b2` is **blocked**, not completed. The `survey` child finished, but the core rejected its result. **Blocker:** `result_rejected`: "result claims evidence that does not exist: `pending-task-2/wordstat.py`". The child reported its evidence path relative to the wrong directory [...] I didn't edit the child's result or accept it by hand.

Grader note: reconciliation was correct (one initial dispatch; task_status on resume; no duplicate). The repeat fails because the child cited evidence relative to its own working directory (the thread's scratch folder, which children inherit) instead of the clone. Root cause: the brief did not require absolute evidence paths; fixed after the matrix.
