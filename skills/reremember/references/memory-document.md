# Memory document shape

Use this shape for a decision, a correction or an operational fact. The reader is
a later agent that has to decide whether to trust the claim.

## Template

```text
Title: <short noun phrase naming the subject>
Claim: <one sentence a later agent can act on>
Scope: <repository, component, version or environment>
Values: <exact strings, numbers, paths and commands, verbatim>
Evidence: <file:line, commit, command output or URL; date checked>
Supersedes: <earlier document title and date, or none>
```

## Examples

### A decision

```text
Title: Retry policy for the ingest client
Claim: The ingest client retries 429 and 5xx responses, stops after 30 seconds
  and never retries a 4xx other than 429.
Scope: src/ingest/client.ts, all environments
Values: retryable = 429, 500, 502, 503, 504; max_elapsed = 30s
Evidence: src/ingest/client.ts:118-140; commit 4f2a1c9; checked 2026-11-19
Supersedes: "Retry policy: every 5xx, three attempts" (2025-06-02)
```

### A correction

```text
Title: Correction: retry policy 4xx set
Claim: Earlier memory said the client retried 408. It does not; 408 is not in
  the retryable set.
Scope: src/ingest/client.ts
Values: retryable does not include 408
Evidence: src/ingest/client.ts:121; tests/ingest/retry.test.ts:44; checked 2026-11-19
Supersedes: "Retry policy for the ingest client" (2025-06-02)
```

### An operational fact

```text
Title: Deploy gate for the API
Claim: A production deploy needs a green ci/api run on the exact merge commit.
Scope: .github/workflows/deploy.yml
Values: required check = ci/api
Evidence: .github/workflows/deploy.yml:22; checked 2026-11-19
Supersedes: none
```

## Do not store

- Credentials, tokens, keys and connection strings.
- Personal data.
- Transcripts or chat logs.
- Branch names, process ids and local paths that change per machine.
- Speculation, a preference stated once, or "we should" without a decision.
- Anything a commit, pull request or issue already records.

## Anti-patterns

- **Append-only contradiction.** Adding "actually..." beside the old claim leaves
  both retrievable. Replace the claim, or write a correction that names it.
- **Decision-shaped speculation.** "We should probably use Postgres" is not a
  decision. Record the decision, its scope and its evidence, or record nothing.
- **Code restatement.** Copying a function body duplicates code that will change.
  Record why it exists and what constrains it.
