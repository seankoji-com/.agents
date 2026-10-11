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

# Ask for the raw media type so no base64 decoder (whose flags differ between GNU
# and BSD) is involved.
gh api -H 'Accept: application/vnd.github.raw' "repos/$1/readme" 2>/dev/null | head -40 || true
