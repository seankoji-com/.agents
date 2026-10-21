"""Relocated installed public acceptance, including the original adversarial cases."""
import unittest
from tests import test_plan_review_ape as ape
from tests import test_plan_review_imps as imps
from tests import test_plan_review_adopters as adopters
from tests import test_thinking_plan_review as thinking
from tests.test_plan_review_installed_matrix import relocate


class RelocatedApe(ape.ApePlanningTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.package, cls.manifest = relocate(cls.box, {'ape': (cls.package, cls.manifest)})['ape']
