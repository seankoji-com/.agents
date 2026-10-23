"""Retain all 21 new-topic and three remaining legacy rounds within the module deadline."""
from tests.elephant_goldfish_job_fixtures import ElephantDocumentJobFixture


class ElephantRoundBudgetTests(ElephantDocumentJobFixture):
    def test_new_documents_get_the_default_rounds_and_legacy_loops_keep_their_remaining_five(self):
        # New topic: the default policy snapshot (initial read plus max_repair_cycles repairs).
        self.assertEqual(self.rounds('rounds-new'), 21)
        self.assertEqual(self.job_state('rounds-new')['policy']['max_repair_cycles'], 20)
        # Legacy loop under the five-round instruction with two rounds already performed.
        self.assertEqual(self.rounds('rounds-legacy', {'max_repair_cycles': 5 - 2 - 1,
                                                        'max_artifact_bytes': 16 * 1024 * 1024}), 3)
