"""The documentation site must be generated from the catalog, not hand-copied."""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import field_guide  # noqa: E402


class RepositoryGuideTest(unittest.TestCase):
    def test_every_plugin_has_a_plate_and_every_plate_has_a_plugin(self):
        specimens = field_guide.load_guide(ROOT)
        names = {s['name'] for s in specimens}
        manifests = {p.parent.name for p in (ROOT / 'plugins').glob('*/plugin.json')}
        self.assertEqual(names, manifests)
        self.assertEqual([s['order'] for s in specimens], list(range(1, len(specimens) + 1)))

    def test_specimen_marks_are_self_contained_svg(self):
        for s in field_guide.load_guide(ROOT):
            svg = s['mark_svg']
            self.assertTrue(svg.startswith('<svg'), s['name'])
            self.assertIn('role="img"', svg, s['name'])
            self.assertIn('aria-label=', svg, s['name'])
            self.assertNotIn('<script', svg, s['name'])
            self.assertNotIn('http', svg.split('xmlns="http://www.w3.org/2000/svg"', 1)[1], s['name'])

    def test_operations_come_from_the_manifest(self):
        by_name = {s['name']: s for s in field_guide.load_guide(ROOT)}
        imps = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        self.assertEqual(by_name['imps']['operations'], imps['operations'])

    def test_sightings_match_the_ledger(self):
        ledger = json.loads((ROOT / 'conformance/compatibility.json').read_text())
        sightings = field_guide.load_sightings(ROOT)
        self.assertEqual(sightings['t3_version'], ledger['t3_version'])
        codex = next(p for p in sightings['providers'] if p['provider'] == 'codex')
        self.assertEqual(codex['tallies']['bugfix'], {'passed': 3, 'repeats': 3, 'notes': []})
        self.assertEqual(codex['tallies']['adverse-review']['repeats'], 0)
        html = field_guide.render_sightings(sightings)
        for row in ledger['providers']:
            self.assertIn(f'<code>{row["provider_instance_id"]}</code>', html)
        self.assertIn('3/3', html)
        self.assertIn('not run', html)
        self.assertIn(ledger['t3_version'], html)

    def test_historical_sightings_expand_on_the_ledger_page(self):
        guide = field_guide.load_guide(ROOT)
        sightings = field_guide.load_sightings(ROOT)
        for page in ('sightings.md',):
            source = (ROOT / 'docs' / page).read_text()
            self.assertIn(field_guide.SIGHTINGS_MARKER, source)
            out = field_guide.expand_page(source, page, ROOT, guide, sightings)
            self.assertNotIn(field_guide.SIGHTINGS_MARKER, out)
            self.assertNotIn('<!-- inline-svg', out)
            self.assertIn('sightings__table', out)

    def test_homepage_links_to_compatibility_without_claiming_historical_passes(self):
        source = (ROOT / 'docs' / 'index.md').read_text()
        out = field_guide.expand_page(source, 'index.md', ROOT,
                                      field_guide.load_guide(ROOT), field_guide.load_sightings(ROOT))
        self.assertNotIn('sightings__table', out)
        self.assertNotIn('<!-- inline-svg', out)
        self.assertIn('(compatibility.md)', out)

    def test_plugin_pages_get_a_specimen_header_after_the_title(self):
        guide = field_guide.load_guide(ROOT)
        for s in guide:
            source = (ROOT / 'docs' / s['page']).read_text()
            out = field_guide.expand_page(source, s['page'], ROOT, guide, {})
            title_at = ('\n' + out).index('\n# ')
            header_at = out.index('specimen--page')
            self.assertLess(title_at, header_at, s['name'])
            self.assertIn(s['binomial'], out)
            self.assertIn('<dt>Habitat</dt>', out)
            self.assertIn('Use it when', out)
            # The use-when line and the invocation come before the field notes.
            self.assertLess(out.index('specimen__use'), out.index('<dt>Habitat</dt>'))
            self.assertLess(out.index('specimen__try'), out.index('<dt>Habitat</dt>'))

    def test_every_try_line_is_a_skill_mention_for_a_real_operation(self):
        for s in field_guide.load_guide(ROOT):
            self.assertTrue(s['try'].startswith(f'$t3-{s["name"]} '), s['name'])
            words = s['try'].split()
            first = words[1]
            if first in s['operations']:
                continue
            # Free text is accepted only by plugins whose entry routes it to run.
            self.assertIn('run', s['operations'], (s['name'], first))

    def test_recording_is_inlined_on_the_homepage_and_is_safe(self):
        svg = field_guide.load_recording(ROOT)
        self.assertIn('class="demo-rec"', svg)
        template = (ROOT / 'overrides' / 'home.html').read_text()
        self.assertIn('guide.recording | safe', template)
        # The tap's stable formula predates these docs, so the hero installs HEAD and
        # says why before the command, not after it.
        self.assertIn('brew install --HEAD seankoji-com/tap/t3-plugins', template)
        self.assertLess(template.index('fg-install__note'), template.index('brew install --HEAD'))
        # The hero sits outside Material's content area, so it carries its own copy
        # button; Material's document-wide clipboard handler serves it.
        self.assertIn('<pre id="fg-install-code">', template)
        self.assertIn('data-clipboard-target="#fg-install-code > code" data-md-type="copy"', template)
        for bad in ('<svg><script>x</script></svg>', '<svg><a href="https://e.invalid/">x</a></svg>',
                    '<svg><style>@import "x.css";</style></svg>', '<svg onload="x()"></svg>',
                    '<svg><rect style="fill:url(https://e.invalid/p#x)"/></svg>', '<p>no</p>'):
            with self.assertRaises(field_guide.FieldGuideError, msg=bad):
                field_guide.check_recording(bad)
        self.assertTrue(field_guide.check_recording('<svg><style>.demo-rec text{fill:red}</style></svg>'))

    def test_other_pages_are_untouched(self):
        guide = field_guide.load_guide(ROOT)
        text = '# Plain\n\nNo markers here.\n'
        self.assertEqual(field_guide.expand_page(text, 'testing.md', ROOT, guide, {}), text)


