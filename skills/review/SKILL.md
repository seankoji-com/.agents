---
name: review
description: Use for independent cross-lineage reviews of plans, code, UI, backend and releases, including review-loop participants and grilling's stop-condition check.
---

# Cross-lineage review

Review the requested scope against its requirements. Independent model review
must be cross-lineage. This skill also owns review evidence and severity; it
grants no authority to repair, file issues or release.

## Obtain an independent review

The coordinator obtains the review. An assigned reviewer follows the reviewer
role below and does not dispatch another reviewer.

1. Identify the scope, exact revision or decision brief, acceptance criteria,
   coordinating model and every model that materially authored the reviewed work.
   Distinguish human authors from unknown model identities.
2. Discover supported host tasks and exact model identities. A named reviewer
   must have a verified lineage differing from both the coordinating model and
   every material model author. Preserve eligible named models and options.
   If a named reviewer is ineligible or unavailable, report the conflict,
   recommend the first eligible alternative and hold dependent review until
   the user accepts it or names an eligible reviewer. Do not substitute.
   Only inside [implement](../implement/SKILL.md), when no reviewer is named,
   use its cost-aware model-selection policy for every round and additional
   opinion, preserving all cross-lineage eligibility requirements. Otherwise
   select the first available reviewer in this order whose verified lineage
   differs from both the coordinating model and every material model author:
   **Sol, Opus, Wonder Full, Argon, Grok 4.7**. Another version, effort setting
   or provider alias of the same family does not qualify. An explicitly named
   same-lineage reviewer is ineligible. Record the exact identities and the basis
   for their lineages.
3. Reuse a completed eligible review only when it covers the current behavior or
   decisions. Otherwise obtain a fresh read-only review through authorized host
   orchestration. Give the reviewer the request, scope, source/version, raw
   evidence, criteria and coordinator/author identities. Include this skill's
   path and explicitly instruct the reviewer to read and apply it in the
   assigned-reviewer role. In T3 Code, discover models with
   `orchestrator_capabilities`, use a new `delegate_task` for every review or
   recheck that the coordinator dispatches, record its `taskId` and follow its
   returned `next`. Use native
   orchestration elsewhere. Respect the calling workflow's delegation limits;
   an existing review may qualify without new dispatch only when its reviewer's
   identity and lineage are verified as differing from the coordinator and every
   material author, including the repairing agent, and it covers the current
   head or decision brief. Assigned reviewers must receive this skill; external
   reviews must provide evidence meeting its identity, scope and reporting rules.
   Otherwise report the specific review gate.
4. Keep the calling workflow's review budget across repairs and resumes. A
   standalone review allows at most three rounds, including failed attempts.
   Recheck material changes or unresolved findings; do not seek unanimity or
   restart budgets by changing reviewer. Receive the complete report before
   treating the review as completed. A timeout, missing reply or task status
   alone is not a review.

If identities cannot be verified, no cross-lineage reviewer is available, or
required dispatch is prohibited, report the specific review gate and hold work
that depends on it. Finish independent preparation. Self-review and same-family
agents cannot satisfy the gate. Required human approval remains a separate gate.

## Reviewer and parent responsibilities

Every assigned reviewer reads this skill, checks the supplied coordinator and
author identities against its own lineage, and reports a missing or conflicting
identity instead of claiming cross-lineage review. Perform the assigned review
directly; do not dispatch agents, including another reviewer of this review.

Implementation participants apply the parent's selected dispositions and these
evidence rules. They do not claim independent review or dispatch reviewers.

A reviewer inspects the work, describes consequential findings and assigns severity.
Return findings and evidence to the parent. Do not fix code, decide deferrals,
file GitHub issues or change labels as part of the review assignment. A later
explicit repair assignment is separate work.

The parent validates findings and decides whether to fix, defer, reject or raise
issues within its existing authorization. Validating findings and repairing code
does not make the parent an independent reviewer. For a direct user request,
the coordinator obtains the independent review and reports it to the user.

## Capture what was evaluated

Bind evidence to the reviewed revision, relevant dirty changes and environment.
Identify the application build or deployment when it differs from the source.
Record the flow, state, viewport or device and conditions needed to interpret it.

