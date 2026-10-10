# babysitter

Keep pull requests moving through review and CI. Read `PKG/shared/t3-runtime.md`,
then `PKG/playbooks/maintain.md`.

- `pr <URL>`: one pull request.
- `repo <owner/name>`: eligible open PRs in one repository.
- `org <owner>`: eligible open PRs across an organization.
- `doctor`: inspect Git, Bash, `gh`, `jq`, GitHub authentication, and T3 watch capability.

Resolve authorization before edits, messages, pushes, or merges. "Review" alone
authorizes inspection; "babysit through merge" includes fixing and landing eligible
PRs within the stated scope. Never bypass protected branch requirements.
