# Prepare a reviewer to inspect the right work

Use this before dispatching a reviewer. Include these constraints in its brief,
alongside scope, acceptance criteria and verified model identities.

## Freeze the source

Name the repository, absolute checkout path, reviewed SHA and comparison base.
For committed scope, read immutable objects with `git show <sha>:<path>` and
`git diff <base>..<sha>`; report the revision covered and any observed HEAD
movement. A decision review names its fixed brief instead.

Freeze edits and commits in a shared reviewed checkout until the report arrives,
or use supported worktree isolation. For explicitly authorised dirty scope, name
the paths and freeze that state or supply a fixed snapshot. Do not substitute
whatever happens to be in the working tree for the requested revision.

A host checkpoint attributed to a read-only child does not establish authorship.
Compare it with concurrent coordinator activity and the child's actual write
operations before alleging a violation.

## Define permitted checks and scratch writes

Read-only forbids repairs and changes to reviewed source, branches, remotes,
GitHub state or live systems. It permits scoped tests, probes and evidence writes
only within the authority and locations specified in the brief. If tests need
to alter the source checkout, use an authorised disposable copy or report the
check unavailable. Full-access runtime mode does not broaden this task scope.

Give the exact verified interpreter/environment, test commands, collection roots
and relevant prerequisites when checks are expected. Require results for checks
run and reasons for checks omitted. Do not instruct the reviewer to discover an
environment the coordinator already knows.

Name a task-owned evidence/scratch directory verified with `git check-ignore`
inside the session worktree, or a host-approved registered scratch root. State
that the child may create and remove its own files there. Put browser profiles,
probe output and custom test temporary roots there too; generic `$TMPDIR` is not
automatically approved. Self-cleaning temporary directories inside test helpers
remain subject to the host's permissions and the task's ownership rules.

Specify what evidence must survive for the parent, with stable IDs and accessible
paths. Clean disposable files and report what remains and why. Do not delete the
only evidence needed for handoff or issue tracking. Report a refused deletion;
do not wrap it or switch tools to evade the refusal. An ignored path alone does
not prove deletion is permitted. If no approved path exists, avoid ad hoc output
locations and mark affected checks or captures unavailable.
