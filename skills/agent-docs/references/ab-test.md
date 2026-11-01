# A/B procedure for agent-doc findings

A finding holds only when the edited doc steers fresh sessions as well as the
original. Arguing about whether a line is a no-op settles nothing; running the
doc does.

1. **Plan.** For each finding, write two prompts that exercise the changed line
   and the expected behavior for each before running anything. For a
   description change, make one prompt a near miss that should not trigger the
   skill. State the run count (findings x 2 prompts x 2 variants x 2 models)
   and confirm it falls within granted spending authority.
2. **Variants.** Keep the original and the edit in separate checkouts, such as
   a worktree on a scratch branch, so each session loads only one variant.
   Batch related findings into one edited variant when they touch the same doc.
3. **Run.** Start a fresh session per prompt and variant, with no prior
   conversation, on one Claude model and one model from another family. Take
   exact model ids from the host. If a family is unavailable, record the gap;
   do not substitute a model from the same family.
4. **Judge.** Compare each run with its written expectation: did it take the
   intended path, reach the completion condition and trigger only when it
   should? The edit holds when it matches or beats the original on both
   families. Otherwise drop or revise the finding and rerun once.
5. **Record.** Per finding, keep the prompts, model ids, variant and outcome.
   Remove scratch checkouts when finished.
