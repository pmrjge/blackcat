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


class Deep(unittest.TestCase):
    def test_bounds_edges(self):
        a = [1, 2, 2, 2, 5]
        self.assertEqual(lower_bound(a, 0), 0)
        self.assertEqual(lower_bound(a, 1), 0)
        self.assertEqual(lower_bound(a, 3), 4)
        self.assertEqual(lower_bound(a, 5), 4)
        self.assertEqual(lower_bound(a, 6), 5)
        self.assertEqual(upper_bound(a, 0), 0)
        self.assertEqual(upper_bound(a, 1), 1)
        self.assertEqual(upper_bound(a, 4), 4)
        self.assertEqual(upper_bound(a, 5), 5)
        self.assertEqual(lower_bound([], 1), 0)
        self.assertEqual(upper_bound([], 1), 0)

    def test_bounds_brute(self):
        a = [0, 0, 1, 3, 3, 3, 4, 8, 8, 9, 12]
        for x in range(-1, 14):
            self.assertEqual(lower_bound(a, x), sum(1 for v in a if v < x))
            self.assertEqual(upper_bound(a, x), sum(1 for v in a if v <= x))

    def test_index_of(self):
        a = [1, 2, 2, 2, 5]
        self.assertEqual(index_of(a, 2), 1)
        self.assertEqual(index_of(a, 1), 0)
        self.assertEqual(index_of(a, 5), 4)
        self.assertEqual(index_of(a, 0), -1)
        self.assertEqual(index_of(a, 6), -1)
        self.assertEqual(index_of([], 1), -1)

    def test_count(self):
        a = [1, 2, 2, 3, 5, 5, 8]
        self.assertEqual(count_in_range(a, 2, 5), 5)
        self.assertEqual(count_in_range(a, 2, 2), 2)
        self.assertEqual(count_in_range(a, 4, 4), 0)
        self.assertEqual(count_in_range(a, 6, 2), 0)
        self.assertEqual(count_in_range(a, 0, 100), 7)
        self.assertEqual(count_in_range(a, 8, 9), 1)
        self.assertEqual(count_in_range(a, 0, 1), 1)

    def test_nearest(self):
        a = [1, 4, 9]
        self.assertEqual(nearest(a, 0), 1)
        self.assertEqual(nearest(a, 10), 9)
        self.assertEqual(nearest(a, 4), 4)
        self.assertEqual(nearest(a, 2), 1)
        self.assertEqual(nearest(a, 3), 4)
        self.assertEqual(nearest([2, 4], 3), 2)
        self.assertEqual(nearest(a, 7), 9)
        self.assertEqual(nearest(a, 6), 4)
        self.assertEqual(nearest([7], 100), 7)
        with self.assertRaises(ValueError):
            nearest([], 1)

    def test_insert_sorted(self):
        a = [1, 3, 3, 7]
        self.assertEqual(insert_sorted(a, 3), 3)
        self.assertEqual(a, [1, 3, 3, 3, 7])
        self.assertEqual(insert_sorted(a, 0), 0)
        self.assertEqual(insert_sorted(a, 9), 6)
        self.assertEqual(a, [0, 1, 3, 3, 3, 7, 9])
        b = []
        self.assertEqual(insert_sorted(b, 1), 0)
