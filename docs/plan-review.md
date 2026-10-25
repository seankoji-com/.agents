# Planning review

Planning commands review their proposed output before dependent work. The coordinator
first collects your work model and review panel choices in short rounds, including exact
supported effort and any permitted replacements. Explicit choices in your request
count. Saved preferences and catalog order are recommendations. Deterministic
doctor, status, list and formatting helpers stay direct.

| Output | Review point |
| --- | --- |
| plan | After accepted discovery and spec, before handoff rendering |
| ape study or forage | Final synthesis, including no-adoption recommendations |
| imps audit, investigation, blast-radius | Integrated conclusions, including zero findings |
| imps run, issues, checklist, discussion | Before a plan with writes, multiple stages or synthesis executes |
| imps verification-init | Authored launch, drive and cleanup recipe before execution |
| agent-tuneup | Conclusions, concrete alignment proposals and substantive bootstrap proposals |
| focus-group | Exact study revision before owner approval and panel work; final report retains the separate stronger fidelity review |
| Ralph or babysitter | An actually written strategy before dependent actions |

Deprecated elephant-goldfish jobs retain their pinned historical document-review
policy. New planning work uses plan and does not maintain `elephant.md`.

Focus-group keeps per-model participant choices, a judgement analyst and a selected
independent fidelity reviewer. A new study revision reopens planning review and
owner approval. Its final fidelity gate already checks the integrated synthesis
against accepted inputs, omitted contradictions, citations, support and dissent;
the operation matrix therefore adds no duplicate planning pass over that report.
An explicit resume retains pinned targets/options or stops.

Routine Ralph loops and PR maintenance retain their existing review gates. An
unchanged reviewed apply plan needs no duplicate planning pass. Raw fetches and
single-file diagnostics produce no new synthesis. The installed
`shared/operation-matrix.json` maps every manifest operation to its trigger or
exception; it also distinguishes model choice from the need for a planning stage.

## What the review proves

The reviewer receives the verbatim request, decisions, requirements, domain rubric,
exact source documents and authorised repository evidence. It challenges feasibility,
assumptions, failure and recovery paths, and simpler alternatives. Every requirement
and load-bearing decision needs an outcome and evidence. Empty findings are valid.
The shared standard ships in every worker bundle as `shared/reviewer-standard.md`.

The coordinator repairs supported findings in source and records every fixed,
rejected or deferred finding. Open majors and blockers prevent readiness. Rejecting
one on unchanged content requires fresh agreement from its original reviewer lineage
or a scoped owner decision. Self-review cannot erase it.

Selected reviewers form a panel. Permitted replacements form a separate finite
chain: suitable cross-lineage children, fresh same-lineage children, then an explicit
main-context self-review if authorised. Technical unavailability can trigger that
chain; disagreement cannot. One combined self-review may cover only exhausted
required slots with explicit permission, preserving other slots' child passes.
The receipt lists covered slot IDs and each slot's actual mode as one degraded panel.
Factual, cold-read,
code and final-evaluation gates retain their stronger requirements.

## Evidence and resuming

Each parent consumes a validated receipt from a separate manifest-pinned planning
job. A metadata boolean, provenance check or owner discovery acceptance cannot supply
that receipt. It binds source bytes, requests, decisions, rubric, templates, relevant
repository evidence and the producing model-selection record. Relevant drift reopens
review. Unrelated HEAD movement remains visible without automatically repeating it.

Private XDG state retains one logical output's rounds, findings and active job across
repairs and replacement jobs. New subjects allow five substantive assessments;
existing subjects retain their recorded limit. Technical attempts have a separate
finite allowance. New model preferences never reset either history or budget.
Unchanged continuations, resumes and nested calls reuse the agreement. New scope
or authority needs a scoped decision. Historical complete
artifacts remain labelled `legacy-unreviewed`; changed plans need current review.

The final report identifies what content passed, actual modes/models and substitutions,
feedback applied, retained findings and evidence limits. For every cleared blocker
or major, include the clearing mode and lineage. A foreign-lineage major repaired
through permitted self-review remains labelled `fixed-by-self-review`.
Planning readiness grants no
implementation, settings, merge or publication authority. See
[testing](testing.md#planning-review-conformance-protocol) for the separate live evidence boundary.

## Check a draft before returning it

An active planning reviewer can run the installed `check-draft` helper when the
brief authorizes its procedural reads. It checks the saved draft against the exact
brief and permitted evidence, without opening live job/subject stores or charging
a round:

```sh
python3 PKG/shared/planning_review_cli.py check-draft --input draft-input.json
```

The input contains `brief_file`, the dispatch descriptor's `brief_sha256`, and
`result_file` under the assigned task artifact directory. Exit 0 means available
draft checks passed; exit 2 reports an invalid draft. A valid adverse review can
pass these checks. The diagnostic always says `acceptance: false` and lists checks
deferred to ingestion, including current state, host identity/options and budgets.
Artifact reads are capped at 16 MiB; final ingestion enforces its pinned limit.

Allow at most one correction before terminal completion. Keep all findings and
actual reads, including unexpected reads. Return an unresolved gap if a correction
needs new authority or evidence. Completed results stay immutable and counted;
the helper grants no retry, follow-up, waiver or readiness. Document-only/cold-read
slots cannot use this planning checker.
The correction bound is procedural. The reviewer checks the pinned helper hash;
the checker does not certify its own installation. The assigned brief and own
draft artifacts are contract/outputs; separately opened helper/source files still
need pre-review declaration and actual-read disclosure.

An unchanged-content re-review may acknowledge a previously agreed rebuttal through
a fresh child from its original lineage. This appends evidence while preserving
the original clearing provenance. Missing historical proof or changed content still
requires the applicable ordinary review path.
This applies to every severity, including minor and note findings. Receipts remain
bound to the producer's validator bytes: upgrading does not transfer an old
approval to a new validator. Keep historical jobs on their producing pins or
obtain the applicable fresh review; never patch an installed validator in place.

## Final reviews and deferred fixes

The planned last review, and always the last available round, keeps full required
coverage but blocks only on issues that must be fixed before handoff, merge or
launch. Unmet acceptance criteria, failed required checks and missing required
evidence still block. Optional cleanup, design changes and safe later hardening
become repository issues with impact, evidence, a safe-deferral reason, owner and
next action. Earlier major/blocker findings retain their original severity and
clearing requirements.

After every subtask review returns, the coordinator immediately gives you at most
three sentences about its findings, blockers, deferrals, coverage gaps and next
action. Full findings stay in the evidence record. The handoff lists deferred
fixes with issue links or explicit unfiled status and captures a lesson about which
build/test or task-structure change would have caught the observed problems sooner.
