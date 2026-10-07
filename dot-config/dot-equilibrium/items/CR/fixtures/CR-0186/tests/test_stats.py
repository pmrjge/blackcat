import unittest

from stats import mean, median, variance, percentile, mode, zscores, clamp_outliers


class Basic(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(mean([1, 2, 3, 4]), 2.5)

    def test_median(self):
        self.assertEqual(median([3, 1, 2]), 2)

    def test_mode(self):
        self.assertEqual(mode([1, 2, 2, 3]), 2)
