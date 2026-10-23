"""Complementary lifecycle cases; all original scenarios and deadlines remain."""
from tests.module_partition import partition
from tests.test_focus_group_lifecycle_rounds import ReviewRoundTest


def load_tests(loader, tests, pattern):
    return partition(loader, ReviewRoundTest, 1)
