"""Queue, landing gates and merge lifecycle under the unchanged module deadline."""
import unittest

from tests.module_partition import partition
from tests.test_babysitter_continuous_safety import (
    LiveMergeHeadChangeTest, MergeCompletionSafetyTest, MergeGateContractTest,
    ReservationSafetyTest, UnclockedQueueSafetyTest,
)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(partition(loader, case, 0, count=1) for case in
                              (UnclockedQueueSafetyTest, MergeGateContractTest,
                               ReservationSafetyTest, MergeCompletionSafetyTest,
                               LiveMergeHeadChangeTest))
