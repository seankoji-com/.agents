---
name: agent-docs
description: "Use when creating, editing or auditing a skill, AGENTS.md, CLAUDE.md or a doc they point to."
---

# Write agent docs

An agent doc is persistent text an agent reads to decide what to do: a skill, an
`AGENTS.md` or `CLAUDE.md`, the source a generated copy comes from, or a file one
of these points to. Delegation briefs and chat prompts are out of scope. The goal
is that every run takes the same path through the doc and that each always-loaded
word earns its place.

## Rules

1. **Pointers.** A skill description or a line naming another file decides when
   the agent reads that material. Say what it is, then list each distinct case
   that should trigger it, leading with the word users actually type. Collapse
   synonyms for one case. Make a skill model-invoked only when an agent or
   another skill must reach it unprompted; otherwise set
   `disable-model-invocation: true` and keep the description human-facing.
2. **Layout.** Put the ordered steps first. Keep in the file what every path
   needs; move material that only some paths need into a sibling file, behind a
   pointer that says when to read it. Keep a concept's rule, reason and caveat
   under one heading.
3. **Completion.** End each step on a condition the agent can check, and make it
   exhaustive where coverage matters: "every changed model listed" rather than
   "list the changes".
4. **One home per rule.** State each rule once and point to it elsewhere. Leave
   out what the environment already says (scripts, config, directory layout,
   `--help`); record what a lookup cannot find, such as conventions, reasons and
   gotchas. For a generated file, edit its source.
5. **No-ops.** Delete any sentence the model already follows by default. A line
   is a no-op only if it changes nothing on every model family that reads the
   doc. Delete the whole sentence rather than trimming it.
6. **Wording.** State the target behavior. Keep prohibitions for hard guardrails
   and pair each with what to do instead. Use calm, specific wording; capitals,
   "CRITICAL" and intensifiers make current models over-apply a rule. Pick one
   term per concept and repeat it.

## Draft or edit

Apply the rules to the doc being written or changed. Keep the repository's own
limits and checks, such as word caps and metadata validation, and run them.
Done when each rule has been applied to every changed line and the repository
checks pass. A/B runs are not required here.

## Audit

Use when asked to audit, prune or trim agent docs.

1. **Inventory.** List every always-loaded item in scope: skill descriptions and
   instruction files loaded each session. Record word counts with a
   deterministic tool. Done when every in-scope file has a count.
2. **Classify.** Read each line once against the rules. Mark it keep, or record
   a finding: no-op, duplicate (name the one home), stale (the behavior or
   environment changed), misplaced (belongs behind a pointer), weak trigger or
   vague completion. Done when every line is marked.
3. **Test.** Follow the [A/B procedure](references/ab-test.md) for each finding
   that would remove a rule, reword a description or change a completion
   condition. Duplicate removal and pure moves skip it. Done when every such
   finding has a result or a stated gap.
4. **Report.** Give a table of file and line, finding, proposed edit and
   evidence, then always-loaded words before and after. Apply edits only within
   granted authority, and only those whose A/B result held.

In T3 Code, use `html_preview` then `html_render` for the audit report; use
readable text elsewhere.

## Boundaries

An audit authorizes reading and proposing. Model runs, edits, commits and
changes in another repository each need authority from the request or standing
instructions. Edit generated files only through their owner's tooling.
