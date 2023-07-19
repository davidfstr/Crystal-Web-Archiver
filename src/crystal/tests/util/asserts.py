from unittest import TestCase


class _DummyTestCase(TestCase):
    maxDiff = None

# All of these assert methods provide a better error message upon failure
# than a bare assert statement
assertEqual = _DummyTestCase().assertEqual
assertIn = _DummyTestCase().assertIn
assertNotIn = _DummyTestCase().assertNotIn
