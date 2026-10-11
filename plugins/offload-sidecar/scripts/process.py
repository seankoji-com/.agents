#!/usr/bin/env python3
"""One-shot adapter for the sidecar, usable from every T3 provider's shell tool."""
import argparse
import json
import os
import sys
from pathlib import Path

# Under `python3 -I` the script directory is not on sys.path, so the sibling engine
# module must be located explicitly. Inserted at the front so no other `offload_sidecar`
# on the path can shadow the one shipped beside this adapter.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from offload_sidecar import OPERATIONS, OPERATION_ALIASES, handle_process_local_file  # noqa: E402


def validate_request(request):
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    for key in ("operation", "input_path", "output_path", "instruction", "tier"):
        if key in request and not isinstance(request[key], str):
            raise ValueError(f"{key} must be a string")
    for key in ("overwrite", "allow_cloud"):
        if key in request and not isinstance(request[key], bool):
            raise ValueError(f"{key} must be a boolean")
    if "params" in request and not isinstance(request["params"], dict):
        raise ValueError("params must be an object")
    if "input_paths" in request and (not isinstance(request["input_paths"], list)
                                    or not all(isinstance(p, str) for p in request["input_paths"])):
        raise ValueError("input_paths must be an array of strings")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", type=Path)
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args(argv)
    if args.doctor:
        print(json.dumps({"ok": True, "python": list(sys.version_info[:3]),
                          "deterministic": True, "model_engines": "not_probed"}))
        return 0
    if args.request is None:
        parser.error("request JSON path required")
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        validate_request(request)
        # Copy before removing adapter-only consent. The engine never sees this field.
        consent = request.pop("allow_cloud", False)
        tier = request.get("tier")
        # Model-backed operations that default to cloud must also be explicitly opted in.
        name = request.get("operation")
        operation = OPERATIONS.get(OPERATION_ALIASES.get(name, name), {})
        selected_tier = tier or operation.get("default_tier", "deep")
        if selected_tier in ("flash", "pro") and consent is not True:
            raise ValueError("cloud tier requires allow_cloud=true after operator authorization")
        os.environ.setdefault("SIDECAR_ROOT", str(Path.cwd()))
        result = handle_process_local_file(request)
    except (OSError, ValueError, TypeError) as exc:
        result = {"status": "error", "reason": str(exc)}
    print(json.dumps(result))
    return 0 if result.get("status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
