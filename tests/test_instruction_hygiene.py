"""Instruction hygiene: plugin instructions, shared contracts and the briefs Python
generates contain none of the banned prompting phrases, and review briefs ask for
every finding with its severity before any filtering."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from core import engine  # noqa: E402
import skills  # noqa: E402

BANNED = ('think step by step', 'think carefully', 'think hard', 'explain your reasoning',
          'show your reasoning', 'only report high-severity', 'final verification step')


def banned_in(text):
    folded = ' '.join(text.casefold().split())
    return [phrase for phrase in BANNED if phrase in folded]


def instruction_files():
    plugins = ROOT / 'plugins'
    found = set(plugins.glob('*/entry.md')) | set((ROOT / 'shared').glob('*.md'))
    for folder in ('playbooks', 'references', 'templates'):
        found |= {p for p in plugins.glob(f'*/{folder}/**/*') if p.is_file()}
    return sorted(found)


def run_state(tmp):
    return {
        'run_id': 'run-fixture', 'repo': {'worktree': tmp, 'base_sha': '0' * 40},
        'brief': {'text': 'fixture', 'requirements_source': None,
                  'requirements': [{'id': 'REQ-ONE', 'text': 'the command prints 3', 'kind': 'command', 'required': True}],
                  'constraints': ['Keep the CLI usage text unchanged.']},
        'policy': {'brief_notes': 'Fixture notes from the run policy.'},
    }


def generated_briefs():
    """Representative output of every Python brief generator."""
    briefs = {}
    with tempfile.TemporaryDirectory() as tmp:
        state = run_state(tmp)
        base = {'id': 'task', 'purpose': 'fix the counter', 'requirement_ids': ['REQ-ONE'],
                'acceptance': ['tests pass'], 'expected_output': 'a commit', 'verification': 'python3 -m unittest'}
        tasks = {
            'writer': dict(base, writes=True, files=['src/*.py']),
            'reader': dict(base, kind='read', writes=False),
            'review': dict(base, id='review-1', kind='review', writes=False),
            'probe': dict(base, id='probe-x', kind='probe', writes=True,
                          probe={'nonce': 'nonce-1', 'marker': os.path.join(tmp, 'marker')}),
        }
        for name, task in tasks.items():
            briefs[f'engine:{name}'] = engine.brief(state, task, 'initial')
        correction = dict(tasks['writer'], next_round={'context': {'problem': 'no result block', 'raw': 'partial output'}})
        briefs['engine:correction'] = engine.brief(state, correction, 'correction')
        repair = dict(tasks['writer'], next_round={'context': {'findings': [{'severity': 'major', 'summary': 'off by one'}]}})
        briefs['engine:repair'] = engine.brief(state, repair, 'repair')
    for meta_path in sorted((ROOT / 'plugins').glob('*/plugin.json')):
        meta = json.loads(meta_path.read_text())
        briefs['adapter:' + meta['name']] = skills.render(meta, Path('/opt/t3-plugins') / meta['name'] / 'entry.md')
    briefs.update(handoff_briefs())
    return briefs


def handoff_briefs():
    plugin = ROOT / 'plugins/elephant-goldfish'
    spec = importlib.util.spec_from_file_location('render_handoff_hygiene', plugin / 'scripts/render_handoff.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rendered = {}
    previous = os.getcwd()
    for output_type in ('research', 'implementation'):
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                topic = Path('thinking/t')
                topic.mkdir(parents=True)
                (topic / 'meta.json').write_text(json.dumps({'slug': 't', 'title': 'A topic', 'output_type': output_type,
                                                             'github': {'mode': 'none'}, 'published': {}}))
                (topic / 'discovery.md').write_text('# Discovery\n\nThe problem, stated.\n')
                (topic / 'spec.md').write_text('# Spec\n\nPass when the output matches.\n')
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = module.main(['t', '--stdout', '--template-dir', str(plugin / 'templates')])
                if code not in (0, None):
                    raise AssertionError(f'render_handoff exited {code} for {output_type}')
                rendered['handoff:' + output_type] = out.getvalue()
            finally:
                os.chdir(previous)
    return rendered


class InstructionHygiene(unittest.TestCase):
    def test_the_linter_matches_case_and_spacing_variants(self):
        self.assertEqual(banned_in('Please THINK  step\nby STEP.'), ['think step by step'])
        self.assertEqual(banned_in('Only report HIGH-severity issues'), ['only report high-severity'])
        self.assertEqual(banned_in('Report what you saw.'), [])

    def test_instruction_files_contain_no_banned_phrases(self):
        files = instruction_files()
        self.assertIn(ROOT / 'shared/delegation.md', files)
        self.assertIn(ROOT / 'plugins/imps/entry.md', files)
        self.assertTrue(any('/templates/' in str(p) for p in files))
        for path in files:
            self.assertEqual(banned_in(path.read_text()), [], path)

    def test_generated_briefs_contain_no_banned_phrases(self):
        briefs = generated_briefs()
        self.assertGreaterEqual(len([k for k in briefs if k.startswith('engine:')]), 6)
        self.assertIn('handoff:implementation', briefs)
        for name, text in briefs.items():
            self.assertTrue(text.strip(), name)
            self.assertEqual(banned_in(text), [], name)

    def test_catalog_prompt_contains_no_banned_phrases(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / 'prefix'
            cli = [sys.executable, str(ROOT / 'scripts/catalog.py'), '--prefix', str(prefix)]
            subprocess.run(cli + ['install', 'imps'], check=True, capture_output=True, timeout=60)
            prompt = subprocess.run(cli + ['prompt', 'imps', 'run', 'fix', 'it'], check=True, capture_output=True,
                                    text=True, timeout=60).stdout
        self.assertIn('run: run fix it', prompt)
        self.assertEqual(banned_in(prompt), [])

    def test_review_brief_asks_for_every_finding_then_filters_separately(self):
        review = generated_briefs()['engine:review']
        every = review.index('Report every finding you observe, each with its severity')
        verdict = review.index('as a separate step, set the verdict')
        self.assertLess(every, verdict)
        self.assertNotIn('reasoning', review.casefold())


if __name__ == '__main__':
    unittest.main()
