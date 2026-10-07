import unittest

from windows import chunk, windows, moving_average, sliding_max, flatten_once, pairwise_diff


class Basic(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_windows(self):
        self.assertEqual(windows([1, 2, 3], 2), [[1, 2], [2, 3]])

    def test_avg(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_chunk_edges(self):
        self.assertEqual(chunk([], 3), [])
        self.assertEqual(chunk([1, 2, 3], 3), [[1, 2, 3]])
        self.assertEqual(chunk([1, 2, 3], 5), [[1, 2, 3]])
        self.assertEqual(chunk("abcd", 1), [["a"], ["b"], ["c"], ["d"]])
        self.assertEqual(chunk((1, 2, 3, 4), 2), [[1, 2], [3, 4]])
        with self.assertRaises(ValueError):
            chunk([1], 0)

    def test_windows_edges(self):
        self.assertEqual(windows([1, 2, 3, 4, 5], 2, step=2), [[1, 2], [3, 4]])
        self.assertEqual(windows([1, 2, 3, 4, 5], 3, step=2), [[1, 2, 3], [3, 4, 5]])
        self.assertEqual(windows([1, 2, 3], 3), [[1, 2, 3]])
        self.assertEqual(windows([1, 2], 3), [])
        self.assertEqual(windows([], 1), [])
        self.assertEqual(windows([1, 2, 3, 4], 1, step=3), [[1], [4]])
        with self.assertRaises(ValueError):
            windows([1], 0)
        with self.assertRaises(ValueError):
            windows([1], 1, step=0)

    def test_moving_average(self):
        self.assertEqual(moving_average([2, 4, 6], 3), [4.0])
        self.assertEqual(moving_average([1, 2], 3), [])
        self.assertEqual(moving_average([5, 5, 5, 5], 1), [5.0, 5.0, 5.0, 5.0])
        self.assertEqual(moving_average([1, 3, 5, 7, 9], 3), [3.0, 5.0, 7.0])
        self.assertEqual(moving_average([], 2), [])
        with self.assertRaises(ValueError):
            moving_average([1], 0)

    def test_sliding_max(self):
        self.assertEqual(sliding_max([1, 3, -1, -3, 5, 3, 6, 7], 3), [3, 3, 5, 5, 6, 7])
        self.assertEqual(sliding_max([4, 2, 12, 3], 1), [4, 2, 12, 3])
        self.assertEqual(sliding_max([9, 8, 7, 6], 2), [9, 8, 7])
        self.assertEqual(sliding_max([1, 2, 3, 4], 4), [4])
        self.assertEqual(sliding_max([2, 2, 2, 2], 2), [2, 2, 2])
        self.assertEqual(sliding_max([1, 2], 3), [])
        self.assertEqual(sliding_max([5, 1, 1, 1, 4], 3), [5, 1, 4])
        with self.assertRaises(ValueError):
            sliding_max([1], 0)

    def test_flatten_pairwise(self):
        self.assertEqual(flatten_once([[1], [], [2, 3], [[4]]]), [1, 2, 3, [4]])
        self.assertEqual(flatten_once([]), [])
        self.assertEqual(pairwise_diff([1, 4, 9, 16]), [3, 5, 7])
        self.assertEqual(pairwise_diff([5]), [])
        self.assertEqual(pairwise_diff([]), [])
        self.assertEqual(pairwise_diff([10, 7]), [-3])
