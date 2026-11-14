# Open pull requests

Read when opening the queue and on every re-inventory in a repository run. Every
open PR in scope is backlog. It leaves the backlog merged, closed with evidence,
explicitly held or in flight elsewhere.

## Classify each PR

Record one ledger row per PR with its head SHA, class, owner, evidence and next
action. Re-check the class on every wake; ownership changes.

1. **In flight elsewhere.** A live owner outside this run covers it: a T3 thread,
   ship or babysitter run, or a human, whose current activity on this PR you
   verified. Evidence is the owner's thread or task state, its watch or link,
   or owner action on the current head. A title, assignee, bot activity or old
   branch is not ownership. Record the owner link and next trigger. Add no watch,
   push, review request or merge. When that owner ends without a merge or
   closure, reclassify.
2. **Adopt.** No verified live owner. The main coordinator runs babysitter on it
   as sole owner with one native watch, under burn-down authority. Repair and
   review tasks count against the run's delegate cap. A pre-existing draft
   follows babysitter's draft rule before conversion.
3. **Retire.** Current evidence shows the PR no longer earns a merge: a newer PR
   or bump supersedes it, it duplicates another open PR, its change already
   landed on the base, or it is abandoned and its remaining value is gone.
   Apply the classification rubric's closure-first test and protections.
4. **Ask.** Closing a draft, or a PR whose changes exist nowhere else on the base
   or in another open PR, needs owner confirmation first. So does a protected
   case under the rubric. Keep babysitting independent gates while waiting.

## Dependency bots

- Adopt Dependabot, Renovate and similar PRs like any other unowned PR.
- Treat organisation automerge or repair bots as evidence to inspect. A bot
  actively pushing to the current head is another writer: coordinate under
  babysitter's one-writer rule. Enabled auto-merge alone is not ownership;
  babysitter's pre-watch audit still applies.
- Repair what the bump directly breaks inside the PR: lockfiles, types,
  configuration, tests and small call-site changes.
- When a bump needs a real migration, such as API changes across modules,
  changed data or behaviour, or a multi-PR plan, ask the owner: migrate now,
  or close with an ignore rule for that version. Give the evidence and a
  recommendation.
- A newer bump of the same dependency supersedes an older one only when it
  carries everything the older PR delivers and can merge without a pending
  migration. Then close the older PR with a link. Otherwise keep the older
  bump, for example a compatible security patch, moving.

## Close a PR unmerged

1. Post a short evidence comment under github-writing: the superseding PR or
   commit, the landed change, or why the remaining value is gone.
2. Close the PR and read back its state.
3. Reclassify any linked issues. A closed PR never closes or satisfies them.
4. Record the evidence and reason in the ledger.

## Schedule and discover

Service adopted PRs before new issue work: merging or repairing in-flight work
reduces both counts and later conflicts. Fill the remaining capacity with issue
dispatch. A PR waiting on checks holds no delegate slot.

A burn-down request is the owner's explicit request for coverage of its scope.
On every wake and at the final audit, re-list open PRs and issues, then classify
and adopt new ones. This re-inventory belongs to the active run. It is not a
poller or scheduled sweep, and nothing stays covered after handback unless the
owner requests a scheduled sweep.

## PR endpoint

- A PR is done when GitHub confirms it merged, or when it is closed with
  read-back and recorded evidence.
- In-flight-elsewhere PRs and issues may remain at a "not zero" handback, each
  with its owner link and next trigger. They never excuse work this run owns:
  an adopted PR, active delegate, pending acceptance or required tracking.
