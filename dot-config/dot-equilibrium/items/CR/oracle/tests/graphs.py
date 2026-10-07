import unittest

from graphs import shortest_path, topo_order, components, reachable, has_cycle


class Basic(unittest.TestCase):
    def test_path(self):
        g = {"a": ["b"], "b": ["c"], "c": []}
        self.assertEqual(shortest_path(g, "a", "c"), ["a", "b", "c"])

    def test_topo(self):
        self.assertEqual(topo_order({1: [2], 2: [3]}), [1, 2, 3])


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_path_shortest(self):
        g = {1: [2, 3], 2: [4], 3: [5], 4: [6], 5: [6], 6: [7], 7: []}
        self.assertEqual(len(shortest_path(g, 1, 7)), 5)
        g2 = {1: [2, 4], 2: [3], 3: [4], 4: []}
        self.assertEqual(shortest_path(g2, 1, 4), [1, 4])

    def test_path_edges(self):
        g = {1: [2], 2: []}
        self.assertEqual(shortest_path(g, 1, 1), [1])
        self.assertIsNone(shortest_path(g, 2, 1))
        self.assertIsNone(shortest_path(g, 1, 9))
        self.assertEqual(shortest_path(g, 1, 2), [1, 2])
        self.assertIsNone(shortest_path({}, 1, 2))
        self.assertEqual(shortest_path({1: [1, 2]}, 1, 2), [1, 2])

    def test_topo_order(self):
        g = {"a": ["c"], "b": ["c"], "c": ["d"], "d": []}
        self.assertEqual(topo_order(g), ["a", "b", "c", "d"])
        self.assertEqual(topo_order({3: [1], 2: [1]}), [2, 3, 1])
        self.assertEqual(topo_order({}), [])
        self.assertEqual(topo_order({5: [], 1: []}), [1, 5])
        self.assertEqual(topo_order({1: [3, 2], 2: [4], 3: [4]}), [1, 2, 3, 4])

    def test_topo_cycle(self):
        for g in ({1: [2], 2: [1]}, {1: [1]}, {1: [2], 2: [3], 3: [2]}):
            with self.assertRaises(ValueError):
                topo_order(g)

    def test_has_cycle(self):
        self.assertTrue(has_cycle({1: [2], 2: [3], 3: [1]}))
        self.assertFalse(has_cycle({1: [2], 2: [3], 3: []}))
        self.assertTrue(has_cycle({7: [7]}))
        self.assertFalse(has_cycle({}))
        self.assertFalse(has_cycle({1: [2, 3], 2: [4], 3: [4]}))

    def test_components(self):
        g = {1: [2], 2: [], 3: [4], 5: []}
        self.assertEqual(components(g), [[1, 2], [3, 4], [5]])
        self.assertEqual(components({}), [])
        self.assertEqual(components({1: [2], 3: [2]}), [[1, 2, 3]])
        self.assertEqual(components({9: [1], 4: [5]}), [[1, 9], [4, 5]])
        self.assertEqual(components({1: [1]}), [[1]])

    def test_reachable(self):
        g = {1: [2], 2: [3], 3: [], 4: [1]}
        self.assertEqual(reachable(g, 1), {1, 2, 3})
        self.assertEqual(reachable(g, 3), {3})
        self.assertEqual(reachable(g, 4), {1, 2, 3, 4})
        self.assertEqual(reachable({}, 9), {9})
        self.assertEqual(reachable({1: [2], 2: [1]}, 1), {1, 2})
