import unittest

from csvline import parse_line, quote_field, join_line, column, header_map


class Basic(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_line("a,b,c"), ["a", "b", "c"])

    def test_quoted_sep(self):
        self.assertEqual(parse_line('"a,b",c'), ["a,b", "c"])

    def test_join(self):
        self.assertEqual(join_line(["a", "b"]), "a,b")


class Deep(unittest.TestCase):
    def test_empty_fields(self):
        self.assertEqual(parse_line(""), [""])
        self.assertEqual(parse_line(","), ["", ""])
        self.assertEqual(parse_line("a,,b,"), ["a", "", "b", ""])
        self.assertEqual(parse_line('""'), [""])
        self.assertEqual(parse_line('a,"",b'), ["a", "", "b"])

    def test_escaped_quotes(self):
        self.assertEqual(parse_line('"say ""hi""",x'), ['say "hi"', "x"])
        self.assertEqual(parse_line('""""'), ['"'])
        self.assertEqual(parse_line('"a""",b'), ['a"', "b"])

    def test_other_separator(self):
        self.assertEqual(parse_line("a;b,c;d", sep=";"), ["a", "b,c", "d"])
        self.assertEqual(parse_line('"a;b";c', sep=";"), ["a;b", "c"])
        self.assertEqual(parse_line("a\tb", sep="\t"), ["a", "b"])

    def test_unterminated(self):
        for bad in ['"abc', 'a,"b', '"a""']:
            with self.assertRaises(ValueError):
                parse_line(bad)

    def test_quote_field(self):
        self.assertEqual(quote_field("plain"), "plain")
        self.assertEqual(quote_field("a,b"), '"a,b"')
        self.assertEqual(quote_field('say "x"'), '"say ""x"""')
        self.assertEqual(quote_field("l1\nl2"), '"l1\nl2"')
        self.assertEqual(quote_field("a;b"), "a;b")
        self.assertEqual(quote_field("a;b", sep=";"), '"a;b"')
        self.assertEqual(quote_field(""), "")

    def test_roundtrip(self):
        rows = [["a", "b"], ["x,y", 'q"r'], ["", ""], ["one"], [""]]
        for row in rows:
            self.assertEqual(parse_line(join_line(row)), row)
        self.assertEqual(parse_line(join_line(["a;b", "c"], ";"), ";"), ["a;b", "c"])

    def test_column(self):
        lines = ["a,1", "b,2", '"c,d",3']
        self.assertEqual(column(lines, 0), ["a", "b", "c,d"])
        self.assertEqual(column(lines, 1), ["1", "2", "3"])
        self.assertEqual(column([], 0), [])
        with self.assertRaises(IndexError):
            column(["a"], 1)

    def test_header_map(self):
        self.assertEqual(header_map("id,name,age"), {"id": 0, "name": 1, "age": 2})
        self.assertEqual(header_map('"a,b",c'), {"a,b": 0, "c": 1})
        with self.assertRaises(ValueError):
            header_map("a,b,a")
