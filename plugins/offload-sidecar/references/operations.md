# File operations

Prefer a deterministic operation when it expresses the transformation. Inspect the
`OPERATIONS` registry in `scripts/offload_sidecar.py` for operation names and parameters.
The engine also exposes its JSON tool schema over MCP `tools/list`.

Save an explicit request file, then pass its path to `scripts/process.py`:

```json
{"operation":"sort_lines","input_path":"input.txt","output_path":"sorted.txt"}
```

`filter_lines` requires `params.pattern`; `extract_fields` requires `params.fields`;
`split_file` requires `params.lines_per_chunk` or `params.num_chunks`. For example:

```json
{"operation":"filter_lines","input_path":"input.txt","output_path":"errors.txt","params":{"pattern":"ERROR"}}
```

Run from the intended project directory, or set `SIDECAR_ROOT` explicitly. Inputs and
outputs must satisfy the engine's containment checks. Use a new output path; inspect
the receipt and output before replacing important source data. The receipt records
engine, byte counts, output hash, and validation scope. A structural validator cannot
certify semantics, factual accuracy, or complete redaction.

Local model tiers `deep` and `fast` use `OLLAMA_HOST` and `OLLAMA_MODEL`; optional
`OLLAMA_FAST_HOST` / `OLLAMA_FAST_MODEL` select the second tier. Local failover stays
local. Cloud tiers `flash` and `pro` use `AGY_BIN` and configured model IDs. They retain
the upstream call-budget and lockout guards. A quota limit is not a monetary cap.
Inspect `status` before model work; it contacts configured Ollama endpoints. Cloud
tiers are reported from local quota state without contacting agy.

The one-shot adapter requires `allow_cloud: true` for cloud execution after the
operator authorizes sending that input. This receipt field is not a security boundary
against an untrusted caller. Direct MCP callers must enforce authorization themselves.
No model engine is needed for deterministic transforms. Never fabricate a model result
when an engine is unavailable.
