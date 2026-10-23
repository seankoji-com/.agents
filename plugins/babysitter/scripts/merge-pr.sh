#!/usr/bin/env bash
#
# merge-pr.sh — attempt to actually land one pull request, fixing exactly the
# merge-blockers that are safe to fix without a human's judgment.
#
# Reads current PR state, updates a behind branch, and pins each merge request to
# the checked head SHA. Review threads must already be explicitly resolved after
# verification. A comment prefix cannot prove that a finding was addressed.
# Incomplete snapshots and changed heads stop without arming auto-merge.
#
# Every network call goes over curl, not `gh api` / `gh pr merge` — same reason as
# list-prs.sh (see its header): under the Claude Code sandbox, gh's Go TLS stack
# fails cert verification against api.github.com while curl completes the identical
# handshake cleanly. `gh` is used only for `gh auth token`, a local credential read.
#
# Usage:
#   merge-pr.sh --repo <owner/name> --pr <N> [--method squash|merge|rebase] [--no-auto | --arm-always]
#               [--expected-head <SHA>]
#   merge-pr.sh --repo <owner/name> --pr <N> --update-only --expected-head <SHA>
#   merge-pr.sh --repo <owner/name> --pr <N> --resolve-thread <ID> --verified-head <SHA>
#               [--reply-file <path>]
#
# --arm-always is the babysitter "enable auto-merge on all PRs" posture. Arming is a
# convenience, not a decision to land the PR: it also arms auto-merge for conflict
# and behind outcomes, but only with a complete, resolved thread list. GitHub's
# auto-merge fires only once every merge requirement on the base branch holds. Where
# the branch requires conversation resolution, it never lands a PR with an unresolved
# thread; it never lands a conflicting PR or one whose required checks fail. So
# `automerge=armed` next to conflict or failing_checks in
# `blockers=` is still blocked: the caller keeps working those blockers. Where the
# branch does NOT require conversation resolution, an armed PR can land with threads
# open, so no mode arms with unresolved or incompletely read threads. --no-auto is the "leave
# auto-merge as set" posture: it arms nothing. Neither mode clears an existing request
# or treats one as a blocker. Neither relaxes the direct-merge gate below.
#
# --expected-head pins merge mode to a head the caller already accepted (the
# babysitter land stage passes its reviewed head). The PR head is reread before every
# merge or auto-merge mutation; any other head stops with
# reason=expected_head_mismatch and no mutation. A BEHIND PR is not updated, because
# update-branch would land a head nobody reviewed. The same SHA goes to GitHub as the
# REST merge `sha` and GraphQL `expectedHeadOid`, so the server enforces it too.
# Without the flag the checked head is pinned the same way, but any head is accepted.
#
# The resolution mode is a separate, explicit action after the agent verifies the
# finding. It checks thread ownership and the verified head, then, with --reply-file,
# posts that file's contents as a reply on the thread (addPullRequestReviewThreadReply),
# prefixed with "[babysitter] " unless the body already starts with it: list-prs.sh
# ignores marked replies, so the plugin's own answer never wakes a watch or re-dispatches
# a fixer for the thread it just answered. It rechecks the verified head after the
# reply, then resolves that one thread and exits without attempting a merge or
# auto-merge. The reply is sent once, never retried: a retried mutation whose first
# attempt landed would post twice. An empty (or whitespace-only) file or one over 60 KB
# is refused before any network call. An armed auto-merge request does not block
# resolution. Prints "RESOLVED <repo>#<pr> thread=<id> head=<sha>", plus " replied=1"
# when a reply was posted.
#
# Without --method, tries squash, then merge, then rebase, stopping at the first the
# repository accepts — GitHub's own error names any method the repo disallows, which
# is simpler and more current than caching each repo's `allowed_merge_methods` here.
#
# The REST merge call is only attempted in two states, and in both only with a
# complete, fully resolved review-thread page, no conflict, and no REVIEW_REQUIRED or
# CHANGES_REQUESTED review decision:
#   - mergeStateStatus CLEAN and the head commit's check rollup SUCCESS.
#   - mergeStateStatus UNSTABLE and every *required* status context at the exact head
#     green. GitHub computes UNSTABLE only once the base branch's own requirements are
#     met; the red or pending contexts that make it unstable are ones the branch does
#     not require. The script does not take that on trust (see the implicit ruleset
#     bypass under "What this script will NOT do"): it reads
#     statusCheckRollup.contexts(first:100) with isRequired(pullRequestNumber:) and
#     merges only when the page is complete (hasNextPage false), at least one context
#     is required, every required CheckRun concluded SUCCESS, NEUTRAL or SKIPPED and
#     every required StatusContext is SUCCESS. A required context that failed, is
#     still running or EXPECTED, a context page cut at 100, or no required context at
#     all ("no required contexts to verify") keeps the PR unmerged. A required check
#     that has not registered at all is not in the rollup; GitHub holds such a PR at
#     BLOCKED rather than UNSTABLE, so it never reaches this path.
# Both paths pin the merge PUT to the checked head SHA. Any other state — a check still
# PENDING/EXPECTED, no rollup yet (a fresh head whose checks have not registered), a
# BLOCKED/HAS_HOOKS/UNKNOWN merge state — is reported as blocked (checks_pending /
# not_clean / branch_protection) instead of merged, and auto-merge is armed where
# GitHub allows it. See "What this script will NOT do" below for why that gate cannot
# be left to GitHub. A successful UNSTABLE merge prints
# "MERGED <repo>#<pr> via <method> merge_state=UNSTABLE".
#
# Eligible BLOCKED outcomes also try arming GitHub's native auto-merge before it
# reports — the courtesy costs one extra mutation and means a PR blocked only on
# something outside this script's authority (a pending required check, a review
# still needed) finishes on its own the moment that condition clears, with no further
# call to this script needed. Auto-merge fires only once GitHub's merge requirements
# are met (it does not act on the arming user's bypass), so it is the safe hand-off
# for a not-yet-CLEAN PR. GitHub refuses to arm it on a PR that is already CLEAN or
# UNSTABLE, and on a PR whose base branch carries no protected-branch rules at all
# (a stacked PR based on an unprotected feature branch always lands here); each is
# reported as automerge=unavailable. Arming it changes nothing about whether THIS
# run considers the PR blocked; the exit code and reason are unaffected.
#
# An existing auto-merge request is never a blocker in any mode. It stays armed,
# is reported as automerge=preexisting, and a CLEAN PR carrying one is merged
# directly here instead of waiting for GitHub to act on it. The old
# automerge_already_enabled refusal made the operator disable it by hand first.
#
# Exit codes:
#   0 — merged, or explicit resolution mode printed "RESOLVED <repo>#<pr> ..."
#   2 — precondition failed (missing gh/curl/jq, bad arguments)
#   3 — the GitHub query itself failed (network, rate limit, permissions)
#   4 — blocked on something this script will not act on unasked: a required human
#       approval, a code-scanning threshold, a check still running, a merge state
#       other than CLEAN, an unresolved thread with no
#       verified resolution yet, a head other than --expected-head, or a merge conflict. Never retried, never
#       overridden with admin/force. stdout is one line:
#         BLOCKED <repo>#<pr> reason=<first> blockers=<all>[ changes_requested_by=<logins>]
#           detail=<...> automerge=<armed|unavailable|preexisting>
#       reason= is the first blocker in the historical gate order, kept for callers
#       that key on it. blockers= is a comma list of EVERY condition visible in the
#       one state read the decision used, so a conflict or BEHIND no longer hides open
#       threads and open threads no longer hide failing checks. Its tokens: conflict,
#       behind, incomplete_review_state, unanswered_threads:<count> (isResolved false,
#       outdated included; a lower bound when incomplete_review_state is also set),
#       failing_checks, checks_pending, changes_requested, review_required, not_clean.
#       A reason outside that vocabulary (head_changed, expected_head_mismatch,
#       closed, permission_denied, ...) leads the list. changes_requested_by= lists
#       each latest review in CHANGES_REQUESTED, bots suffixed [bot]; it is omitted
#       when there are none.
#
# What this script will NOT do, on purpose:
#   - Never merges past branch protection or a ruleset. Not passing `--admin` is
#     NOT enough to guarantee that: when the caller's token belongs to someone on a
#     ruleset's bypass list with bypass mode "always" (org admins typically are),
#     GitHub applies the bypass implicitly to a plain REST merge — no flag, no
#     warning — and accepts it while required checks are still pending. This has
#     happened in practice: an org-admin token merged a PR whose check rollup was
#     still PENDING, with nothing in the response saying a bypass was used. The
#     guard is this script's own: merge only when mergeStateStatus is CLEAN and the
#     rollup is SUCCESS, or UNSTABLE with every required context verified green at the
#     head (neither the rollup nor isRequired depends on who is asking), and hand
#     everything else to auto-merge. The merge PUT pins the checked head SHA, so a new
#     commit is refused (409); a check re-queued on the SAME head between the read and
#     the PUT is a residual window REST merge cannot close. A required check, a required reviewer, or an org ruleset exists on
#     purpose; the fix for a PR that cannot satisfy one is either satisfying it for
#     real or a human's call to waive it, never something this script does on its own.
#   - Never resolves review threads as part of merging. Resolution requires the
#     separate --resolve-thread action and the agent's --verified-head assertion.
#   - Never rebases or force-pushes the PR branch itself. `--method rebase` is
#     GitHub's server-side "rebase and merge" against the *base* branch (replays the
#     PR's commits, then fast-forwards the base) — it never rewrites or force-pushes
#     the PR's own branch, so it does not conflict with the agent's "never
#     force-push" rule, which is about that branch's own history.

