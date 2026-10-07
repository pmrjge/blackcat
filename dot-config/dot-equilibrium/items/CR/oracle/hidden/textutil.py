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


class Deep(unittest.TestCase):
    def test_split_edges(self):
        self.assertEqual(split_words(""), [])
        self.assertEqual(split_words("   "), [])
        self.assertEqual(split_words("  x "), ["x"])
        self.assertEqual(split_words("ab\ncd"), ["ab", "cd"])
        self.assertEqual(split_words("one"), ["one"])

    def test_snake_cases(self):
        self.assertEqual(camel_to_snake("parseHTTPResponse"), "parse_http_response")
        self.assertEqual(camel_to_snake("userID"), "user_id")
        self.assertEqual(camel_to_snake("Name"), "name")
        self.assertEqual(camel_to_snake("already_snake"), "already_snake")
        self.assertEqual(camel_to_snake("aB"), "a_b")
        self.assertEqual(camel_to_snake("ABC"), "abc")
        self.assertEqual(camel_to_snake("getHTTP"), "get_http")
        self.assertEqual(camel_to_snake("x"), "x")
        self.assertEqual(camel_to_snake("fooBarBaz"), "foo_bar_baz")

    def test_truncate_edges(self):
        self.assertEqual(truncate("12345", 5), "12345")
        self.assertEqual(truncate("123456", 5), "12...")
        self.assertEqual(truncate("123456", 3), "...")
        self.assertEqual(truncate("abcdefgh", 6, ellipsis="~"), "abcde~")
        self.assertEqual(len(truncate("x" * 50, 20)), 20)
        self.assertEqual(truncate("", 3), "")
        with self.assertRaises(ValueError):
            truncate("hello world", 2)
        self.assertEqual(truncate("ab", 3, ellipsis="..."), "ab")

    def test_count_words(self):
        self.assertEqual(count_words("The cat. the CAT, a dog!"), {"the": 2, "cat": 2, "a": 1, "dog": 1})
        self.assertEqual(count_words("..."), {})
        self.assertEqual(count_words("(hi) 'hi'"), {"hi": 2})
        self.assertEqual(count_words(""), {})

    def test_title_case(self):
        self.assertEqual(title_case("the lord of the rings"), "The Lord of the Rings")
        self.assertEqual(title_case("a tale in the city"), "A Tale in the City")
        self.assertEqual(title_case("HELLO WORLD"), "Hello World")
        self.assertEqual(title_case("war and peace"), "War and Peace")
        self.assertEqual(title_case("x"), "X")
        self.assertEqual(title_case(""), "")
