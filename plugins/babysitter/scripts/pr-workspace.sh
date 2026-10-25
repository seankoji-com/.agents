#!/usr/bin/env bash
#
# pr-workspace.sh — give one PR its own git worktree, in the right repository.
#
# The babysitter works across a whole org, so "isolated worktree" cannot mean a
# worktree of the repo the session was launched in — each PR lives in a different
# repository. This script keeps one bare-ish cache clone per repository under
# ~/.local/state/t3-plugins/babysitter/repos/ and cuts one worktree per PR from it, so N agents on N
# PRs never share an index, and two PRs in the same repo still get separate
# checkouts.
#
# The PR's head branch is deliberately NOT checked out under its own name. The
# worktree gets a local branch `babysitter/pr-<N>` pointing at origin/<head>, and
# pushes go through `git push origin HEAD:<head>`. That keeps the same branch usable
# from several worktrees without relying on implicit upstream selection.
#
# Usage:
#   pr-workspace.sh --repo <owner/name> --pr <N> --branch <head-ref> [--root <dir>]
#   pr-workspace.sh --repo <owner/name> --pr <N> --remove [--force] [--root <dir>]
#
# --remove refuses to delete a worktree with uncommitted or untracked changes (exit
# 4, left untouched). --force discards them; nothing else does.
# --preserve returns an existing dirty checkout unchanged for its repair worker.
# Clean unpushed commits are always retained; integration belongs to that worker.
#
# On success the worktree path is the only thing written to stdout; progress goes to
# stderr. Callers can therefore do: WT="$(pr-workspace.sh ...)"
#
# Exit codes:
#   0 — worktree ready (path on stdout), or removed
#   2 — precondition failed (bad arguments, missing git/gh)
#   3 — clone, fetch, worktree creation, or worktree removal failed
#   4 — the worktree exists and has uncommitted changes; left untouched (both when
#       reusing it and when asked to --remove it without --force)

set -euo pipefail

# Prints this file's header comment as the help text. Derived from the header
# rather than a hardcoded line range: a `sed -n '2,NNp'` went stale the first time
# this header grew, printing a truncated help message with no other symptom.
usage() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

REPO=""
PR_NUMBER=""
BRANCH=""
REMOVE=0
FORCE=0
PRESERVE=0
# Left empty rather than defaulted to "${HOME}/..." directly: under `set -u` an unset
# HOME aborts with a raw "unbound variable", and defaulting HOME to "" would silently
# produce the absolute-looking /.local/state/t3-plugins/babysitter. Empty here, validated below.
ROOT="${BABYSITTER_HOME:-}"
if [ -z "$ROOT" ] && [ -n "${HOME:-}" ]; then
  ROOT="${HOME}/.local/state/t3-plugins/babysitter"
fi

die() {
  echo "pr-workspace.sh: $1" >&2
  exit "${2:-2}"
}

note() { echo "pr-workspace.sh: $1" >&2; }

# Print configuration provenance without remote names, URL bases, or values.
report_policy_settings() {
  local location="$1" pattern="$2" scope key
  local -a context
  if [ -e "$location/.git" ]; then
    context=(-C "$location")
  else
    context=(--git-dir="$location/.git")
  fi
  git "${context[@]}" config --null --show-origin --name-only --get-regexp "$pattern" |
    while IFS= read -r -d '' scope && IFS= read -r -d '' key; do
      case "$key" in
      url.*.insteadof) key='url.<redacted-base>.insteadof' ;;
      url.*.pushinsteadof) key='url.<redacted-base>.pushinsteadof' ;;
      remote.origin.pushurl | remote.origin.vcs) : ;;
      remote.*.push) key='remote.<redacted>.push' ;;
      remote.*.mirror) key='remote.<redacted>.mirror' ;;
      *) continue ;;
      esac
      printf 'pr-workspace.sh: inspect %s in %s (values redacted)\n' "$key" "$scope" >&2
    done || true
}