set -euo pipefail

usage() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

REPO=""
PR_NUMBER=""
METHOD=""
RESOLVE_THREAD=""
VERIFIED_HEAD=""
REPLY_FILE=""
EXPECTED_HEAD=""
UPDATE_ONLY=0
AUTO_MERGE=1
ARM_ALWAYS=0

die() {
  echo "merge-pr.sh: $1" >&2
  exit "${2:-2}"
}

# Temp files are registered here and removed on exit, so an abort between mktemp and
# the helper's own rm -f (a signal, a `set -e` failure) does not leave response bodies
# behind in TMPDIR. Set again inside each helper, which runs in a command-substitution
# subshell where the parent's EXIT trap does not apply.
GRAPHQL_TMP=""
REST_TMP=""
cleanup_tmp() {
  if [ -n "$GRAPHQL_TMP" ]; then
    rm -f "$GRAPHQL_TMP" "${GRAPHQL_TMP}.err"
  fi
  if [ -n "$REST_TMP" ]; then
    rm -f "$REST_TMP"
  fi
  return 0
}
trap cleanup_tmp EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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
  --method)
    [ $# -ge 2 ] || die "--method requires a value"
    METHOD="$2"
    shift 2
    ;;
  --resolve-thread)
    [ $# -ge 2 ] || die "--resolve-thread requires a value"
    RESOLVE_THREAD="$2"
    shift 2
    ;;
  --verified-head)
    [ $# -ge 2 ] || die "--verified-head requires a value"
    VERIFIED_HEAD="$2"
    shift 2
    ;;
  --reply-file)
    [ $# -ge 2 ] || die "--reply-file requires a value"
    REPLY_FILE="$2"
    shift 2
    ;;
  --expected-head)
    [ $# -ge 2 ] || die "--expected-head requires a value"
    EXPECTED_HEAD="$2"
    shift 2
    ;;
  --update-only)
    UPDATE_ONLY=1
    AUTO_MERGE=0
    shift
    ;;
  --no-auto)
    AUTO_MERGE=0
    shift
    ;;
  --arm-always)
    ARM_ALWAYS=1
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

command -v gh >/dev/null 2>&1 || die "gh CLI not found on PATH"
command -v curl >/dev/null 2>&1 || die "curl not found on PATH"
command -v jq >/dev/null 2>&1 || die "jq not found on PATH"

