# agent-tuneup

Inspect agent settings without weakening them.

## When to use it

You want to inspect permission rules before changing them, find exact duplicates,
or understand which tools a Claude session used. Supply the settings path and its
format explicitly; the provider running the audit may be different.

## Try it

After [installation](../getting-started.md), run in your terminal:

```sh
t3-plugins prompt agent-tuneup doctor
```

Paste the printed line into a T3 thread attached to your project. Once readiness is
clear, generate a task prompt:

```sh
t3-plugins prompt agent-tuneup audit --provider claude --settings .claude/settings.json
```

Paste that output into T3. Replace the sample task or path with your own.
If you installed [skill adapters](../slash-commands.md), select **t3-agent-tuneup**
from `/` and append the same request instead.

## Operations

`doctor`, `audit`, `scan`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/agent-tuneup/entry.md) names the file to load for each operation.

## What you get

A read-only JSON findings receipt with codes and locations, plus minimal proposed
changes and parser limitations. Setting values stay out of the receipt. A finding
is a known pattern worth inspecting, not proof that a tool is allowed after every
policy layer has been applied.

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

## Run without a model

Create a synthetic settings file and audit it using the installed helper:

```sh
printf '%s\n' '{"permissions":{"allow":["Bash(*)"]}}' > example-settings.json
entry="$(t3-plugins path agent-tuneup)"
python3 "$(dirname "$entry")/scripts/audit.py" \
  --provider claude --settings example-settings.json
```

Expect a finding for the broad Bash rule and exit `1`. Exit `0` means no known
findings; `2` means unreadable or invalid input. The helper does not change the
settings file. Use `--list-adapters` to inspect supported formats.

`scan --provider claude` reads recent local transcript tool-call frequencies. Those
counts do not authorize permission changes. Do not share private transcripts.
