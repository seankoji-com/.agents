"""Installed contract import integrity under the unchanged module deadline."""
from tests.module_partition import partition
from tests.test_babysitter_continuous_safety import InstalledImportIntegrityTest


def load_tests(loader, tests, pattern):
    return partition(loader, InstalledImportIntegrityTest, 0, count=1)
