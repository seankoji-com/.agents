"""Plan uses real installed helpers and planning receipts, without live providers."""
import hashlib
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tests.thinking_plan_review_fixtures import ThinkingPlanFixture
from tests.test_plan_review_installed_matrix import relocate


class PlanFixture(ThinkingPlanFixture):
    plugin = 'plan'
    operation = 'plan'
    output_root = 'plans'
    state_script = 'plan_state.py'


class PlanWorkflow(unittest.TestCase):
    def test_relocated_plan_requires_agreement_and_reuses_it_on_resume(self):
        from shared import model_selection as models
        from tests.thinking_plan_review_fixtures import upfront_selection
        with tempfile.TemporaryDirectory() as temp:
            f = PlanFixture(Path(temp) / 'fixture')
            f.install()
            f.package, f.manifest = relocate(f.box, {'plan': (f.package, f.manifest)})['plan']
            scripts = f.package / 'scripts'
            root = f.box.private / 'plans'
            selected = upfront_selection('topic', plugin='plan', operation='plan', output_root='plans')
            args = ['--output-type', 'implementation', '--request-reference', 'fixture:request:topic']
            legacy = deepcopy(selected)
            legacy.pop('agreement')
            legacy = models.freeze(legacy)
            f.command(scripts, root, 'topic', 'init', *args,
                      '--selection', f.box.payload(legacy), ok=False)
            self.assertFalse((root / 'topic/meta.json').exists())
            broken = deepcopy(selected)
            broken['agreement']['target']['label'] = 'Changed without approval'
            f.command(scripts, root, 'topic', 'init', *args,
                      '--selection', f.box.payload(broken), ok=False)
            f.command(scripts, root, 'topic', 'init', *args, '--selection', f.box.payload(selected))
            meta = root / 'topic/meta.json'
            before = json.loads(meta.read_text())
            for _ in range(2):
                resolved = f.command(scripts, root, 'topic', 'resolve')
                self.assertFalse(resolved['execution_authorized'])
                payload = {'selection': selected, 'operation': 'plan/plan'}
                result = f.box.run([sys.executable, f.package / 'shared/execution_agreement_cli.py',
                    'inherit', '--input', f.box.payload(payload)])
                self.assertFalse(json.loads(result.stdout)['chooser'])
                self.assertEqual(json.loads(meta.read_text())['model_admission'], before['model_admission'])

    def test_reviewed_plan_survives_relocation_and_edits_reopen_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            f = PlanFixture(Path(temp) / 'fixture')
            f.install()
            f.package, f.manifest = relocate(f.box, {'plan': (f.package, f.manifest)})['plan']
            scripts = f.package / 'scripts'
            root = f.box.private / 'plans'
            topic = root / 'topic'
            f.command(scripts, root, 'topic', 'init', '--output-type', 'implementation')
            (topic / 'discovery.md').write_text('# Problem\nInspect without writes.\n')
            (topic / 'spec.md').write_text('# Acceptance\n[REQ-SAFE] Return evidence without writes.\n')
            f.command(scripts, root, 'topic', 'review', '--decision', 'accepted',
                      '--scope', 'finalise-brief', '--discovery-sha256',
                      hashlib.sha256((topic / 'discovery.md').read_bytes()).hexdigest(),
                      '--evidence-ref', 'fixture:owner', '--operator-statement', 'I accept this discovery.')
            capabilities = f.box.payload({'inheritedProviderInstanceId': 'fixture-work',
                'inheritedModel': 'gpt-fixture', 'parentThreadId': 'fixture-author',
                'providers': [{'providerInstanceId': 'fixture-work', 'driverKind': 'codex',
                               'models': [{'id': 'gpt-fixture'}]}]})
            for name in ('discovery.md', 'spec.md'):
                f.command(scripts, root, 'topic', 'author', name, '--capabilities', capabilities)
            # A final handoff cannot be rendered from owner acceptance alone.
            argv = [sys.executable, scripts / 'render_handoff.py', 'topic', '--root', root,
                    '--capabilities', capabilities]
            self.assertNotEqual(f.box.run(argv, check=False).returncode, 0)
            accepted = f.approve(scripts, root, 'topic')
            self.assertTrue(accepted['ready'])
            f.box.run(argv)
            checked = f.box.run([sys.executable, scripts / 'validate_document.py',
                                '--root', root, '--slug', 'topic', '--mode', 'handoff'])
            self.assertTrue(json.loads(checked.stdout)['accepted'])
            state = f.command(scripts, root, 'topic', 'resolve')
            self.assertEqual(state['next_phase'], 'complete')
            self.assertFalse(state['execution_authorized'])
            self.assertIn((topic / 'spec.md').read_text(), (topic / 'handoff.md').read_text())
            (topic / 'spec.md').write_text('[REQ-SAFE] Changed scope needs a fresh review.\n')
            f.command(scripts, root, 'topic', 'gate', '--require',
                      'discovery,spec,plan_review,handoff', ok=False)
            self.assertNotEqual(f.box.run(argv, check=False).returncode, 0)

    def test_default_routing_does_not_interpret_prose_as_document_commands(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        from skills import route, render
        from support import skill_manifest
        meta = skill_manifest(Path(__file__).resolve().parents[1] / 'plugins/plan/plugin.json')
        for request in ('', 'check whether retries are safe', 'elephant migration', 'list current plans'):
            self.assertEqual(route(meta, request), 'plan')
        adapter = render(meta, Path('entry.md'))
        self.assertNotIn('Options:', adapter)
        self.assertNotIn('ask which operation', adapter)


if __name__ == '__main__':
    unittest.main()