When reviewing visible behavior:

- Use the host's supported browser or device tools. Capture and inspect
  screenshots of each reviewed flow's key states, including passing states.
  Include relevant loading, empty, error or responsive states when in scope.
- Capture every visible finding. Explain the expected behavior, what the image
  shows and why it matters. A screenshot alone does not prove a functional cause.
- When verifying a fix, retain the original capture and take a fresh capture of
  the same affected state on the fixed revision. Do not reuse an old image as proof.
- Give captures stable evidence IDs. Store them in the host-approved artifact
  location, using a verified ignored directory when repository-local storage is
  required. Avoid secrets and personal data in captures and reports.

Backend and code findings use appropriate evidence, such as a minimal input,
test output, logs or a file/line explanation. Do not take screenshots of code or
terminals merely to satisfy the visual requirement. Plan-only reviews need no
screenshots of behavior that does not yet exist.

If a required state cannot be captured, finish independent checks and identify
the missing state, reason and remaining verification. Mark visual review
incomplete and carry that gap into the release recommendation. Do not substitute
a mockup for observed behavior or claim that passing checks cover the gap.

## Assign severity

Use the shared incident SEV scale for review findings, including pre-release bugs.

| Severity | Impact | Default release treatment |
| --- | --- | --- |
| SEV1 | Essential functionality unavailable or comparably severe impact, including serious security exposure or irreversible data loss | Blocks release; an exception requires the user's explicit approval |
| SEV2 | Degraded functionality with a workable alternative or workaround | Parent evaluates release requirements and the workaround |
| SEV3 | Minor defect with low or no user impact | Normally allows release |

Justify severity using impact, affected users, triggering conditions and existing
mitigations. Rare failures can still be severe. Separate confirmed observations
from hypotheses; uncertainty is an evidence gap, not a reason to lower impact.
Do not force stylistic preferences into bug findings or inflate severity because
a fix is easy. When a consequential defect has no workaround, assess whether
essential functionality is unavailable rather than automatically calling it minor.

Priority describes scheduling and remains separate from severity. Deferral or
issue creation does not lower severity. Report the proposed severity even if
the repository lacks a matching label. Canonical target names are
`severity:SEV1`, `severity:SEV2` and `severity:SEV3`; verify they exist before use.
The parent checks current labels and
maps equivalent meanings; do not equate SEV1 with priority:P1 or invent a label
mapping. Label creation and migration belong to separately authorized work.

## Track deferred bugs

For every confirmed bug intentionally left unfixed, the coordinator must obtain
a verified issue URL before declaring an execution workflow complete. Apply
[deferred-bug tracking](references/deferred-bugs.md) for deduplication, issue
contents and read-back verification. This includes non-blocking SEV3 bugs and
approved release exceptions. Issue creation does not lower severity or waive
a blocking finding. Reviewers report findings; the coordinator files within its
authority. If filing is blocked, preserve the draft and report tracking as
incomplete. Rejected findings and stylistic preferences require no issue.
Already non-blocking bugs may ship while filing is pending under that procedure;
the workflow stays open until required issue URLs are verified.

## Return a usable report

Include scope, revision, checks, reviewed flows and coverage gaps, even when no
bugs are found. Record coordinator, material author and reviewer model identities,
verified lineages and any unknowns. For each finding provide:

- Stable finding ID, SEV level and rationale.
- Location, expected versus observed behavior and user impact.
- Reproduction steps or supporting evidence, with uncertainty stated.
- Evidence IDs, screenshot captions and accessible artifact paths or links.

Dispatched reviewers return a complete plain-text report with artifact references
the parent can actually access. Follow host presentation rules; never leave the
only findings in a child-thread visualisation. The parent must show the user the
relevant screenshots with captions through supported image or presentation tools,
including key passing states. A directory path alone does not show the evidence.
If cross-thread access fails, report it and arrange an authorized handoff.

The parent retains finding IDs and original evidence, and appends dispositions,
reasons, issue URLs and verification results. Keep artifacts available for that
handoff; before task cleanup, preserve any evidence needed for deferred issues
in an authorized durable destination. Do not upload private captures merely
because an issue may eventually be filed.
