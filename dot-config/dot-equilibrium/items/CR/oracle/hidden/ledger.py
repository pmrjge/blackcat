import unittest

from ledger import Ledger, InsufficientFunds


def make():
    lg = Ledger()
    lg.open("a")
    lg.open("b", overdraft=50)
    return lg


class Basic(unittest.TestCase):
    def test_deposit(self):
        lg = make()
        lg.deposit("a", 10)
        self.assertEqual(lg.balance("a"), 10)

    def test_withdraw_insufficient(self):
        lg = make()
        with self.assertRaises(InsufficientFunds):
            lg.withdraw("a", 1)


class Deep(unittest.TestCase):
    def test_open_errors(self):
        lg = make()
        with self.assertRaises(ValueError):
            lg.open("a")
        with self.assertRaises(ValueError):
            lg.open("c", overdraft=-1)

    def test_bad_amounts(self):
        lg = make()
        for amt in (0, -5):
            with self.assertRaises(ValueError):
                lg.deposit("a", amt)
            with self.assertRaises(ValueError):
                lg.withdraw("a", amt)

    def test_withdraw_exact(self):
        lg = make()
        lg.deposit("a", 10)
        lg.withdraw("a", 10)
        self.assertEqual(lg.balance("a"), 0)
        with self.assertRaises(InsufficientFunds):
            lg.withdraw("a", 1)

    def test_overdraft_limit(self):
        lg = make()
        lg.withdraw("b", 50)
        self.assertEqual(lg.balance("b"), -50)
        with self.assertRaises(InsufficientFunds):
            lg.withdraw("b", 1)
        self.assertEqual(lg.balance("b"), -50)
        self.assertEqual(lg.overdrawn(), ["b"])
        lg.deposit("b", 50)
        self.assertEqual(lg.overdrawn(), [])

    def test_transfer(self):
        lg = make()
        lg.deposit("a", 100)
        lg.transfer("a", "b", 30)
        self.assertEqual((lg.balance("a"), lg.balance("b")), (70, 30))
        self.assertEqual(lg.total(), 100)
        self.assertEqual(lg.history[-1], ("transfer", "a", "b", 30))

    def test_transfer_atomic(self):
        lg = make()
        lg.deposit("a", 10)
        with self.assertRaises(InsufficientFunds):
            lg.transfer("a", "b", 11)
        self.assertEqual((lg.balance("a"), lg.balance("b")), (10, 0))
        with self.assertRaises(KeyError):
            lg.transfer("a", "nope", 5)
        self.assertEqual(lg.balance("a"), 10)
        with self.assertRaises(ValueError):
            lg.transfer("a", "a", 5)
        self.assertEqual(lg.balance("a"), 10)
        self.assertEqual(lg.history, [("deposit", "a", 10)])

    def test_transfer_to_overdrawn_via_limit(self):
        lg = make()
        lg.transfer("b", "a", 50)
        self.assertEqual((lg.balance("a"), lg.balance("b")), (50, -50))
        self.assertEqual(lg.total(), 0)

    def test_history(self):
        lg = make()
        lg.deposit("a", 5)
        lg.withdraw("a", 2)
        self.assertEqual(lg.history, [("deposit", "a", 5), ("withdraw", "a", 2)])
