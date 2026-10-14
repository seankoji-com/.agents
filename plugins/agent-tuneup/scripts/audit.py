#!/usr/bin/env python3
"""Read-only settings audit. Findings never include setting values or file contents."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
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


# Root-level lockfiles that mean a new worktree needs an install before work starts.
# uv.lock counts only when tracked, like every other entry here.
LOCKFILES = {"pnpm-lock.yaml": "js", "package-lock.json": "js", "bun.lock": "js",
             "uv.lock": "python", "go.mod": "go"}
SETUP_COMMAND = 'node "$HOME/.local/bin/t3-setup-worktree.mjs"'
IMPORT_NOTE = ("T3 runs the project's saved scripts. Import t3.json scripts in Settings -> project -> Actions, "
               "or pass the existing saved scripts plus the new one to t3_project_update.")


def tracked_lockfiles(root):
    """Tracked root-level lockfiles, read without taking git's optional locks."""
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", *sorted(LOCKFILES)],
                            capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    if result.returncode:
        raise OSError("git ls-files failed")
    return sorted(name for name in result.stdout.split("\0") if name in LOCKFILES)


def read_project_file(root):
    """Return (status, data) for the project's t3.json without echoing its contents."""
    path = root / "t3.json"
    if not path.is_file():
        return "absent", {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("scripts", []), list):
        raise ValueError("t3.json must be an object with a scripts array")
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", "t3.json"],
                            capture_output=True, timeout=30, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    return ("tracked" if listed.returncode == 0 else "untracked"), data


def has_setup_script(scripts):
    return any(isinstance(script, dict) and script.get("runOnWorktreeCreate") is True for script in scripts)


def bootstrap_draft(lockfiles, saved):
    """A reviewable proposal. Go module downloads can run beside the agent; JS and
    Python tests need installed dependencies before the first command. The saved
    script id avoids every id the project already uses."""
    script = {"name": "Setup Worktree", "command": SETUP_COMMAND, "icon": "configure",
              "runOnWorktreeCreate": True,
              "async": all(LOCKFILES[name] == "go" for name in lockfiles)}
    used = {item.get("id") for item in saved if isinstance(item, dict)}
    script_id, suffix = "setup-worktree", 2
    while script_id in used:
        script_id, suffix = f"setup-worktree-{suffix}", suffix + 1
    return {"scripts": [script]}, dict(script, id=script_id)


def inspect_projects(snapshot):
    """Flag projects whose new worktrees start without dependencies.

    `snapshot` holds T3's own tool responses: `environment` from t3_environment_read
    and `projects` from t3_project_list or t3_project_read. Thread mode resolves as
    project override, then environment preference, then t3.json.
    """
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("projects"), list):
        raise ValueError("snapshot must be an object with a projects array")
    environment = snapshot.get("environment", {})
    if not isinstance(environment, dict) or not isinstance(environment.get("preferences", {}), dict):
        raise ValueError("environment must be an object")
    environment_mode = environment.get("preferences", {}).get("defaultThreadEnvMode")
    findings, unchecked = [], []
    for index, project in enumerate(snapshot["projects"]):
        if not isinstance(project, dict):
            raise ValueError("project must be an object")
        location = f"projects[{index}]"
        saved = project.get("scripts")
        saved = [] if saved is None else saved
        if not isinstance(saved, list):
            raise ValueError("project scripts must be an array")
        if project.get("deletedAt"):
            continue
        root = project.get("workspaceRoot")
        if not isinstance(root, str) or not os.path.isabs(root) or not Path(root).is_dir():
            unchecked.append({"location": location, "reason": "workspace_unavailable"})
            continue
        root = Path(root)
        try:
            lockfiles = tracked_lockfiles(root)
            file_status, project_file = read_project_file(root)
        except (OSError, ValueError, subprocess.SubprocessError):
            unchecked.append({"location": location, "reason": "workspace_unreadable"})
            continue
        for source, mode in (("project", project.get("defaultThreadEnvMode")),
                             ("environment", environment_mode),
                             ("t3.json", project_file.get("defaultThreadEnvMode"))):
            if mode:
                break
        else:
            source, mode = "unset", None
        if mode != "worktree" or not lockfiles or has_setup_script(saved):
            continue
        finding = {"location": location, "project_id": project.get("id"), "mode_source": source,
                   "lockfiles": lockfiles, "t3_json": file_status, "import": IMPORT_NOTE}
        if has_setup_script(project_file.get("scripts", [])):
            # The repository already declares a setup script; it only needs importing.
            findings.append({"code": "worktree-bootstrap-not-imported", **finding})
            continue
        draft, saved_script = bootstrap_draft(lockfiles, saved)
        findings.append({"code": "worktree-bootstrap-missing", **finding, "draft_t3_json": draft,
                         "draft_saved_script": saved_script})
    return findings, unchecked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-adapters", action="store_true")
    parser.add_argument("--provider", choices=sorted(ADAPTERS))
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--t3-projects", type=Path, metavar="SNAPSHOT",
                        help="JSON with T3's environment and project tool responses")
    args = parser.parse_args(argv)
    if args.list_adapters:
        print(json.dumps(ADAPTERS))
        return 0
    if args.t3_projects is not None:
        if args.provider or args.settings is not None:
            parser.error("--t3-projects cannot be combined with --provider or --settings")
        try:
            snapshot = json.loads(args.t3_projects.expanduser().read_text(encoding="utf-8"))
            findings, unchecked = inspect_projects(snapshot)
        except (OSError, ValueError):
            print(json.dumps({"ok": False, "error": "snapshot_unreadable_or_invalid", "check": "t3-projects"}))
            return 2
        print(json.dumps({"ok": True, "check": "t3-projects", "findings": findings, "unchecked": unchecked,
                          "scope": "worktree bootstrap check; drafts are proposals, nothing is imported",
                          "writes": 0}))
        return 1 if findings else 0
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
