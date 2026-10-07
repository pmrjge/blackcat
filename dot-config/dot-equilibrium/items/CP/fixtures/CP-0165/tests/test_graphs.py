import unittest

from graphs import shortest_path, topo_order, components, reachable, has_cycle


class Basic(unittest.TestCase):
    def test_path(self):
        g = {"a": ["b"], "b": ["c"], "c": []}
        self.assertEqual(shortest_path(g, "a", "c"), ["a", "b", "c"])

    def test_topo(self):
        self.assertEqual(topo_order({1: [2], 2: [3]}), [1, 2, 3])
