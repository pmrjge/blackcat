import unittest

from bsearch import lower_bound, upper_bound, index_of, count_in_range, nearest, insert_sorted


class Basic(unittest.TestCase):
    def test_bounds(self):
        a = [1, 2, 2, 3]
        self.assertEqual(lower_bound(a, 2), 1)
        self.assertEqual(upper_bound(a, 2), 3)

    def test_index_of(self):
        self.assertEqual(index_of([1, 3, 5], 3), 1)
        self.assertEqual(index_of([1, 3, 5], 4), -1)
