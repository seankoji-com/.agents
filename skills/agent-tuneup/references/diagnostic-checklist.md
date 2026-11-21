# Diagnostic checklist

Consult the matching section when troubleshooting a specific failure class.
Verify the installed host's version and official schema rather than assuming
behavior carries across hosts.

## Skill discovery

- **Location and links:** Check whether the host skips symlinks, vendor
  subfolders or `.gitignore`d paths, and confirm the skill lives in the active
  project or user discovery root.
- **Frontmatter:** Verify `SKILL.md` starts with valid YAML frontmatter,
  `name` matches the directory name, `description` is a single-line string and
  `disable-model-invocation: true` (or `allow_implicit_invocation: false`) is
  not blocking automatic selection.
- **Session freshness:** Most hosts index skills at session start; verify
  changes in a fresh session rather than an already-open conversation.

## MCP connections

- **Transport and command:** Check stdio vs HTTP/SSE mismatch, missing binary
  on `PATH`, wrong working directory or relative script paths.
- **Environment and secrets:** Confirm required environment variables, tokens
  and local profiles are injected into the server's runtime environment (not
  only an interactive shell profile).
- **Startup vs visibility:** Inspect stderr/startup handshake logs first, then
  check whether the server connected cleanly while host permissions, lazy-load
  settings or tool filters hide its tools.

## Hooks

- **Event and matcher:** Confirm the hook event name and tool/command matcher
  pattern match the host's current format and case sensitivity.
- **Execution environment:** Inspect executable permissions read-only (for
  example with `ls -l` or `stat`), plus the shebang, interpreter path and
  assumed working directory.
- **Exit codes and layering:** Verify how the host interprets non-zero exit
  codes (hard block vs warning vs silent ignore) and whether a local, project
  or user settings layer shadows the hook definition.

## Permission precedence

- **Host matching model:** Verify the installed host and version's actual merge
  and rule-matching order (for example, deny-overrides-allow vs
  last-matching-rule-wins such as OpenCode V2 vs first-match) rather than
  assuming deny always wins.
- **Layer interaction:** Check effective precedence across host runtime mode
  (`approval-required`, `auto`, `full-access`), enterprise/policy overrides,
  local overrides, project settings and user settings.
- **Drift and evidence:** Check whether dotfiles or a sync job overwrites a
  generated copy, and separate observed tool calls from actual approval policy
  (an observed call does not prove a rule authorized it).
