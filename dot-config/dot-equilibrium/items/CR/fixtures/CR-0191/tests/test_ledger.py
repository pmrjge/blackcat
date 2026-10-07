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
