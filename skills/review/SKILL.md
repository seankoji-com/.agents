---
name: review
description: "Review plans, code, UI, backend or releases independently. Use when asked for a review, or for review-loop rounds and think's readiness check. Pressure-testing an idea belongs to challenge."
---

# Review against the goal

Check the requested work against its requirements. Return findings with evidence
and severity. Read [project settings](../ship/references/project-settings.md)
before choosing reviewers.

Code and readiness reviewers must differ in model family from each material
author of the code or brief. Other plan, prose and visual reviews follow the
caller's eligibility rules. The caller owns repairs,
filing and release authority.

## Obtain an independent review

The coordinator obtains review; assigned reviewers never delegate.
Apply [T3 dispatch preflight](../agent-tuneup/references/t3-dispatch.md) before T3 dispatch.

1. **Set the review scope.** Record the exact revision or decision brief,
   acceptance criteria and material authors, including repairers.
   Distinguish human authors from unknown model identities.
2. **Choose the reviewers.**

   - Identify available host tasks and exact models. Record each code and
     readiness reviewer's lineage. Lineage follows model family across
     versions, effort settings and provider aliases.
   - Apply [model selection](references/model-selection.md) to each review,
     recheck and additional opinion, including inside implement. Honour named
     choices and the applicable credit, lineage and permission rules.
   - The primary covers the whole change, including visuals. Before starting a
     review or recheck, read the [companion rules](references/parallel-review.md)
     and run the companions they require on the same frozen revision.
     Other judges may share a lineage and cannot replace the primary.
3. **Reuse or dispatch.** Reuse completed reviews from assigned direct
   reviewers when they cover the current head or brief and satisfy its
   eligibility rules. If the primary qualifies, obtain any missing companion
   reports before relying on it. If no primary qualifies, dispatch a fresh
   read-only review within the caller's limits.

   - Supply the request, scope, revision, evidence, criteria and model
     identities. Follow the [reviewer brief](references/reviewer-brief.md) for
     frozen source, allowed checks, scratch ownership and cleanup. Require
     reading the [assigned-reviewer card](references/assigned-reviewer.md) at its absolute path before the review starts.
   - In T3 Code, discover models with `orchestrator_capabilities` and use a new
     `delegate_task` for each review or recheck you dispatch. Record its
     `taskId` and follow `next`. Use native orchestration elsewhere.
   - Apply these identity, scope and reporting rules to external reviews.
     Report any qualifying evidence still missing.
4. **Stop when review is complete or the caller's limit is reached.**

   - Read the [single-round procedure](references/single-round.md) before
     repairing under an adopted `review_rounds: 1`. Otherwise follow the caller's
     stop rule. Standalone review allows three rounds, including failures.
     `review-loop` owns iteration, attempt limits and scored-run recovery.
     Hillclimb supplies its scoring roster.
   - Recheck material changes or unresolved findings. Use the
     [budget diagnosis](references/budget-exhaustion.md) when review stalls or
     runs out of attempts. Preserve budgets across reviewers. Do not seek unanimity.
   - Require the complete report. A timeout, missing reply or task status alone
     is not a review.

If required code-author identities cannot be verified, no eligible reviewer is available, or
required dispatch is prohibited, report the specific review gate and hold work
that depends on it. Finish independent preparation. Self-review cannot satisfy
the code gate. Matching the orchestrator alone never creates a gate or needs a waiver.
Required human approval remains a separate gate.

## Reviewer and parent responsibilities

Give each delegate its self-contained role card as its only review instructions.

- When dispatched, the [assigned reviewer](references/assigned-reviewer.md) checks code-author
  lineage and reports missing or conflicting identities. It reviews directly
  and returns evidence and severity. It cannot delegate, repair, decide
  deferrals, file issues or change labels.
- When repairing, the
  [implementation participant](references/implementation-participant.md)
  applies the parent's dispositions without dispatching reviewers or claiming
  independent review.

A later explicit repair assignment is separate work.
For separately authorised GitHub reviews, apply [GitHub writing](../github-writing/SKILL.md).

The parent validates findings, then decides what to fix, defer, reject or file
within its authority. Apply [feedback dispositions](references/feedback-dispositions.md)
when deciding each finding.
Validating or repairing does not count as independent review. For a direct user
request, the coordinator obtains the review and reports it to the user.

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

For backend/code findings use reproductions, tests, logs or file/line evidence,
not terminal screenshots. Apply [proof quality](references/proof-quality.md)
when adopting bundles, claiming HTTP access or diagnosing unavailable tools.
Plan-only reviews need no screenshots.

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
bugs are found. Before handing back,
[cite verification evidence](references/proof-quality.md#cite-verification-in-the-handoff).
Record material code-author and reviewer model identities,
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
