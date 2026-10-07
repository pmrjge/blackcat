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


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_bad_qty(self):
        inv = Inventory()
        for q in (0, -1):
            with self.assertRaises(ValueError):
                inv.add("a", q)
            with self.assertRaises(ValueError):
                inv.reserve("a", q)

    def test_reserve_exact_and_over(self):
        inv = Inventory()
        inv.add("a", 3)
        inv.reserve("a", 3)
        self.assertEqual(inv.available("a"), 0)
        with self.assertRaises(OutOfStock):
            inv.reserve("a", 1)
        with self.assertRaises(OutOfStock):
            inv.reserve("zzz", 1)
        inv2 = Inventory()
        inv2.add("b", 3)
        with self.assertRaises(OutOfStock):
            inv2.reserve("b", 4)
        self.assertEqual(inv2.available("b"), 3)

    def test_release(self):
        inv = Inventory()
        inv.add("a", 5)
        inv.reserve("a", 5)
        inv.release("a", 2)
        self.assertEqual(inv.available("a"), 2)
        inv.release("a", 3)
        self.assertEqual(inv.available("a"), 5)
        for q in (0, 1, -1):
            with self.assertRaises(ValueError):
                inv.release("a", q)

    def test_ship(self):
        inv = Inventory()
        inv.add("a", 10)
        inv.reserve("a", 4)
        inv.ship("a", 3)
        self.assertEqual(inv.on_hand("a"), 7)
        self.assertEqual(inv.available("a"), 6)
        inv.ship("a", 1)
        self.assertEqual(inv.on_hand("a"), 6)
        self.assertEqual(inv.available("a"), 6)
        with self.assertRaises(ValueError):
            inv.ship("a", 1)
        with self.assertRaises(ValueError):
            inv.ship("a", 0)
        self.assertEqual(inv.total_units(), 6)

    def test_ship_more_than_reserved(self):
        inv = Inventory()
        inv.add("a", 10)
        inv.reserve("a", 2)
        with self.assertRaises(ValueError):
            inv.ship("a", 3)
        self.assertEqual(inv.on_hand("a"), 10)

    def test_low_stock(self):
        inv = Inventory(low_threshold=5)
        inv.add("c", 5)
        inv.add("b", 4)
        inv.add("a", 9)
        inv.reserve("a", 5)
        self.assertEqual(inv.low_stock(), ["a", "b"])
        inv.add("b", 1)
        self.assertEqual(inv.low_stock(), ["a"])
        self.assertEqual(Inventory().low_stock(), [])
        inv3 = Inventory(low_threshold=0)
        inv3.add("x", 1)
        self.assertEqual(inv3.low_stock(), [])

    def test_totals(self):
        inv = Inventory()
        self.assertEqual(inv.total_units(), 0)
        inv.add("a", 2)
        inv.add("a", 3)
        inv.add("b", 4)
        self.assertEqual(inv.total_units(), 9)
        self.assertEqual(inv.on_hand("a"), 5)
        self.assertEqual(inv.on_hand("none"), 0)
