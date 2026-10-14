---
template: home.html
title: Overview
description: "Six workflows for coding agents in T3 Code: fix a bug with checks tied to the files you receive, write a brief, cite another repo, finish a PR. Install with Homebrew on macOS or Linux."
hide:
  - toc
  - navigation
---

## What you can check afterwards

An agent saying "done" tells you very little. These workflows leave files behind instead.

- **imps** gives you a run ID and a report that maps each requirement to its evidence,
  bound to the revision the check ran on. Edit a file after that and the report says
  the evidence is stale, so an old pass can't vouch for new code.
- **elephant-goldfish** writes `discovery.md`, `spec.md` and `handoff.md`, with
  hashes, so the next thread gets the brief you agreed to.
- **ape** pins every citation to a commit and line number.
- **babysitter** only reports a merge once it has seen GitHub record one.

Long jobs keep their plan and decisions in your thread. Fresh T3 tasks do each stage,
and a validator accepts or rejects what they return. If the session drops, `resume`
reads the job overview and checks every recorded task before starting anything new.

[How imps works](plugins/imps.md) · [Safety and data](safety.md)

## Where it stops

The workflows are Markdown files any T3 provider can read, plus Python helpers that use
only the standard library. T3 owns delegated tasks, previews and PR watches. Skill
discovery differs between providers, so every workflow has a `doctor` check and a
prompt you can paste when the slash menu isn't available.

The test suite exercises the helpers without calling a model. The published live
results cover an earlier imps gate and do **not** certify imps 1.0;
[compatibility](compatibility.md) has the exact scope.

MIT licensed. [Source](https://github.com/seankoji-com/t3-plugins) ·
[Contribute](contributing.md)
