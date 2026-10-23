# plan

Describe the problem you want to understand before implementing anything:

```text
$t3-plan simplify retries without hiding failures or repeating unsafe requests
```

There are no public subcommands. A bare `$t3-plan` uses the relevant conversation
context and asks only for a missing topic. You can ask to list or resume an existing
plan in ordinary language.

The workflow establishes the actual problem, current workaround, alternatives and
observable success conditions. It reads relevant repository evidence itself and
asks you about decisions that evidence cannot settle. There is no required interview
length. A quick assessment stays a quick assessment when that is what you request.

## What you get

Each formal plan lives in `plans/<slug>/`:

- `discovery.md` records the problem, constraints, decisions, evidence and unknowns.
- `spec.md` defines stable requirement IDs, acceptance criteria, verification and
  explicit exclusions.
- `handoff.md` contains the reviewed source documents for a fresh implementation
  thread, with `handoff.manifest.json` retaining content and review provenance.

You accept the exact discovery before the final specification and source-plan
review. A separate reviewer challenges the actual request coverage, assumptions,
feasibility, failure handling and verification. Repairs retain prior findings and
their dispositions. A changed discovery reopens your acceptance; an unchanged one
does not require another interview or approval.

The renderer copies the source text deterministically. The readiness gate checks
current discovery acceptance and the actual source-plan review receipt. Missing,
stale or adverse evidence prevents a ready handoff. Reported review mode and coverage
remain distinct from a claim that the implementation works.

## Where it stops

Planning ends at the handoff. It does not implement, open PRs or launch another
implementation workflow. Those need an explicit follow-on instruction. A resume,
scheduled reminder or answer to a planning question does not change that boundary.

Ask for a draft or stop at any point. Incomplete output stays marked non-executable
and names the unresolved decisions. Publication requires explicit authorization for
the content and destination.

## Replacing elephant-goldfish

`plan` replaces the useful planning workflow formerly reached through
`$t3-elephant-goldfish thinking`. It does not use the elephant/goldfish premise or
maintain a separate `elephant.md` document.

The old plugin is deprecated and excluded from default setup. Existing installed
packages, pinned jobs and `thinking/` topics remain intact. Continue old jobs with
their pinned package; start new work with `$t3-plan`. No automatic migration or
rewriting of old review receipts takes place.

## Verification

The package includes its own state, review and rendering helpers and bundled shared
contracts. Installed-artifact tests exercise the helpers after relocation. Local
tests prove deterministic state and acceptance behavior, not live model adherence.
See [planning review](../plan-review.md) and [architecture](../architecture.md).
