import unittest

from money import split_cents, apply_percent, discount, format_cents, parse_cents, add_tax


class Basic(unittest.TestCase):
    def test_split(self):
        self.assertEqual(split_cents(10, 3), [4, 3, 3])

    def test_format(self):
        self.assertEqual(format_cents(12345), "123.45")

    def test_parse(self):
        self.assertEqual(parse_cents("12.5"), 1250)
