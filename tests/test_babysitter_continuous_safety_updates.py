"""Branch updates and resolution receipts under the unchanged module deadline."""
from tests.module_partition import partition
from tests.test_babysitter_continuous_safety import UpdateAndResolutionTest


def load_tests(loader, tests, pattern):
    return partition(loader, UpdateAndResolutionTest, 0, count=1)
