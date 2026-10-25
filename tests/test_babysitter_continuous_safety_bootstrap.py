"""Bootstrap trust and cancelled coverage under the unchanged module deadline."""
import unittest

from tests.module_partition import partition
from tests.test_babysitter_continuous_safety import BootstrapIdentityTest, CancelledCoverageTest


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(partition(loader, case, 0, count=1) for case in
                              (BootstrapIdentityTest, CancelledCoverageTest))
