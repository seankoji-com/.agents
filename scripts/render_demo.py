#!/usr/bin/env python3
"""Render the homepage terminal recording as a self-contained animated SVG.

No JavaScript player, no GIF. Commands are typed with a stepped clip animation and
output lines appear at their timestamps. Readers who prefer reduced motion see the
final frame immediately. The transcript below is scripted from real CLI output; the
T3 thread section is an illustration of what ``doctor`` reports, not a live call.

    python3 scripts/render_demo.py            # writes docs/assets/demo.svg
    python3 scripts/render_demo.py --check    # exit 1 if the committed file is stale
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'docs' / 'assets' / 'demo.svg'

# (kind, text). kind: cmd = typed at the prompt, out = printed, note = dim aside, gap = blank.
FRAMES = [
    ('cmd', 't3-plugins install imps'),
    ('out', '{"ok": true, "data": {"action": "install", "plugin": "imps", "version": "0.2.0+gdf8e8c7", "files": 48}}'),
    ('cmd', 't3-plugins doctor imps'),
    ('out', '{"plugin": "imps", "ok": true, "errors": [], "scope": "installed file integrity; provider behavior not tested"}'),
    ('cmd', 't3-plugins prompt imps doctor'),
    # catalog.py prints the absolute entry path; the home directory is shown as ~ so
    # no machine path ships in the repository (tests/test_contract.py enforces that).
    ('out', 'Read ~/.local/share/t3-plugins/imps/current/entry.md and run: doctor'),
    ('gap', ''),
    ('note', 'pasted into a T3 thread, on whichever provider is selected'),
    ('out', 'imps doctor'),
    ('out', '  python3 3.12.6 · git 2.46.0 · state root writable'),
    ('out', '  T3 tools: orchestrator_capabilities responded'),
    ('out', '  child-capable providers: codex, claudeAgent, antigravity'),
    ('out', '  operations here: doctor run resume status cancel verification-init'),
]

MIN_WIDTH = 960
CHAR_WIDTH = 0.6          # IBM Plex Mono advance, in em
LINE_HEIGHT = 24
PAD_X = 28
PAD_TOP = 34
FONT_SIZE = 15
CHAR_SECONDS = 0.045      # typing speed
LINE_SECONDS = 0.35       # pause before an output line
CMD_PAUSE = 0.6           # pause after a command finishes typing


def build(frames=FRAMES) -> str:
    height = PAD_TOP + LINE_HEIGHT * len(frames) + 22
    # Wide enough for the longest line (commands carry a two-character prompt), so
    # nothing is clipped at the right edge; the page scales the SVG to fit.
    longest = max(len(text) + (2 if kind == 'cmd' else 0) for kind, text in frames)
    width = max(MIN_WIDTH, round(2 * PAD_X + longest * FONT_SIZE * CHAR_WIDTH))
    t = 0.4
    body = []
    styles = []
    for i, (kind, text) in enumerate(frames):
        y = PAD_TOP + LINE_HEIGHT * i
        if kind == 'gap':
            continue
        escaped = html.escape(text, quote=False)
        if kind == 'cmd':
            chars = len(text)
            typing = round(chars * CHAR_SECONDS, 2)
            styles.append(f'#demo-l{i}{{animation:demo-reveal {typing}s steps({chars},end) {t:.2f}s both}}')
            body.append(
                f'<text id="demo-l{i}" x="{PAD_X}" y="{y}" class="cmd">'
                f'<tspan class="prompt">$ </tspan>{escaped}</text>')
            t += typing + CMD_PAUSE
        else:
            styles.append(f'#demo-l{i}{{animation:demo-appear 0.01s linear {t:.2f}s both}}')
            cls = 'note' if kind == 'note' else 'out'
            body.append(f'<text id="demo-l{i}" x="{PAD_X}" y="{y}" class="{cls}">{escaped}</text>')
            t += LINE_SECONDS
    total = round(t, 1)
    # Every selector is scoped to the recording's root: the SVG is inlined into the
    # homepage, where a bare `text` rule would restyle every other diagram.
    css = (
        ".demo-rec text{font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;"
        f"font-size:{FONT_SIZE}px;fill:var(--sp-ink,#1f2a24);white-space:pre}}"
        ".demo-rec .prompt{fill:var(--sp-ink-soft,#55615a)}"
        ".demo-rec .out{fill:var(--sp-ink-soft,#55615a)}"
        ".demo-rec .note{fill:var(--sp-ochre-text,#80601a);font-style:italic}"
        ".demo-rec .cmd{clip-path:inset(0 100% 0 0)}"
        "@keyframes demo-reveal{to{clip-path:inset(0 -2% 0 0)}}"
        "@keyframes demo-appear{from{opacity:0}to{opacity:1}}"
        "@media(prefers-reduced-motion:reduce){.demo-rec text{animation:none!important;clip-path:none!important;opacity:1!important}}"
        + ''.join(styles)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="demo-rec" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Terminal recording: installing imps, running doctor, and pasting the generated prompt into a T3 thread. Total length {total} seconds.">\n'
        f'<style>{css}</style>\n'
        f'<rect width="{width}" height="{height}" fill="var(--sp-paper,#eef0e8)"/>\n'
        f'<text x="{PAD_X}" y="18" style="font-size:11px;letter-spacing:.04em;fill:var(--sp-ink-soft,#55615a)">'
        f'scripted recording · {total}s · no live model call</text>\n'
        + '\n'.join(body) + '\n</svg>\n'
    )


def display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true', help='fail if docs/assets/demo.svg is out of date')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    rendered = build()
    if args.check:
        current = args.output.read_text() if args.output.is_file() else ''
        if current != rendered:
            print(f'{display(args.output)} is stale; run python3 scripts/render_demo.py', file=sys.stderr)
            return 1
        print(f'{display(args.output)} is current.')
        return 0
    args.output.write_text(rendered)
    print(f'wrote {display(args.output)} ({len(rendered)} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
