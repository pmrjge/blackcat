import unittest

from textutil import split_words, camel_to_snake, truncate, count_words, title_case


class Basic(unittest.TestCase):
    def test_split(self):
        self.assertEqual(split_words("a  b\tc"), ["a", "b", "c"])

    def test_snake(self):
        self.assertEqual(camel_to_snake("fooBar"), "foo_bar")

    def test_truncate(self):
        self.assertEqual(truncate("hello", 10), "hello")
        self.assertEqual(truncate("hello world", 8), "hello...")
