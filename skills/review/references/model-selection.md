# Choose the reviewer

Read before selecting any reviewer or judge, including rechecks, additional
opinions and reviews inside implement.

For [Hillclimb scoring](../../hillclimb/references/judges.md), use its confirmed
roster. Apply this reference to Hillclimb's formal delivery review as usual.

1. Preserve explicit reviewer/settings choices within the route restrictions
   below, and preserve narrower fallback limits.
   If an explicitly named reviewer is lineage-ineligible, report the conflict
   and first eligible alternative; hold dependent review until the user accepts
   it or names another eligible reviewer. Standing defaults are not named overrides.
   Default unspecified effort to high. With no named reviewer, apply the gates in
   rule 2, then take the highest-scored eligible provider. Exclude material
   author families for formal code and readiness review. Count orchestrators
   when they authored the candidate. Other plans, prose and visual judgments
   follow the caller's eligibility rules.
2. Before dispatch, apply [T3 preflight](../../agent-tuneup/references/t3-dispatch.md)
   and call its limits snapshot with `detail: "brief"`. After the lineage,
   permission, tool-support and authorised-model gates, take the provider with the
   highest `providers[].paceScore`. `null` is unknown, never zero, and an unscored
   provider cannot win. Match the model inside that provider to the role's
   difficulty. When no candidate is scored, or the tool is absent or erroring,
   keep this static order and record capacity as unknown: Sol high, Opus high,
   Sonnet high via AGY, Grok 4.7 high, Neon high, Hydrogen high, DeepSeek Flash V4.1 high.
   AGY means the Antigravity provider route, not native Claude or OpenCode.
   Opus and Sonnet share the Anthropic lineage; routing Sonnet through AGY does
   not change it. Skip lineage-ineligible and gated routes.
   Try each candidate at most once per selection; never cycle.
3. Score-driven choice may hand a review to a weaker family than a fixed chain
   would; that trade-off is accepted, and lineage, the difficulty match and high
   effort are the remaining protections. Grok 4.7, Neon, Hydrogen and DeepSeek
   Flash V4.1 are ordinary candidates, including for primary review. Every
   unlisted model, including Argon and Muse/Wonder Full, requires the user's
   explicit selection.
   Dispatch DeepSeek Flash V4.1 directly through the host. For T3's OpenCode
   LiteLLM route, verify `litellm/deepseek-v4.1-flash` with `variant: high` and
   apply the T3 permissions rule. Apply DeepSeek family eligibility even when
   the model runs through a different provider.
   `vote` ballot seats are not reviewers or judges: they follow the fixed roster
   and fallback in its T3 workflow, and this reference does not apply to them.
   When a vote seat is unavailable, that workflow makes the single DeepSeek
   substitution; read the [vote skill](../../vote/SKILL.md) for how to start it.
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

Additional opinions cannot replace a required independent primary.
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
| DeepSeek Flash V4.1 is the eligible named reviewer; the host confirms OpenCode LiteLLM high | Dispatch that model directly |
| DeepSeek materially authored the code; DeepSeek Flash V4.1 is named | Report the family conflict and offer an eligible alternative |
| No candidate is scored | Sol high, then the static order |
| Explicitly named Sol; Sol authored | Offer an eligible alternative and hold |
| Sol orchestrates; Opus/Fable wrote the code | Sol eligible, no waiver |
| Opus wrote the brief for readiness review; Anthropic has the best quota pace | Exclude Anthropic, including Sonnet, before quota ranking |
| Sol wrote prose outside a readiness review | Sol eligible under ordinary selection |
