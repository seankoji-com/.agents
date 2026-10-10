#!/usr/bin/env bash
# Phase 1 helper for gibbon-scout — triages finalist repos with `gh repo view`
# as a single preapprovable command instead of a shell for-loop the
# permission system can't statically analyze.
#
# Usage: triage-repos.sh "<owner/repo 1>" ["<owner/repo 2>" ...]
# fail-soft: run every repo check even if some fail, report all results
set -uo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <owner/repo> [<owner/repo> ...]" >&2
  exit 2
fi

failed=0

for r in "$@"; do
  if output="$(gh repo view "$r" --json isArchived,pushedAt,diskUsage,licenseInfo,description 2>&1)"; then
    echo "=== $r ==="
  else
    echo "=== $r === (FAILED)"
    failed=$((failed + 1))
  fi
  printf '%s\n' "$output"
done

if [ "$failed" -gt 0 ]; then
  exit 1
fi
