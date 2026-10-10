"""scripts/check_docs.py link checking against temporary documentation trees."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_docs  # noqa: E402


class CheckDocsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'docs' / 'plugins').mkdir(parents=True)
        (self.root / 'plugins' / 'demo').mkdir(parents=True)
        (self.root / 'plugins' / 'demo' / 'plugin.json').write_text(json.dumps({'name': 'demo', 'entry': 'entry.md'}))
        (self.root / 'plugins' / 'demo' / 'entry.md').write_text('# Demo\n')
        (self.root / 'docs' / 'plugins' / 'demo.md').write_text('# Demo guide\n')
        (self.root / 'docs' / 'target.md').write_text('# Install Guide\n\n## Step one: `brew`\n\n## Step one: `brew`\n\n'
                                                      'Rolling back {#rollback}\n---\n\n<a name="legacy"></a>\n')
        (self.root / 'docs' / 'image.svg').write_text('<svg/>')

    def write(self, text, name='docs/page.md'):
        (self.root / name).write_text(text)

    def errors(self):
        return check_docs.check(self.root)

    def test_code_is_not_scanned(self):
        self.write('Inline `[x](missing-inline.md)` span.\n\n~~~\n[y](missing-tilde.md)\n~~~\n\n'
                   'Paragraph.\n\n    [z](missing-indented.md)\n\n```text\n[w](missing-fence.md)\n```\n\n'
                   '- item\n\n    [kept](missing-list-continuation.md)\n')
        self.assertEqual(self.errors(), ['docs/page.md: missing link missing-list-continuation.md'])

    def test_badge_checks_image_and_link(self):
        self.write('[![badge](image.svg)](target.md) [![badge](nope.svg)](also-nope.md)\n')
        self.assertEqual(self.errors(), ['docs/page.md: missing link nope.svg', 'docs/page.md: missing link also-nope.md'])

    def test_raw_html_targets(self):
        self.write('<p align="center"><a href="target.md"><img src="image.svg"></a>'
                   '<a href="gone.md">x</a><img alt="y" src=\'gone.png\'></p>\n')
        self.assertEqual(self.errors(), ['docs/page.md: missing link gone.md', 'docs/page.md: missing link gone.png'])

    def test_reference_definitions(self):
        self.write('See [the guide][guide] and [more][more].\n\n[guide]: target.md "Title"\n[more]: <nowhere.md>\n')
        self.assertEqual(self.errors(), ['docs/page.md: missing link nowhere.md'])

    def test_anchors_use_the_toc_slug_rule(self):
        self.write('[a](target.md#install-guide) [b](target.md#step-one-brew) [c](target.md#step-one-brew_1) '
                   '[d](target.md#rollback) [e](target.md#legacy) [f](target.md#Install-Guide) [g](target.md#step-one)\n'
                   '[h](image.svg#fragment-not-checked)\n')
        self.assertEqual(self.errors(), ['docs/page.md: missing anchor target.md#Install-Guide',
                                         'docs/page.md: missing anchor target.md#step-one'])

    def test_same_file_anchors(self):
        self.write('# Page Title\n\nSee [top](#page-title) and [below](#details) and [none](#missing).\n\n## Details\n')
        self.assertEqual(self.errors(), ['docs/page.md: missing anchor #missing'])

    def test_plugin_pages_are_scanned_and_pkg_targets_skipped(self):
        self.write('Read [PKG](PKG/references/x.md) and [local](references/present.md) and [bad](references/absent.md).\n',
                   name='plugins/demo/entry.md')
        (self.root / 'plugins' / 'demo' / 'references').mkdir()
        (self.root / 'plugins' / 'demo' / 'references' / 'present.md').write_text('# ok\n')
        (self.root / 'plugins' / 'demo' / 'references' / 'nested.md').write_text('[up](../entry.md) [no](nothing.md)\n')
        self.assertEqual(sorted(self.errors()), ['plugins/demo/entry.md: missing link references/absent.md',
                                                 'plugins/demo/references/nested.md: missing link nothing.md'])

    def test_external_and_template_targets_are_ignored(self):
        self.write('[a](https://example.invalid/x) [b](mailto:someone@example.invalid) [c]({{ site_url }}/x) [d](<path>)\n')
        self.assertEqual(self.errors(), [])

    def test_ids_in_code_samples_are_not_anchors(self):
        self.write('```html\n<a id="sample"></a>\n```\n\n[s](#sample)\n')
        self.assertEqual(self.errors(), ['docs/page.md: missing anchor #sample'])

    def test_links_outside_the_repository_are_refused(self):
        outside = self.root.parent / f'{self.root.name}-outside.md'
        outside.write_text('# Elsewhere\n')
        self.addCleanup(outside.unlink)
        self.write(f'[x](../../{outside.name}) [y](../docs/target.md#install-guide)\n')
        self.assertEqual(self.errors(), [f'docs/page.md: link leaves the repository ../../{outside.name}'])


if __name__ == '__main__':
    unittest.main()
