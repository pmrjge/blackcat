import unittest

from inventory import Inventory, OutOfStock


class Basic(unittest.TestCase):
    def test_add_available(self):
        inv = Inventory()
        inv.add("a", 10)
        self.assertEqual(inv.available("a"), 10)

    def test_reserve(self):
        inv = Inventory()
        inv.add("a", 10)
        inv.reserve("a", 4)
        self.assertEqual(inv.available("a"), 6)
        self.assertEqual(inv.on_hand("a"), 10)
