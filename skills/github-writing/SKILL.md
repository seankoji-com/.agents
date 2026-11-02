---
name: github-writing
description: Use whenever drafting or editing LLM-written GitHub issues, pull requests, comments, reviews, discussions or release notes on the user's behalf.
---

# Disclose AI-written GitHub prose

## Identify the writer

Apply this to prose bodies and replies, including inline review comments and
updates to existing text. Keep repository templates, factual evidence and human
text. The byline identifies who wrote the prose, separately from who wrote or
reviewed the code and which account submits it.

Identify the actual writing model from host-reported identity or the delegated
writer's verified report. Briefs label the dispatch target as expected identity;
the writer confirms its active host-reported identity, which takes precedence.
Report any mismatch. Use the known model/version; do not infer it from the
harness, provider alias or API account. Record unknown identity explicitly.
Credit each model that materially wrote the retained prose. A coordinator that
only posts another model's draft is not its writer. A reviewer belongs in the
existing review attribution, unless it also wrote retained prose.
For multiple agents, new assertions, reasoning or substantially rewritten wording
earn writer credit. Formatting, link fixes, template placement and light copy
edits alone do not add another writer.

Identify the represented operator from the request and standing instructions,
using authenticated account evidence to verify the handle. Do not hard-code the
library owner's handle for another user or infer representation from repository
ownership. When the user directs the write and the posting account is verified
as theirs, use that login as the operator. A bot or shared account's login alone
does not identify the represented human. If the operator is unknown, omit the
on-behalf-of clause. If the model is unknown, use "an AI assistant, model identity
unavailable" instead of guessing.

## Add a visible byline

Start each new prose body with this GitHub NOTE block, followed by a blank line.
Preserve its Markdown and substitute the verified writer and operator:

```markdown
> [!NOTE]
> _Written by **GPT-6.1 Sol** on behalf of @seankoji_
```

For multiple writing models, name each in bold in first-contribution order,
using commas and a final "and". For example:

```markdown
> [!NOTE]
> _Written by **Claude Opus 5.5** and **GPT-6.1 Sol** on behalf of @seankoji_
```

The chosen format authorises mentioning the verified operator, including when
a bot posts. It authorises no other mentions or notifications. Carry the writer
identities and this skill's path in delegated writing assignments and returns.
The parent preserves those identities when posting or merging drafts.

For a rewrite, move the applicable AI byline to the top of its scope and update
it once, preserving still-applicable writer credits and human signatures.
In a wholly AI-written body, put the NOTE before the body and its template
headings. Preserve required headings and checklist answers. If a required
repository format conflicts with this placement, preserve the draft and report
the conflict.

In a mixed human/AI body, section scope takes precedence over that placement.
Put the NOTE immediately before each added or rewritten passage. Follow it with
a plain scope sentence, such as "This byline covers only the Verification section
below." Keep the NOTE wording unchanged. Distinct passages may have distinct
bylines; they are not duplicates. Preserve untouched human text and historical
evidence without attributing it to a model.

A top-level `> [!NOTE]` byline counts as disclosure. An example inside a code
fence or nested quotation such as `> >` does not. On retries and updates, reconcile
the byline for the same passage instead of appending it again.

Use prose bodies, not titles or metadata fields, for bylines. A bodyless or
metadata-only action does not require a new comment solely to add a byline.
Git commit messages and code co-author trailers retain their existing policies.
When explicitly setting a merge commit message, follow commit policy without
injecting this prose byline. A repository's existing squash default may copy the
PR body and its byline; that is not a change to commit policy or reason to rewrite
history. This rule applies to newly drafted or edited text, not a bulk rewrite
of old posts.

Do not add private session links, prompts, transcripts, credentials or machine
paths. Do not claim human review or approval unless it actually occurred. The
byline does not replace the PR's contributor roles, scopes or review outcomes.

## Verify the outgoing text

Before an authorised write, check the repository's contribution and AI-use rules
and required format. Reuse applicable policy evidence already obtained by the
calling workflow. If the destination forbids the submission or required
disclosure, preserve the draft and report the conflict rather than silently
removing the byline or disguising AI involvement.

Read back each created or edited body and verify the content and byline are
present, correctly attributed and not duplicated. Reconcile an uncertain write
before retrying. A read-back failure remains a verification gap, not permission
to repost. A draft includes the byline but is still a draft.

Beyond the required operator mention, this skill grants no authority to post,
notify people, approve a PR, change metadata or share private material.
Use the caller's existing authority and
submission procedure.
