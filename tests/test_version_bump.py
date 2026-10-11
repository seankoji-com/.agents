"""Execute the workflow's real bump step against a synthetic Git history."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('jq'), 'jq required by the workflow')
class VersionBumpTest(unittest.TestCase):
    def test_shared_change_bumps_existing_from_the_fork_point_and_preserves_new_and_explicit_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

            def write(name, version):
                path = root / 'plugins' / name / 'plugin.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'name': name, 'version': version}))

            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            write('existing', '1.0.0')
            write('explicit', '1.0.0')
            (root / 'shared').mkdir()
            contract = root / 'shared/t3-runtime.md'
            contract.write_text('old')
            git('add', '.')
            git('commit', '-qm', 'base')
            git('checkout', '-q', '-b', 'topic')
            write('new-plugin', '0.1.0')
            write('explicit', '1.1.0')
            contract.write_text('new')
            git('add', '.')
            git('commit', '-qm', 'contract and catalog')
            head = git('rev-parse', 'HEAD')
            # The base branch moves on after the fork point. Diffing against its tip would
            # read 1.0.5 as the base version and skip the bump; the fork point says 1.0.0.
            git('checkout', '-q', 'main')
            write('existing', '1.0.5')
            git('add', '.')
            git('commit', '-qm', 'release bump on main after the branch point')
            git('update-ref', 'refs/remotes/origin/main', 'main')
            git('checkout', '-q', 'topic')
            workflow = (ROOT / '.github/workflows/version-bump.yml').read_text()
            script = textwrap.dedent(workflow.split('run: |\n', 1)[1].split('\n      - name:', 1)[0])
            self.assertIn('git merge-base', script)
            self.assertNotIn('pull_request.base.sha', workflow)
            # Event values reach the script through env, never spliced into its source.
            self.assertNotIn('${{', script)
            output = root / 'output'
            for expected in ('changed=1', 'changed=0'):
                output.write_text('')
                result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root,
                                        env={**os.environ, 'GITHUB_OUTPUT': str(output),
                                             'BASE_REF': 'main', 'HEAD': head},
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.read_text().strip(), expected)
            for name, version in {'existing': '1.0.1', 'explicit': '1.1.0', 'new-plugin': '0.1.0'}.items():
                self.assertEqual(json.loads((root / 'plugins' / name / 'plugin.json').read_text())['version'], version)
