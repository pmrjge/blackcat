import unittest

from numtheory import gcd, lcm, is_prime, primes_upto, isqrt, factorize, binom, digit_sum


class Basic(unittest.TestCase):
    def test_gcd(self):
        self.assertEqual(gcd(12, 18), 6)

    def test_prime(self):
        self.assertTrue(is_prime(13))
        self.assertFalse(is_prime(15))

    def test_isqrt(self):
        self.assertEqual(isqrt(17), 4)
