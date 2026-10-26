"""Public pinned revision/prepare and adversarial matrix after prefix relocation."""
import inspect
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from tests.test_rebuild_installed import Sandbox

ROOT = Path(__file__).resolve().parents[1]


def public_recovery(package, prefix, agents, state, private):
    """Run only installed APIs. All owner/native identities are invented."""
    from contextlib import redirect_stdout, redirect_stderr
    from copy import deepcopy
    from io import StringIO
    import json
    from pathlib import Path
    from core.jobs import prepare, record_dispatch, record_result, retry_task
    from core.jobs.store import Store, canonical, digest
    from shared.job_coordinator import create_pinned_job, verify_pinned_dependency, actual_author_lineages
    from shared.job_cli import main
    from shared import model_selection as models
    from tests.model_selection_fixtures import canonical_selection_input
    from tests.upfront_fixtures import agree
    from tests.test_legacy_author_provenance import native_proof
    package, prefix, agents, state, private = map(Path, (package, prefix, agents, state, private))
    manifest = json.loads((package / 'install-manifest.json').read_text())
    caller = {'actor': 'coordinator', 'installation_id': manifest['installation_id'],
              'workflow': 'fixture/recovery', 'package_digest': manifest['package_digest']}
    target = {'providerInstanceId': 'fixture-gateway', 'model': 'gateway/deepseek-example', 'options': {}}
    job = {'schema_version': 1, 'job_id': 'legacy-public', 'installation_id': manifest['installation_id'],
           'workflow': caller['workflow'], 'owner': {'id': 'invented-owner'}, 'objective': 'offline recovery',
           'requirements': {'R1': 'original evidence survives'}, 'authorization': {'actions': ['read']},
           'constraints': ['offline only'], 'dependencies': [{'key': 'imps', 'plugin': 'imps'}],
           'policy': {'max_repair_cycles': 3, 'max_live_workers': 2, 'model_selection_required': False},
           'stages': [{'id': 'work', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                       'validator_dependency': 'imps', 'revision': None}],
           'tasks': [{'task_id': 'cell', 'stage_id': 'work', 'logical_slot_id': 'cell', 'request_id': 'original',
                      'worker_id': 'imps/stage-executor', 'dependency_key': 'imps', 'role': 'worker',
                      'target': target, 'write_scope': {'mode': 'coordinator-only'}}],
           'result_contract': {'schema_version': 1}, 'decisions': [], 'history': [], 'metrics': {}}
    create_pinned_job(job, state, prefix, agents)
    store = Store(state, job['job_id'])
    def cli(command, data):
        source = private / ('input-' + str(len(list(private.iterdir()))) + '.json')
        source.write_bytes(canonical(data))
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = main([command, '--state-root', str(state), '--job', job['job_id'], '--input', str(source),
                           '--prefix', str(prefix), '--agents-root', str(agents)])
        return status, out.getvalue(), err.getvalue()
    proof_info = None
    for attempt in range(2):
        brief = prepare(store, caller, 'cell', verify_pinned_dependency, lambda _: True)
        current = store.load()['tasks'][0]; request = current['request_id']; host = 'old-host-' + str(attempt)
        record_dispatch(store, caller, 'cell', {'kind': 'accepted', 'request_id': request,
            'host_task_id': host, 'child_thread_id': 'old-child-' + str(attempt), 'status_identity': target})
        record_dispatch(store, caller, 'cell', {'kind': 'completion', 'request_id': request,
            'host_task_id': host, 'status': 'completed', 'work_state': 'result_available',
            'has_pending_child_runs': False, 'status_identity': target, 'completion_id': host})
        record_result(store, caller, 'cell', {'request_id': request, 'completion_id': host, 'result': b'not-json'})
        if attempt == 0:
            proof_info = native_proof(store.load(), store.load()['tasks'][0], Path(brief['path']))
            retry_task(store, caller, 'cell', 'invented malformed first attempt')
    original = store.load(); old = deepcopy(original['tasks'][0])
    retained = {str(p): p.read_bytes() for name in ('briefs', 'results') for p in (store.path/name).rglob('*') if p.is_file()}
    authors_file = private / 'document-authors.json'; authors_file.write_bytes(b'{"authors":["invented-original"]}\n')
    status, out, err = cli('decision', {'caller': caller, 'decision': proof_info[0]})
    assert status == 0, err
    assert actual_author_lineages(store.load()) == {'unknown', 'deepseek'}  # no selected coordinator yet
    data = canonical_selection_input(); data['operation'] = 'agent-tuneup/audit'; agree(data)
    record = models.freeze(data)
    current = store.load(); task = deepcopy(current['tasks'][0])
    task['selection_binding'] = {'role': 'workhorse', 'selection_sha256': record['selection_sha256']}
    task['target'] = deepcopy(record['work']['workhorse'])
    reviewer = {'task_id': 'independent', 'stage_id': 'work', 'logical_slot_id': 'independent',
                'request_id': 'new-independent', 'worker_id': 'imps/reviewer', 'dependency_key': 'imps',
                'role': 'worker', 'target': deepcopy(record['review_panel'][0]['target']),
                'selection_binding': {'role': 'reviewer', 'slot_id': 'review', 'selection_sha256': record['selection_sha256']},
                'write_scope': {'mode': 'coordinator-only'}}
    proposal = {'tasks': [task, reviewer], 'policy': {**current['policy'], 'model_selection_required': True},
                'model_selection': record, 'model_selection_sha256': record['selection_sha256']}
    owner = private / 'revision-owner.txt'; owner.write_text('Enable the displayed exact selection, retaining every charged attempt.\n')
    status, out, err = cli('decision', {'caller': caller, 'decision': {'id': 'enable', 'scope': 'plan:enable',
        'quote': owner.read_text().strip(), 'source': str(owner), 'source_sha256': digest(owner.read_bytes())}})
    assert status == 0, err
    before = store.file.read_bytes()
    stripped = deepcopy(proposal); stripped['tasks'][0]['handles'] = []
    status, out, err = cli('plan-revision', {'caller': caller, 'revision': {'id': 'enable', 'owner_decision_id': 'enable'}, 'new_plan': stripped})
    assert status == 2 and 'runtime' in err and store.file.read_bytes() == before, err
    unbound = deepcopy(proposal); unbound['tasks'][0].pop('selection_binding')
    status, out, err = cli('plan-revision', {'caller': caller, 'revision': {'id': 'enable', 'owner_decision_id': 'enable'}, 'new_plan': unbound})
    assert status == 2 and 'selection' in err and store.file.read_bytes() == before, err
    status, out, err = cli('plan-revision', {'caller': caller, 'revision': {'id': 'enable', 'owner_decision_id': 'enable'}, 'new_plan': proposal})
    assert status == 0, err
    updated = store.load()
    for key in ('handles', 'execution_history', 'attempt', 'dispatch_history'):
        assert updated['tasks'][0][key] == old[key], key
    assert updated['authorization'] == original['authorization']
    assert updated['policy'].get('transaction_guard_required') == original['policy'].get('transaction_guard_required')
    assert actual_author_lineages(updated) == {'openai', 'deepseek'}
    status, out, err = cli('prepare', {'caller': caller, 'task_id': 'independent'})
    assert status == 0, err
    prepared = json.loads(Path(json.loads(out)['path']).read_bytes())
    assert prepared['model_selection']['dispatch']['target'] == record['review_panel'][0]['target']
    assert all(Path(p).read_bytes() == raw for p, raw in retained.items())
    assert authors_file.read_bytes() == b'{"authors":["invented-original"]}\n'
    # Reopen owner/native/proof at the actual public prepare gate; no failed call writes state.
    for p in proof_info[1:]:
        raw = p.read_bytes(); p.write_bytes(raw + b' ')
        before = store.file.read_bytes()
        status, out, err = cli('prepare', {'caller': caller, 'task_id': 'independent'})
        assert status == 2 and 'Traceback' not in err, (status, err)
        assert store.file.read_bytes() == before
        p.write_bytes(raw)
    assert len(old['execution_history']) == 2 and old['attempt'] == 2
    archived = [h['tasks'][0] for h in updated['history'] if h.get('kind') == 'superseded-plan']
    assert len(archived) == 1 and 'selection_binding' not in archived[0]
    assert archived[0]['handles'] == old['handles'] and archived[0]['execution_history'] == old['execution_history']
    print(json.dumps({'public_revision_and_prepare': True, 'retained_charges': old['attempt'],
                      'author_lineages': sorted(actual_author_lineages(store.load())),
                      'historical_files': len(retained), 'guard_and_author_records_unchanged': True}))


class InstalledLegacyAuthorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.box = Sandbox(Path(cls.temporary.name))
        package, _ = cls.box.install('imps')
        original_prefix = cls.box.prefix
        moved = cls.box.base / 'moved-prefix'
        cls.box.prefix.rename(moved)
        cls.box.prefix = moved
        adopted = cls.box.t3('adopt', '--from-prefix', original_prefix)
        assert json.loads(adopted.stdout)['verified']
        cls.package = moved / 'imps' / package.name
        cls.support = cls.box.base / 'support'; (cls.support / 'tests').mkdir(parents=True)
        (cls.support / 'tests/__init__.py').write_text('')
        for name in ('model_selection_fixtures.py', 'upfront_fixtures.py', 'test_legacy_author_provenance.py'):
            shutil.copyfile(ROOT / 'tests' / name, cls.support / 'tests' / name)

    def run_installed(self, body):
        header = '''import json, os, sys
from pathlib import Path
package, support, forbidden = map(Path, sys.argv[1:4])
sys.dont_write_bytecode = True
sys.path[:0] = [str(package), str(support)]
def audit(event, args):
    if event in ('open','os.listdir','os.scandir') and args and isinstance(args[0], (str, bytes)):
        p = Path(os.fsdecode(args[0])).absolute()
        if p == forbidden or forbidden in p.parents:
            raise RuntimeError('source checkout access: ' + str(p))
sys.addaudithook(audit)
'''
        result = self.box.run([sys.executable, '-I', '-c', header + body,
                              self.package, self.support, ROOT], check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_relocated_matrix_rejects_unknown_tampered_and_modern_stripped_history(self):
        result = self.run_installed('''import unittest
from shared import legacy_author_provenance
assert Path(legacy_author_provenance.__file__).is_relative_to(package)
suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_legacy_author_provenance')
out = unittest.TextTestRunner(verbosity=1).run(suite)
assert out.wasSuccessful()
''')
        self.assertIn('OK', result.stderr)
        self.assertEqual((self.package/'shared/legacy_author_provenance.py').read_bytes(),
                         (ROOT/'shared/legacy_author_provenance.py').read_bytes())

    def test_relocated_public_owner_revision_and_prepare_preserve_prior_attempts(self):
        body = inspect.getsource(public_recovery)
        args = [str(self.package), str(self.box.prefix), str(self.box.agents),
                str(self.box.jobs), str(self.box.private)]
        result = self.run_installed(body + '\npublic_recovery(*' + repr(args) + ')\n')
        proof = json.loads(result.stdout)
        self.assertTrue(proof['public_revision_and_prepare'])
        self.assertEqual(proof['retained_charges'], 2)
        self.assertEqual(proof['author_lineages'], ['deepseek', 'openai'])
        self.assertTrue(proof['guard_and_author_records_unchanged'])


if __name__ == '__main__':
    unittest.main()
