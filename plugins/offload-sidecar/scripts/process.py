#!/usr/bin/env python3
"""One-shot adapter for the sidecar, usable from every T3 provider's shell tool."""
import argparse
import json
import os
import sys
from pathlib import Path

from offload_sidecar import handle_process_local_file


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
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        # Copy before removing adapter-only consent. The engine never sees this field.
        consent = request.pop("allow_cloud", False)
        tier = request.get("tier")
        # Model-backed operations that default to cloud must also be explicitly opted in.
        from offload_sidecar import OPERATIONS
        operation = OPERATIONS.get(request.get("operation"), {})
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
