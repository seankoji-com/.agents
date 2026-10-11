# A design document that survives a fresh reader

For `check`, inspect `elephant.md` against the repository without editing it. Verify
every path citation and important build/test claim. Spot-check additions the document
omits. Report "document says / code does" with file and line evidence.

For `elephant`:

1. Draft or revise `elephant.md` with Problem, Technical plan, Alternatives, and
   Detailed implementation sections. Cite the owning paths. Preserve human rationale;
   mark superseded decisions explicitly. Record checked revision and dirty-tree status.
2. Verify each concrete claim against code and command definitions. Mark uncertain
   claims as inferred. File existence alone does not prove the claim.
3. If authorized, delegate a cold review under `PKG/shared/delegation.md`. Give the
   reviewer only the document and a brief asking for every bootstrap gap, numbered and
   marked blocking or minor, then `VERDICT: READY` when no gap blocks or
   `VERDICT: NOT READY`. Request no repository inspection.
   T3 workspace access is not a security sandbox: record that the document-only rule
   is an instruction boundary. If independent review is unavailable, report unreviewed.
4. On NOT READY, repair the named gaps, repeat factual checks, and request a new T3
   review task with the previous findings. Stop after five rounds. A missing, failed,
   or ambiguous verdict is an error, never READY. Do not seek another reviewer simply
   to overturn an adverse verdict.
5. Report factual verification and cold-read readiness separately. A plausible
   document is not proof of working software. Deliver the file and unresolved claims.
