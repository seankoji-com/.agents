# Configuration audit

1. Resolve the target provider and exact settings paths from the request and the
   active host configuration. Do not infer the target from the model running this task.
2. Run `python3 PKG/scripts/audit.py --provider <name> --settings <path>` for each file.
   The deterministic audit flags known broad permission patterns, duplicate exact
   rules, and risky sandbox settings. It never emits the settings contents or secrets.
3. For Claude transcript scanning, run `scan_perms.py --json` only when requested.
   Correlated success/failure counts are observational; frequent calls do not imply
   denied permission or justify allowlisting them. Do not publish transcripts.
4. Compare global, project, and local scope against current provider documentation.
   Exact duplicate strings may be redundant; quote variants, bare commands, and globs
   are not necessarily equivalent. Record the source and version for syntax claims.
5. Present minimal proposed changes with reasons and their effect on access. Never
   broadly allow shells, interpreters, installers, arbitrary MCP tools, or remote
   commands. Do not disable sandboxing or approvals to reduce prompt frequency.
6. Apply only explicitly authorized edits. Inspect symlink destinations, preserve
   unrelated keys, back up original bytes, validate the full file, and verify the
   provider actually loads the result. Stop on a denied settings write; do not reroute
   the write through another tool. Restore a backup if validation fails.
7. Report findings, applied changes, parse results, and live verification separately.
   A parseable file is not evidence that the provider enforces it. Do not commit,
   push, or persist personal learnings unless separately requested.
