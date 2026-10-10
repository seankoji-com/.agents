# prompt-builder

Build a reusable prompt and test it.

## When to use it

A repeated task needs a prompt with explicit inputs, output rules, and regression cases.

## Try it

```sh
t3-plugins install prompt-builder
t3-plugins prompt prompt-builder doctor
```

Paste the generated prompt into T3, then use an operation such as:

```text
Read ~/.local/share/t3-plugins/prompt-builder/current/entry.md and run:
build classify support requests into billing, technical, or account categories
```

Replace sample repositories, paths, and tasks with your own.

## Operations

`doctor`, `build`, `brief-only`, `evaluate`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/prompt-builder/entry.md) names the file to load for each operation.

## What you get

The exact prompt, variable definitions, frozen cases, and measured results when execution was available.

## Limits

The local evaluator checks transcribed outputs. It does not authenticate that a model ran or certify subjective quality. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
