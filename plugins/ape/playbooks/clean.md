# Clean research files

Inspect the exact workspace and summarize what would be removed. Cleanup requires
the operator's explicit deletion authorization; an ordinary study does not imply it.
Run `bash PKG/scripts/clean-ape-workspace.sh <workspace> --confirm` to remove clones,
or add `--all` only when deleting reports and the workspace is also authorized.
The helper checks containment under the research root. Never bypass a rejected path.
