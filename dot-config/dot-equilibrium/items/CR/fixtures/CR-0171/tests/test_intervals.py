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
