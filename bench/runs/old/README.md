# Old baseline (imps at `6e4cf82`)

Status: **not run**. Stage 1 prepared the package, the workspaces and the launch sheets,
but the executor thread could not register the workspaces as T3 projects:

```text
t3_project_create → capability_denied: "Changing projects or environment settings needs
a live full-access/default calling thread or a full-access client."
```

The executor ran in runtime mode `auto`. Per the protocol's [Fallback](../../protocol.md#fallback),
the runs wait for the owner.

| Slot | Task | Workspace ID | Fixture commit |
| --- | --- | --- | --- |
| audit-test | transcript audit | `261ebb6f` | `1dd7899` |
| a1 | A | `b86fb41b` | `1dd7899` |
| a2 | A | `110d918b` | `1dd7899` |
| b1 | B | `d1761f60` | `0995b69` |
| b2 | B | `10ae29d8` | `0995b69` |

Workspaces are under `~/t3-plugins-bench/ws/`. The filled `t3_project_create` and
`t3_thread_launch` arguments for each slot, with the frozen worker prompt, are in
`~/t3-plugins-bench/private/launch/` (`audit-test.json`, `old/<slot>.json`).

[package.json](package.json) and [install-manifest.json](install-manifest.json) record the
installed package. Each finished attempt adds `<slot>/summary.json`, `<slot>/output/`
and `<slot>/report.md` through `bench/tools/summarise.py`.
