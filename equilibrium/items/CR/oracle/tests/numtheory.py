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


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_gcd_lcm(self):
        self.assertEqual(gcd(0, 0), 0)
        self.assertEqual(gcd(0, 5), 5)
        self.assertEqual(gcd(-12, 18), 6)
        self.assertEqual(gcd(17, 5), 1)
        self.assertEqual(gcd(100, 75), 25)
        self.assertEqual(lcm(4, 6), 12)
        self.assertEqual(lcm(0, 5), 0)
        self.assertEqual(lcm(5, 0), 0)
        self.assertEqual(lcm(-4, 6), 12)
        self.assertEqual(lcm(7, 13), 91)
        self.assertEqual(lcm(21, 6), 42)

    def test_is_prime(self):
        primes = [2, 3, 5, 7, 11, 13, 97, 101, 7919]
        for p in primes:
            self.assertTrue(is_prime(p), p)
        for c in [-7, 0, 1, 4, 9, 15, 25, 49, 91, 121, 169, 7917]:
            self.assertFalse(is_prime(c), c)

    def test_sieve(self):
        self.assertEqual(primes_upto(1), [])
        self.assertEqual(primes_upto(2), [2])
        self.assertEqual(primes_upto(10), [2, 3, 5, 7])
        self.assertEqual(primes_upto(30), [2, 3, 5, 7, 11, 13, 17, 19, 23, 29])
        self.assertEqual(primes_upto(25), [2, 3, 5, 7, 11, 13, 17, 19, 23])
        self.assertEqual(len(primes_upto(1000)), 168)
        self.assertEqual(primes_upto(49)[-1], 47)
        self.assertEqual(primes_upto(121)[-1], 113)

    def test_isqrt(self):
        for n in [0, 1, 2, 3, 4, 8, 9, 10, 15, 16, 17, 99, 100, 101, 10 ** 12, 10 ** 12 - 1]:
            r = isqrt(n)
            self.assertTrue(r * r <= n < (r + 1) * (r + 1), n)
        self.assertEqual(isqrt(0), 0)
        self.assertEqual(isqrt(1), 1)
        self.assertEqual(isqrt(24), 4)
        self.assertEqual(isqrt(25), 5)
        with self.assertRaises(ValueError):
            isqrt(-1)

    def test_factorize(self):
        self.assertEqual(factorize(2), [2])
        self.assertEqual(factorize(12), [2, 2, 3])
        self.assertEqual(factorize(97), [97])
        self.assertEqual(factorize(360), [2, 2, 2, 3, 3, 5])
        self.assertEqual(factorize(49), [7, 7])
        self.assertEqual(factorize(2 * 3 * 5 * 7 * 11), [2, 3, 5, 7, 11])
        for bad in (1, 0, -4):
            with self.assertRaises(ValueError):
                factorize(bad)

    def test_binom(self):
        self.assertEqual(binom(5, 2), 10)
        self.assertEqual(binom(5, 0), 1)
        self.assertEqual(binom(5, 5), 1)
        self.assertEqual(binom(5, 6), 0)
        self.assertEqual(binom(0, 0), 1)
        self.assertEqual(binom(10, 3), 120)
        self.assertEqual(binom(10, 7), 120)
        self.assertEqual(binom(52, 5), 2598960)
        self.assertEqual(binom(6, 3), 20)
        with self.assertRaises(ValueError):
            binom(-1, 0)
        with self.assertRaises(ValueError):
            binom(3, -1)

    def test_digit_sum(self):
        self.assertEqual(digit_sum(0), 0)
        self.assertEqual(digit_sum(12345), 15)
        self.assertEqual(digit_sum(-909), 18)
        self.assertEqual(digit_sum(255, 16), 30)
        self.assertEqual(digit_sum(5, 2), 2)
        self.assertEqual(digit_sum(8, 2), 1)
        with self.assertRaises(ValueError):
            digit_sum(5, 1)
