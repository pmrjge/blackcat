import unittest

from intervals import normalize, overlaps, merge, total_length, gaps, contains_point


class Basic(unittest.TestCase):
    def test_merge_simple(self):
        self.assertEqual(merge([(1, 3), (2, 6), (8, 10)]), [(1, 6), (8, 10)])

    def test_total(self):
        self.assertEqual(total_length([(0, 2), (5, 6)]), 3)

    def test_normalize_error(self):
        with self.assertRaises(ValueError):
            normalize((4, 1))


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_touching_merge(self):
        self.assertEqual(merge([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(merge([(3, 5), (1, 3)]), [(1, 5)])

    def test_gap_not_merged(self):
        self.assertEqual(merge([(1, 3), (4, 5)]), [(1, 3), (4, 5)])

    def test_contained(self):
        self.assertEqual(merge([(0, 10), (2, 3)]), [(0, 10)])
        self.assertEqual(merge([(0, 10), (2, 12), (11, 13)]), [(0, 13)])

    def test_empty_input(self):
        self.assertEqual(merge([]), [])
        self.assertEqual(total_length([]), 0)

    def test_normalize(self):
        self.assertEqual(normalize((2, 5)), (2, 5))
        with self.assertRaises(ValueError):
            normalize((3, 3))
        with self.assertRaises(ValueError):
            merge([(1, 2), (5, 5)])

    def test_overlaps(self):
        self.assertTrue(overlaps((1, 4), (3, 6)))
        self.assertTrue(overlaps((3, 6), (1, 4)))
        self.assertFalse(overlaps((1, 3), (3, 6)))
        self.assertFalse(overlaps((3, 6), (1, 3)))
        self.assertTrue(overlaps((1, 10), (4, 5)))
        self.assertTrue(overlaps((4, 5), (1, 10)))
        self.assertFalse(overlaps((1, 2), (5, 6)))

    def test_total_union(self):
        self.assertEqual(total_length([(0, 5), (3, 8)]), 8)
        self.assertEqual(total_length([(0, 2), (2, 4)]), 4)
        self.assertEqual(total_length([(0, 1), (5, 7), (6, 9)]), 5)

    def test_gaps(self):
        self.assertEqual(gaps([(2, 4), (6, 8)], 0, 10), [(0, 2), (4, 6), (8, 10)])
        self.assertEqual(gaps([(0, 10)], 0, 10), [])
        self.assertEqual(gaps([], 3, 7), [(3, 7)])
        self.assertEqual(gaps([(0, 3), (3, 6)], 0, 6), [])
        self.assertEqual(gaps([(-5, 2), (8, 20)], 0, 10), [(2, 8)])
        self.assertEqual(gaps([(0, 2), (9, 12)], 2, 9), [(2, 9)])
        self.assertEqual(gaps([(1, 2)], 0, 3), [(0, 1), (2, 3)])

    def test_contains_point(self):
        iv = [(1, 3), (10, 12)]
        self.assertTrue(contains_point(iv, 1))
        self.assertTrue(contains_point(iv, 2))
        self.assertFalse(contains_point(iv, 3))
        self.assertFalse(contains_point(iv, 0))
        self.assertTrue(contains_point(iv, 11))
        self.assertFalse(contains_point(iv, 12))
        self.assertFalse(contains_point([], 1))
