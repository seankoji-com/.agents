---
template: home.html
title: Overview
description: "Fix bugs with current evidence, plan work a fresh thread can use, and carry PRs through review and CI. Five installable workflows for T3 Code."
hide:
  - toc
  - navigation
---

## Start with one useful result

[Install the current catalog from source](getting-started.md#from-source) on the
machine where your T3 provider executes tools, then paste the generated readiness
prompt into T3. The Homebrew tap still packages v0.4.0, whose commands differ from
these guides. The agent checks whether it can run the workflow before changing
anything. For the picker, enable **Show skills in slash
menu**, restart the agent session, then select **t3-imps** from `/` and append a task.

[Installation and source setup](getting-started.md) ·
[Your first workflow](first-workflow.md) · [Troubleshooting](troubleshooting.md)

## Know what was checked

imps ties checks and reviews to the revision they verified. If the files change,
the evidence is stale. Its report names missing checks and blockers, with a run ID
for resuming after an interruption. A local pass does not stand in for CI, merge or
live deployment.

[See how imps works](plugins/imps.md) · [Safety and data](safety.md)

## Use the model you choose

The agent reads the same workflow entry with your selected T3 provider. Local helpers
use Python's standard library; delegated tasks, previews and watches stay with T3.
Skill discovery and host capabilities vary by provider, so every workflow has a
readiness check and a direct-prompt fallback.

The current catalog has deterministic helper tests. The published live-provider
ledger covers an earlier imps gate; it does **not** certify imps 1.0.
[Compatibility and evidence](compatibility.md) has the exact scope.

MIT licensed. [Source](https://github.com/seankoji-com/t3-plugins) ·
[Contribute](contributing.md)
