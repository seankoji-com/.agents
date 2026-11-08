# Check what the evidence actually proves

Use these checks when adopting an existing test bundle, making an HTTP access
claim or diagnosing why a local proof tool cannot run. They do not add a new
attestation system, require deployment testing or grant another run or escalation.

## Adopt a test bundle from the invocation that produced it

Before treating a copied or existing bundle as current evidence, compare its run
identity, capture times and source binding with the invocation and launch source.
Check existing digest bindings too. A directory's existence, recent filesystem
timestamp or successful copy proves none of these. Missing or mismatched bindings
leave adoption unverified; do not invent provenance to fill a gap.

If launch preflight fails before a fresh run identity exists, retain older output
only as explicitly stale diagnostics. A fresh, correctly bound failing run is
valid failure evidence. Its nonzero exit neither invalidates all diagnostics nor
establishes success. Preserve unrelated evidence and existing budgets.

## Validate HTTP access claims

Record the requested and effective URL, status, content type and redirects for
the client and authentication state actually tested. Redact tokens and sensitive
query values. Ignore ambient client configuration when practical and make redirect
handling explicit. With curl, `-q` must be its first option; without `-L`, a 3xx
response remains at the original URL. Record its Location safely when relevant.
`--max-redirs 0` alone does not enable redirect following or describe its chain.

Validate the expected response body or schema before claiming application/API
access. A login page returning 200, or a redirect to an identity provider, does
not prove API access or unauthenticated exposure. Record the redirect or unexpected
HTML as a negative or unknown result for that claim. A deliberately redirecting
route can pass its own redirect contract, but that does not prove access to its
destination. Tests already asserting these properties need no duplicate probe.

## Separate tool presence from permission and health

Check presence independently, for example `command -v <tool>`, then retain the
error from a bounded use/health check. Discarded output from a failed use command
does not establish absence. Classify the result as absent, present but
sandbox-denied, present but unhealthy, or unknown, with the supporting evidence.
Do not infer a sandbox denial from an ambiguous socket or permission error.

For an evidenced sandbox restriction, try at most one supported escalation only
when that route exists and the task authorises it. An unavailable or rejected
route stays a gate. Never bypass a guard or switch launchers to defeat a denial.
Carry the classification and retry result into any handoff deferring proof to
hosted CI. Presence does not prove that the daemon is healthy or usable.