[ -n "$REPO" ] || die "--repo is required"
case "$REPO" in
*/*) : ;;
*) die "--repo must be owner/name, got: ${REPO}" ;;
esac
# REPO is interpolated into REST paths below (/repos/<owner>/<name>/pulls/...), so
# anything beyond a plain owner/name would rewrite the request. Same allowlist as
# pr-workspace.sh.
for component in "${REPO%%/*}" "${REPO#*/}"; do
  case "$component" in
  '' | . | .. | *[!A-Za-z0-9._-]*) die "--repo must contain plain owner/name components, got: ${REPO}" ;;
  esac
done
case "$PR_NUMBER" in '' | *[!0-9]*) die "--pr must be a number, got: ${PR_NUMBER}" ;; esac
case "$METHOD" in
'' | squash | merge | rebase) ;;
*) die "--method must be squash, merge, or rebase, got: ${METHOD}" ;;
esac
if [ "$UPDATE_ONLY" = 1 ]; then
  [ -n "$EXPECTED_HEAD" ] || die "--update-only requires --expected-head"
  [ -z "$RESOLVE_THREAD$VERIFIED_HEAD$REPLY_FILE$METHOD" ] && [ "$ARM_ALWAYS" = 0 ] || die "update-only cannot resolve, merge or arm auto-merge"
  AUTO_MERGE=0
fi
if [ -n "$RESOLVE_THREAD" ] || [ -n "$VERIFIED_HEAD" ]; then
  [ -n "$RESOLVE_THREAD" ] && [ -n "$VERIFIED_HEAD" ] || die "resolution requires both --resolve-thread and --verified-head"
  [[ "$VERIFIED_HEAD" =~ ^[0-9a-f]{40}$ ]] || die "--verified-head must be a full lowercase commit SHA"
  [ -z "$METHOD" ] || die "resolution mode cannot also select a merge method"
  [ "$ARM_ALWAYS" = 0 ] || die "resolution mode cannot also arm auto-merge"
fi
# The reply is validated and encoded before any network call, so a bad file costs
# nothing and can never leave a thread half-handled.
REPLY_MUTATION=""
if [ -n "$REPLY_FILE" ]; then
  [ -n "$RESOLVE_THREAD" ] || die "--reply-file requires --resolve-thread"
  [ -f "$REPLY_FILE" ] && [ -r "$REPLY_FILE" ] || die "--reply-file is not a readable file: ${REPLY_FILE}"
  reply_bytes="$(wc -c <"$REPLY_FILE" | tr -d '[:space:]')"
  [ "$reply_bytes" -le 61440 ] || die "--reply-file is ${reply_bytes} bytes; the limit is 60 KB (61440 bytes)"
  jq -e -Rs 'test("[^[:space:]]")' <"$REPLY_FILE" >/dev/null 2>&1 || die "--reply-file is empty; write the reply body first"
  REPLY_MUTATION="$(jq -n --arg id "$RESOLVE_THREAD" --rawfile body "$REPLY_FILE" '{
    query: "mutation($id:ID!,$body:String!){ addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id, body:$body}){ comment{ id } } }",
    variables: { id: $id, body: (if ($body | startswith("[babysitter]")) then $body else "[babysitter] " + $body end) }
  }')" || die "could not encode --reply-file as JSON"
  # The body travels as one curl argument; Linux caps a single argument at 128 KiB.
  [ "$(printf '%s' "$REPLY_MUTATION" | wc -c | tr -d '[:space:]')" -le 120000 ] || die "--reply-file is too large once JSON-encoded; shorten it"
fi
[ "$ARM_ALWAYS" = 0 ] || [ "$AUTO_MERGE" = 1 ] || die "--arm-always and --no-auto are mutually exclusive"
if [ -n "$EXPECTED_HEAD" ]; then
  [[ "$EXPECTED_HEAD" =~ ^[0-9a-f]{40}$ ]] || die "--expected-head must be a full lowercase commit SHA"
  [ -z "$RESOLVE_THREAD" ] || die "--expected-head applies to merge mode; resolution uses --verified-head"
fi

OWNER="${REPO%%/*}"
NAME="${REPO#*/}"

GH_TOKEN=""
gh_token() {
  if [ -z "$GH_TOKEN" ]; then
    if ! GH_TOKEN="$(gh auth token 2>&1)"; then
      echo "merge-pr.sh: gh auth token failed: ${GH_TOKEN}" >&2
      return 1
    fi
  fi
  printf '%s' "$GH_TOKEN"
}

# POSTs a GraphQL body with two retries after 2 and 4 seconds. Like
# list-prs.sh, uses curl for TLS compatibility, but keeps fixed retry delays
# and sends failure details to stderr; stdout contains successful JSON only.
# An optional second argument caps the attempts: 1 for a non-idempotent mutation.
curl_graphql_retry() {
  local body="$1" max_attempts="${2:-3}" attempt=1 code="" content="" tmp errfile token
  token="$(gh_token)" || return 1
  tmp="$(mktemp "${TMPDIR:-/tmp}/babysitter-graphql.XXXXXX")" || return 1
  errfile="${tmp}.err"
  GRAPHQL_TMP="$tmp"
  trap cleanup_tmp EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  while :; do
    code="$(curl -sS -o "$tmp" -w '%{http_code}' \
      -H @- \
      -H "Content-Type: application/json" \
      -X POST --data "$body" \
      https://api.github.com/graphql <<<"Authorization: bearer ${token}" 2>"$errfile")" || code="000"
    if [ "$code" = "200" ]; then
      cat "$tmp"
      rm -f "$tmp" "$errfile"
      return 0
    fi
    content="$(cat "$tmp" "$errfile" 2>/dev/null)"
    if [ "$attempt" -ge "$max_attempts" ]; then
      printf '%s' "$content" >&2
      rm -f "$tmp" "$errfile"
      return 1
    fi
    sleep "$((attempt * 2))"
    attempt=$((attempt + 1))
  done
}

