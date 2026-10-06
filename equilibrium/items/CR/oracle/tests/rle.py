import unittest

from rle import runs, encode, decode, longest_run, compress_ratio


class Basic(unittest.TestCase):
    def test_encode(self):
        self.assertEqual(encode("aaabcc"), "3a1b2c")

    def test_decode(self):
        self.assertEqual(decode("3a1b2c"), "aaabcc")


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_runs(self):
        self.assertEqual(runs([]), [])
        self.assertEqual(runs("a"), [("a", 1)])
        self.assertEqual(runs("aab"), [("a", 2), ("b", 1)])
        self.assertEqual(runs([1, 1, 2, 2, 2, 1]), [(1, 2), (2, 3), (1, 1)])
        self.assertEqual(runs("abab"), [("a", 1), ("b", 1), ("a", 1), ("b", 1)])

    def test_encode_edges(self):
        self.assertEqual(encode(""), "")
        self.assertEqual(encode("x" * 12), "12x")
        self.assertEqual(encode("ab"), "1a1b")
        with self.assertRaises(ValueError):
            encode("a1")

    def test_decode_edges(self):
        self.assertEqual(decode(""), "")
        self.assertEqual(decode("12x"), "x" * 12)
        self.assertEqual(decode("10a2b"), "a" * 10 + "bb")
        for bad in ["a", "3", "2a3", "0a", "a2", "10"]:
            with self.assertRaises(ValueError):
                decode(bad)

    def test_roundtrip(self):
        for s in ["", "a", "aabbbc", "zzzzzzzzzzzzzz", "abcabc"]:
            self.assertEqual(decode(encode(s)), s)

    def test_longest(self):
        self.assertIsNone(longest_run(""))
        self.assertEqual(longest_run("aabbbcc"), ("b", 3))
        self.assertEqual(longest_run("aabb"), ("a", 2))
        self.assertEqual(longest_run("abccc"), ("c", 3))
        self.assertEqual(longest_run([5]), (5, 1))

    def test_ratio(self):
        self.assertEqual(compress_ratio(""), 1.0)
        self.assertEqual(compress_ratio("aaaa"), 0.5)
        self.assertEqual(compress_ratio("ab"), 2.0)
