# babysitter
Read `PKG/shared/learnings.md` and load this plugin's project lessons before work.

Keep pull requests moving through review and CI. Read `PKG/shared/t3-runtime.md`,
then `PKG/playbooks/maintain.md`. Delegation follows `PKG/shared/delegation.md`.

- `pr <URL>`: one pull request.
- `repo <owner/name>`: eligible open PRs in one repository.
- `org <owner>`: eligible open PRs across an organization.
- `doctor`: inspect Git, Bash, `gh`, `jq`, GitHub authentication, and T3 watch capability.

Invoking `pr`, `repo`, or `org` authorizes babysitting through merge within that
scope: arming auto-merge on every targeted PR, merging PRs that are ready now, and
fixing, pushing to, and replying on the targeted PR branches until they merge. A
request that says "inspect", "review only", or "do not merge" authorizes inspection
alone. Never bypass protected branch requirements.
