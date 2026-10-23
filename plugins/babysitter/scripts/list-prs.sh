#!/usr/bin/env bash
#
# list-prs.sh — emit a full state snapshot, one compact JSON object per line, for
# every open pull request the babysitter is allowed to touch.
#
# This is the plugin's ONLY GitHub reader. Both the initial sweep and the event
# monitor call it: the sweep uses the identity fields, pr-events.sh polls it on an
# interval and diffs consecutive snapshots to derive events. One reader means the
# eligibility rules can never disagree between "which PRs we picked up" and "which
# PRs we react to".
#
# Everything comes from a single GraphQL call per invocation — mergeability, base
# head, check rollup, review threads and the newest comment/review ids — so a poll
# loop over dozens of PRs costs one request, not one per PR per field.
#
# The GraphQL round trip itself goes over curl, not `gh api graphql`. Under the
# Claude Code sandbox's network filter, gh's Go TLS stack fails cert verification
# for this endpoint (x509 errors) while curl completes the same handshake cleanly —
# observed consistently enough to be a real routing difference, not a flake. `gh`
# is still required, but only for `gh auth token`, a local credential read with no
# network round trip of its own.
#
# Usage:
#   list-prs.sh --org <org> [options]            # every eligible open PR in the org
#   list-prs.sh --repo <owner/name> [options]    # every eligible open PR in one repo
#   list-prs.sh --repo <owner/name> --pr <N>     # one specific PR
#
# Options:
#   --include-drafts   keep draft PRs (default: skipped — a draft is not ready)
#   --include-forks    keep PRs whose head branch lives in a fork (default: skipped;
#                      we usually cannot push to a fork's branch)
#   --all-authors      keep PRs by anyone (default: only the authenticated user and bots)
#   --limit <N>        max PRs to return in --org / --repo sweep mode (default 100,
#                      max 100: GitHub caps a search page at 100 and this does not
#                      paginate; a truncated result warns on stderr)
#
# Review state per PR: the first 100 review threads (with the last 5 comments of
# each), the thread totalCount, and whether that page is the whole set. A PR with
# more than 100 threads reports review_threads_complete: false, and its
# unresolved_threads / unresolved_outdated_threads counts are lower bounds; read the
# remaining pages before treating it as clear. review_decision is GitHub's
# reviewDecision; changes_requested_by lists the latest reviews in CHANGES_REQUESTED
# (bots suffixed [bot]).
#
# Pending queue state per PR: pending_checks lists each queued or running check with
# its name, status, startedAt and the creation clock. A queued GitHub Actions job has
# no startedAt, and GraphQL's CheckRun has no createdAt field, so the creation clock
# is read from the supported Actions job API (REST) using the job id in detailsUrl.
# Every pending entry names its clock in queue_clock; queue_clock_gaps lists jobs whose
# clock could not be obtained. This reader sets no age threshold; the coordinator does.
#
# Check-context completeness per PR: checks_complete is false when the rollup has more
# contexts than this query fetched (contexts first:100). failing and pending_checks are
# lower bounds in that case. A single-PR read also binds isRequired on the CheckRun and
# StatusContext nodes it saw (required_contexts / required_contexts_observed); that is
# an observed subset, so required_contexts_known is false and a search page leaves all
# three null/false.
#
# Query cost: GitHub prices a GraphQL call by the connection requests it could need,
# from the first/last arguments, not the rows actually returned. The thread comments
# dominate: limit x 100 threads. At the old 20 threads a 100-PR page cost about 25
# points; at 100 threads it would cost about 106, so a pr-events.sh watch polling
# every 60 s would spend about 6,400 points an hour against GitHub's 5,000-point
# hourly GraphQL budget. A one-off roster sweep keeps the 100-PR default (at most
# about 70,000 nodes per response, far below the 500,000-node cap) so a large org is
# not silently cut short; pr-events.sh passes --limit 50 to its poll loop (about 53
# points, about 3,200 an hour at 60 s) unless its caller chose a limit.
#
# Exit codes:
#   0 — snapshot written to stdout (possibly zero lines)
#   2 — precondition failed (missing gh/jq, not authenticated, bad arguments)
#   3 — the GitHub query itself failed (network, rate limit, permissions)
#
# Exit 3 is kept distinct from 2 on purpose: a poll loop should retry a failed
# query but must never retry a bad argument.