# A REST call over curl for the same TLS reason as the GraphQL helper above.
# Prints "<http_code>\n<body>"; caller splits on the first newline. Returns 1 on a
# transport failure (curl itself could not complete the request — DNS, TLS, a
# dropped connection) rather than folding it into a fake "000" HTTP code with
# exit 0: a caller that only compares `code` against expected values would
# otherwise treat "the request never happened" the same as "GitHub answered with
# some code I did not expect", and could misreport a network blip as a real
# branch-protection block.
curl_rest() {
  local method="$1" path="$2" data="${3:-}" token code tmp curl_rc=0
  token="$(gh_token)" || return 1
  tmp="$(mktemp "${TMPDIR:-/tmp}/babysitter-rest.XXXXXX")" || return 1
  REST_TMP="$tmp"
  trap cleanup_tmp EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [ -n "$data" ]; then
    code="$(curl -sS -o "$tmp" -w '%{http_code}' \
      -H @- \
      -H "Accept: application/vnd.github+json" \
      -H "Content-Type: application/json" \
      -X "$method" --data "$data" \
      "https://api.github.com${path}" <<<"Authorization: bearer ${token}")" || curl_rc=$?
  else
    code="$(curl -sS -o "$tmp" -w '%{http_code}' \
      -H @- \
      -H "Accept: application/vnd.github+json" \
      -X "$method" \
      "https://api.github.com${path}" <<<"Authorization: bearer ${token}")" || curl_rc=$?
  fi
  if [ "$curl_rc" -ne 0 ]; then
    echo "merge-pr.sh: curl transport failure (exit ${curl_rc}) calling ${method} ${path}: $(cat "$tmp" 2>/dev/null)" >&2
    rm -f "$tmp"
    return 1
  fi
  printf '%s\n' "$code"
  cat "$tmp"
  rm -f "$tmp"
}

# Fetches mergeable/mergeStateStatus/reviewThreads fresh — called both up front and
# after any fix, since GitHub's mergeStateStatus lags the action that resolves it by
# a few seconds (queued background work, not synchronous).
fetch_state() {
  local query resp
  query=$(jq -n --arg owner "$OWNER" --arg name "$NAME" --argjson number "$PR_NUMBER" '{
    query: "query($owner:String!,$name:String!,$number:Int!){ repository(owner:$owner,name:$name){ pullRequest(number:$number){ id state headRefOid mergeable mergeStateStatus reviewDecision baseRefName headRefName autoMergeRequest{ enabledAt } reviewThreads(first:100){ pageInfo{ hasNextPage } nodes{ id isResolved } } latestReviews(first:50){ nodes{ state author{ login __typename } } } commits(last:1){ nodes{ commit{ statusCheckRollup{ state contexts(first:100){ pageInfo{ hasNextPage } nodes{ __typename ... on CheckRun{ name status conclusion isRequired(pullRequestNumber:$number) } ... on StatusContext{ context state isRequired(pullRequestNumber:$number) } } } } } } } } } }",
    variables: { owner: $owner, name: $name, number: $number }
  }')
  resp="$(curl_graphql_retry "$query")" || { echo "merge-pr.sh: state query failed (details above)" >&2; return 1; }
  if jq -e '.errors' >/dev/null 2>&1 <<<"$resp"; then
    echo "merge-pr.sh: GraphQL returned errors: $(jq -c '.errors' <<<"$resp")" >&2
    return 1
  fi
  if ! jq -e '.data.repository.pullRequest | if .state == "MERGED" or .state == "CLOSED" then true else .state == "OPEN" and (.headRefOid | type == "string" and test("^[0-9a-f]{40}$")) and (.reviewThreads.nodes | type == "array") and (.reviewThreads.pageInfo.hasNextPage | type == "boolean") end' >/dev/null 2>&1 <<<"$resp"; then
    echo "merge-pr.sh: missing or invalid PR state" >&2
    return 1
  fi
  echo "$resp"
}

