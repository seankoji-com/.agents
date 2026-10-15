"""Synthetic document author provenance and lineage checks."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.jobs.store import JobError
from shared.document_authors import (append_author, author_from_capabilities, authors_for_hash,
                                     has_current_task_waiver, has_current_stage_waiver,
                                     stage_waiver_binding, waiver_binding)
from shared.job_acceptance import AcceptanceError, independent_of_authors, _check_slots


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

    def test_handoff_and_repair_keep_every_source_author_for_cold_readers(self):
        caps_a = copy.deepcopy(self.caps)
        caps_b = copy.deepcopy(self.caps)
        caps_b.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol')
        caps_c = copy.deepcopy(self.caps)
        caps_c.update(inheritedProviderInstanceId='antigravity', inheritedModel='gemini-3.8-flash-high')
        records = append_author({}, b'discovery A', caps_a)
        records = append_author(records, b'spec A', caps_a)
        hashes = tuple(records)
        records = append_author(records, b'handoff rendered by B', caps_b, hashes)
        handoff_hash = __import__('hashlib').sha256(b'handoff rendered by B').hexdigest()
        authors = authors_for_hash(records, handoff_hash)
        self.assertEqual({row['lineage'] for row in authors}, {'anthropic', 'openai'})
        with self.assertRaisesRegex(AcceptanceError, 'differ from every document author'):
            independent_of_authors({'document_authors': authors},
                                   {'target': {'providerInstanceId': 'claudeAgent', 'model': 'claude-opus-5-5', 'lineage': 'anthropic'}})
        records = append_author(records, b'spec repaired by C', caps_c)
        new_hashes = (hashes[0], __import__('hashlib').sha256(b'spec repaired by C').hexdigest())
        records = append_author(records, b'handoff rerendered by B', caps_b, new_hashes)
        repaired = authors_for_hash(records, __import__('hashlib').sha256(b'handoff rerendered by B').hexdigest())
        self.assertEqual({row['lineage'] for row in repaired}, {'anthropic', 'openai', 'google'})
        c_reader = {'target': {'providerInstanceId': 'antigravity', 'model': 'gemini-3.8-flash-high', 'lineage': 'google'}}
        with self.assertRaisesRegex(AcceptanceError, 'differ from every document author'):
            independent_of_authors({'document_authors': repaired}, c_reader)
        unknown_records = append_author({}, b'unknown source rendered', caps_b, ('f' * 64,))
        unknown = authors_for_hash(unknown_records, __import__('hashlib').sha256(b'unknown source rendered').hexdigest())
        with self.assertRaisesRegex(AcceptanceError, 'author unrecorded'):
            independent_of_authors({'document_authors': unknown}, c_reader)

    def test_repaired_source_without_a_hash_record_keeps_rerendered_handoff_unknown(self):
        caps_a, caps_b = (copy.deepcopy(self.caps) for _ in range(2))
        caps_b.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol')
        records = append_author({}, b'discovery A', caps_a)
        old_spec_sha = __import__('hashlib').sha256(b'spec before repair').hexdigest()
        records = append_author(records, b'handoff B', caps_b, (next(iter(records)), old_spec_sha))
        repaired_spec = b'spec repaired by C'
        repaired_spec_sha = __import__('hashlib').sha256(repaired_spec).hexdigest()
        # C's repaired bytes have no record. Rendering B cannot infer their author.
        revised = append_author(records, b'rendered handoff after repair', caps_b,
                                (next(iter(records)), repaired_spec_sha))
        result_sha = __import__('hashlib').sha256(b'rendered handoff after repair').hexdigest()
        self.assertEqual(authors_for_hash(revised, result_sha), [{'unknown': True}])

    def test_author_independence_requires_known_canonical_different_lineage(self):
        task = {'document_authors': [{'lineage': 'anthropic'}]}
        independent_of_authors(task, {'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}})
        with self.assertRaises(AcceptanceError):
            independent_of_authors(task, {'target': {'providerInstanceId': 'claudeAgent', 'model': 'claude-opus-5-5', 'lineage': 'anthropic'}})
        with self.assertRaises(AcceptanceError):
            independent_of_authors({'document_authors': [{'unknown': True}]}, {'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}})
        with self.assertRaises(AcceptanceError):
            independent_of_authors({'document_authors': [{'lineage': 'sonnet'}]}, {'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}})

    def test_reviewer_lineage_is_derived_and_declared_label_must_agree(self):
        authors = {'document_authors': [{'lineage': 'google'}]}
        gemini = {'target': {'providerInstanceId': 'antigravity',
                             'model': 'gemini-3.8-flash-high', 'lineage': 'openai'}}
        with self.assertRaisesRegex(AcceptanceError, 'disagrees with provider and model'):
            independent_of_authors(authors, gemini)
        independent_of_authors(authors, {'target': {'providerInstanceId': 'codex',
                                                    'model': 'gpt-6.1-sol', 'lineage': 'openai'}})

    def test_recording_cannot_guess_between_legacy_predecessor_hashes(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            records = {'a' * 64: {'authors': [{'lineage': 'google'}]},
                       'b' * 64: {'authors': [{'lineage': 'anthropic'}]}}
            with self.assertRaisesRegex(JobError, 'cannot establish the previous author record'):
                append_author(records, b'edited bytes', self.caps, document_path=Path(td) / 'document.md')

    def test_import_follows_only_trusted_system_links_like_macos_var(self):
        from tempfile import TemporaryDirectory
        from unittest import mock
        from core.jobs.store import digest
        import shared.document_authors as authors_module
        with TemporaryDirectory() as td:
            real = Path(td) / 'private' / 'docs'
            real.mkdir(parents=True)
            document = real / 'elephant.md'
            document.write_bytes(b'# Doc\n')
            records = append_author({}, document.read_bytes(), self.caps, document_path=document)
            (real / 'document-authors.json').write_text(json.dumps(records))
            link = Path(td) / 'var'
            link.symlink_to(Path(td) / 'private')
            subject = {'path': str(link / 'docs' / 'elephant.md'), 'sha256': digest(b'# Doc\n')}
            self.assertEqual(authors_module.import_subject_authors(subject), [{'unknown': True}],
                             'a user-owned link stays outside the trust boundary')
            with mock.patch.object(authors_module, 'trusted_link', lambda p: Path(p) == link):
                self.assertEqual([row['lineage'] for row in authors_module.import_subject_authors(subject)],
                                 ['anthropic'])

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
                                 ('independent_of_author', False),
                                 ('requirements', ['R-OTHER']), ('role', 'worker'),
                                 ('dependency_key', 'other'), ('review_required', True),
                                 ('review_task_ids', ['other-review']),
                                 ('context_policy', 'document-only'),
                                 ('write_scope', {'mode': 'worker-evidence'}), ('max_followups', 2)):
                changed = dict(task, **{field: value})
                self.assertFalse(has_current_task_waiver(job, changed), field)

    def test_review_lineage_waiver_binds_the_reviewers_target(self):
        from core.jobs.store import digest
        with __import__('tempfile').TemporaryDirectory() as td:
            source = Path(td) / 'owner.txt'; source.write_text('owner approved reviewer lineage waiver')
            subject = {'task_id': 'subject', 'stage_id': 'read', 'logical_slot_id': 'factual',
                       'worker_id': 'worker', 'target': {'providerInstanceId': 'codex', 'model': 'm1', 'lineage': 'openai'},
                       'independent_of_author': True, 'document': {'path': '/tmp/document', 'sha256': 'a' * 64},
                       'document_authors': [{'lineage': 'openai'}]}
            reviewer = {'target': {'providerInstanceId': 'claudeAgent', 'model': 'm2', 'lineage': 'anthropic'}}
            decision = {'scope': 'lineage-waiver:task:subject', 'requirement_ids': [],
                        'binding': waiver_binding(subject, reviewer), 'source': str(source),
                        'source_sha256': digest(source.read_bytes()), 'quote': 'owner approved reviewer lineage waiver'}
            job = {'decisions': [decision], 'policy': {'max_artifact_bytes': 10000}}
            self.assertTrue(has_current_task_waiver(job, subject, reviewer))
            changed_reviewer = {'target': {'providerInstanceId': 'claudeAgent', 'model': 'm3', 'lineage': 'anthropic'}}
            self.assertFalse(has_current_task_waiver(job, subject, changed_reviewer))


class MarkerAcceptanceTests(unittest.TestCase):
    def test_marked_review_and_subject_require_verified_identity(self):
        stage = {'id': 'read', 'execution_mode': 'direct'}
        for role, extra in (('review', {}), ('worker', {'review_required': True}),
                            ('worker', {'independent_of_author': True})):
            task = {'task_id': 'slot', 'stage_id': 'read', 'request_id': 'req', 'role': role,
                    'handles': [{'request_id': 'req', 'observed_identity': {'status': 'unreported'}}], **extra}
            job = {'policy': {'identity': 'observed'}, 'tasks': [task], 'blockers': []}
            with self.subTest(role=role, extra=extra), self.assertRaisesRegex(
                    AcceptanceError, 'unreported or mismatched'):
                _check_slots(None, job, stage, require_reviews=False)
            task['handles'][0]['observed_identity']['status'] = 'mismatched'
            with self.assertRaisesRegex(AcceptanceError, 'unreported or mismatched'):
                _check_slots(None, job, stage, require_reviews=False)

    def test_legacy_direct_stage_keeps_target_only_acceptance_path(self):
        job = {'policy': {}, 'tasks': [], 'blockers': []}
        _check_slots(None, job, {'id': 'legacy', 'execution_mode': 'direct'}, require_reviews=False)

    def test_stage_waiver_is_bound_to_latest_direct_identity_and_contract(self):
        from core.jobs.store import digest
        with __import__('tempfile').TemporaryDirectory() as td:
            source = Path(td) / 'owner.txt'
            source.write_text('owner approved direct stage lineage waiver')
            stage = {'id': 'fact', 'execution_mode': 'direct', 'independent_of_author': True,
                     'document_authors': [{'lineage': 'anthropic'}],
                     'validator_contract': {'document_sha256': 'a' * 64},
                     'direct_execution_history': [{'identity': {'providerInstanceId': 'codex',
                         'model': 'gpt-6.1-sol', 'lineage': 'openai'}}]}
            decision = {'scope': 'lineage-waiver:stage:fact', 'requirement_ids': [],
                        'binding': stage_waiver_binding(stage, stage['document_authors'], 'a' * 64,
                                                        stage['direct_execution_history'][-1]['identity']),
                        'source': str(source), 'source_sha256': digest(source.read_bytes()),
                        'quote': 'owner approved direct stage lineage waiver'}
            job = {'decisions': [decision], 'policy': {'max_artifact_bytes': 10000}}
            self.assertTrue(has_current_stage_waiver(job, stage))
            job.update(tasks=[], blockers=[])
            _check_slots(None, job, stage, require_reviews=False)
            resumed = copy.deepcopy(stage)
            resumed['direct_execution_history'].append({'identity': {'providerInstanceId': 'claudeAgent',
                'model': 'claude-opus-5-5', 'lineage': 'anthropic'}})
            self.assertFalse(has_current_stage_waiver(job, resumed))
            with self.assertRaisesRegex(AcceptanceError, 'latest direct-execution identity'):
                _check_slots(None, job, resumed, require_reviews=False)

    def test_author_policy_gates_flagless_direct_factual_stage_and_unknown_authors(self):
        stage = {'id': 'factual', 'execution_mode': 'direct', 'validator_contract': {'mode': 'factual'},
                 'document_authors': [{'lineage': 'google'}]}
        job = {'policy': {'author_independence': True}, 'tasks': [], 'blockers': []}
        with self.assertRaisesRegex(AcceptanceError, 'current stage-scoped lineage waiver'):
            _check_slots(None, job, stage, require_reviews=False)
        stage['document_authors'] = [{'unknown': True}]
        with self.assertRaisesRegex(AcceptanceError, 'author unrecorded'):
            _check_slots(None, job, stage, require_reviews=False)


if __name__ == '__main__':
    unittest.main()