set -euo pipefail

# Prints this file's header comment as the help text. Derived from the header
# rather than a hardcoded line range: a `sed -n '2,NNp'` went stale the first time
# this header grew, printing a truncated help message with no other symptom.
usage() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

ORG=""
REPO=""
PR_NUMBER=""
INCLUDE_DRAFTS=0
INCLUDE_FORKS=0
ALL_AUTHORS=0
LIMIT=100

die() {
  echo "list-prs.sh: $1" >&2
  exit "${2:-2}"
}

# Temp files are registered here and removed on exit, so an abort between mktemp and
# the helper's own rm -f (a signal, a `set -e` failure) does not leave response bodies
# behind in TMPDIR. Set again inside the helper, which runs in a command-substitution
# subshell where the parent's EXIT trap does not apply.
GRAPHQL_TMP=""
cleanup_tmp() {
  if [ -n "$GRAPHQL_TMP" ]; then
    rm -f "$GRAPHQL_TMP" "${GRAPHQL_TMP}.err"
  fi
  return 0
}
trap cleanup_tmp EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Runs a GraphQL query, retrying a failed one twice with a widening pause.
#
# An org-wide sweep asks GitHub for every open PR across every repository in one
# query, which sits close enough to GitHub's response-time budget that a 504 ("we
# couldn't respond to your request in time") on the first attempt is ordinary rather
# than exceptional — observed twice in a row on a ~40-PR org, then succeeding on the
# third try with no change. Retrying here rather than in the caller matters because
# pr-events.sh polls through this script: without it, one transient 504 surfaces as an
# ERROR event in the middle of a watch that was otherwise fine.
#
# Bounded at three attempts, so a genuine failure (bad credentials, a repo that is
# gone) still exits 3 promptly instead of hanging a sweep behind a retry loop.
# Overridable so the test suite does not spend six real seconds asleep proving that a
# permanently-failing query still exits 3. Nothing in normal use sets it.
#
# Validated rather than interpolated straight into the arithmetic below: this variable
# exists to be overridden, and a non-integer value there is not a harmless typo. Under
# `set -e` a fractional value aborts the script with "invalid arithmetic operator", and
# under `set -u` an alphabetic one aborts with "unbound variable" — either way the sweep
# dies mid-retry with no snapshot and the wrong exit code, instead of retrying. Fall
# back to the default and say so.
RETRY_BASE_SECS="${BABYSITTER_RETRY_BASE_SECS:-2}"
case "$RETRY_BASE_SECS" in
'' | *[!0-9]*)
  echo "list-prs.sh: BABYSITTER_RETRY_BASE_SECS must be a non-negative integer, got '${RETRY_BASE_SECS}' — using 2" >&2
  RETRY_BASE_SECS=2
  ;;
esac

# Cached across retries and across the two call sites below: a local credential
# read (no network), so nothing is lost by asking once.
GH_TOKEN=""
gh_token() {
  if [ -z "$GH_TOKEN" ]; then
    if ! GH_TOKEN="$(gh auth token 2>&1)"; then
      echo "list-prs.sh: gh auth token failed: ${GH_TOKEN}" >&2
      return 1
    fi
  fi
  printf '%s' "$GH_TOKEN"
}

