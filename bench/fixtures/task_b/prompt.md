Fix this bug in the repository: cleanup can remove a worktree that was deleted and
recreated at the same path.

Add a regression test for it, make sure the repository's test suite passes, and commit
the fix on the current branch.
