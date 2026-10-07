import unittest

from wrap import wrap, center, justify, indent


class Basic(unittest.TestCase):
    def test_wrap(self):
        self.assertEqual(wrap("the quick brown fox", 9), ["the quick", "brown fox"])

    def test_center(self):
        self.assertEqual(center("ab", 6), "  ab  ")


class Deep(unittest.TestCase):
    def test_wrap_boundary(self):
        self.assertEqual(wrap("aa bb cc", 5), ["aa bb", "cc"])
        self.assertEqual(wrap("aa bb cc", 8), ["aa bb cc"])
        self.assertEqual(wrap("aa bb cc", 7), ["aa bb", "cc"])
        self.assertEqual(wrap("aaa bbb", 3), ["aaa", "bbb"])

    def test_wrap_long_word(self):
        self.assertEqual(wrap("a verylongword b", 4), ["a", "verylongword", "b"])
        self.assertEqual(wrap("verylongword", 3), ["verylongword"])

    def test_wrap_misc(self):
        self.assertEqual(wrap("", 5), [])
        self.assertEqual(wrap("   ", 5), [])
        self.assertEqual(wrap("a   b\n c", 10), ["a b c"])
        self.assertEqual(wrap("x", 1), ["x"])
        with self.assertRaises(ValueError):
            wrap("x", 0)
        for line in wrap("lorem ipsum dolor sit amet consectetur", 12):
            self.assertLessEqual(len(line), 12)

    def test_center(self):
        self.assertEqual(center("ab", 5), " ab  ")
        self.assertEqual(center("abc", 8), "  abc   ")
        self.assertEqual(center("abc", 3), "abc")
        self.assertEqual(center("abcd", 2), "abcd")
        self.assertEqual(center("", 3), "   ")
        self.assertEqual(center("a", 2), "a ")

    def test_justify(self):
        self.assertEqual(justify("a b c", 9), "a   b   c")
        self.assertEqual(justify("a b c", 10), "a    b   c")
        self.assertEqual(justify("ab cd", 7), "ab   cd")
        self.assertEqual(justify("solo", 10), "solo")
        self.assertEqual(justify("a b", 3), "a b")
        self.assertEqual(justify("aa bb", 3), "aa bb")
        self.assertEqual(len(justify("one two three four", 30)), 30)
        self.assertEqual(justify("a b c d", 11), "a   b  c  d")

    def test_indent(self):
        self.assertEqual(indent("a\n\nb", "> "), "> a\n\n> b")
        self.assertEqual(indent("", "> "), "")
        self.assertEqual(indent("x", "  "), "  x")
