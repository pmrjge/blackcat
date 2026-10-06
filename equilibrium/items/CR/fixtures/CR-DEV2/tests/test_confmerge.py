import unittest

from confmerge import deep_merge, get_path, set_path, flatten, diff_keys, with_defaults


class Basic(unittest.TestCase):
    def test_merge(self):
        self.assertEqual(deep_merge({"a": 1}, {"b": 2}), {"a": 1, "b": 2})

    def test_get(self):
        self.assertEqual(get_path({"a": {"b": 3}}, "a.b"), 3)

    def test_flatten(self):
        self.assertEqual(flatten({"a": {"b": 1}}), {"a.b": 1})
