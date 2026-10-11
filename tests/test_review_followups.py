"""Policy obligations and copied-artifact regressions survive scheduler removal."""
from support import CoreTestCase
from core import fsutil, recipe
from core.errors import InvalidInput
import json


class FollowupTest(CoreTestCase):
    def test_waiver_names_a_real_requirement(self):
        run = self.init(self.plan(self.make_repo()))
        self.assertEqual(run.submit_raw('waive', {'target':'requirement:REQ-MISSING', 'reason':'x',
                                                'decided_by':'owner','operator_quote':'skip it'})[0], 2)

    def test_policy_check_names_are_unique_and_obligations_cannot_weaken(self):
        repo = self.make_repo()
        plan = self.plan(repo)
        check = plan['policy']['checks'][0]
        self.init(self.plan(repo, policy={'checks':[check, check]}), expect=2)
        run = self.init(self.plan(repo))
        for policy in ({'checks':[]}, {'checks':[dict(check, argv=['true'])]}, {'role_overrides':{}}, {'evidence_roots':[str(self.tmp)]}):
            self.assertEqual(run.submit_raw('policy', {'policy':policy})[0], 4)

    def test_copy_artifact_replaces_stale_target(self):
        run = self.init(self.plan(self.make_repo()))
        source = run.scratch('x.txt', 'original')
        entry = fsutil.copy_artifact(source, run.run_dir, 'checks', [run.run_dir])
        target = run.run_dir/entry['path']
        target.write_text('tampered')
        copied = fsutil.copy_artifact(source, run.run_dir, 'checks', [run.run_dir])
        self.assertEqual(target.read_text(), 'original')
        self.assertEqual(copied['sha256'], entry['sha256'])

    def test_recipe_stamp_refuses_colliding_evidence_names(self):
        run_dir = self.tmp/'run'
        (run_dir/'a').mkdir(parents=True)
        (run_dir/'b').mkdir()
        entries=[]
        for directory in ('a','b'):
            path=run_dir/directory/'same.txt'
            path.write_text(directory)
            entries.append({'path':directory+'/same.txt','sha256':fsutil.sha256_file(path)})
        recipe_path=self.write('recipe.json', json.dumps({'features':[{'id':'F-X'}]}))
        state={'phase':'completed','run_id':'r1','acceptance':[{'requirement_id':'REQ-X','status':'passed',
                'kind':'runtime','artifacts':entries}]}
        with self.assertRaises(InvalidInput) as caught:
            recipe.stamp(recipe_path,state,run_dir,'F-X','REQ-X')
        self.assertEqual(caught.exception.code,'evidence_name_collision')
