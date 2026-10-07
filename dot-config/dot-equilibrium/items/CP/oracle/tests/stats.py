import unittest

from stats import mean, median, variance, percentile, mode, zscores, clamp_outliers


class Basic(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(mean([1, 2, 3, 4]), 2.5)

    def test_median(self):
        self.assertEqual(median([3, 1, 2]), 2)

    def test_mode(self):
        self.assertEqual(mode([1, 2, 2, 3]), 2)


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_empty(self):
        for fn in (mean, median, mode):
            with self.assertRaises(ValueError):
                fn([])
        with self.assertRaises(ValueError):
            variance([])
        with self.assertRaises(ValueError):
            percentile([], 50)

    def test_median_even(self):
        self.assertEqual(median([4, 1, 3, 2]), 2.5)
        self.assertEqual(median([1, 2]), 1.5)
        self.assertEqual(median([5]), 5)
        self.assertEqual(median([9, 1, 5, 3, 7]), 5)
        self.assertEqual(median([1, 100, 2, 3, 4, 5]), 3.5)

    def test_variance(self):
        self.assertAlmostEqual(variance([1, 2, 3, 4]), 5 / 3)
        self.assertAlmostEqual(variance([1, 2, 3, 4], sample=False), 1.25)
        self.assertEqual(variance([5, 5, 5]), 0)
        self.assertEqual(variance([7], sample=False), 0)
        with self.assertRaises(ValueError):
            variance([7])
        self.assertAlmostEqual(variance([2, 4, 4, 4, 5, 5, 7, 9], sample=False), 4.0)

    def test_percentile(self):
        data = [15, 20, 35, 40, 50]
        self.assertEqual(percentile(data, 30), 20)
        self.assertEqual(percentile(data, 40), 20)
        self.assertEqual(percentile(data, 50), 35)
        self.assertEqual(percentile(data, 100), 50)
        self.assertEqual(percentile(data, 1), 15)
        self.assertEqual(percentile(data, 20), 15)
        self.assertEqual(percentile(data, 21), 20)
        self.assertEqual(percentile([3, 1, 2], 100), 3)
        self.assertEqual(percentile(list(range(1, 101)), 95), 95)
        self.assertEqual(percentile(list(range(1, 11)), 90), 9)
        for bad in (0, -5, 101):
            with self.assertRaises(ValueError):
                percentile(data, bad)

    def test_mode_ties(self):
        self.assertEqual(mode([3, 3, 1, 1, 2]), 1)
        self.assertEqual(mode([5]), 5)
        self.assertEqual(mode([2, 9, 9, 2, 7]), 2)
        self.assertEqual(mode(["b", "a", "b", "a"]), "a")

    def test_zscores(self):
        z = zscores([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertAlmostEqual(z[0], -1.5)
        self.assertAlmostEqual(z[-1], 2.0)
        self.assertEqual(zscores([3, 3, 3]), [0.0, 0.0, 0.0])
        self.assertAlmostEqual(sum(z), 0.0)

    def test_clamp(self):
        data = [10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
        out = clamp_outliers(data, k=2.0)
        self.assertEqual(out[:-1], [10] * 9)
        self.assertAlmostEqual(out[-1], 19 + 2 * 27.0)
        self.assertEqual(clamp_outliers([1, 2, 3], k=10), [1, 2, 3])
        self.assertEqual(clamp_outliers([4, 4], k=1), [4, 4])
