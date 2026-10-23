"""Partition unchanged integration cases under the existing module deadline."""
import unittest


def partition(loader, case, index, count=2):
    if not 0 <= index < count:
        raise ValueError('invalid unittest partition')
    names = loader.getTestCaseNames(case)
    return unittest.TestSuite(case(name) for name in names[index::count])
