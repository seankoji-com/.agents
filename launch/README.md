# Public launch kit

Drafts for the owner to edit and publish. Nothing here sends a message or changes
repository settings. Before announcing, confirm the release and site gates below.

## Ready to announce?

- The documentation change has independent review and current-head CI, then merges.
- The release archive and Homebrew formula contain the intended catalog revision.
- A clean install runs `setup`, passes the integrity `doctor`, and prints a usable prompt.
- The deployed Pages site shows the new copy, with working navigation, search and images.
- A real T3 thread invokes the installed current workflow. Report its provider, build,
  operation and result; historical imps results do not certify the new evidence gate.

See [the release procedure](../docs/releasing.md). Plugin manifest versions, GitHub
release tags, the tap formula and installed snapshots are separate version surfaces.
Do not advertise a release that has not reached the install path.

## Repository description

Suggested description:

```text
Five workflows for T3 Code: fix bugs with evidence, plan changes, research code, finish PRs and audit agent settings.
```

Homepage: `https://seankoji-com.github.io/t3-plugins/`.
Suggested topics: `t3-code`, `ai-agents`, `developer-tools`, `agent-workflows`,
`python`, `homebrew`. Upload `docs/assets/social-card.png` in GitHub's repository
social-preview settings after checking it matches the current site.

## Show HN

Title:

```text
Show HN: Five workflows to fix bugs, plan changes and finish PRs in T3 Code
```

Body:

```text
t3-plugins gives your T3 agent a repeatable way to handle five jobs: implement a
bounded change, turn an idea into a testable brief, study another codebase, carry
a PR through review and CI, or audit agent permissions without changing them.

The implementation workflow keeps checks and reviews tied to the files they
verified. If the code changes, the evidence is stale. Interrupted work has a run
ID to resume; blocked work tells you what is missing.

Follow the installation guide, run setup, then select a workflow from T3's
skill picker or paste a generated prompt. The instructions stay the same when
you switch providers. Local helpers use Python's standard library; T3 owns
children, previews and watches.

Current helper tests and historical live-provider observations are documented
separately. The new imps evidence gate has not completed a live provider matrix.
I'd like feedback on the install experience and whether the reports give you
enough evidence to trust the result.

Docs: https://seankoji-com.github.io/t3-plugins/
Source: https://github.com/seankoji-com/t3-plugins
```

## T3 Code community

```text
Five installable workflows for T3 Code: fix bugs with current evidence, plan work
a fresh thread can use, research another codebase, finish authorized PRs, and
inspect agent permissions.

git clone https://github.com/seankoji-com/t3-plugins.git
cd t3-plugins
python3 bin/t3-plugins setup
python3 bin/t3-plugins doctor
python3 bin/t3-plugins prompt imps doctor

Paste the last line's output into T3, or enable the skill menu and select t3-imps
from /. The docs show how to give it a bounded task and inspect the result.

https://seankoji-com.github.io/t3-plugins/

Provider skill discovery varies. Current helper tests are separate from the
historical provider ledger; the new imps gate's live matrix is still pending.
```

## Short post

```text
I built five workflows for T3 Code to save the follow-up work after an agent says
it has finished: current checks and review for a code change, acceptance criteria
for an idea, citations for research, PR blockers, and permission findings.

Install once and use the same entry with your selected provider. imps keeps its
verification evidence tied to the files you receive, and gives interrupted work
a run ID to resume.

Installation, examples and compatibility limits:
https://seankoji-com.github.io/t3-plugins/
```

## Optional media

[Scripted walkthrough](../docs/assets/demo.svg) illustrates installation and a
readiness check; it is not a live model recording. Its content-based snapshot
identifier comes from an archive install, while a Git checkout uses its revision.
[Site preview](../docs/assets/docs-preview.png) shows the field-guide layout.
