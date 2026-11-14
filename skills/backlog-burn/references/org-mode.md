# Org mode: launch one run per repository

Read when the owner names an organisation as the burn-down scope. Org mode is a
launcher. It starts independent repository runs and hands back. It owns no
issues, PRs, watches, delegates, ledger or retrospective. Naming an organisation
is the owner's request for these top-level threads.

1. Record the organisation and the request's authority and holds. Each launched
   run receives them unchanged.
2. Paginate the organisation's repositories. Keep non-archived, non-fork
   repositories with at least one open issue or open PR. Record each skipped
   repository and its reason.
3. For each kept repository, look for a live backlog-burn coordinator bound to
   it. Read the candidate thread to confirm it is running a burn-down of that
   repository. When one exists, skip the repository and record its link. Live
   owners of single PRs do not count; the repository run treats them as in
   flight elsewhere.
4. Match the T3 project by repository identity, not title. When none exists,
   clone and register it through T3's project tools. Record a failure with its
   error and continue with the other repositories.
5. Launch one top-level thread per repository through T3's thread-launch tools,
   in host-sized batches. Use the matching project, a worktree workspace from
   the default branch on origin, the session's model and options, and a stable
   `clientRequestId` per repository for safe retries. Prompt: use backlog-burn
   to burn down `<owner/repo>`'s open issues and pull requests, with the carried
   authority and holds.
6. Read back each launch receipt. Distinguish a created thread from a started
   agent, and report pending preparation as pending. This is one bounded check,
   not supervision.
7. Report the organisation, repositories considered, launched thread links,
   skipped repositories with reasons, failed launches with errors, and the open
   issue and PR counts observed at launch. Then hand back.

Each repository run owns its own delivery, delegate cap, report and
retrospective. Org mode does not watch, aggregate or retrospect them.
