# Free supplemental reviews

T3 coordinators can add up to three free OpenCode model points of view alongside
the required reviewer. This is opportunistic by default when delegation and sharing
with OpenCode are already authorised. Say **"no supplemental reviews"** to opt out
for a run. Asking for extras does not authorise sharing private material with a new
provider; without that authority, the coordinator skips them.

This applies to imps reviews and audits, babysitter PR review, Ralph evaluation,
agent-tuneup verification and elephant-goldfish factual checks. It excludes
document-only cold reads and cheap doctor, status and list operations. The primary
reviewer starts first and keeps its required independence and acceptance gates.

## How targets are chosen

The coordinator reads fresh `orchestrator_capabilities` and verifies the exact
advertised model IDs against current official pricing. It selects at most three
distinct model names across all runnable OpenCode instances, including the Console
`opencode/*` and Go `opencode-go/*` namespaces. There is no bundled model roster.
The same named model through both namespaces counts once.

[Console pricing](https://opencode.ai/v2/docs/console/models/) and
[Go pricing](https://opencode.ai/v2/docs/console/go/) distinguish free offers from
paid access. Go is a subscription; included usage alone does not prove a model is
free. A name ending in `-free` is also insufficient. The coordinator must observe
zero cost for every applicable charge, including caching and requests. Uncertain,
missing or stale pricing means skip. Catalog and pricing observations last five
minutes. The helper trusts these coordinator observations; it does not fetch or
independently verify a price.

OpenCode must advertise Full Access support and the parent must already have that
mode. The review brief still permits inspection only. A narrower parent, disabled
provider, missing cross-provider capability or unavailable host lifecycle tool
means skip. No permission changes or paid fallback are attempted.

## What happens when extras fail

Extras run asynchronously while primary work continues. Overload, unavailable
models, errors, malformed output and stale results are recorded skips. The
coordinator never waits or polls for them, retries ordinary failures, or charges
them to the required workflow's repair budget. A separate private ledger retains
each request ID, task handle, revision/base and cleanup observations across resume.

When the primary round ends, the coordinator closes optional result intake and
requests cancellation of unfinished extras. It records actual status without
waiting. Any unconfirmed cancellation or lost dispatch receipt stays visible in
the report and ledger for later reconciliation. A cancellation request alone is
not proof that work stopped. Existing pending-run gates still apply unchanged.

Returned findings are leads. The coordinator verifies concrete claims against the
current source, records dispositions and sends confirmed real issues through the
normal repair path. An optional review never supplies approval, replaces the
mandatory evaluator or establishes independence for an unknown model lineage.
Repairs still need the workflow's required checks and review.

## Installed helper and evidence limits

Every package includes `shared/supplemental_reviews.py` and the
[coordinator protocol](https://github.com/seankoji-com/t3-plugins/blob/master/shared/supplemental-reviews.md).
The helper only selects, prepares and records. T3 owns dispatch, status and
cancellation. The protocol documents private JSON inputs, the one-ledger-per-round
rule, idempotent recovery of lost replies and cleanup. No provider SDK, model CLI
or scheduler is added.

Offline tests cover selection, error handling, resume, cleanup and a relocated
installed package. They do not prove live provider compatibility, current model
availability, model quality or successful live cancellation.
