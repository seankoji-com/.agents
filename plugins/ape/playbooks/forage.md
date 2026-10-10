# Search broadly

1. Inspect the current project and write a short fingerprint of its stack, relevant
   weaknesses, and techniques it already uses. Resolve the focus from the request.
2. Run `bash PKG/scripts/init-workspace.sh` from the project. Use the returned workspace.
3. Form several focused queries. Use `scripts/search-repos.sh` and
   `scripts/readme-peek.sh` to screen candidates, then `scripts/triage-repos.sh` to
   inspect maintainership, license, and fit. Stars alone are not evidence of fit.
4. Select at most five candidates. Explain why each can address a named local gap.
   Clone through `scripts/clone-candidates.sh <workspace> <url> <name> <sparse:0|1>`;
   repeat triples for multiple candidates. Never reinterpret rejected URLs as shell code.
5. Apply the comparison and reporting rules in `PKG/playbooks/study.md` to each clone.
   Parallel T3 analysts are optional when the independent comparisons justify them.
   Give each the fingerprint, exact scope, source revision, and report path.
6. Synthesize overlap and conflicting recommendations. Recommend the smallest useful
   experiment, with evidence against it. Save reports; do not modify the target project.
