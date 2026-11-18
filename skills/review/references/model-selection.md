# Choose the reviewer

Read before selecting any reviewer or judge, including rechecks, additional
opinions and reviews inside implement.

For [Hillclimb scoring](../../hillclimb/references/judges.md), use its confirmed
roster and scoped DeepSeek exception. Apply this reference to Hillclimb's formal
delivery review as usual.

1. Preserve explicit reviewer/settings choices within the route restrictions
   below, and preserve narrower fallback limits.
   If an explicitly named reviewer is lineage-ineligible, report the conflict
   and first eligible alternative; hold dependent review until the user accepts
   it or names another eligible reviewer. Standing defaults are not named overrides.
   Default unspecified effort to high. With no named reviewer, select Sol high;
   if Sol's lineage authored the reviewed code, start with Opus high. Only code
   authors constrain lineage; ignore a model that merely orchestrates. Plans,
   prose and visual judgments have no lineage exclusion.
2. Before dispatch, apply the subscription check in
   [T3 preflight](../../agent-tuneup/references/t3-dispatch.md). On confirmed
   exhaustion or insufficient headroom under that check, use these preferred
   chains in order:

   | Starting reviewer | Quota fallback order |
   | --- | --- |
   | Sol high | Opus high, then Sonnet high via AGY |
   | Opus high | Sonnet high via AGY, then Sol high |

   AGY means the Antigravity provider route, not native Claude or OpenCode.
   Opus and Sonnet share the Anthropic lineage; routing Sonnet through AGY does
   not change it. Skip lineage-ineligible and quota-constrained routes.
   Try each candidate at most once per selection; never cycle back to Sol or Opus.
3. For the primary reviewer only, when lineage exclusions, alone or combined with
   quota constraints, leave the preferred chain unable to supply an independent reviewer,
   use the first eligible available alternative in order:
   Grok 4.7, then Hydrogen high. Quota constraints alone
   do not unlock this list. Once unlocked, skip constrained or ineligible
   alternatives while preserving the order. Every unlisted model, including Argon
   and Muse/Wonder Full, requires the user's explicit selection.
   DeepSeek Flash V4.1 is removed from direct reviewer dispatch; it is allowed
   only as OCR's backend under [parallel review](parallel-review.md).
   A named DeepSeek request still uses OCR, not direct host-model dispatch.
   The required Hydrogen visual companion has standing authority independently
   of this primary-fallback gate; it adds a second visual review rather than
   replacing the primary's.
4. Record the quota evidence and every lineage exclusion. Other failures do not
   establish exhausted credits or insufficient headroom. If no authorised eligible route
   remains, report the gate and hold dependent review for the user's choice.
   Cost optimisation, automatic upgrades, additional judges and requests for
   another opinion do not expand these fallbacks or raise the default effort.
5. For every selection, named, default or fallback, verify the outgoing model and effort
   options through the host. Give the reviewer its expected identity/settings in
   the brief. Compare available execution metadata and the reviewer's self-report
   before accepting the report. Conflicts block acceptance; missing evidence stays
   unverified. A user-directed reassignment supersedes the earlier choice; record
   that authority and the revised settings instead of treating it as substitution.
   Use high for Grok when supported; if the host confirms it has no effort control,
   report effort as not applicable. Verify high through the host option or model
   variant for the other listed models; do not infer it from an inherited default.

Plan and visual judges need no higher-effort exception to share a lineage.
Additional opinions cannot replace the primary code-author independence check.
Raising effort above these defaults still needs the user's explicit choice.

For a second opinion requiring an unused lineage, apply that exclusion to these
same chains. The lineage-only alternatives remain conditional on that conflict.

## Selection examples

| Code-author lineage and available credits | Primary reviewer |
| --- | --- |
| Neither Sol nor Anthropic; Sol exhausted | Opus high |
| Sol authored; Opus exhausted | Sonnet high via AGY |
| Sol authored; Opus and Sonnet exhausted | Grok 4.7, because Sol conflicts |
| Anthropic authored; Sol exhausted | Grok 4.7, because Opus and Sonnet conflict |
| Both Sol and Anthropic authored | Grok 4.7 |
| Lineage alternatives unlocked; Grok exhausted | Hydrogen high |
| No lineage exclusions; all preferred routes exhausted | Hold for the user |
| Explicitly named Sol; Sol authored | Offer an eligible alternative and hold |
| Sol orchestrates; Opus/Fable wrote the code | Sol high, no waiver |
| Sol wrote only a plan or prose | Sol high, no lineage restriction |
