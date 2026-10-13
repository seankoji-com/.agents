"""The site screenshot helper serves a built site, probes layout width, and fails clearly."""
import json
import math
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
        self.assertEqual(capture_site.shot_name('index.html', 1440, 'dark', 200), 'home-1440-dark-zoom200.png')

    def test_zoom_is_chromes_own_page_zoom_and_must_take_effect(self):
        profile = Path(self.tmp.name) / 'profile'
        capture_site.set_zoom(profile, 200)
        prefs = json.loads((profile / 'Default' / 'Preferences').read_text())
        level = prefs['partition']['default_zoom_level']['x']
        self.assertAlmostEqual(1.2 ** level, 2.0)
        plain = Path(self.tmp.name) / 'plain'
        capture_site.set_zoom(plain, 100)
        self.assertFalse((plain / 'Default' / 'Preferences').exists())
        with self.assertRaisesRegex(capture_site.CaptureError, 'positive'):
            capture_site.set_zoom(plain, 0)
        capture_site.check_zoom('p', 200, 2.0, 1440, 720)
        capture_site.check_zoom('p', 100, 1.0, 1440, 1440)
        with self.assertRaisesRegex(capture_site.CaptureError, 'ignored the zoom'):
            capture_site.check_zoom('p', 200, 1.0, 1440, 720)
        # The right pixel ratio with an unzoomed viewport is a device-scale change, not zoom.
        with self.assertRaisesRegex(capture_site.CaptureError, '720px CSS viewport.*reports 1440px'):
            capture_site.check_zoom('p', 200, 2.0, 1440, 1440)
        with self.assertRaisesRegex(capture_site.CaptureError, 'at least 500px'):
            capture_site.capture(self.site, Path(self.tmp.name) / 'out', ['index.html'], [390],
                                 ['light'], None, 'chrome', zoom=200)
        args = capture_site.chrome_args('chrome', profile, 1440, 900, 'light', None)
        self.assertFalse(any(a.startswith('--virtual-time-budget') for a in args))
        self.assertIn('--force-device-scale-factor=1', args)  # zoom, not device scale, sets the ratio

    def test_controls_need_a_real_window_width(self):
        with self.assertRaisesRegex(capture_site.CaptureError, 'at least 500px'):
            capture_site.check_controls(self.site, Path(self.tmp.name) / 'out', 'index.html', 390, 844,
                                        'light', 100, 'chrome')


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


# Stands in for Chrome: speaks NUL-framed JSON on fds 3 and 4 like --remote-debugging-pipe.
FAKE_CHROME = r'''
import json, os, sys
assert '--remote-debugging-pipe' in sys.argv, sys.argv
buf = b''
def send(obj):
    os.write(4, json.dumps(obj).encode() + b'\0')
while True:
    while b'\0' not in buf:
        chunk = os.read(3, 65536)
        if not chunk:
            sys.exit(0)
        buf += chunk
    raw, buf = buf.split(b'\0', 1)
    msg = json.loads(raw)
    send({'method': 'Page.loadEventFired', 'params': {}})  # events are skipped
    method, reply = msg['method'], {}
    if method == 'Target.getTargets':
        reply = {'targetInfos': [{'type': 'browser', 'targetId': 'b'}, {'type': 'page', 'targetId': 'p1'}]}
    elif method == 'Target.attachToTarget':
        assert msg['params']['targetId'] == 'p1'
        reply = {'sessionId': 's1'}
    elif method == 'Runtime.evaluate':
        assert msg.get('sessionId') == 's1'
        if msg['params']['expression'] == 'boom':
            reply = {'exceptionDetails': {'text': 'Uncaught'}, 'result': {}}
        else:
            reply = {'result': {'value': [msg['params']['expression'], len(sys.argv)]}}
    elif method == 'Page.bogus':
        send({'id': msg['id'], 'error': {'message': 'no such method'}})
        continue
    send({'id': msg['id'], 'result': reply})
    if method == 'Browser.close':
        sys.exit(0)
'''


class DevToolsPipeTest(unittest.TestCase):
    def test_pipe_framing_sessions_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'chrome'
            fake.write_text(f'#!{sys.executable}\n' + FAKE_CHROME)
            fake.chmod(0o755)
            with capture_site.DevTools([str(fake), '--headless=new'], {'PATH': '/usr/bin:/bin'}, timeout=10) as tab:
                self.assertEqual(tab.session, 's1')
                expression, argc = tab.js('1 + 1')
                self.assertEqual(expression, '1 + 1')
                self.assertEqual(argc, 4)  # program, --headless=new, --remote-debugging-pipe, about:blank
                with self.assertRaisesRegex(capture_site.CaptureError, 'page script failed: Uncaught'):
                    tab.js('boom')
                with self.assertRaisesRegex(capture_site.CaptureError, 'Page.bogus: no such method'):
                    tab.send('Page.bogus')
            self.assertEqual(tab.proc.returncode, 0)
            self.assertTrue(tab.proc.stderr.closed)


if __name__ == '__main__':
    unittest.main()
