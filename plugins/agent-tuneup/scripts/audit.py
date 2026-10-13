#!/usr/bin/env python3
"""Read-only settings audit. Findings never include setting values or file contents."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ADAPTERS = {"claude": "JSON", "opencode": "JSON or JSONC", "codex": "TOML (Python 3.11+)", "muse": "JSON"}


def jsonc(text):
    """Remove comments and trailing commas while preserving JSON string contents."""
    tokens = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\n]*|/\*[\s\S]*?\*/')
    clean = tokens.sub(lambda m: m[0] if m[0].startswith('"') else ' ', text)
    return re.sub(r'"(?:[^"\\]|\\.)*"|,\s*(?=[}\]])',
                  lambda m: '' if m[0].startswith(',') else m[0], clean)


def inspect(provider, data):
    if not isinstance(data, dict):
        raise ValueError("settings must be an object")
    findings = []

    def add(code, location):
        findings.append({"code": code, "location": location})

    if provider == "claude":
        permissions = data.get("permissions", {})
        if not isinstance(permissions, dict):
            raise ValueError("permissions must be an object")
        rules = permissions.get("allow", [])
        if not isinstance(rules, list) or not all(isinstance(x, str) for x in rules):
            raise ValueError("permissions.allow must be an array of strings")
        seen = set()
        for index, rule in enumerate(rules):
            location = f"permissions.allow[{index}]"
            if rule in seen:
                add("duplicate_rule", location)
            seen.add(rule)
            if rule in {"*", "Bash", "Bash(*)", "mcp__*"} or re.fullmatch(
                r"Bash\((?:bash|sh|zsh|fish|python\d*|node|ruby|perl|php|lua|ssh|eval|exec)(?: |:)\*\)", rule
            ):
                add("broad_execution_allow", location)
        if permissions.get("defaultMode") == "bypassPermissions":
            add("permissions_bypassed", "permissions.defaultMode")
    elif provider == "codex":
        if data.get("approval_policy") == "never":
            add("approvals_disabled", "approval_policy")
        if data.get("sandbox_mode") == "danger-full-access":
            add("sandbox_disabled", "sandbox_mode")
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("profiles must be a table")
        # Deliberately omit user-chosen profile names from receipts.
        for index, profile in enumerate(profiles.values()):
            if not isinstance(profile, dict):
                raise ValueError("profile must be a table")
            for finding in inspect(provider, {k: v for k, v in profile.items() if k != "profiles"}):
                add(finding["code"], f"profiles[{index}].{finding['location']}")
    elif provider == "opencode":
        permission = data.get("permission", {})
        if permission == "allow":
            add("all_tools_allowed", "permission")
        elif isinstance(permission, dict):
            if permission.get("*") == "allow":
                add("all_tools_allowed", "permission.*")
            for key in ("bash", "external_directory"):
                value = permission.get(key)
                if value == "allow" or isinstance(value, dict) and value.get("*") == "allow":
                    add("broad_tool_allow", f"permission.{key}")
        elif permission not in ("ask", "deny"):
            raise ValueError("permission must be an object or allow/ask/deny")
    elif provider == "muse":
        # Muse's flat settings.json carries named permission profiles under
        # `permissions.profiles`; each profile states approval, filesystem,
        # network and reviewer dimensions (verified against Muse 1.4.7).
        # Profile names are operator-chosen: locations use the index only.
        permissions = data.get("permissions", {})
        if not isinstance(permissions, dict):
            raise ValueError("permissions must be an object")
        profiles = permissions.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("permissions.profiles must be an object")
        for index, profile in enumerate(profiles.values()):
            if not isinstance(profile, dict):
                raise ValueError("permission profile must be an object")
            base = f"permissions.profiles[{index}]"
            for key in ("approval", "reviewer", "extends"):
                if key in profile and not isinstance(profile[key], str):
                    raise ValueError(f"{key} must be a string")
            if "filesystem" in profile and not isinstance(profile["filesystem"], (str, dict)):
                raise ValueError("filesystem must be a string or an object")
            if "network" in profile and not isinstance(profile["network"], dict):
                raise ValueError("network must be an object")
            if profile.get("approval") == "allow_all":
                add("approvals_disabled", f"{base}.approval")
            if profile.get("filesystem") == "unrestricted":
                add("sandbox_disabled", f"{base}.filesystem")
            network = profile.get("network", {})
            if "mode" in network and not isinstance(network["mode"], str):
                raise ValueError("network.mode must be a string")
            if network.get("mode") == "enabled":
                add("network_unrestricted", f"{base}.network.mode")
    else:
        raise ValueError("unsupported adapter")
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-adapters", action="store_true")
    parser.add_argument("--provider", choices=sorted(ADAPTERS))
    parser.add_argument("--settings", type=Path)
    args = parser.parse_args(argv)
    if args.list_adapters:
        print(json.dumps(ADAPTERS))
        return 0
    if not args.provider or args.settings is None:
        parser.error("--provider and --settings are required")
    if args.provider == "codex":
        # Checked before the parse so a too-old interpreter is reported as such, not
        # folded into the redacted "unreadable or invalid settings" receipt.
        try:
            import tomllib
        except ImportError:
            print(json.dumps({"ok": False, "error": "python_3_11_required", "provider": args.provider,
                              "message": "Codex TOML audit requires Python 3.11+ (tomllib); "
                                         f"running {sys.version_info[0]}.{sys.version_info[1]}"}))
            return 2
    try:
        text = args.settings.expanduser().read_text(encoding="utf-8")
        if args.provider == "codex":
            data = tomllib.loads(text)
        else:
            data = json.loads(jsonc(text) if args.provider == "opencode" else text)
        findings = inspect(args.provider, data)
    except (OSError, ValueError):
        # Parser exceptions can include source values. Keep the failure receipt redacted.
        print(json.dumps({"ok": False, "error": "settings_unreadable_or_invalid", "provider": args.provider}))
        return 2
    print(json.dumps({"ok": True, "provider": args.provider, "findings": findings,
                      "scope": "known-pattern audit; not a complete permission evaluation", "writes": 0}))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
