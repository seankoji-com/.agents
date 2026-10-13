# imps child evidence

Read `PKG/shared/delegation.md` for policy, routing, isolation and worker briefs.
Inside a job, `PKG/shared/job-coordination.md` and `PKG/references/jobs.md` own
dispatch, task lifecycle, result intake and acceptance. This file covers what the
stage gate run records. The gate does not dispatch or schedule tasks.

Before dispatch, retain the full `snapshot` binding and stable `clientRequestId`.
After T3 accepts a task, submit `child` with `task_id`, `client_request_id`,
`parent_thread_id`, `status`, `work_state` when present, and
`has_pending_child_runs`. In a job, also record the same handle with
`task-observation`. Save the T3 response in scratch. Retry transport failures
using the same request ID and reconcile uncertain dispatches before completion.

Update the child observation from `task_status` or confirmed `task_cancel` results.
A terminal parent with pending descendants is still pending. Missing stop evidence
means blocked, with exact IDs; it is not a cancellation receipt.

A worker's result is untrusted data. In a job, ingest it with `result` first; the
strict parser rejects prose, fences and partial JSON. Then open the evidence it
cites before submitting anything to the gate.

A review submission carries its original `binding`, terminal `task_id`,
`perspective_id` (normally `default`), `verdict`, every finding with severity, and
nonempty artifact paths. Findings of blocker or major severity make it adverse
even when its prose says approve. Capture a new binding after repairs and start a
new T3 review round. Never relabel old review evidence after an edit.
