"""The site screenshot helper serves a built site, probes layout width, and fails clearly."""
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import capture_site  # noqa: E402


class CaptureSiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name) / 'site'
        (self.site / 'plugins' / 'imps').mkdir(parents=True)
        (self.site / 'index.html').write_text('<html><head><title>t</title></head><body>home</body></html>')
        (self.site / 'plugins' / 'imps' / 'index.html').write_text('<html><body>imps</body></html>')

    def fetch(self, url):
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.read().decode()

    def test_probe_is_injected_only_when_asked(self):
        with capture_site.serve(self.site) as base:
            plain = self.fetch(base + 'index.html')
            probed = self.fetch(base + 'index.html?probe')
            nested = self.fetch(base + 'plugins/imps/?probe')
        self.assertNotIn('PROBE', plain)
        self.assertIn('document.title="PROBE "', probed)
        self.assertTrue(probed.endswith('</script></body></html>'))
        self.assertIn('imps', nested)
        self.assertIn('PROBE', nested)

    def test_narrow_widths_load_the_page_in_a_frame_of_that_width(self):
        url = capture_site.page_url('http://127.0.0.1:1/', 'plugins/imps/index.html', 390, 844, True)
        self.assertIn('/__frame__?src=', url)
        self.assertIn('&w=390&h=844', url)
        wide = capture_site.page_url('http://127.0.0.1:1/', 'index.html', 1440, 900, False)
        self.assertEqual(wide, 'http://127.0.0.1:1/index.html')
        with capture_site.serve(self.site) as base:
            frame = self.fetch(base + url.split('/', 3)[3])
        self.assertIn('<iframe id="f" src="/plugins/imps/index.html?probe" width="390" height="844">', frame)
        args = capture_site.chrome_args('chrome', Path('/p'), 390, 844, 'dark')
        self.assertIn('--window-size=500,844', args)
        self.assertIn('--blink-settings=preferredColorScheme=0', args)

    def test_frame_parameters_are_escaped(self):
        with capture_site.serve(self.site) as base:
            frame = self.fetch(base + '__frame__?src=%22%3E%3Cscript%3E&w=390&h=10')
        self.assertNotIn('"><script>', frame)

    def test_screenshot_names(self):
        self.assertEqual(capture_site.shot_name('index.html', 1440, 'light'), 'home-1440-light.png')
        self.assertEqual(capture_site.shot_name('plugins/imps/index.html', 390, 'dark'), 'plugins-imps-390-dark.png')

    def test_missing_tools_and_sites_fail_clearly(self):
        with mock.patch.object(capture_site.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(capture_site.CaptureError, 'headless Chrome is required'):
                capture_site.find_chrome()
            with self.assertRaisesRegex(capture_site.CaptureError, 'need ffmpeg'):
                capture_site.find_ffmpeg()
        with self.assertRaisesRegex(capture_site.CaptureError, 'not found'):
            capture_site.find_chrome('/nonexistent/chrome')
        with self.assertRaisesRegex(capture_site.CaptureError, 'build the site first'):
            capture_site.capture(Path(self.tmp.name) / 'missing', Path(self.tmp.name) / 'out',
                                 ['index.html'], [1440], ['light'], None, 'chrome')
        with mock.patch.object(capture_site.shutil, 'which', return_value=None):
            self.assertEqual(capture_site.main(['--site', str(self.site), '--out', self.tmp.name]), 2)


if __name__ == '__main__':
    unittest.main()