# A custom remote helper bypasses HTTPS even when get-url reports HTTPS.
verify_origin_transport() {
  local location="$1" status
  local -a context
  if [ -e "$location/.git" ]; then context=(-C "$location"); else context=(--git-dir="$location/.git"); fi
  if git "${context[@]}" config --get-regexp '^remote\.origin\.vcs$' >/dev/null; then
    report_policy_settings "$location" '^remote\.origin\.vcs$'
    die "custom origin transport helper bypasses required HTTPS transport" 3
  else
    status=$?
    [ "$status" = 1 ] || die "cannot inspect origin transport helper" 3
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
  --repo)
    [ $# -ge 2 ] || die "--repo requires a value"
    REPO="$2"
    shift 2
    ;;
  --pr)
    [ $# -ge 2 ] || die "--pr requires a value"
    PR_NUMBER="$2"
    shift 2
    ;;
  --branch)
    [ $# -ge 2 ] || die "--branch requires a value"
    BRANCH="$2"
    shift 2
    ;;
  --root)
    [ $# -ge 2 ] || die "--root requires a value"
    ROOT="$2"
    shift 2
    ;;
  --remove)
    REMOVE=1
    shift
    ;;
  --force)
    FORCE=1
    shift
    ;;
  --preserve)
    PRESERVE=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    die "unknown argument: $1"
    ;;
  esac
done

command -v git >/dev/null 2>&1 || die "git not found on PATH"

# Every path this script creates, and the ones it deletes, is derived from ROOT.
# An empty ROOT — `--root ""`, or BABYSITTER_HOME set empty with HOME unset — would
# put those paths at the filesystem root and point a recursive delete at
# /worktrees/<slug>__pr-<N>. Validate before deriving anything from it.
case "$ROOT" in
'') die "root directory is empty — set --root or BABYSITTER_HOME to an absolute path" ;;
/*) : ;;
*) die "root directory must be an absolute path, got: ${ROOT}" ;;
esac

case "$REPO" in
*/*) : ;;
*) die "--repo must be owner/name, got: ${REPO:-<empty>}" ;;
esac
case "$PR_NUMBER" in
'' | *[!0-9]*) die "--pr must be a number, got: ${PR_NUMBER:-<empty>}" ;;
esac

OWNER="${REPO%%/*}"
NAME="${REPO#*/}"
for component in "$OWNER" "$NAME"; do
  case "$component" in
  '' | . | .. | *[!A-Za-z0-9._-]*) die "--repo must contain plain owner/name components" ;;
  esac
done
SLUG="${OWNER}__${NAME}"
CLONE="${ROOT}/repos/${SLUG}"
WORKTREE="${ROOT}/worktrees/${SLUG}__pr-${PR_NUMBER}"

if [ "$REMOVE" = "1" ]; then
  if [ -d "$CLONE/.git" ] && [ -e "$WORKTREE" ]; then
    if [ "$FORCE" = "1" ]; then
      # Explicitly authorized to discard whatever is there, including a directory
      # Git no longer recognizes as a worktree.
      git -C "$CLONE" worktree remove --force "$WORKTREE" 2>/dev/null ||
        rm -rf "$WORKTREE"
    else
      # Never discard work unasked: an agent that left changes behind may still
      # need them. Say so and let the caller decide, exactly as the reuse path does.
      if ! pending="$(git -C "$WORKTREE" status --porcelain 2>/dev/null)"; then
        echo "$WORKTREE"
        die "cannot inspect ${WORKTREE} for uncommitted changes — left untouched (pass --force to delete it anyway)" 4
      fi
      if [ -n "$pending" ]; then
        echo "$WORKTREE"
        die "worktree ${WORKTREE} has uncommitted changes — left untouched (pass --force to discard them)" 4
      fi
      git -C "$CLONE" worktree remove "$WORKTREE" ||
        die "could not remove ${WORKTREE}; left untouched (pass --force to delete it anyway)" 3
    fi
    git -C "$CLONE" branch -D "babysitter/pr-${PR_NUMBER}" >/dev/null 2>&1 || true
    note "removed ${WORKTREE}"
  else
    note "nothing to remove at ${WORKTREE}"
  fi
  exit 0
fi

[ -n "$BRANCH" ] || die "--branch <head-ref> is required unless --remove is given"
# The head ref is interpolated into refs/remotes/origin/<branch> and handed to git as
# an argument. Git's own ref checker refuses option-like names and ref syntax with
# special meaning (`..`, `:`, `*`, `^`, `~`, `[`, `@{`), so only one branch can match.
case "$BRANCH" in
-* | *' '* | *[[:cntrl:]]*) die "--branch must be a plain head ref name, got: ${BRANCH}" ;;
esac
git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 ||
  die "--branch must be a plain head ref name, got: ${BRANCH}"

mkdir -p "${ROOT}/repos" "${ROOT}/worktrees" || die "cannot create ${ROOT}" 3

# ---- cache clone -------------------------------------------------------------
GH_READY=0
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  GH_READY=1
else
  note "HTTPS-only cache: run gh auth login or configure a working HTTPS credential helper; SSH keys alone cannot authenticate this cache"
