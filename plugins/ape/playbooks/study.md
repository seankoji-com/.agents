# Study one source

1. Run `bash PKG/scripts/study-repo.sh <URL>` with the operator's GitHub URL as one
   quoted argument. It validates the URL, resolves the ref and subdirectory, prepares
   the clone, and prints its revision and report path. Stop on nonzero exit.
2. Inspect the current project's relevant code and dirty changes. Write a fingerprint
   of at most 150 words: stack, architecture, gaps, and practices already in use.
3. Read the source README, directory tree, and only the code needed to substantiate
   transferable ideas. Pin claims to blob URLs at the resolved commit with line numbers.
4. Write a report of at most 900 words with Overlap, Adopt, Adapt, Reject, and Command
   case sections. Each proposal names local target files, effort, tradeoff, strongest
   counterargument, simpler alternative, and a bounded experiment with baseline,
   success criterion, and abandon condition. Empty Adopt/Adapt sections are valid.
5. Deliver the report and its path with the source revision. Experiments are proposals
   until run; do not claim measured improvements from source inspection.
