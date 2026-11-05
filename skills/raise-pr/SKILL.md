---
name: raise-pr
description: Use whenever creating or updating a pull request, including during implementation, review-loop, ship and PR maintenance.
---

# Raise a pull request

Apply these requirements to new PRs and updates to existing PRs. Follow the
repository's delivery policy; a repository that requires direct publication
does not get a PR. This skill adds no authority to commit, push, upload private
artifacts, create PRs, merge or deploy.

Apply [GitHub writing](../github-writing/SKILL.md) to descriptions and comments,
including drafts and later edits.

## Prepare the description

Inspect the actual repository, intended base, current head and scoped diff.
Find applicable PR templates and contribution instructions, including templates
under `.github`, `docs` or the repository root and any organization defaults.
Use the repository-designated template. If several apply and the choice is
unclear, ask which one to use. If template discovery is unavailable, disclose
that limitation rather than claim there is no template.

Keep the template's headings, prompts and required sections. Put the change
summary, verification, screenshots and agent attribution in the matching sections;
append missing sections when needed. Mark checklist items only when verified.
Without a template, use a concise summary, verification, visual evidence and
agent attribution. For an existing PR, retain relevant human text and evidence,
updating stale claims rather than replacing the whole description blindly.

## Include visual evidence

For changes affecting visible UI behavior, capture and inspect the affected
flows at one mobile and one desktop size using supported browser or device tools.
Record actual viewport dimensions or device, state, source revision and the
tested build when it differs. Select the sizes appropriate to the application's
supported layouts. For a platform that cannot run at one size, explain why.

Include after screenshots of the changed behavior at both sizes. Attempt matching
before screenshots when practical, using the intended base or a verified baseline
build. Keep state, viewport and test data comparable. Capture before editing
when the task allows; otherwise use a safe isolated baseline without disturbing
dirty work. Label the revision actually captured. New UI with no previous state
can explain why a before image is not applicable.

Use captions identifying before/after, flow and size. Embed screenshots with
PR-accessible image URLs through an authorized supported artifact mechanism and
check that the images render for the intended reviewers. Local filesystem paths
do not make images visible in a GitHub PR. If the installed CLI supports it,
`gh pr create --attach` and `gh pr edit --attach` upload images and rewrite body
references to the uploaded assets; check local help before relying on that flag.
If API tools lack uploads, use an authorized CLI attachment path or disclose
upload unavailability. Never move non-public captures to public third-party
hosting as a workaround. Do not commit images to source solely to host PR
evidence. Keep secrets and personal data out of captures and uploads.

When capture, upload or access is unavailable, a normal PR is allowed. Include
the available screenshots, explicitly list each missing size/state or inaccessible
image, explain why it is missing, and state the remaining verification. Explain
missing before screenshots too. Never substitute mockups or old screenshots for
observed results, or call incomplete visual evidence complete. Other repository
release gates still apply.

For changes with no visible UI effect, explicitly state that screenshots are
not applicable and explain why. Include useful checks or other evidence;
screenshots of code or terminals are not a substitute for UI evidence.

## Require independent review and disclose agents

Before creating a PR, obtain a completed independent code review covering the
proposed diff. Reuse an existing review only when it covers the current behavior.
Apply [review](../review/SKILL.md) for cross-lineage eligibility, reviewer
selection, dispatch, evidence and findings. Self-review and a separate same-family
agent do not qualify. Give the reviewer the diff, relevant context and acceptance
criteria and require it to read and apply review in the assigned-reviewer role. Bound a
standalone review/repair cycle to three rounds; report unresolved gates when
exhausted. Honour explicit model choices. If an
eligible reviewer is unavailable or delegation is prohibited, finish independent
preparation and report the blocker; do not create the PR, including a draft.
An explicit user waiver, in the original request or later, can override this
skill's creation or renewed-review requirement for the stated scope. Disclose
the missing review, waiver and remaining risk in the PR. A draft request alone
is not a review waiver. Waivers do not bypass repository protections.

Address actionable findings within authorization and obtain review of material
code changes made afterward. For existing PRs, material changes may be pushed
for hosted checks, previews and independent review. Disclose pending review and
require it before merge. Existing eligible agent reviewers can review after the
push; this does not require the repairing agent to dispatch a reviewer. If no
eligible reviewer is available, report the merge gate and who must supply review.
Treat changes to tests, CI workflows and configuration as material when they
affect verification or runtime semantics, even if product code is unchanged.
Description-only corrections and changes demonstrated to preserve the reviewed
semantics may reuse the review; explain reuse and rerun affected checks.
A human review may satisfy repository approval rules; it does not replace this
skill's required cross-lineage model review. Agent review cannot replace a
required human approval, and no review replaces required CI.

Before pushing material changes with review pending, check existing auto-merge
and merge-queue enrollment. Within authorization, hold automatic merging before
the push so stale approvals cannot merge unreviewed repairs. If the hold cannot
be verified or is outside authority, stop before pushing and report that blocker.
Restore automatic merging only after current-diff review and other merge gates
pass, or after an applicable explicit review waiver and all remaining gates.

Disclose every agent that materially wrote or reviewed the change, including
the coordinating agent when it contributed code. For each, record its role,
provider/model when known, contribution or review scope, and review outcome
with remaining findings or limitations. Identify human contributions as human.
State unknown identities explicitly rather than guessing. Record the reviewed
revision or a precise identification of the reviewed dirty diff. A failed task,
timeout or empty response is not a completed review.

## Create or update and verify

Within existing authorization, use the host's GitHub API tools or authenticated
CLI. Never use an interactive browser form for PR creation. Preserve the intended
base, branch and draft status. Verify the returned PR URL and read back its
description, template sections, evidence and attribution. Read the PR's
`closingIssuesReferences` and confirm they match the issues it is meant to
close; fix unintended references in the body and read them again. After a
transport error, check whether the PR already exists before retrying. Partial attachment failure
can create or update the PR despite a nonzero CLI exit; read back the returned
URL and disclose missing images rather than creating a duplicate PR. Follow host
PR linking rules.

On later updates, refresh affected screenshots, review coverage, agent attribution
and checks to match the current change. Label retained historical evidence with
its revision. Do not silently carry old evidence forward as current proof.
Report the PR URL, head, checks, independent review and any visual evidence gaps.
PR creation does not prove hosted CI, merge, deployment or live acceptance.
