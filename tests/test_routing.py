"""User-local routing config: setup writes it from a saved capabilities file, resolve
returns available candidates in tier order. Every call runs with an isolated HOME and
XDG_CONFIG_HOME; the provider and model names are synthetic."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import routing  # noqa: E402


def provider(pid, driver, models, runnable=True, constraints=()):
    return {'providerInstanceId': pid, 'driverKind': driver, 'displayName': pid,
            'models': [{'id': m, 'label': m} for m in models], 'canRunChildTask': runnable,
            'canRunCrossProviderChildTask': runnable, 'constraints': list(constraints)}


CAPABILITIES = {
    'parentThreadId': 'thread-1', 'inheritedProviderInstanceId': 'claudeAgent', 'inheritedModel': 'model-c2',
    'runtimeMode': 'full-access',
    'providers': [
        provider('codex', 'codex', ['model-x1', 'model-x2']),
        provider('claudeAgent', 'claudeAgent', ['model-c1', 'model-c2']),
        provider('cursor', 'cursor', [], runnable=False, constraints=['Provider instance is disabled.']),
        provider('grok', 'grok', ['model-g1'], runnable=False, constraints=['Provider instance is disabled.']),
        provider('opencode', 'opencode', ['gateway/glm-9', 'gateway/kimi-9', 'shared-model']),
        provider('gemini-box', 'antigravity', ['shared-model', 'model-a2']),
    ],
}


def entry(pid, model, tier, lineage):
    return {'providerInstanceId': pid, 'model': model, 'tier': tier, 'lineage': lineage}


class RoutingCli(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.config_home = self.base / 'xdg config'
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.config_home),
                    'XDG_STATE_HOME': str(self.base / 'state')}
        self.config = self.config_home / 't3-plugins/routing.json'
        self.caps = self.base / 'caps.json'
        self.caps.write_text(json.dumps(CAPABILITIES))
        self.repo = self.base / 'repo'
        self.repo.mkdir()

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/catalog.py'), '--prefix', str(self.base / 'prefix'),
                                 *args], env=self.env, cwd=self.repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def resolve(self, role, code=0, caps=None):
        result = self.cli('resolve', role, '--capabilities', str(caps or self.caps), code=code)
        return json.loads(result.stdout) if result.stdout.strip() else result

    def write(self, config, path=None):
        path = path or self.config
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config))

    def test_setup_writes_a_new_config_from_saved_capabilities(self):
        receipts = [json.loads(l) for l in self.cli('setup', 'imps', '--root', str(self.base / 'skills'),
                                                     '--capabilities', str(self.caps)).stdout.splitlines()]
        self.assertEqual(receipts[-1]['action'], 'written')
        self.assertEqual(receipts[-1]['routing'], str(self.config))
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        config = json.loads(self.config.read_text())
        self.assertEqual(config['tiers'], ['low', 'medium', 'high'])
        self.assertEqual(set(config['roles']), {'workhorse', 'reviewer', 'judgement'})
        # Runtime modes are data in the config: auto by default, full-access for OpenCode.
        self.assertEqual(config['providers'], {'claudeAgent': {'runtimeMode': 'auto'}, 'codex': {'runtimeMode': 'auto'},
                                               'gemini-box': {'runtimeMode': 'auto'},
                                               'opencode': {'runtimeMode': 'full-access', 'requireRuntimeMode': True}})
        # Disabled providers get no entries.
        names = {e['providerInstanceId'] for entries in config['roles'].values() for e in entries}
        self.assertNotIn('cursor', names)
        self.assertNotIn('grok', names)
        # The session model judges; reviewers of another lineage come before it.
        self.assertEqual(config['roles']['judgement'], [entry('claudeAgent', 'model-c2', 'high', 'anthropic')])
        reviewers = config['roles']['reviewer']
        self.assertEqual(reviewers[-1]['providerInstanceId'], 'claudeAgent')
        self.assertTrue(all(r['lineage'] != 'anthropic' for r in reviewers[:-1]))
        # One provider, several lineages: labelled from the model family, not the provider.
        self.assertIn(entry('opencode', 'gateway/glm-9', 'medium', 'glm'), reviewers)
        self.assertIn(entry('gemini-box', 'shared-model', 'medium', 'google'), reviewers)
        # No model IDs in the package: everything above came from the capabilities file.
        self.assertFalse((self.home / '.config').exists())

    def test_setup_offers_every_other_lineage_as_a_reviewer(self):
        # Two gateways list the session's lineage first; other lineages come later.
        caps = {'inheritedProviderInstanceId': 'gw-one', 'inheritedModel': 'gateway/gpt-9', 'runtimeMode': 'auto',
                'providers': [provider('gw-one', 'opencode', ['gateway/gpt-9', 'gateway/claude-9']),
                              provider('gw-two', 'opencode', ['gateway/gpt-9', 'gateway/gemini-9'])]}
        config = routing.default_config(caps)
        reviewers = [(r['providerInstanceId'], r['model'], r['lineage']) for r in config['roles']['reviewer']]
        self.assertEqual(reviewers, [('gw-one', 'gateway/claude-9', 'anthropic'), ('gw-two', 'gateway/gemini-9', 'google'),
                                     ('gw-one', 'gateway/gpt-9', 'openai')])

    def test_resolve_puts_other_lineages_first_for_an_implementer(self):
        self.write({'schema_version': 1, 'tiers': ['low', 'high'], 'providers': {},
                    'roles': {'reviewer': [entry('claudeAgent', 'model-c1', 'low', 'anthropic'),
                                           entry('opencode', 'shared-model', 'low', 'anthropic'),
                                           entry('codex', 'model-x1', 'high', 'openai'),
                                           entry('gemini-box', 'model-a2', 'high', 'google')]}})
        result = json.loads(self.cli('resolve', 'reviewer', '--capabilities', str(self.caps),
                                     '--implementer-lineage', 'anthropic').stdout)
        self.assertEqual([(c['model'], c['independent']) for c in result['candidates']],
                         [('model-x1', True), ('model-a2', True), ('model-c1', False), ('shared-model', False)])
        # Unknown lineage on either side is unverified, never independent.
        self.write({'schema_version': 1, 'tiers': ['low'], 'providers': {},
                    'roles': {'reviewer': [entry('claudeAgent', 'model-c1', 'low', 'anthropic'),
                                           entry('opencode', 'gateway/kimi-9', 'low', 'unknown'),
                                           entry('codex', 'model-x1', 'low', 'openai')]}})
        result = json.loads(self.cli('resolve', 'reviewer', '--capabilities', str(self.caps),
                                     '--implementer-lineage', 'anthropic').stdout)
        self.assertEqual([(c['model'], c['independent']) for c in result['candidates']],
                         [('model-x1', True), ('gateway/kimi-9', None), ('model-c1', False)])
        result = json.loads(self.cli('resolve', 'reviewer', '--capabilities', str(self.caps),
                                     '--implementer-lineage', 'unknown').stdout)
        self.assertEqual({c['independent'] for c in result['candidates']}, {None})
        self.write({'schema_version': 1, 'tiers': ['low', 'high'], 'providers': {},
                    'roles': {'reviewer': [entry('claudeAgent', 'model-c1', 'low', 'anthropic'),
                                           entry('opencode', 'shared-model', 'low', 'anthropic'),
                                           entry('codex', 'model-x1', 'high', 'openai'),
                                           entry('gemini-box', 'model-a2', 'high', 'google')]}})
        # Without an implementer lineage the order is plain tier order.
        self.assertEqual([c['model'] for c in self.resolve('reviewer')['candidates']],
                         ['model-c1', 'shared-model', 'model-x1', 'model-a2'])

    def test_setup_preserves_an_existing_config(self):
        mine = {'schema_version': 1, 'tiers': ['cheap', 'dear'], 'providers': {},
                'roles': {'workhorse': [entry('codex', 'model-x2', 'cheap', 'openai')]}}
        self.write(mine)
        before = self.config.read_bytes()
        receipt = json.loads(self.cli('setup', 'imps', '--root', str(self.base / 'skills'),
                                      '--capabilities', str(self.caps)).stdout.splitlines()[-1])
        self.assertEqual(receipt, {'routing': str(self.config), 'action': 'preserved', 'valid': True})
        self.assertEqual(self.config.read_bytes(), before)

    def test_setup_keeps_a_malformed_config_and_says_so(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{broken')
        result = self.cli('setup', 'imps', '--root', str(self.base / 'skills'), '--capabilities', str(self.caps), code=1)
        self.assertEqual(self.config.read_text(), '{broken')
        self.assertFalse(json.loads(result.stdout.splitlines()[-1])['valid'])
        self.assertIn('invalid', result.stderr)

    def test_setup_without_capabilities_writes_no_config(self):
        self.cli('setup', 'imps', '--root', str(self.base / 'skills'))
        self.assertFalse(self.config.exists())

    def test_fallback_path_without_xdg(self):
        env = dict(self.env)
        env.pop('XDG_CONFIG_HOME')
        self.assertEqual(routing.config_path(env), self.home / '.config/t3-plugins/routing.json')
        self.assertEqual(routing.config_path({'HOME': str(self.home), 'XDG_CONFIG_HOME': 'relative'}),
                         self.home / '.config/t3-plugins/routing.json')
        self.assertEqual(routing.config_path(self.env), self.config)

    def test_resolve_returns_available_candidates_in_tier_order(self):
        self.write({'schema_version': 1, 'tiers': ['low', 'medium', 'high'],
                    'providers': {'codex': {'runtimeMode': 'auto'}},
                    'roles': {'workhorse': [entry('claudeAgent', 'model-c2', 'high', 'anthropic'),
                                            entry('codex', 'model-x2', 'low', 'openai'),
                                            entry('opencode', 'gateway/kimi-9', 'medium', 'kimi')]}})
        result = self.resolve('workhorse')
        self.assertEqual([c['model'] for c in result['candidates']], ['model-x2', 'gateway/kimi-9', 'model-c2'])
        self.assertEqual(result['unavailable'], [])
        self.assertEqual(result['sources'], [str(self.config)])

    def test_missing_role_and_missing_config(self):
        result = self.cli('resolve', 'reviewer', '--capabilities', str(self.caps), code=2)
        self.assertIn('no routing config', result.stderr)
        self.write({'schema_version': 1, 'tiers': ['low'], 'providers': {},
                    'roles': {'workhorse': [entry('codex', 'model-x1', 'low', 'openai')]}})
        result = self.cli('resolve', 'reviewer', '--capabilities', str(self.caps), code=2)
        self.assertIn("role 'reviewer' is not configured", result.stderr)

    def test_malformed_configs_are_rejected(self):
        bad = [
            '{not json',
            json.dumps([]),
            json.dumps({'schema_version': 2, 'tiers': ['low'], 'roles': {}}),
            json.dumps({'schema_version': 1, 'tiers': [], 'roles': {}}),
            json.dumps({'schema_version': 1, 'tiers': ['low', 'low'], 'roles': {}}),
            json.dumps({'schema_version': 1, 'tiers': ['low'], 'roles': {'workhorse': [{'model': 'm'}]}}),
            json.dumps({'schema_version': 1, 'tiers': ['low'], 'roles': {'workhorse': [entry('codex', 'model-x1', 'top', 'openai')]}}),
            json.dumps({'schema_version': 1, 'tiers': ['low'], 'providers': {'codex': {'runtimeMode': 'yolo'}},
                        'roles': {'workhorse': [entry('codex', 'model-x1', 'low', 'openai')]}}),
            json.dumps({'schema_version': 1, 'tiers': ['low'], 'roles': {'workhorse': 'codex'}}),
        ]
        for text in bad:
            self.config.parent.mkdir(parents=True, exist_ok=True)
            self.config.write_text(text)
            result = self.cli('resolve', 'workhorse', '--capabilities', str(self.caps), code=2)
            self.assertIn('t3-plugins:', result.stderr, text)

    def test_malformed_capabilities_are_rejected(self):
        self.write({'schema_version': 1, 'tiers': ['low'], 'providers': {},
                    'roles': {'workhorse': [entry('codex', 'model-x1', 'low', 'openai')]}})
        for text in ('nope', json.dumps({'providers': 'all'})):
            self.caps.write_text(text)
            self.cli('resolve', 'workhorse', '--capabilities', str(self.caps), code=2)
        self.caps.write_text(json.dumps({'response': CAPABILITIES}))  # the shape imps records
        self.assertEqual(len(self.resolve('workhorse')['candidates']), 1)

    def test_disabled_provider_is_reported_not_used(self):
        self.write({'schema_version': 1, 'tiers': ['low', 'high'], 'providers': {},
                    'roles': {'reviewer': [entry('grok', 'model-g1', 'low', 'xai'),
                                           entry('codex', 'model-x1', 'high', 'openai')]}})
        result = self.resolve('reviewer')
        self.assertEqual([c['providerInstanceId'] for c in result['candidates']], ['codex'])
        self.assertEqual(result['unavailable'][0]['providerInstanceId'], 'grok')
        self.assertIn('disabled', result['unavailable'][0]['reason'])

    def test_same_model_under_two_providers_stays_distinct(self):
        self.write({'schema_version': 1, 'tiers': ['low'], 'providers': {'opencode': {'runtimeMode': 'auto'}},
                    'roles': {'workhorse': [entry('gemini-box', 'shared-model', 'low', 'google')]}})
        result = self.resolve('workhorse')
        self.assertEqual([(c['providerInstanceId'], c['model']) for c in result['candidates']],
                         [('gemini-box', 'shared-model')])
        caps = dict(CAPABILITIES, providers=[p for p in CAPABILITIES['providers'] if p['providerInstanceId'] != 'gemini-box'])
        self.caps.write_text(json.dumps(caps))
        # The same model ID is still offered by opencode, but that is a different entry.
        result = self.resolve('workhorse', code=1)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['unavailable'][0]['reason'], 'provider_absent')

    def test_configured_model_absent_from_capabilities_is_reported_not_substituted(self):
        self.write({'schema_version': 1, 'tiers': ['low'], 'providers': {},
                    'roles': {'judgement': [entry('claudeAgent', 'model-c9', 'low', 'anthropic')]}})
        result = self.resolve('judgement', code=1)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['unavailable'], [dict(entry('claudeAgent', 'model-c9', 'low', 'anthropic'),
                                                      reason='model_absent')])

    def test_repository_policy_takes_precedence(self):
        self.write({'schema_version': 1, 'tiers': ['low', 'high'], 'providers': {'codex': {'runtimeMode': 'auto'}},
                    'roles': {'reviewer': [entry('codex', 'model-x1', 'low', 'openai')],
                              'workhorse': [entry('codex', 'model-x2', 'low', 'openai')]}})
        policy = self.repo / '.t3-plugins/routing.json'
        self.write({'roles': {'reviewer': [entry('gemini-box', 'model-a2', 'high', 'google')]},
                    'providers': {'codex': {'runtimeMode': 'approval-required'}}}, policy)
        result = self.resolve('reviewer')
        self.assertEqual([c['model'] for c in result['candidates']], ['model-a2'])
        self.assertEqual(result['sources'], [str(self.config), str(policy)])
        workhorse = self.resolve('workhorse')
        self.assertEqual(workhorse['candidates'][0]['runtimeMode'], 'approval-required')
        # Repository policy alone is enough when the user has no config.
        self.config.unlink()
        self.write({'schema_version': 1, 'tiers': ['high'],
                    'roles': {'reviewer': [entry('gemini-box', 'model-a2', 'high', 'google')]}}, policy)
        self.assertEqual(self.resolve('reviewer')['sources'], [str(policy)])

    def test_provider_missing_from_config_gets_the_owner_default(self):
        self.write({'schema_version': 1, 'tiers': ['low'], 'providers': {},
                    'roles': {'workhorse': [entry('opencode', 'gateway/glm-9', 'low', 'glm'),
                                            entry('codex', 'model-x1', 'low', 'openai')]}})
        modes = [c['runtimeMode'] for c in self.resolve('workhorse')['candidates']]
        self.assertEqual(modes, ['full-access', 'auto'])

    def test_child_mode_broader_than_parent_is_lowered_visibly(self):
        self.write({'schema_version': 1, 'tiers': ['low'], 'providers': {'opencode': {'runtimeMode': 'full-access'},
                                                                         'codex': {'runtimeMode': 'auto'}},
                    'roles': {'workhorse': [entry('opencode', 'gateway/glm-9', 'low', 'glm'),
                                            entry('codex', 'model-x1', 'low', 'openai')]}})
        self.assertEqual(self.resolve('workhorse')['candidates'][0]['runtimeMode'], 'full-access')
        self.caps.write_text(json.dumps(dict(CAPABILITIES, runtimeMode='auto')))
        first, second = self.resolve('workhorse')['candidates']
        self.assertEqual(first['runtimeMode'], 'auto')
        self.assertIn('switch this child to full-access', first['owner_action'])
        self.assertNotIn('owner_action', second)

    def test_required_mode_above_parent_is_skipped_not_lowered(self):
        self.write({'schema_version': 1, 'tiers': ['low'],
                    'providers': {'opencode': {'runtimeMode': 'full-access', 'requireRuntimeMode': True}},
                    'roles': {'workhorse': [entry('opencode', 'gateway/glm-9', 'low', 'glm'),
                                            entry('codex', 'model-x1', 'low', 'openai')]}})
        self.assertEqual([c['providerInstanceId'] for c in self.resolve('workhorse')['candidates']],
                         ['opencode', 'codex'])
        self.caps.write_text(json.dumps(dict(CAPABILITIES, runtimeMode='auto')))
        result = self.resolve('workhorse')
        self.assertEqual([c['providerInstanceId'] for c in result['candidates']], ['codex'])
        self.assertEqual(result['unavailable'][0]['reason'],
                         'runtime_mode_above_parent: needs full-access, parent runs auto')
        # Unlisted OpenCode providers get the same default as setup writes.
        self.write({'schema_version': 1, 'tiers': ['low'], 'providers': {},
                    'roles': {'workhorse': [entry('opencode', 'gateway/glm-9', 'low', 'glm')]}})
        result = self.resolve('workhorse', code=1)
        self.assertEqual(result['candidates'], [])
        self.assertTrue(result['unavailable'][0]['reason'].startswith('runtime_mode_above_parent'))
        # A non-boolean flag is a config error.
        self.write({'schema_version': 1, 'tiers': ['low'],
                    'providers': {'opencode': {'runtimeMode': 'full-access', 'requireRuntimeMode': 'yes'}},
                    'roles': {'workhorse': [entry('opencode', 'gateway/glm-9', 'low', 'glm')]}})
        self.assertIn('requireRuntimeMode must be true or false', self.resolve('workhorse', code=2).stderr)


if __name__ == '__main__':
    unittest.main()
