"""Relocated installed public acceptance, including the original adversarial cases."""
import unittest
from tests import test_plan_review_ape as ape
from tests import test_plan_review_imps as imps
from tests import test_plan_review_adopters as adopters
from tests import test_thinking_plan_review as thinking
from tests.test_plan_review_installed_matrix import relocate


class SourceThinking(thinking.ThinkingPlanReviewCommands, unittest.TestCase):
    installed = False


class RelocatedThinking(thinking.ThinkingPlanReviewCommands, unittest.TestCase):
    installed = True

    def setUp(self):
        super().setUp()
        f = self.fixture
        f.package, f.manifest = relocate(f.box, {'elephant-goldfish': (f.package, f.manifest)})['elephant-goldfish']
        self.scripts = f.package / 'scripts'
