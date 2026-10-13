# Study one source

The coordinator prepares the pinned inputs directly, delegates the comparison as one
stage, then inspects and accepts it. Job shape: `PKG/references/research-job.md`.

1. Run `bash PKG/scripts/study-repo.sh <URL>` with the operator's GitHub URL as one
   quoted argument. It validates the URL, resolves the ref and subdirectory, prepares
   the clone, and prints its revision and report path. Stop on nonzero exit.
2. Inspect the current project's relevant code and dirty changes. Write a fingerprint
   of at most 150 words: stack, architecture, gaps, and practices already in use.
   Save it to the returned `fingerprint_path`; reuse it only when reported fresh
   and still accurate for the project.
3. Pin the source snapshot with `PKG/scripts/snapshot_source.py`. Create the job with one `research` stage pinning
   that snapshot, one `ape/source-researcher` primary slot and its single declared
   follow-up. Pin the URL, resolved revision, clone path, snapshot, fingerprint path,
   focus and report path in the task contract. This stage is also the final stage.
4. Prepare, dispatch and record the handle as `PKG/shared/job-coordination.md` describes.
   The worker reads the README, directory tree and only the code needed to substantiate
   transferable ideas, and writes the report to its artifact subtree.
5. The report has at most 900 words with Provenance (source revision and snapshot
   SHA-256), Overlap, Adopt, Adapt, Reject, and Command case sections. Each proposal
   names local target files, effort, tradeoff, strongest counterargument, simpler
   alternative, and a bounded experiment with baseline, success criterion, and abandon
   condition. Empty Adopt/Adapt sections are valid. Claims cite blob URLs at the
   resolved commit with line numbers.
6. Ingest the result. Read the report, open the cited lines for every Adopt and Adapt
   proposal, and record an inspection receipt for each. Use the follow-up slot for a
   same-scope gap; otherwise repair with `retry`. Freeze the report descriptor with
   `observation` and run `accept-stage`.
7. Run `validate-final`, copy the accepted report to the returned report path, and
   deliver it with the source revision. Experiments are proposals until the owner asks
   for one; do not claim measured improvements from source inspection.
