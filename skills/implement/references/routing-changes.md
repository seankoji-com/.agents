# Preserve work when routing changes

Read before replacing a running implementation delegate, applying an automatic
upgrade or returning moved-base conflicts to the owning lead.

## Owner-directed change

1. Record the owner's actual instruction, affected roles and revised choices.
   Reconcile active delegates and descendants. Prepare a checkpoint handoff with
   task handles, checkout, branch, HEAD, dirty paths, authors, findings, checks,
   ledger and remaining work. Preserve incomplete work and never claim an
   unavailable checkpoint was captured.
2. Stop affected delegates through the host before transferring writer ownership.
   Confirm cancellation; cancelling a lead also stops its descendants. Keep the
   owning checkout. Redispatch only through a supported route that can preserve
   and verify it. If the host cannot do that, report the blocker rather than
   starting a replacement from the parent's older base.
3. Verify exact outgoing model/effort and the preserved state before resuming.
   Record a new model/effort segment in plan-report. Owner-directed reassignment
   does not consume the one automatic upgrade and resets no review budget,
   score, finding or review count. Re-evaluate code-review lineage against
   every actual author, including repairs.

## One automatic upgrade

Allow one model or effort upgrade for the whole task, shared by the lead and
coding workers. Reviewer changes require review's selection rules. It requires
evidence of capability failure or diagnosed lack of progress, with a reason the
stronger choice should help. An expected failing regression test alone is not
an escalation reason. Start high-risk work at a suitable level.

Record consumption before dispatch. Preserve state and stop replaced tasks as
above. A stronger worker may start from the lead's committed checkpoint while
the lead remains coordinator. Do not pretend the running lead's model changed.
If the upgrade is still stuck, or safe escalation is unsupported, return the
blocker and preserved work; never label budget exhaustion as success.

## Moved-base conflicts

Send merge/rebase conflicts to the same owning lead through the supported resume
route. Name the exact new base SHA and permitted integration method. The lead
verifies its checkout, resolves the conflicts, reruns affected checks and
reconciles review coverage. A coordinator whose guard excludes that checkout
does not edit around the boundary or create a replacement checkout.
