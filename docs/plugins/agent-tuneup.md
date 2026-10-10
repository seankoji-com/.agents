# agent-tuneup

Inspect agent settings without weakening them.

## When to use it

Permission configuration needs an audit, exact duplicates need inspection, or Claude tool-call frequencies need analysis.

## Try it

```sh
t3-plugins install agent-tuneup
t3-plugins prompt agent-tuneup doctor
```

Paste the generated prompt into T3, then use an operation such as:

```text
Read ~/.local/share/t3-plugins/agent-tuneup/current/entry.md and run:
audit --provider claude --settings .claude/settings.json
```

Replace sample repositories, paths, and tasks with your own.

## Operations

`doctor`, `audit`, `scan`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/agent-tuneup/entry.md) routes each operation to its focused playbook.

## What you get

A read-only findings receipt and minimal proposed changes, with explicit parser and live-verification status.

## Limits

Calling provider and target configuration format are separate. Unsupported formats receive manual inspection, not guessed writes. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.

## Supported audit formats

| Adapter | Input | Scope |
| --- | --- | --- |
| Claude | JSON | Exact duplicate allow rules, known broad execution allows, bypass mode |
| OpenCode | JSON/JSONC | Global/tool wildcard allows |
| Codex | TOML, Python 3.11+ | Disabled approval/sandbox settings, including profiles |

These are known-pattern warnings, not a complete permission evaluator. Deny precedence, dynamic policies, host restrictions, and extension-specific semantics need contextual review.

Format references: [Claude permissions](https://code.claude.com/docs/en/permissions), [OpenCode permissions](https://opencode.ai/docs/permissions/), and [Codex configuration](https://developers.openai.com/codex/config-reference/).
