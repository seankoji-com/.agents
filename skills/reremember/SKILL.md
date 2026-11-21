---
name: reremember
description: Use when a remembered claim is contradicted by the code, when asked to correct or consolidate what the project remembers, or when a session settles a decision later work depends on.
---

# Keep project memory accurate

Memory is a past record, not current state. A claim that was true when someone
wrote it can be false now. This skill covers what deserves a durable record, how
to write it so a later agent can check it, and how to replace it when it stops
being true. The host's memory guide owns retrieval: search, read and reflect.

## When this applies

- A remembered claim is contradicted by current code, git or the source it cites.
- The user asks to correct, consolidate or audit what the project remembers.
- A session settles a decision that later work depends on.

A request to remember the current conversation alone is not this skill. The host
usually captures sessions automatically.

## Authority

You may correct a claim you have just disproved, and record a decision the
session has settled, without asking first. Anything else needs a request.

Never record secrets or credentials, personal data, transcripts, transient state
such as branch names or process ids, speculation, or a restatement of what a
commit, pull request or issue already says better. Never write memory into
`AGENTS.md`, `CLAUDE.md` or another instruction file: a stale copy there can
override the user's live instructions.

## The loop

1. **Read first.** Search for the subject and its owning record. Read the whole
   record. One subject gets one record, so do not add a parallel one.
2. **Verify before trusting.** Check the claim against current code, git or its
   cited source. When you cannot verify it, label it unverified instead of
   repeating it as fact.
3. **Judge durability.** Write only when all three hold: it outlives this
   branch, a new agent would act differently knowing it, and no commit, pull
   request or issue already says it better. When it fails, put the fact where it
   belongs and say where.
4. **Write in shape.** Claim, scope, exact values verbatim, evidence, date,
   supersedes. Follow the [document reference](references/memory-document.md) when writing the record.
5. **Supersede with the backend you have.**
   - A backend that edits records in place and reads them back synchronously:
     edit the owning record and read it back.
   - A backend that appends and consolidates: reuse the exact title to target
     the same document id. When you cannot identify the owning document, write
     `Correction: <topic>` stating what was claimed, what is true and the
     evidence.
   - Initiatives: use the native initiative updater. Do not hand-format a
     generated page.
   - Confirm only what the backend acknowledges. Do not claim retrieval changed.
     Derived pages rebuild on the backend's schedule, which may be hourly. A
     later search confirms it.
6. **No backend.** Do nothing and say nothing when acting on your own. When the
   user explicitly asked you to remember something, say once that no memory
   backend is configured. Do not invent a store.

## Hindsight on this machine

The host guide is `hindsight-coding-agent`. It owns tool names, correction
wording and configuration, so do not restate them here.

- `hindsight_ingest_document(title, content)` returns `{ ok, doc_id }`. The id
  is a slug of the title, so reusing a title targets the same document.
- There is no document-read tool. Knowledge pages refresh on a cron, hourly by
  default. Confirm with a later search, not an immediate read.
- `hindsight_capture_initiative(title, summary, relates_to_page_id)` updates an
  initiative page. The page is generated, so do not format it yourself.

## Finish

Report what you wrote: the title, the id or acknowledgement the backend returned,
and whether the change is visible now or waits for the backend to rebuild. When
you could not verify the old claim, say so rather than implying the new one is
settled.
