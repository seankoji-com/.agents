---
template: home.html
title: Overview
description: "Five agent workflows for T3 Code that keep working when you change the model. Python standard library, evidence before completion, live provider results recorded."
hide:
  - toc
  - navigation
---

## From install to first run

```sh
brew install seankoji-com/tap/t3-plugins
t3-plugins setup
t3-plugins doctor
t3-plugins prompt imps doctor
```

Setup installs snapshots and [skill adapters](slash-commands.md). Enable **Show
skills in slash menu** in T3 and restart the agent session. The agent reads the same
installed entry with the selected provider. Paste the printed prompt when a provider
lacks skill discovery. [Source installs](getting-started.md#from-source) work the same way.

<div class="demo" markdown="0">
<!-- inline-svg: assets/demo.svg -->
</div>

<p class="caption">A scripted recording of the first run: install, <code>doctor</code>, the generated prompt, and what <code>doctor</code> reports inside a T3 thread. Nothing here is a live model call; the frames come from <code>scripts/render_demo.py</code>.</p>

## Sightings

A provider is only listed as working when a live run says so. The ledger below is
generated from `conformance/compatibility.json` at build time, so the numbers on
this page are the numbers in the repository.

<!-- sightings-matrix -->

Two providers completed every repeat of the bug-fix and missing-capability cases.
Antigravity passed one bug fix in three; the other two blocked when a reviewer
listed files it only read as changed, which the core rejected rather than accepted.
OpenCode could run as a child but never opened a parent session. Nothing here
claims more than it observed. [Read the full ledger](sightings.md).

## How it is built

<!-- inline-svg: assets/architecture.svg -->

Three parts, kept apart so each can be inspected on its own:

- **Instructions.** A plugin entry under 1,500 words routes the agent to one playbook. The agent brings its own reasoning and shell.
- **Local tools.** Python standard library only. Installers, state, hashes, and audits are plain scripts with tests.
- **Host orchestration.** T3 owns child tasks, browser previews, and PR watches. The plugins discover its tools; they never ship a second scheduler.

imps adds a small state engine: a claim token names the owner, a generation counter
refuses stale writes, and evidence is tied to the exact revision it checked. An edit
after verification makes the verification stale instead of inheriting its green tick.
[Architecture](architecture.md) has the full picture.

## Why it is built this way

The short version: switching providers should not mean rebuilding your workflow, and a
workflow that cannot show its evidence is a demo. [The case study](case-study.md)
covers the three decisions that shaped the design, what the live conformance matrix
broke, and what changed as a result.

Built by [Sean Carey](https://github.com/seankoji). MIT licensed.
