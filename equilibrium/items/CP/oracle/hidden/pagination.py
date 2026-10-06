import unittest

from pagination import page_count, page_bounds, paginate, window, next_page, prev_page


class Basic(unittest.TestCase):
    def test_count(self):
        self.assertEqual(page_count(10, 5), 2)
        self.assertEqual(page_count(11, 5), 3)

    def test_paginate_first(self):
        self.assertEqual(paginate(list(range(10)), 1, 4), [0, 1, 2, 3])


class Deep(unittest.TestCase):
    def test_count_edges(self):
        self.assertEqual(page_count(0, 5), 0)
        self.assertEqual(page_count(1, 5), 1)
        self.assertEqual(page_count(5, 5), 1)
        self.assertEqual(page_count(6, 5), 2)
        self.assertEqual(page_count(7, 1), 7)
        with self.assertRaises(ValueError):
            page_count(3, 0)
        with self.assertRaises(ValueError):
            page_count(-1, 3)

    def test_bounds(self):
        self.assertEqual(page_bounds(10, 1, 4), (0, 4))
        self.assertEqual(page_bounds(10, 2, 4), (4, 8))
        self.assertEqual(page_bounds(10, 3, 4), (8, 10))
        self.assertEqual(page_bounds(8, 2, 4), (4, 8))
        self.assertEqual(page_bounds(0, 1, 4), (0, 0))

    def test_bounds_errors(self):
        for args in [(10, 0, 4), (10, 4, 4), (10, -1, 4), (0, 2, 4)]:
            with self.assertRaises(IndexError):
                page_bounds(*args)
        with self.assertRaises(ValueError):
            page_bounds(10, 1, 0)

    def test_paginate(self):
        data = list(range(10))
        self.assertEqual(paginate(data, 3, 4), [8, 9])
        self.assertEqual(paginate(data, 2, 4), [4, 5, 6, 7])
        self.assertEqual(paginate([], 1, 3), [])
        self.assertEqual(paginate(tuple(data), 1, 10), data)
        self.assertEqual(paginate(data, 10, 1), [9])
        self.assertEqual(paginate(data, 1, 1), [0])

    def test_window(self):
        self.assertEqual(window(5, 10), [3, 4, 5, 6, 7])
        self.assertEqual(window(1, 10), [1, 2, 3])
        self.assertEqual(window(10, 10), [8, 9, 10])
        self.assertEqual(window(2, 3), [1, 2, 3])
        self.assertEqual(window(1, 1), [1])
        self.assertEqual(window(5, 10, radius=1), [4, 5, 6])
        self.assertEqual(window(5, 10, radius=0), [5])
        self.assertEqual(window(9, 10), [7, 8, 9, 10])

    def test_next_prev(self):
        self.assertEqual(next_page(1, 3), 2)
        self.assertEqual(next_page(2, 3), 3)
        self.assertIsNone(next_page(3, 3))
        self.assertIsNone(next_page(1, 1))
        self.assertIsNone(prev_page(1))
        self.assertEqual(prev_page(2), 1)
        self.assertEqual(prev_page(5), 4)
