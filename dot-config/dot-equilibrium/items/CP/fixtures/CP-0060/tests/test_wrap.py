import unittest

from wrap import wrap, center, justify, indent


class Basic(unittest.TestCase):
    def test_wrap(self):
        self.assertEqual(wrap("the quick brown fox", 9), ["the quick", "brown fox"])

    def test_center(self):
        self.assertEqual(center("ab", 6), "  ab  ")
