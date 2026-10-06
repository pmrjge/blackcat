import unittest

from csvline import parse_line, quote_field, join_line, column, header_map


class Basic(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_line("a,b,c"), ["a", "b", "c"])

    def test_quoted_sep(self):
        self.assertEqual(parse_line('"a,b",c'), ["a,b", "c"])

    def test_join(self):
        self.assertEqual(join_line(["a", "b"]), "a,b")
