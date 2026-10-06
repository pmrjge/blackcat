import unittest

from confmerge import deep_merge, get_path, set_path, flatten, diff_keys, with_defaults


class Basic(unittest.TestCase):
    def test_merge(self):
        self.assertEqual(deep_merge({"a": 1}, {"b": 2}), {"a": 1, "b": 2})

    def test_get(self):
        self.assertEqual(get_path({"a": {"b": 3}}, "a.b"), 3)

    def test_flatten(self):
        self.assertEqual(flatten({"a": {"b": 1}}), {"a.b": 1})


class Deep(unittest.TestCase):
    def test_merge_nested(self):
        a = {"db": {"host": "x", "port": 1}, "debug": False}
        b = {"db": {"port": 2}, "debug": True}
        self.assertEqual(deep_merge(a, b), {"db": {"host": "x", "port": 2}, "debug": True})
        self.assertEqual(deep_merge({"a": {"b": 1}}, {"a": 5}), {"a": 5})
        self.assertEqual(deep_merge({"a": 5}, {"a": {"b": 1}}), {"a": {"b": 1}})
        self.assertEqual(deep_merge({}, {}), {})

    def test_merge_does_not_mutate(self):
        a = {"x": {"y": 1}}
        b = {"x": {"z": 2}}
        out = deep_merge(a, b)
        self.assertEqual(a, {"x": {"y": 1}})
        self.assertEqual(b, {"x": {"z": 2}})
        out["x"]["y"] = 99
        self.assertEqual(a, {"x": {"y": 1}})
        out2 = deep_merge({}, b)
        out2["x"]["z"] = 0
        self.assertEqual(b, {"x": {"z": 2}})

    def test_get_path(self):
        cfg = {"a": {"b": {"c": 1}}, "n": None, "z": 0}
        self.assertEqual(get_path(cfg, "a.b.c"), 1)
        self.assertEqual(get_path(cfg, "a.x", "d"), "d")
        self.assertEqual(get_path(cfg, "a.b.c.d", "d"), "d")
        self.assertIsNone(get_path(cfg, "q"))
        self.assertIsNone(get_path(cfg, "n", "d"))
        self.assertEqual(get_path(cfg, "z", 5), 0)
        self.assertEqual(get_path(cfg, "a.b"), {"c": 1})

    def test_set_path(self):
        cfg = {}
        self.assertIs(set_path(cfg, "a.b.c", 1), cfg)
        self.assertEqual(cfg, {"a": {"b": {"c": 1}}})
        set_path(cfg, "a.b.d", 2)
        self.assertEqual(cfg["a"]["b"], {"c": 1, "d": 2})
        set_path(cfg, "top", 3)
        self.assertEqual(cfg["top"], 3)
        with self.assertRaises(ValueError):
            set_path(cfg, "top.sub", 1)

    def test_flatten(self):
        cfg = {"a": {"b": 1, "c": {"d": 2}}, "e": 3, "f": {}}
        self.assertEqual(flatten(cfg), {"a.b": 1, "a.c.d": 2, "e": 3})
        self.assertEqual(flatten({}), {})
        first = flatten({"x": 1})
        second = flatten({"y": 2})
        self.assertEqual(first, {"x": 1})
        self.assertEqual(second, {"y": 2})

    def test_diff_keys(self):
        a = {"a": 1, "b": {"c": 2, "d": 3}}
        b = {"a": 1, "b": {"c": 5}, "e": 0}
        self.assertEqual(diff_keys(a, b), ["b.c", "b.d", "e"])
        self.assertEqual(diff_keys(a, a), [])
        self.assertEqual(diff_keys({"x": None}, {}), ["x"])
        self.assertEqual(diff_keys({}, {}), [])

    def test_with_defaults(self):
        d = {"a": {"b": 1, "c": 2}}
        self.assertEqual(with_defaults({"a": {"c": 9}}, d), {"a": {"b": 1, "c": 9}})
        self.assertEqual(with_defaults({"q": 1}), {"q": 1})
        self.assertEqual(with_defaults({"q": 1}, None), {"q": 1})
        self.assertEqual(d, {"a": {"b": 1, "c": 2}})
