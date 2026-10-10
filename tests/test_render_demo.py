"""The homepage recording is generated, deterministic, and safe to inline."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import render_demo  # noqa: E402


class RenderDemoTest(unittest.TestCase):
    def test_committed_recording_is_current(self):
        self.assertEqual((ROOT / 'docs/assets/demo.svg').read_text(), render_demo.build())

    def test_output_is_deterministic_and_self_contained(self):
        a, b = render_demo.build(), render_demo.build()
        self.assertEqual(a, b)
        self.assertTrue(a.startswith('<svg xmlns="http://www.w3.org/2000/svg"'))
        self.assertNotIn('<script', a)
        self.assertNotIn('href=', a)
        self.assertIn('prefers-reduced-motion', a)
        self.assertIn('t3-plugins prompt imps doctor', a)
        self.assertIn('no live model call', a)

    def test_styles_cannot_leak_into_the_page(self):
        # Inlined into the homepage: an unscoped rule would restyle the other diagrams.
        import re
        css = render_demo.build().split('<style>', 1)[1].split('</style>', 1)[0]
        css = re.sub(r'@keyframes demo-[a-z]+\{(?:[^{}]*\{[^{}]*\})*\}', '', css)
        css = re.sub(r'@media\([^)]*\)\{(.*)\}', r'\1', css)
        selectors = [sel.strip() for rule in re.findall(r'([^{}]+)\{[^{}]*\}', css) for sel in rule.split(',')]
        self.assertTrue(selectors)
        for sel in selectors:
            self.assertTrue(sel.startswith(('.demo-rec ', '#demo-l')), sel)

    def test_canvas_fits_the_longest_line(self):
        import re
        long = 'x' * 200
        svg = render_demo.build([('out', long)])
        width = int(re.search(r'viewBox="0 0 (\d+) ', svg).group(1))
        self.assertGreaterEqual(width, 2 * render_demo.PAD_X + 200 * render_demo.FONT_SIZE * render_demo.CHAR_WIDTH)

    def test_frames_are_escaped(self):
        svg = render_demo.build([('out', 'a < b & "c"'), ('cmd', '<x>')])
        self.assertIn('a &lt; b &amp; "c"', svg)
        self.assertIn('&lt;x&gt;', svg)
        self.assertNotIn('<x>', svg)

    def test_check_mode_reports_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'demo.svg'
            self.assertEqual(render_demo.main(['--output', str(out)]), 0)
            self.assertEqual(render_demo.main(['--check', '--output', str(out)]), 0)
            out.write_text('stale')
            self.assertEqual(render_demo.main(['--check', '--output', str(out)]), 1)


if __name__ == '__main__':
    unittest.main()
