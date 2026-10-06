import unittest

from roman import to_roman, from_roman, is_valid, add_roman


class Basic(unittest.TestCase):
    def test_to(self):
        self.assertEqual(to_roman(14), "XIV")
        self.assertEqual(to_roman(1994), "MCMXCIV")

    def test_from(self):
        self.assertEqual(from_roman("XLII"), 42)


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_to_edges(self):
        self.assertEqual(to_roman(1), "I")
        self.assertEqual(to_roman(4), "IV")
        self.assertEqual(to_roman(9), "IX")
        self.assertEqual(to_roman(40), "XL")
        self.assertEqual(to_roman(90), "XC")
        self.assertEqual(to_roman(400), "CD")
        self.assertEqual(to_roman(900), "CM")
        self.assertEqual(to_roman(3999), "MMMCMXCIX")
        self.assertEqual(to_roman(3888), "MMMDCCCLXXXVIII")
        self.assertEqual(to_roman(2024), "MMXXIV")
        for bad in (0, -3, 4000):
            with self.assertRaises(ValueError):
                to_roman(bad)

    def test_from_edges(self):
        self.assertEqual(from_roman("I"), 1)
        self.assertEqual(from_roman("IV"), 4)
        self.assertEqual(from_roman("IX"), 9)
        self.assertEqual(from_roman("XC"), 90)
        self.assertEqual(from_roman("CDXLIV"), 444)
        self.assertEqual(from_roman("MMMCMXCIX"), 3999)
        self.assertEqual(from_roman("MMXXIV"), 2024)

    def test_from_invalid(self):
        for bad in ["", "IIII", "VX", "IC", "ABC", "iv", "MMMM", "XXXX", "IIV", "VV"]:
            with self.assertRaises(ValueError):
                from_roman(bad)

    def test_roundtrip(self):
        for n in range(1, 4000, 7):
            self.assertEqual(from_roman(to_roman(n)), n)

    def test_is_valid(self):
        self.assertTrue(is_valid("XIV"))
        self.assertFalse(is_valid("IXI"))
        self.assertFalse(is_valid(""))

    def test_add(self):
        self.assertEqual(add_roman("X", "V"), "XV")
        self.assertEqual(add_roman("IX", "I"), "X")
        self.assertEqual(add_roman("MMM", "CMXCIX"), "MMMCMXCIX")
        with self.assertRaises(ValueError):
            add_roman("MMM", "M")
