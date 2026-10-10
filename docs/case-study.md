---
description: "Why t3-plugins is built the way it is: the three decisions behind it, what the live conformance matrix broke, and what the author would do differently."
---

# Why it is built this way

I wrote these plugins for Claude Code first. When T3 Code added cross-provider
orchestration, I had a choice: port seven workflows by hand to each provider's
extension format, or find the shape that survives a model change. This page is the
reasoning behind the second option, written for anyone deciding whether the same
constraints apply to their own agent tooling.

## The problem in one sentence

A development workflow is mostly instructions and checks, and both get rebuilt every
time the team switches models. The instructions get rewritten because each provider
has its own packaging. The checks get skipped because nobody wants to port them. The
result is that the most expensive part of agent adoption, the part that encodes how
your team works, is the part with the shortest shelf life.

## Three decisions

### 1. Split instructions, tools, and host orchestration, and keep them apart

A plugin here is three things with a hard boundary between them. The entry is a
Markdown file under 1,500 words that the agent reads and that routes to one playbook.
The tools are Python scripts that use only the standard library. The orchestration,
meaning child tasks, previews, and pull-request watches, belongs to T3 and is
discovered through its live tool schemas rather than compiled in.

The boundary matters more than any single piece. Instructions can be read by any
model with a filesystem. Tools can be tested without a model at all. Host features
can change under us without a release, because nothing in the repository hard-codes
a tool signature or a model ID. The cost is that the repository will never feel like
a single integrated product; it feels like a catalog, because it is one.

### 2. Tie evidence to the revision that produced it

The imps workflow has a small state engine with three rules. A claim token names the
single owner of a run. A generation counter refuses writes from anyone holding a stale
view. And every piece of evidence, whether a test log, a review verdict, or an
acceptance check, is recorded against the repository snapshot it was gathered on.

The last rule is the one I would defend hardest. Agents are very good at saying
"tests pass" after a change that happened after the tests ran. With evidence bound to
a revision, an edit after verification makes the verification stale. The agent has to
re-verify. It cannot re-label. In the live runs no repeat reported a false completion;
the repeats that blocked did so because the core refused a claim. That is the reason
the report can say `completed` and mean it.

### 3. Discover providers, do not enumerate them

Nothing in the catalog knows what a "reviewer" model is. Roles are resolved against
T3's live capability list at run time, and a provider that is disabled, uninstalled,
or unauthenticated shows up as exactly that in the `doctor` report. No model ID is
compiled into the catalog or the core: imps roles resolve as `inherit`, `catalog`, or
`same_provider`, and model names appear only as recorded observations in test
fixtures and the conformance ledger.

This is the decision that makes the "provider-neutral" claim honest. It also means the
catalog cannot promise that every model behaves the same. It can only record what
happened when a specific provider ran a specific case, which brings me to the
part that went wrong.

## What the live matrix broke

Unit tests prove that the helpers and the state engine behave. They cannot prove that
a model follows a playbook. So I ran a live conformance matrix: one top-level T3
thread per provider, a plan of three repeats per critical case from a fresh clone,
every transcript committed to the repository. The ledger records where that plan was
not reached and why.

[The sightings page](sightings.md) has the numbers. Two providers completed every
repeat of the bug-fix and missing-capability cases. Two things broke, and both were
my defects, not the models':

- **A review brief showed a `changed_files` example.** A Codex reviewer, asked only to read, dutifully listed the files it had read as changed. The core rejected the claim and blocked the run instead of accepting a false result, which is the behavior I wanted, but two Antigravity repeats blocked on it. Read-only briefs now show an empty list, and a stray list gets one correction round.
- **A child cited a relative evidence path.** Children inherit the thread's scratch directory, not the clone, so the path did not resolve. Briefs now require absolute evidence paths, and a path that does not resolve gets one correction round.

Both fixes have regression tests. Both would have been invisible without the matrix.
The matrix also found infrastructure limits that are recorded rather than hidden:
the Codex driver went down halfway through, and OpenCode never opened a parent
session in that build. The ledger says so, with timestamps.

## What I would do differently

The core's JSON schema validator is hand-rolled to keep the standard-library rule.
It is tested against fixture files, but a dependency would have been safer and I
would accept that trade today for the validator alone.

The conformance matrix should run on a schedule against T3 nightlies instead of once
before a release. The procedure is documented and the collector is a script, so the
missing piece is a runner with provider credentials, which is a budget question
rather than a design one.

## Where to look

- The install path and ownership rules: `scripts/install.py` and [installation](getting-started.md).
- The state engine: `core/` and [architecture](architecture.md).
- The evidence that the matrix produced: `conformance/` and [sightings](sightings.md).
- The tests, including the ones for failure paths: [testing](testing.md).
- The design notes the port started from: `thinking/imps-t3/`, and the pre-merge review rounds under `conformance/review/`.

If you read one file, read `plugins/imps/entry.md`. It is the whole contract between
the agent and the engine, and it stays under 1,500 words by test.
