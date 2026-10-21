"""The focus-group planning contract through a relocated installed package."""
from pathlib import Path
import unittest

from tests import test_focus_group_install as installed
from tests import test_plan_review_focus_group as contract


def setUpModule():
    installed.setUpModule()


def tearDownModule():
    installed.tearDownModule()


class RelocatedFocusPlanningTest(contract.FocusPlanningContract, unittest.TestCase):
    def setUp(self):
        inst=installed.STATE['relocated']
        if not installed.STATE.get('adopted'):
            p=installed.catalog(inst['env'],inst['prefix'],inst['agents'],'adopt','--from-prefix',inst['original_prefix'])
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);installed.STATE['adopted']=True
        base=installed.STATE['base']/self._testMethodName;base.mkdir()
        self.swap=installed.Swap(inst,installed.audited(inst['env'],base),base)
        self.swap.__enter__();self.addCleanup(self.swap.__exit__,None,None,None)
        self.h=installed.InstalledHost(base,inst['package'])

    def tearDown(self):
        hits=[hit for row in installed.audit_rows(self.h.base) for hit in row['hits']]
        self.assertEqual(hits,[],'installed policy flow must not read source')
