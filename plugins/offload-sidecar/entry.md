# offload-sidecar

Process files by path and receive a small receipt instead of filling the main context
with their contents. Read `PKG/shared/t3-runtime.md`, then `PKG/references/operations.md`.

- `process <request.json>`: run `python3 PKG/scripts/process.py <request.json>`.
- `serve`: start `python3 PKG/scripts/offload_sidecar.py` only when explicitly asked
  to run an MCP stdio server. T3's shell path works without registering an MCP server.
- `doctor`: run `python3 PKG/scripts/process.py --doctor` for local prerequisites.
- `status`: run `python3 PKG/scripts/offload_sidecar.py status` to probe configured Ollama endpoints and report cloud quota state without cloud calls.

Deterministic operations need only Python. Model operations use explicitly configured
Ollama or agy engines, independent of the provider running the T3 thread. Cloud calls
send file contents externally and require authorization; do not infer it from install.
