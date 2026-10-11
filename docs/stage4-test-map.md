# Stage 4 test changes

Issue #15 stage 4 adds optional shared learning storage and harvest. No existing
test is deleted. The existing setup installation count now counts installation
receipts separately from the new grant receipts; all surviving installation,
idempotence, preservation and symlink assertions remain.

| Test file | Change | Reason and surviving behaviour |
| --- | --- | --- |
| `tests/test_setup.py` | Changed setup fixture and catalog receipt count; added opt-in grant test | Isolates HOME and both XDG paths; retains the exact 20 installation receipt count and all adapter checks; separately asserts six grant reports, no default config writes and explicit-flag idempotence |
| `tests/test_learnings.py` | New | Canonical identity across worktrees/transports; non-Git/Git-absent fallback; root refusal; read-only immutability; versioned format and authorship; plugin isolation; concurrent writers; symlink/hardlink refusal; fixture-state maintenance; content-install skip; stale proposals and transaction I/O failures; installed helpers for all five plugins |
| `tests/test_learning_grants.py` | New | Dry grants; config backups; idempotence; exact subtree updates preserving sandbox, approval and unrelated settings; unsupported layouts and unsafe paths; soft failures |
| `tests/test_harvest.py` | New | Positive and negative identifier fixtures; blocked drafts omit their text; exact owner approval and edited-draft refusal; fake issue/PR publication with partial URL persistence; changed source and unapproved destination refusal |

The model's decision that a lesson is superseded by current instructions is not
unit-tested. Tests exercise the deterministic helper's transaction and supplied
fixture-state rules. Tests never call live models or mutate GitHub. Sandbox tests
run only against isolated homes; no grant is applied to the owner's configuration.

The required tests, docs checker and strict MkDocs build are separate from hosted
CI and live provider acceptance. Grant configuration does not prove a provider can
write. This stage makes no new live provider compatibility claim.

The strict build supports `T3_DOCS_SITE_DIR` to put generated output in a private
results directory while keeping the literal verification command. Its default
remains `site`; no generated output is committed or edited.

The first review found that global setup wrongly treated HOME as a project. A new
setup-from-home test exercises the default state/config paths and opt-in application.
The storage tests now refuse writes before pending maintenance, and Git lookup
errors refuse an identity change. Harvest approval also binds the project PR slug.
The identifier screen remains conservative about dotted filenames, versions and
relative paths: these false positives are a deferred usability limitation, not a
reason to relax identifier blocking. Git subfolders share their containing repo's
identity by design. Claimed approval strings cannot authenticate a human; the agent
must verify owner provenance in the active conversation before publishing.

The second review found locale-dependent Git diagnostics. Identity probes now use
the C locale, and the failure/fallback fixture verifies that inherited translations
cannot change non-Git detection.
