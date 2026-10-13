"""The homepage recording is rendered from a real transcript, deterministic, and safe to inline."""
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import capture_terminal  # noqa: E402
import render_demo  # noqa: E402


def session(steps):
    return {'format': 1, 'name': 'test', 'summary': 's', 'recorded': '2026-10-13', 'commit': 'abc1234',
            'environment': {'os': 'Linux x86_64', 'python': '3.12.0', 'home': 'h'}, 'note': 'n',
            'steps': [{'command': c, 'exit': 0, 'expected_exit': 0, 'seconds': s, 'lines': lines}
                      for c, s, lines in steps]}


SMALL = session([('t3-plugins list', 0.1, [[0.05, 'imps   Bounded engineering work']]),
                 ('t3-plugins doctor', 0.5, [[0.2, '{"plugin": "imps", "ok": true}'], [0.4, 'done']])])


class RenderDemoTest(unittest.TestCase):
    # The committed recording ------------------------------------------------------
    def test_committed_svg_matches_the_committed_transcript(self):
        self.assertEqual((ROOT / 'docs/assets/demo.svg').read_text(), render_demo.build())

    def test_transcript_comes_from_the_capture_script_and_shows_the_quickstart(self):
        data = render_demo.load()
        self.assertEqual(data['format'], capture_terminal.FORMAT)
        commands = [s['command'] for s in data['steps']]
        self.assertEqual(commands, capture_terminal.SESSIONS['quickstart'][1])
        self.assertTrue(all(s['exit'] == s['expected_exit'] for s in data['steps']))
        doctor = next(s for s in data['steps'] if s['command'] == 't3-plugins doctor')
        self.assertTrue(doctor['lines'])
        self.assertTrue(all('"ok": true' in text for _, text in doctor['lines']))

    def test_readme_names_the_recording_date(self):
        import datetime as dt
        day = dt.date.fromisoformat(render_demo.load()['recorded'])
        self.assertIn(f'recorded {day.day} {day:%b %Y}', (ROOT / 'README.md').read_text())

    def test_committed_assets_contain_nothing_private(self):
        paths = [ROOT / 'docs/assets/demo.svg', *sorted((ROOT / 'docs/assets/recordings').glob('*'))]
        for path in paths:
            self.assertEqual(capture_terminal.leaks(path.read_text()), [], path.name)

    def test_binary_assets_stay_small(self):
        for name in ('quickstart.mp4', 'quickstart.webm', 'quickstart-terminal.png', 'docs-preview.png'):
            path = ROOT / 'docs/assets' / name
            self.assertTrue(path.is_file(), name)
            self.assertLess(path.stat().st_size, 2 * 1024 * 1024, name)

    # Rendering ---------------------------------------------------------------------

    def test_output_is_deterministic_and_self_contained(self):
        a, b = render_demo.build(SMALL), render_demo.build(SMALL)
        self.assertEqual(a, b)
        self.assertTrue(a.startswith('<svg xmlns="http://www.w3.org/2000/svg"'))
        self.assertNotIn('<script', a)
        self.assertNotIn('href=', a)
        self.assertIn('prefers-reduced-motion', a)
        self.assertIn('t3-plugins doctor', a)
        self.assertIn('simulated typing', a)
        self.assertIn('recorded 13 Oct 2026', a)

    def test_styles_cannot_leak_into_the_page(self):
        # Inlined into the homepage: an unscoped rule would restyle every other diagram.
        css = render_demo.build(SMALL).split('<style>', 1)[1].split('</style>', 1)[0]
        css = re.sub(r'@keyframes demo-[a-z]+\{(?:[^{}]*\{[^{}]*\})*\}', '', css)
        css = re.sub(r'@media\([^)]*\)\{(.*)\}', r'\1', css)
        selectors = [sel.strip() for rule in re.findall(r'([^{}]+)\{[^{}]*\}', css) for sel in rule.split(',')]
        self.assertTrue(selectors)
        for sel in selectors:
            self.assertTrue(sel.startswith(('.demo-rec ', '#demo-')), sel)

    def test_output_appears_at_its_recorded_offset(self):
        rows, total = render_demo.timeline(SMALL)
        cmd = rows[0]
        start, typing = cmd['typed']
        first_out = rows[1]
        self.assertAlmostEqual(first_out['at'], start + typing + render_demo.ENTER_PAUSE + 0.05, places=3)
        times = [r['at'] for r in rows]
        self.assertEqual(times, sorted(times))
        self.assertGreater(total, times[-1])

    def test_long_words_hard_break_and_keep_every_character(self):
        long = 'x' * 200
        rows, _ = render_demo.timeline(session([('cmd', 0.1, [[0.0, long]])]))
        out = [r['text'] for r in rows if r['kind'] == 'out']
        self.assertEqual(out[0], 'x' * render_demo.COLS)
        self.assertTrue(all(row.startswith('  x') for row in out[1:]))
        self.assertTrue(all(len(row) <= render_demo.COLS for row in out))
        self.assertEqual(out[0] + ''.join(row[2:] for row in out[1:]), long)
        self.assertEqual(len(out), 1 + math.ceil((200 - render_demo.COLS) / (render_demo.COLS - 2)))
        self.assertEqual(render_demo.wrap(''), [''])
        self.assertEqual(render_demo.wrap('short line'), ['short line'])

    def test_wraps_at_spaces_and_hangs_under_the_description_column(self):
        line = 'imps                 ' + ' '.join(['evidence'] * 20)
        rows = render_demo.wrap(line, cols=50)
        self.assertTrue(all(len(row) <= 50 for row in rows))
        self.assertTrue(all(row.startswith(' ' * 21 + 'evidence') for row in rows[1:]))
        self.assertTrue(all(row.rstrip().endswith('evidence') for row in rows))
        self.assertEqual(rows[0] + ''.join(row[21:] for row in rows[1:]), line)
        json_line = '{"ok": true, "data": {"plugin": "imps", "files": 73}}'
        rows = render_demo.wrap(json_line, cols=24)
        self.assertTrue(all(row.startswith('  ') for row in rows[1:]))
        self.assertEqual(rows[0] + ''.join(row[2:] for row in rows[1:]), json_line)

    def test_canvas_has_a_fixed_terminal_size(self):
        long = session([('cmd', 0.1, [[0.0, 'y' * 500]] * 40)])
        width = int(re.search(r'viewBox="0 0 (\d+) ', render_demo.build(long)).group(1))
        self.assertEqual(width, render_demo.geometry()[0])
        self.assertIn('demo-scroll', render_demo.build(long))

    def test_static_frame_shows_only_what_has_happened(self):
        rows, total = render_demo.timeline(SMALL)
        early = render_demo.build(SMALL, at=rows[1]['at'], colours=render_demo.LIGHT)
        self.assertIn('Bounded engineering work', early)
        self.assertNotIn('done', early)
        self.assertNotIn('@keyframes', early)
        final = render_demo.build(SMALL, at=total, colours=render_demo.LIGHT)
        self.assertIn('done', final)
        self.assertNotIn('var(--sp-', final)
        before = render_demo.build(SMALL, at=0.0, colours=render_demo.LIGHT)
        self.assertNotIn('t3-plugins list<', before)

    def test_static_frame_scrolls_to_the_newest_rows(self):
        many = session([('cmd', 1.0, [[i / 100, f'line {i}'] for i in range(40)])])
        _, total = render_demo.timeline(many)
        frame = render_demo.build(many, at=total, colours=render_demo.LIGHT)
        hidden = 41 - render_demo.ROWS
        self.assertIn(f'translate(0 {-hidden * render_demo.LINE_HEIGHT})', frame)

    def test_success_marker_is_highlighted_and_text_is_escaped(self):
        svg = render_demo.build(session([('<x>', 0.1, [[0.0, 'a < b & "ok": true']])]))
        self.assertIn('a &lt; b &amp; <tspan class="ok">"ok": true</tspan>', svg)
        self.assertIn('&lt;x&gt;', svg)
        self.assertNotIn('<x>', svg)

    def test_frame_times_merge_rows_that_arrive_together(self):
        times = render_demo.frame_times(session([('c', 0.1, [[0.0, 'a'], [0.01, 'b'], [0.5, 'c']])]))
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(b - a >= 0.06 for a, b in zip(times, times[1:])))

    def test_check_mode_reports_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'demo.svg'
            self.assertEqual(render_demo.main(['--output', str(out)]), 0)
            self.assertEqual(render_demo.main(['--check', '--output', str(out)]), 0)
            out.write_text('stale')
            self.assertEqual(render_demo.main(['--check', '--output', str(out)]), 1)

    def test_video_fails_clearly_without_chrome_or_ffmpeg(self):
        with mock.patch.object(render_demo.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(render_demo.RenderError, 'needs google-chrome'):
                render_demo.render_video(SMALL)
        with mock.patch.object(render_demo.shutil, 'which', side_effect=lambda n: None if n == 'ffmpeg' else '/bin/true'):
            with self.assertRaisesRegex(render_demo.RenderError, 'needs ffmpeg'):
                render_demo.render_video(SMALL)


if __name__ == '__main__':
    unittest.main()
