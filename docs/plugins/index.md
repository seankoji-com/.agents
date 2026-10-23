# Choose a workflow

Start from the job you need done. For a quick edit, ask the agent directly; reach for a
workflow when you want its checks or the files it leaves behind.

| You have… | Use | Send in T3 |
| --- | --- | --- |
| A bug you can describe, or a small feature with a clear finish line | [imps](imps.md) | `$t3-imps run …` |
| A problem you can't yet write as a task | [plan](plan.md) | `$t3-plan TOPIC` |
| A gap another project has probably solved | [ape](ape.md) | `$t3-ape URL QUESTION` |
| A PR stuck on reviews, checks or conflicts | [babysitter](babysitter.md) | `$t3-babysitter pr URL` |
| Providers with different permissions, MCPs or plugins | [agent-tuneup](agent-tuneup.md) | `$t3-agent-tuneup` |
| A goal you want built by one model and graded by another | [ralph](ralph.md) | `$t3-ralph GOAL` |
| A product or prototype you want tested by a panel of invented personas | [focus-group](focus-group.md) | `$t3-focus-group plan URL` |
| An upstream project or service that appears broken | [bug-report](bug-report.md) | `$t3-bug-report describe the error` |

Common chains: plan writes the brief, then imps or ralph implements it.
ape finds the approach before you commit to one. babysitter takes over once a PR
exists.

Plan, ape and agent-tuneup choose their normal workflow automatically. Use the
catalog's `t3-plugins doctor` for installed-package diagnostics.
The first five run long work as one job: your thread keeps the plan and accepts each
stage, while fresh T3 tasks do the stage work. See
[architecture](../architecture.md#whole-jobs).

Any T3 provider with file access can read the entries. That's a portability design,
not a finished live test across providers; [compatibility](../compatibility.md) has
the details. No slash menu? [Generate a prompt](../cli.md#catalog-commands) instead.

Shared jobs record host execution identity. Document workflows also track author
lineage by document hash. A first author record cannot identify earlier authors of an
unrecorded document, and a direct cold-read stage cannot fall back to the coordinator.
