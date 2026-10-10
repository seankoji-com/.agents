#!/usr/bin/env bash
# Print the host repository identity shared by forage and study.
set -euo pipefail
if project_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  cd "$project_root"
fi
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
      -e 's|^ssh://[^/]+/||' \
      -e 's|\.git$||' \
      -e 's|/$||' |
    tr '/' '_')
  if [ -n "$owner_repo" ] && [ "$owner_repo" != "$repo_basename" ]; then
    slug="${owner_repo}__${repo_basename}"
  fi
fi
printf '%s\n' "$slug"