# Every merge blocker visible in one state read, computed together so the report
# lists all of them: the gates below still stop at the first, but a conflict or a
# BEHIND branch no longer hides open threads, and open threads no longer hide red
# checks. `check_status` is the rollup verdict for every state except UNSTABLE, where
# it is the verdict over the contexts marked isRequired for this PR (see the header).
read -r -d '' CONDITIONS_JQ <<'JQ' || true
def ctx_name: if .__typename == "CheckRun" then (.name // "?") else (.context // "?") end;
def ctx_ok:
  if .__typename == "CheckRun" then ((.conclusion // "") | IN("SUCCESS", "NEUTRAL", "SKIPPED"))
  else .state == "SUCCESS" end;
def ctx_pending:
  if .__typename == "CheckRun" then .conclusion == null
  else (.state == null or (.state | IN("PENDING", "EXPECTED"))) end;
def reviewer:
  (.author.login // "ghost") as $login
  | if .author.__typename == "Bot" and ($login | endswith("[bot]") | not)
    then $login + "[bot]" else $login end;
.data.repository.pullRequest as $pr
| ($pr.mergeStateStatus // "UNKNOWN") as $ms
| ($pr.commits.nodes[0].commit.statusCheckRollup // null) as $rollup
| ($rollup.state // "NONE") as $checks
| ($pr.reviewDecision // "NONE") as $decision
| [$pr.reviewThreads.nodes[]? | select(.isResolved != true)] as $open
| ($rollup.contexts // null) as $ctx
| [$ctx.nodes[]? | select(.isRequired == true)] as $required
| [$required[] | select((ctx_ok | not) and (ctx_pending | not)) | ctx_name] as $req_failing
| [$required[] | select(ctx_pending) | ctx_name] as $req_pending
| ($ctx != null and $ctx.pageInfo.hasNextPage == false) as $ctx_complete
| (if $ms == "UNSTABLE" then
     if ($req_failing | length) > 0 then "failing_checks"
     elif ($ctx_complete | not) or ($req_pending | length) > 0 then "checks_pending"
     elif ($required | length) == 0 then "no_required"
     else "ok" end
   elif ($checks | IN("FAILURE", "ERROR")) then "failing_checks"
   elif $checks == "SUCCESS" then "ok"
   else "checks_pending" end) as $check_status
| {
    merge_state: $ms,
    checks: $checks,
    decision: $decision,
    conflict_mergeable: ($pr.mergeable == "CONFLICTING"),
    dirty: ($ms == "DIRTY"),
    behind: ($ms == "BEHIND"),
    incomplete: ($pr.reviewThreads.pageInfo.hasNextPage == true),
    open_count: ($open | length),
    open_ids: ($open | map(.id) | join(",")),
    check_status: $check_status,
    ctx_complete: $ctx_complete,
    required_failing: ($req_failing | unique | join(",")),
    required_pending: ($req_pending | unique | join(",")),
    changes_requested_by: ([$pr.latestReviews.nodes[]? | select(.state == "CHANGES_REQUESTED") | reviewer] | unique | join(",")),
    blockers: ([
      (if $pr.mergeable == "CONFLICTING" or $ms == "DIRTY" then "conflict" else empty end),
      (if $ms == "BEHIND" then "behind" else empty end),
      (if $pr.reviewThreads.pageInfo.hasNextPage == true then "incomplete_review_state" else empty end),
      (if ($open | length) > 0 then "unanswered_threads:\($open | length)" else empty end),
      (if $check_status == "failing_checks" then "failing_checks" else empty end),
      (if $check_status == "checks_pending" then "checks_pending" else empty end),
      (if $decision == "CHANGES_REQUESTED" then "changes_requested" else empty end),
      (if $decision == "REVIEW_REQUIRED" then "review_required" else empty end),
      (if ($ms | IN("CLEAN", "UNSTABLE", "DIRTY", "BEHIND") | not) or $check_status == "no_required"
       then "not_clean" else empty end)
    ] | join(","))
  }
JQ

# Reads one field of the conditions computed by apply_merge_gates.
cond() {
  jq -r ".$1" <<<"$CONDS"
}

# PUTs the update-branch endpoint (server-side merge of base into head — the same
# non-destructive operation as `git merge origin/<base>`, just without a worktree)
# and polls briefly for mergeStateStatus to leave BEHIND. Bounded at 5 polls / ~15s:
# long enough for GitHub's queued merge to land, short enough that a genuinely stuck
# state falls through to being reported rather than hanging the caller.
sync_behind_branch() {
  local resp code body
  resp="$(curl_rest PUT "/repos/${REPO}/pulls/${PR_NUMBER}/update-branch" "$(jq -n --arg sha "$expected_head" '{expected_head_sha:$sha}')")" || return 1
  code="${resp%%$'\n'*}"
  body="${resp#*$'\n'}"
  case "$code" in
  2*) ;;
  *)
    echo "merge-pr.sh: update-branch failed (HTTP ${code}): ${body}" >&2
    return 1
    ;;
  esac
  local i state
  for i in 1 2 3 4 5; do
    sleep 3
    state="$(fetch_state)" || return 1
    if [ "$(jq -r '.data.repository.pullRequest.mergeStateStatus' <<<"$state")" != "BEHIND" ]; then
      return 0
    fi
  done
  echo "merge-pr.sh: mergeStateStatus still BEHIND after update-branch + ${i} polls" >&2
  return 1
}

# Arms GitHub's native auto-merge on the current PR (idempotent — re-arming an
# already-armed PR just re-confirms it), trying the same method order as try_merge.
# Returns 1 if the repository does not allow auto-merge at all (the setting is off in
# repo settings) or every method is rejected; the caller treats that as informational,
# never as a reason to change what it reports.
enable_automerge() {
  local pr_id already m mutation resp state expected_head
  # update-branch can succeed before mergeStateStatus catches up. Arm against a
  # fresh head and complete review state, never the pre-update snapshot.
  state="$(fetch_state)" || return 1
  handle_terminal_state "${1:-}"
  expected_head="$(jq -r '.data.repository.pullRequest.headRefOid' <<<"$state")"
  [ -z "$EXPECTED_HEAD" ] || [ "$expected_head" = "$EXPECTED_HEAD" ] || return 1
  jq -e '.data.repository.pullRequest.reviewThreads | .pageInfo.hasNextPage == false and all(.nodes[]; .isResolved == true)' >/dev/null <<<"$state" || return 1
  pr_id="$(jq -r '.data.repository.pullRequest.id // empty' <<<"$state")"
  [ -n "$pr_id" ] || return 1
  already="$(jq -r '.data.repository.pullRequest.autoMergeRequest.enabledAt // empty' <<<"$state")"
  [ -n "$already" ] && return 2
  local methods_upper=(SQUASH MERGE REBASE)
  [ -n "$METHOD" ] && methods_upper=("$(tr '[:lower:]' '[:upper:]' <<<"$METHOD")")
  for m in "${methods_upper[@]}"; do
    mutation=$(jq -n --arg id "$pr_id" --arg m "$m" --arg sha "$expected_head" '{
      query: "mutation($id:ID!,$m:PullRequestMergeMethod!,$sha:GitObjectID!){ enablePullRequestAutoMerge(input:{pullRequestId:$id, mergeMethod:$m, expectedHeadOid:$sha}){ pullRequest{ autoMergeRequest{ enabledAt } } } }",
      variables: { id: $id, m: $m, sha: $sha }
    }')
    resp="$(curl_graphql_retry "$mutation")" || continue
    if jq -e '.data.enablePullRequestAutoMerge.pullRequest.autoMergeRequest.enabledAt' >/dev/null 2>&1 <<<"$resp"; then
      return 0
    fi
  done
  return 1
}

# Reports a BLOCKED outcome, arming auto-merge first (best-effort) so a condition
# outside this run's control — a required check still to pass, a review still
# needed — resolves on its own without another call to this script. Exit code and
# reason are the same whether or not auto-merge could be armed.
#
# blockers= is recomputed from the same $state the decision used (merge mode, open PR
# only), so it lists every condition, not just the one that stopped this run. The
# reason always appears in it: as itself, as its counted form, or for
# branch_protection as the review/merge-state tokens that explain it.
blocked() {
  local reason="$1" detail="$2" automerge="unavailable" arm_rc armable="$AUTO_MERGE" conds blockers="" cr_by=""
  if jq -e '.data.repository.pullRequest.autoMergeRequest.enabledAt' >/dev/null 2>&1 <<<"${state:-}"; then
    automerge="preexisting"
  fi
  if [ -z "$RESOLVE_THREAD" ] && jq -e '.data.repository.pullRequest.state == "OPEN"' >/dev/null 2>&1 <<<"${state:-}"; then
    conds="$(jq -c "$CONDITIONS_JQ" <<<"$state")" || conds='{}'
    blockers="$(jq -r '.blockers // ""' <<<"$conds")"
    cr_by="$(jq -r '.changes_requested_by // ""' <<<"$conds")"
  fi
  case ",${blockers}," in
  *",${reason},"* | *",${reason}:"*) ;;
  *)
    if [ "$reason" != "branch_protection" ] || [ -z "$blockers" ]; then
      blockers="${reason}${blockers:+,${blockers}}"
    fi
    ;;
  esac
  case "$reason" in
  head_changed | expected_head_mismatch | closed | verified_head_changed | thread_not_on_pr | permission_denied | validation_failed) armable=0 ;;
  esac
  # A branch without conversation-resolution rules could merge immediately after
  # arming. Thread completion therefore gates arming in every posture.
  case ",${blockers}," in
  *,incomplete_review_state,* | *,unanswered_threads:*) armable=0 ;;
  esac
  # Arming for conflicts or a stale base is the --arm-always posture only.
  if [ "$ARM_ALWAYS" != 1 ]; then
    case ",${blockers}," in
    *,conflict,* | *,behind,*) armable=0 ;;
    esac
  fi
  if [ "$armable" = 1 ]; then
    if enable_automerge "$reason"; then
      automerge="armed"
    else
      arm_rc=$?
      [ "$arm_rc" != 2 ] || automerge="preexisting"
    fi
  fi
  echo "BLOCKED ${REPO}#${PR_NUMBER} reason=${reason} blockers=${blockers}${cr_by:+ changes_requested_by=${cr_by}} detail=${detail} automerge=${automerge}"
  exit 4
}

handle_terminal_state() {
  case "$(jq -r '.data.repository.pullRequest.state' <<<"$state")" in
    MERGED) echo "MERGED ${REPO}#${PR_NUMBER} via preexisting${1:+ prior_blocker=$1}"; exit 0 ;;
    CLOSED) blocked "closed" "PR was closed without merging; no action taken${1:+; prior_blocker=$1}" ;;
  esac
}

