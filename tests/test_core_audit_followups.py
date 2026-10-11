"""Pre-verification binding, input truthfulness and schema regression checks."""
import json
from pathlib import Path
from unittest import mock

from support import CoreTestCase, ROOT, cli
from core import cli as core_cli, schema, snapshot
from core.errors import InvalidInput


class EvidenceBindingTest(CoreTestCase):
    def payload(self, run, name='unit'):
        check = run.state['policy']['checks'][0]
        return {'name': name, 'argv': check['argv'], 'cwd': run.state['repo']['worktree'], 'exit_code': 0,
                'log': str(run.scratch('check.log', 'ok')), 'binding': run.binding()}

    def test_precheck_binding_required_and_edit_before_submission_rejected(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo))
        payload = self.payload(run)
        (repo/'wordstat.py').write_text('edited after check')
        self.assertEqual(run.submit_raw('check', payload)[0], 4)
        self.assertEqual(run.state['checks'], [])
        payload = self.payload(run)
        del payload['binding']
        self.assertEqual(run.submit_raw('check', payload)[0], 2)

    def test_check_receipts_require_planned_argv_cwd_and_integer_exit(self):
        run = self.init(self.plan(self.make_repo()))
        for changes, expected in (({'argv':['true']},2), ({'cwd':str(self.tmp)},2), ({'exit_code':True},2),
                                  ({'exit_code':'0'},2), ({'name':'unknown'},2), ({'exit_code':None},2),
                                  ({'unavailable_reason':'missing tool'},2)):
            self.assertEqual(run.submit_raw('check', dict(self.payload(run), **changes))[0], expected)
        run.submit('check', self.payload(run))
        saved = run.state['checks'][0]
        self.assertEqual(saved['snapshot'], run.binding()['snapshot'])
        self.assertEqual(saved['exit_code'], 0)
        self.assertTrue(saved['artifact']['sha256'])

    def test_semantic_change_after_check_rejects_old_binding(self):
        run = self.init(self.plan(self.make_repo()))
        payload = self.payload(run)
        run.submit('policy', {'policy': {'review': {'required': True}}})
        self.assertEqual(run.submit_raw('check', payload)[0], 4)

    def test_evidence_stores_attested_snapshot_not_later_scan(self):
        run = self.init(self.plan(self.make_repo()))
        payload = self.payload(run)
        run.submit('check', payload)
        self.assertEqual(run.state['checks'][0]['snapshot'], payload['binding']['snapshot'])
        self.assertEqual(run.state['checks'][0]['contract_hash'], payload['binding']['contract_hash'])
        self.assertEqual(run.state['checks'][0]['policy_hash'], payload['binding']['policy_hash'])

    def test_tuple_form_schema_items_is_refused(self):
        with self.assertRaises(InvalidInput):
            schema.check_keywords({'type':'array','items':[{'type':'string'}]})

    def test_internal_errors_keep_environment_exit_and_value_errors_are_input(self):
        import contextlib
        import io
        for error, expected in ((KeyError('bug'),5), (TypeError('bug'),5), (ValueError('bad'),2)):
            output = io.StringIO()
            with mock.patch.object(core_cli, 'execute', side_effect=error), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                code = core_cli.main(['status'])
            self.assertEqual(code, expected)
            self.assertFalse(json.loads(output.getvalue())['ok'])
