# .agents

[![skills.sh](https://skills.sh/b/seankoji-com/.agents)](https://skills.sh/seankoji-com/.agents)

*Give your coding agent a way to finish the job.*

A collection of skills for the work around writing code. Decide what to build,
choose how it should work, get an independent review, and carry a change through
to delivery with evidence that it works.

You describe the outcome. The skills give your agent a repeatable way to work
toward it, and give you a way to see what is decided, what is checked, and what
still needs your attention.

[Find a skill](#find-your-starting-point) · [Why T3 Code](#built-for-t3-code) · [See an example](#what-it-looks-like-in-practice) · [Get started](#use-the-library) · [All skills](#skill-catalog)

> [!TIP]
> **New here?** The [skills site](https://seankoji-com.github.io/.agents/)
> describes every skill in plain language, with a copy-ready install command
> for each one. This README is the full reference.

## Why these skills exist

A coding agent can produce a patch while leaving the important work unfinished.
It may solve the wrong problem, make a product decision you wanted to make,
review its own assumptions, or stop while checks are still running.

This library gives those parts of the job names and instructions. You can ask
for a focused interview before building anything. You can get a second opinion
without asking for edits. You can hand over a change for delivery and expect the
agent to track it through review and the repository's release gates.

The aim is to spend your attention on decisions that change the result. Routine
work continues within the scope you gave; consequential unanswered questions
come back to you.

## What is a skill?

A skill is a small written guide that your coding agent reads when it needs to
perform a particular kind of work. Each folder has a `SKILL.md` file with the
purpose, steps, evidence to collect, and conditions for finishing.

The names describe jobs. `think` helps you decide what you mean. `review`
checks work against the goal. `ship` owns delivery. You can use one skill on its
own or combine several in a request.

Your agent host supplies the models, tools, permissions, and any background
workers. This repository supplies their working instructions. There is no
service to start or separate scheduler to run.

## Built for T3 Code

The skills are written and tested in [T3 Code](https://github.com/pingdotgg/t3code),
which runs agents from several providers, such as Codex, Claude and OpenCode, in
one app. They use what T3 provides:

- **Reviewers from another model family.** `review`, `think`, `challenge`,
  `review-loop` and `design-loop` have a model from a different family check the work. A model checking
  its own work tends to share the blind spots that produced it
  ([research](#why-a-different-model-family-reviews-the-work)). T3 can start that
  reviewer on another provider from inside the same conversation.
- **Separate workspaces.** `implement` runs coding in its own T3 worktree, so the
  main conversation stays free for decisions and reviews.
- **Background tasks.** `raise-issue` files issues in a background T3 task while
  delivery carries on.
- **PR watching without polling.** `babysitter` uses T3's pull request watch, which
  wakes the agent when checks or reviews change.
- **Progress and previews you can see.** `ship` keeps its task list in T3's plan
  panel, and `choose-design` shows mockups side by side in T3's preview frames.

Most skills still work in Claude Code, Codex or another host that supports
skills, using what that host offers instead. Outside T3, `babysitter` waits with
its bundled `scripts/pr-wait` helper, and `ship` posts status lists in the
conversation. `implement` and asynchronous `raise-issue` need T3. Cross-family
review needs a host that can reach a second model family; without one, the agent
reports the review as unavailable instead of reviewing its own work.

## Why a different model family reviews the work

When a model reviews its own work, or work from a close relative, it tends to
rate that work too kindly and to repeat its mistakes. Published research points
the same way:

- **Models recognise and favour their own output.** Panickssery, Bowman and Feng
  found that GPT-4 and Llama 2 can tell their own text from other models' and
  humans' at better than chance. The stronger that self-recognition, the stronger
  the self-preference ([2024](https://arxiv.org/abs/2404.13076)). Wataoka,
  Takahashi and Ri measured significant self-preference in GPT-4 and linked it
  to familiarity: judges score low-perplexity text higher than human raters do
  ([2024](https://arxiv.org/abs/2410.21819)). The MT-Bench study by Zheng et al.
  lists self-enhancement among the biases of LLM judges
  ([2023](https://arxiv.org/abs/2306.05685)).
- **Related models make the same mistakes.** On one leaderboard dataset, Kim et
  al. found that when two models are both wrong, they give the same wrong answer
  60% of the time. A shared provider and a shared architecture are among the
  causes ([ICML 2025](https://arxiv.org/abs/2506.07962)).
- **Self-correction without outside feedback is unreliable.** Huang et al. found
  that models struggle to fix their own reasoning without external feedback, and
  sometimes get worse when they try ([ICLR 2024](https://arxiv.org/abs/2310.01798)).
- **Mixing families helps.** Verga et al. replaced a single GPT-4 judge with a
  panel of smaller models from different families. The panel did better across
  six datasets, showed less bias towards any one model and cost over seven times
  less ([2024](https://arxiv.org/abs/2404.18796)).

The [review](skills/review/SKILL.md) skill applies this in a few rules:

- The primary reviewer's lineage must differ from the coordinator's and from every
  model that materially wrote the work. A new version, effort setting or provider
  alias of the same model is still the same lineage.
- Findings need evidence, such as a reproduction, test output, screenshot or
  file and line. A verdict without supporting reasoning does not count. Kim et al.
  also found that strong models from different providers still share many errors,
  so a second family reduces shared blind spots without removing them.
- When several judges score a loop round, the round takes the lowest score.
- In `review-loop` and `design-loop`, an additional judge may share a lineage
  when its reasoning level is strictly higher than every implementor's. That
  exception is this library's own judgment, made to widen the judge pool. The
  research above does not test it, and it never replaces the primary
  cross-lineage review.
- If no second family is reachable, the agent reports the review as unavailable.
  It does not review its own work and call that independent.

These studies measure LLM judges and reasoning benchmarks, not code review with
these skills. They support the design choice. They do not show how much it
improves results here.

## Find your starting point

Choose a skill by the job you want done. Each link opens the instructions your
agent will follow.

[Product and design](#product-and-design) · [Engineering](#engineering) · [Writing and conversation](#writing-and-conversation) · [Agent setup](#agent-setup)

### Product and design

Settle what to build and how people will use it before implementation.

- [think](skills/think/SKILL.md): Turn an idea into a buildable brief through focused questions and a check for unresolved decisions.
- [challenge](skills/challenge/SKILL.md): Get an independent critique of a proposal, a simpler alternative, and evidence that would help you choose. No implementation.
- [choose-design](skills/choose-design/SKILL.md): Compare visual options for a new interface or a material interaction change, then choose before building.
- [design-loop](skills/design-loop/SKILL.md): Research comparable products and autonomously improve the real UI toward a fixed score target, with cross-lineage judges and annotated reports each round.
- [focus-group](skills/focus-group/SKILL.md): Explore a product through fictional participants in a clearly labelled synthetic study. Model responses are not human research.

### Engineering

Build, check, and deliver changes with evidence of what works and what remains.

- [ship](skills/ship/SKILL.md): Carry a change through implementation, checks, independent review, and delivery, with visible progress and a final workflow retrospective.
- [implement](skills/implement/SKILL.md): Move substantial coding into a separate workspace and return reviewed commits to the main conversation for integration. Requires T3 delegation.
- [review](skills/review/SKILL.md): Evaluate a plan, change, or release using an independent model family. Return findings tied to evidence without changing code.
- [review-loop](skills/review-loop/SKILL.md): Hill-climb through repairs and review until the score target and required gates pass or two consecutive rounds fail to improve the best score.
- [test-writer](skills/test-writer/SKILL.md): Choose tests that catch consequential failures, with attention to reliability, maintenance, and CI time.
- [raise-pr](skills/raise-pr/SKILL.md): Prepare PR descriptions and evidence that meet the repository's requirements. Creating or updating the PR needs authority from your request.
- [babysitter](skills/babysitter/SKILL.md): Repair an existing PR, handle checks and review gates, and verify its merge when permitted. Explicit limits such as no-merge still apply.
- [raise-issue](skills/raise-issue/SKILL.md): Prepare and file a bug, feature, or task asynchronously, preserving the evidence and returning a verified issue URL. Requires T3 delegation.

### Writing and conversation

Understand the work and communicate it clearly.

- [github-writing](skills/github-writing/SKILL.md): Credit AI-written GitHub prose with a visible byline naming the actual writer and represented operator.

### Agent setup

Maintain the instructions and configuration your agents depend on.

- [agent-tuneup](skills/agent-tuneup/SKILL.md): Diagnose settings, permissions, connections, or missing skills. Separate saved configuration from observed behavior.

## What it looks like in practice

Suppose you want to add a replay to a browser game. You know the outcome, but
have not decided how replay timing should work.

```text
Add a post-game replay that plays the match in real time.
Use think to settle the timing decisions before implementation.
Keep the game's existing visual style.
```

The interview should resolve questions that change the implementation. Does
pausing the replay pause the whole game? What happens if someone leaves? It
should use facts already available in the project and reuse decisions you have
made.

If the replay needs a new control that the existing design does not answer,
`choose-design` can help you choose it. If the current interface already gives
a clear answer, the agent can preserve it and continue.

For delivery, you can be explicit about the endpoint:

```text
Ship the agreed replay. Verify playback in the browser, get an independent
review, and take it through the repository's checks and merge gates.
```

You should receive the result and its evidence, with any unfinished work named.
A passing local test, a merged PR, and a working production replay are separate
claims. Each needs its own verification.

You can also keep the job narrow:

```text
Challenge this replay proposal. Return findings without editing code.
```

That request ends with an evaluation. It does not start implementation.

## What you stay in control of

Skills carry different scopes. Read the linked instructions before handing over
a job, especially one that can publish or merge changes.

- **Decisions.** The agent asks about missing choices that could materially
  change the next step. Settled choices stay settled unless new evidence affects them.
- **Authority.** `ship` and `babysitter` include scoped commits, pushes, and
  merges through repository protections. Explicit limits in your request still apply.
  `ship` also permits rebasing its own PR branch with `--force-with-lease`, filing
  deferred-bug issues, and proposing workflow improvements as issues in your
  explicitly configured skill repository. These skills do not bypass protections.
- **Sharing.** Invoking `choose-design` permits sending the minimal design
  brief to the selected providers, subject to your sharing limits. Broader raw-file
  sharing needs separate authority.
- **Review.** Independent review uses a different model family from the
  coordinator and material authors. Additional loop judges may share a lineage
  when their verified reasoning level is higher than every material implementor's.
- **Evidence.** The agent reports checks against the revision it actually tested.
  Missing access, unavailable reviewers, and unverified behavior remain visible gaps.
- **Follow-through.** Confirmed bugs deliberately left unfixed need tracking.
  The workflow records what remains rather than treating a passing check as the end.

These are instructions for agents to follow. The library's own tests check its
structure and helper behavior; they do not establish how reliably a live model
will follow every instruction or prove a cost or quality advantage.

## Use the library

Pick the skills you need. You can install one or more through
[skills.sh](https://skills.sh/seankoji-com/.agents) without adopting this owner's
whole setup. Run this from your project and choose the skills and agents:

```sh
npx skills add seankoji-com/.agents
```

Or select a single skill:

```sh
npx skills add seankoji-com/.agents --skill think
```

The [Skills CLI](https://github.com/vercel-labs/skills#install-a-skill) requires
Node.js 22.20 or later. Workflow skills can reference other skills in this
library; install their supporting skills too. Installation does not supply the
host capabilities described below.

### Use an installed skill

Invoke a skill using the convention your host supports, such as its name in a
request or a slash command. Start with a bounded job:

```text
Use review to evaluate this implementation against the brief. Do not edit files.
```

`focus-group` disables automatic model invocation.
Use your host's explicit skill invocation, such as `/focus-group`
where slash commands are supported.

### Work from a clone

To edit the skills or maintain your own copy, clone the repository:

```sh
git clone https://github.com/seankoji-com/.agents.git
```

Point your host's native skill discovery at the clone's `skills` directory,
using that host's configuration. Keep the directory together because skills
link to sibling skills and references. You can read every skill directly on
GitHub before configuring discovery.

### Host requirements

The library is written for **T3 Code and Codex**, and optimised for T3 Code.
[Built for T3 Code](#built-for-t3-code) explains what the skills use there. Other
hosts can use skills whose required capabilities they provide. Isolated `implement` and asynchronous
`raise-issue` require T3 delegation. Follow each skill's own fallback when a
required capability is missing. Inline issue work requires an explicit request.

Reading the instructions needs no running service. Python helpers require Python
3.10+ and the standard library. Owner host-delivery configuration is only for
maintaining this repository, not for using skills from a clone.

Older releases through v0.13.2 contain archives from the previous package.
Use the current `skills` tree for the library described here.

## Other skills I use

These skills come from [pstack](https://github.com/cursor/plugins/tree/main/pstack).
Install them from upstream rather than from this repository:

- [bro](https://github.com/cursor/plugins/blob/main/pstack/skills/bro/SKILL.md): Restate the last answer in plain language.
- [unslop](https://github.com/cursor/plugins/blob/main/pstack/skills/unslop/SKILL.md): Remove formulaic AI phrasing from writing.
- [ketchup](https://github.com/cursor/plugins/blob/main/pstack/skills/ketchup/SKILL.md): Catch up on changes in a conversation and decisions waiting on you.

```sh
npx skills add cursor/plugins --skill bro unslop ketchup --global
```

These require explicit invocation on hosts that respect
`disable-model-invocation`, such as `/bro`, `/unslop` or `/ketchup` where supported.

For writing skills and agent instructions, install
[writing-for-agents](https://github.com/mattpocock/skills/tree/main/skills/productivity/writing-for-agents)
from Matt Pocock's library. It replaces this repository's former `agent-docs` skill
and keeps its upstream name:

```sh
npx skills add mattpocock/skills --skill writing-for-agents --global
```

This library maintains its own versions of several workflow skills inspired by
other libraries. They remain here because their instructions differ from
upstream. Third-party installations are local state, excluded from the generated
catalog and from Git. The owner checkout ignores the installed `bro`, `unslop`,
`ketchup` and `writing-for-agents` folders, the Hindsight coding-agent plugin's
generated `hindsight-coding-agent` folder and the Skills CLI's global lock file.
A fresh checkout does not install these optional skills automatically.

## How the workflows fit together

Use the skills that help with the current task. You do not need the whole
library for every change. The [workflow guide](https://seankoji-com.github.io/.agents/workflows.html)
on the skills site shows the handoffs with diagrams: decisions, implementation
in a separate worktree, review, delivery, deferred-bug filing and the T3
permission workarounds. Each skill's own file holds the exact rules.

A strong model coordinates each workflow. The reviewers and workers it starts
can be cheaper models. They read a short role card instead of a whole skill:

- [assigned-reviewer card](skills/review/references/assigned-reviewer.md) for a
  dispatched reviewer or judge.
- [implementation-participant card](skills/review/references/implementation-participant.md)
  for a dispatched coding or repair worker.

AI-written GitHub passages open with a visible byline under
[github-writing](skills/github-writing/SKILL.md):

```markdown
> [!NOTE]
> _Written by **GPT-6.1 Sol** on behalf of @seankoji_
```

## Skill catalog

The complete index below uses each skill's own metadata. Use the grouped list above
for a human introduction, or open a skill here to read its exact instructions.

<!-- skill-catalog:start -->

| Skill | When to use it |
| --- | --- |
| [agent-tuneup](skills/agent-tuneup/SKILL.md) | Use when the user asks to audit, troubleshoot or change agent configuration, permissions, MCP connections or native skill discovery. |
| [babysitter](skills/babysitter/SKILL.md) | Autonomously repair requested pull requests through verified merge. Use when asked to babysit, merge, watch or monitor PRs; honour explicit read-only and no-merge limits. |
| [challenge](skills/challenge/SKILL.md) | Pressure-test an idea, design or proposal with an independent cross-lineage reviewer. Use when the user asks for an adversarial second opinion, asks "are you sure", or wants to challenge assumptions; return findings without implementation. |
| [choose-design](skills/choose-design/SKILL.md) | Use after product decisions are settled for new UI, requested redesigns or material unresolved visual or interaction choices. For existing UI, preserve its design and limit choices to the requested change; routine edits need no chooser. |
| [design-loop](skills/design-loop/SKILL.md) | Improve a product's UI through reference research, direct interaction and scored cross-lineage judging, with annotated HTML reports each round and a final PR. Use for autonomous design iteration toward a score target, rather than operator-selected mockup options. |
| [focus-group](skills/focus-group/SKILL.md) | Use when the user requests a synthetic focus group or persona-based product evaluation, including planning, running or reviewing the study. |
| [github-writing](skills/github-writing/SKILL.md) | Use whenever drafting or editing LLM-written GitHub issues, pull requests, comments, reviews, discussions or release notes on the user's behalf. |
| [implement](skills/implement/SKILL.md) | Use when the user invokes implement or requests implementation through T3 delegates, returning reviewed commits for the main thread to integrate and ship. |
| [raise-issue](skills/raise-issue/SKILL.md) | Use when the user or an authorised workflow asks to investigate, prepare, file or follow up on a bug, feature or task issue in an owned, organisation or external repository, using an asynchronous T3 delegate. |
| [raise-pr](skills/raise-pr/SKILL.md) | Use whenever creating or updating a pull request, including during implementation, review-loop, ship and PR maintenance. |
| [review](skills/review/SKILL.md) | Use for independent cross-lineage reviews of plans, code, UI, backend and releases, including review-loop participants and think's stop-condition check. |
| [review-loop](skills/review-loop/SKILL.md) | Use when the user requests an iterative implementation, independent review and repair loop, or invokes review-loop to carry a goal to an agreed endpoint. |
| [ship](skills/ship/SKILL.md) | Use when the user explicitly asks to ship a change through delivery, visible progress tracking and a final workflow retrospective. |
| [test-writer](skills/test-writer/SKILL.md) | Use when writing or reviewing tests, choosing regression coverage, or assessing test value, reliability and CI runtime. |
| [think](skills/think/SKILL.md) | Think a plan, decision or idea through with focused questions until it is ready to build. Use when the user says think or thinking about a plan, decision or idea, such as think this through, think about it or keep thinking, asks to interrogate or stress-test it, or wants an interview to clarify their thinking. |

<!-- skill-catalog:end -->

## Maintaining this library

The instructions below are for people changing or publishing this repository.
They cover documentation checks and the owner's direct-publication workflow.

<details>
<summary><strong>Contributor and owner guide</strong> · checks, publication, and host delivery</summary>

### Documentation that tracks the code

```sh
python3 -B scripts/check_library.py
python3 -B -m unittest discover -s tests -v
```

The same checks run in CI and before owner publication. They enforce:

- Every registered skill appears exactly once in the generated catalog, with
  its current description. New source skills must be registered.
- Local Markdown links resolve, and annotated Mermaid skill nodes name real skills.
- The [skills site](site/index.html) lists every registered skill once, and its
  install commands, picker and related-skill lists name only registered skills.
  Its [workflow guide](site/workflows.html) links and diagrams name only
  registered skills. Pushes to `main` that change `site/` deploy it to GitHub
  Pages through `pages.yml`, the only Pages workflow.
- Role cards stay under 600 words and contain no links, so a child agent that
  reads one loads nothing else.
- Changes to skill instructions or their Markdown references invalidate the
  README's review receipt, requiring another look at the prose and diagrams.
- Skill metadata, entry-point budgets, helper imports and relocation contracts
  continue to pass the existing library checks.

To see what each skill costs to load, in words:

```sh
python3 -B scripts/check_library.py --stats
```

"entry" is the `SKILL.md` alone, "own folder" adds its references, and "all
links" is what an agent loads if it follows every link. Keep links conditional:
say when the linked file must be read.

After reviewing the README and the site's workflow guide against changed
instructions, refresh the README with:

```sh
python3 -B scripts/check_library.py --update-readme --acknowledge-docs
```

The command regenerates the catalog and records the current instruction digest.
It preserves the hand-written prose and diagrams. A review receipt records an
acknowledgement; it cannot prove that a human or model checked every claim.
Tests do not establish Mermaid rendering, live model behaviour, installed skill
discovery or deployment success. Those need separate evidence.

People changing the library should also read [AGENTS.md](AGENTS.md).

<!-- skills-review: 640e7b7fb464556fcf8bc5058cb0a16019b62aed9c8673001065a24274c50f37 -->

### Owner maintenance

This repository publishes by fast-forward updates to `main`; it does not use PRs
for its own maintenance. That repository policy is separate from the PR workflow
the skills support in other projects.

These commands are for the repository owner. Using the skills from a clone does
not require host-delivery configuration.

#### Configure host delivery

Copy [.env.example](.env.example) to `.env` in the repository root, then replace
its synthetic destinations with SSH aliases or `user@host` destinations you control:

```sh
cp .env.example .env
```

Set `MAINTAIN_SYNC_HOSTS` to a whitespace-separated list. The loader reads this
setting from the file, not from shell environment variables. Real destinations
belong only in the local `.env`. Files matching `.env*`, including local variants
and editor backups, are ignored; `.env.example` is the sole checked-in exception.
Keep that example generic.

Each receiver keeps its source checkout at `~/.agents` and its discovery refresh script at
`~/.dotfiles/scripts/t3-workflow-skills.py`. Configure SSH keys, ports and jump
hosts through your SSH configuration. The receiving checkout must be clean, on
`main` and use the same origin as the publishing checkout.

`maintain.py` reads `.env` beside the script's repository, regardless of the
working directory. It accepts UTF-8 with or without a byte-order mark, quoted
values, comments beginning after whitespace and an optional `export` prefix for
`MAINTAIN_SYNC_HOSTS`. It does not execute shell code, expand variables
or export settings to subprocesses. Other settings are ignored. Missing, empty,
invalid or duplicate destinations stop publication before commits or pushes.
Validation and commit hooks need no local host configuration.

#### Publish and retry delivery

```sh
python3 scripts/maintain.py check  # validate only
python3 scripts/maintain.py        # validate, commit, push and deliver to configured hosts
python3 scripts/maintain.py sync   # retry configured host delivery
```

The publication command stages current changes, obtains a commit message from
the local Codex CLI and pushes `main`. It then updates the owner's configured
checkouts with fast-forward updates, runs their tests and refreshes skill
discovery. It stops publication on failed local checks, a changing working tree
or a rejected push. A dirty receiver is left untouched, and delivery continues
to the other configured destinations. A partial delivery reports failure while
preserving the source commit, successful push and completed receiver updates.
Fix the reported receiver problem, then use `maintain.py sync` to retry delivery
without generating another commit.

#### One-time external skill migration on receivers

Older checkouts track `bro`, `unslop`, `ketchup` or `agent-docs`. Updating removes
those tracked files, even if you installed identical upstream copies beforehand.
The upstream replacement for `agent-docs` is named `writing-for-agents`. Sync detects
this transition and leaves that receiver's checkout untouched. Migrate each
affected receiver once, then retry delivery from the publishing checkout.

On a clean receiver checkout on `main` with the expected origin, first check
that the Skills CLI is available. Then update and immediately reinstall the upstream
skills before refreshing discovery:

```sh
cd ~/.agents
npx skills --version
git pull --ff-only origin main
npx skills add cursor/plugins --skill bro unslop ketchup --global --agent codex --yes
npx skills add mattpocock/skills --skill writing-for-agents --global --agent codex --yes
python3 scripts/check_library.py
python3 ~/.dotfiles/scripts/t3-workflow-skills.py install
python3 ~/.dotfiles/scripts/t3-workflow-skills.py check
```

Run the update and reinstall while no agent is using those skills. If the
installation fails, keep that receiver out of use and rerun the installation
before refreshing discovery. Sync does not install third-party skills or change
provider settings automatically. A sync run can update other receivers while
reporting this receiver's migration hold.

In T3, the Publish action in `t3.json` runs the same owner workflow and requires
the same local `.env` setup. It does not supply destinations or bypass checks.
Organisation workflows remain in place. Publishing, receiver tests, discovery
refresh and fresh-session acceptance are separate results.

#### Keep maintenance logs local

For a worktree-owned log, pass `--log-file` with a new path in an existing ignored
directory. The helper creates the file with owner-only permissions and refuses
to overwrite an existing file. Without this option it uses the system temporary
directory.

Local MCP settings, synced skill copies, marketplace state and machine wiring
are ignored. Keep them out of the public source; do not force-add ignored paths.

</details>

## License and security

[MIT licensed](LICENSE). Report vulnerabilities through the repository's
[private advisory form](https://github.com/seankoji-com/.agents/security/advisories/new).
If it is unavailable, follow the
[organisation security policy](https://github.com/seankoji-com/.github/blob/main/SECURITY.md).
Keep secrets and private logs out of public reports.
