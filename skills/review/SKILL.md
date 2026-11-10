---
name: review
description: Use for independent cross-lineage reviews of plans, code, UI, backend and releases, including review-loop participants and think's stop-condition check.
---

# Cross-lineage review

Review the requested scope against its requirements. Independent model review
uses cross-lineage reviewers, with the additional-judge exception below.
This skill also owns review evidence and severity; it
grants no authority to repair, file issues or release.

## Obtain an independent review

The coordinator obtains review; assigned reviewers never delegate.
Apply [T3 dispatch preflight](../agent-tuneup/references/t3-dispatch.md) before T3 dispatch.

1. Identify the scope, exact revision or decision brief, acceptance criteria,
   coordinating model and every model that materially authored the reviewed work.
   Distinguish human authors from unknown model identities.
2. Discover supported host tasks and exact model identities. Reviewers must have
   a verified lineage differing from the coordinator and every material model
   author, except for additional judges below. Versions, effort settings and
   provider aliases do not change lineage. Record identities and lineage evidence.
   Preserve eligible named models/options. For unavailable or ineligible choices,
   report the conflict and first eligible alternative; hold dependent review
   until the user accepts it or names another eligible reviewer.
   With no named reviewer, use implement's cost-aware selection when running
   inside implement; otherwise choose the first eligible available
   reviewer in this order: **Sol, Opus, Wonder Full, Argon, Grok 4.7**.
   **Additional-judge exception:** In review-loop and design-loop, an additional
   judge may share the lineage of the coordinator, implementor or another judge
   when its verified reasoning level is strictly higher than every material
   implementor's. Record exact model/effort settings and supported ordering;
   unknown or incomparable levels require cross-lineage judges. This includes
   named additional judges, selection, reuse and identity checks. It never replaces
   primary cross-lineage review or required independent code review.
3. Reuse completed reviews only when eligible against all current authors,
   including repairers, and covering the current head or decision brief.
   Otherwise obtain a fresh read-only review through authorized host orchestration.
   Supply the request, scope, source/version, evidence, criteria and model identities.
   Apply the [reviewer brief](references/reviewer-brief.md) for fixed source,
   permitted checks, scratch ownership and cleanup. Give the reviewer the
   absolute path of the [assigned-reviewer card](references/assigned-reviewer.md)
   and require reading it; a reviewer does not need this skill.
   In T3 Code, discover models with
   `orchestrator_capabilities`, use a new `delegate_task` for every review or
   recheck that the coordinator dispatches, record its `taskId` and follow its
   returned `next`. Use native orchestration elsewhere. Respect caller delegation
   limits. External reviews must meet these identity, scope and reporting rules;
   otherwise report the specific review gate.
4. Follow the caller's stopping rule across repairs and resumes. Review-loop
   and design-loop use score targets and two-round stagnation without a required
   cap; their evaluations do not inherit the standalone limit. A
   standalone review allows at most three rounds, including failed attempts.
   On stalling or exhaustion, apply the [budget diagnosis](references/budget-exhaustion.md).
   Recheck material changes or unresolved findings; do not seek unanimity or
   restart budgets by changing reviewer. Receive the complete report before
   treating the review as completed. A timeout, missing reply or task status
   alone is not a review.

If identities cannot be verified, no eligible reviewer is available, or
required dispatch is prohibited, report the specific review gate and hold work
that depends on it. Finish independent preparation. Self-review cannot satisfy
the gate. Same-family agents qualify only under the additional-judge exception.
Required human approval remains a separate gate.

## Reviewer and parent responsibilities

Children read a role card, not this skill. Each card restates these rules for
one role and links to nothing else:

- An assigned reviewer follows the [assigned-reviewer card](references/assigned-reviewer.md).
  It checks the supplied identities against its own lineage, reports a missing
  or conflicting identity instead of claiming eligible review, reviews directly
  and never dispatches agents. It returns findings with severity and evidence;
  it does not fix code, decide deferrals, file issues or change labels.
- An implementation participant follows the
  [implementation-participant card](references/implementation-participant.md).
  It applies the parent's selected dispositions and never claims independent
  review or dispatches reviewers.

A later explicit repair assignment is separate work.
For separately authorised GitHub reviews, apply [GitHub writing](../github-writing/SKILL.md).

The parent validates findings and decides whether to fix, defer, reject or raise
issues within its existing authorization, under [feedback dispositions](references/feedback-dispositions.md). Validating findings and repairing code
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
