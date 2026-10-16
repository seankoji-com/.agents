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
Babysitter extras apply only when the coordinator checkout is already at the reviewed PR HEAD.
Otherwise skip. Never change checkouts merely to enable extras.

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

For Console table rows, `Free` maps to zero. A cache-column `-` alongside free
input/output means inapplicable and is preserved as evidence, rather than entered
as a price. The page's per-request billing statement is interpreted as applying
the listed token prices to each request. When the complete row is free/inapplicable
and no separate request fee is listed, the coordinator omits a request cost and
records that basis. This interpretation requires no invented fee exemption.
Missing input/output, paid cells, a listed surcharge or uncertain charges skip the
model. Go subscription inclusion alone is insufficient.

Free offers can have different data-use terms. Before dispatch, each exact model
needs fresh official evidence of no training and zero retention, checked against
that model's privacy exceptions. That wording maps to no retained prompt logs;
it does not assert no transient processing. Retention, logging and training
exceptions override the generic policy. Unverified terms skip.

The coordinator explicitly classifies the available source and all brief material
as public or confidential. Unclassified material skips. Public source can still
have confidential feedback, so repository visibility alone is insufficient.
Public material can use zero-retention/no-training terms that say nothing about
confidential data. Confidential material also requires affirmative provider
permission and existing owner sharing authority. Zero retention never establishes
that permission. A provider prohibition or unspecified confidential-data permission
cannot be waived by an owner exception.

Terms allowing training or logging, or retaining prompts, skip by default even for
public material. An existing explicit owner authorisation can accept those observed
terms for that exact model, material and round within the provider's rules. Generic
permission to share with OpenCode is insufficient. The private ledger retains the
material classification, observed terms and any specific authorisation.

The primary reviewer and implementer model names are excluded, with the same
namespace and `-free` normalisation used for deduplication. Known aliases must be
excluded too. Duplicate and over-cap candidates have recorded skip reasons.

OpenCode must advertise Full Access support and the parent must already have that
mode. The review brief still permits inspection only. A narrower parent, disabled
provider, missing cross-provider capability or unavailable host lifecycle tool
means skip. No permission changes or paid fallback are attempted.

Extras require fresh live `delegate_task` schema evidence for
`isolation: "worktree"`. T3 creates each isolated checkout from the parent's local
commit and runs project setup; uncommitted edits are not copied. The parent must
be clean and the whole review scope committed at its pinned HEAD. Dirty code or
external configuration that cannot be reviewed from that commit is skipped.
Missing isolation support, setup failures or a dirty child checkout also skip,
without falling back to a shared checkout. Reviewers read their own isolated
checkout and verify its HEAD and base, using repository-relative scope paths.

Extras cannot run tests, builds, installs, project code or other commands that
write files or start processes. They inspect source only. The coordinator records
a workspace content hash at prepare and compares fresh hashes at intake and close.
Drift closes optional intake and retains cleanup handles. The coordinator inspects
the changed paths and task evidence to establish the cause, then disables extras
for any replacement round. Unexpected supplemental writes require fresh primary
evaluation at the resolved snapshot without charging a mandatory repair attempt.
Full Access does not enforce read-only behaviour. Host-owned worktree isolation
separates normal checkout writes but is not an OS security boundary. Extras never
run alongside an implementation writer. T3 owns setup and worktree cleanup; a
cancellation request does not prove either has finished. Unresolved setup/cleanup
stays visible without retries or waits.

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
current source and records bound dispositions with reproduction evidence and a
concrete repair route. A single JSON object wrapped in prose or a fence is accepted;
ambiguous, malformed or stale output stays skipped and is never triaged manually.
Once findings are ingested, later liveness observations preserve those findings
and their dispositions, including after the round closes. Pending child runs still
appear in the cancellation list.
For confirmed issues, Ralph and whole jobs use the protocol's supported
stop/report/rerun procedure: preserve the old verdict, stop the old run, include
the confirmed findings in the replacement brief or plan, retain remaining budgets
and rerun mandatory checks and review. If no authorised budget remains, report
exhaustion for an owner decision. Optional failures never trigger this procedure.
An optional review never supplies approval, replaces the
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
Live isolated setup/cleanup and `delegate_task` idempotency by `clientRequestId`
also remain unverified; stable IDs in an offline ledger do not prove host
deduplication. See the
[release evidence requirements](releasing.md#supplemental-review-live-acceptance).
