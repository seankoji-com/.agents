# Reporting ledger inputs

Run `python3 PKG/scripts/session.py ACTION --session ID --input FILE`. IDs use
letters, numbers, underscores and hyphens, at most 80 characters. Default state
root: `$XDG_STATE_HOME/agents/jobs/bug-report`. It must be private, POSIX, outside
repositories and live userdata, with no symlink components. `status` never creates
or locks files. All other actions serialize under a no-follow root lock and save
with private atomic replacement. An operation failure permits no dependent host
write. Restore missing state from verified private backups; never reset state to
escape pending operations, a deadline or a budget. Recovery remains blocked when
the reservation exists but its session is missing.

The helper validates shapes, ownership records, deadlines and deduplication. All
classification, privacy, permission and host observations are operator assertions.
It cannot certify their truth or stop a privileged agent bypassing a receipt.

| Action | Input |
| --- | --- |
| `init` | `incident_key`, `owner_thread`, optional `private_values` array of nonempty sensitive strings. Repeated incident keys return the existing session, even under another ID, and persist newly declared literals without removing earlier ones. New literals hold previously prepared unsent intents for reconciliation and preparation again; existing owner, budget and deadline remain. |
| `problem` | `id`, `outcome`, `evidence`, `ownership_evidence`, `expectation_evidence`, `documentation`, `claims`; for defects `observation`; for unconfirmed `missing`; for external `destination`. Updates retain classification history and invalidate search. |
| `search` | `problem`, `queries`, `issues_complete`, `discussions_complete`, `candidates`, `selected` (canonical URL or null), `reason`. Candidates each retain `url`, `content`, `comments`, `versions`, `resolution`, `reason`. Complete flags require current full pagination. Returns a redacted draft with the search assessment, selected canonical link and matching candidate reason. |
| `budget` | `active` boolean. Optional `seconds` requires `owner_decision` with literal instruction and provenance; never infer consent. |
| `prepare` | `kind`, `payload`, optional `problem`, `target`, and assertions below. Saves a pending intent and returns `operation`, `hash`, redacted `payload` and generated `request`. A read with `reconciliation_for` naming the pending intent may inspect its outcome; it permits no second reporting admission. Confirmed unchanged evidence returns `duplicate:true` without a new intent. |
| `send` | `operation`. Recheck guards immediately before the host call. Returns the exact generated `request` for host dispatch. A sent intent cannot be sent again. Classification/search generations must still match preparation. |
| `finish` | `operation`, `observation` below; or `uncertain:true`; or `failed:true, confirmed_no_effect:true` only with observed definite failure. Closing a diagnostic/read also needs `request_terminal:true` from observed completion/stop. Failed reads require a nonempty `failure_class`; its redacted value and optional `evidence` survive in the operation/status, alongside a digest for repeated-failure detection. Matching repeated failures and the third failure stop retries. |
| `reconcile` | `operation`, fetched observation; or `absent:true, complete_search:true, evidence` after exhaustive remote reconciliation. A sent diagnostic/read additionally requires `request_terminal:true`; absence of public effects cannot prove it stopped. No ambiguous retry. |
| `comments` | `target`, `pages_complete:true`, authenticated `actor`, `items` containing `id`, `author`, `body`. Returns unseen content versions, excluding own replies. Existing unanswered versions remain in `status`. |
| `handled` | `version`, `disposition`: `answered`, `needs-owner`, `irrelevant`, `out-of-scope`; optional `detail`. Answered requires a confirmed `reply` operation bound to this exact comment version, target and observation time. |
| `block` | `requirement`, `next_action`, and any sanitized handle/attempt evidence. |
| `gap` | `since`, `reason`, optional `until`. Missing interval, app downtime and interrupted monitoring stay visible. |
| `wake` | Empty object. Refreshes current clock before resumed work. |
| `cancel` | Nonempty `owner_instruction`. The first redacted instruction and `cancelled_at` are retained in state/status; repeated cancellation preserves that cause/time. Reporting ends; cleanup remains necessary. |
| `status` | No input. Current-clock summary with verified URLs, dispositions, actions, gaps, unanswered requests, deadline and actual cleanup state. |

