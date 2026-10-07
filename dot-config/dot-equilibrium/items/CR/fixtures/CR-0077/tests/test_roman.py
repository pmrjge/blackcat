import unittest

from roman import to_roman, from_roman, is_valid, add_roman


class Basic(unittest.TestCase):
    def test_to(self):
        self.assertEqual(to_roman(14), "XIV")
        self.assertEqual(to_roman(1994), "MCMXCIV")

    def test_from(self):
        self.assertEqual(from_roman("XLII"), 42)
