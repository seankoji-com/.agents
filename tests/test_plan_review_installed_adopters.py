"""Relocated installed public acceptance, including the original adversarial cases."""
import unittest
from tests import test_plan_review_ape as ape
from tests import test_plan_review_imps as imps
from tests import test_plan_review_adopters as adopters
from tests import test_thinking_plan_review as thinking
from tests.test_plan_review_installed_matrix import relocate


class RelocatedAdopters(adopters.AdoptersTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.packages = relocate(cls.box, cls.packages)
