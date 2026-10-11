"""The Homebrew formula template must pass the tap's `brew audit --strict`."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / 'packaging' / 't3-plugins.rb.tmpl').read_text()
WORKFLOW = (ROOT / '.github' / 'workflows' / 'release.yml').read_text()


class FormulaTemplateTest(unittest.TestCase):
    def test_no_version_stanza_because_the_url_carries_it(self):
        # brew audit --strict: "`version` is redundant with version scanned from URL".
        self.assertIsNone(re.search(r'^\s*version\s', TEMPLATE, re.MULTILINE))
        self.assertIn('url "__URL__"', TEMPLATE)

    def test_every_placeholder_is_filled_by_the_release_workflow(self):
        placeholders = set(re.findall(r'__[A-Z0-9]+__', TEMPLATE))
        filled = set(re.findall(r's\|(__[A-Z0-9]+__)\|', WORKFLOW))
        self.assertEqual(placeholders, filled)


if __name__ == '__main__':
    unittest.main()