class StylesheetContrastTest(unittest.TestCase):
    """DESIGN.md: controls need 3:1 against their background in both schemes."""

    @staticmethod
    def _luminance(hex_colour):
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = [c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return .2126 * r + .7152 * g + .0722 * b

    def _ratio(self, a, b):
        hi, lo = sorted((self._luminance(a), self._luminance(b)), reverse=True)
        return (hi + .05) / (lo + .05)

    def test_code_copy_icon_is_a_visible_control(self):
        css = (ROOT / 'docs' / 'stylesheets' / 'extra.css').read_text()
        # Material 9.7 names the copy control .md-code__button; hover and keyboard focus count too.
        rule = re.search(r'^\.md-code__button \{ color: var\(--([\w-]+)\); \}', css, re.M)
        hover = re.search(r'^\.md-code__button:hover, \.md-code__button\.focus-visible, '
                          r'\.md-code__button:focus-visible \{ color: var\(--([\w-]+)\); \}', css, re.M)
        self.assertTrue(rule and hover, 'copy icon colours are not set in extra.css')
        light, dark = css.split('[data-md-color-scheme="slate"]', 1)
        for scheme, block in (('light', light), ('dark', dark)):
            # The button sits on the code block and on Material's code-nav backing.
            backing = re.findall(r'--md-code-bg-color(?:--light|--lighter)?: var\(--paper-deep\);', block)
            self.assertEqual(len(backing), 3, f'{scheme}: code and copy-button backgrounds must be --paper-deep')
            tokens = dict(re.findall(r'--([\w-]+): (#[0-9a-fA-F]{6});', block))
            for state, token in (('rest', rule[1]), ('hover', hover[1])):
                ratio = self._ratio(tokens[token], tokens['paper-deep'])
                self.assertGreaterEqual(ratio, 3, f'{scheme} {state}: {ratio:.2f}:1')


class SyntheticRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / 'plugins/alpha').mkdir(parents=True)
        (self.tmp / 'docs/assets/specimens').mkdir(parents=True)
        (self.tmp / 'plugins/alpha/plugin.json').write_text(json.dumps({
            'name': 'alpha', 'version': '1.0.0', 'description': 'd', 'entry': 'entry.md',
            'operations': ['doctor'], 'kind': 'workflow', 'compatibility': 'experimental'}))
        (self.tmp / 'docs/assets/specimens/alpha.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        self.guide = {'alpha': {'plate': 'I', 'binomial': 'A b', 'summary': 's', 'use_when': 'u',
                                'try': '$t3-alpha doctor', 'habitat': 'h', 'diet': 'd', 'field_marks': 'f'}}
        self.write_guide()

    def write_guide(self):
        (self.tmp / 'docs/field-guide.json').write_text(json.dumps(self.guide))

    def test_missing_entry_fails_the_build(self):
        (self.tmp / 'plugins/beta').mkdir()
        (self.tmp / 'plugins/beta/plugin.json').write_text(json.dumps({
            'name': 'beta', 'version': '1', 'description': 'd', 'entry': 'entry.md',
            'operations': [], 'kind': 'workflow', 'compatibility': 'experimental'}))
        with self.assertRaisesRegex(field_guide.FieldGuideError, "missing=\\['beta'\\]"):
            field_guide.load_guide(self.tmp)

    def test_extra_entry_fails_the_build(self):
        self.guide['ghost'] = dict(self.guide['alpha'], plate='II')
        self.write_guide()
        with self.assertRaisesRegex(field_guide.FieldGuideError, "extra=\\['ghost'\\]"):
            field_guide.load_guide(self.tmp)

    def test_missing_mark_fails_the_build(self):
        (self.tmp / 'docs/assets/specimens/alpha.svg').unlink()
        with self.assertRaisesRegex(field_guide.FieldGuideError, 'missing specimen mark'):
            field_guide.load_guide(self.tmp)

    def test_unsafe_mark_fails_the_build(self):
        for svg in ('<svg><script>alert(1)</script></svg>', '<svg onload="alert(1)"></svg>',
                    '<svg><image href="https://example.invalid/x.png"/></svg>',
                    '<svg><a xlink:href="javascript:alert(1)"/></svg>', '<p>not svg</p>',
                    '<svg><style>@import url("https://example.invalid/a.css");</style></svg>',
                    '<svg><rect fill="url(https://example.invalid/a.svg#x)"/></svg>',
                    '<svg><rect style="fill:url( \'//example.invalid/p.svg#x\')"/></svg>'):
            (self.tmp / 'docs/assets/specimens/alpha.svg').write_text(svg)
            with self.assertRaisesRegex(field_guide.FieldGuideError, 'self-contained SVG', msg=svg):
                field_guide.load_guide(self.tmp)
        (self.tmp / 'docs/assets/specimens/alpha.svg').write_text(
            '<svg><defs><g id="a"/></defs><use href="#a"/><rect fill="url(#a)"/></svg>')
        self.assertEqual(len(field_guide.load_guide(self.tmp)), 1)

    def test_missing_use_when_or_try_fails_the_build(self):
        for field in ('use_when', 'try'):
            entry = dict(self.guide['alpha'])
            entry[field] = ''
            (self.tmp / 'docs/field-guide.json').write_text(json.dumps({'alpha': entry}))
            with self.assertRaisesRegex(field_guide.FieldGuideError, f'missing .*{field}'):
                field_guide.load_guide(self.tmp)

    def test_try_must_mention_its_own_skill(self):
        self.guide['alpha']['try'] = '$t3-beta doctor'
        self.write_guide()
        with self.assertRaisesRegex(field_guide.FieldGuideError, r'\$t3-alpha'):
            field_guide.load_guide(self.tmp)

    def test_missing_recording_fails_the_build(self):
        with self.assertRaisesRegex(field_guide.FieldGuideError, 'render_demo'):
            field_guide.load_recording(self.tmp)

    def test_empty_catalog_fails_the_build(self):
        shutil.rmtree(self.tmp / 'plugins/alpha')
        self.guide = {}
        self.write_guide()
        with self.assertRaisesRegex(field_guide.FieldGuideError, 'empty'):
            field_guide.load_guide(self.tmp)

    def test_plate_gaps_fail_the_build(self):
        self.guide['alpha']['plate'] = 'III'
        self.write_guide()
        with self.assertRaisesRegex(field_guide.FieldGuideError, 'without gaps'):
            field_guide.load_guide(self.tmp)

    def test_inline_svg_refuses_paths_outside_assets(self):
        (self.tmp / 'docs/secret.svg').write_text('<svg/>')
        with self.assertRaises(field_guide.FieldGuideError):
            field_guide.inline_svgs('<!-- inline-svg: assets/../secret.svg -->', self.tmp)
        with self.assertRaises(field_guide.FieldGuideError):
            field_guide.inline_svgs('<!-- inline-svg: assets/missing.svg -->', self.tmp)
        out = field_guide.inline_svgs('x <!-- inline-svg: assets/specimens/alpha.svg --> y', self.tmp)
        self.assertEqual(out, 'x <div class="diagram-frame" markdown="0">'
                              '<svg xmlns="http://www.w3.org/2000/svg"></svg></div> y')

    def test_dots_render_every_state(self):
        self.assertIn('sighting--none', field_guide.dots(0, 0))
        self.assertIn('●●●', field_guide.dots(3, 3))
        self.assertIn('sighting--clean', field_guide.dots(3, 3))
        self.assertIn('●○○', field_guide.dots(1, 3))
        self.assertIn('sighting--mixed', field_guide.dots(1, 3))
        self.assertIn('○', field_guide.dots(0, 1))
        self.assertIn('sighting--failed', field_guide.dots(0, 1))
        self.assertIn('aria-label="1 of 3 passed"', field_guide.dots(1, 3))

    def test_html_in_data_is_escaped(self):
        self.guide['alpha']['binomial'] = '<b>x</b>'
        self.guide['alpha']['try'] = '$t3-alpha run <i>y</i>'
        self.write_guide()
        header = field_guide.render_specimen_header(field_guide.load_guide(self.tmp)[0])
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', header)
        self.assertNotIn('<b>x</b>', header)
        self.assertIn('&lt;i&gt;y&lt;/i&gt;', header)


if __name__ == '__main__':
    unittest.main()
