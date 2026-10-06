import unittest

from money import split_cents, apply_percent, discount, format_cents, parse_cents, add_tax


class Basic(unittest.TestCase):
    def test_split(self):
        self.assertEqual(split_cents(10, 3), [4, 3, 3])

    def test_format(self):
        self.assertEqual(format_cents(12345), "123.45")

    def test_parse(self):
        self.assertEqual(parse_cents("12.5"), 1250)


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_split_more(self):
        self.assertEqual(split_cents(9, 3), [3, 3, 3])
        self.assertEqual(split_cents(2, 5), [1, 1, 0, 0, 0])
        self.assertEqual(split_cents(0, 2), [0, 0])
        self.assertEqual(split_cents(7, 1), [7])
        self.assertEqual(sum(split_cents(101, 7)), 101)
        self.assertEqual(split_cents(101, 7), [15, 15, 15, 14, 14, 14, 14])
        with self.assertRaises(ValueError):
            split_cents(5, 0)
        with self.assertRaises(ValueError):
            split_cents(-1, 2)

    def test_percent_rounding(self):
        self.assertEqual(apply_percent(1000, 10), 100)
        self.assertEqual(apply_percent(5, 50), 3)
        self.assertEqual(apply_percent(1, 49), 0)
        self.assertEqual(apply_percent(1, 50), 1)
        self.assertEqual(apply_percent(333, 100), 333)
        self.assertEqual(apply_percent(333, 0), 0)
        self.assertEqual(apply_percent(199, 15), 30)
        with self.assertRaises(ValueError):
            apply_percent(100, 101)
        with self.assertRaises(ValueError):
            apply_percent(100, -1)

    def test_discount(self):
        self.assertEqual(discount(1000, 25), 750)
        self.assertEqual(discount(999, 50), 499)
        self.assertEqual(discount(100, 0), 100)
        self.assertEqual(discount(100, 100), 0)

    def test_format(self):
        self.assertEqual(format_cents(0), "0.00")
        self.assertEqual(format_cents(5), "0.05")
        self.assertEqual(format_cents(-5), "-0.05")
        self.assertEqual(format_cents(100), "1.00")
        self.assertEqual(format_cents(-12345), "-123.45")
        self.assertEqual(format_cents(99), "0.99")
        self.assertEqual(format_cents(1234567), "12345.67")

    def test_parse(self):
        self.assertEqual(parse_cents("123.45"), 12345)
        self.assertEqual(parse_cents("7"), 700)
        self.assertEqual(parse_cents(" 7.5 "), 750)
        self.assertEqual(parse_cents("-0.05"), -5)
        self.assertEqual(parse_cents(".5"), 50)
        self.assertEqual(parse_cents("0.99"), 99)
        self.assertEqual(parse_cents("10.01"), 1001)
        for bad in ["", "abc", "1.234", "1.2.3", "-", ".", "1,5"]:
            with self.assertRaises(ValueError):
                parse_cents(bad)

    def test_roundtrip(self):
        for c in [0, 1, 99, 100, 101, 12345, -1, -250]:
            self.assertEqual(parse_cents(format_cents(c)), c)

    def test_tax(self):
        self.assertEqual(add_tax(1000, 2300), 1230)
        self.assertEqual(add_tax(1000, 0), 1000)
        self.assertEqual(add_tax(1, 5000), 2)
        self.assertEqual(add_tax(1, 4999), 1)
        self.assertEqual(add_tax(333, 1000), 366)
