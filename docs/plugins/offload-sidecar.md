# offload-sidecar

Transform files without filling the main context.

## When to use it

A fixed operation can process a large file locally, or an explicitly authorized external engine can handle irregular input.

## Try it

```sh
t3-plugins install offload-sidecar
t3-plugins prompt offload-sidecar doctor
```

Paste the generated prompt into T3, then use an operation such as:

```text
Read ~/.local/share/t3-plugins/offload-sidecar/current/entry.md and run:
process request.json
```

Replace sample repositories, paths, and tasks with your own.

## Operations

`doctor`, `process`, `serve`, `status`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/offload-sidecar/entry.md) routes each operation to its focused playbook.

## What you get

Output files and a small receipt with engine, byte counts, validation scope, and output hashes.

## Limits

Deterministic processing needs only Python. Local model tiers need Ollama; cloud tiers need agy and authorization to transmit input. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.

## Request format

```json
{"operation":"sort_lines","input_path":"input.txt","output_path":"sorted.txt"}
```

Run from the project directory. [Try the deterministic example](../first-workflow.md#a-model-free-first-result). The [operation reference](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/offload-sidecar/references/operations.md) explains engine configuration and cloud consent.
