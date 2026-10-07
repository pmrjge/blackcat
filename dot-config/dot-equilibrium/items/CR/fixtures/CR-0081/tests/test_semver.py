import unittest

from semver import parse, compare, bump, satisfies, latest


class Basic(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse("1.2.3"), (1, 2, 3))

    def test_compare(self):
        self.assertEqual(compare("1.2.3", "1.2.4"), -1)

    def test_bump(self):
        self.assertEqual(bump("1.2.3", "patch"), "1.2.4")
