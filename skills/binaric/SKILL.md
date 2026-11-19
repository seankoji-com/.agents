---
name: binaric
description: "ONLY for LLM-to-LLM messages: delegate briefs, follow-ups and child reports, kept short with every fact the reader acts on. Never for anything a human is meant to read."
disable-model-invocation: true
---

# Binaric: LLM-to-LLM messages

Use this only when every intended reader is a model. If a human is meant to
read the text, use unslop instead. That includes text agents also read, such as
a README, docs, a PR, an issue, a report or the final user reply: humans win.
Decide per message, not per thread. One text gets one skill. Never apply
binaric and unslop to the same text.

Sender and receiver re-read each message on every later call, so every token
should carry a fact the reader acts on.

## Rules

0. **Contracts win.** Role cards, task contracts and required-field templates
   override this skill. Keep every field; write each tersely.
1. **BLUF.** Line one: verdict or state, revision, next action. Blockers next.
   Evidence last.
2. **Delta** only into a live context that holds the baseline, such as a
   running delegate; name the revision or IDs it amends. A fresh session,
   recheck or replacement gets a self-contained brief: authority, scope, exact
   base revision, numeric limits, criteria and the question.
3. **Once.** One final report through the host's native result channel.
   Interim notes only when the reader must act, the expected outcome changed, a
   decision is open or the workflow requires one.
4. **Pointer** to anything the reader can open, including other local
   worktrees. Inline the rest only if you may share it; otherwise say it
   exists and who can open it. Keep commands and error text needed to act inline.
5. **Load-bearing**, kept in full: authority and limits, scope, acceptance
   criteria, conditions and exceptions, exact identifiers, numbers, commands,
   error text, uncertainty and unverified status.
6. **Form.** Fragments, `key: value` lines and short lists. Content first: no
   greeting, restated request, hedges or process narration.
7. **Check.** From this message and what it points to, can the reader take the
   correct first action and produce every required report field?

## Reply contract

Children read a role card, not this skill. Judge the reply's audience by the
rule above: paste this block only when only models will read the reply. If a
person will read it, directly or relayed, omit it and say so in the brief.

```text
Reply terse for a model reader; if this brief says a person will read it,
write for people. Required fields and formats win. Otherwise line 1:
verdict/state, revision, next action; then blockers, results, evidence as
paths/IDs I can open. Keep exact commands, numbers, errors, unknowns. Skip
what this brief says. One final report.
```

Read [evidence](references/evidence.md) before estimating savings.
