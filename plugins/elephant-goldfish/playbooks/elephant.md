# A design document that survives a fresh reader

Delegated factual checks and cold reads follow `PKG/references/document-jobs.md`.
Load it before you create a job.

## check

Inspect `elephant.md` against the repository without editing it. Verify every path
citation and important build/test claim. Spot-check additions the document omits.
Report "document says / code does" with file and line evidence. This is a factual pass
only: never start a cold read from `check`.

For a short document, run the pass yourself. When the claims are many enough to
justify a child, create a one-stage `factual` job with an
`elephant-goldfish/factual-checker` slot, inspect its evidence, and accept the stage
with `validate_document.py --mode factual`.

## elephant

1. Draft or revise `elephant.md` with Problem, Technical plan, Alternatives, and
   Detailed implementation sections. Cite the owning paths. Preserve human rationale;
   mark superseded decisions explicitly. Record checked revision and dirty-tree status.
   Then record its hash-bound author lineage with `scripts/record_document_author.py
   <path-to-elephant.md> --capabilities FILE`, using a fresh
   `orchestrator_capabilities` response. Repeat this after each edit.
   You write the document; workers never edit it.
2. Create the job with a `factual` stage and then a `cold-read` stage, and record the
   cold-read round budget. Verify each concrete claim against code and command
   definitions, directly or through the factual slot. Mark uncertain claims as
   inferred. File existence alone does not prove the claim. Accept the factual stage
   before the cold read.
3. If authorized, dispatch the cold read: a fresh `elephant-goldfish/cold-reader`
   child that receives only the document, its procedural definition and correlation
   fields. It reports every bootstrap gap, numbered and marked blocking or minor, then
   `VERDICT: READY` when no gap blocks or `VERDICT: NOT READY`. It does no repository
   inspection. Record that the document-only rule is an instruction boundary: T3
   workspace access is not a security sandbox. If independent review is unavailable,
   report the document unreviewed.
4. On NOT READY, repair the named gaps yourself, repeat the factual check on the new
   hash, then request a fresh cold read in a new child. New documents stop after twelve
   rounds in total; legacy loops keep the five-round limit they started under, minus
   the rounds already performed. A missing, failed, or ambiguous verdict is an error,
   never READY. Do not seek another reviewer simply to overturn an adverse verdict.
5. Run `validate-final` over both stages. Report factual verification and cold-read
   readiness separately. A plausible document is not proof of working software.
   Deliver the file and unresolved claims.
