# elephant-goldfish

Prepare a brief that a fresh session can use.

## When to use it

The problem is still uncertain, or an existing design document needs factual and cold-reader checks.

## Try it

```sh
t3-plugins install elephant-goldfish
t3-plugins prompt elephant-goldfish doctor
```

Paste the generated prompt into T3, then use an operation such as:

```text
Read ~/.local/share/t3-plugins/elephant-goldfish/current/entry.md and run:
thinking retry-policy
```

Replace sample repositories, paths, and tasks with your own.

## Operations

`doctor`, `thinking`, `elephant`, `check`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/elephant-goldfish/entry.md) routes each operation to its focused playbook.

## What you get

Discovery, a testable specification, and a deterministically rendered handoff with hashes.

## Limits

Thinking stops at the handoff. A cold-reader pass establishes readability and completeness, not factual correctness. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