# With --expected-head, refuses (exit 4, nothing armed or merged) unless the head in
# $state is the caller's accepted head.
require_expected_head() {
  local head
  [ -n "$EXPECTED_HEAD" ] || return 0
  head="$(jq -r '.data.repository.pullRequest.headRefOid' <<<"$state")"
  [ "$head" = "$EXPECTED_HEAD" ] || blocked "expected_head_mismatch" "PR head ${head} is not the expected head ${EXPECTED_HEAD}; rebind and re-review before merging"
}

try_merge() {
  local method="$1" resp code body
  resp="$(curl_rest PUT "/repos/${REPO}/pulls/${PR_NUMBER}/merge" "$(jq -n --arg m "$method" --arg sha "$expected_head" '{merge_method:$m,sha:$sha}')")" || return 2
  code="${resp%%$'\n'*}"
  body="${resp#*$'\n'}"
  if [ "$code" = "200" ] && jq -e '.merged == true' >/dev/null 2>&1 <<<"$body"; then
    echo "MERGED ${REPO}#${PR_NUMBER} via ${method}"
    return 0
  fi
  # 405: "Pull Request is not mergeable" (or a merge-method the repo disallows) —
  # the caller tries the next method / classifies the message. A 409 means the
  # checked head changed: never retry another method or arm auto-merge for it.
  printf '%s' "$body" >&2
  echo "$code"
}

state="$(fetch_state)" || die "could not read PR state" 3
handle_terminal_state
expected_head="$(jq -r '.data.repository.pullRequest.headRefOid' <<<"$state")"
[ -n "$RESOLVE_THREAD" ] || require_expected_head
# Resolution never merges, so an existing auto-merge request does not block it.
if [ -n "$RESOLVE_THREAD" ]; then
  [ "$VERIFIED_HEAD" = "$expected_head" ] || blocked "verified_head_changed" "re-verify the finding against the new head before resolving"
  # Query the node directly so resolution works beyond the first 100 threads too.
  query=$(jq -n --arg id "$RESOLVE_THREAD" '{query:"query($id:ID!){node(id:$id){... on PullRequestReviewThread{id pullRequest{id headRefOid}}}}",variables:{id:$id}}')
  thread_state="$(curl_graphql_retry "$query")" || die "thread query failed" 3
  pr_id="$(jq -r '.data.repository.pullRequest.id' <<<"$state")"
  jq -e --arg id "$pr_id" --arg sha "$VERIFIED_HEAD" '.errors == null and .data.node.pullRequest.id == $id and .data.node.pullRequest.headRefOid == $sha' >/dev/null <<<"$thread_state" || blocked "thread_not_on_pr" "thread is not on this PR at the verified head; refresh its identity and the finding"
  # Reply before resolving, once: a retry after an ambiguous failure could post the
  # reply twice, and a failed reply leaves the thread open for the caller to retry.
  replied=""
  if [ -n "$REPLY_MUTATION" ]; then
    reply="$(curl_graphql_retry "$REPLY_MUTATION" 1)" || die "thread reply outcome unknown; check the thread for the reply before retrying (thread not resolved)" 3
    jq -e '.errors == null and (.data.addPullRequestReviewThreadReply.comment.id | type == "string")' >/dev/null 2>&1 <<<"$reply" || die "thread reply failed (thread not resolved): $(jq -c '.errors // .' <<<"$reply" 2>/dev/null | head -c 400)" 3
    replied=" replied=1"
    # Posting the reply can take long enough for another push to invalidate the
    # fix. A posted reply is not permission to resolve against a different head.
    thread_state="$(curl_graphql_retry "$query")" || die "thread recheck failed (the reply was posted; thread not resolved); refresh before retrying" 3
    jq -e --arg id "$pr_id" --arg sha "$VERIFIED_HEAD" '.errors == null and .data.node.pullRequest.id == $id and .data.node.pullRequest.headRefOid == $sha' >/dev/null <<<"$thread_state" || blocked "verified_head_changed" "thread identity or PR head changed after reply; the reply was posted but thread not resolved; re-verify before retrying"
  fi
  mutation=$(jq -n --arg id "$RESOLVE_THREAD" '{query:"mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{id isResolved}}}",variables:{id:$id}}')
  resolution="$(curl_graphql_retry "$mutation")" || die "thread resolution outcome unknown; refresh before retrying${replied:+ (the reply was posted; do not post it again)}" 3
  jq -e --arg id "$RESOLVE_THREAD" '.errors == null and .data.resolveReviewThread.thread.id == $id and .data.resolveReviewThread.thread.isResolved == true' >/dev/null <<<"$resolution" || die "thread resolution failed${replied:+ (the reply was posted; do not post it again)}: $(jq -c '.errors // .' <<<"$resolution" 2>/dev/null | head -c 400)" 3
  echo "RESOLVED ${REPO}#${PR_NUMBER} thread=${RESOLVE_THREAD} head=${VERIFIED_HEAD}${replied}"
  exit 0
