---
name: review-evidence
description: Use during engineering reviews to capture visible behavior, report evidence-backed findings and assign SEV1–SEV3 severity. Applies to direct reviews and dispatched reviewers.
---

# Review evidence and severity

Use for code, UI, backend and release reviews. Review the requested scope against
its requirements. This skill standardises evidence and findings; it does not
require delegation or grant authority to repair, file issues or release.

## Reviewer and parent responsibilities

A dispatched reviewer inspects behavior, describes bugs and assigns severity.
Return findings and evidence to the parent. Do not fix code, decide deferrals,
file GitHub issues or change labels as part of the review assignment. A later
explicit repair assignment is separate work.

The parent validates findings and decides whether to fix, defer, reject or raise
issues within its existing authorization. For a direct review, the reviewing
agent reports findings to the user and performs only separately authorized work.

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

## Return a usable report

Include scope, revision, checks, reviewed flows and coverage gaps, even when no
bugs are found. For each finding provide:

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
