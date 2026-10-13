# Search broadly

Discovery runs directly in the coordinator because the plan's slot count depends on it.
Comparison and synthesis run as delegated stages. Job shape: `PKG/references/research-job.md`.

1. Inspect the current project and write a short fingerprint of its stack, relevant
   weaknesses, and techniques it already uses. Resolve the focus from the request.
2. Run `bash PKG/scripts/init-workspace.sh` from the project. Use the returned workspace
   and save the fingerprint to the returned `fingerprint` path.
3. Form several focused queries. Use `scripts/search-repos.sh` and
   `scripts/readme-peek.sh` to screen candidates, then `scripts/triage-repos.sh` to
   inspect maintainership, license, and fit. Stars alone are not evidence of fit.
4. Select at most five candidates. Explain why each can address a named local gap.
   Clone through `scripts/clone-candidates.sh <workspace> <url> <name> <sparse:0|1>`;
   repeat triples for multiple candidates. Never reinterpret rejected URLs as shell code.
   Record each clone's resolved commit, then write and hash its source snapshot.
5. Create the job: one independent `research-<n>` stage per clone with one
   `ape/source-researcher` slot, then one `synthesis` stage that depends on all of them,
   with one `ape/synthesizer` slot. The research stages are parallel readers; dispatch
   them together. Each applies the comparison and report rules in
   `PKG/playbooks/study.md` steps 4–6 to its own clone.
6. Accept each research stage on its own report descriptor. Then prepare the synthesis
   brief with the accepted report paths and hashes. The synthesizer compares overlap and
   conflicting recommendations and proposes the smallest useful experiment with the
   evidence against it. It builds on the accepted reports, not fresh source research;
   its descriptor pins every candidate snapshot and quotes the text those reports cited.
7. Accept synthesis, run `validate-final` over every stage, and save the reports in the
   workspace. Do not modify the target project or start any experiment.
