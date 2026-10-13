"""Stable error codes from the persisted interface contract, and a reader for them.

An error carries its code as a `code` attribute (core CoreError, RegistryError) or as
the leading `code: ` prefix of its message (JobError, ResultError, AcceptanceError).
CLIs print the message unchanged, so the code is visible on stderr either way.
"""
from __future__ import annotations

STABLE_CODES = frozenset({
    'plan_invalid', 'undeclared_expansion', 'uncertain_dispatch', 'result_transport_unavailable',
    'required_review_unavailable', 'owner_decision_required', 'stale_evidence', 'pin_mismatch',
    'capacity_deferred', 'attempt_budget_exhausted', 'schema_invalid', 'ownership_mismatch',
    'artifact_invalid', 'artifact_oversize', 'dispatch_unavailable', 'cancel_unconfirmed',
    'dependency_stale',
})


def code_of(error: BaseException) -> str | None:
    """The stable contract code an error carries, or None when it carries none."""
    code = getattr(error, 'code', None)
    if code in STABLE_CODES:
        return code
    head = str(error).split(':', 1)[0].strip()
    return head if head in STABLE_CODES else None
