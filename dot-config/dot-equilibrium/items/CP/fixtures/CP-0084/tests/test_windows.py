import unittest

from windows import chunk, windows, moving_average, sliding_max, flatten_once, pairwise_diff


class Basic(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_windows(self):
        self.assertEqual(windows([1, 2, 3], 2), [[1, 2], [2, 3]])

    def test_avg(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