fi
if [ ! -d "$CLONE/.git" ]; then
  if [ -e "$CLONE" ] || [ -L "$CLONE" ]; then
    die "cache path exists without a Git clone; preserve it and choose another root or reconcile it privately" 3
  fi
  note "cloning ${REPO} (first PR seen in this repo)"
  # Use gh's headless credential helper when authenticated, while keeping Git's
  # literal validated HTTPS URL. Otherwise retain the host's existing Git helpers.
  #
  # Retried once, because a clone here fails transiently more often than it fails
  # for real: a large repo has been observed stalling for minutes against an
  # ESTABLISHED connection and then dying, where an immediate bare retry succeeded.
  # Retry only when Git removed its failed target. Never delete a cache collision
  # or a remaining partial clone; preserve it for private inspection.
  clone_diagnostics=$(mktemp "${TMPDIR:-/tmp}/babysitter-clone-error.XXXXXX") ||
    die "cannot create private clone diagnostics" 3
  inspection_owned=0
  cleanup_inspection() {
    if [ "$inspection_owned" = 1 ]; then
      # This Git directory was created exclusively below, with no templates or
      # transport. Only our probe is removed; a nonempty destination survives.
      rm -rf "$CLONE/.git"
      rmdir "$CLONE" 2>/dev/null || true
    fi
  }
  trap 'rm -f "$clone_diagnostics"; cleanup_inspection' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  # ls-remote --get-url performs no transport. Use the future clone Git directory
  # and the same exact identity maps that clone --config installs before fetching.
  # Git resolves the git-dir's parent even for config-only reads. Use an owned
  # empty destination so the future .git path, includeIf rules and inherited
  # system/global/command configuration are identical to the actual clone.
  mkdir "$CLONE" || die "cannot prepare clone configuration inspection" 3
  inspection_owned=1
  git init --quiet --bare --template= "$CLONE/.git" || die "cannot initialize configuration inspection" 3
  verify_origin_transport "$CLONE"
  initial_transport=$(git --git-dir="$CLONE/.git" \
    -c "url.https://github.com/${REPO}.git.insteadOf=https://github.com/${REPO}.git" \
    -c "url.https://github.com/${REPO}.git.pushInsteadOf=https://github.com/${REPO}.git" \
    ls-remote --get-url "https://github.com/${REPO}.git" 2>/dev/null) ||
    die "cannot inspect initial clone transport; inspect inherited Git configuration privately" 3
  [ "$initial_transport" = "https://github.com/${REPO}.git" ] ||
    die "initial clone transport differs from required HTTPS repository; inspect inherited URL rewrites privately" 3
  cleanup_inspection
  [ ! -e "$CLONE" ] || die "inspection destination changed; preserved for private inspection" 3
  inspection_owned=0
  report_clone_failure() {
    local category=unclassified
    if grep -Eiq 'Authentication failed|could not read Username|Permission denied.*publickey|publickey' "$clone_diagnostics"; then
      category=authentication
    elif grep -Eiq 'repository .*not found|Repository not found' "$clone_diagnostics"; then
      category=repository-not-found
    elif grep -Eiq 'certificate|SSL|TLS' "$clone_diagnostics"; then
      category=TLS
    elif grep -Eiq 'Could not resolve|unable to access|Connection|proxy|timed out' "$clone_diagnostics"; then
      category=network
    elif grep -Eiq 'Permission denied|cannot create|could not create' "$clone_diagnostics"; then
      category=filesystem
    elif grep -Eiq 'config|rewrite|protocol|bad boolean' "$clone_diagnostics"; then
      category=configuration
    fi
    # Raw errors may contain credential-bearing URLs, even in config-key names.
    note "clone failure category=${category}; diagnostic contents redacted"
  }
  clone_once() {
    local -a credential_options=()
    if [ "$GH_READY" = "1" ]; then
      # Keep Git's literal validated URL; gh repo clone may canonicalize aliases.
      credential_options=(-c credential.helper= -c 'credential.helper=!gh auth git-credential')
    fi
    git ${credential_options[@]+"${credential_options[@]}"} clone --quiet \
      --config "url.https://github.com/${REPO}.git.insteadOf=https://github.com/${REPO}.git" \
      --config "url.https://github.com/${REPO}.git.pushInsteadOf=https://github.com/${REPO}.git" \
      "https://github.com/${REPO}.git" "$CLONE" 2>"$clone_diagnostics"
  }

  if ! clone_once; then
    if [ -e "$CLONE" ] || [ -L "$CLONE" ]; then
      report_clone_failure
      die "failed clone path remains; preserved for private inspection instead of retrying" 3
    fi
    note "clone of ${REPO} failed — retrying once"
    clone_once || {
      report_clone_failure
      if [ "$GH_READY" = "1" ]; then
        die "clone of ${REPO} failed twice" 3
      fi
      die "clone of ${REPO} failed twice (and gh is unavailable for authenticated clone)" 3
    }
  fi
  rm -f "$clone_diagnostics"
