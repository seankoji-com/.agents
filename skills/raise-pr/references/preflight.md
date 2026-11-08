# Check delivery gates before creating a PR

Read this at delivery start, or before creating a PR when there was no earlier
preflight. Refresh it when the intended base, diff or repository policy changes.

## Read effective rules and their producers

Read effective base-branch rules, including inherited rulesets, through the
supported API. On GitHub, `GET /repos/{owner}/{repo}/rules/branches/{branch}`
complements classic branch protection. A classic-protection 404 is not proof of
an unprotected branch. Include applicable classic requirements and repository
settings rather than treating either source as complete on its own.

Record required status contexts and their app identities, review requirements,
linear history, code-scanning requirements and allowed merge methods. Merge-method
availability also comes from repository settings. Carry the permitted method into
delivery. If reads fail, report unknown requirements rather than an empty list.

For required checks, identify an actual producer and whether it can report for
this PR's events and base. Producers can be workflows, GitHub Apps or external
services. Inspect the revisions GitHub uses for each event; a new workflow in the
PR may not bootstrap a default-branch `pull_request_target` or `workflow_run`
producer. For code scanning, check the required tool's base analysis and applicable
configuration. Absent evidence is a gate, not proof the requirement is satisfied.

When a producer cannot report, raise the concrete owner decision early. Recommend
an appropriate bootstrap or configuration repair; explicit owner-approved bypass
or exclusion is a separate option only where supported. Do not change rules,
create synthetic success statuses or bypass protections under this preflight.

## Check validation skipped by a stacked base

For a non-default base, inspect relevant validation workflows against the scoped
diff. List workflows whose path selection applies but whose branch selection
excludes that base. Report these in the PR's verification section as outstanding
validation gates even when GitHub lists no required context for them. Filters or
workflow chains you cannot evaluate remain unknown, not inapplicable.

Clear such a gate with a successful equivalent run on the same source tree, or
an explicit operator waiver recorded in the PR. Compare relevant base/merge tree,
event, workflow version, configuration, permissions and secrets availability; tree
equality alone does not make different execution conditions equivalent. A
`workflow_dispatch` run or another PR can supply evidence only after that comparison.
This adds no authority to trigger privileged workflows or alter their filters.

## Make carried dependencies visible

When the PR carries unmerged commits from another open PR, prefer a supported CI
route that preserves the intended stack base. If it must target another base,
show the dependency in the title, for example `[after #123]`, keep draft status,
and explain in the body and handoff that merging first also lands the dependency's
commits, under this PR's title when squash-merging.

Use an existing do-not-merge label or blocking mechanism only when verified and
authorised. Do not create labels, checks or rules. State when no such mechanism
or authority exists. After the prerequisite merges, reconcile the actual remaining
diff and review before removing the dependency hold and stale title/metadata.

If the dependent PR merges first, record the landed commits and merge commit,
the prerequisite PR's resulting state and leftover commits, and the review
coverage that still applies. Notify its owner through an already-authorised
coordination route, or report the notification needed. Do not close or rewrite
the prerequisite PR without its owner's authority.

## Scan credential-shaped examples before pushing

When adding credential-shaped fixtures or documentation examples, run the
repository-configured scanner at its pinned version and configuration across
the full outgoing PR commit range before pushing, including later pushes that
add such strings. A clean final tree does not clear a finding in an earlier
commit. Prefer obviously synthetic values compatible with the test's purpose;
do not remove the behavior a security test is meant to exercise merely to pass
the scanner. Allowlisting needs a recorded, scoped justification.

Repair unpushed commits within existing authority. Pushed-history rewrites still
need the applicable authority. If the repository has no configured scanner or
the pin cannot be used within scope, report scanning as unverified. Do not
silently substitute an unpinned tool. Diffs without credential-shaped additions
add no scan requirement under this rule.
