import unittest

from validate import parse_bool, parse_port, check_username, check_email, collect_errors, clamp


class Basic(unittest.TestCase):
    def test_bool(self):
        self.assertTrue(parse_bool("Yes"))
        self.assertFalse(parse_bool("off"))

    def test_port(self):
        self.assertEqual(parse_port("8080"), 8080)

    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 3), 3)
