# Launch readiness: 12 October 2026

The documentation refresh is prepared locally. Public promotion still depends on
delivery of the current catalog and an installed live workflow.
This is a dated handoff, not an automatically updated release status.

## Verified locally

| Check | Result |
| --- | --- |
| Regression suite | Suite passed on Python 3.12; loopback fixtures ran with socket access |
| Documentation checks | Local Markdown links, catalog coverage and entry budgets passed |
| Site | Strict MkDocs Material 9.7.7 build passed |
| Rendered targets | 26 HTML pages and 1,479 local link, asset and anchor targets checked |
| Shell examples | 34 documented shell blocks passed `bash -n` |
| Installed artifact | Isolated release-tree setup installed all five snapshots and adapters; integrity, prompts and relocated settings audit passed |
| Browser | Homepage and installation inspected in light/dark schemes; five plugin pages and CLI checked at 390px; homepage, first workflow, architecture and historical results checked at 768px; desktop checked at 1280px |
| Interaction | Search returned relevant results; code-copy controls present and exercised; keyboard focus visible |
| Privacy | Built homepage and guides made no third-party resource requests after disabling the theme's GitHub metadata fetch |
| Share image | Social PNG regenerated at 1200 × 630 from the current SVG source |

The 200% CSS scaling probe had no page overflow. Native browser zoom could not be
changed through the preview keyboard transport, so native 200% zoom is unverified.
Reduced-motion CSS was inspected; no animated recording remains on the homepage.

## Remaining gates

1. **Independent review passed.** OpenCode Qwen 3.8 Max approved the full diff
   against refreshed `origin/master`, with no blocker or major findings. It independently
   passed 510 tests across 58 modules and checked installed CLI behavior. All eight
   minor findings are addressed or verified: obsolete install-line CSS and design
   wording removed; release-channel cross-references added; adapter-removal refusal
   clarified; historical metadata corrected; demo elision labelled; the rendered
   target count rerun; source setup wording corrected.
2. **Release alignment.** The public latest release and tap formula still point to
   `v0.4.0`. The tap's test still expects the retired prompt-builder plugin. This
   checkout has five plugin manifests at `1.0.0`. Publish and verify the intended
   catalog before promoting the new behavior through the Homebrew install command.
3. **Current live workflow.** The published provider ledger describes an earlier
   imps gate. Run the installed current gate in T3 with a bounded task, retain its
   checks and independent review, and inspect its final report. Do not describe
   historical passes as current compatibility.
4. **Delivery.** This refresh is prepared for a PR. Current-head hosted CI, merge,
   release/tap update and Pages deployment acceptance remain separate gates. Follow [the release procedure](../docs/releasing.md).

No announcement, repository-settings update or deployment was performed.

## Review dispositions

The resumed independent review's release-channel blocker is addressed in the docs
by making current source installation the default and marking Homebrew v0.4.0 as
a different catalog. Publishing the next release remains a launch gate. Its CLI
exit-code finding is fixed, alongside optional arguments, snapshot path wording,
source upgrades, adapter removal, upgrade-page copy and unused chooser CSS.

Optional media are linked from the launch kit; their archive content identifiers
are distinguished from Git revision identifiers. Provenance records and manifest
metadata remain maintainer data; the visitor journey does not lead with them.
The reviewer independently confirmed the full suite total of 510 tests. Only explicit changed paths will be staged.
