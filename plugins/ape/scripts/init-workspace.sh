#!/usr/bin/env bash
# Phase 0 helper for /ape:forage — creates the workspace and reports whether a
# fresh run directory is allocated, as a single preapprovable command (no ad hoc
# compound bash the permission system can't statically analyze).
# fail-fast: partial workspace init is worse than none
set -euo pipefail

# Derive a disambiguated slug from remote origin + basename to avoid
# collisions between identically-named repos at different paths.
repo_basename="$(basename "$(pwd)")"
slug="$repo_basename"
if remote_url=$(git remote get-url origin 2>/dev/null); then
  # Normalize remote URL to extract owner/repo.
  # Supports https://, git@, ssh:// formats.
  owner_repo=$(echo "$remote_url" |
    sed -E \
      -e 's|^https?://[^/]+/||' \
      -e 's|^git@[^:]+:||' \
      -e 's|^ssh://[^/]+/[^/]+/||' \
      -e 's|\.git$||' \
      -e 's|/$||' |
    tr '/' '_')
  if [ -n "$owner_repo" ] && [ "$owner_repo" != "$repo_basename" ]; then
    slug="${owner_repo}__${repo_basename}"
  fi
fi
workspace="$HOME/tmp/repo-research/$slug"

# Never adopt or rename an existing unmarked research directory.
script_dir="$(cd "$(dirname "$0")" && pwd -P)"
python3 "$script_dir/workspace.py" init "$workspace"

mkdir -p "$workspace/reports"
reports_dir="$(mktemp -d "$workspace/reports/run.XXXXXXXX")"

echo "slug=$slug"
echo "workspace=$workspace"
echo "reports=$reports_dir"
ls -la "$workspace"

echo "fingerprint=$reports_dir/fingerprint.md"
