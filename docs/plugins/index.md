# Choose a plugin

Start with a concrete job. A short shell command or direct agent request is often enough; use a workflow when its checks or saved artifacts help.

| Plugin | Use it for |
| --- | --- |
| [imps](imps.md) | Implement with revision-bound evidence |
| [elephant-goldfish](elephant-goldfish.md) | Prepare a brief that a fresh session can use |
| [ape](ape.md) | Find ideas that transfer to your project |
| [babysitter](babysitter.md) | Carry pull requests through review and CI |
| [agent-tuneup](agent-tuneup.md) | Align agent settings with reviewed provider-specific changes |

All entries can be read by any T3 provider with filesystem access. That is a portability contract, not a completed live conformance matrix. See [compatibility](../compatibility.md).

## Not sure where to start?

- Know the bug and expected behavior? Start with **imps**.
- Still deciding what should change? Start with **elephant-goldfish**, then hand its brief to imps.
- Need evidence from another codebase? Use **ape** before committing to an approach.
- Already have a PR? Give **babysitter** its URL and the actions you authorize.
- Comparing provider permissions, MCPs or plugins? Use **agent-tuneup** with `align`.

Every workflow has a `doctor` operation. [Install once](../getting-started.md), then
use the T3 skill picker or [generate a prompt](../cli.md#catalog-commands).