# Takes an already-assembled GraphQL request body (query + variables, as JSON) and
# POSTs it directly — see the header comment above for why curl rather than
# `gh api graphql`. Mirrors gh_graphql_retry's old contract exactly: prints the
# response body and returns 0 on success (HTTP 200), or prints the last error and
# returns 1 after three attempts.
curl_graphql_retry() {
  local body="$1" attempt=1 code="" content="" tmp errfile token
  token="$(gh_token)" || return 1
  tmp="$(mktemp "${TMPDIR:-/tmp}/babysitter-graphql.XXXXXX")" || {
    echo "list-prs.sh: mktemp failed for graphql response" >&2
    return 1
  }
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
    if [ "$attempt" -ge 3 ]; then
      printf '%s' "$content"
      rm -f "$tmp" "$errfile"
      return 1
    fi
    echo "list-prs.sh: GitHub query failed (attempt ${attempt}/3), retrying — ${content}" >&2
    sleep "$((attempt * RETRY_BASE_SECS))"
    attempt=$((attempt + 1))
  done
}

# GraphQL's CheckRun has startedAt and completedAt but no createdAt. A queued
# Actions job therefore has no creation clock in the GraphQL response; its
# detailsUrl carries the job id, and the supported Actions job API returns
# created_at. One bounded REST read per pending job that needs it keeps the queue
# clock honest. Lookups are capped so a large page cannot spend the REST budget.
MAX_QUEUE_CLOCK_LOOKUPS="${BABYSITTER_MAX_QUEUE_CLOCK_LOOKUPS:-25}"
case "$MAX_QUEUE_CLOCK_LOOKUPS" in
'' | *[!0-9]*) MAX_QUEUE_CLOCK_LOOKUPS=25 ;;
esac
QUEUE_CLOCK_LOOKUPS=0

gh_rest_job_created_at() {
  local owner_repo="$1" job_id="$2" token tmp errfile attempt=1 code created
  token="$(gh_token)" || return 1
  tmp="$(mktemp "${TMPDIR:-/tmp}/babysitter-job.XXXXXX")" || return 1
  errfile="${tmp}.err"
  while :; do
    code="$(curl -sS -o "$tmp" -w '%{http_code}' -H @- \
      -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/${owner_repo}/actions/jobs/${job_id}" \
      <<<"Authorization: bearer ${token}" 2>"$errfile")" || code="000"
    if [ "$code" = "200" ]; then
      created="$(jq -r '.created_at // empty' "$tmp" 2>/dev/null || true)"
      rm -f "$tmp" "$errfile"
      [ -n "$created" ] && printf '%s' "$created"
      return 0
    fi
    if [ "$attempt" -ge 2 ]; then
      rm -f "$tmp" "$errfile"
      return 1
    fi
    attempt=$((attempt + 1))
    sleep "$RETRY_BASE_SECS"
  done
}

