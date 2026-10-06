import unittest

from trie import Trie


def make(*ws):
    t = Trie()
    for w in ws:
        t.insert(w)
    return t


class Basic(unittest.TestCase):
    def test_insert_contains(self):
        t = make("cat", "car")
        self.assertIn("cat", t)
        self.assertNotIn("ca", t)

    def test_len(self):
        self.assertEqual(len(make("a", "b")), 2)
