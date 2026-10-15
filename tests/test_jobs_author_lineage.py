"""Synthetic document author provenance and lineage checks."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.jobs.store import JobError
from shared.document_authors import append_author, author_from_capabilities, authors_for_hash, has_current_task_waiver, waiver_binding
from shared.job_acceptance import AcceptanceError, independent_of_authors


class DocumentAuthorTests(unittest.TestCase):
    def setUp(self):
        self.caps = json.loads((ROOT / 'tests/fixtures/t3/capabilities.json').read_text())

    def test_author_requires_inherited_fields_and_catalog_correlation(self):
        self.assertEqual(author_from_capabilities(self.caps)['lineage'], 'anthropic')
        for key in ('inheritedProviderInstanceId', 'inheritedModel', 'parentThreadId'):
            changed = copy.deepcopy(self.caps)
            changed.pop(key)
            with self.subTest(key=key), self.assertRaises(JobError):
                author_from_capabilities(changed)
        changed = copy.deepcopy(self.caps)
        changed['inheritedModel'] = 'not-in-catalog'
        with self.assertRaises(JobError):
            author_from_capabilities(changed)

    def test_hash_records_union_renderer_and_sources_and_unknown_is_sticky(self):
        records = {}
        records = append_author(records, b'discovery', self.caps)
        caps_b = copy.deepcopy(self.caps)
        caps_b.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol')
        records = append_author(records, b'spec', caps_b)
        handoff = append_author(records, b'handoff', caps_b,
                                (next(iter(records)), list(records)[1]))
        self.assertEqual({a['lineage'] for a in authors_for_hash(handoff, __import__('hashlib').sha256(b'handoff').hexdigest())}, {'anthropic', 'openai'})
        unknown = append_author({}, b'unknown-source', caps_b, ('f' * 64,))
        self.assertEqual(authors_for_hash(unknown, __import__('hashlib').sha256(b'unknown-source').hexdigest()), [{'unknown': True}])

    def test_author_independence_requires_known_canonical_different_lineage(self):
        task = {'document_authors': [{'lineage': 'anthropic'}]}
        independent_of_authors(task, {'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}})
        with self.assertRaises(AcceptanceError):
            independent_of_authors(task, {'target': {'providerInstanceId': 'claudeAgent', 'model': 'claude-opus-5-5', 'lineage': 'anthropic'}})
        with self.assertRaises(AcceptanceError):
            independent_of_authors({'document_authors': [{'unknown': True}]}, {'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}})
        with self.assertRaises(AcceptanceError):
            independent_of_authors({'document_authors': [{'lineage': 'sonnet'}]}, {'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}})

    def test_task_waiver_rebinds_to_target_authors_contract_and_document(self):
        from core.jobs.store import digest
        with __import__('tempfile').TemporaryDirectory() as td:
            from pathlib import Path
            source = Path(td) / 'owner.txt'
            source.write_text('owner approved lineage waiver')
            task = {'task_id': 'review-1', 'stage_id': 'read', 'logical_slot_id': 'cold',
                    'worker_id': 'cold-reader', 'target': {'providerInstanceId': 'claudeAgent', 'model': 'm', 'lineage': 'anthropic'},
                    'independent_of_author': True, 'document': {'path': '/tmp/document', 'sha256': 'a' * 64},
                    'document_authors': [{'unknown': True}]}
            decision = {'scope': 'lineage-waiver:task:review-1', 'requirement_ids': [],
                        'binding': waiver_binding(task), 'source': str(source),
                        'source_sha256': digest(source.read_bytes()), 'quote': 'owner approved lineage waiver'}
            job = {'decisions': [decision], 'policy': {'max_artifact_bytes': 10000}}
            self.assertTrue(has_current_task_waiver(job, task))
            for field, value in (('target', {'providerInstanceId': 'codex', 'model': 'x', 'lineage': 'openai'}),
                                 ('document_authors', [{'lineage': 'openai'}]),
                                 ('document', {'path': '/tmp/document', 'sha256': 'b' * 64}),
                                 ('independent_of_author', False)):
                changed = dict(task, **{field: value})
                self.assertFalse(has_current_task_waiver(job, changed), field)


if __name__ == '__main__':
    unittest.main()
