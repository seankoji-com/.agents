"""Complementary identity-report scenarios under the unchanged module deadline."""
from tests.module_partition import partition
from tests.test_focus_group_report_identity import IdentityProjectionTest, setUpModule, tearDownModule


def load_tests(loader, tests, pattern):
    return partition(loader, IdentityProjectionTest, 1)
