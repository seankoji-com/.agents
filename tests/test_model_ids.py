"""No fixed model ID in the release archive's operational files. The archive is the
tracked tree minus the `.gitattributes` export-ignore paths; dated evidence and test
fixtures live under ignored paths and may name models."""
import re
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = re.compile(
    r'\b(?:claude-(?:opus|sonnet|haiku|fable)-?\d|gpt-\d|gemini-\d|grok-\d|glm-\d|kimi-k\d|qwen\d|'
    r'deepseek-v?\d|llama-?\d|mistral-(?:small|large|medium)|o[134]-mini)', re.IGNORECASE)


def ignored_prefixes():
    prefixes = []
    for line in (ROOT / '.gitattributes').read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[0].startswith('#') and 'export-ignore' in parts[1:]:
            prefixes.append(parts[0])
    return prefixes


def archive_files():
    tracked = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True, text=True, check=True)
    prefixes = ignored_prefixes()
    for rel in tracked.stdout.split('\0'):
        if not rel or not (ROOT / rel).is_file():
            continue
        if any(rel == p or (p.endswith('/') and rel.startswith(p)) for p in prefixes):
            continue
        yield rel


class ReleaseArchiveModelIds(unittest.TestCase):
    def test_pattern_catches_ids_and_spares_prose(self):
        for text in ('claude-opus-5-5', 'gpt-6.1-sol', 'GEMINI-3.8-flash', 'litellm/glm-5.3', 'qwen3.8-max'):
            self.assertRegex(text, MODEL_ID)
        for text in ('the Claude provider', 'an OpenAI lineage', 'gemini', 'MODEL_ID'):
            self.assertNotRegex(text, MODEL_ID)

    def test_archive_has_no_model_ids(self):
        files = list(archive_files())
        self.assertIn('plugins/imps/entry.md', files)
        self.assertIn('scripts/routing.py', files)
        self.assertFalse(any(f.startswith(('tests/', 'docs/', 'bench/')) for f in files))
        for rel in files:
            try:
                text = (ROOT / rel).read_text()
            except UnicodeDecodeError:
                continue
            match = MODEL_ID.search(text)
            self.assertIsNone(match, f'{rel}: {match and match.group(0)}')


if __name__ == '__main__':
    unittest.main()
