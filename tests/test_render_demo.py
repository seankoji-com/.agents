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
