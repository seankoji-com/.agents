"""Planning panel regressions against an adopted, relocated immutable package."""
import unittest
from tests import test_planning_review as panel
from tests.test_plan_review_installed_matrix import relocate


class RelocatedPlanningPanel(panel.PlanningReviewTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.package, cls.manifest = relocate(cls.box, {'imps': (cls.package, cls.manifest)})['imps']

    def cli(self, command, data=None, **kw):
        kw['installed'] = True
        return super().cli(command, data, **kw)
