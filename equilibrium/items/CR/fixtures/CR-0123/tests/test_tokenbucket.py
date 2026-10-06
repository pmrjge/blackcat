import unittest

from tokenbucket import TokenBucket


class Basic(unittest.TestCase):
    def test_drain(self):
        b = TokenBucket(2, 1.0)
        self.assertTrue(b.allow(0))
        self.assertTrue(b.allow(0))
        self.assertFalse(b.allow(0))

    def test_refill(self):
        b = TokenBucket(2, 1.0)
        b.allow(0)
        b.allow(0)
        self.assertTrue(b.allow(1.0))
