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


class Deep(unittest.TestCase):
    def test_insert_return(self):
        t = Trie()
        self.assertTrue(t.insert("go"))
        self.assertFalse(t.insert("go"))
        self.assertTrue(t.insert("gopher"))
        self.assertEqual(len(t), 2)
        self.assertTrue(t.insert(""))
        self.assertIn("", t)
        self.assertEqual(len(t), 3)

    def test_contains_prefix_not_word(self):
        t = make("apple")
        self.assertNotIn("app", t)
        self.assertNotIn("apples", t)
        self.assertNotIn("", t)
        self.assertNotIn("b", t)

    def test_starts_with(self):
        t = make("app", "apple", "apply", "apt", "bat")
        self.assertEqual(t.starts_with("app"), 3)
        self.assertEqual(t.starts_with("ap"), 4)
        self.assertEqual(t.starts_with(""), 5)
        self.assertEqual(t.starts_with("z"), 0)
        self.assertEqual(t.starts_with("apple"), 1)
        self.assertEqual(t.starts_with("apples"), 0)
        self.assertEqual(t.starts_with("b"), 1)

    def test_words_sorted(self):
        t = make("banana", "band", "ban", "apple", "b")
        self.assertEqual(t.words(), ["apple", "b", "ban", "banana", "band"])
        self.assertEqual(t.words("ban"), ["ban", "banana", "band"])
        self.assertEqual(t.words("x"), [])
        self.assertEqual(t.words("band"), ["band"])
        self.assertEqual(Trie().words(), [])

    def test_remove(self):
        t = make("to", "tom", "tone")
        self.assertTrue(t.remove("to"))
        self.assertFalse(t.remove("to"))
        self.assertNotIn("to", t)
        self.assertIn("tom", t)
        self.assertEqual(len(t), 2)
        self.assertFalse(t.remove("t"))
        self.assertFalse(t.remove("zzz"))
        self.assertEqual(t.starts_with("to"), 2)
        self.assertEqual(len(t), 2)

    def test_lcp(self):
        self.assertEqual(make("flower", "flow", "flight").longest_common_prefix(), "fl")
        self.assertEqual(make("dog", "racecar").longest_common_prefix(), "")
        self.assertEqual(make("same").longest_common_prefix(), "same")
        self.assertEqual(make("ab", "abc").longest_common_prefix(), "ab")
        self.assertEqual(Trie().longest_common_prefix(), "")
        self.assertEqual(make("", "a").longest_common_prefix(), "")
        self.assertEqual(make("interview", "internet", "internal").longest_common_prefix(), "inter")