Evidence includes every field, with null for unknowns: `symptom`, `expected`,
`actual`, `impact`, `version`, `channel`, `provider`, `platform`, `procedure`,
`results`, `references`. Each claim includes `text`, `evidence` and `limits`.
Use citations and factual limits in the reviewed draft, rather than interpreting
these presence checks as evidence that reproduction happened.
For a claim with `fixes_affected_environment:true`, record the problem's structured
`environment`, the identical `tested_environment` on the claim, and a
`fix_observation` reference. A different-limit test cannot establish a fix for the
affected environment. These observations still need factual review.

`prepare` kinds:

- `launch`: reportable `problem`, `privacy_reviewed:true`,
  `thread_search_complete:true`; payload contains `scratch:true`, no `projectId`
  or `workspaceStrategy`, and a self-contained redacted `message` and `title`.
  Discover the host schema; missing scratch support blocks launch.
- `issue`, `comment`, `idea`, `reply`: `problem`, `privacy_reviewed:true`,
  `actor_thread`, `destination_refreshed:true`, `destination_observation` containing
  `write_access:true`, `templates_read:true`, and for Ideas `ideas_category_id`.
  Payload accepts only `body` and, for new issues/Ideas, `title`. Never pass
  arbitrary owner/repository/endpoint arguments. Set `transport` to
  `github-create-issue` for the connected issue creation tool, `github-rest` for
  issue/comment REST calls, or `github-graphql` for Discussion calls. The helper
  generates a destination-bound request. A comment/reply also needs a `target`
  identical to the search's inspected `selected` canonical target. A reply needs
  `comment_version` naming the outstanding request version.
  New Ideas, like new issues, require no selected matching target. Contribute to
  a selected Ideas destination through `comment` and its Discussion-comment request.
- `diagnostic`: `scope` is `read-only` or `task-owned-disposable`,
  `safe_procedure_reviewed:true`. Never use it to smuggle a code change/restart.
  Both validated fields survive in the operation and status actions.
- `read`: stable `read_key` per logical read, retained across retries. Both reads
  and diagnostics need active investigation budget before first publication.
  To reconcile a pending operation, add `reconciliation_for` with its exact ID.
  Only one such read may be in flight; unrelated reads and reporting remain held.
  Reads still obey expiry and investigation-budget guards.
- `schedule`: `actor_thread`, payload with
  `schedule:{"type":"interval","everyMs":120000}`, `bindToCurrentThread:true`
  and the safe host prompt. Only `schedule`, `bindToCurrentThread`, `prompt`,
  `title` and `clientRequestId` are accepted. No other project binding is allowed.
  This contract is for the interval fallback only.
- `cleanup`: payload contains the owned schedule's `task_id`. Preparation and
  dispatch require the original deadline reached or an explicit owner cancellation.
  Can then proceed while another pre-deadline request remains unresolved. Never
  clean up another task.

Successful observations always contain `fetched:true` and `operation_hash` equal
to the returned operation hash. Additional fields:

- Diagnostic/read: `request_terminal:true` only after observing completion or
  termination of the actual request. An uncertain asynchronous request remains
  charged; a lost response is not a terminal observation.

- Public write: actual `url`, `created_at` as UTC epoch seconds, `payload_sha256`
  equal to SHA-256 of the canonical returned payload (sorted keys, compact JSON,
  UTF-8, no newline). Confirm the fetched public content matches that payload and
  its session/content marker. Capture the actual result of an in-flight request
  even after expiry. No extra fetch for follow-up starts after deadline; if the
  original request did not provide a fetched result, leave it uncertain for an
  explicitly authorized reconciliation exercise.
  Record `timestamp_precision:1` for a second-resolution API timestamp, otherwise
  omit it or use zero. At most one second of precision tolerance is admitted;
  the retained remote timestamp still determines the original deadline.
- Launch: `thread_id`, accepted `state` (`preparing`, `running`, `idle`,
  `completed`), after reading the actual ordinary thread. Failed launch is not a
  reporting thread. Lost response requires listing likely threads before retry.
- Schedule: actual `task_id`, `next_run` and `bound_thread` equal to reporting
  thread. Creation after an expiry race is retained, then cleaned up.
- Cleanup: owned `task_id`, `disabled_or_absent:true` after host verification.

The public content hash is an operator observation, not a cryptographic GitHub
receipt. Remote exactly-once delivery is not promised. Root locking prevents
simultaneous local state mutations; durable prepared/sent intents prevent a second
admission while the first remote request is in flight. The `send`/host-call boundary
still depends on the agent invoking the tool immediately and respecting its guard.

