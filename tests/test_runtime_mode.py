"""Runtime modes remain config data; core no longer builds dispatch calls."""
import json
from support import ROOT, CoreTestCase
from core import schema


class RuntimeModeTest(CoreTestCase):
    def test_persisted_role_runtime_mode_is_not_silently_rewritten(self):
        roles = {'reviewer': {'chain': [{'select': 'fixed', 'providerInstanceId': 'fixture-provider',
                                       'model': 'fixture-model', 'runtimeMode': 'full-access'}]}}
        run = self.init(self.plan(self.make_repo(), roles=roles))
        self.assertEqual(run.state['roles']['reviewer']['chain'][0]['runtimeMode'], 'full-access')
        bad = {'reviewer': {'chain': [dict(roles['reviewer']['chain'][0], runtimeMode='root')]}}
        self.init(self.plan(self.make_repo(), roles=bad), expect=2)
        published = schema.load_schema_file(ROOT/'plugins/imps/schemas/roles.schema.json')
        self.assertEqual(schema.errors(roles, published), [])
