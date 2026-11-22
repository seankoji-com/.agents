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
   Default unspecified effort to high. With no named reviewer, apply the gates in
   rule 2, then take the highest-scored eligible provider either way. Only code
   authors constrain lineage; ignore a model that merely orchestrates. Plans,
   prose and visual judgments have no lineage exclusion.
2. Before dispatch, apply [T3 preflight](../../agent-tuneup/references/t3-dispatch.md)
   and call its limits snapshot with `detail: "brief"`. After the lineage,
   permission, tool-support and authorised-model gates, take the provider with the
   highest `providers[].paceScore`. `null` is unknown, never zero, and an unscored
   provider cannot win. Match the model inside that provider to the role's
   difficulty. When no candidate is scored, or the tool is absent or erroring,
   keep this static order and record capacity as unknown: Sol high, Opus high,
   Sonnet high via AGY, Grok 4.7 high, Neon high, Hydrogen high.
   AGY means the Antigravity provider route, not native Claude or OpenCode.
   Opus and Sonnet share the Anthropic lineage; routing Sonnet through AGY does
   not change it. Skip lineage-ineligible and gated routes.
   Try each candidate at most once per selection; never cycle.
3. Score-driven choice may hand a review to a weaker family than a fixed chain
   would; that trade-off is accepted, and lineage, the difficulty match and high
   effort are the remaining protections. Grok 4.7, Neon and Hydrogen are ordinary
   candidates once lineage allows them, so a score alone may make any of them
   primary. Every unlisted model, including Argon and Muse/Wonder Full, requires
   the user's explicit selection.
   DeepSeek Flash V4.1 is removed from direct reviewer dispatch. OCR follows
   the [OCR skill](../../ocr/SKILL.md): a public repository draws free OpenCode
   reviewers, and the paid `ocr` CLI uses DeepSeek Flash V4.1 unless DeepSeek
   wrote the code, in which case it uses Qwen 3.8 Flash and the control that
   sends high reasoning effort. `--effort high` is OCR review depth and is
   recorded separately.
   A named DeepSeek request still uses OCR, not direct host-model dispatch,
   except in `choose-design` design scoring, which follows its
   [named fallback](../../choose-design/references/scoring.md).
   Hydrogen's separate role as the required visual companion keeps standing
   authority; it adds a second visual review rather than replacing the primary's.
4. Record each chosen score with its basis, the gates applied and every lineage
   exclusion. Other failures do not
   establish exhausted credits or insufficient headroom. If no authorised eligible route
   remains, report the gate and hold dependent review for the user's choice.
   Cost optimisation, automatic upgrades, additional judges and requests for
   another opinion do not expand these eligibility rules or raise the default effort.
5. For every selection, named, default or fallback, verify the outgoing model and effort
   options through the host. Give the reviewer its expected identity/settings in
   the brief. Compare available execution metadata and the reviewer's self-report
   before accepting the report. Conflicts block acceptance; missing evidence stays
   unverified. A user-directed reassignment supersedes the earlier choice; record
   that authority and the revised settings instead of treating it as substitution.
   Use high effort for every listed model. Set it through the host's control where
   one exists. Where a route exposes none, as Gemini can, select its high-named
   variant. With neither a control nor such a variant, keep the provider default
   and record effort as not applicable. Verify high through the host option or
   model variant for the other listed models; do not infer it from an inherited
   default.

Plan and visual judges need no higher-effort exception to share a lineage.
Additional opinions cannot replace the primary code-author independence check.
Raising effort above these defaults still needs the user's explicit choice.

For a second opinion requiring an unused lineage, apply that exclusion to the same
gates and score selection.

## Selection examples

| Situation | Primary reviewer |
| --- | --- |
| Best-scored provider did not author the code | its difficulty-matched model at high effort |
| Best-scored provider authored the code | the next best-scored eligible provider |
| Sonnet via AGY outscores Sol; no lineage conflict | Sonnet high via AGY |
| Grok 4.7 outscores Sol and Opus; no lineage conflict | Grok 4.7 high |
| No candidate is scored | Sol high, then the static order |
| Explicitly named Sol; Sol authored | Offer an eligible alternative and hold |
| Sol orchestrates; Opus/Fable wrote the code | Sol eligible, no waiver |
| Sol wrote only a plan or prose | Sol eligible, no lineage restriction |
