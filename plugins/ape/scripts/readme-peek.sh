#!/usr/bin/env bash
# Phase 1 helper for gibbon-scout — peeks at a repo's README headline as a
# single preapprovable command instead of a multi-stage pipe chain.
#
# Usage: readme-peek.sh <owner/repo>
# fail-soft: report available README content, tolerate fetch/decode failures
set -uo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <owner/repo>" >&2
  exit 2
fi

# --decode rather than -d: -d is GNU-only, and older macOS base64 rejects it.
gh api "repos/$1/readme" -q .content 2>/dev/null | base64 --decode 2>/dev/null | head -40 || true