fi

# ---- make this clone pushable ------------------------------------------------
# Applied on every run, not just on a fresh clone, so a clone made by an earlier
# version of this script — or by a `gh` whose git_protocol was set differently at the
# time — gets repaired rather than staying broken forever. Worktrees share the clone's
# config, so fixing it here fixes every PR in the repo at once.
#
# Each of these three closes a push failure that has actually happened in a sweep, and
# each one presented as a different, misleading error:
#
#   1. An SSH origin is a dead end wherever the ssh-agent cannot sign ("agent refused
#      operation"). One repo in an org cloning over SSH while the rest come down over
#      HTTPS is enough to strand every PR in it, and no retry helps.
#   2. A global credential.helper that cannot run headlessly (macOS `osxkeychain` is
#      the usual one) does not cleanly fall through to the next helper in the chain;
#      git ends up trying to prompt on a TTY that is not there and reports "could not
#      read Username ... Device not configured", or a SOCKS/proxy error, depending on
#      which fallback it reached. The empty value first is what resets the inherited
#      chain — `credential.helper` accumulates across config scopes, so adding the gh
#      helper without clearing would leave the broken one still in front of it.
#   3. `push.default=current` pushes the *local* branch name to a same-named remote
#      ref. The local branch here is deliberately `babysitter/pr-<N>`, so under that
#      setting a bare `git push` silently creates a stray remote branch instead of
#      updating the PR — worse than an error, because nothing says it went wrong.
#      `upstream` is unsafe when another worktree tracks the default branch.
#      `nothing` refuses every implicit push, regardless of upstream names or
#      remotes; callers must use the explicit HEAD:<head> push documented above.
if ! git -C "$CLONE" remote set-url origin "https://github.com/${REPO}.git" 2>/dev/null; then
  report_policy_settings "$CLONE" '^remote\..*\.(push|mirror)$'
  die "cannot configure HTTPS origin in ${CLONE}" 3
fi

# Exact per-clone identity mappings neutralize common inherited shorter SSH
# rewrites without editing global configuration. The resolved push URL below
# remains authoritative and refuses ambiguous exact rewrites/pushurl overrides.
for rewrite in insteadOf pushInsteadOf; do
  git -C "$CLONE" config --local --replace-all \
    "url.https://github.com/${REPO}.git.${rewrite}" "https://github.com/${REPO}.git" ||
    die "cannot scope HTTPS transport to this clone" 3
done

# Only when gh can actually serve credentials: clearing the chain and pointing it at a
# gh that is not authenticated would replace a helper that might work with one that
# certainly does not.
if [ "$GH_READY" = "1" ]; then
  git -C "$CLONE" config --local --unset-all credential.helper 2>/dev/null || true
  git -C "$CLONE" config --local --add credential.helper "" 2>/dev/null || true
  git -C "$CLONE" config --local --add credential.helper "!gh auth git-credential" 2>/dev/null || true
fi

