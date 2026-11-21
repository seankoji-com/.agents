# Run trigger evals

A manual check that a description selects its skill and loses near cases to the
right neighbour. Tests never call live models, so the owner runs this by hand.

1. **Choose the model.** Use the cheapest model the owner expects to run these
   skills, at its default effort. A description that works there works on
   stronger models.
2. **Prepare the host.** Install the whole library and the owner's usual
   plugins, so the skill list matches real use. Done when the skill under test
   appears in the host's skill list.
3. **Run each prompt.** Open a fresh session per prompt from
   `skills/<name>/references/trigger-evals.md`. Send the prompt alone. Record
   the first skill the model loads, or `none`.
4. **Score.**

   | Section | Pass |
   | --- | --- |
   | Should fire | The skill under test loads |
   | Should not fire | The `expect` skill loads, or nothing when it says `none` |

   Done when all 10 prompts have a recorded result.
5. **Act on misses.** For a should-fire miss, add the missing case to the
   description in the owner's words. For a should-not miss, add the boundary to
   whichever of the two descriptions owns the case. Rerun only the prompts the
   change could affect.
6. **Report.** Put the results in the change notes:

   ```text
   Trigger evals: <skill> on <model>, <date>
   Should fire: n/5 (misses: <prompt> -> <skill loaded>)
   Should not fire: n/5 (misses: <prompt> -> <skill loaded>)
   ```

Keep prompts synthetic. Never copy a real transcript, credential, hostname or
private path into an eval file.
