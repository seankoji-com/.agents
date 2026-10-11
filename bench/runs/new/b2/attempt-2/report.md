The bug is fixed and committed on `main` in three local commits (nothing pushed, no PR). The full test suite passes (574 tests) and the independent review approved the final revision. The imps run (`20261011-103752-d4b830`) validates as **completed**.

**Cause:** cleanup decided a worktree was still "ours" by comparing inode numbers. ext4 hands freed inode numbers straight back, so a worktree deleted and recreated at the same path looked identical, and cleanup offered `git worktree remove` for it. This reproduced in 20 of 20 trials on the original code.

**Fix:**
- **`ca7775d`:** when the run records a worktree, it writes a random owner token into the worktree's git admin directory. Removing the worktree deletes that directory, so a recreated worktree has no token and is reported as replaced.
- **`27ac032`:** the identity also records when the worktree's `.git` file was last changed. Rebuilding a checkout and running `git worktree repair` keeps the old admin directory and token, but always produces a new `.git` file, so this is now caught. A corrupt token no longer crashes cleanup or the report.
- **`d85ab02`:** a new `unproven` state for a worktree that might still be the run's but can't be proven to be. That covers records made before this fix and worktrees whose `.git` file was rewritten, for example by `git worktree repair --relative-paths`. Cleanup never removes these or their branch, and the report lists them under "Unproven resources" with the reason. `plugins/imps/entry.md` and `references/delegation.md` describe this.

**Behaviour change:** a run started before this fix and resumed afterwards will no longer remove its own worktree automatically. The report lists it for you to check instead. I chose to fail safe here.

**Verification at `d85ab02`:**
- **Suite and docs:** `python3 -m unittest discover -s tests -v` ran 574 tests, all OK. `scripts/check_docs.py` passes; `entry.md` is at 1,495 of its 1,500 words.
- **Regression tests:** 5 new tests in `tests/test_cleanup.py` cover remove and re-add, a rebuilt and repaired checkout, both kinds of older record, repair in place, and a corrupt token. The new tests fail against each earlier version of the code where expected and pass now.
- **Reproductions:** the scratch scripts show no wrong results after the fix, even with inode numbers reused in 18 of 20 trials.
- **Not run:** `mkdocs build --strict`. No file under `docs/` changed and there's no docs virtualenv; the reviewer did run it and it passed.

**Review** (Codex `gpt-6.1-sol`, an independent model family): rounds 1 and 2 were adverse with one major finding each, both fixed above. Round 3 approved. I set a three-round limit and deferred its two remaining items:
- **Minor:** if a finished run's worktree is replaced by one on the same branch, cleanup keeps retrying `git branch -d`, which Git refuses. Nothing gets deleted. The retry loop already existed on the base code.
- **Note:** a replaced worktree can appear in the report with a literal `` `None` `` command. This also already existed on the base code.

**Other things you should know:**
- The imps gate refused my first evidence as stale even though no tracked file had changed. The command sandbox creates and removes empty placeholder files in the repo between commands, which shifts the gate's snapshot. Later rounds took the snapshot and ran every check in one command, and those were accepted.
- The imps learning store is outside the directories you allowed me to write to, so I didn't save this as a lesson. Proposed lesson: under this sandbox, take the snapshot, run the checks and submit them without other tools in between.
- The untracked dotfiles in the repo root were left untouched. No background processes or child tasks are still running.

Files are in `.bench-state/runs/20261011-103752-d4b830/`:
- report.md
- scratch/
