"""Source-spec case 13 (evidence half): artifact traversal and symlink escapes are
rejected, and stored artifacts cannot point outside the run directory."""
import json
import os

from support import CoreTestCase


class PathSafetyTest(CoreTestCase):
    def verifying(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo))
        (repo / 'wordstat.py').write_text('changed\n')
        return repo, run

    def accept(self, run, path):
        return run.submit_raw('evidence', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                             'explanation': 'x', 'artifacts': [str(path)], 'binding': run.binding()})

    def test_traversal_is_rejected(self):
        repo, run = self.verifying()
        (self.tmp / 'outside.log').write_text('secret')
        before = (run.run_dir / 'run.json').read_bytes()
        code, env, _ = self.accept(run, run.run_dir / 'scratch' / '..' / '..' / '..' / '..' / 'outside.log')
        self.assertEqual((code, env['error']['code']), (2, 'path_traversal'))
        self.assertEqual((run.run_dir / 'run.json').read_bytes(), before)

    def test_symlink_escape_is_rejected(self):
        repo, run = self.verifying()
        (self.tmp / 'outside.log').write_text('secret')
        link = run.run_dir / 'scratch' / 'innocent.log'
        os.symlink(self.tmp / 'outside.log', link)
        code, env, _ = self.accept(run, link)
        self.assertEqual((code, env['error']['code']), (2, 'path_escape'))
        inner = repo / 'link-out'
        os.symlink(self.tmp / 'outside.log', inner)
        code, env, _ = self.accept(run, inner)
        self.assertEqual((code, env['error']['code']), (2, 'path_escape'))

    def test_tampered_stored_artifact_path_is_not_trusted(self):
        repo, run = self.verifying()
        log = run.scratch('ok.log', 'fine')
        self.assertEqual(self.accept(run, log)[0], 0)
        state_file = run.run_dir / 'run.json'
        data = json.loads(state_file.read_text())
        data['acceptance'][-1]['artifacts'][0]['path'] = '../../outside.log'
        state_file.write_text(json.dumps(data))
        from support import cli
        code, env, _ = cli('validate', *run.args())
        self.assertIn('escapes the run directory', json.dumps(env['data']['stale']))
