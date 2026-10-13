# Clean research files

Cleanup is direct and deterministic. Never create a job or delegate it.

Inspect the exact workspace and summarize what would be removed. Cleanup requires
the operator's explicit deletion authorization; an ordinary study does not imply it.
Ask through the native question picker with "keep the workspace" as an option; until
the operator answers, delete nothing.
Run `bash PKG/scripts/clean-ape-workspace.sh <workspace> --confirm` to remove clones,
or add `--all` only when deleting reports and the workspace is also authorized.
The helper requires a direct child of the research root and a matching ownership marker
created by `init-workspace.sh`. It rejects unmarked legacy directories and individual
report folders. Never bypass a rejected path or add a marker to adopt unrelated data.
Run the helper immediately after the authorization so the ownership check is current.