# Adds creation clocks to one emitted PR row. A job whose clock cannot be obtained
# stays pending with a named queue_clock_gap, so the coordinator reports unknown age
# rather than inventing a fresh one.
enrich_queue_clocks() {
  local row="$1" manifest updates='{}' gaps='[]' _index name url pair owner_repo job_id created why
  manifest="$(printf '%s' "$row" | jq -r '
    .pending_checks
    | to_entries[]
    | select(.value.created_at == null and .value.started_at == null)
    | [.key, .value.name, (.value.details_url // "")] | @tsv' 2>/dev/null || true)"
  if [ -z "$manifest" ]; then
    printf '%s\n' "$row"
    return 0
  fi
  while IFS=$'\t' read -r _index name url; do
    [ -n "${name:-}" ] || continue
    created=""
    pair="$(printf '%s' "$url" | sed -nE 's#^https?://[^/]+/([^/]+/[^/]+)/actions/runs/[0-9]+/job/([0-9]+).*$#\1 \2#p')"
    owner_repo="${pair%% *}"
    job_id="${pair##* }"
    why=""
    if [ -z "$pair" ] || [ "$owner_repo" = "$pair" ] || [ -z "$job_id" ]; then
      why="detailsUrl does not identify an Actions job"
    elif [ "$QUEUE_CLOCK_LOOKUPS" -ge "$MAX_QUEUE_CLOCK_LOOKUPS" ]; then
      why="queue-clock lookup budget exhausted"
    else
      QUEUE_CLOCK_LOOKUPS=$((QUEUE_CLOCK_LOOKUPS + 1))
      if ! created="$(gh_rest_job_created_at "$owner_repo" "$job_id")"; then
        why="Actions job API read failed"
        created=""
      fi
      [ -n "$created" ] || why="${why:-Actions job API returned no created_at}"
    fi
    if [ -n "$created" ]; then
      updates="$(jq -cn --argjson u "$updates" --arg name "$name" --arg created "$created" '$u + {($name): $created}')"
    else
      gaps="$(jq -cn --argjson g "$gaps" --arg name "$name" --arg why "$why" '$g + [{name: $name, reason: $why}]')"
    fi
  done <<<"$manifest"
  printf '%s' "$row" | jq -c --argjson updates "$updates" --argjson gaps "$gaps" '
    .pending_checks = [ .pending_checks[]
      | if (.created_at == null and .started_at == null and ($updates[.name] // null) != null)
        then (.created_at = $updates[.name] | .queue_clock = "actions-job-api")
        else . end ]
    | .queue_clock_gaps = $gaps
    | .oldest_pending_check = (
        [ .pending_checks[]
          | select((.created_at // null) != null or (.started_at // null) != null) ]
        | sort_by(.created_at // .started_at) | first // null)'
}

while [ $# -gt 0 ]; do
  case "$1" in
  --org)
    [ $# -ge 2 ] || die "--org requires a value"
    ORG="$2"
    shift 2
    ;;
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
  --include-drafts)
    INCLUDE_DRAFTS=1
    shift
    ;;
  --include-forks)
    INCLUDE_FORKS=1
    shift
    ;;
  --all-authors)
    ALL_AUTHORS=1
    shift
    ;;
  --limit)
    [ $# -ge 2 ] || die "--limit requires a value"
    LIMIT="$2"
    shift 2
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

case "$LIMIT" in
'' | *[!0-9]*) die "--limit must be a number, got: ${LIMIT}" ;;
esac
[ "$LIMIT" -ge 1 ] && [ "$LIMIT" -le 100 ] || die "--limit must be between 1 and 100"

# Three targets, and exactly one of them:
#   --org X            every open PR in the org        -> search
#   --repo X           every open PR in one repository -> search
#   --repo X --pr N    one specific PR                 -> repository.pullRequest
# The two search forms differ only in the qualifier, so they share a code path and
# cannot drift apart in paging, filtering, or output shape.
if [ -n "$PR_NUMBER" ] && [ -z "$REPO" ]; then
  die "--pr requires --repo <owner/name>"
fi
if [ -n "$ORG" ] && [ -n "$REPO" ]; then
  die "--org cannot be combined with --repo"
fi
if [ -n "$REPO" ]; then
  case "$REPO" in
  */*) : ;;
  *) die "--repo must be owner/name, got: ${REPO}" ;;
  esac
  if [ -n "$PR_NUMBER" ]; then
    case "$PR_NUMBER" in
    *[!0-9]*) die "--pr must be a number, got: ${PR_NUMBER}" ;;
    esac
  fi
elif [ -z "$ORG" ]; then
  die "one of --org or --repo is required"
fi

# CheckRun.isRequired and StatusContext.isRequired take the pull request number, which
# is only known when this reader was asked for one PR. A search page cannot bind them,
# so required_contexts stays null there and the coordinator classifies from the rollup
# and merge state instead.
CHECK_REQUIRED_FIELD=""
STATUS_REQUIRED_FIELD=""
if [ -n "$PR_NUMBER" ]; then
  CHECK_REQUIRED_FIELD="isRequired(pullRequestNumber: ${PR_NUMBER})"
  STATUS_REQUIRED_FIELD="isRequired(pullRequestNumber: ${PR_NUMBER})"
fi

# The PullRequest selection is written once and reused by both query shapes, so a
# field added for the monitor is automatically present in the initial sweep. The
# heredoc is deliberately unquoted so ${CHECK_REQUIRED_FIELD} expands; the fragment
# must therefore contain no shell metacharacters, backticks or dollar signs.
read -r -d '' PR_FRAGMENT <<GRAPHQL || true
fragment PRState on PullRequest {
  number
  title
  url
  state
  isDraft
  isCrossRepository
  mergeable
  mergeStateStatus
  author { login }
  headRefName
  baseRefName
  baseRef { target { oid } }
  repository { nameWithOwner }
  # Several of the most recent comments, with bodies, not just the newest id: the
  # ids below are computed from the newest comment that is NOT one of the plugin's
  # own [babysitter] replies. Fetching only the last one would make an agent's own
  # reply the newest id and re-trigger a COMMENT event on the following poll.
  comments(last: 10) { nodes { databaseId body } }
  reviews(last: 1) { nodes { databaseId state } }
  reviewDecision
  latestReviews(first: 50) { nodes { state author { login __typename } } }
  reviewThreads(first: 100) {
    totalCount
    pageInfo { hasNextPage }
    nodes {
      isResolved
      isOutdated
      comments(last: 5) { nodes { databaseId body } }
    }
  }
  commits(last: 1) {
    nodes {
      commit {
        oid
        statusCheckRollup {
          state
          contexts(first: 100) {
            totalCount
            pageInfo { hasNextPage }
            nodes {
              __typename
              ... on CheckRun { name status conclusion startedAt detailsUrl ${CHECK_REQUIRED_FIELD} }
              ... on StatusContext { context state createdAt ${STATUS_REQUIRED_FIELD} }
            }
          }
        }
      }
    }
  }
}
GRAPHQL

if [ -z "$PR_NUMBER" ]; then
  if [ -n "$ORG" ]; then
    SCOPE_QUALIFIER="org:${ORG}"
  else
    SCOPE_QUALIFIER="repo:${REPO}"
  fi
  QUERY="query(\$q: String!, \$limit: Int!) {
    viewer { login }
    search(query: \$q, type: ISSUE, first: \$limit) {
      issueCount
      nodes { ...PRState }
    }
  }
  ${PR_FRAGMENT}"
  BODY=$(jq -n --arg query "$QUERY" --arg q "${SCOPE_QUALIFIER} is:pr is:open" --argjson limit "$LIMIT" \
    '{query: $query, variables: {q: $q, limit: $limit}}')
  RAW=$(curl_graphql_retry "$BODY") || die "GitHub query failed after 3 attempts: ${RAW}" 3
  NODES_PATH='.data.search.nodes'

  # GitHub caps a search page at 100 and this script does not paginate. Silently
  # returning the first page would make the sweep look complete while leaving PRs
  # unbabysat, and the watch would then report each missing one as NEW only if it
  # happened to surface later. Say so instead.
  #
  # issueCount is GitHub's count *before* this script's author/draft/fork filters run,
  # so it is always >= the number of lines emitted below and usually much larger. An
  # earlier phrasing ("has N open PRs") was read as the size of the roster about to be
  # worked, which made a correct 42-PR roster look like it had lost 33 PRs. The wording
  # below names the population explicitly for that reason — do not shorten it back.
  TOTAL=$(printf '%s' "$RAW" | jq -r '.data.search.issueCount // 0' 2>/dev/null || echo 0)
  case "$TOTAL" in
  '' | *[!0-9]*) TOTAL=0 ;;
  esac
  if [ "$TOTAL" -gt "$LIMIT" ]; then
    echo "list-prs.sh: ${SCOPE_QUALIFIER} has ${TOTAL} open PRs before this script's author/draft/fork filters, and only the first ${LIMIT} were fetched — the snapshot below is drawn from a partial page. Raise --limit (max 100) or narrow the scope. ${TOTAL} is not the size of the eligible roster; the line count below is." >&2
  fi
else
  OWNER="${REPO%%/*}"
  NAME="${REPO##*/}"
  QUERY="query(\$owner: String!, \$name: String!, \$number: Int!) {
    viewer { login }
    repository(owner: \$owner, name: \$name) {
      pullRequest(number: \$number) { ...PRState }
    }
  }
  ${PR_FRAGMENT}"
  BODY=$(jq -n --arg query "$QUERY" --arg owner "$OWNER" --arg name "$NAME" --argjson number "$PR_NUMBER" \
    '{query: $query, variables: {owner: $owner, name: $name, number: $number}}')
  RAW=$(curl_graphql_retry "$BODY") || die "GitHub query failed after 3 attempts: ${RAW}" 3
  NODES_PATH='[.data.repository.pullRequest]'
fi

# A GraphQL error arrives with HTTP 200: an `errors` array, usually alongside a null
# or partial `data` block. Neither curl nor jq treats that as a failure, so check for
# it explicitly rather than emitting an empty snapshot that looks like "no PRs".
if printf '%s' "$RAW" | jq -e '.errors != null' >/dev/null 2>&1; then
  die "GitHub returned errors: $(printf '%s' "$RAW" | jq -r '[.errors[] | .message // tostring] | join("; ")' 2>/dev/null | head -c 400)" 3
fi
if ! printf '%s' "$RAW" | jq -e '.data' >/dev/null 2>&1; then
  die "GitHub returned no data: $(printf '%s' "$RAW" | head -c 400)" 3
fi
# In --pr mode a null pullRequest means the number does not exist in that repository
# (or the token cannot see it). That is a failed query, not "no eligible PRs": a
# caller that got an empty snapshot here would conclude the PR was merged.
if [ -n "$PR_NUMBER" ] && printf '%s' "$RAW" | jq -e '.data.repository.pullRequest == null' >/dev/null 2>&1; then
  die "pull request ${REPO}#${PR_NUMBER} not found or not accessible with the current credentials" 3
fi

if [ -n "$PR_NUMBER" ]; then PR_MODE=1; else PR_MODE=0; fi

printf '%s' "$RAW" | jq -c \
  --argjson include_drafts "$INCLUDE_DRAFTS" \
  --argjson include_forks "$INCLUDE_FORKS" \
  --argjson all_authors "$ALL_AUTHORS" \
  --argjson pr_mode "$PR_MODE" \
  --arg nodes_path "$NODES_PATH" '
  # The plugin marks every comment it posts with a [babysitter] prefix. Comments
  # carrying it are excluded from the "newest comment" ids below, so an agent
  # replying on a thread does not raise the id and trigger a COMMENT event on the
  # next poll — a re-dispatch that finds nothing to do and returns noop.
  #
  # Deliberately keyed on the marker rather than on the comment author. This plugin
  # assumes one gh identity both opens the PR and leaves feedback on it, which is
  # the normal case for a solo maintainer; filtering by author would silently hide
  # their own review comments from the babysitter. Same reasoning imps/prs.md
  # records for its own filter.
  def is_own_reply:
    ((.body // "") | startswith("[babysitter]"));

  # Bot logins come back without the [bot] suffix in GraphQL; add it so the names
  # match what the merge helper and the GitHub UI show.
  def reviewer:
    (.author.login // "ghost") as $login
    | if .author.__typename == "Bot" and ($login | endswith("[bot]") | not)
      then $login + "[bot]" else $login end;

  def is_bot($login):
    $login != null and (
      ($login | endswith("[bot]"))
      or ($login | ascii_downcase | startswith("copilot"))
      or ($login | ascii_downcase) == "dependabot"
    );

  # A check is failing only once it has finished and finished badly. A run that has
  # not concluded yet is pending, not failing — dispatching an agent to "fix" a job
  # that is still queued is how a babysitter invents work for itself.
  #
  # The inner parentheses around the `not` are load-bearing: in jq the pipe binds
  # looser than "and", so "a and b | not" means "(a and b) | not", which inverts the
  # null guard along with the test and selects every queued run.
  #
  # (No apostrophes in this block. The whole program is a single-quoted shell
  # argument, and one stray apostrophe ends it and hands the rest to bash.)
  #
  # NEUTRAL and SKIPPED are passes. CANCELLED, TIMED_OUT, STALE and ACTION_REQUIRED
  # are failures — an abandoned job blocks a merge exactly as hard as a red one.
  def failing_contexts:
    [ .[]?
      | if .__typename == "CheckRun" then
          select(.conclusion != null
            and ((.conclusion | IN("SUCCESS", "NEUTRAL", "SKIPPED")) | not))
          | .name
        else
          select(.state != null and (.state | IN("FAILURE", "ERROR")))
          | .context
        end
    ] | unique;

  # A pending queue entry carries the only clock that can prove a job is stuck.
  # A GraphQL CheckRun exposes startedAt but no createdAt, so a queued Actions job
  # leaves created_at null here and the shell resolves it from the Actions job API
  # using detailsUrl. Callers compute age against their own observation time; this
  # script never invents a threshold.
  def pending_checks:
    [ .[]?
      | if .__typename == "CheckRun" then
          select(.conclusion == null
            and (.status != null and (.status | IN("QUEUED", "IN_PROGRESS", "WAITING", "PENDING", "REQUESTED"))))
          | {name: .name, status: .status, conclusion: null,
             created_at: null, started_at: .startedAt, details_url: (.detailsUrl // null),
             queue_clock: (if .startedAt then "check-run-started-at" else null end)}
        else
          select(.state != null and (.state | IN("PENDING", "EXPECTED")))
          | {name: .context, status: .state, conclusion: null,
             created_at: .createdAt, started_at: null, details_url: null,
             queue_clock: "status-context-created-at"}
        end
    ] | unique_by(.name);

  . as $root
  | (.data.viewer.login) as $viewer
  | (if $nodes_path == "[.data.repository.pullRequest]"
     then [$root.data.repository.pullRequest]
     else $root.data.search.nodes end)
  | map(select(. != null and .number != null))
  | map(
      (.author.login) as $author
      | (.commits.nodes[0].commit) as $head
      | {
          repo: .repository.nameWithOwner,
          number: .number,
          url: .url,
          title: .title,
          author: $author,
          bot: is_bot($author),
          mine: ($author == $viewer),
          draft: .isDraft,
          fork: .isCrossRepository,
          state: .state,
          head_ref: .headRefName,
          base_ref: .baseRefName,
          base_oid: (.baseRef.target.oid // null),
          head_oid: ($head.oid // null),
          mergeable: .mergeable,
          # GitHub-computed merge-readiness state (CLEAN, BEHIND, BLOCKED, DIRTY, DRAFT,
          # HAS_HOOKS, UNKNOWN, UNSTABLE) — distinct from `mergeable`, which only
          # says whether the diff applies cleanly (no conflicts). A PR can be
          # `mergeable: MERGEABLE` and still be BLOCKED by branch protection: an
          # unresolved conversation, a required reviewer, a code-scanning alert
          # threshold, or an org ruleset like "extra approval for unattributed
          # changes". Callers that only checked `mergeable` + checks_state +
          # unresolved_threads have reported a PR "clean" and had the actual `gh pr
          # merge` reject it for reasons this snapshot said nothing about.
          merge_state_status: .mergeStateStatus,
          checks_state: ($head.statusCheckRollup.state // null),
          # A false here means failing and pending_checks are lower bounds: the
          # rollup had more contexts than this query fetched.
          checks_complete: (
            (($head.statusCheckRollup.contexts.pageInfo.hasNextPage // false) == false)
          ),
          checks_total: ($head.statusCheckRollup.contexts.totalCount // null),
          failing: ($head.statusCheckRollup.contexts.nodes // [] | failing_contexts),
          pending_checks: ($head.statusCheckRollup.contexts.nodes // [] | pending_checks),
          # Only a single-PR read can bind isRequired on the contexts it saw. That is
          # an observed subset: a required context that is absent from this page cannot
          # be enumerated here, so required_contexts_known stays false. Null elsewhere so
          # the coordinator treats required-context evidence as unknown, not empty.
          required_contexts: (
            if $pr_mode == 1 then
              ([ $head.statusCheckRollup.contexts.nodes[]?
                 | if .__typename == "CheckRun" then
                     select(.isRequired == true) | .name
                   elif .__typename == "StatusContext" then
                     select(.isRequired == true) | .context
                   else empty end ] | unique)
            else null end
          ),
          # Present required contexts (a safe subset), not the complete configured set.
          required_contexts_observed: (
            if $pr_mode == 1 then
              ([ $head.statusCheckRollup.contexts.nodes[]?
                 | if .__typename == "CheckRun" then
                     select(.isRequired == true) | .name
                   elif .__typename == "StatusContext" then
                     select(.isRequired == true) | .context
                   else empty end ] | unique)
            else null end
          ),
          required_contexts_known: false,
          # The oldest pending job drives queue-age diagnosis at the coordinator
          # observation time. Null when every observed check has finished.
          oldest_pending_check: (
            ($head.statusCheckRollup.contexts.nodes // [] | pending_checks)
            | sort_by(.created_at // .started_at // "") | first // null
          ),
          # Filled by the shell after the Actions job API lookup for any pending job
          # that had neither a creation clock nor a startedAt.
          queue_clock_gaps: [],
          # Counts every thread that the required_review_thread_resolution
          # branch-protection rule blocks a merge on. That rule keys on
          # `isResolved` alone — an `isOutdated` thread (its diff line moved under
          # a later commit) still blocks merge if nobody resolved it. Excluding
          # isOutdated here used to undercount: a PR could show
          # `unresolved_threads: 0` and still hard-fail `gh pr merge` with "A
          # conversation must be resolved before this pull request can be merged."
          # `isOutdated` is exposed separately below so a caller can tell still
          # open from resolved-but-not-yet-marked-outdated-clear if it matters,
          # without reintroducing the undercount here.
          unresolved_threads: (
            [.reviewThreads.nodes[]? | select(.isResolved == false)] | length
          ),
          unresolved_outdated_threads: (
            [.reviewThreads.nodes[]? | select(.isResolved == false and .isOutdated == true)]
            | length
          ),
          # Both counts above cover the first 100 threads only. A real PR carried 55
          # threads when this read 20, and reported most of them as absent. Compared
          # with == false, not //, because jq treats a false value as missing.
          review_threads_complete: (.reviewThreads.pageInfo.hasNextPage == false),
          review_thread_total: (.reviewThreads.totalCount // null),
          review_decision: (.reviewDecision // null),
          changes_requested_by: (
            [.latestReviews.nodes[]? | select(.state == "CHANGES_REQUESTED") | reviewer] | unique
          ),
          last_thread_comment_id: (
            [ .reviewThreads.nodes[]?.comments.nodes[]?
              | select(is_own_reply | not) | .databaseId ] | max // 0
          ),
          last_comment_id: (
            [ .comments.nodes[]? | select(is_own_reply | not) | .databaseId ] | max // 0
          ),
          last_review_id: (.reviews.nodes[0].databaseId // 0),
          last_review_state: (.reviews.nodes[0].state // null)
        }
    )
  # Open only. In --org mode the search query already says is:open, but the
  # single-PR query has no such filter and happily returns a merged or closed PR.
  # Two things depend on this: babysitting a merged PR is pointless work, and
  # pr-events.sh --exit-when-empty terminates precisely because a merged PR drops
  # out of the snapshot. Without this line that watch would never end.
  | map(select(.state == "OPEN"))
  | map(select($all_authors == 1 or .mine or .bot))
  | map(select($include_drafts == 1 or (.draft | not)))
  | map(select($include_forks == 1 or (.fork | not)))
  | sort_by(.repo, .number)
  | .[]
' | while IFS= read -r row; do
  enrich_queue_clocks "$row"
done
