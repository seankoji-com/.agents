# elephant-goldfish

Prepare a brief that a fresh session can use.

## When to use it

You know something needs improving but cannot yet give an implementation agent a
clear task. It also checks whether an existing design document is still accurate.

## Try it

After [installation](../getting-started.md), run in your terminal:

```sh
t3-plugins prompt elephant-goldfish doctor
```

Paste the printed line into a T3 thread attached to your project. Once readiness is
clear, generate a task prompt:

```sh
t3-plugins prompt elephant-goldfish thinking retry-policy
```

Paste that output into T3. Replace the sample task or path with your own.
If you installed [skill adapters](../slash-commands.md), select **t3-elephant-goldfish**
from `/` and append the same request instead.

## Operations

`doctor`, `thinking`, `elephant`, `check`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/elephant-goldfish/entry.md) names the file to load for each operation.

## What you get

Local `thinking/<topic>/discovery.md`, `spec.md`, `handoff.md` and a provenance
manifest. Discovery records decisions and unknowns; the specification gives stable
requirement IDs and observable acceptance criteria. The handoff copies the source
verbatim with hashes. Give it to a fresh thread when you are ready to implement.

## Limits

Thinking stops at the handoff. A cold-reader pass establishes readability and completeness, not factual correctness. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.

## Continue planning

Use `thinking retry-policy` again to resume the same topic, or `thinking list` to
inspect saved topics. `elephant` checks a durable design document against repository
facts and runs a separate cold-reader review; `check` runs the factual drift check.
A readable brief can still be factually wrong, so those verdicts stay separate.
GitHub publication is optional and requires explicit authorization.
