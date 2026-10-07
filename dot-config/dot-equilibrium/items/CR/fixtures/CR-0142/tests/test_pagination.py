import unittest

from pagination import page_count, page_bounds, paginate, window, next_page, prev_page


class Basic(unittest.TestCase):
    def test_count(self):
        self.assertEqual(page_count(10, 5), 2)
        self.assertEqual(page_count(11, 5), 3)

    def test_paginate_first(self):
        self.assertEqual(paginate(list(range(10)), 1, 4), [0, 1, 2, 3])
