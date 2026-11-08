# Review reuse after a rebase

Use this when a reviewed branch is rebased onto an advanced base. Preserve the
reviewer's identity, covered revision, findings and original comparison base.

Before rebasing, establish a merge base with the refreshed intended base. Check
`git rev-parse --is-shallow-repository` and `git merge-base <head> <base>`.
When shallow history prevents a reliable comparison, deepen the relevant refs
with a bounded fetch or unshallow within authority, then recheck. Stop if no
merge base can be established. Do not loop indefinitely or rebase unrelated
histories. A full, sufficient checkout needs no additional deepening fetch.

Record the branch's changed paths before rebasing. If conflicts unexpectedly
extend beyond them, abort the task-owned rebase and diagnose before retrying.
Upstream renames or deletions can legitimately explain those paths; absence from
the old diff is a warning, not proof of corrupt history. Preserve other work
and the repository's permitted update method and push restrictions.

After a clean rebase, compare diffs from each revision's own merge base:

```sh
git diff --binary --no-ext-diff --no-textconv <reviewed-merge-base> <reviewed-head> | git patch-id --verbatim
git diff --binary --no-ext-diff --no-textconv <current-merge-base> <current-head> | git patch-id --verbatim
```

Retain both commands/results with the review attribution. Require actual output
and successful diff generation, not equality of two empty or failed results.
`--verbatim` preserves whitespace that `--stable` ignores. Inspect binary blobs,
file modes, renames and other relevant metadata separately when the comparison
does not fully represent them. Patch IDs are supporting evidence, not proof of
semantic equivalence or a substitute for considering the new base.

Reuse requires unchanged reviewed behavior, no conflict resolution and no
relevant change to dependencies, interfaces, schemas, tests or assumptions in
the new base. Changed patches or any such uncertainty require fresh review.
Rerun covering checks against the new base even with equal IDs. Explain the
reuse and its scope. Reviewer lineage, human approvals, required CI and
auto-merge holds still apply.
