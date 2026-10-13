#!/usr/bin/env python3
"""Render a recorded terminal session as an animated SVG, and optionally as video.

The input is a transcript written by ``scripts/capture_terminal.py``: real commands,
real output, and the time each output line arrived. Nothing here invents output.
Commands are typed at a fixed speed (the only simulated part, and the caption says
so); output lines appear at their recorded offsets. Long lines wrap at the terminal
width as they would in a terminal, and the view scrolls to keep the newest rows.

    python3 scripts/render_demo.py            # writes docs/assets/demo.svg
    python3 scripts/render_demo.py --check    # exit 1 if the committed SVG is stale
    python3 scripts/render_demo.py --video    # also writes quickstart.mp4, .webm and the poster PNG

The SVG has no script and no external references, and its styles are scoped to its
``.demo-rec`` root so it can be inlined into a page. ``prefers-reduced-motion`` shows
the final frame. ``--video`` needs headless Chrome (to rasterise frames with the
bundled fonts) and ffmpeg; it stops with a clear message when either is missing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'docs' / 'assets'
TRANSCRIPT = ASSETS / 'recordings' / 'quickstart.json'
OUTPUT = ASSETS / 'demo.svg'
VIDEO_STEM = ASSETS / 'quickstart'
POSTER = ASSETS / 'quickstart-terminal.png'

COLS = 72                 # terminal width in characters
ROWS = 22                 # visible rows
CHAR_WIDTH = 0.6          # IBM Plex Mono advance, in em
FONT_SIZE = 14
LINE_HEIGHT = 20
PAD_X = 20
HEADER = 34               # caption band above the terminal rows
PAD_BOTTOM = 14
CHAR_SECONDS = 0.04       # simulated typing speed
TYPE_CAP = 1.1            # longest time spent typing one command
ENTER_PAUSE = 0.3         # between the last typed character and the command starting
STEP_PAUSE = 0.7          # after a command's output, before the next prompt
START = 0.4
HOLD = 3.0                # final frame hold in the video
FPS = 30
HIGHLIGHT = '"ok": true'

LIGHT = {'ink': '#1f2a24', 'ink-soft': '#55615a', 'paper': '#eef0e8', 'fern': '#2f6b4f',
         'ochre-text': '#80601a', 'rule': '#c6cdbf'}


class RenderError(RuntimeError):
    """A prerequisite for video rendering is missing."""


def load(path: Path = TRANSCRIPT) -> dict:
    return json.loads(path.read_text())


def wrap(text: str, cols: int = COLS) -> list[str]:
    """Hard-wrap at the terminal width, as a terminal does; an empty line keeps one row."""
    return [text[i:i + cols] for i in range(0, len(text), cols)] or ['']


def timeline(session: dict, cols: int = COLS) -> tuple[list[dict], float]:
    """Rows in display order with the time each appears, plus the total length.

    A command row has ``typed`` (start, duration); output rows have ``at``."""
    rows, t = [], START
    for step in session['steps']:
        command = step['command']
        typing = round(min(TYPE_CAP, len(command) * CHAR_SECONDS), 2)
        rows.append({'kind': 'cmd', 'text': command, 'at': t, 'typed': (t, typing)})
        began = t + typing + ENTER_PAUSE
        for offset, text in step['lines']:
            for part in wrap(text, cols):
                rows.append({'kind': 'out', 'text': part, 'at': round(began + offset, 3)})
        t = began + step['seconds'] + STEP_PAUSE
    return rows, round(t, 1)


def scroll_at(rows: list[dict], t: float, visible: int = ROWS) -> int:
    shown = sum(1 for r in rows if r['at'] <= t)
    return max(0, shown - visible)


def caption(session: dict, total: float) -> str:
    env = session['environment']
    day = dt.date.fromisoformat(session['recorded'])
    return (f"recorded {day.day} {day:%b %Y} · {session['commit']} · {env['os']} · empty HOME · "
            f"real output, simulated typing · {total:.1f}s")


def text_spans(text: str, cls: str) -> str:
    """Escape a row, colouring the literal ``"ok": true`` in success rows."""
    if cls != 'out' or HIGHLIGHT not in text:
        return html.escape(text, quote=False)
    parts = text.split(HIGHLIGHT)
    mark = f'<tspan class="ok">{html.escape(HIGHLIGHT, quote=False)}</tspan>'
    return mark.join(html.escape(p, quote=False) for p in parts)


def geometry(cols: int = COLS, visible: int = ROWS) -> tuple[int, int]:
    width = round(2 * PAD_X + (cols + 2) * FONT_SIZE * CHAR_WIDTH)
    height = HEADER + visible * LINE_HEIGHT + PAD_BOTTOM
    return width, height


def _style(colours: dict | None) -> str:
    def c(name):
        return colours[name] if colours else f'var(--sp-{name},{LIGHT[name]})'
    return (
        ".demo-rec text{font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;"
        f"font-size:{FONT_SIZE}px;fill:{c('ink')};white-space:pre}}"
        f".demo-rec .prompt{{fill:{c('fern')}}}"
        f".demo-rec .out{{fill:{c('ink-soft')}}}"
        f".demo-rec .ok{{fill:{c('fern')}}}"
        f".demo-rec .cap{{font-family:'IBM Plex Sans',system-ui,sans-serif;font-size:12px;fill:{c('ink-soft')}}}"
        f".demo-rec .bg{{fill:{c('paper')}}}"
        f".demo-rec .rule{{stroke:{c('rule')};stroke-width:1}}"
    )


def build(session: dict | None = None, at: float | None = None, colours: dict | None = None) -> str:
    """The recording as SVG. With ``at``, a static frame at that time (for video)."""
    session = load() if session is None else session
    rows, total = timeline(session)
    width, height = geometry()
    animated = at is None
    styles, body = [], []
    for i, row in enumerate(rows):
        y = (i + 1) * LINE_HEIGHT - 5
        if row['kind'] == 'cmd':
            start, typing = row['typed']
            chars = len(row['text'])
            if animated:
                styles.append(f'#demo-l{i}{{animation:demo-reveal {typing}s steps({chars},end) {start:.2f}s both}}')
                text = html.escape(row['text'], quote=False)
            else:
                if at < start:
                    continue
                done = chars if typing == 0 else min(chars, int(chars * (at - start) / typing))
                text = html.escape(row['text'][:done], quote=False)
            # The prompt and the command are separate <text> elements: clip-path and
            # opacity animate reliably on text, not on tspans.
            cx = round(PAD_X + 2 * FONT_SIZE * CHAR_WIDTH, 1)
            if animated:
                styles.append(f'#demo-p{i}{{animation:demo-appear .01s linear {start:.2f}s both}}')
            body.append(f'<text id="demo-p{i}" x="{PAD_X}" y="{y}" class="prompt">$</text>'
                        f'<text id="demo-l{i}" x="{cx}" y="{y}">{text}</text>')
        else:
            if not animated and row['at'] > at:
                continue
            if animated:
                styles.append(f'#demo-l{i}{{animation:demo-appear .01s linear {row["at"]:.2f}s both}}')
            body.append(f'<text id="demo-l{i}" x="{PAD_X}" y="{y}" class="out">{text_spans(row["text"], "out")}</text>')
    if animated:
        # One keyframe per scroll change, held until the next (step-end).
        stops, last = [], 0
        for t in sorted({r['at'] for r in rows}):
            offset = scroll_at(rows, t)
            if offset != last:
                stops.append((t, offset))
                last = offset
        final = last
        frames = ['0%{transform:translateY(0)}']
        frames += [f'{100 * t / total:.3f}%{{transform:translateY({-n * LINE_HEIGHT}px)}}' for t, n in stops]
        frames.append(f'100%{{transform:translateY({-final * LINE_HEIGHT}px)}}')
        styles.append('@keyframes demo-scroll{' + ''.join(frames) + '}')
        styles.append(f'.demo-rec .demo-scroll{{animation:demo-scroll {total}s step-end both}}')
        scroll_attr = ''
    else:
        final = scroll_at(rows, at)
        scroll_attr = f' transform="translate(0 {-final * LINE_HEIGHT})"'
    css = (
        _style(colours)
        + ("@keyframes demo-reveal{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 -2% 0 0)}}"
           "@keyframes demo-appear{from{opacity:0}to{opacity:1}}"
           "@media(prefers-reduced-motion:reduce){.demo-rec text{animation:none!important;"
           "clip-path:none!important;opacity:1!important}"
           f".demo-rec .demo-scroll{{animation:none!important;transform:translateY({-final * LINE_HEIGHT}px)}}}}"
           if animated else '')
        + ''.join(styles)
    )
    label = (f'Terminal recording, {total:.0f} seconds: t3-plugins list, setup, doctor, the installed '
             f'slash-command skills, and the prompt for T3. Real output recorded {session["recorded"]}.')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="demo-rec" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{html.escape(label)}">\n'
        f'<style>{css}</style>\n'
        f'<rect class="bg" width="{width}" height="{height}"/>\n'
        f'<text class="cap" x="{PAD_X}" y="21">{html.escape(caption(session, total), quote=False)}</text>\n'
        f'<line class="rule" x1="0" y1="{HEADER - 4}" x2="{width}" y2="{HEADER - 4}"/>\n'
        f'<svg x="0" y="{HEADER}" width="{width}" height="{ROWS * LINE_HEIGHT + PAD_BOTTOM - 4}">'
        f'<g class="demo-scroll"{scroll_attr}>\n'
        + '\n'.join(body) + '\n</g></svg>\n</svg>\n'
    )


# Video ---------------------------------------------------------------------------

def frame_times(session: dict, step: int = 2) -> list[float]:
    """Every moment the picture changes: typed characters (in steps) and arriving rows."""
    rows, total = timeline(session)
    times = {0.0, total}
    for row in rows:
        if row['kind'] == 'cmd':
            start, typing = row['typed']
            chars = len(row['text'])
            for n in range(0, chars + 1, step):
                times.add(round(start + typing * n / max(chars, 1), 3))
            times.add(round(start + typing, 3))
        else:
            times.add(row['at'])
    merged = []
    for t in sorted(times):  # rows a few milliseconds apart become one frame
        if not merged or t - merged[-1] >= 0.06:
            merged.append(t)
    return merged


def find_tool(names: tuple[str, ...], purpose: str) -> str:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    raise RenderError(f'{purpose} needs {names[0]}; install it or put it on PATH')


def frame_page(svg: str, width: int, height: int) -> str:
    fonts = (ASSETS / 'fonts').as_uri()
    return ('<!doctype html><html><head><meta charset="utf-8"><style>'
            f"@font-face{{font-family:'IBM Plex Mono';src:url('{fonts}/ibm-plex-mono-400.woff2')}}"
            f"@font-face{{font-family:'IBM Plex Sans';src:url('{fonts}/ibm-plex-sans-variable.woff2');font-weight:100 700}}"
            f'html,body{{margin:0;background:{LIGHT["paper"]}}}svg{{display:block;width:{width}px;height:{height}px}}'
            f'</style></head><body>{svg}</body></html>')


def render_video(session: dict, stem: Path = VIDEO_STEM, poster: Path = POSTER, scale: int = 2) -> list[Path]:
    chrome = find_tool(('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'),
                       'Video rendering')
    ffmpeg = find_tool(('ffmpeg',), 'Video rendering')
    width, height = geometry()
    times = frame_times(session)
    _, total = timeline(session)
    with tempfile.TemporaryDirectory(prefix='render-demo-') as tmp:
        tmp = Path(tmp)
        env = dict(os.environ, HOME=str(tmp), XDG_CONFIG_HOME=str(tmp), XDG_CACHE_HOME=str(tmp))
        frames = []
        for n, t in enumerate(times):
            page = tmp / f'f{n:04d}.html'
            page.write_text(frame_page(build(session, at=t, colours=LIGHT), width, height))
            png = tmp / f'f{n:04d}.png'
            for _ in range(2):  # an occasional sandbox socket failure is transient
                proc = subprocess.run([chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                                       '--no-first-run', '--disable-crash-reporter', '--allow-file-access-from-files',
                                       f'--user-data-dir={tmp / "profile"}', f'--window-size={width},{height}',
                                       f'--force-device-scale-factor={scale}', '--virtual-time-budget=1000',
                                       f'--screenshot={png}', page.as_uri()],
                                      env=env, capture_output=True, text=True, timeout=60)
                if proc.returncode == 0 and png.is_file():
                    break
            else:
                raise RenderError(f'Chrome could not render frame {n}: {proc.stderr.strip()[-300:]}')
            frames.append((png, t))
        # A constant-rate image sequence (links to the rendered frames) times every frame
        # exactly; the concat demuxer's per-entry durations drift at the last entry.
        seq = tmp / 'seq'
        seq.mkdir()
        end = total + HOLD
        index, n = 0, 0
        while n / FPS < end:
            while index + 1 < len(frames) and frames[index + 1][1] <= n / FPS:
                index += 1
            (seq / f'{n:05d}.png').symlink_to(frames[index][0])
            n += 1
        base = [ffmpeg, '-v', 'error', '-y', '-framerate', str(FPS), '-i', str(seq / '%05d.png'),
                '-vf', 'format=yuv420p', '-an']
        outputs = []
        mp4 = stem.with_suffix('.mp4')
        subprocess.run(base + ['-c:v', 'libx264', '-preset', 'slow', '-crf', '30', '-tune', 'stillimage',
                               '-movflags', '+faststart', str(mp4)], check=True)
        outputs.append(mp4)
        webm = stem.with_suffix('.webm')
        subprocess.run(base + ['-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '40', '-row-mt', '1', str(webm)], check=True)
        outputs.append(webm)
        shutil.copyfile(frames[-1][0], poster)
        outputs.append(poster)
    print(f'video: {len(times)} frames, {total + HOLD:.1f}s including a {HOLD:.0f}s hold on the final frame')
    return outputs


def display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true', help='fail if the SVG is out of date')
    parser.add_argument('--transcript', type=Path, default=TRANSCRIPT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--video', action='store_true', help='also render MP4, WebM and a poster PNG')
    args = parser.parse_args(argv)
    session = load(args.transcript)
    rendered = build(session)
    if args.check:
        current = args.output.read_text() if args.output.is_file() else ''
        if current != rendered:
            print(f'{display(args.output)} is stale; run python3 scripts/render_demo.py', file=sys.stderr)
            return 1
        print(f'{display(args.output)} is current.')
        return 0
    args.output.write_text(rendered)
    print(f'wrote {display(args.output)} ({len(rendered)} bytes)')
    if args.video:
        try:
            for path in render_video(session):
                print(f'wrote {display(path)} ({path.stat().st_size} bytes)')
        except RenderError as exc:
            print(f'render_demo: {exc}', file=sys.stderr)
            return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
