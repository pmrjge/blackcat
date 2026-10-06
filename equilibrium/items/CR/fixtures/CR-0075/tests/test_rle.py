import unittest

from rle import runs, encode, decode, longest_run, compress_ratio


class Basic(unittest.TestCase):
    def test_encode(self):
        self.assertEqual(encode("aaabcc"), "3a1b2c")

    def test_decode(self):
        self.assertEqual(decode("3a1b2c"), "aaabcc")
