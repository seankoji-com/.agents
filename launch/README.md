# Launch kit

Drafts for announcing t3-plugins. Nothing here posts itself. Edit freely, post
from your own accounts, and delete this directory once the posts are out if you
would rather not keep marketing copy in the tree.

## Repository settings

Run once from a machine with `gh` authenticated as a repository admin:

```sh
gh repo edit seankoji-com/t3-plugins \
  --description "Seven agent workflows for T3 Code that keep working when you change the model. Python stdlib, evidence before completion, live provider results recorded." \
  --homepage "https://seankoji-com.github.io/t3-plugins/" \
  --add-topic t3-code --add-topic ai-agents --add-topic developer-tools \
  --add-topic agent-workflows --add-topic python --add-topic mkdocs-material \
  --add-topic claude --add-topic codex --add-topic homebrew
```

Then upload `docs/assets/social-card.png` as the social preview under
Settings → General → Social preview. GitHub has no API for that field.

## Show HN

Title (80 characters max):

```
Show HN: t3-plugins – agent workflows for T3 Code that survive a model change
```

Body:

```
I maintain a set of coding-agent workflows (plan a change, research an approach,
implement with evidence, babysit the PR) that I originally wrote for Claude Code.
When T3 Code added cross-provider orchestration I ported them so the same
instructions run on Codex, Claude, Gemini, or whatever provider the thread has
selected.

The part I'd like feedback on is the evidence model. imps, the implementation
workflow, ties every test log and review verdict to the repository revision it
was gathered on. An edit after verification makes the verification stale; the
agent has to re-run, it can't re-label. That one rule removed a whole class of
"tests pass" claims that were true a commit ago.

Everything deterministic is Python standard library with tests. The provider side
is a live conformance ledger rather than a logo wall: per-provider pass counts,
the two defects the matrix found, and the transcripts.

Docs: https://seankoji-com.github.io/t3-plugins/
Why it's built this way: https://seankoji-com.github.io/t3-plugins/case-study/
Source: https://github.com/seankoji-com/t3-plugins
```

## T3 Code community (Discord)

```
Built a plugin catalog for T3's cross-provider orchestration and would love
people to kick the tyres: https://seankoji-com.github.io/t3-plugins/

Seven workflows (imps for implementing with evidence, babysitter for PRs,
elephant-goldfish for planning, ape for researching other codebases, and a few
helpers). They're plain Markdown entries plus stdlib Python, so they inherit
whatever provider the thread is on and delegate children through delegate_task.

Honest status: imps has live results for Codex, Claude and Antigravity on the
0.0.46 nightly; the ledger lists what failed too. Install is
`brew install seankoji-com/tap/t3-plugins`. Bug reports very welcome.
```

## LinkedIn

```
I shipped t3-plugins: seven agent workflows for T3 Code that keep working when
you change the model.

The idea is simple. A development workflow is mostly instructions and checks,
and both get rebuilt every time a team switches providers. So I split each
workflow into three parts that can be inspected separately: instructions the
agent reads, small local tools in the Python standard library, and host
orchestration that T3 owns. No provider SDK, no fixed model IDs.

The part I'm proudest of is the evidence rule in the implementation workflow:
every check is tied to the revision it ran on, so an edit after verification
makes the verification stale. The agent re-runs; it can't re-label.

I also ran a live conformance matrix across providers and published the ledger,
including the two defects it found in my own briefs and the infrastructure
failures it hit. If you're evaluating agent tooling, I'd rather you read that
page than the feature list.

Docs and case study: https://seankoji-com.github.io/t3-plugins/
```

## seankoji.com post

Suggested title: "What survives a model change". Reuse the case study page as the
body (`docs/case-study.md`), adding a short intro paragraph in your own voice and
an embedded copy of `docs/assets/demo.svg`. The page is already written in first
person and licensed MIT, so it can be republished as is.
