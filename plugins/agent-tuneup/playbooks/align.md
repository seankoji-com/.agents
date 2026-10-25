# agent-tuneup align playbook

Follow `PKG/references/central-wiring.md` to inventory, compare and align native
provider layers.

1. Inspect the live catalog in the central runtime database. Read only
   `providers` and `instances` rows; do not write to live databases.
2. Read configured native settings for each discovered provider instance.
3. Compare declared shared assets against native provider configuration:
   instructions, skills, permissions, MCP servers, and runtime features.
4. For each asset, classify the native state:
   - `configured`: native layer implements the declared asset.
   - `unknown`: native layer references an unrecognized asset.
   - `unsupported`: provider lacks the capability to configure the asset natively.
   - `intentional-difference`: explicit divergence recorded in wiring policy.
5. In the alignment proposal, represent cells with these exact states:
   `configured`, `unknown`, `unsupported`, and `intentional-difference`.
   Do not use capability-summary states such as `disabled` or
   `not_in_supplied_sources` for wiring cells. Do not install a provider to fill
   a disabled row or disclose transcript scan input or output. The default
   tuneup includes a private local scan where supported.
6. Use wiring v2 for detailed native definitions and portable roles, following
   `PKG/references/central-wiring.md`. Supply only documented native surfaces for
   the recorded runtime version, explicit paths and receipt/caller evidence. Keep
   the private normalization proposal outside checkouts; this settings-only apply
   workflow cannot execute it. T3 remains the sole delegation owner.

```json
{
  "wiring_version": 2
}
```
