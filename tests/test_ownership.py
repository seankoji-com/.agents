"""Source-spec cases 2 and 3, REQ-OWNERSHIP: claims, generations and recovery."""
import json
import subprocess
import sys
import threading
import time

from support import CLI, CoreTestCase, cli


class OwnershipTest(CoreTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()
        self.run = self.init(self.plan(self.repo))
        self.state_file = self.run.run_dir / 'run.json'

    def test_mutation_without_any_claim_is_rejected_when_no_owner_file_exists(self):
        """Regression for workflow-evidence.py:212, where a missing owner file let a patch through."""
        self.assertFalse((self.run.run_dir / 'owner.json').exists())
        before = self.state_file.read_bytes()
        code, env, _ = self.run.record_raw('note', {'key': 'x', 'text': 'y'}, token='made-up-token', generation=1)
        self.assertEqual(code, 3, env)
        self.assertEqual(env['error']['code'], 'not_owned')
        code, env, _ = self.run.record_raw('note', {'key': 'x', 'text': 'y'}, token='', generation=1)
        self.assertEqual(code, 3, env)
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_stale_generation_rejected_and_state_bytes_unchanged(self):
        self.run.claim()
        generation = self.run.generation
        self.run.record('note', {'key': 'a', 'text': 'first'}, generation=generation)
        before = self.state_file.read_bytes()
        code, env, _ = self.run.record_raw('note', {'key': 'b', 'text': 'second'}, generation=generation)
        self.assertEqual(code, 3, env)
        self.assertEqual(env['error']['code'], 'stale_generation')
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_wrong_token_rejected(self):
        self.run.claim()
        before = self.state_file.read_bytes()
        code, env, _ = self.run.record_raw('note', {'key': 'a', 'text': 'x'}, token='not-the-token')
        self.assertEqual((code, env['error']['code']), (3, 'token_mismatch'))
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_concurrent_claims_have_exactly_one_winner(self):
        outcomes, errors = [], []
        args = [sys.executable, str(CLI), 'claim', *self.run.args()]
        args = [str(a) for a in args]

        def claim():
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=60)
                outcomes.append((result.returncode, json.loads(result.stdout)))
            except Exception as exc:  # a thread's exception is otherwise lost
                errors.append(repr(exc))
        threads = [threading.Thread(target=claim) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        winners = [env for code, env in outcomes if code == 0]
        losers = [env for code, env in outcomes if code == 3]
        self.assertEqual(len(winners), 1, outcomes)
        self.assertEqual(len(losers), 7)
        self.assertTrue(all(env['error']['code'] == 'owned' for env in losers))

    def test_concurrent_writers_with_same_generation_only_one_lands(self):
        self.run.claim()
        generation = self.run.generation
        results = []

        errors = []

        def write(n):
            try:
                results.append(self.run.record_raw('note', {'key': f'k{n}', 'text': str(n)}, generation=generation)[0])
            except Exception as exc:
                errors.append(repr(exc))
        threads = [threading.Thread(target=write, args=(n,)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [0, 3, 3, 3, 3, 3])
        self.assertEqual(len(self.run.state['notes']), 1)

    def test_unknown_fields_survive_updates(self):
        data = json.loads(self.state_file.read_text())
        data['x_future_field'] = {'kept': True}
        data['tasks'][0]['x_task_extension'] = [1, 2]
        self.state_file.write_text(json.dumps(data))
        self.run.claim()
        self.run.record('note', {'key': 'k', 'text': 'v'})
        after = self.run.state
        self.assertEqual(after['x_future_field'], {'kept': True})
        self.assertEqual(after['tasks'][0]['x_task_extension'], [1, 2])

    def test_recover_requires_confirmed_dead_even_after_deadline(self):
        self.run.claim()
        stale = self.run.token
        owner_file = self.run.run_dir / 'owner.json'
        owner = json.loads(owner_file.read_text())
        owner['deadline'] = time.time() - 3600
        owner_file.write_text(json.dumps(owner))
        code, env, _ = cli('recover', *self.run.args('--token', stale))
        self.assertNotEqual(code, 0)
        self.assertEqual((code, env['error']['code']), (4, 'recovery_unconfirmed'))
        self.assertTrue(owner_file.exists(), 'claim survives a recover without --confirmed-dead')
        code, env, _ = cli('claim', *self.run.args())
        self.assertEqual(code, 3, 'a new invocation cannot claim while the crashed claim stands')
        code, env, _ = cli('recover', *self.run.args('--token', stale, '--confirmed-dead'))
        self.assertEqual(code, 0, env)
        self.assertFalse(owner_file.exists())
        self.run.claim()
        self.assertNotEqual(self.run.token, stale)

    def test_budget_persists_across_resume(self):
        self.run.claim()
        time.sleep(1.1)
        self.run.release()
        spent = self.run.state['budget']['spent_seconds']
        self.assertGreaterEqual(spent, 1.0)
        self.run.claim()
        self.run.release()
        self.assertGreaterEqual(self.run.state['budget']['spent_seconds'], spent)
