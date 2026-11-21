---
name: new-skill
description: "Add a skill to this library with a description agents can match, steps a small model can follow, trigger evals and full registration."
disable-model-invocation: true
---

# Add a skill to this library

Read [writing-for-agents](https://github.com/mattpocock/skills/tree/main/skills/productivity/writing-for-agents)
before drafting the body. It covers trigger wording, disclosure, completion
conditions and no-ops. This skill covers what it leaves out: the description
contract that `scripts/check_library.py` enforces, trigger evals and this
repository's registration steps.

Input: what the skill should do, in the owner's words. If it is missing, ask for
it and stop.

## Steps

1. **Check neighbours.** List every description with
   `grep -H -m2 -E '^(name|description):' skills/*/SKILL.md` and read the host's
   skill list for built-in and plugin skills. If one already covers the request,
   name it, propose extending it and stop. Done when every skill whose cases
   overlap is named.
2. **List the cases.** Write each distinct situation the skill handles as a
   phrase the owner would type. Merge phrases that rename one case. Done when
   each case takes a different path through the body.
3. **Choose the invocation.** Make the skill model-invoked only when an agent or
   another skill must reach it unprompted. Otherwise set
   `disable-model-invocation: true` (Claude Code) and add `agents/openai.yaml`
   with `policy.allow_implicit_invocation: false` (Codex), as this skill does.
4. **Name it.** Lowercase letters, digits and hyphens, matching the folder. Use a
   word the owner already types, different from every existing and built-in name.
5. **Write the description.** Use this shape:

   ```text
   <Verb> <what it produces>. Use when <case>, <case> or <case>. <Which neighbour wins a near case.>
   ```

   The checker fails a description over 40 words or 250 characters, one that
   says "I", "you", "your", "this skill" or "then" outside quotes, and a
   model-invoked one without a `Use when/for/at` or `when asked/the user`
   clause. Keep the procedure, and rules that matter only after selection, in
   the body: an agent that reads steps in the description can run them and
   skip the body.
6. **Write the body.** Stay under 1,500 words. In order:

   | Part | Rule |
   | --- | --- |
   | Inputs | What must exist first, and what to do if it is missing |
   | Steps | Numbered, one action each, each ending on a checkable done condition |
   | Branches | A table instead of nested "if" prose |
   | Exits | "If X is unavailable, report Y and stop" |
   | Output | An exact template |

   Move exact or fragile work into a stdlib Python helper with `--help`, and
   tell the agent to run it. Put material only some cases need in
   `references/`, one level deep. Write each local link in a sentence that says
   when to read it, using a word such as when, before, after, if or for.
7. **Write trigger evals** if the skill is model-invoked. Create
   `references/trigger-evals.md` in the shape of
   `skills/think/references/trigger-evals.md`: 5 should-fire prompts and 5
   should-not-fire prompts. Take the should-not prompts from the neighbours in
   step 1 and end each with `(expect: <skill|none>)`.
8. **Register.**
   - Add the name to `SKILLS` in `scripts/check_library.py`.
   - Add a row to `site/index.html` with its Source link, install command and
     one host-support tier chip.
   - Change `site/workflows.html` only if the skill joins a documented workflow.
   - Review the README and site diagrams, then run
     `python3 -B scripts/check_library.py --update-readme --acknowledge-docs`.
9. **Check.** Run `python3 scripts/check_library.py`,
   `python3 -m unittest discover -s tests -v` and
   `python3 scripts/check_library.py --stats`. Run any new helper from a foreign
   working directory. Done when all pass.
10. **Offer the trigger evals.** When the owner wants evidence that the
    description selects well, follow
    [the trigger-eval procedure](references/run-trigger-evals.md). Run it after
    any later description change too.

## Output

```text
Skill: <name> (<model-invoked|user-invoked>)
Description: <text> (<words> words)
Neighbours checked: <names>
Files: <paths>
Checks: check_library <pass|fail>, unittest <pass|fail>, entry <words> words
Trigger evals: <not run | n of 10 matched; misses listed>
```
