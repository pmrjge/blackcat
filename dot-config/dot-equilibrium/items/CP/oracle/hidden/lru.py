import unittest

from lru import LRUCache


class Basic(unittest.TestCase):
    def test_put_get(self):
        c = LRUCache(2)
        c.put("a", 1)
        self.assertEqual(c.get("a"), 1)
        self.assertEqual(c.get("zz", 7), 7)

    def test_evict_oldest(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        self.assertEqual(c.put("c", 3), "a")


class Deep(unittest.TestCase):
    def test_capacity_validation(self):
        with self.assertRaises(ValueError):
            LRUCache(0)

    def test_get_refreshes(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        c.get("a")
        self.assertEqual(c.put("c", 3), "b")
        self.assertIn("a", c)
        self.assertNotIn("b", c)

    def test_update_refreshes_without_evicting(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        self.assertIsNone(c.put("a", 10))
        self.assertEqual(len(c), 2)
        self.assertEqual(c.put("c", 3), "b")
        self.assertEqual(c.get("a"), 10)

    def test_no_eviction_below_capacity(self):
        c = LRUCache(3)
        self.assertIsNone(c.put(1, 1))
        self.assertIsNone(c.put(2, 2))
        self.assertIsNone(c.put(3, 3))
        self.assertEqual(len(c), 3)
        self.assertEqual(c.put(4, 4), 1)
        self.assertEqual(len(c), 3)

    def test_counters(self):
        c = LRUCache(2)
        self.assertEqual(c.hit_ratio(), 0.0)
        c.put("a", 1)
        c.get("a")
        c.get("b")
        c.get("a")
        self.assertEqual((c.hits, c.misses), (2, 1))
        self.assertAlmostEqual(c.hit_ratio(), 2 / 3)
        c.get("q")
        self.assertEqual(c.hit_ratio(), 0.5)

    def test_missing_get_does_not_touch(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.get("nope")
        self.assertEqual(c.keys_by_recency(), ["a"])

    def test_delete(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        self.assertTrue(c.delete("a"))
        self.assertFalse(c.delete("a"))
        self.assertEqual(len(c), 1)
        self.assertIsNone(c.put("c", 3))
        self.assertEqual(c.keys_by_recency(), ["c", "b"])

    def test_recency_order(self):
        c = LRUCache(3)
        for k in "abc":
            c.put(k, k)
        c.get("a")
        self.assertEqual(c.keys_by_recency(), ["a", "c", "b"])
        c.put("b", 0)
        self.assertEqual(c.keys_by_recency(), ["b", "a", "c"])
