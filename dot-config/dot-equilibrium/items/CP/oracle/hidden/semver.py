import unittest

from semver import parse, compare, bump, satisfies, latest


class Basic(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse("1.2.3"), (1, 2, 3))

    def test_compare(self):
        self.assertEqual(compare("1.2.3", "1.2.4"), -1)

    def test_bump(self):
        self.assertEqual(bump("1.2.3", "patch"), "1.2.4")


class Deep(unittest.TestCase):
    def test_parse_forms(self):
        self.assertEqual(parse("v10.0.7"), (10, 0, 7))
        for bad in ["1.2", "1.2.3.4", "a.b.c", "1.2.x", "", "1..3", "-1.0.0", "v"]:
            with self.assertRaises(ValueError):
                parse(bad)

    def test_numeric_order(self):
        self.assertEqual(compare("1.10.0", "1.9.0"), 1)
        self.assertEqual(compare("2.0.0", "10.0.0"), -1)
        self.assertEqual(compare("1.2.3", "1.2.3"), 0)
        self.assertEqual(compare("1.2.10", "1.2.9"), 1)
        self.assertEqual(compare("0.0.1", "0.0.0"), 1)
        self.assertEqual(compare("1.0.0", "0.9.9"), 1)
        self.assertEqual(compare("v1.0.0", "1.0.0"), 0)

    def test_bump(self):
        self.assertEqual(bump("1.2.3", "minor"), "1.3.0")
        self.assertEqual(bump("1.2.3", "major"), "2.0.0")
        self.assertEqual(bump("0.0.0", "patch"), "0.0.1")
        self.assertEqual(bump("9.9.9", "major"), "10.0.0")
        self.assertEqual(bump("v1.9.9", "minor"), "1.10.0")
        with self.assertRaises(ValueError):
            bump("1.0.0", "build")

    def test_satisfies(self):
        self.assertTrue(satisfies("1.2.0", ">=1.2.0,<2.0.0"))
        self.assertFalse(satisfies("2.0.0", ">=1.2.0,<2.0.0"))
        self.assertFalse(satisfies("1.1.9", ">=1.2.0"))
        self.assertTrue(satisfies("1.9.9", "<=1.9.9"))
        self.assertFalse(satisfies("1.9.10", "<=1.9.9"))
        self.assertTrue(satisfies("1.0.0", "==1.0.0"))
        self.assertFalse(satisfies("1.0.1", "==1.0.0"))
        self.assertFalse(satisfies("1.0.0", ">1.0.0"))
        self.assertTrue(satisfies("1.0.1", ">1.0.0"))
        self.assertTrue(satisfies("3.0.0", ""))
        self.assertTrue(satisfies("1.5.0", ">= 1.2.0 , < 2.0.0"))
        self.assertFalse(satisfies("1.5.0", ">1.2.0,<1.5.0"))
        with self.assertRaises(ValueError):
            satisfies("1.0.0", "~1.0.0")

    def test_latest(self):
        vs = ["1.0.0", "1.10.0", "1.9.0", "2.0.0"]
        self.assertEqual(latest(vs), "2.0.0")
        self.assertEqual(latest(vs, "<2.0.0"), "1.10.0")
        self.assertIsNone(latest(vs, ">=3.0.0"))
        self.assertIsNone(latest([]))
        self.assertEqual(latest(["1.0.0"], "==1.0.0"), "1.0.0")
