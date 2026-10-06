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


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_validation(self):
        for args in [(0, 1), (1, 0), (-1, 1), (1, -2)]:
            with self.assertRaises(ValueError):
                TokenBucket(*args)

    def test_cap_on_refill(self):
        b = TokenBucket(3, 10.0)
        self.assertEqual(b.available(100.0), 3.0)
        self.assertTrue(b.allow(100.0, cost=3))
        self.assertFalse(b.allow(100.0))

    def test_exact_boundary(self):
        b = TokenBucket(2, 1.0)
        self.assertTrue(b.allow(0, cost=2))
        self.assertFalse(b.allow(0.5))
        self.assertTrue(b.allow(1.5))
        self.assertFalse(b.allow(1.5))

    def test_cost(self):
        b = TokenBucket(5, 1.0)
        self.assertTrue(b.allow(0, cost=5))
        self.assertFalse(b.allow(0, cost=6))
        self.assertFalse(b.allow(3.0, cost=4))
        self.assertTrue(b.allow(4.0, cost=4))
        self.assertAlmostEqual(b.available(4.0), 0.0)

    def test_oversize_cost_never_allowed(self):
        b = TokenBucket(2, 100.0)
        self.assertFalse(b.allow(0, cost=3))
        self.assertFalse(b.allow(1000, cost=3))

    def test_time_backwards(self):
        b = TokenBucket(2, 1.0, now=10.0)
        with self.assertRaises(ValueError):
            b.allow(9.0)
        self.assertTrue(b.allow(10.0))

    def test_wait_time(self):
        b = TokenBucket(4, 2.0)
        self.assertEqual(b.wait_time(0), 0.0)
        b.allow(0, cost=4)
        self.assertAlmostEqual(b.wait_time(0), 0.5)
        self.assertAlmostEqual(b.wait_time(0, cost=3), 1.5)
        self.assertAlmostEqual(b.wait_time(0.25, cost=1), 0.25)
        with self.assertRaises(ValueError):
            b.wait_time(0, cost=5)

    def test_start_time(self):
        b = TokenBucket(1, 1.0, now=5.0)
        self.assertTrue(b.allow(5.0))
        self.assertFalse(b.allow(5.5))
        self.assertTrue(b.allow(6.0))