Confirmed reads and diagnostics are never permanently deduplicated: each wake
gets a fresh occurrence, with bounded retry identity via `read_key`. Confirmed
supporting evidence deduplicates per canonical destination across issues, Ideas,
comments and replies. Rephrasing or asking for the same evidence does not make it
new. Changed claims, ownership and expectation documentation are part of evidence
identity, so factual corrections can be published. A suppressed reply does not
mark its request answered. Retain it outstanding or send a short reference reply:
set `reference_operation` to the already-published matching evidence operation,
with exactly `{"body":"Evidence is already recorded here: URL."}` using that
operation's actual URL. The helper validates this link-only response and binds it
to the request version without repeating the data. Diagnostics require active
accounting under the finite investigation budget throughout follow-up; periodic
monitoring reads use the separate fixed deadline after publication.
An in-flight investigative read/diagnostic, including an uncertain one, must finish
before pausing its budget. Whether a request is budgeted is frozen at preparation;
publication during reconciliation cannot remove its original budget accounting.

Generated requests carry `transport` plus exact arguments. For `github-rest`, use
the returned method, endpoint and `input` JSON with authenticated `gh api`; for
`github-graphql`, submit the returned query and variables to `gh api graphql` as a
JSON input file. No shell interpolation. Prefer the connected issue creation tool
when sufficient, with the generated `arguments`. Discussion observations also need
the fetched `repository_id` and `ideas_category_id`; Discussion replies need
`object_url` matching the canonical target and its fetched `discussion_id`.
Legacy T3 destination observations include
`repository_url:"https://github.com/pingdotgg/t3code"`. Other upstreams use the
verified route below. Discover and fetch these IDs,
never infer them from model output. Missing supported transport retains the draft.
Native requests use `t3-thread-launch`, `t3-schedule-task` or
`t3-delete-scheduled-task`, with generated `arguments`. Map actual `threadId`/`status`,
`scheduledTaskId`/`nextRunAt`/`boundThreadId` and verified deleted/disabled host state
to the observation fields above. This mapping does not itself verify host state.


## Upstream reporting routes

New non-T3 defects use outcome `upstream-defect`, an `upstream_name`, and:

```json
{"reporting_route": {"method": "github", "destination": "https://github.com/OWNER/REPO",
 "documentation": "https://github.com/OWNER/REPO/blob/main/CONTRIBUTING.md",
 "ownership_evidence": "observed package origin and authoritative upstream link"}}
```

Methods are `github`, `web` and `email`. Web intake uses the documented HTTPS
tracker/form URL; email uses exactly one `mailto:` recipient without query headers.
No known usable method means outcome `external` and a private draft. T3 legacy
outcomes retain their original destination without rewriting existing state.

For GitHub, `destination_observation.repository_url` must equal the recorded
repository, and generated REST/GraphQL/connected requests use that repository.
For web/email, use `transport: documented`, with current
`destination_observation.reporting_destination` and `method_documentation` equal
to the route. The generated request names the method, destination, canonical target
(if replying) and sanitized title/body. Dispatch it through a sufficient connected
tool or the documented tracker API. Never reinterpret its destination as shell code.
A missing supported transport holds publication; the helper performs no network I/O.

Non-GitHub duplicate searches use `channels_complete: true` and a nonempty `channels`
list of `{channel, status, evidence}`, where status is `searched` or documented
`not-applicable`, plus the ordinary queries, reason and inspected candidates.
Unsupported or failed search stays incomplete. GitHub keeps the existing issue and
Discussion completeness fields, including documented unavailable/not-applicable
channels in the search reasoning.
When every channel is documented as not-applicable, queries may be empty. Never
invent a search to report through a documented private intake. A searched channel
still requires the actual queries; failed or unsupported searches do not pass.

For web/email completion, supply the ordinary fetched/content-matching observation
and a nonempty `receipt_reference` from the actual ticket or sent-message receipt.
Web receipt URLs must belong to the documented tracker's origin. Email retains the
documented `mailto:` URL and records the actual sent-message identifier as the
receipt reference. Never manufacture an email ticket URL. A confirmed response's
actual creation/sending time starts the same fixed 30-minute window. Preserve the
receipt reference when handing the work back, including when no public URL exists.
Email `comments` observations also name `receipt_reference` matching an owned
sent-message receipt, so unrelated mail at the same recipient is not follow-up.
