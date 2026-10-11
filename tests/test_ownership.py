"""Atomic transactions remain safe without an agent lease or optimistic counter."""
import json
import subprocess
import sys

from support import CLI, CoreTestCase, cli


class StorageTest(CoreTestCase):
    def test_concurrent_writers_keep_every_update(self):
        run = self.init(self.plan(self.make_repo()))
        processes = [subprocess.Popen([sys.executable, str(CLI), 'note', *map(str, run.args()),
                                       '--json', json.dumps({'text': f'note {i}'})],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for i in range(12)]
        for process in processes:
            out, err = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, out + err)
            self.assertTrue(json.loads(out)['ok'])
        self.assertEqual({n['text'] for n in run.status()['notes']}, {f'note {i}' for i in range(12)})
        self.assertTrue((run.run_dir / 'run.lock').is_file())
        self.assertFalse((run.run_dir / 'owner.json').exists())

    def test_rejected_submission_leaves_state_byte_identical(self):
        run = self.init(self.plan(self.make_repo()))
        before = (run.run_dir / 'run.json').read_bytes()
        code, env, _ = run.submit_raw('note', {'text': 'x', 'ready': True})
        self.assertEqual(code, 2)
        self.assertEqual((run.run_dir / 'run.json').read_bytes(), before)

    def test_removed_commands_and_counter_are_refused(self):
        run = self.init(self.plan(self.make_repo()))
        for op in ('claim', 'release', 'recover', 'next', 'record', 'unblock'):
            code, env, _ = cli(op, *run.args())
            self.assertEqual((code, env['error']['code']), (2, 'usage'))
        code, env, _ = cli('note', *run.args('--expect-generation', '1', '--json', '{"text":"x"}'))
        self.assertEqual(code, 2)
        self.assertNotIn('generation', run.state)

    def test_old_major_is_refused_by_every_state_command_without_writes(self):
        run = self.init(self.plan(self.make_repo()))
        path = run.run_dir / 'run.json'
        path.write_text('{"schema_version":1,"generation":9}')
        (run.run_dir / 'run.lock').unlink()
        before = {p.name: p.read_bytes() for p in run.run_dir.iterdir() if p.is_file()}
        for op in ('status', 'snapshot', 'validate', 'report', 'note', 'cancel', 'recipe-stamp'):
            code, env, _ = cli(op, *run.args('--json', '{"text":"x"}'))
            self.assertEqual(code, 2, env)
            self.assertIn('major version 1', env['error']['message'])
            self.assertIn('major version 2', env['error']['message'])
        self.assertEqual({p.name: p.read_bytes() for p in run.run_dir.iterdir() if p.is_file()}, before)