# Remote push refspecs and mirror mode take precedence over push.default.
# Refuse inherited or reused settings rather than silently changing their meaning.
verify_push_policy() {
  local location="$1" status mirror destination fetch_destination
  verify_origin_transport "$location"
  if ! destination=$(git -C "$location" remote get-url --push --all origin 2>/dev/null); then
    report_policy_settings "$location" '^remote\..*\.(push|mirror)$'
    die "cannot inspect origin push destination" 3
  fi
  if ! fetch_destination=$(git -C "$location" remote get-url --all origin 2>/dev/null); then
    report_policy_settings "$location" '^remote\..*\.(push|mirror)$'
    die "cannot inspect origin fetch destination" 3
  fi
  if [ "$destination" != "https://github.com/${REPO}.git" ] ||
    [ "$fetch_destination" != "https://github.com/${REPO}.git" ]; then
    report_policy_settings "$location" '^(url\..*\.(insteadof|pushinsteadof)|remote\.origin\.pushurl)$'
    die "origin push destination differs from required HTTPS repository; scope SSH/URL rewrites outside this cache or remove its pushurl override" 3
  fi
  local keys key
  if keys=$(git -C "$location" config --name-only --get-regexp '^remote\..*\.(push|mirror)$'); then
    :
  else
    status=$?
    [ "$status" = 1 ] || die "cannot inspect remote push configuration" 3
  fi
  # Remote names can themselves contain sensitive text. Never log names or values.
  # Read all effective configured remotes, including alternate branch push remotes.
  while IFS= read -r key; do
    [ -n "$key" ] || continue
    case "$key" in
    *.push)
      report_policy_settings "$location" '^remote\..*\.(push|mirror)$'
      die "configured remote push refspec bypasses safe push policy" 3 ;;
    *.mirror)
      if mirror=$(git -C "$location" config --bool "$key" 2>/dev/null); then
        if [ "$mirror" = true ]; then
          report_policy_settings "$location" '^remote\..*\.(push|mirror)$'
          die "remote mirror mode bypasses safe push policy" 3
        fi
      else
        report_policy_settings "$location" '^remote\..*\.(push|mirror)$'
        die "cannot inspect remote mirror mode" 3
      fi ;;
    esac
  done <<< "$keys"

}
verify_common_push_policy() {
  local location="$1"
  [ "$(git -C "$location" config --get push.default)" = nothing ] &&
    [ "$(git -C "$location" config --get remote.pushDefault)" = origin ] ||
    die "effective common safe push policy is not enforced" 3
}

verify_push_policy "$CLONE"

git -C "$CLONE" config --local push.default nothing ||
  die "cannot configure safe push policy in ${CLONE}" 3
git -C "$CLONE" config --local remote.pushDefault origin ||
  die "cannot configure push remote in ${CLONE}" 3
verify_common_push_policy "$CLONE"

git -C "$CLONE" fetch --prune --quiet origin ||
  die "fetch failed in ${CLONE}" 3

git -C "$CLONE" rev-parse --verify --quiet "refs/remotes/origin/${BRANCH}" >/dev/null ||
  die "origin/${BRANCH} does not exist in ${REPO} — was the PR branch deleted?" 3

# ---- worktree ----------------------------------------------------------------
LOCAL_BRANCH="babysitter/pr-${PR_NUMBER}"
# Keep push selection predictable too; a stale branch pushRemote overrides
# remote.pushDefault. Explicit origin HEAD:<head> remains the supported push.
git -C "$CLONE" config --local "branch.${LOCAL_BRANCH}.pushRemote" origin ||
  die "cannot configure push remote for ${LOCAL_BRANCH}" 3

verify_worktree_policy() {
  local location="$1"
  verify_push_policy "$location"
  verify_common_push_policy "$location"
  [ "$(git -C "$location" config --get "branch.${LOCAL_BRANCH}.pushRemote")" = origin ] ||
    die "effective safe push policy is not enforced for ${LOCAL_BRANCH}" 3
}

if [ -d "$WORKTREE/.git" ] || [ -f "$WORKTREE/.git" ]; then
  # Validate worktree overrides before even fetching from inherited destinations.
  verify_worktree_policy "$WORKTREE"
  # Reuse. Never discard work: if a previous agent left changes behind, say so and
  # let the caller decide rather than resetting over them.
  if [ -n "$(git -C "$WORKTREE" status --porcelain 2>/dev/null)" ]; then
    echo "$WORKTREE"
    if [ "$PRESERVE" = 1 ]; then
      note "preserved unfinished work in ${WORKTREE}; worker must integrate current head"
      exit 0
    fi
    die "worktree ${WORKTREE} has uncommitted changes — inspect it before reusing" 4
  fi
  git -C "$WORKTREE" fetch --quiet origin -- "$BRANCH" || die "fetch failed in worktree" 3
  if git -C "$WORKTREE" merge-base --is-ancestor HEAD "origin/${BRANCH}"; then
    git -C "$WORKTREE" merge --quiet --ff-only "origin/${BRANCH}" ||
      die "could not advance ${LOCAL_BRANCH} to origin/${BRANCH}" 3
  else
    note "preserved local commits in ${WORKTREE}; worker must integrate current head"
  fi
  note "reused ${WORKTREE}"
else
  rm -rf "$WORKTREE"
  git -C "$CLONE" worktree prune
  git -C "$CLONE" worktree add --quiet -B "$LOCAL_BRANCH" "$WORKTREE" "origin/${BRANCH}" ||
    die "could not create worktree for ${REPO}#${PR_NUMBER}" 3
  note "created ${WORKTREE} on ${LOCAL_BRANCH} (tracking origin/${BRANCH})"
fi

verify_worktree_policy "$WORKTREE"

echo "$WORKTREE"
