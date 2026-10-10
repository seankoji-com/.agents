#!/usr/bin/env bash
# Phase 0 helper for /ape:forage — creates the workspace and reports whether a
# fresh run directory is allocated, as a single preapprovable command (no ad hoc
# compound bash the permission system can't statically analyze).
# fail-fast: partial workspace init is worse than none
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd -P)"
slug="$(bash "$script_dir/workspace-slug.sh")"
workspace="$HOME/tmp/repo-research/$slug"

# Never adopt or rename an existing unmarked research directory.
python3 "$script_dir/workspace.py" init "$workspace"

mkdir -p "$workspace/reports"
reports_dir="$(mktemp -d "$workspace/reports/run.XXXXXXXX")"

echo "slug=$slug"
echo "workspace=$workspace"
echo "reports=$reports_dir"
ls -la "$workspace"

echo "fingerprint=$workspace/fingerprint.md"
