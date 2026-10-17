"""Issue #57: code-review lineage is derived from provider and model; synthetic data only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from core.jobs import JobError
from shared.job_acceptance import AcceptanceError, _check_slots, independent_lineage, independent_of_authors, target_lineage
from shared.job_coordinator import prepare_task
from tests import test_issue28_pass10 as pass10

ROOT = Path(__file__).resolve().parents[1]
WORKER = {'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}}
GPT_OSS = {'providerInstanceId': 'opencode', 'model': 'opencode/litellm/gpt-oss-120b'}
CLAUDE = {'providerInstanceId': 'opencode', 'model': 'opencode/anthropic/claude-opus-5-5', 'lineage': 'anthropic'}


def catalog(*rows):
    caps = json.loads((ROOT / 'tests/fixtures/t3/capabilities.json').read_text())
    caps['providers'] += [{'providerInstanceId': p, 'driverKind': d, 'models': [{'id': m}]} for p, d, m in rows]
    return caps


class CodeReviewLineageTests(unittest.TestCase):
    def test_meta_label_on_gpt_oss_reviewer_is_refused_for_openai_worker(self):
        with self.assertRaisesRegex(AcceptanceError, 'disagrees with provider and model'):
            independent_lineage(WORKER, {'target': dict(GPT_OSS, lineage='meta')})
        with self.assertRaisesRegex(AcceptanceError, 'different model target and a known different lineage'):
            independent_lineage(WORKER, {'target': dict(GPT_OSS, lineage='openai')})

    def test_correctly_labelled_cross_lineage_reviewer_passes(self):
        independent_lineage(WORKER, {'target': CLAUDE})
        independent_lineage(WORKER, {'target': {'providerInstanceId': 'claudeAgent', 'model': 'claude-opus-5-5',
                                                'lineage': 'anthropic'}})

    def test_mislabelled_worker_and_unresolvable_lineage_fail_closed(self):
        with self.assertRaisesRegex(AcceptanceError, 'disagrees with provider and model'):
            independent_lineage({'target': dict(WORKER['target'], lineage='meta')}, {'target': CLAUDE})
        for model, label in (('opencode/big-pickle', 'big'), ('llama-4', 'llama'), ('9000', 'unknown')):
            with self.subTest(model=model), self.assertRaisesRegex(AcceptanceError, 'unknown or non-canonical'):
                independent_lineage(WORKER, {'target': {'providerInstanceId': 'opencode', 'model': model, 'lineage': label}})
        with self.assertRaisesRegex(AcceptanceError, 'lineage is unknown'):
            independent_lineage(WORKER, {'target': GPT_OSS})

    def test_document_and_code_reviews_share_the_derivation(self):
        authors = {'document_authors': [{'lineage': 'openai'}]}
        mislabelled = {'target': dict(GPT_OSS, lineage='meta')}
        for check in (lambda: independent_lineage(WORKER, mislabelled), lambda: independent_of_authors(authors, mislabelled)):
            with self.assertRaisesRegex(AcceptanceError, 'disagrees with provider and model'):
                check()
        independent_of_authors(authors, {'target': CLAUDE})


class CatalogDriverKindTests(unittest.TestCase):
    def test_no_catalog_keeps_instance_id_as_driver(self):
        self.assertEqual(target_lineage({'providerInstanceId': 'claudeAgent', 'model': 'opus'}), 'anthropic')
        self.assertEqual(target_lineage({'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol'}), 'openai')
        self.assertEqual(target_lineage(GPT_OSS), 'openai')
        with self.assertRaisesRegex(AcceptanceError, 'unknown or non-canonical'):
            target_lineage({'providerInstanceId': 'work-claude', 'model': 'opus'})

    def test_custom_instance_for_single_lineage_driver_resolves_through_catalog(self):
        caps = catalog(('work-claude', 'claudeAgent', 'opus'), ('gateway', 'opencode', 'gpt-oss-120b'))
        self.assertEqual(target_lineage({'providerInstanceId': 'work-claude', 'model': 'opus',
                                         'lineage': 'anthropic'}, caps), 'anthropic')
        self.assertEqual(target_lineage({'providerInstanceId': 'gateway', 'model': 'gpt-oss-120b'}, caps), 'openai')
        with self.assertRaisesRegex(AcceptanceError, 'disagrees with provider and model'):
            target_lineage({'providerInstanceId': 'work-claude', 'model': 'opus', 'lineage': 'openai'}, caps)

    def test_target_absent_from_catalog_is_unknown(self):
        caps = catalog(('work-claude', 'claudeAgent', 'opus'))
        for target in ({'providerInstanceId': 'missing', 'model': 'opus'},
                       {'providerInstanceId': 'work-claude', 'model': 'sonnet'}):
            with self.subTest(target=target), self.assertRaisesRegex(AcceptanceError, 'absent from the capabilities catalog'):
                target_lineage(target, caps)
        broken = copy.deepcopy(caps)
        broken['providers'][-1].pop('driverKind')
        with self.assertRaisesRegex(AcceptanceError, 'absent from the capabilities catalog'):
            target_lineage({'providerInstanceId': 'work-claude', 'model': 'opus'}, broken)


class ReviewPreparationTests(pass10.Pass10Fixture):
    def store(self, root, reviewer):
        return pass10.Pass10JobsTests.review_store(self, root, reviewer)

    def test_prepare_and_acceptance_refuse_meta_labelled_gpt_oss_reviewer(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, dict(GPT_OSS, lineage='meta'))
            before = store.file.read_bytes()
            with self.assertRaisesRegex(JobError, 'disagrees with provider and model'):
                prepare_task(store, self.caller, 't1', lambda *_: True, lambda *_: True)
            self.assertEqual(store.file.read_bytes(), before)
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, pass10.REVIEWER)
            pass10.Pass10JobsTests.review(self, store)
            state = store.load()
            _check_slots(store, state, state['stages'][0])
            state['tasks'][1]['handles'][0]['target'] = dict(pass10.REVIEWER, lineage='meta')
            with self.assertRaisesRegex(AcceptanceError, 'disagrees with provider and model'):
                _check_slots(store, state, state['stages'][0])


if __name__ == '__main__':
    unittest.main()