fi
# An existing auto-merge request is deliberately never a blocker, in any mode. It
# belongs to whoever armed it; this script leaves it in place and reports it as
# automerge=preexisting (see blocked()). A CLEAN PR with one armed is still merged
# directly here, which is simply faster than waiting for GitHub to act on it, and a
# non-CLEAN PR reports its real blocker instead of blaming the armed request. The
# old automerge_already_enabled refusal forced the operator to disable it by hand
# before babysitter would work the PR at all.
mergeable="$(jq -r '.data.repository.pullRequest.mergeable' <<<"$state")"
merge_state="$(jq -r '.data.repository.pullRequest.mergeStateStatus' <<<"$state")"

if [ "$mergeable" = "CONFLICTING" ]; then
  blocked "conflict" "merge conflicts against the base branch; resolve in a worktree first, not here"
fi

if [ "$UPDATE_ONLY" = 1 ]; then
  [ "$merge_state" = "BEHIND" ] || blocked "not_behind" "refresh state before reserving another branch update"
  if ! sync_behind_branch; then
    blocked "behind" "update outcome requires reconciliation; refresh the branch before retrying"
  fi
  state="$(fetch_state)" || die "could not re-read PR state after update-branch" 3
  updated_head="$(jq -r '.data.repository.pullRequest.headRefOid' <<<"$state")"
  [[ "$updated_head" =~ ^[0-9a-f]{40}$ ]] && [ "$updated_head" != "$EXPECTED_HEAD" ] || blocked "update_pending" "update accepted but no new head confirmed; retain the reservation as uncertain and reconcile before another write"
  echo "UPDATED ${REPO}#${PR_NUMBER} previous_head=${EXPECTED_HEAD} head=${updated_head} refresh_gates=required"
  exit 0
fi

if [ "$merge_state" = "BEHIND" ]; then
  if [ -n "$EXPECTED_HEAD" ]; then
    blocked "behind" "branch is behind its base; update-branch would replace the expected head, so update and re-review it first"
  fi
  if ! sync_behind_branch; then
    blocked "behind" "update-branch did not clear BEHIND in time"
  fi
  state="$(fetch_state)" || die "could not re-read PR state after update-branch" 3
  handle_terminal_state
fi

