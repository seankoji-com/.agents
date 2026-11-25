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
> **New here?** The [skills site](https://skills.seankoji.com/)
> describes every skill in plain language, with a copy-ready install command
> and a link to its definition on GitHub. This README is the full reference.

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

- **Separate reviewers.** `review`, `think`, `challenge`, `review-loop` and
  `hillclimb` use separate reviewers or judges. Written-code reviewers differ in family
  from the code authors. A model checking its own code tends to share the blind spots that produced it
  ([research](#why-a-different-model-family-reviews-the-work)). T3 can start that
  reviewer on another provider from inside the same conversation.
- **Three-model votes on T3 Workflows.** `vote` posts a packet to the
  `workflows/vote.ts` T3 workflow. The workflow starts one voter per model
  family, or counts the invoker's existing recommendation when the invoker is on
  the panel. Its code keeps the seat deadline, checks each ballot and each
  seat's recorded model, and tallies the 2/3 choice or the split. Without T3
  Workflows, `vote` reports what is missing and stops.
- **Scored loops on T3 Workflows.** `review-loop` and `hillclimb` post their
  scope, rubric and baseline to the `workflows/scored-loop.ts` T3 workflow. For
  `review-loop` the workflow picks the reviewer by quota pace and lineage; for
  `hillclimb` it takes the confirmed roster and adds the full panel when the
  primary passes, or from the baseline when the operator confirms that. It
  starts each judge in a fresh thread, asks the invoking thread for each repair,
  and keeps the counters, the target gate, the two-round stop and the single
  recovery in code, so a restart cannot dispatch a recovery twice.
- **Separate workspaces.** `implement` runs coding in its own T3 worktree, so the
  main conversation stays free for decisions and reviews.
- **Background tasks.** `raise-issue` files issues in a background T3 task while
  delivery carries on.
- **Subscription checks.** Before routing delegates, the shared
  [dispatch preflight](skills/agent-tuneup/references/t3-dispatch.md) consults
  LiteLLM's limits snapshot when available. It ranks eligible providers by quota
  pace score (`paceScore`), checks current headroom (`headroomNow`) for long
  tasks, and records unknown capacity instead of inventing thresholds.
- **PR watching without polling.** `babysitter` uses T3's pull request watch, which
  wakes the agent when checks or reviews change.
- **Progress and previews you can see.** `ship`, `implement` and `review-loop` show
  their phases in T3's Tasks row when the host exposes a todo tool; the list is
  best-effort and can vanish when the turn settles. `plan-report` shows estimates
  and progress on a timeline, `review-loop` and `hillclimb` render an inline HTML
  score line graph of reviewer scores, targets, failure/recovery annotations and
  3–5 bullet + dimension rationales on hover, and `choose-design` shows mockups
  side by side in T3's preview frames.

Most skills still work in Claude Code, Codex or another host that supports
skills, using what that host offers instead. Outside T3, `babysitter` waits with
its bundled `scripts/pr-wait` helper, and `ship` posts status lists in the
conversation. `implement` and asynchronous `raise-issue` need T3, and `vote`,
`review-loop` and `hillclimb` need T3 with Workflows turned on. Cross-family code review needs a host that
can reach a second model family; without one, the agent reports the review as
unavailable instead of reviewing its own work. `vote` never simulates a ballot:
without its workflow it reports the gap and stops.

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

- Reviewers come from the provider with the best quota pace score once lineage is
  satisfied, then use the model that matches the review's difficulty at high
  effort. Sol, Opus, Sonnet via AGY, Grok 4.7, Neon and Hydrogen are all ordinary
  candidates, so a score alone can make any of them primary and review may land on
  a weaker family than a fixed chain would pick. With no score available the order
  is Sol, Opus, Sonnet via AGY, Grok 4.7, Neon, Hydrogen, all at high effort.
  Formal review keeps DeepSeek Flash V4.1 out of direct reviewer dispatch. OCR
  follows the [OCR skill](skills/ocr/SKILL.md): a public repository draws free
  OpenCode reviewers, and the paid CLI uses DeepSeek Flash V4.1 unless DeepSeek
  wrote the code, in which case it uses Qwen 3.8 Flash and the control that
  sends high reasoning effort. `--effort high` is OCR review depth and is
  recorded separately. `vote` is separate: its ballot seats follow the fixed
  roster in `workflows/vote.ts`, and one unavailable seat may be filled by
  DeepSeek Flash. A vote is not formal review. Other models require
  your explicit selection. The [selection rules](skills/review/references/model-selection.md)
  apply inside `implement` too. If no eligible authorised route remains, review
  stays pending.
- Cross-lineage restrictions apply only to written code, measured against models
  that materially wrote that code. The orchestrator is irrelevant unless it also
  wrote code. Sol can review Opus/Fable-authored code while Sol orchestrates,
  without a waiver. Plans, prose and visual judgments have no lineage exclusion.
  Versions, effort settings and provider aliases do not change a model's lineage.
- Run the primary and required companions in parallel. The primary reviews the
  whole scope, UI/visual behavior included. `opencodereview`, invoking the OCR
  library, is the non-UI/visual companion only where the repository has no PR
  path: its delivery policy requires direct publication, or the host reports
  pull requests unavailable. A repository that accepts PRs uses the primary alone,
  and OCR runs only when you ask for it. Hydrogen high adds a second visual review
  for UI/visual changes; mixed scope uses Hydrogen, plus OCR in a PR-less
  repository. The [parallel-review guide](skills/review/references/parallel-review.md)
  defines invocation, coverage and reporting. Companions do not replace the primary.
- Findings need evidence, such as a reproduction, test output, screenshot or
  file and line. A verdict without supporting reasoning does not count. Kim et al.
  also found that strong models from different providers still share many errors,
  so a second family reduces shared blind spots without removing them.
- When several judges score a loop round, the round takes the lowest score.
- If two consecutive code reviews expose the same design assumption through
  distinct material findings, `review-loop` reconsiders it before the next repair.
- Extra plan and visual judges may share a lineage without an effort exception.
  Their judgments do not replace independent review of authored code.
- If no eligible second family is reachable for code review, the agent reports it as unavailable.
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
- [vote](skills/vote/SKILL.md): Settle a framed binary, multi-option or open decision with three voters from different model families. A 2/3 majority decides; a split comes back to you. A panel model's existing recommendation can fill its seat.
- [challenge](skills/challenge/SKILL.md): Get an independent critique of a proposal, a simpler alternative, and evidence that would help you choose. No implementation.
- [choose-design](skills/choose-design/SKILL.md): Compare visual options for a new interface or a material interaction change, then choose before building.
- [focus-group](skills/focus-group/SKILL.md): Explore a product through fictional participants in a clearly labelled synthetic study. Model responses are not human research.

### Engineering

Build, check, and deliver changes with evidence of what works and what remains.

- [ship](skills/ship/SKILL.md): Carry a change through implementation, checks, independent review, and delivery, with visible progress and a final workflow retrospective that saves durable decisions and files workflow amendments.
- [implement](skills/implement/SKILL.md): Move substantial coding into a separate workspace and return reviewed commits to the main conversation for integration. Requires T3 delegation.
- [plan-report](skills/plan-report/SKILL.md): Show proposed plans, progress and final calibration on a timeline from a private ledger.
- [review](skills/review/SKILL.md): Evaluate a plan, change, or release against its requirements. Code reviewers differ in family from code authors. Return evidence-backed findings without edits.
- [ocr](skills/ocr/SKILL.md): Run OpenCodeReview on a frozen diff. A public repository draws up to three free OpenCode reviewers and returns one grouped report. A private one runs the `ocr` CLI through one watcher.
- [review-loop](skills/review-loop/SKILL.md): Hill-climb through repairs and review until the score target and required gates pass or two consecutive rounds fail to improve the best score. A failed run gets one reflect-fix-re-invoke before it reports. Its T3 workflow keeps the rounds, the stop rule and the recovery in code.
- [hillclimb](skills/hillclimb/SKILL.md): Improve a workflow, artifact or product toward a fixed score target. Confirm the judging roster, follow the rounds in one report and use the real interface for UI judging. A failed run gets one reflect-fix-re-invoke before it reports. Runs on the scored-loop T3 workflow.
- [test-writer](skills/test-writer/SKILL.md): Choose tests that catch consequential failures, with attention to reliability, maintenance, and CI time.
- [raise-pr](skills/raise-pr/SKILL.md): Prepare PR descriptions and evidence that meet the repository's requirements. Creating or updating the PR needs authority from your request.
- [babysitter](skills/babysitter/SKILL.md): Repair an existing PR, handle checks and review gates, and verify its merge when permitted. Explicit limits such as no-merge still apply.
- [raise-issue](skills/raise-issue/SKILL.md): Prepare and file a bug, feature, or task asynchronously, preserving the evidence and returning a verified issue URL. Requires T3 delegation.
- [backlog-burn](skills/backlog-burn/SKILL.md): Drive a repository's open issues and PRs to zero. It closes obsolete issues and superseded PRs with evidence, babysits unowned PRs to merge, and fills available delegate capacity up to 20 for worthwhile work through ship. Naming an organisation launches one run per repository. Requires T3 delegation.
- [settle](skills/settle/SKILL.md): Close out a finished thread. Save durable decisions, remove only what the session created, raise optional follow-ups, release closed PRs, then settle the thread in T3.

### Writing and conversation

Understand the work and communicate it clearly.

- [github-writing](skills/github-writing/SKILL.md): Credit AI-written GitHub prose with a visible byline naming the actual writer and represented operator.
- [binaric](skills/binaric/SKILL.md): Keep messages between AI agents (delegate briefs, follow-ups and child reports) short without dropping the facts the reader acts on. Only for model-to-model text, never for anything a person reads. Dispatching skills point to it.

### Agent setup

Maintain the instructions and configuration your agents depend on.

- [agent-tuneup](skills/agent-tuneup/SKILL.md): Diagnose settings, permissions, hooks, connections, or missing skills. Separate saved configuration from observed behavior.
- [reremember](skills/reremember/SKILL.md): Keep a project's long-term memory accurate. Verify claims against the code, record decisions so a later agent can check them, and supersede stale records.
- [new-skill](skills/new-skill/SKILL.md): Add a skill to this library with a description agents can match, steps a small model can follow, trigger evals and full registration. Slash-only.

## What it looks like in practice

For a longer run, [plan-report](skills/plan-report/SKILL.md) keeps the proposed
plan and its progress in a private JSON ledger and generates a self-contained
HTML timeline. It shows dependencies, milestones, model-labelled build and
review segments, overruns, external events and decisions waiting on you.
Approval freezes the original estimates; recorded replans preserve that history.
Final calibration compares estimates, actual work and review rounds by model
and effort, with known costs and unknown coverage kept explicit. Changed models
are marked not comparable rather than inheriting another model's estimate.

`ship`, `backlog-burn` and `implement` use it at proposal, task completion,
final handback and on request, including solo tasks. Review and fix rounds get
short chat updates. Whole-run timelines appear only at proposal and
final handback; progress reports show the remaining work. Empty collapsible
sections are omitted. Only the main thread presents the report. The
ledger and reports stay in a verified ignored worktree directory, outside GitHub;
removing that worktree loses them. Host cost capabilities and their limits are
documented in the skill's [cost evidence](skills/plan-report/references/host-costs.md).

Each task is one compact row grouped by stream: solid build, hatched review and
a dashed forecast split between build and review, coloured by provider. An
overall bar shows estimated work done. Progress reports hide finished tasks and
start where the oldest open task began; idle gaps over an hour are cut and time
more than four hours ahead is compressed. An mtoks column totals reported
tokens. Running now shows model, task ID and the value of the work; completed
history stays out of progress reports. Future observation timestamps are rejected.

`ship` batches foreseeable owner decisions before dispatch. Agreed owner-only
manual follow-ups remain unverified and tracked, while required gates still
block delivery. Completed visible work gets a captioned screenshot in the thread.
The project's [Delegation settings](skills/ship/references/project-settings.md)
can name routes, capacity ceilings, cadence and screenshot commit permission.
Ready independent work refills available capacity within authority. Routing
changes preserve checkpoints and checkout ownership; they add a new model segment.
Formal review keeps DeepSeek out of direct reviewer dispatch. OCR follows the
[OCR skill](skills/ocr/SKILL.md). Opting into
`review_rounds: 1` keeps primary and companion coverage and permits coordinator
verification of that round's repairs, disclosed as not independently re-reviewed.
The original score stays reported; coordinator verification replaces that score
gate for eligible repairs.
New behavior and later CI/bot findings retain normal review. Before each merge,
fresh rules determine the explicit method; named-check exceptions need actual
authority and their scope appears in the merge message and read-back.

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
  brief and that designer's emphasis to each selected designer, and the base
  brief, option HTML and rendered captures to the Neon/Sol scoring roster,
  including Fable or DeepSeek Flash when a named scorer is replaced. On the
  owner's configured host it also permits uploading that run's option HTML and
  generated comparison index to the private `CHOOSE_DESIGN_S3` base, with links
  shared only with you; it does not permit public access or another destination.
  These sends are subject to your sharing limits. Redact secrets and unrelated
  private data; broader raw-file sharing needs separate authority.
  Where OCR's lane applies, it sends the selected
  diff and context to its configured provider; use existing authority for that scope
  and exclude secrets and unrelated files. Covered authorization needs no repeated question.
- **Review.** Written-code review uses a different model family from the code
  authors. The orchestrator's family is irrelevant unless it wrote code.
  Plans, prose and visual judgments have no lineage exclusion. The primary reviews
  the whole scope, UI included; OCR in a PR-less repository, or Hydrogen high,
  runs alongside it according to the scope.
- **Hillclimb scoring.** Confirm the models, effort and any shared lineage before
  a run. Choose whether to upgrade the primary before the full panel scores its
  first candidate. Direct DeepSeek Flash high is available for Hillclimb scoring
  and the `choose-design` scoring fallback when the route and settings can be
  verified.
- **Evidence.** The agent reports checks against the revision it actually tested.
  Missing access, unavailable reviewers, and unverified behavior remain visible gaps.
- **Stopped scoring loops.** A failed `review-loop` or `hillclimb` run gets one
  automatic recovery, enforced by the scored-loop T3 workflow: the agent
  records the attempt, diagnoses what stalled,
  fixes the cause and re-invokes once from the latest candidate. A deadline or
  spending cap already reached stops the recovery. A repair-round cap already
  reached still allows a setup-only fix, and blocks one that changes the
  candidate. A revised rubric, target or roster
  is recorded and flagged against the original target. If the retry also fails,
  the agent reports both attempts and the best candidate rather than continuing.
- **Follow-through.** Confirmed bugs deliberately left unfixed need tracking.
  The workflow records what remains rather than treating a passing check as the end.

These are instructions for agents to follow. The library's own tests check its
structure and helper behavior; they do not establish how reliably a live model
will follow every instruction or prove a cost or quality advantage.

## Use the library

`hillclimb` replaces `design-loop`. Start new runs with the new name. For an
in-progress run, use its recorded instructions and references from the version
it started on.

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

`focus-group`, `binaric` and `new-skill` disable automatic model invocation.
Use your host's explicit skill invocation, such as `/focus-group` or `/binaric`
where slash commands are supported. Claude Code reads the
`disable-model-invocation` flag and leaves these skills out of the model's skill
list. Codex reads `agents/openai.yaml` instead: `new-skill` sets
`policy.allow_implicit_invocation: false` there and runs as `$new-skill`.
`focus-group` and `binaric` have no such file yet, so Codex still lists them. The T3 dispatch preflight and reviewer
brief link to `binaric`, so coordinators read it when they write a brief.

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
3.10+ and the standard library. The paid OCR route needs the installed
[OpenCodeReview CLI](https://github.com/alibaba/open-code-review) and a configured,
authorised OCR provider. A public repository uses free OpenCode models first and
falls back to that CLI only when every free reviewer fails. UI/visual review needs host browser or device access and
Hydrogen high.
Owner host-delivery configuration is only for
maintaining this repository, not for using skills from a clone.

### Use vote on T3 Workflows

`vote` runs through the `workflows/vote.ts` T3 workflow, so a fresh install
needs three things on each host where you vote:

1. Turn on Workflows in T3 Code, and check that T3's scratch project ("No
   project", at `~/.t3/scratch`) exists. T3 creates it the first time you start
   a thread without a project; voters open their threads there.
2. Put `workflows/vote.ts` in `~/.t3/workflows`. The owner's
   [host delivery](#t3-workflow-delivery) does this; from a clone, copy the
   file there yourself.
3. The hook URL saved in `~/.config/t3-workflows/vote.curl`. The owner's host
   delivery writes it after each install. On a host that has the dotfiles
   installer but missed a sync, run
   `python3 ~/.dotfiles/scripts/t3-workflows.py hooks --source ~/.agents/workflows`.
   From a clone without it, save the URL once in your own terminal rather than
   an agent thread:

   ```sh
   t3 workflow hooks                       # the URL for "vote  ballot"
   install -d -m 700 ~/.config/t3-workflows
   read -rs 'URL?Hook URL: '               # zsh; in bash: read -rsp 'Hook URL: ' URL
   tmp=$(mktemp ~/.config/t3-workflows/.hook.XXXXXX)
   printf 'url = "http://127.0.0.1:3773%s"\n' "$URL" > "$tmp"; unset URL
   mv -f "$tmp" ~/.config/t3-workflows/vote.curl
   ```

Voter threads open in T3's scratch project (`~/.t3/scratch`), not your
repository, and no voter runs in a broader runtime mode than the invoker states.
The workflow cannot check that statement, so treat the hook config as an
operator credential. Antigravity voters need `auto-accept-edits` to submit a
ballot, so from a stricter invoker the Neon seat falls back to the DeepSeek
substitute. Without any of these, `vote` reports what is missing and stops.

### Use the scored loop on T3 Workflows

`review-loop` and `hillclimb` run through the `workflows/scored-loop.ts` T3
workflow. Each host where you run them needs:

1. Workflows turned on in T3 Code.
2. `workflows/scored-loop.ts` in `~/.t3/workflows`, put there by the owner's
   [host delivery](#t3-workflow-delivery) or copied from a clone.
3. The hook URL saved in `~/.config/t3-workflows/scored-loop.curl`. Host
   delivery and the `hooks` command in the vote section write it. From a clone
   without the installer, use the vote section's manual steps with the URL for
   "scored-loop  start" and `scored-loop.curl` as the file name.

Judges open fresh threads in the project the packet names. They read the
committed candidate through `git show` and `git diff` in your checkout and run
in your thread's runtime mode or not at all. Antigravity routes need
`auto-accept-edits` or broader. The packet carries your thread's route report.
The workflow asks your thread for every repair, with the recorded model of each
judge thread that scored the work being repaired, and for the one recovery,
then posts the result with the full score ledger. A continuation's ledger
includes every earlier run. Scores round to the packet's `scale.decimals`
places. A `hillclimb` packet also
names the confirmed primary, the panel and when it joins; a judge sharing a
model family with another judge or with an implementer needs the operator's
recorded approval. Without the workflow, the file or the hook config, either
skill reports what is missing and stops.

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

To add a skill to this library, run `/new-skill`. It defers to `writing-for-agents`
for the writing and covers this repository's description checks, trigger evals
and registration steps.

This library maintains its own versions of several workflow skills inspired by
other libraries. They remain here because their instructions differ from
upstream. Third-party installations are local state, excluded from the generated
catalog and from Git. The owner checkout ignores the installed `bro`, `unslop`,
`ketchup` and `writing-for-agents` folders, the Hindsight coding-agent plugin's
generated `hindsight-coding-agent` folder and the Skills CLI's global lock file.
A fresh checkout does not install these optional skills automatically.

## How the workflows fit together

Use the skills that help with the current task. You do not need the whole
library for every change. The [workflow guide](https://skills.seankoji.com/workflows.html)
on the skills site shows the handoffs with diagrams: decisions, implementation
in a separate worktree, review, delivery, deferred-bug filing and the T3
permission workarounds. Each skill's own file holds the exact rules.

`backlog-burn` assesses closure before dispatch. It strongly prefers closing ordinary
issues that are obsolete, already done or no longer worth pursuing, with a short
evidence-based reason and no per-issue confirmation. It retires trivial leftovers
without replacement issues. Material defects and necessary unmet outcomes remain
actionable; protected issues retain owner review. Reports distinguish completed
outcomes from work retired as not planned. New delivery-review defects still
require fixing or tracking, including SEV3 findings.
Inventory, triage-only and question-only requests propose actions without closure,
implementation or merge.

Open PRs are part of the backlog, and issues and PRs always share one scope. The
default is the current repository. The coordinator babysits every PR without a
verified live owner through merge, including dependency bumps, and makes small
repairs inside the PR. A bump that needs a real migration becomes an owner
question. It closes superseded, duplicate or already-landed PRs with an evidence
comment, and asks before closing drafts or PRs with unique changes. PRs that
another live thread or person already owns are recorded with their owner and
left alone. Each wake re-lists the scope, so PRs opened mid-run are adopted;
nothing stays covered after handback without a scheduled sweep. Naming an
organisation launches one independent repository run per repository with open
work, skips repositories that already have one, and hands back.

Each turn triages open items from their headers. It checks PR ownership and
verifies ready issue fixes side by side, dispatching independent work while it
checks unrelated PRs. It registers PR watches after completing the pass.

It dispatches each worthwhile verified ready issue before reading unrelated
histories, while continuing discovery and owner questions where the host permits.
It uses `ship` for delivery and isolated `implement` leads. Coding leads and
workers default to the main thread's model and effort unless the owner selects another;
reviewers use review's Sol/Opus defaults and cross-lineage eligibility. The main
coordinator uses the maximum host-supported concurrency up to 20 across every
delegate it starts, including nested work, investigations and issue filing, with
child-slot budgets and review headroom.
It records host limits and concrete reasons for unused slots, then refills
available capacity on every completion, PR notification,
answer or continuation wake. An empty ready queue resumes discovery. At full
capacity, the coordinator continues classification and owner questions. It retains
PR delivery and watches, records why capacity is unused, and finishes with one
consolidated retrospective that saves durable decisions to project memory.
Ready independent work starts before blocking questions.
One unanswered question or watched PR cannot stop independent
work. Awaiting-owner requires every remaining issue and PR to be explicitly held,
owned by a live owner elsewhere or awaiting an actual unanswered question; a
host-required yield preserves the queue. Success is a fresh zero for both issues
and PRs. When only held items and work owned elsewhere remain, the run hands
back "not zero" with each owner and next trigger.

A strong model coordinates each workflow. Coding workers can use cheaper models;
reviewers use the defaults above. They read a short role card instead of a whole skill:

- [assigned-reviewer card](skills/review/references/assigned-reviewer.md) for a
  dispatched reviewer or judge.
- [implementation-participant card](skills/review/references/implementation-participant.md)
  for a dispatched coding or repair worker.

Delivery also keeps a repository's linked project board true. `implement`, `ship`,
`raise-pr`, `review-loop` and `babysitter` assign the operator and move an issue
through `In Progress`, `In Review` and `Done` under the
[issue-status contract](skills/ship/references/issue-status.md). `Done` waits for
verified production, or for a verified direct publish. GitHub's default board
sets an option named `Done` itself when an issue closes, so a production gate
maps its release option and keeps no `Done` option. A missing board, field or
option is reported in the handoff and never blocks the work.

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
| [agent-tuneup](skills/agent-tuneup/SKILL.md) | Audit, troubleshoot or change agent configuration, permissions, hooks, MCP connections or native skill discovery when the user asks. |
| [babysitter](skills/babysitter/SKILL.md) | Repair and monitor open pull requests through verified merge when asked to babysit, merge, watch or monitor them. Honour read-only and no-merge limits. |
| [backlog-burn](skills/backlog-burn/SKILL.md) | Clear a repository's open issues and pull requests, or launch one backlog run per repository in a named organisation. Use when asked to clear, burn down or get the backlog to zero. |
| [binaric](skills/binaric/SKILL.md) | ONLY for LLM-to-LLM messages: delegate briefs, follow-ups and child reports, kept short with every fact the reader acts on. Never for anything a human is meant to read. |
| [challenge](skills/challenge/SKILL.md) | Pressure-test an idea, design or proposal with an independent reviewer when asked to challenge assumptions, give a second opinion or answer 'are you sure?'. Return findings without edits. |
| [choose-design](skills/choose-design/SKILL.md) | Compare design options once product decisions are settled. Use for new UI, a requested redesign or an unresolved visual or interaction choice, not for routine edits to an existing design. |
| [focus-group](skills/focus-group/SKILL.md) | Plan, run or review a synthetic focus group or product study with fictional participants. |
| [github-writing](skills/github-writing/SKILL.md) | Add a byline to AI-written GitHub text posted on the user's behalf. Use when drafting or editing issues, pull requests, comments, reviews, discussions or release notes. |
| [hillclimb](skills/hillclimb/SKILL.md) | Improve a workflow, artifact or product toward an agreed score over several judged rounds. Use when asked to hillclimb or to keep improving something until it reaches a target score. |
| [implement](skills/implement/SKILL.md) | Implement through T3 delegation when the user requests it or invokes implement. Return reviewed commits to the main thread for integration and delivery. |
| [new-skill](skills/new-skill/SKILL.md) | Add a skill to this library with a description agents can match, steps a small model can follow, trigger evals and full registration. |
| [ocr](skills/ocr/SKILL.md) | Run OpenCodeReview on a frozen diff and return one grouped report. Use when asked for OCR or OpenCodeReview, or when review calls for it on a repository without a PR path. |
| [plan-report](skills/plan-report/SKILL.md) | Show a plan, progress or final calibration on an HTML timeline from a private ledger. Use for coordinated work, timeline requests or reporting in ship, backlog-burn and implement. |
| [raise-issue](skills/raise-issue/SKILL.md) | Investigate, draft, file or follow up on a bug, feature or task issue when the user or an authorised workflow asks. Use an asynchronous T3 delegate. |
| [raise-pr](skills/raise-pr/SKILL.md) | Prepare, create or update a pull request with the repository's required evidence and checks. Use when preparing, opening or updating a PR during implementation, review-loop, ship or PR maintenance. |
| [reremember](skills/reremember/SKILL.md) | Use when a remembered claim is contradicted by the code, when asked to correct or consolidate what the project remembers, or when a session settles a decision later work depends on. |
| [review](skills/review/SKILL.md) | Review plans, code, UI, backend or releases independently. Use when asked for a review, or for review-loop rounds and think's readiness check. Pressure-testing an idea belongs to challenge. |
| [review-loop](skills/review-loop/SKILL.md) | Implement, review and repair in rounds when asked to iterate with independent review or when the user invokes review-loop. Work toward the agreed score and acceptance criteria. |
| [settle](skills/settle/SKILL.md) | Close out a finished top-level thread and settle it in T3. Use at a completed handback or for /settle. |
| [ship](skills/ship/SKILL.md) | Deliver and verify a change when the user explicitly asks to ship or backlog-burn calls for delivery. Show progress and finish with a retrospective. |
| [test-writer](skills/test-writer/SKILL.md) | Write or review tests, choose regression coverage, or assess test value, reliability and CI runtime. Use when adding tests or judging a suite. |
| [think](skills/think/SKILL.md) | Turn an idea, plan or decision into a brief ready to build. Use when asked to think about it, think it through, keep thinking, interrogate or stress-test it, or clarify it through an interview. |
| [vote](skills/vote/SKILL.md) | Settle a framed binary, multi-option or open decision by 2/3 vote from three blind, distinct model families, or return the split. Use when asked to vote, poll models, or break a deadlock; think frames an unframed decision. |

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
- Every description stays within 40 words and 250 characters, avoids "I",
  "you", "your" and "this skill" outside quotes, never says "then", and, for a skill agents
  can pick up on their own, includes a `Use when/for/at` or `when asked/the user`
  clause. The description loads on every turn, so it says when to pick the
  skill and leaves the procedure to the body.
- Every local link in a `SKILL.md` sits in a sentence with a condition word
  (when, before, after, if, for and similar), so the agent knows when to follow it.
- Every skill agents can pick up on their own has `references/trigger-evals.md`
  with 5 prompts that should select it and 5 that should not, each naming the
  skill expected instead. `/new-skill` describes how to run them by hand.
- Skill metadata, entry-point budgets, helper imports and relocation contracts
  continue to pass the existing library checks.
- Every file in `workflows/` sits directly in that folder under a name T3 loads,
  defines one versioned `T3.workflow` named after the file, and declares the T3
  version it was tested on and whether it starts manually or from an automated
  trigger. Referenced skill files must exist. Effort above `xhigh`, hook URLs and
  token-shaped values fail the check. The check needs no JavaScript toolchain;
  delivery proves that T3 loaded the code.

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
Browser checks are needed to verify the rendered site. Live model behaviour,
installed skill discovery and deployment success each need their own evidence.

People changing the library should also read [AGENTS.md](AGENTS.md).

<!-- skills-review: da6f301d09179564060bf489c6e2f65d39fe029da87887869bffbf9363845cce -->

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

#### T3 workflow delivery

After the receiver's tests and discovery refresh pass, sync runs the dotfiles
installer:

```sh
python3 ~/.dotfiles/scripts/t3-workflows.py install --source ~/.agents/workflows
```

It copies changed workflow files to `~/.t3/workflows`. Manual-start workflows go
to every receiver. Workflows with automated triggers go only to the designated
trigger host, so each event starts one run. Any write in that folder makes T3
rebuild its workflow engine and interrupts every running workflow, so the
installer refuses a change while any run is unfinished. T3 keeps serving the
previous good revision when a new one fails to load or is held back, and its
log of registered workflows names only `name@version`. So a changed workflow
body must raise its `version`, and the installer refuses one that does not.
A workflow that leaves the source, or should stop on a host, is retired by a
trigger-free stub at the next version rather than deleted, so T3 can register
the retirement. After each write the installer requires no load error for a
written file in T3's server trace, and a registration entry that lists each
written `name@version`. A sync with nothing to write still checks that T3 runs
every expected `name@version` now, so turning Workflows off fails the next sync.
Without that evidence the receiver's delivery fails and the next sync retries
it. A host without T3's boot-service log fails delivery unless its installer
runs with `--allow-unverified`, because the trace alone does not name the
definitions that took effect. Moving the trigger host takes two syncs: first with no trigger host,
then with the new one. Dotfiles documents the installer, the trigger-host move
and hook provisioning in `docs/t3-workflow-delivery.md`.

A skill that starts a workflow posts to the workflow's webhook with
`curl --noproxy '' -K ~/.config/t3-workflows/<workflow>.curl`. That private
config holds the hook URL and token, so neither appears in command text or
transcripts. After a successful install, the installer reads
`t3 workflow hooks --json` and writes a mode-600 config for each manual
webhook workflow, printing only file paths. A rotated token is picked up on the
next sync. Agents run the `t3 workflow` CLI only through that installer unless
explicitly directed by the operator to inspect or clear a blocked run.

If delivery stops with `unfinished runs would be interrupted by the reload: ...`
when nothing appears to be running, check for `paused` workflow runs. The
installer refuses changes whenever any row in T3's `workflow_runs` table has
`ended_at IS NULL`, which includes `paused` (and `waiting`) runs alongside
active `running` ones. A paused run looks idle in the T3 UI — for example, when
a workflow `callback` step into a busy or failing invoker thread fails twice and
pauses the run. On the blocked host, an operator (or an agent with operator
direction) can inspect and clear it before retrying `python3 scripts/maintain.py sync`:

```sh
t3 workflow list --status paused          # or `t3 workflow list` for all runs
t3 workflow show <run>                    # add `--json` for full step results
t3 workflow cancel <run> --reason "<why>" # ends the run (keeps step results and score history; loses resumability)
t3 workflow resume <run>                  # alternative: re-runs the failed step (delivery stays blocked until it finishes)
```

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
