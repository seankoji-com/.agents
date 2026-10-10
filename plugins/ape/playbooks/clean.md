# Clean research files

Inspect the exact workspace and summarize what would be removed. Cleanup requires
the operator's explicit deletion authorization; an ordinary study does not imply it.
Run `bash PKG/scripts/clean-ape-workspace.sh <workspace> --confirm` to remove clones,
or add `--all` only when deleting reports and the workspace is also authorized.
The helper requires a direct child of the research root and a matching ownership marker
created by `init-workspace.sh`. It rejects unmarked legacy directories and individual
report folders. Never bypass a rejected path or add a marker to adopt unrelated data.
