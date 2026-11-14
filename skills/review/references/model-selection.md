# Choose the reviewer

Read before selecting any reviewer or judge, including rechecks, additional
opinions and reviews inside implement.

1. Preserve explicit reviewer/settings choices and narrower fallback limits.
   If an explicitly named reviewer is lineage-ineligible, report the conflict
   and first eligible alternative; hold dependent review until the user accepts
   it or names another eligible reviewer. Standing defaults are not named overrides.
   Default unspecified effort to high. With no named reviewer, select Sol high;
   if Sol's lineage authored the work or matches the coordinator, start with Opus
   high. Apply review's lineage eligibility before every dispatch.
2. On confirmed credit exhaustion, use these preferred chains in order:

   | Starting reviewer | Credit fallback order |
   | --- | --- |
   | Sol high | Opus high, then Sonnet high via AGY |
   | Opus high | Sonnet high via AGY, then Sol high |

   AGY means the Antigravity provider route, not native Claude or OpenCode.
   Opus and Sonnet share the Anthropic lineage; routing Sonnet through AGY does
   not change it. Skip lineage-ineligible models and confirmed exhausted routes.
   Try each candidate at most once per selection; never cycle back to Sol or Opus.
3. Only when lineage exclusions, alone or combined with confirmed credit
   exhaustion, leave the preferred chain unable to supply an independent reviewer,
   use the first eligible available alternative in order:
   Grok 4.7, DeepSeek Flash V4.1 high, then Hydrogen high. Credit exhaustion alone
   does not unlock this list. Once unlocked, skip exhausted or ineligible
   alternatives while preserving the order. Every unlisted model, including Argon
   and Muse/Wonder Full, requires the user's explicit selection.
4. Record the evidence for credit exhaustion and every lineage exclusion. Other
   failures do not establish exhausted credits. If no authorised eligible route
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

The higher-reasoning exception does not make high effort strictly higher than
another high-effort implementor. Verify the supported ordering. If qualification
needs a higher effort or another model, obtain the user's explicit choice first.

For a second opinion requiring an unused lineage, apply that exclusion to these
same chains. The lineage-only alternatives remain conditional on that conflict.

## Selection examples

| Authors/coordinator lineage and available credits | Reviewer |
| --- | --- |
| Neither Sol nor Anthropic; Sol exhausted | Opus high |
| Sol authored; Opus exhausted | Sonnet high via AGY |
| Sol authored; Opus and Sonnet exhausted | Grok 4.7, because Sol conflicts |
| Anthropic authored; Sol exhausted | Grok 4.7, because Opus and Sonnet conflict |
| Both Sol and Anthropic authored | Grok 4.7 |
| Lineage alternatives unlocked; Grok exhausted | DeepSeek Flash V4.1 high |
| No lineage exclusions; all preferred routes exhausted | Hold for the user |
| Explicitly named Sol; Sol authored | Offer an eligible alternative and hold |
