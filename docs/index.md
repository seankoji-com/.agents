---
hide:
  - toc
  - navigation
---

<div class="hero-layout" markdown>
<div class="hero" markdown>
<p class="eyebrow">Open source · Built for T3 Code</p>

# Change the model. Keep the workflow.

<p class="lead">Seven practical plugins for planning, research, implementation, and review.
Readable instructions guide the agent. Small local tools handle the parts that should be deterministic.</p>

[Get started](getting-started.md){ .md-button .md-button--primary }
[Explore the architecture](architecture.md){ .md-button }
</div>
<div class="terminal">
<p class="label">From your terminal to a T3 thread</p>
<pre><code>$ brew install seankoji-com/tap/t3-plugins
$ t3-plugins install
$ t3-plugins prompt imps doctor</code></pre>
<p class="terminal-note">Paste the generated prompt into T3.<br>Keep the provider you already use.</p>
</div>
</div>

<div class="principles">
<div><strong>One catalog</strong><span>Install once. Read from any T3 provider.</span></div>
<div><strong>Local tools</strong><span>Python standard library. No runtime package install.</span></div>
<div><strong>Checkable outcomes</strong><span>Tests, hashes, revisions, and explicit limits.</span></div>
</div>

## Start with the job you need done

<div class="grid cards" markdown>

- **Make a change and prove it works**

    imps tracks a bounded task through implementation, verification, and independent
    review. Evidence belongs to the revision it actually checked.

    [Meet imps](plugins/imps.md)

- **Work out what to build**

    elephant-goldfish turns a problem into discovery notes, acceptance criteria,
    and a reproducible handoff for a fresh session.

    [Prepare a brief](plugins/elephant-goldfish.md)

- **Learn from another codebase**

    ape studies open-source projects for ideas that address a specific gap in yours.
    Every recommendation needs source evidence and a small experiment.

    [Research with ape](plugins/ape.md)

- **Keep pull requests moving**

    babysitter handles review findings, failing checks, and conflicts within an
    authorized scope. T3 owns the watch and wakes the thread when something changes.

    [Maintain a PR](plugins/babysitter.md)

</div>

Also in the catalog: [prompt-builder](plugins/prompt-builder.md) for reusable prompts,
[agent-tuneup](plugins/agent-tuneup.md) for settings audits, and
[offload-sidecar](plugins/offload-sidecar.md) for file transforms by path.

## A short path from install to first use

```sh
brew install seankoji-com/tap/t3-plugins
t3-plugins install
t3-plugins prompt imps doctor
```

Paste the printed prompt into a T3 thread. The agent reads the installed entry and
uses the provider you selected. You do not need a Claude marketplace or a second
model client. [Source installation](getting-started.md#from-source) works too.

## Why this project exists

Changing providers should not mean rebuilding the same development workflow.
t3-plugins separates instructions, deterministic tools, and host orchestration so
each can be inspected and tested on its own.

Built by [Sean Carey](https://github.com/seankoji), this repository documents the
engineering decisions as well as the result: ownership-aware upgrades, bounded
delegation, revision-bound evidence, and regression tests for failure paths.

Provider-neutral describes the design, not a promise that every model behaves
identically. New ports are experimental; existing imps conformance is partial.
[Read the evidence and limits](compatibility.md) before relying on unattended work.