# Every direct-merge gate, applied to the current $state snapshot. The gates stop at
# the first hit, in the historical order that reason= has always reported; blocked()
# lists the rest from the same snapshot. Sets MERGE_NOTE when the UNSTABLE path passes.
apply_merge_gates() {
  local detail
  CONDS="$(jq -c "$CONDITIONS_JQ" <<<"$state")"
  MERGE_NOTE=""
  expected_head="$(jq -r '.data.repository.pullRequest.headRefOid' <<<"$state")"
  merge_state="$(cond merge_state)"
  checks_state="$(cond checks)"
  review_decision="$(cond decision)"

  if [ "$(cond conflict_mergeable)" = true ]; then
    blocked "conflict" "merge conflicts against the base branch; resolve in a worktree first, not here"
  fi
  # Only reachable when the branch fell behind again after update-branch, or on the
  # --expected-head reread; either way this run will not update it a second time.
  if [ "$(cond behind)" = true ]; then
    blocked "behind" "mergeStateStatus=BEHIND at the gate read; not merging a head that is behind its base"
  fi
  # A bounded query must not silently certify a partial review snapshot.
  if [ "$(cond incomplete)" = true ]; then
    blocked "incomplete_review_state" "more than 100 review threads; inspect all pages and merge through the host's verified PR flow"
  fi
  unanswered_count="$(cond open_count)"
  if [ "$unanswered_count" -gt 0 ]; then
    blocked "unanswered_threads" "${unanswered_count} unresolved review thread(s); threads=$(cond open_ids); verify each finding and explicitly resolve it before merging"
  fi

  # Checked here, after fixing what could be fixed, rather than at the very top: base
  # drift or an unanswered thread can be the reason a required check never ran at all
  # (queued behind the branch update), so re-reading it now — not the possibly-stale
  # copy from the very first fetch_state call — is what makes this an accurate report
  # instead of a guess.
  #
  # This is the gate that stops the implicit admin bypass (see the header): GitHub
  # would accept a merge here for a ruleset-bypass actor whatever the rollup says, so
  # nothing short of CLEAN + SUCCESS, or UNSTABLE with every required context verified
  # green, reaches try_merge. A null rollup is treated as pending, not green: right
  # after update-branch (or any push) the new head has no check suites yet, and a
  # bypass-capable token must not merge into that gap.
  if [ "$(cond dirty)" = true ]; then
    blocked "conflict" "mergeStateStatus=DIRTY; resolve in a worktree first, not here"
  fi
  case "$(cond check_status)" in
  failing_checks)
    if [ "$merge_state" = "UNSTABLE" ]; then
      blocked "failing_checks" "required check(s) red at the head: $(cond required_failing) (mergeStateStatus=UNSTABLE, rollup=${checks_state}) — that is a code/CI fix, not something this script can resolve"
    fi
    blocked "failing_checks" "required status checks are red (rollup=${checks_state}) — that is a code/CI fix, not something this script can resolve"
    ;;
  checks_pending)
    if [ "$merge_state" = "UNSTABLE" ]; then
      if [ "$(cond ctx_complete)" != true ]; then
        detail="the head has more than 100 status contexts (or none were returned), so every required one cannot be verified"
      else
        detail="required check(s) not finished: $(cond required_pending)"
      fi
      blocked "checks_pending" "${detail} (mergeStateStatus=UNSTABLE, rollup=${checks_state}); not merging until each required context is green"
    fi
    case "$checks_state" in
    PENDING | EXPECTED | NONE)
      blocked "checks_pending" "checks have not finished (rollup=${checks_state}, mergeStateStatus=${merge_state}); not merging until they pass"
      ;;
    esac
    blocked "checks_pending" "unrecognised check rollup (rollup=${checks_state}, mergeStateStatus=${merge_state}); not merging until it reads SUCCESS"
    ;;
  esac
  case "$review_decision" in
  CHANGES_REQUESTED)
    detail="changes requested by $(cond changes_requested_by)"
    [ -n "$(cond changes_requested_by)" ] || detail="changes requested, but no latest review names the reviewer"
    case ",$(cond changes_requested_by)," in
    *"[bot],"*) detail="${detail}; a [bot] reviewer is an automated review to address and request re-review, not a missing human approval; never dismiss a review to clear this gate" ;;
    esac
    blocked "branch_protection" "mergeStateStatus=${merge_state} with reviewDecision=CHANGES_REQUESTED; ${detail}"
    ;;
  REVIEW_REQUIRED)
    blocked "branch_protection" "mergeStateStatus=${merge_state} with reviewDecision=REVIEW_REQUIRED; a required approving review is outstanding"
    ;;
  esac
  if [ "$merge_state" = "CLEAN" ]; then
    return 0
  fi
  if [ "$merge_state" = "UNSTABLE" ]; then
    if [ "$(cond check_status)" = ok ]; then
      MERGE_NOTE=" merge_state=UNSTABLE"
      return 0
    fi
    blocked "not_clean" "mergeStateStatus=UNSTABLE (rollup=${checks_state}); no required contexts to verify, so an UNSTABLE PR is not merged directly"
  fi
  blocked "not_clean" "mergeStateStatus=${merge_state} (rollup=${checks_state}); merging now could apply a ruleset bypass, so only CLEAN, or UNSTABLE with every required context green, is merged directly"
}

apply_merge_gates

# Reread the head right before the merge PUT: the gates above used an earlier read.
if [ -n "$EXPECTED_HEAD" ]; then
  state="$(fetch_state)" || die "could not re-read PR state before merging" 3
  handle_terminal_state
  require_expected_head
  # The fresh snapshot can show new failures or review blockers at the same head.
  apply_merge_gates
  expected_head="$EXPECTED_HEAD"
fi

methods=("$METHOD")
[ -z "$METHOD" ] && methods=(squash merge rebase)

last_code=""
for m in "${methods[@]}"; do
  out="$(try_merge "$m")" || die "merge request failed; outcome unknown, refresh PR state before retrying" 3
  if [[ "$out" == MERGED* ]]; then
    echo "${out}${MERGE_NOTE}"
    exit 0
  fi
  if [ "$out" = "409" ]; then
    blocked "head_changed" "PR head changed after verification; inspect the new commit and rerun"
  fi
  if [ "$out" = "403" ]; then
    blocked "permission_denied" "GitHub rejected the merge (HTTP 403); inspect the API error and repository permissions or rules before retrying"
  fi
  if [ "$out" = "422" ]; then
    blocked "validation_failed" "GitHub rejected the merge input (HTTP 422); inspect the API error and correct the request before retrying"
  fi
  if [ "$out" != "405" ]; then
    die "merge request returned HTTP ${out}; refresh PR state before retrying" 3
  fi
  last_code="$out"
done

# Every method failed. Re-fetch once more to give an accurate reason: a stale
# `mergeable`/`mergeStateStatus` read from the top of this script is a common way to
# misreport a review that landed CHANGES_REQUESTED or a code-scanning alert that
# posted in between.
#
# Deliberately not `<<<"${state:-{}}"`: bash's `${var:-word}` parser closes the
# expansion at the first unescaped `}` it sees — a literal `{}` in `word` is not
# tracked as nested — so that form silently appends a stray extra `}` after a
# non-empty `$state` and makes jq fail with "Unmatched '}'" on every successful
# fetch. Guard explicitly instead.
state="$(fetch_state)" || true
[ -n "$state" ] || state='{}'
handle_terminal_state
merge_state="$(jq -r '.data.repository.pullRequest.mergeStateStatus // "UNKNOWN"' <<<"$state")"
case "$merge_state" in
BLOCKED)
  blocked "branch_protection" "GitHub reports BLOCKED after every merge method failed (last HTTP ${last_code}) — likely a required reviewer, an org ruleset (e.g. approval required for unattributed changes), or a code-scanning alert at or above the org's threshold; none of these are safe for this script to satisfy on its own"
  ;;
DIRTY)
  blocked "conflict" "mergeStateStatus flipped to DIRTY between the top of this run and the merge attempt"
  ;;
*)
  blocked "unknown" "every merge method failed (last HTTP ${last_code}), mergeStateStatus=${merge_state}"
  ;;
esac
