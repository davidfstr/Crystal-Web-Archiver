from crystal.tests.util.screenshots import screenshot_if_raises_deco
from unittest import TestCase


class _DummyTestCase(TestCase):
    maxDiff = None

# Advantages of these assert methods over a bare assert statement:
# 1. A better error message is provided, including the operands that were compared
# 2. A screenshot will be taken automatically upon failure
assertEqual = screenshot_if_raises_deco(_DummyTestCase().assertEqual)
assertNotEqual = screenshot_if_raises_deco(_DummyTestCase().assertEqual)
assertIn = screenshot_if_raises_deco(_DummyTestCase().assertIn)
assertNotIn = screenshot_if_raises_deco(_DummyTestCase().assertNotIn)
assertRaises = screenshot_if_raises_deco(_DummyTestCase().assertRaises)
